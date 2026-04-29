"""Time series endpoints — /api/timeseries/*

Query Silver layer channels table (RLE intervals) for interactive time series
visualization. Supports in-memory Polars cache with LTTB downsampling for
datasets with 100M–300M+ data points.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from server.mcp_tools import execute_sql
from server.ts_cache import TimeSeriesCache, get_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/timeseries", tags=["timeseries"])

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_]+$")

# Synthetic test data marker
_SYNTHETIC_CONTAINER_ID = "-1"
_SYNTHETIC_CATALOG = "synthetic"
_SYNTHETIC_SCHEMA = "test"


def _is_synthetic(container_id: object) -> bool:
    return str(container_id) == _SYNTHETIC_CONTAINER_ID

# Background load jobs — keyed by load_id
_load_jobs: dict[str, dict] = {}

# Session-scoped TS Viewer overrides — keyed by session_id (UI-set field overrides)
_ts_session_overrides: dict[str, dict] = {}


def _get_session_overrides(session_id: str | None) -> dict | None:
    if not session_id:
        return None
    return _ts_session_overrides.get(session_id)


def _validate_id(value: str, name: str) -> str:
    if not value or not _IDENTIFIER_RE.match(value):
        raise HTTPException(400, f"Invalid {name}: must be alphanumeric/underscores only")
    return value


def _get_user_token(request: Request) -> str | None:
    return request.headers.get("X-Forwarded-Access-Token")


# ---------------------------------------------------------------------------
# Container listing
# ---------------------------------------------------------------------------


def _to_id_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


@router.get("/containers")
async def list_containers(
    catalog: str, schema: str, request: Request,
    session_id: str | None = Query(None),
):
    """List available measurement containers with metadata."""
    # Synthetic data path
    if catalog == _SYNTHETIC_CATALOG and schema == _SYNTHETIC_SCHEMA:
        from test.synthetic_ts import SYNTHETIC_CONTAINER
        return {"containers": [SYNTHETIC_CONTAINER]}

    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    token = _get_user_token(request)

    from server.schema_adapter import SchemaAdapter
    overrides = _get_session_overrides(session_id)
    sql = SchemaAdapter.from_active_profile(catalog, schema, session_overrides=overrides).containers_list_query()

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
            "container_id": _to_id_str(row[0]),
            "vehicle_key": row[1] or "",
            "start_dt": str(row[2]) if row[2] else None,
            "stop_dt": str(row[3]) if row[3] else None,
            "num_channels": int(row[4]) if row[4] else 0,
            "duration_ms": int(row[5]) if row[5] else 0,
        })
    return {"containers": containers}


# ---------------------------------------------------------------------------
# Signal listing (for a specific container)
# ---------------------------------------------------------------------------


@router.get("/signals")
async def list_signals(
    catalog: str, schema: str, container_id: str, request: Request,
    session_id: str | None = Query(None),
):
    """List available signals for a container with metadata."""
    if _is_synthetic(container_id):
        return _list_synthetic_signals()

    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    token = _get_user_token(request)

    from server.schema_adapter import SchemaAdapter
    overrides = _get_session_overrides(session_id)
    sql = SchemaAdapter.from_active_profile(catalog, schema, session_overrides=overrides).signals_list_query(container_id)

    try:
        result = execute_sql(sql, user_token=token)
    except Exception as e:
        msg = str(e)
        if "TABLE_OR_VIEW_NOT_FOUND" in msg or "does not exist" in msg.lower():
            raise HTTPException(404, "Channel metadata tables not found.")
        raise

    def _to_float(v):
        if v in (None, "", "NULL"):
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    signals = []
    for row in result.get("rows", []):
        signals.append({
            "channel_id": _to_id_str(row[0]),
            "channel_name": row[1] or "",
            "unit": row[2] or "",
            "sample_count": int(row[3]) if row[3] else 0,
            "min_value": _to_float(row[4]),
            "max_value": _to_float(row[5]),
            "mean_value": _to_float(row[6]),
        })
    return {"signals": signals}


# ---------------------------------------------------------------------------
# Load channels into in-memory cache (async with polling)
# ---------------------------------------------------------------------------


class LoadRequest(BaseModel):
    catalog: str
    schema_name: str  # 'schema' is a Pydantic reserved name
    container_id: str
    channel_ids: list[str]
    session_id: str | None = None


def _background_load(load_id: str, body: LoadRequest, token: str | None):
    """Run the heavy SQL fetch in a background thread."""
    job = _load_jobs[load_id]
    cache = get_cache()

    try:
        # Synthetic data path
        if _is_synthetic(body.container_id):
            result = _load_synthetic(body.channel_ids)
            job["result"] = result
            job["status"] = "done"
            return

        from server.ts_connector import fetch_channel_arrow, get_connection

        overrides = _get_session_overrides(body.session_id) if body.session_id else None
        conn = get_connection(token)
        channels = []
        try:
            for channel_id in body.channel_ids:
                cache_key = TimeSeriesCache.make_key(
                    body.catalog, body.schema_name, body.container_id, channel_id
                )

                if cache.is_loaded(cache_key):
                    ch = cache._cache[cache_key]
                    channels.append({
                        "channel_id": channel_id,
                        "cache_key": cache_key,
                        "total_points": ch.total_points,
                        "t_min_ns": ch.t_min_ns,
                        "t_max_ns": ch.t_max_ns,
                        "load_time_ms": 0,
                        "cached": True,
                    })
                    continue

                job["message"] = "Fetching data from warehouse..."
                t0 = time.monotonic()
                table = fetch_channel_arrow(
                    conn, body.catalog, body.schema_name, body.container_id, channel_id,
                    session_overrides=overrides,
                )
                fetch_ms = (time.monotonic() - t0) * 1000

                job["message"] = f"Processing {table.num_rows:,} rows..."
                ch = cache.load_from_arrow(cache_key, channel_id, table)
                total_ms = (time.monotonic() - t0) * 1000

                logger.info(
                    "Loaded %s: fetch=%.0fms, total=%.0fms, %d points",
                    cache_key, fetch_ms, total_ms, ch.total_points,
                )

                channels.append({
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

        job["result"] = {
            "channels": channels,
            "memory_used_mb": round(cache.get_memory_usage() / 1024**2),
        }
        job["status"] = "done"

    except Exception as e:
        logger.exception("Background load failed for %s", load_id)
        job["status"] = "error"
        job["error"] = str(e)


@router.post("/load")
async def load_channels(body: LoadRequest, request: Request):
    """Start loading channel data in the background. Returns a load_id to poll."""
    cache = get_cache()
    token = _get_user_token(request)

    # Quick path: if all channels are already cached, return immediately
    all_cached = True
    channels = []
    for channel_id in body.channel_ids:
        if _is_synthetic(body.container_id):
            all_cached = False
            break
        cache_key = TimeSeriesCache.make_key(
            body.catalog, body.schema_name, body.container_id, channel_id
        )
        if cache.is_loaded(cache_key):
            ch = cache._cache[cache_key]
            channels.append({
                "channel_id": channel_id,
                "cache_key": cache_key,
                "total_points": ch.total_points,
                "t_min_ns": ch.t_min_ns,
                "t_max_ns": ch.t_max_ns,
                "load_time_ms": 0,
                "cached": True,
            })
        else:
            all_cached = False
            break

    if all_cached:
        return {
            "status": "done",
            "channels": channels,
            "memory_used_mb": round(cache.get_memory_usage() / 1024**2),
        }

    # Start background load
    load_id = uuid.uuid4().hex[:12]
    _load_jobs[load_id] = {
        "status": "loading",
        "message": "Starting data fetch...",
        "result": None,
        "error": None,
        "started": time.monotonic(),
    }

    thread = threading.Thread(
        target=_background_load, args=(load_id, body, token), daemon=True
    )
    thread.start()

    return {"status": "loading", "load_id": load_id}


@router.get("/load/status/{load_id}")
async def load_status(load_id: str):
    """Poll for background load completion."""
    job = _load_jobs.get(load_id)
    if job is None:
        raise HTTPException(404, "Unknown load_id")

    elapsed_ms = round((time.monotonic() - job["started"]) * 1000)

    if job["status"] == "loading":
        return {
            "status": "loading",
            "message": job["message"],
            "elapsed_ms": elapsed_ms,
        }

    if job["status"] == "error":
        # Clean up
        _load_jobs.pop(load_id, None)
        return {"status": "error", "error": job["error"], "elapsed_ms": elapsed_ms}

    # Done — return result and clean up
    result = job["result"]
    _load_jobs.pop(load_id, None)
    return {"status": "done", "elapsed_ms": elapsed_ms, **result}


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
    container_id: str,
    channel_id: str,
    request: Request,
    x_min: int | None = Query(None, description="Min timestamp (nanoseconds)"),
    x_max: int | None = Query(None, description="Max timestamp (nanoseconds)"),
    n_points: int = Query(5000, ge=100, le=50000),
    session_id: str | None = Query(None),
):
    """Legacy: fetch + downsample in one call. Use /load + /resample for large data."""
    import numpy as np

    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    token = _get_user_token(request)

    from server.schema_adapter import SchemaAdapter
    overrides = _get_session_overrides(session_id) if session_id else None
    adapter = SchemaAdapter.from_active_profile(catalog, schema, session_overrides=overrides)
    has_tend = adapter.has_tend()
    base_sql = adapter.ts_explorer_signal_fetch_query(container_id, channel_id)
    extra_filters = []
    if x_max is not None:
        extra_filters.append(f"tstart <= {x_max}")
    if x_min is not None:
        # For RLE schemas, an interval is in-range if it ends at or after x_min
        extra_filters.append(f"tend >= {x_min}" if has_tend else f"tstart >= {x_min}")
    sql = base_sql + ("".join(f" AND {f}" for f in extra_filters)) + " ORDER BY tstart"

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
        tstart = int(row[0]) if row[0] is not None else 0
        if has_tend:
            tend = int(row[1]) if row[1] is not None else tstart
            val = float(row[2]) if row[2] is not None else 0.0
        else:
            tend = tstart
            val = float(row[1]) if row[1] is not None else 0.0
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


def _load_synthetic(channel_ids: list[str]) -> dict:
    """Load synthetic data into cache."""
    from test.synthetic_ts import load_synthetic_data

    all_results = load_synthetic_data()
    cache = get_cache()

    channels = []
    for cid in channel_ids:
        cid_int = int(cid)
        info = all_results.get(cid_int, {})
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


# ---------------------------------------------------------------------------
# Session-scoped TS Viewer source overrides (UI flexibility layer)
# ---------------------------------------------------------------------------


_OVERRIDE_FIELDS = {
    "timeseries_table",
    "timeseries_time_col",
    "timeseries_value_col",
    "timeseries_container_match_col",
    "timeseries_channel_match_expr",
    "channel_container_id_col",
    "channel_id_col",
    "channel_name_col",
}


class SourceConfigPayload(BaseModel):
    overrides: dict[str, str | None]


@router.get("/source-config/{session_id}")
async def get_source_config(session_id: str):
    return {"overrides": _ts_session_overrides.get(session_id, {})}


@router.post("/source-config/{session_id}")
async def set_source_config(session_id: str, payload: SourceConfigPayload):
    cleaned = {k: v for k, v in payload.overrides.items() if k in _OVERRIDE_FIELDS}
    if cleaned:
        _ts_session_overrides[session_id] = cleaned
    else:
        _ts_session_overrides.pop(session_id, None)
    return {"overrides": _ts_session_overrides.get(session_id, {})}


@router.delete("/source-config/{session_id}")
async def clear_source_config(session_id: str):
    _ts_session_overrides.pop(session_id, None)
    return {"ok": True}


@router.post("/test-source")
async def test_source(payload: SourceConfigPayload, request: Request):
    """Validate a candidate source config by running SELECT ... LIMIT 1.
    Returns the resulting columns or the SQL error."""
    overrides = {k: v for k, v in payload.overrides.items() if k in _OVERRIDE_FIELDS}
    catalog = payload.overrides.get("__catalog", "")
    schema = payload.overrides.get("__schema", "")
    if not catalog or not schema:
        raise HTTPException(400, "Catalog and schema required")

    token = _get_user_token(request)
    table = overrides.get("timeseries_table") or ""
    if not table:
        raise HTTPException(400, "timeseries_table required")

    table_path = table if "." in table else f"{catalog}.{schema}.{table}"
    time_expr = overrides.get("timeseries_time_col") or "tstart"
    value_expr = overrides.get("timeseries_value_col") or "value"
    sql = f"SELECT {time_expr} AS tstart, {value_expr} AS value FROM {table_path} LIMIT 1"

    try:
        result = execute_sql(sql, user_token=token)
        return {"ok": True, "rows": result.get("rows", [])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/describe-table")
async def describe_table(catalog: str, schema: str, table: str, request: Request):
    """Return columns + types for a UC table — used by the configure-source modal."""
    _validate_id(catalog, "catalog")
    _validate_id(schema, "schema")
    _validate_id(table, "table")
    token = _get_user_token(request)
    sql = f"DESCRIBE TABLE {catalog}.{schema}.{table}"
    try:
        result = execute_sql(sql, user_token=token)
    except Exception as e:
        raise HTTPException(404, f"Could not describe table: {e}")
    columns = []
    for row in result.get("rows", []):
        if not row or not row[0] or row[0].startswith("#"):
            continue
        columns.append({"name": row[0], "type": row[1] if len(row) > 1 else ""})
    return {"columns": columns}
