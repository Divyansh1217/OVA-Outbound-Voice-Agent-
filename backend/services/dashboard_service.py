"""Dashboard stats service."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import Call, Patient


def stats(db: Session) -> dict:
    today_prefix = datetime.now(timezone.utc).isoformat()[:10]
    completed_statuses = ("completed", "no_answer", "busy", "declined")

    def count(statement) -> int:
        return db.scalar(statement) or 0

    return {
        "patients": count(select(func.count()).select_from(Patient)),
        "calls": count(select(func.count()).select_from(Call)),
        "in_progress": count(
            select(func.count()).select_from(Call).where(Call.status == "in_progress")
        ),
        "completed": count(
            select(func.count())
            .select_from(Call)
            .where(Call.status.in_(completed_statuses))
        ),
        "appointments_booked": count(
            select(func.count()).select_from(Call).where(Call.appointment_booked.is_(True))
        ),
        "today": count(
            select(func.count()).select_from(Call).where(Call.created_at.like(f"{today_prefix}%"))
        ),
    }