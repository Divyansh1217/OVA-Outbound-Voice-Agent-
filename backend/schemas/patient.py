"""Patient-related request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BiomarkerIn(BaseModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    unit: str = ""
    reference_range: str = ""
    status: str = "NORMAL"


class PatientIn(BaseModel):
    name: str = Field(min_length=1)
    phone: str = Field(min_length=3)
    notes: str = ""


class PatientUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    notes: str | None = None


class PatientReportIn(BaseModel):
    biomarkers: list[BiomarkerIn]