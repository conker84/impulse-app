"""User settings endpoints — cluster and model preferences.

The PAT-management routes were removed when the app moved to SP-as-orchestrator
for job ops (see TASKS.md).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.config import IS_DATABRICKS_APP, SERVING_ENDPOINT, get_available_models
from server.token_store import (
    get_cluster_id, get_serving_endpoint,
    store_cluster_id, store_serving_endpoint,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _resolve_user_email(request: Request) -> str:
    """Extract the calling user's email from the X-Forwarded-Email header."""
    if not IS_DATABRICKS_APP:
        return "local-dev@localhost"
    email = request.headers.get("X-Forwarded-Email", "")
    if not email:
        raise HTTPException(401, "Missing X-Forwarded-Email header")
    return email


@router.get("/token-status")
async def token_status(request: Request):
    """Return user preferences (cluster ID, serving endpoint, available models).

    Endpoint name is legacy — kept for frontend compat. PAT fields are
    unconditionally true since no PAT is needed anymore.
    """
    available_models = get_available_models()
    if not IS_DATABRICKS_APP:
        return {
            "local_mode": True,
            "has_token": True,
            "cluster_id": "",
            "serving_endpoint": SERVING_ENDPOINT,
            "available_models": available_models,
        }

    email = _resolve_user_email(request)
    return {
        "local_mode": False,
        "has_token": True,
        "user_email": email,
        "cluster_id": get_cluster_id(email),
        "serving_endpoint": get_serving_endpoint(email) or SERVING_ENDPOINT,
        "available_models": available_models,
    }


class ClusterRequest(BaseModel):
    cluster_id: str = ""


@router.post("/cluster")
async def save_cluster(request: Request, body: ClusterRequest):
    """Store the all-purpose cluster ID for the calling user."""
    if not IS_DATABRICKS_APP:
        return {"status": "skipped", "message": "Local mode — cluster config not persisted."}

    email = _resolve_user_email(request)
    store_cluster_id(email, body.cluster_id.strip())
    return {"status": "saved", "cluster_id": body.cluster_id.strip(), "user_email": email}


class ModelRequest(BaseModel):
    serving_endpoint: str


@router.post("/model")
async def save_model(request: Request, body: ModelRequest):
    """Store the preferred serving endpoint for the calling user."""
    valid_ids = {m["id"] for m in get_available_models()}
    if body.serving_endpoint and body.serving_endpoint not in valid_ids:
        raise HTTPException(400, f"Invalid model. Choose from: {', '.join(sorted(valid_ids))}")

    if not IS_DATABRICKS_APP:
        return {"status": "skipped", "message": "Local mode — model preference not persisted."}

    email = _resolve_user_email(request)
    store_serving_endpoint(email, body.serving_endpoint)
    return {"status": "saved", "serving_endpoint": body.serving_endpoint, "user_email": email}
