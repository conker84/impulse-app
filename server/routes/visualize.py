"""Visualize endpoints — /api/visualize/*

Query histogram results from Unity Catalog gold layer tables for
interactive visualization with filtering by vehicle, time range,
and mileage.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.mcp_tools import execute_sql

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/visualize", tags=["visualize"])

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_]+$")

def _get_mapping_table() -> str:
    return os.environ.get("IMPULSE_MAPPING_TABLE", "")


def _validate_id(value: str, name: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise HTTPException(400, f"Invalid {name}: must be alphanumeric/underscores only")
    return value


def _table(catalog: str, schema: str, prefix: str, suffix: str) -> str:
    return f"{catalog}.{schema}.{prefix}_{suffix}"


def _get_user_token(request: Request) -> str | None:
    return request.headers.get("X-Forwarded-Access-Token")


def _safe_sql(func):
    """Wrap an endpoint helper to catch missing-table errors and return 404."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
                raise HTTPException(
                    404,
                    "Report results not found in Unity Catalog. "
                    "Deploy and run the report first.",
                )
            raise
    return wrapper


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
            f"SELECT visual_id, name, type, description, bins_unit, values_unit, page_number "
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
            "name": row[1] or "",
            "type": row[2] or "",
            "description": row[3] or "",
            "bins_unit": row[4] or "",
            "values_unit": row[5] or "",
        })
    return {"histograms": histograms}


@router.get("/vehicles")
async def list_vehicles(
    catalog: str, schema: str, prefix: str, request: Request,
):
    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    _validate_id(prefix, "prefix")
    token = _get_user_token(request)
    tbl = _table(catalog, schema, prefix, "session_dimension")

    try:
        result = execute_sql(
            f"SELECT DISTINCT s.test_object_id, m.test_object_name "
            f"FROM {tbl} s "
            f"LEFT JOIN {_get_mapping_table()} m "
            f"  ON CAST(s.test_object_id AS STRING) = CAST(m.test_object_id AS STRING) "
            f"ORDER BY m.test_object_name, s.test_object_id",
            user_token=token,
        )
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
            raise HTTPException(404, "Session dimension table not found.")
        raise

    vehicles = [
        {"id": row[0] or "", "name": row[1] or row[0] or ""}
        for row in result.get("rows", [])
        if row[0]
    ]
    return {"vehicles": vehicles}


@router.get("/filter-range")
async def get_filter_range(
    catalog: str, schema: str, prefix: str, request: Request,
):
    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    _validate_id(prefix, "prefix")
    token = _get_user_token(request)
    tbl = _table(catalog, schema, prefix, "session_dimension")

    try:
        result = execute_sql(
            f"SELECT "
            f"  CAST(MIN(first_datapoint_timestamp) AS STRING), "
            f"  CAST(MAX(last_datapoint_timestamp) AS STRING), "
            f"  MIN(measurement_session_start_odo_mileage), "
            f"  MAX(measurement_session_end_odo_mileage) "
            f"FROM {tbl}",
            user_token=token,
        )
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
            raise HTTPException(404, "Session dimension table not found.")
        raise

    row = result["rows"][0] if result.get("rows") else [None, None, None, None]
    return {
        "min_ts": row[0],
        "max_ts": row[1],
        "min_mileage": float(row[2]) if row[2] else None,
        "max_mileage": float(row[3]) if row[3] else None,
    }


