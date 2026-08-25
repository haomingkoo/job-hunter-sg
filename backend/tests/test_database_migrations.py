from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text


def test_default_database_path_does_not_depend_on_working_directory(tmp_path):
    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = str(backend_dir)

    result = subprocess.run(
        [sys.executable, "-c", "import database; print(database.DATABASE_URL)"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == f"sqlite:///{backend_dir / 'jobhunter.db'}"


def test_legacy_work_location_backfill_is_provisional_overseas_safe_and_batched(monkeypatch):
    import database
    from models import Base, ScrapedJob

    monkeypatch.setattr(database, "_WORK_LOCATION_BACKFILL_BATCH_SIZE", 2)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            ScrapedJob.__table__.insert(),
            [
                {
                    "id": 1,
                    "title": "Engineer",
                    "company": "Example",
                    "location": "NGEE ANN CITY",
                    "source": "MyCareersFuture",
                    "description": "Build products in Singapore.",
                    "dedup_key": "scope-backfill-1",
                },
                {
                    "id": 2,
                    "title": "Engineer",
                    "company": "Example",
                    "location": "Singapore",
                    "source": "MyCareersFuture",
                    "description": "Location: Shanghai, China",
                    "dedup_key": "scope-backfill-2",
                },
                {
                    "id": 3,
                    "title": "Engineer",
                    "company": "Example",
                    "location": "",
                    "source": "MyCareersFuture",
                    "description": "Location: Singapore",
                    "dedup_key": "scope-backfill-3",
                },
            ],
        )
        database._backfill_work_location_scopes(connection)
        rows = connection.execute(
            text("SELECT id, work_location_scope, work_location_scope_source FROM scraped_jobs ORDER BY id")
        ).all()

    assert rows == [
        (1, "singapore", "legacy_mcf_source_provisional_v1"),
        (2, "overseas", "text_override_v1"),
        (3, "unknown", "unknown"),
    ]


def test_legacy_users_remain_unverified_when_verification_column_is_added(monkeypatch):
    import database

    scraped_columns = {
        "parsed_jd",
        "posted_at_sort",
        "jd_summary",
        "jd_summary_generated_at",
        "jd_summary_status",
        "job_terms_preview",
        "embedding_vector",
        "closing_date",
        "source_posting_id",
        "openings",
        "hidden",
        "sector",
        "company_ssic_code",
        "company_ssic_description",
        "company_ssic_source",
        "salary_floor",
        "skills_flat",
    }
    scraped_indexes = {
        "ix_scraped_jobs_posted_sort",
        "ix_scraped_jobs_source",
        "ix_scraped_jobs_location",
        "ix_scraped_jobs_seniority",
        "ix_scraped_jobs_emp_type",
        "ix_scraped_jobs_sector",
        "ix_scraped_jobs_source_posting",
        "ix_scraped_jobs_ssic_code",
        "ix_scraped_jobs_ssic_source",
        "ix_scraped_jobs_salary_floor",
    }

    class Inspector:
        def get_table_names(self):
            return [
                "scraped_jobs",
                "users",
                "recruitment_activity_events",
                "proposed_resume_edits",
                "recruitment_runs",
                "candidate_profile_artifacts",
                "target_assessment_artifacts",
                "job_alert_preferences",
            ]

        def get_columns(self, table):
            if table == "scraped_jobs":
                names = scraped_columns
            elif table == "users":
                names = {"id", "email", "tier", "terms_accepted_at", "privacy_accepted_at"}
            elif table == "proposed_resume_edits":
                names = {"id", "rewrite"}
            elif table == "job_alert_preferences":
                names = {"id", "last_run_at", "consented_at", "unsubscribed_at"}
            else:
                names = {"id", "thread_id", "run_id"}
            return [{"name": name, "type": object()} for name in names]

        def get_indexes(self, table):
            names = scraped_indexes if table == "scraped_jobs" else set()
            return [{"name": name} for name in names]

    statements = []

    class Result:
        def scalar_one_or_none(self):
            return None

        def mappings(self):
            return []

    class Connection:
        def execute(self, statement, _parameters=None):
            statements.append(str(statement))
            return Result()

    class Engine:
        @contextmanager
        def begin(self):
            yield Connection()

    monkeypatch.setattr(database, "inspect", lambda _engine: Inspector())
    monkeypatch.setattr(database, "engine", Engine())

    database._apply_lightweight_migrations()

    assert "ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP" in statements
    assert "ALTER TABLE scraped_jobs ADD COLUMN retirement_reason VARCHAR(30) DEFAULT ''" in statements
    assert "ALTER TABLE scraped_jobs ADD COLUMN retired_at VARCHAR(50) DEFAULT ''" in statements
    assert "ALTER TABLE scraped_jobs ADD COLUMN embedding_input_sha256 VARCHAR(64) DEFAULT ''" in statements
    assert "ALTER TABLE scraped_jobs ADD COLUMN embedding_model_identity VARCHAR(300) DEFAULT ''" in statements
    assert "ALTER TABLE scraped_jobs ADD COLUMN direct_employer INTEGER NOT NULL DEFAULT -1" in statements
    assert not any("ix_scraped_jobs_direct_employer" in item for item in statements)
    assert "ALTER TABLE recruitment_activity_events ADD COLUMN parent_id TEXT" in statements
    assert "ALTER TABLE recruitment_activity_events ADD COLUMN duration_ms FLOAT" in statements
    assert any("recruitment_activity_events ADD COLUMN attributes JSON" in item for item in statements)
    assert "ALTER TABLE proposed_resume_edits ADD COLUMN evidence_ids JSON" in statements
    assert (
        "ALTER TABLE candidate_profile_artifacts ADD COLUMN execution_metrics JSON NOT NULL DEFAULT '{}'" in statements
    )
    assert "ALTER TABLE candidate_profile_artifacts ADD COLUMN evaluation JSON" in statements
    assert (
        "ALTER TABLE target_assessment_artifacts ADD COLUMN execution_metrics JSON NOT NULL DEFAULT '{}'" in statements
    )
    assert "ALTER TABLE recruitment_runs ADD COLUMN attempt_ledger JSON NOT NULL DEFAULT '{}'" in statements
    assert "ALTER TABLE recruitment_runs ADD COLUMN lease_owner VARCHAR(64)" in statements
    assert "ALTER TABLE recruitment_runs ADD COLUMN lease_expires_at TIMESTAMP" in statements
    assert "ALTER TABLE job_alert_preferences ADD COLUMN match_cursor_at TIMESTAMP" in statements
    assert (
        "UPDATE job_alert_preferences SET match_cursor_at = last_run_at WHERE match_cursor_at IS NULL"
    ) in statements
    assert not any("SET email_verified_at" in statement for statement in statements)
    assert not any("SET tier = 'user'" in statement for statement in statements)


def test_postgres_schema_repairs_take_a_transaction_advisory_lock():
    import database

    calls = []

    class Dialect:
        name = "postgresql"

    class Connection:
        dialect = Dialect()

        def execute(self, statement, parameters):
            calls.append((str(statement), parameters))

    database._acquire_schema_migration_lock(Connection())

    assert calls == [
        (
            "SELECT pg_advisory_xact_lock(:key)",
            {"key": database._SCHEMA_MIGRATION_LOCK_KEY},
        )
    ]


def test_legacy_recruitment_activity_metadata_is_scrubbed_once(tmp_path, monkeypatch):
    import database
    import models  # noqa: F401 - register every table on Base.metadata

    test_engine = create_engine(f"sqlite:///{tmp_path / 'activity-scrub.db'}")
    database.Base.metadata.create_all(bind=test_engine)
    with test_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recruitment_activity_events "
                "(thread_id, run_id, sequence, event_type, status, team_member, attempt, "
                "trace_key, summary, detail, attributes, created_at) VALUES "
                "('thread-1', 'run-1', 1, 'assessment', 'completed', 'coordinator', 1, "
                "'trace', 'Safe summary', '{\"query\": \"private search\"}', "
                '\'{"prompt": "private prompt"}\', CURRENT_TIMESTAMP)'
            )
        )

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'activity-scrub.db'}")
    database._apply_lightweight_migrations()
    database._apply_lightweight_migrations()

    with test_engine.connect() as connection:
        row = connection.execute(
            text("SELECT detail, attributes FROM recruitment_activity_events WHERE run_id = 'run-1'")
        ).one()
        versions = connection.execute(
            text("SELECT version FROM app_schema_migrations WHERE version = :version"),
            {"version": database._ACTIVITY_METADATA_SCRUB_VERSION},
        ).all()

    assert tuple(json.loads(value) for value in row) == ({}, {})
    assert versions == [(database._ACTIVITY_METADATA_SCRUB_VERSION,)]
    test_engine.dispose()


