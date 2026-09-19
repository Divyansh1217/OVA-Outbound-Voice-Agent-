"""Patient + biomarker report service."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.models import Biomarker, Patient, call_dict, patient_dict
from backend.schemas.patient import BiomarkerIn, PatientIn, PatientUpdate
from backend.services.call_service import calls_for_patient


def create_patient(db: Session, body: PatientIn) -> dict:
    patient = Patient(
        name=body.name.strip(),
        phone=body.phone.strip(),
        notes=body.notes.strip(),
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient_dict(patient)


def _latest_call_status(db: Session, patient_id: str) -> str | None:
    from sqlalchemy import select

    from backend.models.entities import Call

    call = db.scalars(
        select(Call).where(Call.patient_id == patient_id).order_by(Call.created_at.desc()).limit(1)
    ).first()
    return call.status if call else None


def list_patients(db: Session) -> list[dict]:
    patients = db.scalars(
        select(Patient)
        .options(selectinload(Patient.biomarkers))
        .order_by(Patient.created_at.desc())
    ).all()
    result = []
    for p in patients:
        data = patient_dict(p)
        data["biomarker_count"] = len(p.biomarkers)
        data["last_call_status"] = _latest_call_status(db, p.id)
        result.append(data)
    return result


def get_patient(db: Session, patient_id: str) -> dict:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    data = patient_dict(patient)
    data["calls"] = calls_for_patient(db, patient_id)
    return data


def update_patient(db: Session, patient_id: str, body: PatientUpdate) -> dict:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if body.name is not None:
        patient.name = body.name.strip()
    if body.phone is not None:
        patient.phone = body.phone.strip()
    if body.notes is not None:
        patient.notes = body.notes.strip()
    db.commit()
    db.refresh(patient)
    return patient_dict(patient)


def delete_patient(db: Session, patient_id: str) -> None:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    db.delete(patient)
    db.commit()


def _apply_biomarkers(patient: Patient, biomarkers: list[BiomarkerIn]) -> None:
    patient.biomarkers.clear()
    for b in biomarkers:
        patient.biomarkers.append(
            Biomarker(
                name=(b.name or "").strip(),
                value=(b.value or "").strip(),
                unit=(b.unit or "").strip(),
                reference_range=(b.reference_range or "").strip(),
                status=(b.status or "NORMAL").strip(),
            )
        )


def save_report(db: Session, patient_id: str, biomarkers: list[BiomarkerIn]) -> dict:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    _apply_biomarkers(patient, biomarkers)
    db.commit()
    db.refresh(patient)
    return patient_dict(patient)