"""State endpoint — /api/state, /api/advance-step, /api/set-metadata

Returns the current ReportState for a given session and manages wizard step progression.
"""

import logging
import os
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from server.agent import _sessions, _Session

from server.models import (
    AggregationDefinition,
    AvailableChannel,
    EvalType,
    Histogram1DDefinition,
    Histogram2DDefinition,
    HistogramDefinition,
    HistogramType,
    ReportState,
    SignalDefinition,
    SourceDataConfig,
    SourceDataMode,
    StatisticsDefinition,
    VehicleCandidate,
    VehicleConfig,
    WizardStep,
    WIZARD_ORDER,
)

logger = logging.getLogger(__name__)

def _get_mapping_table() -> str:
    """Return the mapping table path. Empty string if not configured."""
    return os.environ.get("IMPULSE_MAPPING_TABLE", "")


class MetadataPayload(BaseModel):
    name: str
    description: str = ""
    creator: str = ""


class SelectedCandidate(BaseModel):
    alias: str
    var_name: str
    channel_name: str = ""
    description: str = ""


class SelectCandidatesPayload(BaseModel):
    selected: list[SelectedCandidate]

class SourceDataPayload(BaseModel):
    mode: str  # "upload" | "existing"
    silver_catalog: str = ""
    silver_schema: str = ""
    upload_catalog: str = ""
    upload_schema: str = ""
    upload_volume: str = ""


router = APIRouter(prefix="/api", tags=["state"])


def _apply_source_data(session: _Session, payload: SourceDataPayload) -> None:
    """Apply source data payload fields to the session state."""
    mode = SourceDataMode(payload.mode)
    session.state.source_data.mode = mode
    if mode == SourceDataMode.EXISTING:
        session.state.source_data.silver_catalog = payload.silver_catalog
        session.state.source_data.silver_schema = payload.silver_schema
    elif mode == SourceDataMode.UPLOAD:
        session.state.source_data.upload_catalog = payload.upload_catalog
        session.state.source_data.upload_schema = payload.upload_schema
        session.state.source_data.upload_volume = payload.upload_volume
        if payload.upload_catalog and payload.upload_schema and payload.upload_volume:
            session.state.source_data.upload_volume_path = (
                f"/Volumes/{payload.upload_catalog}/{payload.upload_schema}/{payload.upload_volume}"
            )
        if payload.silver_catalog:
            session.state.source_data.silver_catalog = payload.silver_catalog
        if payload.silver_schema:
            session.state.source_data.silver_schema = payload.silver_schema


@router.post("/set-source-data/{session_id}")
async def set_source_data(session_id: str, payload: SourceDataPayload):
    """Configure the data source mode — upload raw files or point to existing Silver tables."""
    session = _sessions.get(session_id)
    if not session:
        session = _Session(session_id)
        _sessions[session_id] = session
    _apply_source_data(session, payload)
    return {"session_id": session_id, "report_state": session.state.model_dump()}


@router.post("/set-source-data")
async def set_source_data_new(payload: SourceDataPayload):
    """Configure data source and create a new session."""
    session_id = str(uuid.uuid4())
    session = _Session(session_id)
    _sessions[session_id] = session
    _apply_source_data(session, payload)
    return {"session_id": session_id, "report_state": session.state.model_dump()}


