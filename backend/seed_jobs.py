#!/usr/bin/env python3
"""
Job seeding script — pre-populates the database with jobs from all sources.

Run manually:    python seed_jobs.py
Run with args:   python seed_jobs.py --keywords "data engineer,PM,devops" --limit 30
Schedule daily:  Railway cron or system crontab

This scrapes all working API sources for popular SG job keywords
and caches the results in the database.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime

# Setup path so imports work
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, SessionLocal
from models import ScrapedJob
from sanitizer import sanitize_job
from scraper import JobAggregator

try:
    from jd_preparser import preparse_job_description
except ImportError:
    preparse_job_description = None

try:
    from ats_terms import build_job_ats_terms
except ImportError:
    build_job_ats_terms = None


def _build_term_preview(job_row: ScrapedJob, db) -> None:
    """Compute and cache job_terms_preview at scrape time."""
    if not build_job_ats_terms or not (job_row.description or "").strip():
        return
    if job_row.job_terms_preview:
        return
    import re
    parsed_jd = job_row.parsed_jd if isinstance(job_row.parsed_jd, dict) else None
    db_skills = [str(s).strip() for s in (job_row.skills or []) if str(s).strip()] if isinstance(job_row.skills, list) else []
    terms = build_job_ats_terms(
        jd_text=job_row.description or "",
        job_skills=db_skills,
        parsed_jd=parsed_jd,
        job_title=job_row.title or "",
        limit=24,
        db_session=db,
    )
    labels: list[str] = []
    seen: set[str] = set()
    for term in terms:
        label = re.sub(r"\s+", " ", str(term.get("skill", "")).strip())
        lower = label.lower()
        if not label or lower in seen:
            continue
        seen.add(lower)
        labels.append(label)
        if len(labels) >= 8:
            break
    job_row.job_terms_preview = labels

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("seed")


def _posted_sort_iso(posted_date: str, scraped_at: str = "") -> str:
    from main import _parse_job_posted_at
    return _parse_job_posted_at(posted_date, scraped_at).isoformat()

# Popular SG job search keywords to pre-cache
DEFAULT_KEYWORDS = [
    "software engineer",
    "data engineer",
    "data analyst",
    "data scientist",
    "machine learning",
    "product manager",
    "project manager",
    "devops engineer",
    "frontend developer",
    "backend developer",
    "full stack developer",
    "cloud engineer",
    "cybersecurity",
    "business analyst",
    "UI UX designer",
    "AI engineer",
    "solutions architect",
    "quality assurance",
    "scrum master",
    "technical program manager",
]


def seed_jobs(
    keywords: list[str],
    sources: list[str] | None = None,
    limit_per_source: int = 20,
) -> dict:
    """
    Scrape jobs for each keyword and cache in the database.
    Returns stats.
    """
    init_db()
    db = SessionLocal()
    aggregator = JobAggregator()

    stats = {
        "keywords_searched": 0,
        "total_raw": 0,
        "total_cached": 0,
        "new_jobs": 0,
        "updated_jobs": 0,
        "errors": 0,
        "duration_seconds": 0,
    }
    start = time.time()

    for keyword in keywords:
        log.info(f"Searching: '{keyword}'...")
        stats["keywords_searched"] += 1

        try:
            results = aggregator.search_all(
                keyword=keyword,
                sources=sources,
                limit_per_source=limit_per_source,
                enrich_skills=False,  # Skip SSG to save time during bulk seed
            )

            stats["total_raw"] += results["total_raw"]
            log.info(
                f"  Got {results['total_deduped']} jobs "
                f"(raw: {results['total_raw']}, dupes removed: {results['duplicates_removed']})"
            )

            # Cache each job in the database
            for job in results["jobs"]:
                raw = asdict(job)
                raw["dedup_key"] = job.dedup_key  # Property not included by asdict()
                clean = sanitize_job(raw)
                clean["search_keyword"] = keyword
                clean["posted_at_sort"] = _posted_sort_iso(clean.get("posted_date", ""), clean.get("scraped_at", ""))

                existing = (
                    db.query(ScrapedJob)
                    .filter(ScrapedJob.dedup_key == clean["dedup_key"])
                    .first()
                )
                if existing:
                    for key, val in clean.items():
                        if key != "id":
                            setattr(existing, key, val)
                    # Pre-parse JD if not already done
                    if preparse_job_description and not existing.parsed_jd:
                        existing.parsed_jd = preparse_job_description(
                            existing.description or "",
                            skills=existing.skills if isinstance(existing.skills, list) else [],
                        )
                    _build_term_preview(existing, db)
                    stats["updated_jobs"] += 1
                else:
                    job_row = ScrapedJob(**clean)
                    # Pre-parse JD at insert time
                    if preparse_job_description:
                        job_row.parsed_jd = preparse_job_description(
                            clean.get("description", ""),
                            skills=clean.get("skills", []),
                        )
                    db.add(job_row)
                    db.flush()  # get ID assigned for term preview
                    _build_term_preview(job_row, db)
                    stats["new_jobs"] += 1

                stats["total_cached"] += 1

            db.commit()

        except Exception as e:
            log.error(f"  Error searching '{keyword}': {e}")
            stats["errors"] += 1
            db.rollback()

        # Be polite between keywords
        time.sleep(1)

    stats["duration_seconds"] = round(time.time() - start, 1)

    # Final count
    total_in_db = db.query(ScrapedJob).count()
    db.close()

    log.info("=" * 60)
    log.info("SEED COMPLETE")
    log.info(f"  Keywords searched:  {stats['keywords_searched']}")
    log.info(f"  Total raw results:  {stats['total_raw']}")
    log.info(f"  New jobs added:     {stats['new_jobs']}")
    log.info(f"  Jobs updated:       {stats['updated_jobs']}")
    log.info(f"  Errors:             {stats['errors']}")
    log.info(f"  Duration:           {stats['duration_seconds']}s")
    log.info(f"  Total jobs in DB:   {total_in_db}")
    log.info("=" * 60)

    return stats


def crawl_all_jobs() -> dict:
    """
    FULL CRAWL — paginate through ALL jobs from MCF and CareersGov.
    MCF: ~12,000 jobs (pages of 100)
    CareersGov: ~3,000 jobs (pages of 20)
    Takes ~15-20 minutes total.
    """
    init_db()
    db = SessionLocal()

    stats = {"new": 0, "updated": 0, "errors": 0, "pages": 0}
    start = time.time()

    # ── MCF: paginate through all jobs ──────────────────────────────
    from scraper import MyCareersFutureScraper
    mcf = MyCareersFutureScraper()

    log.info("=" * 60)
    log.info("FULL CRAWL: MyCareersFuture")
    log.info("=" * 60)

    page = 0
    while True:
        try:
            jobs = mcf.search("", limit=100, page=page)  # Empty string = all jobs
            if not jobs:
                log.info(f"[MCF] Page {page}: no results, stopping")
                break

            for job in jobs:
                raw = asdict(job)
                raw["dedup_key"] = job.dedup_key
                clean = sanitize_job(raw)
                clean["search_keyword"] = "all"
                clean["posted_at_sort"] = _posted_sort_iso(clean.get("posted_date", ""), clean.get("scraped_at", ""))

                try:
                    existing = db.query(ScrapedJob).filter(
                        ScrapedJob.dedup_key == clean["dedup_key"]
                    ).first()
                    if existing:
                        for key, val in clean.items():
                            if key != "id":
                                setattr(existing, key, val)
                        stats["updated"] += 1
                    else:
                        db.add(ScrapedJob(**clean))
                        db.flush()
                        stats["new"] += 1
                except Exception:
                    db.rollback()
                    stats["updated"] += 1  # Likely a dupe

            db.commit()
            stats["pages"] += 1
            log.info(f"[MCF] Page {page}: {len(jobs)} jobs (new: {stats['new']}, updated: {stats['updated']})")

            page += 1
            time.sleep(0.3)

            if page >= 1000:
                log.info("[MCF] Hit 1000 page limit, stopping")
                break

        except Exception as e:
            log.error(f"[MCF] Page {page} failed: {e}")
            stats["errors"] += 1
            db.rollback()
            page += 1
            time.sleep(1)

    # ── CareersGov: single JSON fetch via OpenGovSG ─────────────────
    from scraper import CareersGovScraper
    cgov = CareersGovScraper()

    log.info("")
    log.info("=" * 60)
    log.info("FULL CRAWL: Careers@Gov (via OpenGovSG)")
    log.info("=" * 60)

    try:
        cgov_jobs = cgov.fetch_all()

        # Health check: ensure data is fresh and reasonable
        if len(cgov_jobs) < 500:
            log.warning(f"[CareersGov] Only {len(cgov_jobs)} jobs — data may be stale or incomplete, skipping")
            cgov_jobs = []
        else:
            log.info(f"[CareersGov] Health check passed: {len(cgov_jobs)} jobs")

        # Clean slate: remove old CareersGov entries to avoid duplicates
        # (old Workday URLs won't match new OpenGovSG dedup_keys)
        old_count = db.query(ScrapedJob).filter(ScrapedJob.source == "Careers@Gov").count()
        if cgov_jobs and old_count > 0:
            db.query(ScrapedJob).filter(ScrapedJob.source == "Careers@Gov").delete()
            db.commit()
            log.info(f"[CareersGov] Cleared {old_count} old entries before fresh insert")

        for job in cgov_jobs:
            raw = asdict(job)
            raw["dedup_key"] = job.dedup_key
            clean = sanitize_job(raw)
            clean["search_keyword"] = "all"
            clean["posted_at_sort"] = _posted_sort_iso(clean.get("posted_date", ""), clean.get("scraped_at", ""))

            # Pre-parse JD at insert time
            if preparse_job_description and clean.get("description"):
                clean["parsed_jd"] = preparse_job_description(
                    clean["description"], clean.get("title", "")
                )

            try:
                existing = db.query(ScrapedJob).filter(
                    ScrapedJob.dedup_key == clean["dedup_key"]
                ).first()
                if existing:
                    for key, val in clean.items():
                        if key != "id":
                            setattr(existing, key, val)
                    _build_term_preview(existing, db)
                    stats["updated"] += 1
                else:
                    job_row = ScrapedJob(**clean)
                    db.add(job_row)
                    db.flush()
                    _build_term_preview(job_row, db)
                    stats["new"] += 1
            except Exception:
                db.rollback()
                stats["updated"] += 1

        db.commit()
        stats["pages"] += 1
        log.info(f"[CareersGov] Loaded {len(cgov_jobs)} jobs (new: {stats['new']}, updated: {stats['updated']})")

    except Exception as e:
        log.error(f"[CareersGov] Fetch failed: {e}")
        stats["errors"] += 1
        db.rollback()

    duration = round(time.time() - start, 1)
    total_in_db = db.query(ScrapedJob).count()
    db.close()

    log.info("")
    log.info("=" * 60)
    log.info("FULL CRAWL COMPLETE")
    log.info(f"  Pages fetched:    {stats['pages']}")
    log.info(f"  New jobs added:   {stats['new']}")
    log.info(f"  Jobs updated:     {stats['updated']}")
    log.info(f"  Errors:           {stats['errors']}")
    log.info(f"  Duration:         {duration}s ({round(duration/60, 1)} min)")
    log.info(f"  Total jobs in DB: {total_in_db}")
    log.info("=" * 60)

    return stats


def main():
    parser = argparse.ArgumentParser(description="Pre-populate job database")
    parser.add_argument(
        "--keywords", "-k",
        help="Comma-separated keywords (default: 20 popular SG tech keywords)",
        default=None,
    )
    parser.add_argument(
        "--sources", "-s",
        help="Comma-separated sources: mcf,careersgov,adzuna,jooble (default: API sources only)",
        default="mcf,careersgov,adzuna,jooble",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int, default=20,
        help="Max jobs per source per keyword (default: 20)",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick test — 5 keywords, 5 jobs each (~15 sec)",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="FULL CRAWL — paginate ALL jobs from MCF + CareersGov (~15-20 min, ~15,000 jobs)",
    )

    args = parser.parse_args()

    # Full crawl mode — get EVERYTHING
    if args.full:
        log.info("Starting FULL CRAWL of all SG job portals...")
        crawl_all_jobs()
        return

    keywords = DEFAULT_KEYWORDS
    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",")]
    elif args.quick:
        keywords = keywords[:5]

    sources = [s.strip() for s in args.sources.split(",")] if args.sources else None

    log.info(f"Seeding {len(keywords)} keywords from {sources or 'all'} sources...")
    seed_jobs(keywords, sources=sources, limit_per_source=args.limit)


if __name__ == "__main__":
    main()
