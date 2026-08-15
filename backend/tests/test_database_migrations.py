from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys


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
            ]

        def get_columns(self, table):
            if table == "scraped_jobs":
                names = scraped_columns
            elif table == "users":
                names = {"id", "email", "tier", "terms_accepted_at", "privacy_accepted_at"}
            elif table == "proposed_resume_edits":
                names = {"id", "rewrite"}
            else:
                names = {"id", "thread_id", "run_id"}
            return [{"name": name, "type": object()} for name in names]

        def get_indexes(self, table):
            names = scraped_indexes if table == "scraped_jobs" else set()
            return [{"name": name} for name in names]

    statements = []

    class Connection:
        def execute(self, statement):
            statements.append(str(statement))

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
    assert "ALTER TABLE recruitment_activity_events ADD COLUMN parent_id TEXT" in statements
    assert "ALTER TABLE recruitment_activity_events ADD COLUMN duration_ms FLOAT" in statements
    assert any("recruitment_activity_events ADD COLUMN attributes JSON" in item for item in statements)
    assert "ALTER TABLE proposed_resume_edits ADD COLUMN evidence_ids JSON" in statements
    assert (
        "ALTER TABLE candidate_profile_artifacts ADD COLUMN execution_metrics JSON NOT NULL DEFAULT '{}'"
        in statements
    )
    assert "ALTER TABLE candidate_profile_artifacts ADD COLUMN evaluation JSON" in statements
    assert (
        "ALTER TABLE target_assessment_artifacts ADD COLUMN execution_metrics JSON NOT NULL DEFAULT '{}'"
        in statements
    )
    assert (
        "ALTER TABLE recruitment_runs ADD COLUMN attempt_ledger JSON NOT NULL DEFAULT '{}'"
        in statements
    )
    assert "ALTER TABLE recruitment_runs ADD COLUMN lease_owner VARCHAR(64)" in statements
    assert "ALTER TABLE recruitment_runs ADD COLUMN lease_expires_at TIMESTAMP" in statements
    assert not any("SET email_verified_at" in statement for statement in statements)
    assert not any("SET tier = 'user'" in statement for statement in statements)