@router.post("/upload-mf4/{session_id}")
async def upload_mf4_files(
    session_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
):
    """Upload MF4 files to a Unity Catalog Volume.

    The session must already have upload_catalog, upload_schema, and upload_volume set
    (via set-source-data). Files are streamed to the Volume using the Databricks SDK.
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    sd = session.state.source_data
    if not sd.upload_catalog or not sd.upload_schema or not sd.upload_volume:
        raise HTTPException(
            400,
            "Volume location not configured. Set catalog, schema, and volume name first.",
        )

    volume_path = f"/Volumes/{sd.upload_catalog}/{sd.upload_schema}/{sd.upload_volume}"

    from server.config import IS_DATABRICKS_APP

    if IS_DATABRICKS_APP:
        from databricks.sdk import WorkspaceClient
        user_token = request.headers.get("X-Forwarded-Access-Token")
        if user_token:
            host = os.environ.get("DATABRICKS_HOST", "")
            w = WorkspaceClient(host=host, token=user_token)
        else:
            w = WorkspaceClient()
    else:
        from server.config import get_workspace_client
        w = get_workspace_client()

    uploaded: list[str] = []
    errors: list[str] = []

    for f in files:
        if not f.filename:
            continue
        fname = f.filename
        if not fname.lower().endswith(".mf4"):
            errors.append(f"Skipped '{fname}': only MF4 files are supported.")
            continue

        target = f"{volume_path}/{fname}"
        try:
            contents = await f.read()
            import io
            w.files.upload(target, io.BytesIO(contents), overwrite=True)
            uploaded.append(fname)
            if fname not in sd.uploaded_files:
                sd.uploaded_files.append(fname)
            logger.info("Uploaded %s to %s", fname, target)
        except Exception as e:
            logger.exception("Failed to upload %s", fname)
            errors.append(f"Failed to upload '{fname}': {e}")

    sd.upload_volume_path = volume_path

    return {
        "uploaded": uploaded,
        "errors": errors,
        "report_state": session.state.model_dump(),
    }


@router.get("/state/{session_id}", response_model=ReportState)
async def get_state(session_id: str) -> ReportState:
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return session.state


@router.post("/set-metadata/{session_id}")
async def set_metadata(session_id: str, payload: MetadataPayload):
    """Save report metadata directly from the form (bypasses LLM)."""
    session = _sessions.get(session_id)
    if not session:
        session = _Session(session_id)
        _sessions[session_id] = session

    clean_name = payload.name.strip().lower().replace(" ", "_").replace("-", "_")
    if not clean_name:
        raise HTTPException(400, "Report name is required.")

    session.state.name = clean_name
    session.state.description = payload.description or f"{clean_name} Report"
    session.state.creator = payload.creator
    session.state.data_sources.table_prefix = f"{clean_name}_report"

    return {"report_state": session.state.model_dump()}


@router.post("/set-metadata")
async def set_metadata_new(payload: MetadataPayload):
    """Save report metadata and create a new session."""
    session_id = str(uuid.uuid4())
    session = _Session(session_id)
    _sessions[session_id] = session

    clean_name = payload.name.strip().lower().replace(" ", "_").replace("-", "_")
    if not clean_name:
        raise HTTPException(400, "Report name is required.")

    session.state.name = clean_name
    session.state.description = payload.description or f"{clean_name} Report"
    session.state.creator = payload.creator
    session.state.data_sources.table_prefix = f"{clean_name}_report"

    return {"session_id": session_id, "report_state": session.state.model_dump()}


@router.post("/select-candidates/{session_id}")
async def select_candidates(session_id: str, payload: SelectCandidatesPayload):
    """Add user-selected signal candidates as physical signals."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    added = []
    for sel in payload.selected:
        if any(s.var_name == sel.var_name for s in session.state.signals):
            continue
        session.state.signals.append(
            SignalDefinition(
                var_name=sel.var_name,
                signal_type="physical",
                alias=sel.alias,
                channel_name=sel.channel_name or sel.alias,
                description=sel.description,
            )
        )
        added.append(sel.var_name)

    session.state.signal_candidates = []

    return {"added": added, "report_state": session.state.model_dump()}


@router.delete("/signal/{session_id}/{var_name}")
async def delete_signal(session_id: str, var_name: str):
    """Remove a signal by var_name."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    idx = next((i for i, s in enumerate(session.state.signals) if s.var_name == var_name), None)
    if idx is None:
        raise HTTPException(404, f"Signal '{var_name}' not found.")
    session.state.signals.pop(idx)
    # Also remove any aggregations referencing this signal
    session.state.aggregations = [
        a for a in session.state.aggregations
        if not (
            (hasattr(a, "signal_ref") and a.signal_ref == var_name)
            or (hasattr(a, "x_signal_ref") and a.x_signal_ref == var_name)
            or (hasattr(a, "y_signal_ref") and a.y_signal_ref == var_name)
            or (hasattr(a, "signal_refs") and var_name in a.signal_refs)
        )
    ]
    return {"report_state": session.state.model_dump()}


class UpdateSignalPayload(BaseModel):
    var_name: str
    expression: str | None = None
    eval_type: str | None = None
    description: str | None = None
    alias: str | None = None


@router.put("/signal/{session_id}/{var_name}")
async def update_signal(session_id: str, var_name: str, payload: UpdateSignalPayload):
    """Update an existing signal."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    sig = next((s for s in session.state.signals if s.var_name == var_name), None)
    if sig is None:
        raise HTTPException(404, f"Signal '{var_name}' not found.")
    if payload.expression is not None:
        sig.expression = payload.expression
    if payload.eval_type is not None:
        sig.eval_type = EvalType(payload.eval_type)
    if payload.description is not None:
        sig.description = payload.description
    if payload.alias is not None:
        sig.alias = payload.alias
    # Handle rename
    if payload.var_name != var_name:
        if any(s.var_name == payload.var_name for s in session.state.signals if s is not sig):
            raise HTTPException(400, f"Signal '{payload.var_name}' already exists.")
        sig.var_name = payload.var_name
    return {"report_state": session.state.model_dump()}


