#!/usr/bin/env python3
"""Backfill company SSIC metadata for existing scraped jobs.

Default mode only uses the local company SSIC cache. Pass --live to query the
official ACRA datasets on data.gov.sg; this is intentionally explicit because
the public API is rate-limited.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import func

sys.path.insert(0, os.path.dirname(__file__))

import company_taxonomy
from company_taxonomy import lookup_company_ssic
from database import SessionLocal, init_db
from job_precompute import apply_job_precomputes
from models import ScrapedJob


def backfill_company_ssic(limit: int, live: bool, dry_run: bool) -> dict:
    init_db()
    db = SessionLocal()
    stats = {"companies_checked": 0, "companies_matched": 0, "jobs_updated": 0}
    try:
        company_rows = (
            db.query(ScrapedJob.company, func.count(ScrapedJob.id).label("job_count"))
            .filter(ScrapedJob.hidden == 0, ScrapedJob.company != "")
            .group_by(ScrapedJob.company)
            .order_by(func.count(ScrapedJob.id).desc())
            .limit(limit)
            .all()
        )
        total_companies = len(company_rows)
        for company, count in company_rows:
            stats["companies_checked"] += 1
            match = lookup_company_ssic(company, allow_live=live)
            if match:
                stats["companies_matched"] += 1

            jobs = (
                db.query(ScrapedJob)
                .filter(ScrapedJob.company == company)
                .yield_per(200)
            )
            updated_for_company = 0
            for job in jobs:
                data = {
                    "title": job.title or "",
                    "company": job.company or "",
                    "salary": job.salary or "",
                    "skills": job.skills,
                    "description": job.description or "",
                    "sector": job.sector or "",
                    "company_ssic_code": job.company_ssic_code or "",
                    "company_ssic_description": job.company_ssic_description or "",
                    "company_ssic_source": job.company_ssic_source or "",
                }
                apply_job_precomputes(data)
                changed = (
                    data.get("sector", "") != (job.sector or "")
                    or data.get("company_ssic_code", "") != (job.company_ssic_code or "")
                    or data.get("company_ssic_description", "") != (job.company_ssic_description or "")
                    or data.get("company_ssic_source", "") != (job.company_ssic_source or "")
                )
                if not changed:
                    continue
                updated_for_company += 1
                if dry_run:
                    continue
                job.sector = data.get("sector", "")
                job.company_ssic_code = data.get("company_ssic_code", "")
                job.company_ssic_description = data.get("company_ssic_description", "")
                job.company_ssic_source = data.get("company_ssic_source", "")

            stats["jobs_updated"] += updated_for_company
            print(
                f"[{stats['companies_checked']}/{total_companies}] "
                f"{company} ({count} jobs): "
                f"{'matched' if match else 'no official match'}, "
                f"updated={updated_for_company}",
                flush=True,
            )
            if not dry_run:
                db.commit()
            else:
                db.rollback()
        return stats
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200, help="Top companies to check by job count")
    parser.add_argument("--live", action="store_true", help="Query official ACRA data.gov.sg datasets")
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Seconds to wait between live ACRA requests. Useful when data.gov.sg returns 429.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.delay is not None:
        company_taxonomy.LIVE_LOOKUP_MIN_INTERVAL_SECONDS = max(0, args.delay)
    print(backfill_company_ssic(limit=args.limit, live=args.live, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