class HistogramDataRequest(BaseModel):
    catalog: str
    schema_name: str
    prefix: str
    histogram_names: list[str]
    vehicle_ids: list[str] | None = None
    start_ts: str | None = None
    end_ts: str | None = None
    min_mileage: float | None = None
    max_mileage: float | None = None
    group_by_vehicle: bool = False


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
    sess_tbl = _table(body.catalog, body.schema_name, body.prefix, "session_dimension")

    dim_result = _fetch_dimension_metadata(dim_tbl, body.histogram_names, token)

    needs_session_join = bool(
        body.vehicle_ids or body.start_ts or body.end_ts
        or body.min_mileage is not None or body.max_mileage is not None
        or body.group_by_vehicle
    )

    histograms: dict[str, Any] = {}
    for hist_name in body.histogram_names:
        meta = dim_result.get(hist_name)
        if not meta:
            continue

        is_duration = meta["type"] == "duration"
        value_expr = "SUM(f.hist_value) / 1e9" if is_duration else "SUM(f.hist_value)"
        value_alias = "hist_value"

        vehicle_col = ", COALESCE(m.test_object_name, s.test_object_id) AS vehicle_name" if body.group_by_vehicle else ""
        vehicle_group = ", COALESCE(m.test_object_name, s.test_object_id)" if body.group_by_vehicle else ""

        joins = f"INNER JOIN {dim_tbl} d ON f.visual_id = d.visual_id"
        if needs_session_join:
            joins += f" INNER JOIN {sess_tbl} s ON f.global_session_id = s.global_session_id"
        if body.group_by_vehicle:
            joins += (
                f" LEFT JOIN {_get_mapping_table()} m"
                f" ON CAST(s.test_object_id AS STRING) = CAST(m.test_object_id AS STRING)"
            )

        where_clauses = [f"d.name = '{hist_name}'"]
        if body.vehicle_ids:
            ids_str = ", ".join(f"'{v}'" for v in body.vehicle_ids)
            where_clauses.append(f"s.test_object_id IN ({ids_str})")
        if body.start_ts:
            where_clauses.append(f"s.first_datapoint_timestamp >= '{body.start_ts}'")
        if body.end_ts:
            where_clauses.append(f"s.last_datapoint_timestamp <= '{body.end_ts}'")
        if body.min_mileage is not None:
            where_clauses.append(f"s.measurement_session_start_odo_mileage >= {body.min_mileage}")
        if body.max_mileage is not None:
            where_clauses.append(f"s.measurement_session_end_odo_mileage <= {body.max_mileage}")

        where_sql = " AND ".join(where_clauses)

        sql = (
            f"WITH agg AS ("
            f"  SELECT f.visual_id, f.bin_ID, f.lower_bound, f.upper_bound, f.bin_name"
            f"    {vehicle_col},"
            f"    {value_expr} AS {value_alias}"
            f"  FROM {fact_tbl} f {joins}"
            f"  WHERE {where_sql}"
            f"  GROUP BY f.visual_id, f.bin_ID, f.lower_bound, f.upper_bound, f.bin_name"
            f"    {vehicle_group}"
            f"), totals AS ("
            f"  SELECT *, SUM({value_alias}) OVER ("
            f"    PARTITION BY visual_id"
            f"    {',' if body.group_by_vehicle else ''}"
            f"    {'vehicle_name' if body.group_by_vehicle else ''}"
            f"  ) AS total_value"
            f"  FROM agg"
            f") SELECT bin_ID, bin_name, lower_bound, upper_bound, {value_alias},"
            f"  CASE WHEN total_value > 0 THEN ({value_alias} / total_value) * 100 ELSE 0 END AS relative_pct"
            f"  {', vehicle_name' if body.group_by_vehicle else ''}"
            f" FROM totals ORDER BY {'vehicle_name,' if body.group_by_vehicle else ''} bin_ID ASC"
        )

        try:
            result = execute_sql(sql, user_token=token)
        except Exception as e:
            logger.exception("Failed to query histogram %s", hist_name)
            msg = str(e)
            if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
                raise HTTPException(404, "Report results not found.")
            raise

        series: dict[str, list[dict]] = {}
        for row in result.get("rows", []):
            bin_data = {
                "bin_id": int(row[0]) if row[0] else 0,
                "bin_name": row[1] or "",
                "lower_bound": float(row[2]) if row[2] else 0,
                "upper_bound": float(row[3]) if row[3] else 0,
                "hist_value": float(row[4]) if row[4] else 0,
                "relative_pct": float(row[5]) if row[5] else 0,
            }
            if body.group_by_vehicle:
                vehicle_id = row[6] or "_unknown"
                series.setdefault(vehicle_id, []).append(bin_data)
            else:
                series.setdefault("_all", []).append(bin_data)

        histograms[hist_name] = {
            "type": meta["type"],
            "bins_unit": meta["bins_unit"],
            "values_unit": "seconds" if is_duration else meta["values_unit"],
            "description": meta["description"],
            "series": series,
        }

    return {"histograms": histograms}


def _fetch_dimension_metadata(
    dim_tbl: str, histogram_names: list[str], token: str | None,
) -> dict[str, dict[str, str]]:
    names_str = ", ".join(f"'{n}'" for n in histogram_names)
    result = execute_sql(
        f"SELECT name, type, description, bins_unit, values_unit "
        f"FROM {dim_tbl} WHERE name IN ({names_str})",
        user_token=token,
    )
    meta: dict[str, dict[str, str]] = {}
    for row in result.get("rows", []):
        meta[row[0]] = {
            "type": row[1] or "",
            "description": row[2] or "",
            "bins_unit": row[3] or "",
            "values_unit": row[4] or "",
        }
    return meta