class AddVirtualSignalPayload(BaseModel):
    var_name: str
    expression: str
    eval_type: str = "SampleSeries"
    description: str = ""


@router.post("/add-virtual-signal/{session_id}")
async def add_virtual_signal(session_id: str, payload: AddVirtualSignalPayload):
    """Add a virtual signal via the UI (not chat)."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if any(s.var_name == payload.var_name for s in session.state.signals):
        raise HTTPException(400, f"Signal '{payload.var_name}' already exists.")
    session.state.signals.append(
        SignalDefinition(
            var_name=payload.var_name,
            signal_type="virtual",
            expression=payload.expression,
            eval_type=EvalType(payload.eval_type),
            description=payload.description,
        )
    )
    return {"report_state": session.state.model_dump()}


@router.get("/channel-catalog/{session_id}")
async def channel_catalog(session_id: str, request: Request):
    """Discover available channels from the silver layer after ingest.

    Queries channel_tags + channel_metrics to build a list of distinct channels
    with their metadata (name, unit, sample count, min/max/mean, sample rate).
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    sd = session.state.source_data
    catalog = sd.silver_catalog
    schema = sd.silver_schema
    if not catalog or not schema:
        logger.warning("Channel catalog: silver_catalog=%s, silver_schema=%s — not configured", catalog, schema)
        raise HTTPException(400, "Silver layer catalog/schema not configured.")

    from server.mcp_tools import execute_sql

    user_token = request.headers.get("X-Forwarded-Access-Token")
    logger.info("Fetching channel catalog from %s.%s", catalog, schema)

    # Filter channels to only those belonging to selected vehicles' containers
    vehicle_ids = [v.vehicle_id for v in session.state.vehicles]
    if vehicle_ids:
        ids_str = ", ".join(f"'{v}'" for v in vehicle_ids)
        vehicle_filter = (
            f"JOIN {catalog}.{schema}.container_tags ct_veh "
            f"  ON t_name.container_id = ct_veh.container_id "
            f"  AND ct_veh.key = 'vehicle_key' "
            f"  AND ct_veh.value IN ({ids_str}) "
        )
    else:
        vehicle_filter = ""

    sql = (
        f"SELECT t_name.value AS channel_name, "
        f"       COALESCE(t_unit.value, '') AS unit, "
        f"       CAST(SUM(m.sample_count) AS INT) AS sample_count, "
        f"       MIN(m.min) AS min_value, "
        f"       MAX(m.max) AS max_value, "
        f"       AVG(m.mean) AS mean_value, "
        f"       AVG(m.sample_rate) AS sample_rate, "
        f"       COUNT(DISTINCT t_name.container_id) AS container_count "
        f"FROM {catalog}.{schema}.channel_tags t_name "
        f"LEFT JOIN {catalog}.{schema}.channel_tags t_unit "
        f"  ON t_name.container_id = t_unit.container_id "
        f"  AND t_name.channel_id = t_unit.channel_id "
        f"  AND t_unit.key = 'unit' "
        f"JOIN {catalog}.{schema}.channel_metrics m "
        f"  ON t_name.container_id = m.container_id "
        f"  AND t_name.channel_id = m.channel_id "
        f"{vehicle_filter}"
        f"WHERE t_name.key = 'channel_name' "
        f"GROUP BY t_name.value, t_unit.value "
        f"ORDER BY channel_name"
    )
    try:
        result = execute_sql(sql, user_token=user_token)
    except Exception as e:
        logger.exception("Failed to query channel catalog")
        raise HTTPException(502, f"Channel catalog query failed: {e}")

    col_map = {c.lower(): i for i, c in enumerate(result["columns"])}

    channels: list[AvailableChannel] = []
    for row in result["rows"]:
        def _get(col: str, default=""):
            idx = col_map.get(col, -1)
            return row[idx] if 0 <= idx < len(row) else default

        try:
            channels.append(AvailableChannel(
                channel_name=_get("channel_name", ""),
                unit=_get("unit", ""),
                sample_count=int(float(_get("sample_count", "0"))),
                min_value=float(_get("min_value")) if _get("min_value") not in ("", "NULL") else None,
                max_value=float(_get("max_value")) if _get("max_value") not in ("", "NULL") else None,
                mean_value=float(_get("mean_value")) if _get("mean_value") not in ("", "NULL") else None,
                sample_rate=float(_get("sample_rate")) if _get("sample_rate") not in ("", "NULL") else None,
                container_count=int(float(_get("container_count", "0"))),
            ))
        except (ValueError, IndexError):
            continue

    session.state.available_channels = channels

    # Auto-populate data sources if not already set
    _auto_populate_silver_data_sources(session)

    return {
        "channels": [c.model_dump() for c in channels],
        "report_state": session.state.model_dump(),
    }


