"""Direct SQL connector for Arrow-native time series data fetching.

Uses databricks-sql-connector to fetch large result sets as Arrow batches,
bypassing the MCP text-serialization path. Returns PyArrow Tables for
direct conversion to NumPy arrays.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pyarrow as pa

if TYPE_CHECKING:
    from databricks.sql.client import Connection

logger = logging.getLogger(__name__)


def get_connection(token: str | None = None) -> Connection:
    """Create a DBSQL connection using the OBO token (app) or CLI profile (local).

    Args:
        token: OBO access token from X-Forwarded-Access-Token header.
               None in local dev mode (uses CLI profile).
    """
    from databricks.sql import connect as dbsql_connect
    from server.config import IS_DATABRICKS_APP, WAREHOUSE_ID, get_workspace_client

    cfg = get_workspace_client().config
    host = cfg.host.rstrip("/").replace("https://", "")
    http_path = f"/sql/1.0/warehouses/{WAREHOUSE_ID}"

    if IS_DATABRICKS_APP and token:
        return dbsql_connect(
            server_hostname=host,
            http_path=http_path,
            access_token=token,
        )

    # Local dev: use token from CLI profile
    local_token = cfg.token or os.environ.get("DATABRICKS_TOKEN", "")
    if not local_token:
        raise RuntimeError(
            "No Databricks token available. Set DATABRICKS_TOKEN or configure a CLI profile."
        )
    return dbsql_connect(
        server_hostname=host,
        http_path=http_path,
        access_token=local_token,
    )


def fetch_channel_arrow(
    conn: Connection,
    catalog: str,
    schema: str,
    container_id: str,
    channel_id: str,
    session_overrides: dict | None = None,
) -> pa.Table:
    """Fetch a channel's samples as a PyArrow Table with columns [tstart, value].

    SQL is built via SchemaAdapter — table name and column mappings come from
    the active schema profile (or session overrides when supplied).
    """
    from server.schema_adapter import SchemaAdapter

    adapter = SchemaAdapter.from_active_profile(catalog, schema, session_overrides=session_overrides)
    sql = adapter.ts_explorer_signal_fetch_query(container_id, channel_id)

    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        return cursor.fetchall_arrow()
    finally:
        cursor.close()
