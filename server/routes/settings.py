"""User settings endpoints — PAT management.

Temporary workaround: stores Personal Access Tokens so the app can
deploy and run jobs on behalf of end users.  Will be removed once
Databricks Apps support the required OAuth scopes for job deployment.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.config import IS_DATABRICKS_APP
from server.token_store import delete_pat, get_cluster_id, has_pat, store_cluster_id, store_pat

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


class TokenRequest(BaseModel):
    pat: str


@router.get("/token-status")
async def token_status(request: Request):
    """Check whether the user has a stored PAT and cluster config."""
    if not IS_DATABRICKS_APP:
        return {"local_mode": True, "has_token": True, "cluster_id": ""}

    email = _resolve_user_email(request)
    return {
        "local_mode": False,
        "has_token": has_pat(email),
        "user_email": email,
        "cluster_id": get_cluster_id(email),
    }


@router.post("/token")
async def save_token(request: Request, body: TokenRequest):
    """Store an encrypted PAT for the calling user."""
    if not IS_DATABRICKS_APP:
        return {"status": "skipped", "message": "Local mode — PAT storage not needed."}

    email = _resolve_user_email(request)
    if not body.pat or not body.pat.startswith("dapi"):
        raise HTTPException(400, "Invalid PAT. Databricks PATs start with 'dapi'.")

    store_pat(email, body.pat)
    return {"status": "saved", "user_email": email}


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


@router.delete("/token")
async def remove_token(request: Request):
    """Delete the stored PAT for the calling user."""
    if not IS_DATABRICKS_APP:
        return {"status": "skipped", "message": "Local mode — no PAT to delete."}

    email = _resolve_user_email(request)
    deleted = delete_pat(email)
    if not deleted:
        raise HTTPException(404, "No stored PAT found for your account.")
    return {"status": "deleted", "user_email": email}
