"""Time series endpoints — /api/timeseries/*

Query Silver layer channels table (RLE intervals) for interactive time series
visualization. Supports LTTB downsampling for large datasets.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request

from server.mcp_tools import execute_sql

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/timeseries", tags=["timeseries"])

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _validate_id(value: str, name: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise HTTPException(400, f"Invalid {name}: must be alphanumeric/underscores only")
    return value


def _get_user_token(request: Request) -> str | None:
    return request.headers.get("X-Forwarded-Access-Token")


# ---------------------------------------------------------------------------
# Container listing
# ---------------------------------------------------------------------------


@router.get("/containers")
async def list_containers(
    catalog: str, schema: str, request: Request,
):
    """List available measurement containers with metadata."""
    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    token = _get_user_token(request)

    sql = (
        f"SELECT m.container_id, "
        f"  COALESCE(t_fn.value, CAST(m.container_id AS STRING)) AS filename, "
        f"  COALESCE(t_vk.value, '') AS vehicle_key, "
        f"  m.start_dt, m.stop_dt, m.num_channels, m.duration_ms "
        f"FROM {catalog}.{schema}.container_metrics m "
        f"LEFT JOIN {catalog}.{schema}.container_tags t_fn "
        f"  ON m.container_id = t_fn.container_id AND t_fn.key = 'filename' "
        f"LEFT JOIN {catalog}.{schema}.container_tags t_vk "
        f"  ON m.container_id = t_vk.container_id AND t_vk.key = 'vehicle_key' "
        f"ORDER BY m.start_dt DESC"
    )

    try:
        result = execute_sql(sql, user_token=token)
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
            raise HTTPException(404, "Container metrics table not found.")
        raise

    containers = []
    for row in result.get("rows", []):
        containers.append({
            "container_id": int(row[0]) if row[0] else 0,
            "filename": row[1] or "",
            "vehicle_key": row[2] or "",
            "start_dt": str(row[3]) if row[3] else None,
            "stop_dt": str(row[4]) if row[4] else None,
            "num_channels": int(row[5]) if row[5] else 0,
            "duration_ms": int(row[6]) if row[6] else 0,
        })
    return {"containers": containers}


# ---------------------------------------------------------------------------
# Signal listing (for a specific container)
# ---------------------------------------------------------------------------


@router.get("/signals")
async def list_signals(
    catalog: str, schema: str, container_id: int, request: Request,
):
    """List available signals for a container with metadata."""
    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    token = _get_user_token(request)

    sql = (
        f"SELECT t_name.channel_id, "
        f"  t_name.value AS channel_name, "
        f"  COALESCE(t_unit.value, '') AS unit, "
        f"  m.sample_count, m.min, m.max, m.mean "
        f"FROM {catalog}.{schema}.channel_tags t_name "
        f"LEFT JOIN {catalog}.{schema}.channel_tags t_unit "
        f"  ON t_name.container_id = t_unit.container_id "
        f"  AND t_name.channel_id = t_unit.channel_id "
        f"  AND t_unit.key = 'unit' "
        f"LEFT JOIN {catalog}.{schema}.channel_metrics m "
        f"  ON t_name.container_id = m.container_id "
        f"  AND t_name.channel_id = m.channel_id "
        f"WHERE t_name.key = 'channel_name' "
        f"  AND t_name.container_id = {container_id} "
        f"ORDER BY channel_name"
    )

    try:
        result = execute_sql(sql, user_token=token)
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
            raise HTTPException(404, "Channel metadata tables not found.")
        raise

    signals = []
    for row in result.get("rows", []):
        signals.append({
            "channel_id": int(row[0]) if row[0] else 0,
            "channel_name": row[1] or "",
            "unit": row[2] or "",
            "sample_count": int(row[3]) if row[3] else 0,
            "min_value": float(row[4]) if row[4] else None,
            "max_value": float(row[5]) if row[5] else None,
            "mean_value": float(row[6]) if row[6] else None,
        })
    return {"signals": signals}


# ---------------------------------------------------------------------------
# Time series data with LTTB downsampling
# ---------------------------------------------------------------------------


def _lttb_downsample(t: np.ndarray, v: np.ndarray, n_out: int) -> tuple[np.ndarray, np.ndarray]:
    """Downsample using Largest-Triangle-Three-Buckets (LTTB).

    Falls back to pure-numpy implementation if tsdownsample is unavailable.
    """
    if len(t) <= n_out:
        return t, v

    try:
        from tsdownsample import LTTBDownsampler

        indices = LTTBDownsampler().downsample(t, v, n_out=n_out)
        return t[indices], v[indices]
    except ImportError:
        # Pure-numpy fallback — simple bucket-based selection
        indices = np.round(np.linspace(0, len(t) - 1, n_out)).astype(int)
        return t[indices], v[indices]


@router.get("/data")
async def get_timeseries_data(
    catalog: str,
    schema: str,
    container_id: int,
    channel_id: int,
    request: Request,
    x_min: int | None = Query(None, description="Min timestamp (nanoseconds)"),
    x_max: int | None = Query(None, description="Max timestamp (nanoseconds)"),
    n_points: int = Query(1500, ge=100, le=10000),
):
    """Fetch time series data for a single channel, downsampled with LTTB.

    The Silver layer stores RLE intervals (tstart, tend, value). We expand
    each interval to step pairs [(tstart, value), (tend, value)] to preserve
    the step-function shape, then downsample.
    """
    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    token = _get_user_token(request)

    # Build channels table name — it's simply 'channels' in the schema
    channels_table = f"{catalog}.{schema}.channels"

    where_parts = [
        f"container_id = {container_id}",
        f"channel_id = {channel_id}",
    ]
    if x_min is not None:
        where_parts.append(f"tend >= {x_min}")
    if x_max is not None:
        where_parts.append(f"tstart <= {x_max}")

    where_sql = " AND ".join(where_parts)

    sql = (
        f"SELECT tstart, tend, value "
        f"FROM {channels_table} "
        f"WHERE {where_sql} "
        f"ORDER BY tstart"
    )

    try:
        result = execute_sql(sql, user_token=token)
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
            raise HTTPException(404, "Channels table not found.")
        raise

    rows = result.get("rows", [])
    if not rows:
        return {"data": [], "total_points": 0}

    # Expand RLE intervals to step pairs
    times: list[int] = []
    values: list[float] = []
    for row in rows:
        tstart = int(row[0]) if row[0] else 0
        tend = int(row[1]) if row[1] else 0
        val = float(row[2]) if row[2] else 0.0
        times.append(tstart)
        values.append(val)
        if tend != tstart:
            times.append(tend)
            values.append(val)

    t_arr = np.array(times, dtype=np.float64)
    v_arr = np.array(values, dtype=np.float64)

    total_points = len(t_arr)

    # Downsample
    t_ds, v_ds = _lttb_downsample(t_arr, v_arr, n_points)

    # Convert nanosecond timestamps to seconds for JSON transport
    data = [
        {"t": t / 1e9, "v": float(v)}
        for t, v in zip(t_ds.tolist(), v_ds.tolist())
    ]

    return {"data": data, "total_points": total_points}