def _auto_populate_silver_data_sources(session: _Session) -> None:
    """Auto-fill data_sources from the silver layer tables produced by ingest."""
    sd = session.state.source_data
    catalog = sd.silver_catalog
    schema = sd.silver_schema
    if not catalog or not schema:
        return

    ds = session.state.data_sources
    prefix = f"{catalog}.{schema}"

    if not ds.channels:
        ds.channels = [f"{prefix}.bronze_channels"]
    if not ds.container_metrics:
        ds.container_metrics = f"{prefix}.container_metrics"
    if not ds.channel_metrics:
        ds.channel_metrics = f"{prefix}.channel_metrics"
    if not ds.destination_catalog:
        ds.destination_catalog = catalog
    if not ds.destination_schema:
        ds.destination_schema = schema


@router.post("/fetch-vehicle-candidates/{session_id}")
async def fetch_vehicle_candidates(session_id: str, request: Request):
    """Query for available vehicles.

    Two modes:
    - If IMPULSE_MAPPING_TABLE is configured, query it for test_object_name (Mercedes/legacy).
    - Otherwise, discover vehicles from the silver layer container_tags (vehicle_key).
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    from server.mcp_tools import execute_sql

    user_token = request.headers.get("X-Forwarded-Access-Token")

    mapping_table = _get_mapping_table()
    if mapping_table:
        # Legacy: query mapping table
        sql = (
            f"SELECT test_object_name, COUNT(*) AS datapoint_count "
            f"FROM {mapping_table} "
            f"GROUP BY test_object_name "
            f"ORDER BY test_object_name"
        )
        name_col = "test_object_name"
        count_col = "datapoint_count"
    else:
        # Silver layer: discover vehicles from container_tags
        sd = session.state.source_data
        catalog = sd.silver_catalog
        schema = sd.silver_schema
        if not catalog or not schema:
            raise HTTPException(400, "Silver layer catalog/schema not configured and no mapping table set.")
        sql = (
            f"SELECT value AS vehicle_id, COUNT(DISTINCT container_id) AS container_count "
            f"FROM {catalog}.{schema}.container_tags "
            f"WHERE key = 'vehicle_key' AND value IS NOT NULL AND value != 'NA' "
            f"GROUP BY value "
            f"ORDER BY value"
        )
        name_col = "vehicle_id"
        count_col = "container_count"

    try:
        result = execute_sql(sql, user_token=user_token)
    except Exception as e:
        logger.exception("Failed to query vehicle candidates")
        raise HTTPException(502, f"SQL query failed: {e}")

    col_map = {c.lower(): i for i, c in enumerate(result["columns"])}
    name_idx = col_map.get(name_col, 0)
    count_idx = col_map.get(count_col, 1)

    candidates = []
    seen: set[str] = set()
    for row in result["rows"]:
        vid = row[name_idx] if name_idx < len(row) else ""
        if not vid or vid in seen:
            continue
        seen.add(vid)
        cnt = 0
        try:
            cnt = int(float(row[count_idx])) if count_idx < len(row) else 0
        except (ValueError, IndexError):
            pass
        candidates.append(VehicleCandidate(vehicle_id=vid, datapoint_count=cnt))

    session.state.vehicle_candidates = candidates
    session.state.vehicle_col_name = "test_object_name" if mapping_table else "vehicle_key"
    return {"candidates": [c.model_dump() for c in candidates], "report_state": session.state.model_dump()}


class SelectedVehicle(BaseModel):
    vehicle_id: str
    start_ts: str = ""


class SelectVehiclesPayload(BaseModel):
    selected: list[SelectedVehicle]


@router.post("/select-vehicles/{session_id}")
async def select_vehicles(session_id: str, payload: SelectVehiclesPayload, request: Request):
    """Add user-selected vehicles to the report state and auto-resolve data sources."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    user_token = request.headers.get("X-Forwarded-Access-Token")

    added = []
    vehicle_ids = []
    for sel in payload.selected:
        if any(v.vehicle_id == sel.vehicle_id for v in session.state.vehicles):
            continue
        session.state.vehicles.append(
            VehicleConfig(vehicle_id=sel.vehicle_id, start_ts=sel.start_ts, col_name=session.state.vehicle_col_name)
        )
        added.append(sel.vehicle_id)
        vehicle_ids.append(sel.vehicle_id)

    session.state.vehicle_candidates = []

    if vehicle_ids:
        try:
            _auto_resolve_data_sources(session, vehicle_ids, user_token=user_token)
        except Exception:
            logger.exception("Auto-resolve data sources failed (non-fatal)")

    return {"added": added, "report_state": session.state.model_dump()}


