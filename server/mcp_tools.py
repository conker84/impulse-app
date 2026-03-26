"""Databricks MCP server integration.

Provides SQL execution tools to the LLM agent via MCP.

Two modes:
- **Local**: connects to a local stdio-based MCP server (databricks-mcp-server)
- **Deployed**: connects to the Databricks managed DBSQL MCP server

MCP client methods use asyncio, which conflicts with FastAPI/uvicorn's
running event loop. All MCP calls are dispatched to a separate thread
via ThreadPoolExecutor to avoid this.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from server.config import DATABRICKS_PROFILE, IS_DATABRICKS_APP, get_workspace_client

logger = logging.getLogger(__name__)

_sp_mcp_client = None
_thread_pool = ThreadPoolExecutor(max_workers=4)

_local_loop: asyncio.AbstractEventLoop | None = None
_local_thread: threading.Thread | None = None
_local_session = None
_local_stdio_cm = None
_local_session_cm = None


def _run_in_thread(fn, *args):
    """Run fn(*args) in a thread that has no active event loop."""
    future = _thread_pool.submit(fn, *args)
    return future.result(timeout=120)


# ---------------------------------------------------------------------------
# Local MCP server (stdio)
# ---------------------------------------------------------------------------

def _find_mcp_server_cmd() -> tuple[str, list[str]]:
    """Auto-discover the databricks-mcp-server command.

    Checks in order:
    1. Env vars LOCAL_MCP_CMD / LOCAL_MCP_ARGS (explicit override)
    2. 'databricks-mcp' executable on PATH or in the project venv
    3. 'python -m databricks_mcp' via the project venv
    """
    if os.environ.get("LOCAL_MCP_CMD"):
        cmd = os.environ["LOCAL_MCP_CMD"]
        args = os.environ.get("LOCAL_MCP_ARGS", "").split() if os.environ.get("LOCAL_MCP_ARGS") else []
        return cmd, args

    import shutil

    app_dir = os.path.join(os.path.dirname(__file__), "..")
    venv_bin = os.path.join(app_dir, ".venv", "bin")

    for name in ("databricks-mcp", "databricks-mcp-server"):
        venv_path = os.path.join(venv_bin, name)
        if os.path.isfile(venv_path):
            return venv_path, ["start"]
        system_path = shutil.which(name)
        if system_path:
            return system_path, ["start"]

    venv_python = os.path.join(venv_bin, "python")
    if os.path.isfile(venv_python):
        return venv_python, ["-m", "databricks_mcp", "start"]

    raise RuntimeError(
        "Cannot find databricks-mcp server. Install it in the project venv "
        "(uv pip install databricks-mcp) or set LOCAL_MCP_CMD env var."
    )


def _local_server_params():
    from mcp.client.stdio import StdioServerParameters

    cmd, args = _find_mcp_server_cmd()

    w = get_workspace_client()
    host = w.config.host
    token = w.config.token

    if not token:
        headers = w.config.authenticate()
        token = headers.get("Authorization", "").removeprefix("Bearer ")

    logger.info("Local MCP server: cmd=%s args=%s host=%s", cmd, args, host)
    env = os.environ.copy()
    env["DATABRICKS_HOST"] = host
    if token:
        env["DATABRICKS_TOKEN"] = token
    return StdioServerParameters(
        command=cmd,
        args=args,
        env=env,
    )


def _ensure_local_loop() -> asyncio.AbstractEventLoop:
    """Start a background thread with a dedicated event loop (once)."""
    global _local_loop, _local_thread
    if _local_loop is not None and _local_loop.is_running():
        return _local_loop
    _local_loop = asyncio.new_event_loop()
    _local_thread = threading.Thread(target=_local_loop.run_forever, daemon=True)
    _local_thread.start()
    return _local_loop


async def _init_local_session():
    """Open the stdio MCP client and session, keep them alive in the background loop."""
    global _local_session, _local_stdio_cm, _local_session_cm
    if _local_session is not None:
        return _local_session

    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    logger.info("Starting persistent local MCP server (stdio)")
    _local_stdio_cm = stdio_client(_local_server_params())
    read, write = await _local_stdio_cm.__aenter__()
    _local_session_cm = ClientSession(read, write)
    _local_session = await _local_session_cm.__aenter__()
    await _local_session.initialize()
    logger.info("Local MCP server session ready")
    return _local_session


def _get_local_session():
    """Get the persistent local MCP session, initializing if needed."""
    loop = _ensure_local_loop()
    future = asyncio.run_coroutine_threadsafe(_init_local_session(), loop)
    return future.result(timeout=30)


def _local_list_tools_sync():
    session = _get_local_session()
    loop = _ensure_local_loop()
    future = asyncio.run_coroutine_threadsafe(session.list_tools(), loop)
    return future.result(timeout=120)


def _local_call_tool_sync(name, arguments):
    session = _get_local_session()
    loop = _ensure_local_loop()
    future = asyncio.run_coroutine_threadsafe(session.call_tool(name, arguments), loop)
    return future.result(timeout=120)


# ---------------------------------------------------------------------------
# Managed MCP server (Databricks App)
# ---------------------------------------------------------------------------

def _get_server_url() -> str:
    w = get_workspace_client()
    return f"{w.config.host}/api/2.0/mcp/sql"


def _get_sp_client():
    """Get the cached service-principal MCP client (for discovery)."""
    global _sp_mcp_client
    if _sp_mcp_client is not None:
        return _sp_mcp_client

    from databricks_mcp import DatabricksMCPClient

    w = get_workspace_client()
    server_url = _get_server_url()
    logger.info("Connecting to managed DBSQL MCP server (SP): %s", server_url)
    _sp_mcp_client = DatabricksMCPClient(server_url=server_url, workspace_client=w)
    return _sp_mcp_client


async def _call_tool_as_user(server_url: str, tool_name: str, arguments: dict, user_token: str):
    """Call an MCP tool using the end-user's token directly via streamablehttp_client."""
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {user_token}"}

    async with streamablehttp_client(url=server_url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


def _call_tool_as_user_sync(server_url: str, tool_name: str, arguments: dict, user_token: str):
    """Sync wrapper — runs the async user-token MCP call in a fresh event loop (via thread)."""
    return asyncio.run(_call_tool_as_user(server_url, tool_name, arguments, user_token))


# ---------------------------------------------------------------------------
# MCP tool whitelist (Llama 3.3 supports max 32 tools; 8 are app tools)
# ---------------------------------------------------------------------------

_MCP_TOOL_WHITELIST: set[str] = {
    "execute_sql",
    "list_catalogs",
    "list_schemas",
    "list_tables",
    "describe_table",
    "get_table",
    "get_table_summary",
    "list_columns",
    "create_table",
    "list_functions",
    "get_function",
    "list_volume_directory",
    "read_from_volume",
    "upload_to_volume",
    "download_from_volume",
    "get_volume_file_info",
    "get_current_user",
    "list_connections",
    "list_registered_models",
    "get_registered_model",
}


# ---------------------------------------------------------------------------
# OpenAI tool schema helpers
# ---------------------------------------------------------------------------

def _mcp_schema_to_openai_params(input_schema: dict) -> dict:
    """Convert an MCP tool inputSchema to OpenAI function parameters format."""
    params: dict[str, Any] = {"type": "object", "properties": {}}
    if "properties" in input_schema:
        params["properties"] = input_schema["properties"]
    if "required" in input_schema:
        params["required"] = input_schema["required"]
    return params


# ---------------------------------------------------------------------------
# Discovery (always service principal)
# ---------------------------------------------------------------------------

def discover_mcp_tools(user_token: str | None = None) -> tuple[list[dict], dict[str, str]]:
    """Discover tools from the MCP server.

    Local: uses stdio-based databricks-mcp-server.
    Deployed: uses the managed DBSQL MCP server via service principal.
    """
    try:
        if IS_DATABRICKS_APP:
            client = _get_sp_client()
            mcp_tools = _run_in_thread(client.list_tools)
        else:
            logger.info("Discovering tools from local MCP server (stdio)")
            result = _run_in_thread(_local_list_tools_sync)
            mcp_tools = result.tools if hasattr(result, "tools") else result
    except Exception:
        logger.exception("Failed to discover MCP tools")
        return [], {}

    openai_tools: list[dict] = []
    name_map: dict[str, str] = {}

    skipped = 0
    for t in mcp_tools:
        if t.name not in _MCP_TOOL_WHITELIST:
            skipped += 1
            continue

        safe_name = f"mcp_{t.name.replace('.', '_').replace('-', '_')}"
        name_map[safe_name] = t.name

        schema = t.inputSchema.copy() if hasattr(t, "inputSchema") and t.inputSchema else {}
        spec = {
            "type": "function",
            "function": {
                "name": safe_name,
                "description": f"[DBSQL MCP] {t.description or t.name}",
                "parameters": _mcp_schema_to_openai_params(schema),
            },
        }
        openai_tools.append(spec)
        logger.info("Registered MCP tool: %s -> %s", safe_name, t.name)

    logger.info(
        "Registered %d MCP tools (%d skipped, %d available from server)",
        len(openai_tools), skipped, len(mcp_tools),
    )
    return openai_tools, name_map


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def _parse_values(data_array: list) -> list[list[str]]:
    """Extract row values from the SQL Statement API data_array format."""
    rows: list[list[str]] = []
    for row_obj in data_array:
        values = row_obj.get("values", [])
        row = []
        for v in values:
            if "string_value" in v:
                row.append(v["string_value"])
            elif "int_value" in v:
                row.append(str(v["int_value"]))
            elif "double_value" in v:
                row.append(str(v["double_value"]))
            elif "bool_value" in v:
                row.append(str(v["bool_value"]))
            elif "null_value" in v:
                row.append("NULL")
            else:
                row.append(str(v))
        rows.append(row)
    return rows


def _format_sql_response(raw: str) -> str:
    """Parse an MCP SQL response into a markdown table.

    Handles two formats:
    - Managed DBSQL MCP: raw SQL Statement API JSON (dict with status/manifest/result)
    - Local MCP server: already-parsed list of row dicts, or {"result": [...]}
    """
    import json as _json

    try:
        payload = _json.loads(raw)
    except (ValueError, TypeError):
        return raw

    # --- Local MCP server: list of row dicts or {"result": [...]} ---
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and "result" in payload and isinstance(payload["result"], list):
        rows = payload["result"]
    else:
        rows = None

    if rows is not None and len(rows) > 0 and isinstance(rows[0], dict):
        col_names = list(rows[0].keys())
        lines = [f"| {' | '.join(col_names)} |"]
        lines.append("| " + " | ".join(["---"] * len(col_names)) + " |")
        for row in rows:
            vals = [str(row.get(c, "")) for c in col_names]
            lines.append(f"| {' | '.join(vals)} |")
        lines.append(f"\n{len(rows)} row(s) returned")
        return "\n".join(lines)

    if rows is not None and len(rows) == 0:
        return "Query returned 0 rows."

    # --- Managed DBSQL MCP: SQL Statement API format ---
    if not isinstance(payload, dict):
        return raw

    status = payload.get("status", {}).get("state", "")
    if status != "SUCCEEDED":
        msg = payload.get("status", {}).get("error", {}).get("message", status)
        return f"SQL query failed: {msg}"

    manifest = payload.get("manifest", {})
    columns = manifest.get("schema", {}).get("columns", [])
    col_names = [c.get("name", f"col{i}") for i, c in enumerate(columns)]
    if not col_names:
        return raw

    data_array = payload.get("result", {}).get("data_array", [])
    parsed_rows = _parse_values(data_array)

    total_rows = manifest.get("total_row_count", len(parsed_rows))
    truncated = manifest.get("truncated", False)

    lines = [f"| {' | '.join(col_names)} |"]
    lines.append("| " + " | ".join(["---"] * len(col_names)) + " |")
    for row in parsed_rows:
        padded = row + [""] * (len(col_names) - len(row))
        lines.append(f"| {' | '.join(padded)} |")

    summary = f"\n{total_rows} row(s) returned"
    if truncated:
        summary += " (truncated)"
    lines.append(summary)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _extract_response_text(response) -> list[str]:
    """Extract text parts from an MCP CallToolResult."""
    parts = []
    for content in response.content:
        if hasattr(content, "text"):
            parts.append(content.text)
        else:
            parts.append(str(content))
    return parts


def call_mcp_tool(mcp_tool_name: str, arguments: dict[str, Any], user_token: str | None = None) -> str:
    """Call a tool on the MCP server.

    Local: uses the stdio-based local MCP server.
    Deployed: uses end-user token when available, falls back to SP.
    """
    if mcp_tool_name == "execute_sql" and "warehouse_id" in arguments:
        from server.config import WAREHOUSE_ID
        arguments = {**arguments, "warehouse_id": WAREHOUSE_ID}

    try:
        if IS_DATABRICKS_APP:
            server_url = _get_server_url()
            if user_token:
                response = _run_in_thread(
                    _call_tool_as_user_sync, server_url, mcp_tool_name, arguments, user_token
                )
            else:
                client = _get_sp_client()
                response = _run_in_thread(client.call_tool, mcp_tool_name, arguments)
        else:
            response = _run_in_thread(_local_call_tool_sync, mcp_tool_name, arguments)

        parts = [_format_sql_response(t) for t in _extract_response_text(response)]
        return "\n".join(parts) if parts else "(empty result)"
    except Exception as e:
        logger.exception("MCP tool call failed: %s", mcp_tool_name)
        return f"Error calling MCP tool '{mcp_tool_name}': {e}"


def execute_sql(statement: str, user_token: str | None = None) -> dict[str, Any]:
    """Execute SQL via the MCP server and return structured results.

    Returns: {"columns": list[str], "rows": list[list[str]], "row_count": int}
    """
    import json as _json

    if IS_DATABRICKS_APP:
        server_url = _get_server_url()
        if user_token:
            response = _run_in_thread(
                _call_tool_as_user_sync, server_url, "execute_sql", {"query": statement}, user_token
            )
        else:
            client = _get_sp_client()
            response = _run_in_thread(client.call_tool, "execute_sql", {"query": statement})
    else:
        response = _run_in_thread(
            _local_call_tool_sync, "execute_sql", {"sql_query": statement}
        )

    raw = ""
    for text in _extract_response_text(response):
        raw = text
        break

    try:
        payload = _json.loads(raw)
    except (ValueError, TypeError):
        raise RuntimeError(f"Unexpected MCP response: {raw[:500]}")

    # Local MCP server returns list of row dicts or {"result": [...]}
    if isinstance(payload, list):
        row_dicts = payload
    elif isinstance(payload, dict) and "result" in payload and isinstance(payload["result"], list):
        row_dicts = payload["result"]
    else:
        row_dicts = None

    if row_dicts is not None:
        if len(row_dicts) == 0:
            return {"columns": [], "rows": [], "row_count": 0}
        columns = list(row_dicts[0].keys())
        rows = [[str(r.get(c, "")) for c in columns] for r in row_dicts]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}

    # Managed DBSQL MCP: SQL Statement API format
    status = payload.get("status", {}).get("state", "")
    if status != "SUCCEEDED":
        err = payload.get("status", {}).get("error", {}).get("message", status)
        raise RuntimeError(f"SQL execution failed: {err}")

    manifest = payload.get("manifest", {})
    col_defs = manifest.get("schema", {}).get("columns", [])
    columns = [c.get("name", f"col{i}") for i, c in enumerate(col_defs)]

    data_array = payload.get("result", {}).get("data_array", [])
    rows = _parse_values(data_array)

    return {"columns": columns, "rows": rows, "row_count": len(rows)}
