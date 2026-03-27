"""Persistent report definition storage backed by Lakebase.

Stores only the wizard-configured subset of ReportState (metadata,
signals, aggregations, vehicles, data sources, compute flag).
Transient fields like deployment status, run IDs, and candidates
are excluded.

In local mode every function is a no-op / returns empty data.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from server.config import IS_DATABRICKS_APP
from server.models import ReportState

logger = logging.getLogger(__name__)

_PERSISTED_KEYS = frozenset({
    "name",
    "description",
    "creator",
    "signals",
    "aggregations",
    "vehicles",
    "data_sources",
    "use_all_purpose_cluster",
})


def _extract_persisted(state: ReportState) -> dict[str, Any]:
    """Return the subset of ReportState fields that should be persisted."""
    full = state.model_dump()
    return {k: full[k] for k in _PERSISTED_KEYS if k in full}


def save_report(user_email: str, state: ReportState) -> dict[str, Any]:
    """Upsert a report definition keyed by (user_email, report_name)."""
    if not IS_DATABRICKS_APP:
        logger.debug("save_report no-op in local mode")
        return {"id": None, "report_name": state.name}

    from server.db import get_connection

    payload = json.dumps(_extract_persisted(state))

    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO saved_reports (user_email, report_name, report_state, updated_at)
            VALUES (%s, %s, %s::jsonb, NOW())
            ON CONFLICT (user_email, report_name)
            DO UPDATE SET report_state = EXCLUDED.report_state, updated_at = NOW()
            RETURNING id, report_name, created_at, updated_at
            """,
            (user_email, state.name, payload),
        ).fetchone()
        conn.commit()

    logger.info("Saved report '%s' for %s", state.name, user_email)
    return {
        "id": str(row[0]),
        "report_name": row[1],
        "created_at": row[2].isoformat() if row[2] else None,
        "updated_at": row[3].isoformat() if row[3] else None,
    }


def list_reports(user_email: str) -> list[dict[str, Any]]:
    """Return summary info for all reports owned by the user."""
    if not IS_DATABRICKS_APP:
        return []

    from server.db import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, report_name,
                   report_state->>'description' AS description,
                   report_state->>'creator' AS creator,
                   updated_at
            FROM saved_reports
            WHERE user_email = %s
            ORDER BY updated_at DESC
            """,
            (user_email,),
        ).fetchall()

    return [
        {
            "id": str(r[0]),
            "report_name": r[1],
            "description": r[2] or "",
            "creator": r[3] or "",
            "updated_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


def load_report(report_id: str) -> dict[str, Any] | None:
    """Fetch the full persisted report_state by UUID."""
    if not IS_DATABRICKS_APP:
        return None

    from server.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT report_state, report_name, user_email FROM saved_reports WHERE id = %s",
            (report_id,),
        ).fetchone()

    if not row:
        return None

    data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    data["_report_name"] = row[1]
    data["_user_email"] = row[2]
    return data


def delete_report(report_id: str) -> bool:
    """Delete a saved report. Returns True if a row was deleted."""
    if not IS_DATABRICKS_APP:
        return False

    from server.db import get_connection

    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM saved_reports WHERE id = %s",
            (report_id,),
        )
        conn.commit()
        deleted = cur.rowcount > 0

    if deleted:
        logger.info("Deleted saved report %s", report_id)
    return deleted
