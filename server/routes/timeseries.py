"""Time series endpoints — /api/timeseries/*

Query Silver layer channels table (RLE intervals) for interactive time series
visualization. Supports in-memory Polars cache with LTTB downsampling for
datasets with 100M–300M+ data points.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from server.mcp_tools import execute_sql
from server.ts_cache import TimeSeriesCache, get_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/timeseries", tags=["timeseries"])

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_]+$")

# Synthetic test data marker
_SYNTHETIC_CONTAINER_ID = 0
_SYNTHETIC_CATALOG = "synthetic"
_SYNTHETIC_SCHEMA = "test"


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
    # Synthetic data path
    if catalog == _SYNTHETIC_CATALOG and schema == _SYNTHETIC_SCHEMA:
        from test.synthetic_ts import SYNTHETIC_CONTAINER
        return {"containers": [SYNTHETIC_CONTAINER]}

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
    # Synthetic data path
    if container_id == _SYNTHETIC_CONTAINER_ID:
        return _list_synthetic_signals()

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
# Load channels into in-memory cache
# ---------------------------------------------------------------------------


class LoadRequest(BaseModel):
    catalog: str
    schema_name: str  # 'schema' is a Pydantic reserved name
    container_id: int
    channel_ids: list[int]


@router.post("/load")
async def load_channels(body: LoadRequest, request: Request):
    """Load channel data into in-memory Polars cache for fast resampling.

    For synthetic data (container_id=0): generates test data locally.
    For real data: fetches from Databricks SQL warehouse via Arrow.
    """
    cache = get_cache()
    token = _get_user_token(request)
    results = []

    # Synthetic data path
    if body.container_id == _SYNTHETIC_CONTAINER_ID:
        return _load_synthetic(body.channel_ids)

    # Real data path
    _validate_id(body.catalog, "catalog")
    _validate_id(body.schema_name, "schema")

    from server.ts_connector import fetch_channel_polars, get_connection

    conn = get_connection(token)
    try:
        for channel_id in body.channel_ids:
            cache_key = TimeSeriesCache.make_key(
                body.catalog, body.schema_name, body.container_id, channel_id
            )

            if cache.is_loaded(cache_key):
                ch = cache._cache[cache_key]
                results.append({
                    "channel_id": channel_id,
                    "cache_key": cache_key,
                    "total_points": ch.total_points,
                    "t_min_ns": ch.t_min_ns,
                    "t_max_ns": ch.t_max_ns,
                    "load_time_ms": 0,
                    "cached": True,
                })
                continue

            t0 = time.monotonic()
            df = fetch_channel_polars(
                conn, body.catalog, body.schema_name, body.container_id, channel_id
            )
            fetch_ms = (time.monotonic() - t0) * 1000

            ch = cache.load_from_polars(cache_key, channel_id, df)
            total_ms = (time.monotonic() - t0) * 1000

            logger.info(
                "Loaded %s: fetch=%.0fms, total=%.0fms, %d points",
                cache_key, fetch_ms, total_ms, ch.total_points,
            )

            results.append({
                "channel_id": channel_id,
                "cache_key": cache_key,
                "total_points": ch.total_points,
                "t_min_ns": ch.t_min_ns,
                "t_max_ns": ch.t_max_ns,
                "load_time_ms": round(total_ms),
                "cached": False,
            })
    finally:
        conn.close()

    return {
        "channels": results,
        "memory_used_mb": round(cache.get_memory_usage() / 1024**2),
    }


# ---------------------------------------------------------------------------
# Resample from cache (fast path — <50ms)
# ---------------------------------------------------------------------------


class ResampleRequest(BaseModel):
    cache_keys: list[str]
    x_min_ns: float | None = None
    x_max_ns: float | None = None
    n_points: int = 5000
    normalize: bool = False


@router.post("/resample")
async def resample_channels(body: ResampleRequest):
    """Resample cached channels using LTTB. Instant response from in-memory data."""
    cache = get_cache()
    traces = []

    for cache_key in body.cache_keys:
        if not cache.is_loaded(cache_key):
            raise HTTPException(404, f"Channel {cache_key} not loaded. Call /load first.")

        t0 = time.monotonic()
        result = cache.resample(
            cache_key,
            x_min_ns=body.x_min_ns,
            x_max_ns=body.x_max_ns,
            n_points=body.n_points,
            normalize=body.normalize,
        )
        resample_ms = (time.monotonic() - t0) * 1000

        logger.debug("Resample %s: %.1fms, %d window pts", cache_key, resample_ms, result["window_points"])

        result["cache_key"] = cache_key
        traces.append(result)

    return {"traces": traces}


# ---------------------------------------------------------------------------
# Legacy data endpoint (kept for backward compatibility)
# ---------------------------------------------------------------------------


def _lttb_downsample(t, v, n_out):
    """Downsample using LTTB — legacy path."""
    import numpy as np

    if len(t) <= n_out:
        return t, v
    try:
        from tsdownsample import LTTBDownsampler
        indices = LTTBDownsampler().downsample(t, v, n_out=n_out)
        return t[indices], v[indices]
    except ImportError:
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
    n_points: int = Query(5000, ge=100, le=50000),
):
    """Legacy: fetch + downsample in one call. Use /load + /resample for large data."""
    import numpy as np

    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    token = _get_user_token(request)

    channels_table = f"{catalog}.{schema}.channels"
    where_parts = [
        f"container_id = {container_id}",
        f"channel_id = {channel_id}",
    ]
    if x_min is not None:
        where_parts.append(f"tend >= {x_min}")
    if x_max is not None:
        where_parts.append(f"tstart <= {x_max}")

    sql = (
        f"SELECT tstart, tend, value "
        f"FROM {channels_table} "
        f"WHERE {' AND '.join(where_parts)} "
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

    t_ds, v_ds = _lttb_downsample(t_arr, v_arr, n_points)

    data = [
        {"t": t / 1e9, "v": float(v)}
        for t, v in zip(t_ds.tolist(), v_ds.tolist())
    ]

    return {"data": data, "total_points": total_points}


# ---------------------------------------------------------------------------
# Synthetic data helpers
# ---------------------------------------------------------------------------


def _list_synthetic_signals() -> dict:
    """Return synthetic signal metadata without touching Databricks."""
    from test.synthetic_ts import SYNTHETIC_SIGNALS
    return {"signals": [dict(s) for s in SYNTHETIC_SIGNALS]}


def _load_synthetic(channel_ids: list[int]) -> dict:
    """Load synthetic data into cache."""
    from test.synthetic_ts import load_synthetic_data

    all_results = load_synthetic_data()
    cache = get_cache()

    channels = []
    for cid in channel_ids:
        info = all_results.get(cid, {})
        cache_key = info.get("cache_key", TimeSeriesCache.make_key(
            _SYNTHETIC_CATALOG, _SYNTHETIC_SCHEMA, _SYNTHETIC_CONTAINER_ID, cid
        ))
        ch = cache._cache.get(cache_key)
        if ch:
            channels.append({
                "channel_id": cid,
                "cache_key": cache_key,
                "total_points": ch.total_points,
                "t_min_ns": ch.t_min_ns,
                "t_max_ns": ch.t_max_ns,
                "load_time_ms": 0,
                "cached": True,
            })

    return {
        "channels": channels,
        "memory_used_mb": round(cache.get_memory_usage() / 1024**2),
    }
