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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("seed")

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

                existing = (
                    db.query(ScrapedJob)
                    .filter(ScrapedJob.dedup_key == clean["dedup_key"])
                    .first()
                )
                if existing:
                    for key, val in clean.items():
                        if key != "id":
                            setattr(existing, key, val)
                    stats["updated_jobs"] += 1
                else:
                    db.add(ScrapedJob(**clean))
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

    # ── CareersGov: paginate through all jobs ───────────────────────
    from scraper import CareersGovScraper
    cgov = CareersGovScraper()

    log.info("")
    log.info("=" * 60)
    log.info("FULL CRAWL: Careers@Gov")
    log.info("=" * 60)

    offset = 0
    while True:
        try:
            jobs = cgov.search("", limit=20, offset=offset)
            if not jobs:
                log.info(f"[CareersGov] Offset {offset}: no results, stopping")
                break

            for job in jobs:
                raw = asdict(job)
                raw["dedup_key"] = job.dedup_key
                clean = sanitize_job(raw)
                clean["search_keyword"] = "all"

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
                    stats["updated"] += 1

            db.commit()
            stats["pages"] += 1
            log.info(f"[CareersGov] Offset {offset}: {len(jobs)} jobs (new: {stats['new']}, updated: {stats['updated']})")

            offset += 20
            time.sleep(0.3)

            if offset >= 10000:
                log.info("[CareersGov] Hit 10,000 offset limit, stopping")
                break

        except Exception as e:
            log.error(f"[CareersGov] Offset {offset} failed: {e}")
            stats["errors"] += 1
            db.rollback()
            offset += 20
            time.sleep(2)

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
