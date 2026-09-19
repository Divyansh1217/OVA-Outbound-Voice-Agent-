"""Serializers: ORM entities -> plain dicts for API responses."""

from __future__ import annotations

from typing import Any

from backend.models.entities import Biomarker, Call, Patient


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


def biomarker_dict(b: Biomarker) -> dict[str, Any]:
    return {
        "name": b.name,
        "value": b.value,
        "unit": b.unit,
        "reference_range": b.reference_range,
        "status": b.status,
    }


def patient_dict(p: Patient, include_calls: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": p.id,
        "name": p.name,
        "phone": p.phone,
        "notes": p.notes,
        "created_at": _iso(p.created_at),
        "updated_at": _iso(p.updated_at),
        "biomarkers": [biomarker_dict(b) for b in p.biomarkers],
    }
    if include_calls:
        data["calls"] = [call_dict(c) for c in p.calls]
    return data


def call_dict(c: Call, include_extras: bool = False) -> dict[str, Any]:
    """Serialize a Call. ``include_extras`` adds transcript, evaluations and the
    full patient report used by the call-detail endpoint."""
    patient = c.patient
    data: dict[str, Any] = {
        "id": c.id,
        "patient_id": c.patient_id,
        "patient_name": patient.name if patient else None,
        "patient_phone": patient.phone if patient else None,
        "status": c.status,
        "preferred_time": c.preferred_time,
        "room_name": c.room_name,
        "created_at": _iso(c.created_at),
        "started_at": _iso(c.started_at),
        "ended_at": _iso(c.ended_at),
        "duration_seconds": c.duration_seconds,
        "outcome": c.outcome,
        "appointment_booked": c.appointment_booked,
        "appointment_details": c.appointment_details or {},
        "patient_agreed_not_booked": c.patient_agreed_not_booked,
        "sentiment": c.sentiment,
        "key_topics": c.key_topics or [],
        "summary": c.summary,
    }
    if include_extras:
        data["transcript"] = [
            {"role": t.role, "content": t.content, "timestamp": _iso(t.timestamp)}
            for t in c.transcript
        ]
        data["evaluations"] = [
            {
                "metric_name": e.metric_name,
                "score": e.score,
                "reason": e.reason,
                "passed": e.passed,
            }
            for e in c.evaluations
        ]
        data["biomarkers"] = [biomarker_dict(b) for b in patient.biomarkers] if patient else []
        data["patient"] = (
            {
                "id": patient.id,
                "name": patient.name,
                "phone": patient.phone,
                "biomarkers": [biomarker_dict(b) for b in patient.biomarkers],
            }
            if patient
            else None
        )
    return data