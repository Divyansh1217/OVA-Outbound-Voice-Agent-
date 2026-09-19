"""Dashboard stats endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.models import get_db
from backend.services import dashboard_service

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    return dashboard_service.stats(db)