@router.delete("/vehicle/{session_id}/{vehicle_id}")
async def delete_vehicle(session_id: str, vehicle_id: str):
    """Remove a vehicle by ID."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    idx = next((i for i, v in enumerate(session.state.vehicles) if v.vehicle_id == vehicle_id), None)
    if idx is None:
        raise HTTPException(404, f"Vehicle '{vehicle_id}' not found.")
    session.state.vehicles.pop(idx)
    return {"report_state": session.state.model_dump()}


def _auto_resolve_data_sources(session: _Session, vehicle_ids: list[str], user_token: str | None = None):
    """Query the mapping table to auto-fill data source config for the selected vehicles.

    Skipped when no mapping table is configured — data sources are already
    populated from the silver layer by _auto_populate_silver_data_sources().
    """
    mapping_table = _get_mapping_table()
    if not mapping_table:
        # Silver layer mode: data sources already auto-populated
        _auto_populate_silver_data_sources(session)
        return

    from server.mcp_tools import execute_sql

    ids_str = ", ".join(f"'{v}'" for v in vehicle_ids)
    sql = (
        f"SELECT DISTINCT test_object_name, datapoint_location, "
        f"measurement_session_metric, signal_metric_location "
        f"FROM {mapping_table} "
        f"WHERE test_object_name IN ({ids_str})"
    )
    result = execute_sql(sql, user_token=user_token)
    if result["row_count"] == 0:
        return

    col_map = {c.lower(): i for i, c in enumerate(result["columns"])}
    dp_idx = col_map.get("datapoint_location", -1)
    cm_idx = col_map.get("measurement_session_metric", -1)
    sm_idx = col_map.get("signal_metric_location", -1)

    channels: set[str] = set()
    container_metrics = ""
    channel_metrics = ""
    for row in result["rows"]:
        if dp_idx >= 0 and dp_idx < len(row) and row[dp_idx]:
            channels.add(row[dp_idx])
        if cm_idx >= 0 and cm_idx < len(row) and row[cm_idx] and not container_metrics:
            container_metrics = row[cm_idx]
        if sm_idx >= 0 and sm_idx < len(row) and row[sm_idx] and not channel_metrics:
            channel_metrics = row[sm_idx]

    ds = session.state.data_sources
    if channels:
        ds.channels = sorted(channels)
    if container_metrics:
        ds.container_metrics = container_metrics
    if channel_metrics:
        ds.channel_metrics = channel_metrics
    if not ds.destination_catalog and session.state.source_data.silver_catalog:
        ds.destination_catalog = session.state.source_data.silver_catalog
    if not ds.destination_schema and session.state.source_data.silver_schema:
        ds.destination_schema = session.state.source_data.silver_schema

    logger.info(
        "Auto-resolved data sources: %d channels, container_metrics=%s, channel_metrics=%s",
        len(ds.channels), ds.container_metrics, ds.channel_metrics,
    )


class VehicleTimestamp(BaseModel):
    vehicle_id: str
    start_ts: str = ""
    stop_ts: str | None = None


class UpdateTimestampsPayload(BaseModel):
    global_start_ts: str = ""
    global_stop_ts: str | None = None
    per_vehicle: list[VehicleTimestamp] = []


def _normalize_ts(value: str | None) -> str | None:
    """Convert datetime-local format (2025-10-01T00:00) to expected format (2025-10-01 00:00:00)."""
    if not value:
        return value
    v = value.replace("T", " ")
    if len(v) == 16:
        v += ":00"
    return v


@router.post("/update-vehicle-timestamps/{session_id}")
async def update_vehicle_timestamps(session_id: str, payload: UpdateTimestampsPayload):
    """Set start/stop timestamps globally or per vehicle."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    overrides = {v.vehicle_id: v for v in payload.per_vehicle}

    for vehicle in session.state.vehicles:
        override = overrides.get(vehicle.vehicle_id)
        if override:
            vehicle.start_ts = _normalize_ts(override.start_ts) or ""
            vehicle.stop_ts = _normalize_ts(override.stop_ts)
        else:
            if payload.global_start_ts:
                vehicle.start_ts = _normalize_ts(payload.global_start_ts) or ""
            if payload.global_stop_ts is not None:
                vehicle.stop_ts = _normalize_ts(payload.global_stop_ts)

    return {"report_state": session.state.model_dump()}


