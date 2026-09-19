"""Call arrangement, dispatch tracking, and live result ingestion."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.core.events import bus
from backend.models import Call, Evaluation, Patient, SessionLocal, Transcript, call_dict
from backend.schemas.call import CallCreate, ResultIn
from backend.services.livekit import dispatch_agent_call

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_call_or_error(db: Session, call_id: str) -> Call:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


def _build_metadata(patient: Patient, preferred_time: str) -> str:
    biomarkers = {
        b.name: {
            "value": b.value,
            "unit": b.unit,
            "reference_range": b.reference_range,
            "status": b.status,
        }
        for b in patient.biomarkers
    }
    return json.dumps(
        {
            "name": patient.name,
            "phone_number": patient.phone,
            "patient_id": patient.id,
            "biomarkers": biomarkers,
            "preferred_time": preferred_time,
        }
    )


def arrange_call(db: Session, body: CallCreate) -> tuple[dict, str, str, str]:
    """Create the call record and return (call_dict, call_id, room_name, metadata_json).

    Dispatches to LiveKit are scheduled by the endpoint as a background task
    via ``track_dispatch`` so the API returns immediately.
    """
    patient = db.get(Patient, body.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    call_id = uuid.uuid4().hex
    room_name = f"healthcare-call-{call_id[-8:]}-{int(time.time())}"
    metadata_json = _build_metadata(patient, body.preferred_time)

    call = Call(
        id=call_id,
        patient_id=patient.id,
        status="dispatched",
        preferred_time=body.preferred_time,
        room_name=room_name,
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    return call_dict(call), call_id, room_name, metadata_json


async def track_dispatch(call_id: str, room_name: str, metadata_json: str) -> None:
    """Dispatch the job to LiveKit; mark the call as errored on failure."""
    try:
        await dispatch_agent_call(room_name, metadata_json)
    except Exception as e:
        logger.exception("Dispatch failed for call %s", call_id)
        with SessionLocal() as s:
            call = s.get(Call, call_id)
            if call is not None:
                call.status = "error"
                call.outcome = "error"
                call.summary = f"Dispatch failed: {e}"
                s.commit()
        bus.publish(call_id, {"type": "status", "status": "error", "message": f"Dispatch failed: {e}"})
        return
    with SessionLocal() as s:
        call = s.get(Call, call_id)
        if call is not None and call.status in ("pending", "dispatched"):
            call.status = "accepted"
            s.commit()
    bus.publish(call_id, {"type": "status", "status": "accepted", "message": "Worker accepted the call job"})


def list_calls(db: Session, limit: int = 100) -> list[dict]:
    calls = db.scalars(
        select(Call)
        .options(selectinload(Call.patient))
        .order_by(Call.created_at.desc())
        .limit(limit)
    ).all()
    return [call_dict(c) for c in calls]


def get_call(db: Session, call_id: str) -> dict:
    call = db.scalars(
        select(Call)
        .options(
            selectinload(Call.patient).selectinload(Patient.biomarkers),
            selectinload(Call.transcript),
            selectinload(Call.evaluations),
        )
        .where(Call.id == call_id)
    ).one_or_none()
    if call is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return call_dict(call, include_extras=True)


def calls_for_patient(db: Session, patient_id: str) -> list[dict]:
    calls = db.scalars(
        select(Call)
        .options(selectinload(Call.patient))
        .where(Call.patient_id == patient_id)
        .order_by(Call.created_at.desc())
    ).all()
    return [call_dict(c) for c in calls]


def ingest_events(db: Session, call_id: str, events: list[dict]) -> dict[str, str]:
    call = _get_call_or_error(db, call_id)
    if call.status in ("completed", "error", "no_answer", "busy", "declined"):
        for ev in events:
            if ev.get("type") == "status":
                bus.publish(call_id, {"type": "status", "status": ev.get("status", call.status)})
        return {"ok": "true"}

    if call.status in ("pending", "dispatched", "accepted", "in_progress"):
        call.status = "in_progress"
        if call.started_at is None:
            call.started_at = _utcnow()

    for ev in events:
        etype = ev.get("type")
        if etype == "conversation":
            role = ev.get("role", "")
            content = ev.get("content", "")
            if role and content:
                call.transcript.append(Transcript(role=role, content=content))
            bus.publish(call_id, {"type": "conversation", "role": role, "content": content})
        elif etype == "status":
            bus.publish(call_id, {"type": "status", "status": ev.get("status", "in_progress")})
    db.commit()
    return {"ok": "true"}


def ingest_result(db: Session, call_id: str, body: ResultIn) -> dict[str, str]:
    call = _get_call_or_error(db, call_id)
    call.status = body.status
    call.outcome = body.outcome
    call.duration_seconds = body.duration_seconds
    call.appointment_booked = body.appointment_booked
    call.appointment_details = body.appointment_details
    call.patient_agreed_not_booked = body.patient_agreed_not_booked
    call.sentiment = body.sentiment
    call.key_topics = body.key_topics
    call.summary = body.summary
    call.ended_at = _utcnow()

    for turn in body.transcript:
        call.transcript.append(
            Transcript(role=turn.get("role", ""), content=turn.get("content", ""))
        )
    for ev in body.evaluations:
        call.evaluations.append(
            Evaluation(
                metric_name=ev.get("metric_name", ""),
                score=ev.get("score", 0),
                reason=ev.get("reason", ""),
                passed=bool(ev.get("passed", True)),
            )
        )
    db.commit()

    bus.publish(call_id, {"type": "result", "result": body.model_dump(), "status": body.status})
    bus.publish(call_id, {"type": "status", "status": body.status})
    return {"ok": "true"}