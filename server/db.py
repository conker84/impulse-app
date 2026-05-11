"""Lakebase (PostgreSQL) connection layer for persistent app state.

Uses autoscaling Lakebase with OAuth credential generation.
The SP's token sub (its client UUID) must match a postgres role
with LOGIN and appropriate grants on the target database.
"""

from __future__ import annotations

import logging
import os

import psycopg

from server.config import IS_DATABRICKS_APP

logger = logging.getLogger(__name__)

LAKEBASE_PROJECT = os.environ.get("LAKEBASE_PROJECT", "impulse")
_ENDPOINT_PATH = f"projects/{LAKEBASE_PROJECT}/branches/production/endpoints/primary"

# All tables live in a SP-owned `impulse` schema. The app SP creates the schema
# at startup (it gets CREATE on the database via the `apps[].resources[].database`
# binding's CAN_CONNECT_AND_CREATE) and becomes the schema owner, which lets it
# DDL/DML freely without separate GRANTs. Avoids the `public`-schema gotcha
# where Postgres 15+ revokes CREATE from PUBLIC by default.
DB_SCHEMA = "impulse"

_SCHEMA_SQL = f"""\
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.user_settings (
    user_email TEXT PRIMARY KEY,
    encrypted_pat TEXT NOT NULL DEFAULT '',
    cluster_id TEXT NOT NULL DEFAULT '',
    serving_endpoint TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.saved_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email TEXT NOT NULL,
    report_name TEXT NOT NULL,
    report_state JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_email, report_name)
);

CREATE INDEX IF NOT EXISTS idx_saved_reports_user ON {DB_SCHEMA}.saved_reports(user_email);

ALTER TABLE {DB_SCHEMA}.user_settings ADD COLUMN IF NOT EXISTS serving_endpoint TEXT NOT NULL DEFAULT '';
"""


def _get_db_credential() -> tuple[str, str]:
    """Generate a Lakebase database credential via the Python SDK.

    Returns (username, token). The username is extracted from the JWT sub
    claim to ensure it matches the postgres role.
    """
    import base64
    import json as _json

    from server.config import get_workspace_client

    w = get_workspace_client()
    cred = w.postgres.generate_database_credential(endpoint=_ENDPOINT_PATH)
    token = cred.token or ""

    # Extract sub from JWT — this is what Lakebase validates against the role
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        claims = _json.loads(base64.urlsafe_b64decode(payload_b64))
        user = claims.get("sub", "")
    except Exception:
        user = os.environ.get("DATABRICKS_CLIENT_ID", "")

    logger.info("Generated Lakebase credential for user=%s", user)
    return user, token


def get_connection(dbname: str | None = None) -> psycopg.Connection:
    """Open a fresh connection to Lakebase."""
    if not IS_DATABRICKS_APP:
        raise RuntimeError(
            "Lakebase is only available when running as a Databricks App."
        )
    host = os.environ["LAKEBASE_HOST"]
    port = int(os.environ.get("LAKEBASE_PORT", "5432"))
    db = dbname or os.environ.get("LAKEBASE_DB", "impulse")

    user, password = _get_db_credential()

    conn = psycopg.connect(
        host=host,
        port=port,
        dbname=db,
        user=user,
        password=password,
        sslmode="require",
        autocommit=False,
        # Ensure unqualified table refs resolve to our SP-owned schema.
        options=f"-c search_path={DB_SCHEMA},public",
    )
    return conn


def init_schema() -> None:
    """Create application tables if they don't exist yet."""
    if not IS_DATABRICKS_APP:
        logger.info("Skipping schema init — not running as Databricks App")
        return
    try:
        conn = get_connection()
        for stmt in _SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        conn.close()
        logger.info("Lakebase schema initialized")
    except Exception:
        logger.exception("Failed to initialize Lakebase schema")
