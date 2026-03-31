"""Unity Catalog browsing endpoints — /api/uc/*

List catalogs, schemas, and volumes for dynamic dropdowns in the Source Data step.
Uses SQL queries via the warehouse (covered by the OBO token's ``sql`` scope)
instead of SDK catalog API (which requires a ``unity-catalog`` scope not available
at the workspace level).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from server.config import IS_DATABRICKS_APP, WAREHOUSE_ID, get_workspace_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uc", tags=["uc-browse"])


def _execute_sql(request: Request, statement: str) -> list[dict]:
    """Execute a SQL statement via the warehouse and return rows as dicts."""
    from databricks.sdk.config import Config

    if IS_DATABRICKS_APP:
        from databricks.sdk import WorkspaceClient
        import os

        token = request.headers.get("X-Forwarded-Access-Token")
        if token:
            cfg = Config(
                host=os.environ.get("DATABRICKS_HOST", ""),
                token=token,
                client_id=None,
                client_secret=None,
                auth_type="pat",
            )
            w = WorkspaceClient(config=cfg)
        else:
            w = get_workspace_client()
    else:
        w = get_workspace_client()

    result = w.statement_execution.execute_statement(
        warehouse_id=WAREHOUSE_ID,
        statement=statement,
        wait_timeout="30s",
    )

    if not result.result or not result.result.data_array:
        return []

    columns = [c.name for c in result.manifest.schema.columns]
    return [dict(zip(columns, row)) for row in result.result.data_array]


@router.get("/catalogs")
async def list_catalogs(request: Request):
    """List available Unity Catalog catalogs."""
    try:
        rows = _execute_sql(request, "SHOW CATALOGS")
        catalogs = []
        for row in rows:
            name = row.get("catalog", "")
            if not name:
                continue
            catalogs.append({"name": name, "comment": row.get("comment", "")})
        return {"catalogs": catalogs}
    except Exception as e:
        logger.exception("Failed to list catalogs")
        raise HTTPException(502, f"Failed to list catalogs: {e}")


@router.get("/schemas")
async def list_schemas(catalog: str, request: Request):
    """List schemas within a catalog."""
    try:
        rows = _execute_sql(request, f"SHOW SCHEMAS IN `{catalog}`")
        schemas = []
        for row in rows:
            name = row.get("databaseName", row.get("schema_name", row.get("namespace", "")))
            if not name or name == "information_schema":
                continue
            schemas.append({"name": name, "comment": row.get("comment", "")})
        return {"schemas": schemas}
    except Exception as e:
        logger.exception("Failed to list schemas")
        raise HTTPException(502, f"Failed to list schemas: {e}")


@router.get("/volumes")
async def list_volumes(catalog: str, schema: str, request: Request):
    """List volumes within a schema."""
    try:
        rows = _execute_sql(request, f"SHOW VOLUMES IN `{catalog}`.`{schema}`")
        volumes = []
        for row in rows:
            name = row.get("volume_name", row.get("name", ""))
            if not name:
                continue
            volumes.append({"name": name, "comment": row.get("comment", "")})
        return {"volumes": volumes}
    except Exception as e:
        logger.exception("Failed to list volumes")
        raise HTTPException(502, f"Failed to list volumes: {e}")
