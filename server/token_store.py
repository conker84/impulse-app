"""Encrypted PAT storage backed by Lakebase + Databricks Secrets.

Temporary workaround: Databricks Apps do not yet support the OAuth
scopes required for deploying and running jobs on behalf of end users.
Once that limitation is lifted, PAT storage can be removed and all
operations can use X-Forwarded-Access-Token directly.

In local mode every function is a no-op — the local Databricks profile
handles authentication.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from server.config import IS_DATABRICKS_APP

logger = logging.getLogger(__name__)


@lru_cache()
def _get_fernet():
    """Retrieve the Fernet key from Databricks Secrets and return a Fernet instance."""
    import base64

    from cryptography.fernet import Fernet
    from server.config import get_workspace_client

    scope = os.environ.get("SECRET_SCOPE", "impulse")
    key_name = os.environ.get("SECRET_KEY_NAME", "fernet-key")

    w = get_workspace_client()
    secret_resp = w.secrets.get_secret(scope=scope, key=key_name)
    # The SDK returns the value base64-encoded; decode to get the original key
    raw = secret_resp.value
    if isinstance(raw, str):
        raw = raw.encode()
    key_bytes = base64.b64decode(raw)

    logger.info("Loaded Fernet key from scope=%s key=%s", scope, key_name)
    return Fernet(key_bytes)


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def store_pat(user_email: str, pat: str) -> None:
    """Encrypt and upsert a PAT for the given user."""
    if not IS_DATABRICKS_APP:
        logger.debug("store_pat no-op in local mode")
        return

    from server.db import get_connection

    encrypted = _encrypt(pat)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_email, encrypted_pat, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_email)
            DO UPDATE SET encrypted_pat = EXCLUDED.encrypted_pat, updated_at = NOW()
            """,
            (user_email, encrypted),
        )
        conn.commit()
    logger.info("Stored PAT for %s", user_email)


def get_pat(user_email: str) -> str | None:
    """Retrieve and decrypt the stored PAT, or None if not found."""
    if not IS_DATABRICKS_APP:
        return None

    from server.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT encrypted_pat FROM user_settings WHERE user_email = %s",
            (user_email,),
        ).fetchone()

    if not row:
        return None
    return _decrypt(row[0])


def has_pat(user_email: str) -> bool:
    """Check whether a PAT is stored for the user."""
    if not IS_DATABRICKS_APP:
        return False

    from server.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_settings WHERE user_email = %s",
            (user_email,),
        ).fetchone()

    return row is not None


def delete_pat(user_email: str) -> bool:
    """Delete the stored PAT. Returns True if a row was deleted."""
    if not IS_DATABRICKS_APP:
        return False

    from server.db import get_connection

    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM user_settings WHERE user_email = %s",
            (user_email,),
        )
        conn.commit()
        deleted = cur.rowcount > 0

    if deleted:
        logger.info("Deleted PAT for %s", user_email)
    return deleted


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
