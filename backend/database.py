"""
Database setup — SQLAlchemy engine, session, and init.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./jobhunter.db")

# Railway gives postgres:// but SQLAlchemy 2.x needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create all tables that don't exist yet."""
    from models import Base as _  # noqa: F401 — ensure models are imported
    Base.metadata.create_all(bind=engine)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    """
    Keep older local databases compatible with the current ORM model.
    This avoids hard failures when new nullable columns are introduced.
    """
    inspector = inspect(engine)
    if "scraped_jobs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("scraped_jobs")}
    statements: list[str] = []
    if "parsed_jd" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN parsed_jd JSON")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session, closes on teardown."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
