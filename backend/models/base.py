"""SQLAlchemy engine, session factory, and declarative base.

The ORM entities live in ``backend.models.entities``. Services receive a
``Session`` (via the ``get_db`` dependency) and talk to entities through it.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DSN = f"sqlite:///{( _ROOT / 'voiceagent.db').as_posix()}"

DATABASE_URL = os.getenv("VOICEAGENT_DB_URL", _DEFAULT_DSN)

_engine_kwargs = {"future": True}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_engine_kwargs)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM entities."""


def init_db() -> None:
    """Create all tables on the configured engine."""
    from backend.models import entities  # noqa: F401  (registers models)

    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()