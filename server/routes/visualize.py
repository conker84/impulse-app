"""Visualize endpoints — /api/visualize/*

Query histogram (1D & 2D) and statistics results from Unity Catalog
gold layer tables for interactive visualization.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.mcp_tools import execute_sql
from server.schema_profile import get_profile

logger = logging.getLogger(__name__)


def _clean(val: str | None) -> str:
    return "" if not val or val == "NULL" else val

router = APIRouter(prefix="/api/visualize", tags=["visualize"])

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _validate_id(value: str, name: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise HTTPException(400, f"Invalid {name}: must be alphanumeric/underscores only")
    return value


def _table(catalog: str, schema: str, prefix: str, suffix: str) -> str:
    return f"{catalog}.{schema}.{prefix}_{suffix}"


def _get_user_token(request: Request) -> str | None:
    return request.headers.get("X-Forwarded-Access-Token")


@router.get("/histograms")
async def list_histograms(
    catalog: str, schema: str, prefix: str, request: Request,
):
    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    _validate_id(prefix, "prefix")
    token = _get_user_token(request)
    tbl = _table(catalog, schema, prefix, "histogram_dimension")

    try:
        result = execute_sql(
            f"SELECT visual_id, name, agg_type, description, bins_unit, values_unit, page_number "
            f"FROM {tbl} ORDER BY page_number, visual_id",
            user_token=token,
        )
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
            raise HTTPException(
                404,
                "Report results not found in Unity Catalog. Deploy and run the report first.",
            )
        raise

    histograms = []
    for row in result.get("rows", []):
        histograms.append({
            "visual_id": int(row[0]) if row[0] else 0,
            "name": _clean(row[1]),
            "type": _clean(row[2]),
            "description": _clean(row[3]),
            "bins_unit": _clean(row[4]),
            "values_unit": _clean(row[5]),
        })
    return {"histograms": histograms}


class HistogramDataRequest(BaseModel):
    catalog: str
    schema_name: str
    prefix: str
    histogram_names: list[str]


@router.post("/histogram-data")
async def get_histogram_data(body: HistogramDataRequest, request: Request):
    _validate_id(body.catalog, "catalog")
    _validate_id(body.schema_name, "schema")
    _validate_id(body.prefix, "prefix")
    for name in body.histogram_names:
        _validate_id(name, "histogram_name")
    token = _get_user_token(request)

    fact_tbl = _table(body.catalog, body.schema_name, body.prefix, "histogram_fact")
    dim_tbl = _table(body.catalog, body.schema_name, body.prefix, "histogram_dimension")

    dim_result = _fetch_dimension_metadata(dim_tbl, body.histogram_names, token)

    histograms: dict[str, Any] = {}
    for hist_name in body.histogram_names:
        meta = dim_result.get(hist_name)
        if not meta:
            continue

        is_duration = meta["type"] == "histogram_duration"
        is_distance = meta["type"] == "histogram_distance"
        value_expr = "SUM(f.hist_value)"
        value_alias = "hist_value"
        value_divisor = (get_profile().duration_scale_to_seconds or 1.0) if is_duration else 1.0

        sql = (
            f"WITH agg AS ("
            f"  SELECT f.visual_id, f.bin_ID, f.lower_bound, f.upper_bound, f.bin_name,"
            f"    {value_expr} AS {value_alias}"
            f"  FROM {fact_tbl} f"
            f"  INNER JOIN {dim_tbl} d ON f.visual_id = d.visual_id"
            f"  WHERE d.name = '{hist_name}'"
            f"  GROUP BY f.visual_id, f.bin_ID, f.lower_bound, f.upper_bound, f.bin_name"
            f"), totals AS ("
            f"  SELECT *, SUM({value_alias}) OVER (PARTITION BY visual_id) AS total_value"
            f"  FROM agg"
            f") SELECT bin_ID, bin_name, lower_bound, upper_bound, {value_alias},"
            f"  CASE WHEN total_value > 0 THEN ({value_alias} / total_value) * 100 ELSE 0 END AS relative_pct"
            f" FROM totals ORDER BY bin_ID ASC"
        )

        try:
            result = execute_sql(sql, user_token=token)
        except Exception as e:
            logger.exception("Failed to query histogram %s", hist_name)
            msg = str(e)
            if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
                raise HTTPException(404, "Report results not found.")
            raise

        bins: list[dict] = []
        for row in result.get("rows", []):
            bins.append({
                "bin_id": int(row[0]) if row[0] else 0,
                "bin_name": row[1] or "",
                "lower_bound": float(row[2]) if row[2] else 0,
                "upper_bound": float(row[3]) if row[3] else 0,
                "hist_value": (float(row[4]) / value_divisor) if row[4] else 0,
                "relative_pct": float(row[5]) if row[5] else 0,
            })

        if is_duration:
            values_unit = "seconds"
        elif is_distance:
            values_unit = meta["values_unit"] or "distance"
        else:
            values_unit = meta["values_unit"] or ""

        histograms[hist_name] = {
            "type": meta["type"],
            "bins_unit": meta["bins_unit"],
            "values_unit": values_unit,
            "description": meta["description"],
            "series": {"_all": bins},
        }

    return {"histograms": histograms}


def _fetch_dimension_metadata(
    dim_tbl: str, histogram_names: list[str], token: str | None,
) -> dict[str, dict[str, str]]:
    names_str = ", ".join(f"'{n}'" for n in histogram_names)
    result = execute_sql(
        f"SELECT name, agg_type, description, bins_unit, values_unit "
        f"FROM {dim_tbl} WHERE name IN ({names_str})",
        user_token=token,
    )
    meta: dict[str, dict[str, str]] = {}
    for row in result.get("rows", []):
        meta[row[0]] = {
            "type": _clean(row[1]),
            "description": _clean(row[2]),
            "bins_unit": _clean(row[3]),
            "values_unit": _clean(row[4]),
        }
    return meta


# ---------------------------------------------------------------------------
# Unified aggregation listing (1D + 2D histograms + statistics)
# ---------------------------------------------------------------------------


@router.get("/aggregations")
async def list_aggregations(
    catalog: str, schema: str, prefix: str, request: Request,
):
    """Return all available aggregations across all types."""
    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    _validate_id(prefix, "prefix")
    token = _get_user_token(request)

    aggregations: list[dict] = []

    # 1D histograms
    try:
        tbl = _table(catalog, schema, prefix, "histogram_dimension")
        result = execute_sql(
            f"SELECT visual_id, name, agg_type, description, bins_unit, values_unit "
            f"FROM {tbl} ORDER BY visual_id",
            user_token=token,
        )
        for row in result.get("rows", []):
            aggregations.append({
                "visual_id": int(row[0]) if row[0] else 0,
                "name": _clean(row[1]),
                "agg_type": "histogram_1d",
                "type": _clean(row[2]),
                "description": _clean(row[3]),
                "bins_unit": _clean(row[4]),
                "values_unit": _clean(row[5]),
                "x_bins_unit": "",
                "y_bins_unit": "",
            })
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" not in msg and "does not exist" not in msg.lower():
            raise
        logger.debug("histogram_dimension table not found, skipping 1D histograms")

    # 2D histograms
    try:
        tbl = _table(catalog, schema, prefix, "histogram2d_dimension")
        result = execute_sql(
            f"SELECT visual_id, name, description, x_bins_unit, y_bins_unit "
            f"FROM {tbl} ORDER BY visual_id",
            user_token=token,
        )
        for row in result.get("rows", []):
            aggregations.append({
                "visual_id": int(row[0]) if row[0] else 0,
                "name": _clean(row[1]),
                "agg_type": "histogram_2d",
                "type": "duration",
                "description": _clean(row[2]),
                "bins_unit": "",
                "values_unit": "",
                "x_bins_unit": _clean(row[3]),
                "y_bins_unit": _clean(row[4]),
            })
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" not in msg and "does not exist" not in msg.lower():
            raise
        logger.debug("histogram2d_dimension table not found, skipping 2D histograms")

    # Statistics
    try:
        tbl = _table(catalog, schema, prefix, "stats_aggregator_dimension")
        result = execute_sql(
            f"SELECT visual_id, name, description "
            f"FROM {tbl} ORDER BY visual_id",
            user_token=token,
        )
        for row in result.get("rows", []):
            aggregations.append({
                "visual_id": int(row[0]) if row[0] else 0,
                "name": _clean(row[1]),
                "agg_type": "statistics",
                "type": "",
                "description": _clean(row[2]),
                "bins_unit": "",
                "values_unit": "",
                "x_bins_unit": "",
                "y_bins_unit": "",
            })
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" not in msg and "does not exist" not in msg.lower():
            raise
        logger.debug("stats_aggregator_dimension table not found, skipping statistics")

    if not aggregations:
        raise HTTPException(
            404,
            "Report results not found in Unity Catalog. Deploy and run the report first.",
        )

    return {"aggregations": aggregations}


# ---------------------------------------------------------------------------
# 2D Histogram (heatmap) data
# ---------------------------------------------------------------------------


class Histogram2DDataRequest(BaseModel):
    catalog: str
    schema_name: str
    prefix: str
    histogram_names: list[str]


@router.post("/histogram2d-data")
async def get_histogram2d_data(body: Histogram2DDataRequest, request: Request):
    _validate_id(body.catalog, "catalog")
    _validate_id(body.schema_name, "schema")
    _validate_id(body.prefix, "prefix")
    for name in body.histogram_names:
        _validate_id(name, "histogram_name")
    token = _get_user_token(request)

    fact_tbl = _table(body.catalog, body.schema_name, body.prefix, "histogram2d_fact")
    dim_tbl = _table(body.catalog, body.schema_name, body.prefix, "histogram2d_dimension")

    histograms: dict[str, Any] = {}
    for hist_name in body.histogram_names:
        try:
            dim_res = execute_sql(
                f"SELECT description, x_bins_unit, y_bins_unit "
                f"FROM {dim_tbl} WHERE name = '{hist_name}'",
                user_token=token,
            )
        except Exception as e:
            msg = str(e)
            if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
                raise HTTPException(404, "2D histogram results not found.")
            raise
        dim_row = dim_res["rows"][0] if dim_res.get("rows") else [None, None, None]

        # Fetch human-friendly channel names for axis labels.
        # Schema columns are x_channel_name / y_channel_name in the upstream wheel.
        x_signal_label = ""
        y_signal_label = ""
        try:
            expr_res = execute_sql(
                f"SELECT x_channel_name, y_channel_name FROM {dim_tbl} WHERE name = '{hist_name}'",
                user_token=token,
            )
            if expr_res.get("rows"):
                x_signal_label = expr_res["rows"][0][0] or ""
                y_signal_label = expr_res["rows"][0][1] or ""
        except Exception:
            pass  # Graceful fallback — older tables may lack these columns

        sql = (
            f"SELECT f.x_bin_id, f.y_bin_id, "
            f"  f.x_bin_name, f.y_bin_name, "
            f"  SUM(f.hist_value) AS hist_value "
            f"FROM {fact_tbl} f "
            f"INNER JOIN {dim_tbl} d ON f.visual_id = d.visual_id "
            f"WHERE d.name = '{hist_name}' "
            f"GROUP BY f.x_bin_id, f.y_bin_id, f.x_bin_name, f.y_bin_name "
            f"ORDER BY f.y_bin_id, f.x_bin_id"
        )

        try:
            result = execute_sql(sql, user_token=token)
        except Exception as e:
            logger.exception("Failed to query 2D histogram %s", hist_name)
            msg = str(e)
            if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
                raise HTTPException(404, "2D histogram results not found.")
            raise

        # Build x/y label lists and z matrix
        x_labels_set: dict[int, str] = {}
        y_labels_set: dict[int, str] = {}
        cells: list[tuple[int, int, float]] = []
        value_divisor = get_profile().duration_scale_to_seconds or 1.0

        for row in result.get("rows", []):
            x_id = int(row[0]) if row[0] else 0
            y_id = int(row[1]) if row[1] else 0
            x_name = row[2] or str(x_id)
            y_name = row[3] or str(y_id)
            value = (float(row[4]) / value_divisor) if row[4] else 0.0
            x_labels_set[x_id] = x_name
            y_labels_set[y_id] = y_name
            cells.append((x_id, y_id, value))

        x_ids_sorted = sorted(x_labels_set.keys())
        y_ids_sorted = sorted(y_labels_set.keys())
        x_labels = [x_labels_set[i] for i in x_ids_sorted]
        y_labels = [y_labels_set[i] for i in y_ids_sorted]

        x_idx_map = {xid: idx for idx, xid in enumerate(x_ids_sorted)}
        y_idx_map = {yid: idx for idx, yid in enumerate(y_ids_sorted)}

        z = [[0.0] * len(x_ids_sorted) for _ in range(len(y_ids_sorted))]
        for x_id, y_id, val in cells:
            z[y_idx_map[y_id]][x_idx_map[x_id]] = val

        histograms[hist_name] = {
            "x_labels": x_labels,
            "y_labels": y_labels,
            "z": z,
            "x_bins_unit": dim_row[1] or "",
            "y_bins_unit": dim_row[2] or "",
            "x_signal_label": x_signal_label,
            "y_signal_label": y_signal_label,
            "values_unit": "seconds",
            "description": dim_row[0] or "",
        }

    return {"histograms": histograms}


# ---------------------------------------------------------------------------
# Statistics data
# ---------------------------------------------------------------------------


class StatisticsDataRequest(BaseModel):
    catalog: str
    schema_name: str
    prefix: str
    statistics_names: list[str]


@router.post("/statistics-data")
async def get_statistics_data(body: StatisticsDataRequest, request: Request):
    _validate_id(body.catalog, "catalog")
    _validate_id(body.schema_name, "schema")
    _validate_id(body.prefix, "prefix")
    for name in body.statistics_names:
        _validate_id(name, "statistics_name")
    token = _get_user_token(request)

    fact_tbl = _table(body.catalog, body.schema_name, body.prefix, "stats_aggregator_fact")
    dim_tbl = _table(body.catalog, body.schema_name, body.prefix, "stats_aggregator_dimension")

    statistics: dict[str, Any] = {}
    for stat_name in body.statistics_names:
        try:
            dim_res = execute_sql(
                f"SELECT description, channel_names, statistics "
                f"FROM {dim_tbl} WHERE name = '{stat_name}'",
                user_token=token,
            )
        except Exception as e:
            msg = str(e)
            if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
                raise HTTPException(404, "Statistics results not found.")
            raise
        dim_row = dim_res["rows"][0] if dim_res.get("rows") else [None, None, None]
        # channel_names and statistics come back as JSON-encoded arrays from the SQL connector
        dim_channel_names = _parse_array(dim_row[1])
        dim_stat_labels = _parse_array(dim_row[2])

        sql = (
            f"SELECT f.event_instance_id, f.channel_name, f.aggregation_label, f.statistic_value "
            f"FROM {fact_tbl} f "
            f"INNER JOIN {dim_tbl} d ON f.visual_id = d.visual_id "
            f"WHERE d.name = '{stat_name}' "
            f"ORDER BY f.event_instance_id, f.channel_name, f.aggregation_label"
        )

        try:
            result = execute_sql(sql, user_token=token)
        except Exception as e:
            logger.exception("Failed to query statistics %s", stat_name)
            msg = str(e)
            if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
                raise HTTPException(404, "Statistics results not found.")
            raise

        rows = []
        channel_names_set: set[str] = set()
        stat_labels_set: set[str] = set()
        for row in result.get("rows", []):
            instance_id = int(row[0]) if row[0] is not None else 0
            channel = row[1] or ""
            label = row[2] or ""
            val = float(row[3]) if row[3] is not None else 0.0
            rows.append({
                "event_instance_id": instance_id,
                "channel_name": channel,
                "aggregation_label": label,
                "value": val,
            })
            channel_names_set.add(channel)
            stat_labels_set.add(label)

        # Prefer dim-table arrays for ordering/completeness; fall back to facts.
        channel_names = dim_channel_names or sorted(channel_names_set)
        stat_labels = dim_stat_labels or sorted(stat_labels_set)

        statistics[stat_name] = {
            "rows": rows,
            "channel_names": channel_names,
            "stat_labels": stat_labels,
            "description": _clean(dim_row[0]),
        }

    return {"statistics": statistics}


def _parse_array(val: Any) -> list[str]:
    """Best-effort parse of a SQL ARRAY value coming back from the connector.

    SQL connectors variably return ARRAY<STRING> as a Python list, a JSON string,
    or None. Normalise to list[str].
    """
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x is not None]
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        try:
            import json
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x is not None]
        except Exception:
            pass
    return []
