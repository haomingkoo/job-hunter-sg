"""
Database setup — SQLAlchemy engine, session, and init.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import config as app_config

DEFAULT_DATABASE_PATH = Path(__file__).resolve().with_name("jobhunter.db")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE_PATH}")

# Railway gives postgres:// but SQLAlchemy 2.x needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine_kwargs = {"connect_args": connect_args}
if not DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update(
        pool_pre_ping=True,
        pool_size=app_config.DATABASE_POOL_SIZE,
        max_overflow=app_config.DATABASE_MAX_OVERFLOW,
        pool_timeout=app_config.DATABASE_POOL_TIMEOUT,
        pool_recycle=app_config.DATABASE_POOL_RECYCLE_SECONDS,
    )

engine = create_engine(DATABASE_URL, **engine_kwargs)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
    if "embedding_vector" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN embedding_vector JSON")
    if "closing_date" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN closing_date VARCHAR(100) DEFAULT ''")
    if "source_posting_id" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN source_posting_id VARCHAR(300) DEFAULT ''")
    if "openings" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN openings INTEGER DEFAULT 1")
    if "hidden" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN hidden INTEGER DEFAULT 0")
    if "sector" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN sector VARCHAR(100) DEFAULT ''")
    if "company_ssic_code" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN company_ssic_code VARCHAR(10) DEFAULT ''")
    if "company_ssic_description" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN company_ssic_description VARCHAR(300) DEFAULT ''")
    if "company_ssic_source" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN company_ssic_source VARCHAR(30) DEFAULT ''")
    if "salary_floor" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN salary_floor INTEGER DEFAULT 0")
    if "skills_flat" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN skills_flat TEXT DEFAULT ''")
    if "content_hash" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN content_hash VARCHAR(64) DEFAULT ''")
    if "promotional_score" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN promotional_score INTEGER DEFAULT 0")
    if "company_promotional_score" not in existing_columns:
        statements.append(
            "ALTER TABLE scraped_jobs ADD COLUMN company_promotional_score INTEGER DEFAULT 0"
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("scraped_jobs")}
    index_defs = {
        "ix_scraped_jobs_posted_sort": "CREATE INDEX ix_scraped_jobs_posted_sort ON scraped_jobs (posted_at_sort)",
        "ix_scraped_jobs_source": "CREATE INDEX ix_scraped_jobs_source ON scraped_jobs (source)",
        "ix_scraped_jobs_location": "CREATE INDEX ix_scraped_jobs_location ON scraped_jobs (location)",
        "ix_scraped_jobs_seniority": "CREATE INDEX ix_scraped_jobs_seniority ON scraped_jobs (seniority)",
        "ix_scraped_jobs_emp_type": "CREATE INDEX ix_scraped_jobs_emp_type ON scraped_jobs (employment_type)",
        "ix_scraped_jobs_sector": "CREATE INDEX ix_scraped_jobs_sector ON scraped_jobs (sector)",
        "ix_scraped_jobs_source_posting": "CREATE INDEX ix_scraped_jobs_source_posting ON scraped_jobs (source, source_posting_id)",
        "ix_scraped_jobs_ssic_code": "CREATE INDEX ix_scraped_jobs_ssic_code ON scraped_jobs (company_ssic_code)",
        "ix_scraped_jobs_ssic_source": "CREATE INDEX ix_scraped_jobs_ssic_source ON scraped_jobs (company_ssic_source)",
        "ix_scraped_jobs_salary_floor": "CREATE INDEX ix_scraped_jobs_salary_floor ON scraped_jobs (salary_floor)",
        "ix_scraped_jobs_content_hash": "CREATE INDEX ix_scraped_jobs_content_hash ON scraped_jobs (content_hash)",
        "ix_scraped_jobs_promotional": "CREATE INDEX ix_scraped_jobs_promotional ON scraped_jobs (promotional_score)",
    }
    for idx_name, idx_sql in index_defs.items():
        if idx_name not in existing_indexes:
            statements.append(idx_sql)

    if "users" in inspector.get_table_names():
        user_columns = {col["name"] for col in inspector.get_columns("users")}
        if "terms_accepted_at" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN terms_accepted_at TIMESTAMP")
        if "privacy_accepted_at" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN privacy_accepted_at TIMESTAMP")
        if "email_verified_at" not in user_columns:
            statements.append("ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP")
        if "token_version" not in user_columns:
            statements.append(
                "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
            )

    if "tracked_jobs" in inspector.get_table_names():
        tracked_columns = {col["name"] for col in inspector.get_columns("tracked_jobs")}
        if "resume_version_id" not in tracked_columns:
            statements.append("ALTER TABLE tracked_jobs ADD COLUMN resume_version_id INTEGER")
        if "stage_history" not in tracked_columns:
            statements.append("ALTER TABLE tracked_jobs ADD COLUMN stage_history JSON")
        if "source_url" not in tracked_columns:
            statements.append("ALTER TABLE tracked_jobs ADD COLUMN source_url TEXT DEFAULT ''")
        if "job_description" not in tracked_columns:
            statements.append("ALTER TABLE tracked_jobs ADD COLUMN job_description TEXT DEFAULT ''")
        if "role_metadata" not in tracked_columns:
            statements.append("ALTER TABLE tracked_jobs ADD COLUMN role_metadata JSON")

    if "user_memories" in inspector.get_table_names():
        memory_columns = {col["name"] for col in inspector.get_columns("user_memories")}
        if "resume_embedding" not in memory_columns:
            statements.append("ALTER TABLE user_memories ADD COLUMN resume_embedding JSON")

    if "job_alert_preferences" in inspector.get_table_names():
        alert_columns = {col["name"] for col in inspector.get_columns("job_alert_preferences")}
        if "consented_at" not in alert_columns:
            statements.append("ALTER TABLE job_alert_preferences ADD COLUMN consented_at TIMESTAMP")
        if "unsubscribed_at" not in alert_columns:
            statements.append("ALTER TABLE job_alert_preferences ADD COLUMN unsubscribed_at TIMESTAMP")

    # usage_logs: rate limits and admin metrics should not full-scan forever
    if "usage_logs" in inspector.get_table_names():
        usage_indexes = {idx["name"] for idx in inspector.get_indexes("usage_logs")}
        usage_index_defs = {
            "ix_usage_logs_user_action_created": (
                "CREATE INDEX ix_usage_logs_user_action_created "
                "ON usage_logs (user_id, action, created_at)"
            ),
            "ix_usage_logs_action_created": (
                "CREATE INDEX ix_usage_logs_action_created "
                "ON usage_logs (action, created_at)"
            ),
        }
        for idx_name, idx_sql in usage_index_defs.items():
            if idx_name not in usage_indexes:
                statements.append(idx_sql)

    # target_assessment_artifacts: pending-state columns for resuming a paused
    # (ask_candidate) run with the candidate's answer
    if "target_assessment_artifacts" in inspector.get_table_names():
        assessment_columns = {col["name"] for col in inspector.get_columns("target_assessment_artifacts")}
        if "pending_specialist_runs" not in assessment_columns:
            statements.append("ALTER TABLE target_assessment_artifacts ADD COLUMN pending_specialist_runs JSON")
        if "pending_synthesis" not in assessment_columns:
            statements.append("ALTER TABLE target_assessment_artifacts ADD COLUMN pending_synthesis TEXT")
        if "pending_proposed_edits" not in assessment_columns:
            statements.append("ALTER TABLE target_assessment_artifacts ADD COLUMN pending_proposed_edits JSON")

    if "recruitment_activity_events" in inspector.get_table_names():
        activity_columns = {
            col["name"] for col in inspector.get_columns("recruitment_activity_events")
        }
        if "parent_id" not in activity_columns:
            statements.append(
                "ALTER TABLE recruitment_activity_events ADD COLUMN parent_id TEXT"
            )
        if "duration_ms" not in activity_columns:
            statements.append(
                "ALTER TABLE recruitment_activity_events ADD COLUMN duration_ms FLOAT"
            )
        if "attributes" not in activity_columns:
            statements.append(
                "ALTER TABLE recruitment_activity_events ADD COLUMN attributes JSON NOT NULL DEFAULT '{}'"
            )

    if "proposed_resume_edits" in inspector.get_table_names():
        edit_columns = {col["name"] for col in inspector.get_columns("proposed_resume_edits")}
        if "evidence_ids" not in edit_columns:
            statements.append("ALTER TABLE proposed_resume_edits ADD COLUMN evidence_ids JSON")

    # Widen jd_summary_status if it was created as VARCHAR(30) (too short for
    # model names). SQLite's ALTER TABLE has no "change column type"
    # operation -- this only runs against Postgres, which does.
    if not DATABASE_URL.startswith("sqlite"):
        summary_status_column = next(
            (column for column in inspector.get_columns("scraped_jobs") if column["name"] == "jd_summary_status"),
            None,
        )
        summary_status_length = (
            getattr(summary_status_column["type"], "length", None) if summary_status_column else None
        )
        if summary_status_length is not None and summary_status_length < 100:
            statements.append("ALTER TABLE scraped_jobs ALTER COLUMN jd_summary_status TYPE VARCHAR(100)")

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
