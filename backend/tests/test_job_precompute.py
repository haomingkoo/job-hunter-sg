from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_precompute import apply_job_precomputes, parse_job_posted_at, posted_sort_iso


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-08-20T12:30:00Z", datetime(2026, 8, 20, 12, 30, tzinfo=timezone.utc)),
        ("20 Aug 2026", datetime(2026, 8, 20, tzinfo=timezone.utc)),
        ("August 20, 2026", datetime(2026, 8, 20, tzinfo=timezone.utc)),
        ("2026/08/20", datetime(2026, 8, 20, tzinfo=timezone.utc)),
    ],
)
def test_parse_job_posted_at_supports_source_formats(raw, expected):
    assert parse_job_posted_at(raw) == expected


def test_relative_posted_dates_preserve_freshness_order():
    today = parse_job_posted_at("Posted Today")
    yesterday = parse_job_posted_at("Posted Yesterday")
    four_days = parse_job_posted_at("Posted 4 Days Ago")
    thirty_days = parse_job_posted_at("Posted 30+ Days Ago")
    two_months = parse_job_posted_at("Posted 2 Months Ago")

    assert today > yesterday > four_days > thirty_days > two_months


def test_posted_date_uses_scrape_time_then_epoch_as_explicit_fallbacks():
    scraped = "2026-08-19T04:05:06Z"

    assert posted_sort_iso("unknown", scraped) == "2026-08-19T04:05:06+00:00"
    assert posted_sort_iso("unknown", "also invalid") == "1970-01-01T00:00:00+00:00"


def test_seed_date_normalization_does_not_import_the_api_composition_root():
    backend_dir = Path(__file__).resolve().parents[1]
    script = """
import sys
import seed_jobs
value = seed_jobs._posted_sort_iso('Posted 4 Days Ago')
assert value
assert 'main' not in sys.modules
print(value)
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_dir,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "T" in completed.stdout


def test_job_precomputes_persist_direct_employer_classification():
    direct = apply_job_precomputes({
        "title": "Quality Manager",
        "company": "Micron Semiconductor",
        "description": "Lead quality systems.",
        "skills": [],
        "salary": "",
    })
    agency = apply_job_precomputes({
        "title": "Quality Manager",
        "company": "Example Talent Search",
        "description": "EA Licence No: 12C3456.",
        "skills": [],
        "salary": "",
    })

    assert direct["direct_employer"] == 1
    assert agency["direct_employer"] == 0


def test_incremental_precompute_backfill_skips_retired_jobs():
    from database import SessionLocal
    from main import _precompute_batch
    from models import ScrapedJob

    now = datetime.now(timezone.utc).isoformat()
    db = SessionLocal()
    try:
        public = ScrapedJob(
            title="Quality Manager",
            company="Micron Semiconductor",
            description="Lead quality systems.",
            dedup_key="precompute-public-job",
            posted_at_sort=now,
            scraped_at=now,
            hidden=0,
            direct_employer=-1,
        )
        retired = ScrapedJob(
            title="Quality Manager",
            company="Retired Semiconductor",
            description="Lead quality systems.",
            dedup_key="precompute-retired-job",
            posted_at_sort=now,
            scraped_at=now,
            hidden=1,
            retirement_reason="source_retired",
            direct_employer=-1,
        )
        db.add_all((public, retired))
        db.commit()

        done, _ = _precompute_batch(
            db,
            (ScrapedJob.direct_employer < 0)
            & ScrapedJob.dedup_key.in_(
                ("precompute-public-job", "precompute-retired-job")
            ),
            50,
            public_only=True,
        )
        public = db.query(ScrapedJob).filter_by(dedup_key="precompute-public-job").one()
        retired = db.query(ScrapedJob).filter_by(dedup_key="precompute-retired-job").one()

        assert done == 1
        assert public.direct_employer == 1
        assert retired.direct_employer == -1
    finally:
        db.query(ScrapedJob).filter(
            ScrapedJob.dedup_key.in_(("precompute-public-job", "precompute-retired-job"))
        ).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_mutated_listing_refreshes_every_derived_search_field():
    from main import _refresh_job_precomputes
    from models import ScrapedJob

    job = ScrapedJob(
        title="Quality Manager",
        company="Example Talent Search",
        description="Lead QMS for our client.",
        skills=["ISO 9001"],
        salary="$8,000 - $10,000",
        dedup_key="derived-field-refresh",
        sector="stale",
        direct_employer=1,
        salary_floor=1,
        skills_flat="stale",
        promotional_score=99,
    )

    _refresh_job_precomputes(job)

    assert job.direct_employer == 0
    assert job.salary_floor == 8000
    assert job.skills_flat == "ISO 9001"
    assert job.sector != "stale"
    assert job.promotional_score != 99
    assert len(job.content_hash) == 64
