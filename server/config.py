"""Databricks authentication and configuration for both local and deployed app contexts."""

import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

IS_DATABRICKS_APP = bool(
    os.environ.get("DATABRICKS_APP_NAME")
    or os.environ.get("DATABRICKS_CLIENT_ID")
)
DATABRICKS_PROFILE = os.environ.get("DATABRICKS_PROFILE", "DEFAULT")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
SERVING_ENDPOINT = os.environ.get("SERVING_ENDPOINT", "databricks-claude-sonnet-4-6")

def resolve_serving_endpoint(user_preference: str | None = None) -> str:
    """Resolve model: user preference -> env var -> hardcoded default."""
    if user_preference:
        return user_preference
    return SERVING_ENDPOINT


@lru_cache()
def get_available_models() -> list[dict]:
    """List chat-capable serving endpoints in the workspace.

    Returns Foundation Model API endpoints (name prefixed with ``databricks-``)
    that are currently READY. Cached for the app lifetime; restart to pick up
    newly provisioned endpoints.
    """
    try:
        client = get_workspace_client()
        endpoints = client.serving_endpoints.list()
    except Exception:
        logger.exception("Failed to list serving endpoints; returning empty list")
        return []

    models: list[dict] = []
    for ep in endpoints:
        name = getattr(ep, "name", "") or ""
        if not name.startswith("databricks-"):
            continue
        state_obj = getattr(ep, "state", None)
        ready = getattr(state_obj, "ready", None) if state_obj is not None else None
        if ready and str(ready).upper() not in {"READY"}:
            continue
        models.append({"id": name, "label": name})
    models.sort(key=lambda m: m["id"])
    return models
_app_dir = os.path.join(os.path.dirname(__file__), "..")
SKILLS_ROOT = os.environ.get(
    "SKILLS_ROOT",
    os.path.join(_app_dir, "skills")
    if os.path.isdir(os.path.join(_app_dir, "skills"))
    else os.path.join(_app_dir, "..", ".claude", "skills"),
)
TEMPLATE_ROOT = os.environ.get(
    "TEMPLATE_ROOT",
    os.path.join(_app_dir, ".template")
    if os.path.isdir(os.path.join(_app_dir, ".template"))
    else os.path.join(_app_dir, "..", "nameda", ".template"),
)
REPORTS_ROOT = os.environ.get(
    "REPORTS_ROOT",
    os.path.join(_app_dir, "reports")
    if os.environ.get("DATABRICKS_APP_NAME") or os.environ.get("DATABRICKS_CLIENT_ID")
    else os.path.join(_app_dir, "reports"),
)

logger.info("IS_DATABRICKS_APP=%s, WAREHOUSE_ID=%s, ENDPOINT=%s", IS_DATABRICKS_APP, WAREHOUSE_ID, SERVING_ENDPOINT)


@lru_cache()
def get_workspace_client():
    from databricks.sdk import WorkspaceClient

    if IS_DATABRICKS_APP:
        logger.info("Using Databricks App auth (service principal)")
        return WorkspaceClient()
    logger.info("Using profile auth: %s", DATABRICKS_PROFILE)
    return WorkspaceClient(profile=DATABRICKS_PROFILE)


def get_user_client(token: str):
    """Create a WorkspaceClient authenticated with a user token (PAT).

    The app runtime always injects DATABRICKS_CLIENT_ID/SECRET for the
    SP. The SDK reads those and sees both oauth + pat, so we must
    temporarily hide them.
    """
    from databricks.sdk import WorkspaceClient

    host = get_workspace_client().config.host
    saved = {}
    for key in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"):
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    try:
        return WorkspaceClient(host=host, token=token)
    finally:
        os.environ.update(saved)


def get_sql_connection_params() -> dict:
    cfg = get_workspace_client().config
    return {
        "host": cfg.host,
        "warehouse_id": WAREHOUSE_ID,
        "config": cfg,
    }
