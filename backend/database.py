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
    if "posted_at_sort" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN posted_at_sort VARCHAR(50)")
    if "jd_summary" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN jd_summary TEXT")
    if "jd_summary_generated_at" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN jd_summary_generated_at VARCHAR(50)")
    if "jd_summary_status" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN jd_summary_status VARCHAR(100)")
    if "job_terms_preview" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN job_terms_preview JSON")

    # Add indexes if they don't exist (safe for Postgres and SQLite)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("scraped_jobs")}
    index_defs = {
        "ix_scraped_jobs_posted_sort": "CREATE INDEX ix_scraped_jobs_posted_sort ON scraped_jobs (posted_at_sort)",
        "ix_scraped_jobs_source": "CREATE INDEX ix_scraped_jobs_source ON scraped_jobs (source)",
        "ix_scraped_jobs_location": "CREATE INDEX ix_scraped_jobs_location ON scraped_jobs (location)",
        "ix_scraped_jobs_seniority": "CREATE INDEX ix_scraped_jobs_seniority ON scraped_jobs (seniority)",
        "ix_scraped_jobs_emp_type": "CREATE INDEX ix_scraped_jobs_emp_type ON scraped_jobs (employment_type)",
    }
    for idx_name, idx_sql in index_defs.items():
        if idx_name not in existing_indexes:
            statements.append(idx_sql)

    # Widen jd_summary_status if it was created as VARCHAR(30) (too short for model names)
    if "jd_summary_status" in existing_columns:
        try:
            # Postgres: ALTER COLUMN TYPE
            statements.append("ALTER TABLE scraped_jobs ALTER COLUMN jd_summary_status TYPE VARCHAR(100)")
        except Exception:
            pass  # SQLite doesn't support ALTER COLUMN TYPE, but doesn't enforce VARCHAR length anyway

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            try:
                connection.execute(text(statement))
            except Exception:
                pass  # Skip if already applied


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session, closes on teardown."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