def test_legacy_thread_deletion_requests_become_content_free_tombstones(tmp_path, monkeypatch):
    import database
    import models  # noqa: F401 - register every table on Base.metadata

    test_engine = create_engine(f"sqlite:///{tmp_path / 'deletion-scrub.db'}")
    database.Base.metadata.create_all(bind=test_engine)
    with test_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, name, tier, api_key, token_version, created_at) VALUES "
                "(1, 'audit@example.invalid', 'hash', 'Audit', 'user', 'audit-key', 1, "
                "CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO recruitment_thread_deletion_requests "
                "(id, user_id, thread_id, idempotency_key, status, targets, result, created_at) "
                "VALUES ('delete-1', 1, 'thread-1', 'key-1', 'requested', "
                '\'{"trace_keys":["private-trace"],"assessment_artifact_ids":["private-id"]}\', '
                "'{}', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO recruitment_thread_deletion_requests "
                "(id, user_id, thread_id, idempotency_key, status, targets, result, created_at) "
                "VALUES ('delete-2', 1, 'thread-2', 'key-2', 'cleanup_pending', "
                "'{\"checkpoint_tokens\":[\"opaque-checkpoint\"]}', '{}', CURRENT_TIMESTAMP)"
            )
        )

    monkeypatch.setattr(database, "engine", test_engine)
    database._apply_lightweight_migrations()
    database._apply_lightweight_migrations()

    with test_engine.connect() as connection:
        row = connection.execute(
            text("SELECT status, targets FROM recruitment_thread_deletion_requests WHERE id = 'delete-1'")
        ).one()
        pending_row = connection.execute(
            text("SELECT status, targets FROM recruitment_thread_deletion_requests WHERE id = 'delete-2'")
        ).one()
        versions = connection.execute(
            text("SELECT version FROM app_schema_migrations WHERE version = :version"),
            {"version": database._DELETION_TOMBSTONE_SCRUB_VERSION},
        ).all()

    assert row[0] == "completed"
    assert json.loads(row[1]) == {}
    assert pending_row[0] == "cleanup_pending"
    assert json.loads(pending_row[1]) == {"checkpoint_tokens": ["opaque-checkpoint"]}
    assert versions == [(database._DELETION_TOMBSTONE_SCRUB_VERSION,)]
    test_engine.dispose()


