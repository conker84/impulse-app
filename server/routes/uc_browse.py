"""Unity Catalog browsing endpoints — /api/uc/*

List catalogs, schemas, and volumes for dynamic dropdowns in the Source Data step.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request

from server.config import IS_DATABRICKS_APP, get_workspace_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uc", tags=["uc-browse"])


def _get_client(request: Request):
    """Get a WorkspaceClient using the user's token (deployed) or profile (local)."""
    if IS_DATABRICKS_APP:
        from databricks.sdk import WorkspaceClient

        token = request.headers.get("X-Forwarded-Access-Token")
        if token:
            host = os.environ.get("DATABRICKS_HOST", "")
            return WorkspaceClient(host=host, token=token)
        return WorkspaceClient()
    return get_workspace_client()


@router.get("/catalogs")
async def list_catalogs(request: Request):
    """List available Unity Catalog catalogs."""
    w = _get_client(request)
    catalogs = []
    for c in w.catalogs.list():
        if c.catalog_type and c.catalog_type.value == "SYSTEM_CATALOG":
            continue
        catalogs.append({"name": c.name, "comment": c.comment or ""})
    return {"catalogs": catalogs}


@router.get("/schemas")
async def list_schemas(catalog: str, request: Request):
    """List schemas within a catalog."""
    w = _get_client(request)
    schemas = []
    for s in w.schemas.list(catalog_name=catalog):
        if s.name == "information_schema":
            continue
        schemas.append({"name": s.name, "comment": s.comment or ""})
    return {"schemas": schemas}


@router.get("/volumes")
async def list_volumes(catalog: str, schema: str, request: Request):
    """List volumes within a schema."""
    w = _get_client(request)
    volumes = []
    for v in w.volumes.list(catalog_name=catalog, schema_name=schema):
        volumes.append({"name": v.name, "comment": v.comment or ""})
    return {"volumes": volumes}
