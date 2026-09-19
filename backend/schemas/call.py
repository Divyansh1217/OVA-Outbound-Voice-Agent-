"""Call-related request/response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CallCreate(BaseModel):
    patient_id: str
    preferred_time: str = "morning"


class EventIn(BaseModel):
    events: list[dict[str, Any]]


class ResultIn(BaseModel):
    status: str = "completed"
    outcome: str = "completed"
    duration_seconds: float = 0.0
    appointment_booked: bool = False
    appointment_details: dict[str, Any] = Field(default_factory=dict)
    patient_agreed_not_booked: bool = False
    key_topics: list[str] = Field(default_factory=list)
    sentiment: str = ""
    summary: str = ""
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    evaluations: list[dict[str, Any]] = Field(default_factory=list)