"""
Database setup — SQLAlchemy engine, session, and init.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import config as app_config


# Stable application-scoped key for PostgreSQL's transaction advisory lock.
# It serializes create_all plus the legacy repair pass across rolling replicas.
_SCHEMA_MIGRATION_LOCK_KEY = 0x4A485347
_ACTIVITY_METADATA_SCRUB_VERSION = "2026-08-23-recruitment-activity-metadata-scrub"
_DELETION_TOMBSTONE_SCRUB_VERSION = "2026-08-23-recruitment-deletion-tombstone-scrub"
_WORK_LOCATION_SCOPE_V2 = "2026-08-26-work-location-scope-v2"
_WORK_LOCATION_BACKFILL_BATCH_SIZE = 1000
_LEGACY_LOCATION_SOURCES = {
    "MyCareersFuture": "legacy_mcf_source_provisional_v1",
    "Careers@Gov": "legacy_careersgov_source_provisional_v1",
}
_LEGACY_MCF_SINGAPORE_LOCATIONS = frozenset(
    {
        "singapore",
        "central",
        "islandwide",
        "west",
        "north",
        "east",
        "north-east",
        "north east",
        "ngee ann city",
    }
)

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

    with engine.begin() as connection:
        _acquire_schema_migration_lock(connection)
        Base.metadata.create_all(bind=connection)
        _apply_lightweight_migrations(connection)


def _acquire_schema_migration_lock(connection) -> None:
    if getattr(getattr(connection, "dialect", None), "name", "") == "postgresql":
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _SCHEMA_MIGRATION_LOCK_KEY},
        )


def _apply_lightweight_migrations(connection=None) -> None:
    """
    Keep older local databases compatible with the current ORM model.
    This avoids hard failures when new nullable columns are introduced.

    When called directly, inspection and DDL run in one locked transaction.
    init_db passes its existing transaction so create_all and repair are one
    serialized operation on PostgreSQL.
    """
    if connection is None:
        with engine.begin() as migration_connection:
            _acquire_schema_migration_lock(migration_connection)
            _apply_lightweight_migrations(migration_connection)
        return

    inspector = inspect(connection)
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
    if "embedding_input_sha256" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN embedding_input_sha256 VARCHAR(64) DEFAULT ''")
    if "embedding_model_identity" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN embedding_model_identity VARCHAR(300) DEFAULT ''")
    if "closing_date" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN closing_date VARCHAR(100) DEFAULT ''")
    if "source_posting_id" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN source_posting_id VARCHAR(300) DEFAULT ''")
    if "openings" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN openings INTEGER DEFAULT 1")
    if "hidden" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN hidden INTEGER DEFAULT 0")
    if "retirement_reason" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN retirement_reason VARCHAR(30) DEFAULT ''")
    if "retired_at" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN retired_at VARCHAR(50) DEFAULT ''")
    if "sector" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN sector VARCHAR(100) DEFAULT ''")
    if "company_ssic_code" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN company_ssic_code VARCHAR(10) DEFAULT ''")
    if "company_ssic_description" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN company_ssic_description VARCHAR(300) DEFAULT ''")
    if "company_ssic_source" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN company_ssic_source VARCHAR(30) DEFAULT ''")
    if "direct_employer" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN direct_employer INTEGER NOT NULL DEFAULT -1")
    if "employer_relationship" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN employer_relationship VARCHAR(20)")
    if "employer_relationship_evidence" not in existing_columns:
        statements.append(
            "ALTER TABLE scraped_jobs ADD COLUMN employer_relationship_evidence VARCHAR(50) NOT NULL DEFAULT ''"
        )
    if "work_location_scope" not in existing_columns:
        statements.append(
            "ALTER TABLE scraped_jobs ADD COLUMN work_location_scope VARCHAR(20) NOT NULL DEFAULT 'unknown'"
        )
    if "work_location_scope_source" not in existing_columns:
        statements.append(
            "ALTER TABLE scraped_jobs ADD COLUMN work_location_scope_source VARCHAR(40) NOT NULL DEFAULT 'unknown'"
        )
    if "salary_floor" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN salary_floor INTEGER DEFAULT 0")
    if "skills_flat" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN skills_flat TEXT DEFAULT ''")
    if "content_hash" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN content_hash VARCHAR(64) DEFAULT ''")
    if "promotional_score" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN promotional_score INTEGER DEFAULT 0")
    if "company_promotional_score" not in existing_columns:
        statements.append("ALTER TABLE scraped_jobs ADD COLUMN company_promotional_score INTEGER DEFAULT 0")

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
        "ix_scraped_jobs_work_location_scope": "CREATE INDEX ix_scraped_jobs_work_location_scope ON scraped_jobs (work_location_scope)",
        "ix_scraped_jobs_employer_relationship": "CREATE INDEX ix_scraped_jobs_employer_relationship ON scraped_jobs (employer_relationship)",
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
            statements.append("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")

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
        if "match_cursor_at" not in alert_columns:
            statements.extend(
                (
                    "ALTER TABLE job_alert_preferences ADD COLUMN match_cursor_at TIMESTAMP",
                    "UPDATE job_alert_preferences SET match_cursor_at = last_run_at WHERE match_cursor_at IS NULL",
                )
            )

    if "job_alert_deliveries" in inspector.get_table_names():
        delivery_indexes = {index["name"] for index in inspector.get_indexes("job_alert_deliveries")}
        if "ux_job_alert_deliveries_user_job" not in delivery_indexes:
            # Keep the newest state for legacy duplicates before enforcing the
            # identity already assumed by record_delivery_action().
            statements.extend(
                (
                    "DELETE FROM job_alert_deliveries WHERE id IN ("
                    "SELECT id FROM ("
                    "SELECT id, ROW_NUMBER() OVER ("
                    "PARTITION BY user_id, scraped_job_id ORDER BY id DESC"
                    ") AS duplicate_rank FROM job_alert_deliveries"
                    ") ranked WHERE duplicate_rank > 1)",
                    "CREATE UNIQUE INDEX ux_job_alert_deliveries_user_job "
                    "ON job_alert_deliveries (user_id, scraped_job_id)",
                )
            )

    # usage_logs: rate limits and admin metrics should not full-scan forever
    if "usage_logs" in inspector.get_table_names():
        usage_indexes = {idx["name"] for idx in inspector.get_indexes("usage_logs")}
        usage_index_defs = {
            "ix_usage_logs_user_action_created": (
                "CREATE INDEX ix_usage_logs_user_action_created ON usage_logs (user_id, action, created_at)"
            ),
            "ix_usage_logs_action_created": (
                "CREATE INDEX ix_usage_logs_action_created ON usage_logs (action, created_at)"
            ),
        }
        for idx_name, idx_sql in usage_index_defs.items():
            if idx_name not in usage_indexes:
                statements.append(idx_sql)

    # target_assessment_artifacts: pending-state columns for resuming a paused
    # (ask_candidate) run with the candidate's answer
    if "target_assessment_artifacts" in inspector.get_table_names():
        assessment_columns = {col["name"] for col in inspector.get_columns("target_assessment_artifacts")}
        if "execution_metrics" not in assessment_columns:
            statements.append(
                "ALTER TABLE target_assessment_artifacts ADD COLUMN execution_metrics JSON NOT NULL DEFAULT '{}'"
            )
        if "pending_specialist_runs" not in assessment_columns:
            statements.append("ALTER TABLE target_assessment_artifacts ADD COLUMN pending_specialist_runs JSON")
        if "pending_synthesis" not in assessment_columns:
            statements.append("ALTER TABLE target_assessment_artifacts ADD COLUMN pending_synthesis TEXT")
        if "synthesis_claims" not in assessment_columns:
            statements.append(
                "ALTER TABLE target_assessment_artifacts ADD COLUMN synthesis_claims JSON NOT NULL DEFAULT '[]'"
            )
        if "pending_synthesis_claims" not in assessment_columns:
            statements.append("ALTER TABLE target_assessment_artifacts ADD COLUMN pending_synthesis_claims JSON")
        if "pending_proposed_edits" not in assessment_columns:
            statements.append("ALTER TABLE target_assessment_artifacts ADD COLUMN pending_proposed_edits JSON")

    if "candidate_profile_artifacts" in inspector.get_table_names():
        profile_columns = {col["name"] for col in inspector.get_columns("candidate_profile_artifacts")}
        if "execution_metrics" not in profile_columns:
            statements.append(
                "ALTER TABLE candidate_profile_artifacts ADD COLUMN execution_metrics JSON NOT NULL DEFAULT '{}'"
            )
        if "evaluation" not in profile_columns:
            statements.append("ALTER TABLE candidate_profile_artifacts ADD COLUMN evaluation JSON")

    if "recruitment_runs" in inspector.get_table_names():
        run_columns = {col["name"] for col in inspector.get_columns("recruitment_runs")}
        if "attempt_ledger" not in run_columns:
            statements.append("ALTER TABLE recruitment_runs ADD COLUMN attempt_ledger JSON NOT NULL DEFAULT '{}'")
        if "lease_owner" not in run_columns:
            statements.append("ALTER TABLE recruitment_runs ADD COLUMN lease_owner VARCHAR(64)")
        if "lease_expires_at" not in run_columns:
            statements.append("ALTER TABLE recruitment_runs ADD COLUMN lease_expires_at TIMESTAMP")

    if "recruitment_activity_events" in inspector.get_table_names():
        activity_columns = {col["name"] for col in inspector.get_columns("recruitment_activity_events")}
        if "parent_id" not in activity_columns:
            statements.append("ALTER TABLE recruitment_activity_events ADD COLUMN parent_id TEXT")
        if "duration_ms" not in activity_columns:
            statements.append("ALTER TABLE recruitment_activity_events ADD COLUMN duration_ms FLOAT")
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
    if getattr(getattr(connection, "dialect", None), "name", "") != "sqlite":
        summary_status_column = next(
            (column for column in inspector.get_columns("scraped_jobs") if column["name"] == "jd_summary_status"),
            None,
        )
        summary_status_length = (
            getattr(summary_status_column["type"], "length", None) if summary_status_column else None
        )
        if summary_status_length is not None and summary_status_length < 100:
            statements.append("ALTER TABLE scraped_jobs ALTER COLUMN jd_summary_status TYPE VARCHAR(100)")

    for statement in statements:
        connection.execute(text(statement))

    if "scraped_jobs" in inspector.get_table_names():
        _run_once_migration(
            connection,
            _WORK_LOCATION_SCOPE_V2,
            lambda: _backfill_work_location_scopes(connection),
        )

    if "recruitment_activity_events" in inspector.get_table_names():
        _run_once_migration(
            connection,
            _ACTIVITY_METADATA_SCRUB_VERSION,
            lambda: connection.execute(text("UPDATE recruitment_activity_events SET detail = '{}', attributes = '{}'")),
        )

    if "recruitment_thread_deletion_requests" in inspector.get_table_names():
        _run_once_migration(
            connection,
            _DELETION_TOMBSTONE_SCRUB_VERSION,
            lambda: connection.execute(
                text(
                    "UPDATE recruitment_thread_deletion_requests "
                    "SET status = 'completed', targets = '{}' "
                    "WHERE status <> 'cleanup_pending'"
                )
            ),
        )


def _backfill_work_location_scopes(
    connection,
    *,
    now: datetime | None = None,
) -> None:
    """Classify legacy rows that are public now or can become public at startup."""
    from job_visibility import public_job_cutoff_iso, resolve_work_location_scope

    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    cutoff = public_job_cutoff_iso(now=reference)
    today = reference.date().isoformat()
    visibility_sql = (
        "hidden = 0 "
        "AND (posted_at_sort IS NULL OR posted_at_sort = '' OR posted_at_sort >= :cutoff) "
        "AND (closing_date IS NULL OR closing_date = '' OR closing_date >= :today)"
    )
    mcf_singapore_locations = ", ".join(f"'{location}'" for location in sorted(_LEGACY_MCF_SINGAPORE_LOCATIONS))
    for source, scope_source in _LEGACY_LOCATION_SOURCES.items():
        source_location_sql = (
            "LOWER(TRIM(location)) = 'singapore'"
            if source == "Careers@Gov"
            else f"LOWER(TRIM(location)) IN ({mcf_singapore_locations})"
        )
        connection.execute(
            text(
                "UPDATE scraped_jobs SET work_location_scope = 'singapore', "
                "work_location_scope_source = :scope_source "
                f"WHERE {visibility_sql} AND source = :source "
                f"AND {source_location_sql} "
                "AND (work_location_scope <> 'singapore' "
                "OR work_location_scope_source <> :scope_source)"
            ),
            {
                "cutoff": cutoff,
                "today": today,
                "source": source,
                "scope_source": scope_source,
            },
        )

    last_id = 0
    while True:
        rows = list(
            connection.execute(
                text(
                    "SELECT id, source, location, title, description, "
                    "work_location_scope, work_location_scope_source FROM scraped_jobs "
                    f"WHERE id > :last_id AND {visibility_sql} "
                    "AND source IN (:mcf_source, :careersgov_source) "
                    "ORDER BY id LIMIT :batch_size"
                ),
                {
                    "last_id": last_id,
                    "batch_size": _WORK_LOCATION_BACKFILL_BATCH_SIZE,
                    "cutoff": cutoff,
                    "today": today,
                    "mcf_source": "MyCareersFuture",
                    "careersgov_source": "Careers@Gov",
                },
            ).mappings()
        )
        if not rows:
            return
        updates = []
        for row in rows:
            location = str(row["location"] or "")
            normalized = " ".join(location.split()).casefold()
            is_source_backed_singapore = (
                normalized == "singapore"
                if row["source"] == "Careers@Gov"
                else normalized in _LEGACY_MCF_SINGAPORE_LOCATIONS
                if row["source"] == "MyCareersFuture"
                else False
            )
            provisional = "singapore" if is_source_backed_singapore else "unknown"
            resolved = resolve_work_location_scope(
                provisional,
                location,
                str(row["title"] or ""),
                str(row["description"] or ""),
            )
            scope_source = (
                "text_override_v1"
                if resolved != provisional
                else _LEGACY_LOCATION_SOURCES[row["source"]]
                if provisional == "singapore"
                else "unknown"
            )
            stored_scope = str(row["work_location_scope"] or "unknown")
            stored_source = str(row["work_location_scope_source"] or "unknown")
            if resolved != stored_scope or scope_source != stored_source:
                updates.append(
                    {
                        "job_id": int(row["id"]),
                        "scope": resolved,
                        "scope_source": scope_source,
                    }
                )
        if updates:
            connection.execute(
                text(
                    "UPDATE scraped_jobs SET work_location_scope = :scope, "
                    "work_location_scope_source = :scope_source WHERE id = :job_id"
                ),
                updates,
            )
        last_id = int(rows[-1]["id"])


def _run_once_migration(connection, version: str, migrate) -> None:
    """Run one idempotent data repair and record it in the same transaction."""
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS app_schema_migrations ("
            "version VARCHAR(100) PRIMARY KEY, "
            "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
    )
    applied = connection.execute(
        text("SELECT version FROM app_schema_migrations WHERE version = :version"),
        {"version": version},
    ).scalar_one_or_none()
    if applied is not None:
        return
    migrate()
    connection.execute(
        text("INSERT INTO app_schema_migrations (version) VALUES (:version)"),
        {"version": version},
    )


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session, closes on teardown."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
