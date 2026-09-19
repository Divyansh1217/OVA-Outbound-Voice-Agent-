"""FastAPI application for the healthcare voice agent dashboard.

Run with:  uvicorn backend.main:app --reload --port 8001
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.endpoints import calls, dashboard, health, internal, patients
from backend.models.base import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized; dashboard API ready")
    yield


app = FastAPI(
    title="Healthcare Voice Agent API",
    version="1.0.0",
    description="Doctor dashboard API for arranging AI voice calls with patient reports.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (health.router, dashboard.router, patients.router, calls.router, internal.router):
    app.include_router(router)