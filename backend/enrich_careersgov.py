#!/usr/bin/env python3
"""Enrich CareersGov jobs with full descriptions from individual job pages."""

from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from database import SessionLocal, init_db
from models import ScrapedJob
from scraper import CareersGovScraper

# Regex to extract the external_path portion from a stored CareersGov URL.
# URL format: https://sggovterp.wd102.myworkdayjobs.com/en-US/PublicServiceCareers/job/...
_PATH_RE = re.compile(r"/en-US/PublicServiceCareers(/job/.+)$")

RATE_LIMIT_SECONDS = 1.0


def _extract_external_path(url: str) -> str:
    """Pull the /job/... segment from a CareersGov URL."""
    match = _PATH_RE.search(url)
    return match.group(1) if match else ""


def _html_to_text(html: str) -> str:
    """Convert HTML description to plain text, preserving line breaks."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def enrich() -> None:
    init_db()
    db = SessionLocal()
    scraper = CareersGovScraper()

    jobs = (
        db.query(ScrapedJob)
        .filter(
            ScrapedJob.source == "Careers@Gov",
            (ScrapedJob.description == "") | (ScrapedJob.description.is_(None)),
        )
        .all()
    )

    total = len(jobs)
    print(f"Found {total} CareersGov jobs to enrich")
    if total == 0:
        db.close()
        return

    enriched = 0
    failed = 0

    for i, job in enumerate(jobs, start=1):
        external_path = _extract_external_path(job.url)
        if not external_path:
            print(f"  [{i}/{total}] SKIP (no valid URL): {job.title}")
            failed += 1
            continue

        try:
            detail = scraper.get_job_detail(external_path)
            if not detail:
                print(f"  [{i}/{total}] SKIP (empty response): {job.title}")
                failed += 1
                time.sleep(RATE_LIMIT_SECONDS)
                continue

            # Extract description — Workday returns HTML in jobPostingInfo.jobDescription
            raw_desc = detail.get("jobDescription", "")
            description = _html_to_text(raw_desc)

            # Extract skills/tags if available
            skills: list[str] = []
            for tag_section in detail.get("skillTags", []):
                if isinstance(tag_section, str):
                    skills.append(tag_section)
                elif isinstance(tag_section, dict):
                    skills.append(tag_section.get("name", ""))
            # Workday sometimes puts skills in additionalLocations or tagLine — fallback
            if not skills:
                tag_line = detail.get("tagLine", "")
                if tag_line:
                    skills = [s.strip() for s in tag_line.split(",") if s.strip()]

            # Update the record
            if description:
                job.description = description
            if skills:
                job.skills = skills

            # Also backfill agency from the detail if available
            agency = detail.get("companyName", "") or detail.get("company", "")
            if agency and (not job.agency or job.agency == job.location):
                job.agency = agency

            db.commit()
            enriched += 1

            if i % 10 == 0 or i == total:
                print(f"  [{i}/{total}] Progress: {enriched} enriched, {failed} failed")

        except Exception as exc:
            db.rollback()
            print(f"  [{i}/{total}] ERROR on '{job.title}': {exc}")
            failed += 1

        time.sleep(RATE_LIMIT_SECONDS)

    db.close()
    print(f"\nDone. Enriched {enriched}/{total} jobs ({failed} failed/skipped).")


if __name__ == "__main__":
    enrich()
