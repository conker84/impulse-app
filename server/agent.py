"""LLM agent with tool-calling for building Impulse reports.

Uses Databricks Foundation Model API (OpenAI-compatible) with tools that
map 1:1 to Impulse skill steps.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from server.config import SERVING_ENDPOINT, get_workspace_client

logger = logging.getLogger(__name__)
from server.mcp_tools import call_mcp_tool, discover_mcp_tools
from server.models import (
    ChatMessage,
    DataSourceConfig,
    DeploymentStatus,
    EvalType,
    Histogram1DDefinition,
    Histogram2DDefinition,
    HistogramDefinition,
    HistogramType,
    ReportState,
    SignalCandidate,
    SignalDefinition,
    StatisticsDefinition,
    VehicleConfig,
    WizardStep,
)
from server.skill_loader import build_system_prompt, load_skill_full

# ---------------------------------------------------------------------------
# Session store (in-memory; swap for Lakebase in production)
# ---------------------------------------------------------------------------

_sessions: dict[str, _Session] = {}


class _Session:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = ReportState()
        self.messages: list[dict[str, Any]] = []


def _get_session(session_id: str | None) -> _Session:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    sid = session_id or str(uuid.uuid4())
    sess = _Session(sid)
    _sessions[sid] = sess
    return sess


# ---------------------------------------------------------------------------
# Tool definitions (map to skill steps)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_physical_signal",
            "description": (
                "Add a physical signal using a channel alias. "
                "From define-channels skill step 3."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "var_name": {"type": "string", "description": "Python variable name"},
                    "alias": {"type": "string", "description": "ChannelAliasName_withScope value"},
                    "description": {"type": "string", "description": "Human-readable description"},
                },
                "required": ["var_name", "alias"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_virtual_signal",
            "description": (
                "Add a virtual/derived signal built from existing signals. "
                "From define-channels skill step 4. "
                "Expression uses Python syntax referencing var_names of existing signals."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "var_name": {"type": "string", "description": "Python variable name"},
                    "expression": {
                        "type": "string",
                        "description": "Python expression, e.g. 'Eng_Spd.where((Eng_Spd >= 0) & (Eng_Spd <= 7000))'",
                    },
                    "eval_type": {
                        "type": "string",
                        "enum": ["SampleSeries", "Intervals", "PointsInTime", "PitSeries"],
                        "description": "Resulting expression type",
                    },
                    "description": {"type": "string"},
                },
                "required": ["var_name", "expression", "eval_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_signal_candidates",
            "description": (
                "MANDATORY after identifying channels for the user. Present signal candidates to the user "
                "as checkboxes in the right panel. NEVER list channel names in chat text — always use this tool. "
                "For silver layer channels, set alias=channel_name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "alias": {"type": "string", "description": "Channel identifier (channel_name or alias)"},
                                "channel_name": {"type": "string", "description": "Physical channel name from the data"},
                                "unit": {"type": "string", "description": "Unit of measurement (e.g. rpm, °C, km/h)"},
                                "description": {"type": "string", "description": "Human-readable description inferred from name/unit/context"},
                            },
                            "required": ["alias"],
                        },
                        "description": "List of channel candidates to present to the user",
                    },
                },
                "required": ["candidates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_histogram",
            "description": (
                "Add a 1D histogram visualization. "
                "From create-histogram-1d skill steps 2-5."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Unique histogram ID, convention: <short_name>_p<page>",
                    },
                    "histogram_type": {
                        "type": "string",
                        "enum": ["duration", "distance", "duration_count", "event_count"],
                    },
                    "signal_ref": {
                        "type": "string",
                        "description": "Key in signals dict (var_name of a signal)",
                    },
                    "bins": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Bin edge values",
                    },
                    "bins_unit": {"type": "string"},
                    "max_duration": {
                        "type": "number",
                        "description": "Max sample duration in nanoseconds (duration type only)",
                    },
                    "event_signal_ref": {
                        "type": "string",
                        "description": "Event trigger signal ref (event_count type only)",
                    },
                    "weight_const": {"type": "number"},
                    "description": {"type": "string"},
                },
                "required": ["name", "histogram_type", "signal_ref", "bins"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_aggregation",
            "description": (
                "Remove an aggregation (histogram, statistics, etc.) by name. "
                "Use when the user wants to delete or redo an aggregation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the aggregation to remove",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_histogram_2d",
            "description": (
                "Add a 2D histogram (heatmap) visualization with two signal axes. "
                "Use when the user wants to see how two signals correlate (e.g. engine speed vs torque)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Unique histogram ID, convention: <short_name>_2d_p<page>",
                    },
                    "x_signal_ref": {
                        "type": "string",
                        "description": "var_name of the X-axis signal",
                    },
                    "y_signal_ref": {
                        "type": "string",
                        "description": "var_name of the Y-axis signal",
                    },
                    "x_bins": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Bin edges for the X axis",
                    },
                    "y_bins": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Bin edges for the Y axis",
                    },
                    "x_bins_unit": {"type": "string", "description": "Unit for X bins axis"},
                    "y_bins_unit": {"type": "string", "description": "Unit for Y bins axis"},
                    "description": {"type": "string"},
                },
                "required": ["name", "x_signal_ref", "y_signal_ref", "x_bins", "y_bins"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_statistics",
            "description": (
                "Add a statistics aggregation that computes min, max, mean, median, std, and/or count "
                "for one or more signals. Use when the user wants summary statistics instead of histograms."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Unique aggregation ID, convention: <short_name>_stats_p<page>",
                    },
                    "signal_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "var_names of signals to compute statistics for",
                    },
                    "stat_labels": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["min", "max", "mean", "median", "std", "count"],
                        },
                        "description": "Which statistics to compute (default: all)",
                    },
                    "event_signal_ref": {
                        "type": "string",
                        "description": "Optional event signal ref to compute stats at event points",
                    },
                    "description": {"type": "string"},
                },
                "required": ["name", "signal_refs"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_report_metadata",
            "description": "Set report name, description, and creator. From create-report skill step 2.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Report name (lowercase, underscores, no spaces)",
                    },
                    "description": {"type": "string"},
                    "creator": {"type": "string", "description": "Name of the report creator"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_vehicle",
            "description": "Add or update a vehicle configuration. From configure-report skill vehicles section.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vehicle_id": {"type": "string"},
                    "col_name": {"type": "string", "description": "Column name, default test_object_name"},
                    "start_ts": {"type": "string", "description": "Start timestamp YYYY-MM-DD HH:MM:SS"},
                    "stop_ts": {"type": "string", "description": "Optional stop timestamp"},
                },
                "required": ["vehicle_id", "start_ts"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_data_sources",
            "description": (
                "Configure data source and destination tables. "
                "Resolve channels/container_metrics/channel_metrics from the mapping table query. "
                "Aliases and destination are optional. Destination defaults to the Silver layer catalog/schema from the Source Data step."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "container_metrics": {"type": "string", "description": "From mapping table column: measurement_session_metric"},
                    "channel_metrics": {"type": "string", "description": "From mapping table column: signal_metric_location"},
                    "channels": {"type": "array", "items": {"type": "string"}, "description": "From mapping table column: datapoint_location (one per vehicle)"},
                    "aliases": {"type": "string", "description": "Channel alias lookup table (optional)"},
                    "aliases_copy_table_name": {"type": "string", "description": "Default: channel_aliases"},
                    "device_aliases": {"type": "string", "description": "Device alias lookup table (optional)"},
                    "device_aliases_copy_table_name": {"type": "string", "description": "Default: device_aliases"},
                    "destination_catalog": {"type": "string", "description": "Destination catalog (defaults to Silver layer catalog)"},
                    "destination_schema": {"type": "string", "description": "Destination schema (defaults to Silver layer schema)"},
                    "table_prefix": {"type": "string", "description": "Default: <report_name>_report"},
                },
                "required": ["container_metrics", "channel_metrics", "channels"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_code",
            "description": "Generate and return a preview of the Python code and config JSON that will be created.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": (
                "Load the full documentation for an Impulse skill. Call this BEFORE performing "
                "any skill-specific task to get detailed procedures, code patterns, and reference material. "
                "Available skills: create-report, configure-report, define-channels, create-histogram-1d, "
                "validate-report-execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "enum": [
                            "create-report",
                            "configure-report",
                            "define-channels",
                            "create-histogram-1d",
                            "validate-report-execution",
                        ],
                        "description": "Name of the skill to load",
                    },
                },
                "required": ["skill_name"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# MCP tool discovery (cached)
# ---------------------------------------------------------------------------

_mcp_tools_cache: tuple[list[dict], dict[str, str]] | None = None


def _get_all_tools(user_token: str | None = None) -> tuple[list[dict], dict[str, str]]:
    """Return combined tool list (report tools + MCP tools) and name map."""
    global _mcp_tools_cache
    if _mcp_tools_cache is None:
        mcp_specs, mcp_names = discover_mcp_tools(user_token=user_token)
        _mcp_tools_cache = (mcp_specs, mcp_names)
        logger.info("Cached %d MCP tools", len(mcp_specs))

    mcp_specs, mcp_names = _mcp_tools_cache
    return TOOLS + mcp_specs, mcp_names


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _exec_add_physical_signal(state: ReportState, var_name: str, alias: str, description: str = "") -> str:
    if any(s.var_name == var_name for s in state.signals):
        return f"Signal '{var_name}' already exists. Use a different name or remove it first."
    state.signals.append(
        SignalDefinition(var_name=var_name, signal_type="physical", alias=alias, description=description)
    )
    return f"Added physical signal '{var_name}' with alias '{alias}'."


def _exec_add_virtual_signal(
    state: ReportState, var_name: str, expression: str, eval_type: str, description: str = ""
) -> str:
    if any(s.var_name == var_name for s in state.signals):
        return f"Signal '{var_name}' already exists."
    state.signals.append(
        SignalDefinition(
            var_name=var_name,
            signal_type="virtual",
            expression=expression,
            eval_type=EvalType(eval_type),
            description=description,
        )
    )
    return f"Added virtual signal '{var_name}' = `{expression}` (type: {eval_type})."


def _exec_suggest_candidates(state: ReportState, candidates: list[dict]) -> str:
    seen: set[str] = set()
    unique: list[SignalCandidate] = []
    for c in candidates:
        alias = c["alias"]
        if alias in seen:
            continue
        seen.add(alias)
        unique.append(
            SignalCandidate(
                alias=alias,
                channel_name=c.get("channel_name", alias),
                unit=c.get("unit", ""),
                device_name=c.get("device_name", ""),
                description=c.get("description", ""),
            )
        )
    state.signal_candidates = unique
    return (
        f"Presented {len(unique)} unique candidate(s) to the user in the selection panel. "
        "The user can check the ones they want and click 'Add Selected', or tell you which ones to add via chat."
    )


def _exec_add_histogram(state: ReportState, **kwargs: Any) -> str:
    name = kwargs["name"]
    if any(a.name == name for a in state.aggregations):
        return f"Aggregation '{name}' already exists."
    state.aggregations.append(
        Histogram1DDefinition(
            name=name,
            histogram_type=HistogramType(kwargs["histogram_type"]),
            signal_ref=kwargs["signal_ref"],
            bins=kwargs.get("bins", []),
            bins_unit=kwargs.get("bins_unit"),
            values_unit=kwargs.get("values_unit"),
            description=kwargs.get("description", ""),
            max_duration=kwargs.get("max_duration"),
            event_signal_ref=kwargs.get("event_signal_ref"),
            weight_signal_ref=kwargs.get("weight_signal_ref"),
            weight_const=kwargs.get("weight_const"),
        )
    )
    return f"Added {kwargs['histogram_type']} histogram '{name}' on signal '{kwargs['signal_ref']}' with {len(kwargs.get('bins', []))} bin edges."


def _exec_add_histogram_2d(state: ReportState, **kwargs: Any) -> str:
    name = kwargs["name"]
    if any(a.name == name for a in state.aggregations):
        return f"Aggregation '{name}' already exists."
    state.aggregations.append(
        Histogram2DDefinition(
            name=name,
            x_signal_ref=kwargs["x_signal_ref"],
            y_signal_ref=kwargs["y_signal_ref"],
            x_bins=kwargs.get("x_bins", []),
            y_bins=kwargs.get("y_bins", []),
            x_bins_unit=kwargs.get("x_bins_unit"),
            y_bins_unit=kwargs.get("y_bins_unit"),
            description=kwargs.get("description", ""),
        )
    )
    return (
        f"Added 2D histogram '{name}' — X: '{kwargs['x_signal_ref']}' ({len(kwargs.get('x_bins', []))} edges), "
        f"Y: '{kwargs['y_signal_ref']}' ({len(kwargs.get('y_bins', []))} edges)."
    )


def _exec_add_statistics(state: ReportState, **kwargs: Any) -> str:
    name = kwargs["name"]
    if any(a.name == name for a in state.aggregations):
        return f"Aggregation '{name}' already exists."
    signal_refs = kwargs["signal_refs"]
    stat_labels = kwargs.get("stat_labels", ["min", "max", "mean", "median", "std", "count"])
    state.aggregations.append(
        StatisticsDefinition(
            name=name,
            signal_refs=signal_refs,
            stat_labels=stat_labels,
            event_signal_ref=kwargs.get("event_signal_ref"),
            description=kwargs.get("description", ""),
        )
    )
    return (
        f"Added statistics aggregation '{name}' for {len(signal_refs)} signal(s) "
        f"computing: {', '.join(stat_labels)}."
    )


def _exec_remove_aggregation(state: ReportState, name: str) -> str:
    idx = next((i for i, a in enumerate(state.aggregations) if a.name == name), None)
    if idx is None:
        return f"Aggregation '{name}' not found."
    removed = state.aggregations.pop(idx)
    return f"Removed {removed.agg_kind} aggregation '{name}'."


def _exec_set_report_metadata(state: ReportState, name: str, description: str = "", creator: str = "") -> str:
    state.name = name.lower().replace(" ", "_").replace("-", "_")
    state.description = description or f"{state.name} Report"
    if creator:
        state.creator = creator
    state.data_sources.table_prefix = f"{state.name}_report"
    return f"Report name set to '{state.name}'."


def _exec_set_vehicle(state: ReportState, vehicle_id: str, start_ts: str, col_name: str | None = None, stop_ts: str | None = None) -> str:
    col_name = col_name or state.vehicle_col_name
    existing = next((v for v in state.vehicles if v.vehicle_id == vehicle_id), None)
    if existing:
        existing.start_ts = start_ts
        existing.stop_ts = stop_ts
        existing.col_name = col_name
        return f"Updated vehicle '{vehicle_id}'."
    state.vehicles.append(VehicleConfig(vehicle_id=vehicle_id, col_name=col_name, start_ts=start_ts, stop_ts=stop_ts))
    return f"Added vehicle '{vehicle_id}' starting from {start_ts}."


def _get_ds_defaults() -> dict[str, str]:
    return {
        "aliases_copy_table_name": "channel_aliases",
        "device_aliases_copy_table_name": "device_aliases",
    }


def _exec_set_data_sources(state: ReportState, **kwargs: Any) -> str:
    for key, default in _get_ds_defaults().items():
        if default:
            kwargs.setdefault(key, default)
    if not kwargs.get("table_prefix"):
        kwargs["table_prefix"] = f"{state.name}_report" if state.name else "report"
    state.data_sources = DataSourceConfig(**kwargs)
    return (
        f"Data sources configured: {len(state.data_sources.channels)} channel table(s), "
        f"container_metrics={state.data_sources.container_metrics}, "
        f"destination={state.data_sources.destination_catalog}.{state.data_sources.destination_schema}"
    )


def _exec_preview_code(state: ReportState) -> str:
    from server.code_generator import generate_report_notebook, generate_config_json

    parts = ["## Generated Code Preview\n"]
    parts.append("### report.py\n```python\n" + generate_report_notebook(state) + "\n```\n")
    parts.append("### dev_config.json\n```json\n" + json.dumps(generate_config_json(state), indent=2) + "\n```\n")
    return "\n".join(parts)


_TOOL_STEP_MAP: dict[str, set[WizardStep]] = {
    "set_report_metadata": {WizardStep.REPORT_NAME},
    "set_vehicle": {WizardStep.VEHICLES},
    "set_data_sources": {WizardStep.VEHICLES},
    "add_physical_signal": {WizardStep.CHANNELS},
    "add_virtual_signal": {WizardStep.CHANNELS},
    "suggest_signal_candidates": {WizardStep.CHANNELS},
    "add_histogram": {WizardStep.AGGREGATIONS},
    "add_histogram_2d": {WizardStep.AGGREGATIONS},
    "add_statistics": {WizardStep.AGGREGATIONS},
    "remove_aggregation": {WizardStep.AGGREGATIONS},
    "preview_code": {WizardStep.AGGREGATIONS, WizardStep.READY},
    "load_skill": {WizardStep.REPORT_NAME, WizardStep.VEHICLES, WizardStep.CHANNELS, WizardStep.AGGREGATIONS, WizardStep.READY},
}

_STEP_LABELS = {
    WizardStep.REPORT_NAME: "Report Name",
    WizardStep.VEHICLES: "Vehicles",
    WizardStep.CHANNELS: "Channels",
    WizardStep.AGGREGATIONS: "Aggregations",
    WizardStep.READY: "Ready",
}


def _dispatch_tool(
    state: ReportState,
    name: str,
    args: dict[str, Any],
    mcp_name_map: dict[str, str],
    user_token: str | None = None,
) -> str:
    allowed_steps = _TOOL_STEP_MAP.get(name)
    if allowed_steps and state.wizard_step not in allowed_steps:
        current = _STEP_LABELS[state.wizard_step]
        needed = ", ".join(_STEP_LABELS[s] for s in sorted(allowed_steps, key=lambda s: s.value))
        return (
            f"Tool '{name}' cannot be used during the '{current}' step. "
            f"It is available in: {needed}. "
            f"Please complete the current step first and click 'Next Step'."
        )

    if name == "add_physical_signal":
        return _exec_add_physical_signal(state, args["var_name"], args["alias"], args.get("description", ""))
    if name == "add_virtual_signal":
        return _exec_add_virtual_signal(state, args["var_name"], args["expression"], args["eval_type"], args.get("description", ""))
    if name == "suggest_signal_candidates":
        return _exec_suggest_candidates(state, args["candidates"])
    if name == "add_histogram":
        return _exec_add_histogram(state, **args)
    if name == "add_histogram_2d":
        return _exec_add_histogram_2d(state, **args)
    if name == "add_statistics":
        return _exec_add_statistics(state, **args)
    if name == "remove_aggregation":
        return _exec_remove_aggregation(state, args["name"])
    if name == "set_report_metadata":
        return _exec_set_report_metadata(state, args["name"], args.get("description", ""), args.get("creator", ""))
    if name == "set_vehicle":
        return _exec_set_vehicle(state, args["vehicle_id"], args["start_ts"], args.get("col_name", "test_object_name"), args.get("stop_ts"))
    if name == "set_data_sources":
        return _exec_set_data_sources(state, **args)
    if name == "preview_code":
        return _exec_preview_code(state)
    if name == "load_skill":
        return load_skill_full(args["skill_name"])

    if name in mcp_name_map:
        original_name = mcp_name_map[name]
        logger.info("Dispatching to MCP tool: %s -> %s", name, original_name)
        return call_mcp_tool(original_name, args, user_token=user_token)

    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# OpenAI-compatible client for Databricks Foundation Model API
# ---------------------------------------------------------------------------

def _get_openai_client():
    from openai import OpenAI

    w = get_workspace_client()
    token = w.config.token

    if not token:
        try:
            result = w.config.authenticate()
            if callable(result):
                headers = result()
                if isinstance(headers, dict):
                    token = headers.get("Authorization", "").removeprefix("Bearer ").strip()
            elif isinstance(result, dict):
                token = result.get("Authorization", "").removeprefix("Bearer ").strip()
            elif isinstance(result, str):
                token = result
        except Exception as e:
            logger.error("authenticate() failed: %s", e)

    if not token:
        raise RuntimeError(
            f"Could not obtain auth token. auth_type={w.config.auth_type}, "
            f"host={w.config.host}, "
            f"has_client_id={bool(w.config.client_id)}"
        )

    return OpenAI(
        base_url=f"{w.config.host}/serving-endpoints",
        api_key=token,
    )


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

_MAX_TOOL_ROUNDS = 8

_MD_TABLE_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|$", re.MULTILINE)


def _extract_aliases_from_markdown(text: str) -> list[str]:
    """Best-effort extraction of alias names from a single-column markdown-table SQL result."""
    rows = _MD_TABLE_ROW_RE.findall(text)
    aliases: list[str] = []
    for val in rows:
        stripped = val.strip()
        if not stripped or stripped.startswith("---") or stripped.lower() == "channelalias" or stripped.lower().startswith("channelalias"):
            continue
        aliases.append(stripped)
    return aliases


def _maybe_auto_suggest_candidates(
    state: ReportState,
    called_sql: bool,
    called_suggest: bool,
    last_sql_result: str,
) -> None:
    """Fallback: if the LLM queried aliases but forgot to call suggest_signal_candidates,
    parse the SQL result and populate candidates programmatically.

    Disabled when available_channels is populated (silver layer discovery mode) —
    the agent should use the in-context channel catalog, not raw SQL results.
    """
    if state.wizard_step != WizardStep.CHANNELS:
        return
    if state.available_channels:
        return
    if not called_sql or called_suggest:
        return
    if not last_sql_result:
        return

    aliases = _extract_aliases_from_markdown(last_sql_result)
    if not aliases:
        return

    logger.warning(
        "LLM called execute_sql but NOT suggest_signal_candidates — "
        "auto-populating %d candidates from SQL result", len(aliases),
    )
    _exec_suggest_candidates(state, [{"alias": a} for a in aliases])


def run_agent(
    user_message: str,
    session_id: str | None = None,
    user_token: str | None = None,
) -> tuple[str, ReportState, str]:
    """Run the agent for one user turn. Returns (assistant_text, report_state, session_id)."""
    session = _get_session(session_id)
    client = _get_openai_client()
    system_prompt = build_system_prompt(
        wizard_step=session.state.wizard_step.value,
        signals=[s.model_dump() for s in session.state.signals] if session.state.signals else None,
        available_channels=[ch.model_dump() for ch in session.state.available_channels] if session.state.available_channels else None,
    )

    all_tools, mcp_name_map = _get_all_tools(user_token=user_token)
    tool_names = [t["function"]["name"] for t in all_tools]
    logger.info("Tools sent to LLM (%d): %s", len(tool_names), tool_names)

    session.messages.append({"role": "user", "content": user_message})

    messages_for_api: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *session.messages,
    ]

    called_sql = False
    called_suggest = False
    last_sql_result = ""

    for _ in range(_MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=SERVING_ENDPOINT,
            messages=messages_for_api,
            tools=all_tools,
            max_tokens=4096,
        )

        choice = response.choices[0]
        msg = choice.message

        if not msg.tool_calls:
            assistant_text = msg.content or ""
            _maybe_auto_suggest_candidates(
                session.state, called_sql, called_suggest, last_sql_result,
            )
            session.messages.append({"role": "assistant", "content": assistant_text})
            return assistant_text, session.state, session.session_id

        messages_for_api.append(msg.model_dump(exclude_none=True))

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            logger.info("LLM called tool: %s with args: %s", fn_name, list(fn_args.keys()))
            result = _dispatch_tool(
                session.state, fn_name, fn_args, mcp_name_map, user_token=user_token
            )
            messages_for_api.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

            if fn_name == "mcp_execute_sql":
                called_sql = True
                last_sql_result = result
            elif fn_name == "suggest_signal_candidates":
                called_suggest = True

    _maybe_auto_suggest_candidates(
        session.state, called_sql, called_suggest, last_sql_result,
    )
    final = messages_for_api[-1].get("content", "")
    session.messages.append({"role": "assistant", "content": final})
    return final, session.state, session.session_id