@router.get("/data-time-range/{session_id}")
async def data_time_range(session_id: str, request: Request):
    """Query the actual time range of data for the selected vehicles.

    Uses container_metrics (start_dt, stop_dt) joined with container_tags
    to filter by selected vehicles. Returns min(start_dt) and max(stop_dt).
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    sd = session.state.source_data
    catalog = sd.silver_catalog
    schema = sd.silver_schema
    if not catalog or not schema:
        raise HTTPException(400, "Silver layer catalog/schema not configured.")

    from server.mcp_tools import execute_sql

    user_token = request.headers.get("X-Forwarded-Access-Token")

    vehicle_ids = [v.vehicle_id for v in session.state.vehicles]
    if vehicle_ids:
        ids_str = ", ".join(f"'{v}'" for v in vehicle_ids)
        vehicle_join = (
            f"JOIN {catalog}.{schema}.container_tags ct "
            f"  ON m.container_id = ct.container_id "
            f"  AND ct.key = 'vehicle_key' "
            f"  AND ct.value IN ({ids_str}) "
        )
    else:
        vehicle_join = ""

    sql = (
        f"SELECT MIN(m.start_dt) AS min_start, MAX(m.stop_dt) AS max_stop "
        f"FROM {catalog}.{schema}.container_metrics m "
        f"{vehicle_join}"
    )

    try:
        result = execute_sql(sql, user_token=user_token)
    except Exception as e:
        logger.exception("Failed to query data time range")
        raise HTTPException(502, f"Time range query failed: {e}")

    col_map = {c.lower(): i for i, c in enumerate(result["columns"])}
    min_idx = col_map.get("min_start", 0)
    max_idx = col_map.get("max_stop", 1)

    min_start = None
    max_stop = None
    if result["rows"]:
        row = result["rows"][0]
        min_start = row[min_idx] if min_idx < len(row) and row[min_idx] not in ("", "NULL", None) else None
        max_stop = row[max_idx] if max_idx < len(row) and row[max_idx] not in ("", "NULL", None) else None

    return {"min_start": min_start, "max_stop": max_stop}


@router.post("/go-back/{session_id}")
async def go_back(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    idx = WIZARD_ORDER.index(session.state.wizard_step)
    if idx <= 0:
        raise HTTPException(400, "Already at the first step.")

    session.state.wizard_step = WIZARD_ORDER[idx - 1]
    return {"wizard_step": session.state.wizard_step.value, "report_state": session.state.model_dump()}


def _validate_step_complete(state: ReportState) -> str | None:
    """Return an error message if the current wizard step is incomplete, else None."""
    step = state.wizard_step
    if step == WizardStep.SOURCE_DATA:
        if state.source_data.mode == SourceDataMode.NONE:
            return "Please choose a data source: upload raw files or point to existing Silver layer tables."
        if state.source_data.mode == SourceDataMode.EXISTING:
            if not state.source_data.silver_catalog or not state.source_data.silver_schema:
                return "Please provide the catalog and schema for your existing Silver layer tables."
        if state.source_data.mode == SourceDataMode.UPLOAD:
            if not state.source_data.upload_volume_path:
                return "Please configure the Volume location (catalog, schema, volume name)."
            if not state.source_data.uploaded_files:
                return "Please upload at least one MF4 file."
    elif step == WizardStep.REPORT_NAME:
        if not state.name:
            return "Please set a report name before continuing."
    elif step == WizardStep.VEHICLES:
        if len(state.vehicles) == 0:
            return "Please add at least one vehicle before continuing."
    elif step == WizardStep.CHANNELS:
        if len(state.signals) == 0:
            return "Please add at least one signal before continuing."
    elif step == WizardStep.AGGREGATIONS:
        if len(state.aggregations) == 0:
            return "Please add at least one aggregation before continuing."
    return None


class ClusterConfigPayload(BaseModel):
    use_all_purpose_cluster: bool = False
    all_purpose_cluster_id: str = ""


@router.post("/set-cluster-config/{session_id}")
async def set_cluster_config(session_id: str, payload: ClusterConfigPayload, request: Request):
    """Configure whether the report_orchestration task runs on a job cluster or all-purpose cluster.

    When switching to all-purpose mode with an empty cluster ID, the stored
    cluster ID from Lakebase is auto-populated.
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    cluster_id = payload.all_purpose_cluster_id.strip()

    if payload.use_all_purpose_cluster and not cluster_id:
        from server.config import IS_DATABRICKS_APP
        if IS_DATABRICKS_APP:
            from server.token_store import get_cluster_id
            email = request.headers.get("X-Forwarded-Email", "")
            if email:
                cluster_id = get_cluster_id(email)

    session.state.use_all_purpose_cluster = payload.use_all_purpose_cluster
    session.state.all_purpose_cluster_id = cluster_id

    return {"report_state": session.state.model_dump()}


