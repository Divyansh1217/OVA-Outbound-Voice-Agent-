"""Internal webhooks fed by the LiveKit agent worker.

These are kept off the public surface (marked internal) — only the worker should
POST here. They are async so event-bus publishes always happen on the event loop
thread (asyncio.Queue is not cross-thread safe).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.models import get_db
from backend.schemas.call import EventIn, ResultIn
from backend.services import call_service

router = APIRouter(prefix="/api/v1/internal/calls", tags=["internal"])


@router.post("/{call_id}/events")
async def ingest_events(call_id: str, body: EventIn, db: Session = Depends(get_db)) -> dict[str, str]:
    return call_service.ingest_events(db, call_id, body.events)


@router.post("/{call_id}/result")
async def ingest_result(call_id: str, body: ResultIn, db: Session = Depends(get_db)) -> dict[str, str]:
    return call_service.ingest_result(db, call_id, body)