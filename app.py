"""Impulse — FastAPI application.

Serves the REST API and the built React frontend as static files.
"""

import logging
import os
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Enable MLflow tracing for the agent (no-op if mlflow absent or disabled via env).
from server.observability import init_tracing
init_tracing()

app = FastAPI(title="Impulse", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return {"status": "ok"}


try:
    from server.routes import chat, deploy, ingest, reports, settings, state, timeseries, uc_browse, validate, visualize

    app.include_router(chat.router)
    app.include_router(state.router)
    app.include_router(deploy.router)
    app.include_router(validate.router)
    app.include_router(settings.router)
    app.include_router(reports.router)
    app.include_router(visualize.router)
    app.include_router(uc_browse.router)
    app.include_router(ingest.router)
    app.include_router(timeseries.router)
    logger.info("All API routers loaded successfully")

    from server.db import init_schema
    init_schema()
except Exception:
    logger.error("Failed to load API routers:\n%s", traceback.format_exc())

    @app.get("/api/{path:path}")
    async def api_error(path: str):
        return JSONResponse(
            status_code=503,
            content={"error": "Backend modules failed to load. Check app logs."},
        )


FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend", "dist")
logger.info("Looking for frontend at: %s (exists=%s)", FRONTEND_DIR, os.path.isdir(FRONTEND_DIR))

if os.path.isdir(FRONTEND_DIR):
    assets_dir = os.path.join(FRONTEND_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
        logger.info("Mounted /assets from %s", assets_dir)

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
else:
    @app.get("/")
    async def root():
        return {"message": "Impulse API", "docs": "/docs"}
