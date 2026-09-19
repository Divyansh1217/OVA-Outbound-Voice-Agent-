"""ORM entities for the healthcare voice agent dashboard (SQLAlchemy 2.0 style)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    biomarkers: Mapped[list[Biomarker]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
        order_by="Biomarker.id",
    )
    calls: Mapped[list[Call]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )


class Biomarker(Base):
    __tablename__ = "biomarkers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(64), default="")
    reference_range: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(32), default="NORMAL")

    patient: Mapped[Patient] = relationship(back_populates="biomarkers")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_id)
    patient_id: Mapped[str] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    preferred_time: Mapped[str] = mapped_column(String(32), default="morning")
    room_name: Mapped[str] = mapped_column(String(255), default="")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0)
    outcome: Mapped[str] = mapped_column(String(64), default="")
    appointment_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    appointment_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    patient_agreed_not_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    sentiment: Mapped[str] = mapped_column(String(32), default="")
    key_topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")

    patient: Mapped[Patient] = relationship(back_populates="calls")
    transcript: Mapped[list[Transcript]] = relationship(
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="Transcript.id",
    )
    evaluations: Mapped[list[Evaluation]] = relationship(
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="Evaluation.id",
    )


class Transcript(Base):
    __tablename__ = "transcript"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    call: Mapped[Call] = relationship(back_populates="transcript")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    metric_name: Mapped[str] = mapped_column(String(128))
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    passed: Mapped[bool] = mapped_column(Boolean, default=True)

    call: Mapped[Call] = relationship(back_populates="evaluations")