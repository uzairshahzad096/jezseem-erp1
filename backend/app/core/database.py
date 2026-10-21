"""
SQLAlchemy 2.x engine, session factory and declarative base.

Every ERP table inherits from Base. Multi-tenant tables additionally inherit
from the CompanyScopedMixin / AuditMixin defined in app/common/mixins.py.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # avoid stale connections after idle periods
    pool_size=10,
    max_overflow=20,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model in the application."""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a DB session and guarantees it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
