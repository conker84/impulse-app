"""Per-user preferences (cluster ID, serving endpoint) backed by Lakebase.

In local mode every function is a no-op.
"""

from __future__ import annotations

import logging

from server.config import IS_DATABRICKS_APP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cluster ID persistence
# ---------------------------------------------------------------------------

def store_cluster_id(user_email: str, cluster_id: str) -> None:
    """Persist an all-purpose cluster ID for the user."""
    if not IS_DATABRICKS_APP:
        logger.debug("store_cluster_id no-op in local mode")
        return

    from server.db import get_connection

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_email, cluster_id, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_email)
            DO UPDATE SET cluster_id = EXCLUDED.cluster_id, updated_at = NOW()
            """,
            (user_email, cluster_id),
        )
        conn.commit()
    logger.info("Stored cluster_id for %s", user_email)


def get_cluster_id(user_email: str) -> str:
    """Retrieve the stored cluster ID, or empty string if not found."""
    if not IS_DATABRICKS_APP:
        return ""

    from server.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT cluster_id FROM user_settings WHERE user_email = %s",
            (user_email,),
        ).fetchone()

    return row[0] if row else ""


# ---------------------------------------------------------------------------
# Serving endpoint preference
# ---------------------------------------------------------------------------

def store_serving_endpoint(user_email: str, endpoint: str) -> None:
    """Persist a serving endpoint preference for the user."""
    if not IS_DATABRICKS_APP:
        logger.debug("store_serving_endpoint no-op in local mode")
        return

    from server.db import get_connection

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_email, serving_endpoint, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_email)
            DO UPDATE SET serving_endpoint = EXCLUDED.serving_endpoint, updated_at = NOW()
            """,
            (user_email, endpoint),
        )
        conn.commit()
    logger.info("Stored serving_endpoint for %s", user_email)


def get_serving_endpoint(user_email: str) -> str:
    """Retrieve the stored serving endpoint preference, or empty string if not found."""
    if not IS_DATABRICKS_APP:
        return ""

    from server.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT serving_endpoint FROM user_settings WHERE user_email = %s",
            (user_email,),
        ).fetchone()

    return row[0] if row else ""
