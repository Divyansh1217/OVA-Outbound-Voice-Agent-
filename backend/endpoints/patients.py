"""Patient + report endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.models import get_db
from backend.schemas.patient import PatientIn, PatientReportIn, PatientUpdate
from backend.services import patient_service

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])


@router.post("", status_code=201)
def create_patient(body: PatientIn, db: Session = Depends(get_db)) -> dict:
    return patient_service.create_patient(db, body)


@router.get("")
def list_patients(db: Session = Depends(get_db)) -> list[dict]:
    return patient_service.list_patients(db)


@router.get("/{patient_id}")
def get_patient(patient_id: str, db: Session = Depends(get_db)) -> dict:
    return patient_service.get_patient(db, patient_id)


@router.put("/{patient_id}")
def update_patient(patient_id: str, body: PatientUpdate, db: Session = Depends(get_db)) -> dict:
    return patient_service.update_patient(db, patient_id, body)


@router.delete("/{patient_id}", status_code=204)
def delete_patient(patient_id: str, db: Session = Depends(get_db)) -> None:
    patient_service.delete_patient(db, patient_id)


@router.put("/{patient_id}/report")
def save_report(patient_id: str, body: PatientReportIn, db: Session = Depends(get_db)) -> dict:
    return patient_service.save_report(db, patient_id, body.biomarkers)