@router.post("/advance-step/{session_id}")
async def advance_step(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    state = session.state
    error = _validate_step_complete(state)
    if error:
        raise HTTPException(400, error)

    idx = WIZARD_ORDER.index(state.wizard_step)
    if idx >= len(WIZARD_ORDER) - 1:
        raise HTTPException(400, "Already at the final step.")

    state.wizard_step = WIZARD_ORDER[idx + 1]
    return {"wizard_step": state.wizard_step.value, "report_state": state.model_dump()}


# ---------------------------------------------------------------------------
# Histogram builder endpoints
# ---------------------------------------------------------------------------


class SuggestBinsPayload(BaseModel):
    histogram_type: str
    signal_ref: str


class AddHistogramPayload(BaseModel):
    name: str
    histogram_type: str
    signal_ref: str
    bins: list[float]
    bins_unit: str | None = None
    values_unit: str | None = None
    description: str = ""
    max_duration: float | None = None
    event_signal_ref: str | None = None
    weight_signal_ref: str | None = None
    weight_const: float | None = None


@router.post("/suggest-bins/{session_id}")
async def suggest_bins(session_id: str, payload: SuggestBinsPayload):
    """Use a focused LLM call to suggest bin edges for a histogram."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    signal = next(
        (s for s in session.state.signals if s.var_name == payload.signal_ref), None
    )
    if not signal:
        raise HTTPException(400, f"Signal '{payload.signal_ref}' not found.")

    signal_desc = signal.description or signal.alias or signal.var_name

    prompt = (
        "You are an automotive measurement data analysis expert. "
        "Suggest appropriate histogram bin edges for the following setup.\n\n"
        f"Histogram type: {payload.histogram_type}\n"
        f"Signal: {signal.var_name}\n"
        f"Signal description / alias: {signal_desc}\n"
        f"Signal type: {signal.signal_type}\n\n"
        "Return ONLY a JSON object (no markdown fences) with these fields:\n"
        '- "bins": array of numeric bin edge values (typically 10-20 edges)\n'
        '- "bins_unit": unit label for the bins axis (e.g. "rpm", "°C", "km/h")\n'
        '- "description": a short human-readable description for the histogram\n'
        '- "name": a suggested name following the convention <short_name>_p1\n\n'
        "Consider the physical meaning of the signal. For temperature signals use "
        "ranges like -40 to 160°C, for engine speed 0-7000 rpm, etc. "
        "Include catch-all boundaries (-9999.0 / 9999.0) only if they make sense."
    )

    import json

    from server.agent import _get_openai_client
    from server.config import SERVING_ENDPOINT

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model=SERVING_ENDPOINT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        text = response.choices[0].message.content or ""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        suggestion = json.loads(text)
    except Exception as e:
        logger.exception("LLM suggest-bins call failed")
        raise HTTPException(502, f"Bin suggestion failed: {e}")

    return {
        "bins": suggestion.get("bins", []),
        "bins_unit": suggestion.get("bins_unit", ""),
        "description": suggestion.get("description", ""),
        "name": suggestion.get("name", f"{payload.signal_ref}_{payload.histogram_type}_p1"),
    }


@router.post("/add-histogram/{session_id}")
async def add_histogram(session_id: str, payload: AddHistogramPayload):
    """Add a histogram directly from the builder UI (bypasses LLM agent)."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    state = session.state

    if not any(s.var_name == payload.signal_ref for s in state.signals):
        raise HTTPException(400, f"Signal '{payload.signal_ref}' does not exist.")

    if any(a.name == payload.name for a in state.aggregations):
        raise HTTPException(400, f"Aggregation '{payload.name}' already exists.")

    if not payload.bins or len(payload.bins) < 2:
        raise HTTPException(400, "At least 2 bin edges are required.")

    state.aggregations.append(
        Histogram1DDefinition(
            name=payload.name,
            histogram_type=HistogramType(payload.histogram_type),
            signal_ref=payload.signal_ref,
            bins=payload.bins,
            bins_unit=payload.bins_unit,
            values_unit=payload.values_unit,
            description=payload.description,
            max_duration=payload.max_duration,
            event_signal_ref=payload.event_signal_ref,
            weight_signal_ref=payload.weight_signal_ref,
            weight_const=payload.weight_const,
        )
    )

    return {"report_state": state.model_dump()}


@router.delete("/aggregation/{session_id}/{name}")
async def delete_aggregation(session_id: str, name: str):
    """Remove an aggregation by name."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    state = session.state
    idx = next((i for i, a in enumerate(state.aggregations) if a.name == name), None)
    if idx is None:
        raise HTTPException(404, f"Aggregation '{name}' not found.")

    state.aggregations.pop(idx)
    return {"report_state": state.model_dump()}


@router.put("/aggregation/{session_id}/{name}")
async def update_aggregation(session_id: str, name: str, payload: AddHistogramPayload):
    """Replace an existing aggregation by name."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    state = session.state
    idx = next((i for i, a in enumerate(state.aggregations) if a.name == name), None)
    if idx is None:
        raise HTTPException(404, f"Aggregation '{name}' not found.")

    if not any(s.var_name == payload.signal_ref for s in state.signals):
        raise HTTPException(400, f"Signal '{payload.signal_ref}' does not exist.")

    if not payload.bins or len(payload.bins) < 2:
        raise HTTPException(400, "At least 2 bin edges are required.")

    # If name changed, check uniqueness
    if payload.name != name and any(a.name == payload.name for a in state.aggregations):
        raise HTTPException(400, f"Aggregation '{payload.name}' already exists.")

    state.aggregations[idx] = Histogram1DDefinition(
        name=payload.name,
        histogram_type=HistogramType(payload.histogram_type),
        signal_ref=payload.signal_ref,
        bins=payload.bins,
        bins_unit=payload.bins_unit,
        values_unit=payload.values_unit,
        description=payload.description,
        max_duration=payload.max_duration,
        event_signal_ref=payload.event_signal_ref,
        weight_signal_ref=payload.weight_signal_ref,
        weight_const=payload.weight_const,
    )

    return {"report_state": state.model_dump()}


# ---------------------------------------------------------------------------
# Histogram 2D builder endpoint
# ---------------------------------------------------------------------------


class AddHistogram2DPayload(BaseModel):
    name: str
    x_signal_ref: str
    y_signal_ref: str
    x_bins: list[float]
    y_bins: list[float]
    x_bins_unit: str | None = None
    y_bins_unit: str | None = None
    x_signal_name: str | None = None
    y_signal_name: str | None = None
    values_unit: str | None = None
    description: str = ""


@router.post("/add-histogram-2d/{session_id}")
async def add_histogram_2d(session_id: str, payload: AddHistogram2DPayload):
    """Add a 2D histogram directly from the builder UI."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    state = session.state

    if not any(s.var_name == payload.x_signal_ref for s in state.signals):
        raise HTTPException(400, f"X signal '{payload.x_signal_ref}' does not exist.")
    if not any(s.var_name == payload.y_signal_ref for s in state.signals):
        raise HTTPException(400, f"Y signal '{payload.y_signal_ref}' does not exist.")

    if any(a.name == payload.name for a in state.aggregations):
        raise HTTPException(400, f"Aggregation '{payload.name}' already exists.")

    if not payload.x_bins or len(payload.x_bins) < 2:
        raise HTTPException(400, "At least 2 X bin edges are required.")
    if not payload.y_bins or len(payload.y_bins) < 2:
        raise HTTPException(400, "At least 2 Y bin edges are required.")

    state.aggregations.append(
        Histogram2DDefinition(
            name=payload.name,
            x_signal_ref=payload.x_signal_ref,
            y_signal_ref=payload.y_signal_ref,
            x_bins=payload.x_bins,
            y_bins=payload.y_bins,
            x_bins_unit=payload.x_bins_unit,
            y_bins_unit=payload.y_bins_unit,
            x_signal_name=payload.x_signal_name,
            y_signal_name=payload.y_signal_name,
            values_unit=payload.values_unit,
            description=payload.description,
        )
    )

    return {"report_state": state.model_dump()}


# ---------------------------------------------------------------------------
# Statistics builder endpoint
# ---------------------------------------------------------------------------

VALID_STAT_LABELS = {"min", "max", "mean", "median", "std", "count"}


class AddStatisticsPayload(BaseModel):
    name: str
    signal_refs: list[str]
    stat_labels: list[str] = ["min", "max", "mean", "median", "std", "count"]
    event_signal_ref: str | None = None
    signal_names: list[str] | None = None
    description: str = ""


@router.post("/add-statistics/{session_id}")
async def add_statistics(session_id: str, payload: AddStatisticsPayload):
    """Add a statistics aggregation directly from the builder UI."""
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    state = session.state

    if not payload.signal_refs:
        raise HTTPException(400, "At least one signal is required.")

    for ref in payload.signal_refs:
        if not any(s.var_name == ref for s in state.signals):
            raise HTTPException(400, f"Signal '{ref}' does not exist.")

    if any(a.name == payload.name for a in state.aggregations):
        raise HTTPException(400, f"Aggregation '{payload.name}' already exists.")

    invalid = set(payload.stat_labels) - VALID_STAT_LABELS
    if invalid:
        raise HTTPException(400, f"Invalid stat labels: {invalid}")

    state.aggregations.append(
        StatisticsDefinition(
            name=payload.name,
            signal_refs=payload.signal_refs,
            stat_labels=payload.stat_labels,
            event_signal_ref=payload.event_signal_ref,
            signal_names=payload.signal_names,
            description=payload.description,
        )
    )

    return {"report_state": state.model_dump()}
