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
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "997c48107f9a1467")
SERVING_ENDPOINT = os.environ.get("SERVING_ENDPOINT", "databricks-claude-sonnet-4-6")

AVAILABLE_MODELS = [
    {"id": "databricks-claude-haiku-4-5", "label": "Claude Haiku 4.5 (fast)"},
    {"id": "databricks-claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (balanced)"},
    {"id": "databricks-claude-opus-4-6", "label": "Claude Opus 4.6 (best reasoning)"},
    {"id": "databricks-gemini-2-5-flash", "label": "Gemini 2.5 Flash"},
    {"id": "databricks-gemini-2-5-pro", "label": "Gemini 2.5 Pro"},
    {"id": "databricks-gpt-5-4-mini", "label": "GPT 5.4 Mini"},
    {"id": "databricks-gpt-5-4", "label": "GPT 5.4"},
    {"id": "databricks-meta-llama-3-3-70b-instruct", "label": "Llama 3.3 70B"},
]


def resolve_serving_endpoint(user_preference: str | None = None) -> str:
    """Resolve model: user preference -> env var -> hardcoded default."""
    if user_preference:
        return user_preference
    return SERVING_ENDPOINT
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
