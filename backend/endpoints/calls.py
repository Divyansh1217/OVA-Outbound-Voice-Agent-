"""Call arrangement, history, and live SSE endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.core.events import bus, sse_frame
from backend.models import get_db
from backend.schemas.call import CallCreate
from backend.services import call_service, dashboard_service

router = APIRouter(prefix="/api/v1/calls", tags=["calls"])

_SNAPSHOT_KEYS = (
    "id",
    "status",
    "preferred_time",
    "room_name",
    "outcome",
    "summary",
    "appointment_booked",
    "patient_agreed_not_booked",
    "sentiment",
    "duration_seconds",
    "appointment_details",
    "key_topics",
)


@router.post("", status_code=201)
async def arrange_call(body: CallCreate, db: Session = Depends(get_db)) -> dict:
    """Arrange an AI voice call to the patient using their current report.

    The LiveKit worker must be running (`python main.py start`) to pick up the job.
    Progress streams via SSE on GET /api/v1/calls/{id}/events.
    """
    call, call_id, room_name, metadata_json = call_service.arrange_call(db, body)
    bus.publish(call_id, {"type": "status", "status": "dispatched", "message": "Call dispatched to the voice worker"})
    asyncio.create_task(call_service.track_dispatch(call_id, room_name, metadata_json))
    return call


@router.get("")
def list_calls(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {
        "calls": call_service.list_calls(db),
        "stats": dashboard_service.stats(db),
    }


@router.get("/{call_id}")
def get_call(call_id: str, db: Session = Depends(get_db)) -> dict:
    return call_service.get_call(db, call_id)


@router.get("/{call_id}/events")
async def call_events(call_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    """Server-Sent Events stream for live call updates."""
    call = call_service.get_call(db, call_id)

    async def gen():
        q = bus.subscribe(call_id)
        snapshot = {
            "type": "snapshot",
            "status": call["status"],
            "call": {k: call[k] for k in _SNAPSHOT_KEYS},
            "transcript": call.get("transcript", []),
            "evaluations": call.get("evaluations", []),
        }
        try:
            yield sse_frame(snapshot)
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield sse_frame(event)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(call_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )