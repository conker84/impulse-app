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


@lru_cache()
def resolve_warehouse_id() -> str:
    """Look up the SQL warehouse the bundle created for this app.

    The bundle names the warehouse identically to the app (DATABRICKS_APP_NAME),
    so we can find it by name at runtime. Override via DATABRICKS_WAREHOUSE_ID
    env var for non-default deployments.
    """
    explicit = os.environ.get("DATABRICKS_WAREHOUSE_ID", "").strip()
    if explicit:
        return explicit
    app_name = os.environ.get("DATABRICKS_APP_NAME", "")
    if not app_name:
        return ""
    try:
        w = get_workspace_client()
        for wh in w.warehouses.list():
            if wh.name == app_name:
                return wh.id
    except Exception as e:
        logger.warning("Could not resolve SQL warehouse by app name %r: %s", app_name, e)
    return ""


def resolve_serving_endpoint(user_preference: str | None = None) -> str:
    """Resolve model: user preference -> first available endpoint in workspace.

    No env var needed. End users pick their model in Settings (persisted
    per-user in Lakebase); the only time this matters is the initial default
    for users who haven't picked yet, in which case we use the first model
    in the curated list that actually exists in the workspace.
    """
    if user_preference:
        return user_preference
    available = get_available_models()
    if available:
        return available[0]["id"]
    return "databricks-claude-sonnet-4-6"  # last-resort fallback


CURATED_MODELS = [
    {"id": "databricks-claude-haiku-4-5", "label": "Claude Haiku 4.5 (fast)"},
    {"id": "databricks-claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (balanced)"},
    {"id": "databricks-claude-opus-4-6", "label": "Claude Opus 4.6 (best reasoning)"},
    {"id": "databricks-gemini-2-5-flash", "label": "Gemini 2.5 Flash"},
    {"id": "databricks-gemini-2-5-pro", "label": "Gemini 2.5 Pro"},
    {"id": "databricks-gpt-5-4-mini", "label": "GPT 5.4 Mini"},
    {"id": "databricks-gpt-5-4", "label": "GPT 5.4"},
    {"id": "databricks-meta-llama-3-3-70b-instruct", "label": "Llama 3.3 70B"},
]


@lru_cache()
def get_available_models() -> list[dict]:
    """Return chat-capable FMAPI endpoints actually available in this workspace.

    Intersects the curated list (for nice labels + chat-capability filtering)
    with the workspace's serving_endpoints inventory. Falls back to the full
    curated list if the workspace API is unreachable (e.g., local dev).
    """
    try:
        w = get_workspace_client()
        available_names = {ep.name for ep in w.serving_endpoints.list()}
        filtered = [m for m in CURATED_MODELS if m["id"] in available_names]
        if not filtered:
            logger.warning(
                "None of the curated models exist in this workspace; "
                "returning the full curated list as a fallback. "
                "Workspace endpoints: %s", sorted(available_names)
            )
            return CURATED_MODELS
        return filtered
    except Exception as e:
        logger.warning("Could not list serving endpoints (%s); returning curated list", e)
        return CURATED_MODELS
_app_dir = os.path.join(os.path.dirname(__file__), "..")
SKILLS_ROOT = os.environ.get(
    "SKILLS_ROOT",
    os.path.join(_app_dir, "skills")
    if os.path.isdir(os.path.join(_app_dir, "skills"))
    else os.path.join(_app_dir, "..", ".claude", "skills"),
)
TEMPLATE_ROOT = os.environ.get(
    "TEMPLATE_ROOT",
    os.path.join(_app_dir, "report_template")
    if os.path.isdir(os.path.join(_app_dir, "report_template"))
    else os.path.join(_app_dir, "..", "nameda", "report_template"),
)
REPORTS_ROOT = os.environ.get(
    "REPORTS_ROOT",
    os.path.join(_app_dir, "reports")
    if os.environ.get("DATABRICKS_APP_NAME") or os.environ.get("DATABRICKS_CLIENT_ID")
    else os.path.join(_app_dir, "reports"),
)

logger.info("IS_DATABRICKS_APP=%s", IS_DATABRICKS_APP)


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
        "warehouse_id": resolve_warehouse_id(),
        "config": cfg,
    }
