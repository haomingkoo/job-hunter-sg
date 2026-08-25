"""Export a frozen, public-only job corpus for ranking evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from database import SessionLocal
from job_visibility import apply_public_job_visibility
from models import ScrapedJob
from sqlalchemy.orm import load_only


def export(output: Path, exported_at: datetime | None = None) -> dict:
    """Write sorted public rows once and return a content-only receipt."""
    snapshot_time = exported_at or datetime.now(timezone.utc)
    digest = hashlib.sha256()
    count = 0
    seen_keys: set[str] = set()
    with SessionLocal() as db, output.open("x", encoding="utf-8") as destination:
        rows = apply_public_job_visibility(
            db.query(ScrapedJob).options(load_only(
                ScrapedJob.id,
                ScrapedJob.title,
                ScrapedJob.company,
                ScrapedJob.location,
                ScrapedJob.description,
                ScrapedJob.skills,
                ScrapedJob.seniority,
                ScrapedJob.salary,
                ScrapedJob.company_ssic_description,
                ScrapedJob.source,
                ScrapedJob.source_posting_id,
                ScrapedJob.posted_date,
                ScrapedJob.closing_date,
                ScrapedJob.scraped_at,
                ScrapedJob.posted_at_sort,
                ScrapedJob.hidden,
                ScrapedJob.content_hash,
            )),
            now=snapshot_time,
        ).order_by(ScrapedJob.id.asc()).yield_per(500)
        for job in rows:
            source_id = (job.source_posting_id or "").strip() or f"row-{job.id}"
            key = f"{(job.source or 'unknown').strip()}:{source_id}"
            if key in seen_keys:
                key = f"{key}:row-{job.id}"
            seen_keys.add(key)
            record = {
                "key": key,
                "title": job.title or "",
                "company": job.company or "",
                "location": job.location or "",
                "description": job.description or "",
                "skills": job.skills if isinstance(job.skills, (list, dict, str)) else [],
                "seniority": job.seniority or "",
                "salary": job.salary or "",
                "company_ssic_description": job.company_ssic_description or "",
                "source": job.source or "",
                "source_posting_id": job.source_posting_id or "",
                "posted_date": job.posted_date or "",
                "closing_date": job.closing_date or "",
                "scraped_at": job.scraped_at or "",
                "content_hash": job.content_hash or "",
            }
            raw = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode()
            destination.write(raw.decode())
            digest.update(raw)
            count += 1
    return {
        "exported_at": snapshot_time.isoformat(),
        "job_count": count,
        "sha256": digest.hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.output.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