def test_legacy_job_alert_deliveries_are_deduplicated_before_unique_index(tmp_path, monkeypatch):
    import database
    import models  # noqa: F401 - register every table on Base.metadata

    test_engine = create_engine(f"sqlite:///{tmp_path / 'alert-dedupe.db'}")
    database.Base.metadata.create_all(bind=test_engine)
    with test_engine.begin() as connection:
        connection.execute(text("DROP INDEX ux_job_alert_deliveries_user_job"))
        connection.execute(
            text(
                "INSERT INTO job_alert_deliveries "
                "(id, user_id, scraped_job_id, resume_hash, match_score, action, sent_at) VALUES "
                "(1, 7, 11, '', 0, 'tracked', CURRENT_TIMESTAMP), "
                "(2, 7, 11, '', 0, 'dismissed', CURRENT_TIMESTAMP)"
            )
        )

    monkeypatch.setattr(database, "engine", test_engine)
    database._apply_lightweight_migrations()
    database._apply_lightweight_migrations()

    with test_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, action FROM job_alert_deliveries WHERE user_id = 7 AND scraped_job_id = 11")
        ).all()
    indexes = {index["name"]: index for index in inspect(test_engine).get_indexes("job_alert_deliveries")}

    assert rows == [(2, "dismissed")]
    assert indexes["ux_job_alert_deliveries_user_job"]["unique"] == 1
    test_engine.dispose()


def test_postgres_legacy_repair_is_idempotent(monkeypatch):
    postgres_url = os.environ.get("POSTGRES_MIGRATION_TEST_URL", "").strip()
    if not postgres_url:
        pytest.skip("POSTGRES_MIGRATION_TEST_URL is not configured")

    import database
    import models  # noqa: F401 - register every table on Base.metadata

    schema = f"migration_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(postgres_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    scoped_engine = create_engine(
        postgres_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    try:
        database.Base.metadata.create_all(bind=scoped_engine)
        with scoped_engine.begin() as connection:
            connection.execute(text("ALTER TABLE recruitment_runs DROP COLUMN lease_owner"))

        monkeypatch.setattr(database, "engine", scoped_engine)
        monkeypatch.setattr(database, "DATABASE_URL", postgres_url)
        database._apply_lightweight_migrations()
        database._apply_lightweight_migrations()

        columns = {column["name"] for column in inspect(scoped_engine).get_columns("recruitment_runs")}
        assert "lease_owner" in columns
    finally:
        scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin_engine.dispose()


def test_postgres_job_crawl_lease_is_single_flight_across_connections(monkeypatch):
    postgres_url = os.environ.get("POSTGRES_MIGRATION_TEST_URL", "").strip()
    if not postgres_url:
        pytest.skip("POSTGRES_MIGRATION_TEST_URL is not configured")

    import crawl_lease
    import database

    test_engine = create_engine(postgres_url)
    monkeypatch.setattr(database, "engine", test_engine)
    try:
        with crawl_lease.job_crawl_lease() as first_acquired:
            assert first_acquired
            with crawl_lease.job_crawl_lease() as second_acquired:
                assert not second_acquired

        with crawl_lease.job_crawl_lease() as reacquired:
            assert reacquired
    finally:
        test_engine.dispose()
