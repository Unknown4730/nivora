"""FastAPI application entry point for the AURA-Med backend."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router
from .live_routes import router as live_router
from .schemas import ServiceInfo


SERVICE_NAME = "aura-med-backend"
SERVICE_VERSION = "0.2.0"


def _cors_origins() -> list[str]:
    configured = os.getenv("AURA_MED_CORS_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


app = FastAPI(
    title="AURA-Med Signal Reliability Backend",
    description=(
        "Deterministic, local-first research backend for simulated physiological "
        "signal reliability experiments."
    ),
    version=SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(router)
app.include_router(live_router)

_frontend_dir = os.getenv("AURA_MED_FRONTEND_DIR")
if _frontend_dir and Path(_frontend_dir).is_dir():
    app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


@app.get("/", response_model=ServiceInfo, tags=["service"])
def service_info() -> ServiceInfo:
    return ServiceInfo(service=SERVICE_NAME, version=SERVICE_VERSION, status="ready")


@app.get("/health", response_model=ServiceInfo, tags=["service"])
def health() -> ServiceInfo:
    return ServiceInfo(service=SERVICE_NAME, version=SERVICE_VERSION, status="ok")
