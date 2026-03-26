"""Databricks authentication and configuration for both local and deployed app contexts."""

import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

IS_DATABRICKS_APP = bool(
    os.environ.get("DATABRICKS_APP_NAME")
    or os.environ.get("DATABRICKS_CLIENT_ID")
)
DATABRICKS_PROFILE = os.environ.get("DATABRICKS_PROFILE", "fe-vm-maximhammer")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "e0458b451165d343")
SERVING_ENDPOINT = os.environ.get("SERVING_ENDPOINT", "databricks-claude-haiku-4-5")
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
    from databricks.sdk import WorkspaceClient

    cfg = get_workspace_client().config
    return WorkspaceClient(host=cfg.host, token=token)


def get_sql_connection_params() -> dict:
    cfg = get_workspace_client().config
    return {
        "host": cfg.host,
        "warehouse_id": WAREHOUSE_ID,
        "config": cfg,
    }
