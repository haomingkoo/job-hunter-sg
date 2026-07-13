from __future__ import annotations

from contextlib import contextmanager


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
            return ["scraped_jobs", "users"]

        def get_columns(self, table):
            names = scraped_columns if table == "scraped_jobs" else {
                "id", "email", "tier", "terms_accepted_at", "privacy_accepted_at"
            }
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
    assert not any("SET email_verified_at" in statement for statement in statements)
    assert not any("SET tier = 'user'" in statement for statement in statements)
