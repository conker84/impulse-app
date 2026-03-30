"""Saved reports endpoints — /api/reports

CRUD for persisting and loading report definitions from Lakebase.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from server.agent import _sessions, _Session
from server.config import IS_DATABRICKS_APP
from server.models import (
    DataSourceConfig,
    ReportState,
    WizardStep,
)
from server.report_store import delete_report, list_reports, load_report, save_report
from server.token_store import get_cluster_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _resolve_user_email(request: Request) -> str:
    if not IS_DATABRICKS_APP:
        return "local-dev@localhost"
    email = request.headers.get("X-Forwarded-Email", "")
    if not email:
        raise HTTPException(401, "Missing X-Forwarded-Email header")
    return email


@router.get("")
async def list_saved_reports(request: Request):
    """List all saved reports for the current user."""
    email = _resolve_user_email(request)
    reports = list_reports(email)
    return {"reports": reports}


@router.post("/save/{session_id}")
async def save_current_report(session_id: str, request: Request):
    """Save the current session's report definition to Lakebase."""
    email = _resolve_user_email(request)
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    state = session.state
    if not state.name:
        raise HTTPException(400, "Report has no name. Complete the metadata step first.")

    result = save_report(email, state)
    return {"status": "saved", **result}


@router.post("/load/{report_id}")
async def load_saved_report(report_id: str, request: Request):
    """Load a saved report into a new session."""
    email = _resolve_user_email(request)
    data = load_report(report_id)

    if not data:
        raise HTTPException(404, "Report not found")

    if data.get("_user_email") != email:
        raise HTTPException(403, "You do not own this report.")

    data.pop("_report_name", None)
    data.pop("_user_email", None)

    state = ReportState(
        name=data.get("name", ""),
        description=data.get("description", ""),
        creator=data.get("creator", ""),
        signals=data.get("signals", []),
        aggregations=data.get("aggregations", data.get("histograms", [])),
        vehicles=data.get("vehicles", []),
        data_sources=DataSourceConfig(**data["data_sources"]) if data.get("data_sources") else DataSourceConfig(),
        use_all_purpose_cluster=data.get("use_all_purpose_cluster", False),
        wizard_step=WizardStep.READY,
        run_id=data.get("run_id"),
        run_url=data.get("run_url"),
        deployment=data.get("deployment", "not_started"),
        validation=data.get("validation"),
    )

    if state.use_all_purpose_cluster and IS_DATABRICKS_APP:
        state.all_purpose_cluster_id = get_cluster_id(email)

    import uuid
    session_id = str(uuid.uuid4())
    session = _Session(session_id)
    session.state = state
    _sessions[session_id] = session

    return {
        "session_id": session_id,
        "report_state": state.model_dump(),
    }


@router.delete("/{report_id}")
async def delete_saved_report(report_id: str, request: Request):
    """Delete a saved report."""
    email = _resolve_user_email(request)

    data = load_report(report_id)
    if not data:
        raise HTTPException(404, "Report not found")
    if data.get("_user_email") != email:
        raise HTTPException(403, "You do not own this report.")

    deleted = delete_report(report_id)
    if not deleted:
        raise HTTPException(404, "Report not found")
    return {"status": "deleted"}
