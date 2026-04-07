"""Direct SQL connector for Arrow-native time series data fetching.

Uses databricks-sql-connector to fetch large result sets as Arrow batches,
bypassing the MCP text-serialization path. Zero-copy into Polars DataFrames.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import polars as pl

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


def fetch_channel_polars(
    conn: Connection,
    catalog: str,
    schema: str,
    container_id: int,
    channel_id: int,
) -> pl.DataFrame:
    """Fetch all RLE rows for a channel as a Polars DataFrame.

    Returns DataFrame with columns [tstart: Int64, tend: Int64, value: Float64].
    Uses Arrow-native fetching for zero-copy transfer.
    """
    sql = (
        f"SELECT tstart, tend, value "
        f"FROM {catalog}.{schema}.channels "
        f"WHERE container_id = {container_id} AND channel_id = {channel_id} "
        f"ORDER BY tstart"
    )

    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        arrow_table = cursor.fetchall_arrow()
        return pl.from_arrow(arrow_table)
    finally:
        cursor.close()
