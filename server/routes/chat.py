"""Chat endpoint — /api/chat

Receives a user message, runs the LLM agent, returns the assistant response
together with the updated ReportState.
"""

import logging
import traceback

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from server.agent import run_agent
from server.models import ChatMessage, ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    user_token = request.headers.get("x-forwarded-access-token")
    try:
        assistant_text, report_state, session_id = run_agent(
            req.message, req.session_id, user_token=user_token
        )
        return ChatResponse(
            message=ChatMessage(role="assistant", content=assistant_text),
            report_state=report_state,
            session_id=session_id,
        )
    except Exception as e:
        logger.exception("Chat endpoint error")
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "traceback": traceback.format_exc()},
        )
