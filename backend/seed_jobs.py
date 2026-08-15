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
import gc
import hashlib
import logging
import os
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import or_

# Setup path so imports work
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, SessionLocal
from job_precompute import apply_job_precomputes
from job_store import find_existing_scraped_job
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

MCF_MIN_HEALTHY_JOBS = 5000
CAREERSGOV_MIN_HEALTHY_JOBS = 500


def _posted_sort_iso(posted_date: str, scraped_at: str = "") -> str:
    from main import _parse_job_posted_at
    return _parse_job_posted_at(posted_date, scraped_at).isoformat()


def _crawl_semantic_key(job) -> str:
    """Collapse same-content source spam without merging distinct real roles."""
    description = re.sub(r"\s+", " ", (job.description or "")).strip().casefold()
    if not description:
        return ""
    fields = (
        job.source,
        job.company,
        job.agency,
        job.title,
        job.location,
        job.salary,
        job.posted_date,
        job.closing_date,
        job.employment_type,
        description,
    )
    normalized = [re.sub(r"\s+", " ", str(value or "")).strip().casefold() for value in fields]
    return hashlib.sha256("\x1f".join(normalized).encode()).hexdigest()


def _retire_stale_jobs(db, source: str, crawl_marker: str) -> int:
    """Hide visible source rows not refreshed by this completed crawl."""
    return (
        db.query(ScrapedJob)
        .filter(
            ScrapedJob.source == source,
            ScrapedJob.hidden == 0,
            or_(
                ScrapedJob.scraped_at < crawl_marker,
                ScrapedJob.scraped_at.is_(None),
            ),
        )
        .update({ScrapedJob.hidden: 1}, synchronize_session=False)
    )

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
    """Scrape jobs for each keyword, cache them in the database, return stats."""
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

            for job in results["jobs"]:
                raw = asdict(job)
                raw["dedup_key"] = job.dedup_key  # Property not included by asdict()
                clean = sanitize_job(raw)
                clean["search_keyword"] = keyword
                clean["posted_at_sort"] = _posted_sort_iso(clean.get("posted_date", ""), clean.get("scraped_at", ""))
                apply_job_precomputes(clean)

                existing = find_existing_scraped_job(db, clean)
                if existing:
                    for key, val in clean.items():
                        if key != "id":
                            setattr(existing, key, val)
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
            db.expunge_all()  # Release ORM objects to free memory

        except Exception as e:
            log.error(f"  Error searching '{keyword}': {e}")
            stats["errors"] += 1
            db.rollback()

        # Be polite between keywords
        time.sleep(1)

    stats["duration_seconds"] = round(time.time() - start, 1)

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

    stats = {
        "new": 0,
        "updated": 0,
        "errors": 0,
        "pages": 0,
        "retired": 0,
        "reactivated": 0,
        "duplicates_collapsed": 0,
    }
    start = time.time()

    from scraper import MyCareersFutureScraper
    mcf = MyCareersFutureScraper()

    log.info("=" * 60)
    log.info("FULL CRAWL: MyCareersFuture")
    log.info("=" * 60)

    mcf_crawl_marker = datetime.now(timezone.utc).isoformat()
    mcf_complete = True
    mcf_seen = 0
    mcf_seen_semantic_keys: set[str] = set()
    mcf_terminal_page_seen = False
    page = 0
    while True:
        try:
            jobs = mcf.search("", limit=100, page=page)  # Empty string = all jobs
            if not jobs:
                healthy_mcf_jobs = len(mcf_seen_semantic_keys)
                if healthy_mcf_jobs < MCF_MIN_HEALTHY_JOBS:
                    log.warning(
                        f"[MCF] Only {healthy_mcf_jobs} unique jobs with descriptions "
                        f"({mcf_seen} processed) — data may be stale or incomplete; "
                        "skipping stale-job retirement"
                    )
                    stats["errors"] += 1
                    mcf_complete = False
                elif not mcf_terminal_page_seen:
                    log.warning(
                        "[MCF] Crawl ended after a full page; the scraper may have hidden "
                        "an upstream error, so stale-job retirement is skipped"
                    )
                    stats["errors"] += 1
                    mcf_complete = False
                log.info(f"[MCF] Page {page}: no results, stopping")
                break

            if mcf_terminal_page_seen:
                log.warning("[MCF] Received jobs after a short page; treating crawl as incomplete")
                stats["errors"] += 1
                mcf_complete = False
            mcf_terminal_page_seen = len(jobs) < 100

            page_new = 0
            page_updated = 0
            page_reactivated = 0
            for job in jobs:
                semantic_key = _crawl_semantic_key(job)
                if semantic_key and semantic_key in mcf_seen_semantic_keys:
                    stats["duplicates_collapsed"] += 1
                    continue
                try:
                    is_new = False
                    was_hidden = False
                    with db.begin_nested():
                        raw = asdict(job)
                        raw["dedup_key"] = job.dedup_key
                        clean = sanitize_job(raw)
                        clean["search_keyword"] = "all"
                        clean["scraped_at"] = mcf_crawl_marker
                        clean["posted_at_sort"] = _posted_sort_iso(
                            clean.get("posted_date", ""), clean.get("scraped_at", "")
                        )
                        apply_job_precomputes(clean)

                        existing = find_existing_scraped_job(db, clean)
                        if existing:
                            was_hidden = bool(existing.hidden)
                            for key, val in clean.items():
                                if key != "id":
                                    setattr(existing, key, val)
                            existing.hidden = 0
                            _build_term_preview(existing, db)
                        else:
                            job_row = ScrapedJob(**clean)
                            db.add(job_row)
                            db.flush()
                            _build_term_preview(job_row, db)
                            is_new = True
                    if semantic_key:
                        mcf_seen_semantic_keys.add(semantic_key)
                    page_new += int(is_new)
                    page_updated += int(not is_new)
                    page_reactivated += int(was_hidden)
                    mcf_seen += 1
                except Exception as e:
                    log.error(f"[MCF] Page {page} job failed: {e}")
                    stats["errors"] += 1
                    mcf_complete = False

            db.commit()
            db.expunge_all()
            stats["new"] += page_new
            stats["updated"] += page_updated
            stats["reactivated"] += page_reactivated
            stats["pages"] += 1
            log.info(f"[MCF] Page {page}: {len(jobs)} jobs (new: {stats['new']}, updated: {stats['updated']})")

            page += 1
            time.sleep(0.3)

            # Periodic GC to reclaim memory from expelled ORM objects
            if page % 50 == 0:
                gc.collect()
                log.info(f"[MCF] GC at page {page}")

            if page >= 1000:
                log.info("[MCF] Hit 1000 page limit, stopping")
                mcf_complete = False
                break

        except Exception as e:
            log.error(f"[MCF] Page {page} failed: {e}")
            stats["errors"] += 1
            mcf_complete = False
            db.rollback()
            page += 1
            time.sleep(1)

    if mcf_complete:
        try:
            retired = _retire_stale_jobs(db, "MyCareersFuture", mcf_crawl_marker)
            db.commit()
            stats["retired"] += retired
            log.info(f"[MCF] Retired {retired} stale jobs")
        except Exception as e:
            log.error(f"[MCF] Stale-job retirement failed: {e}")
            stats["errors"] += 1
            db.rollback()
    else:
        log.warning("[MCF] Crawl was incomplete; stale-job retirement skipped")

    from scraper import CareersGovScraper
    cgov = CareersGovScraper()

    log.info("")
    log.info("=" * 60)
    log.info("FULL CRAWL: Careers@Gov (via OpenGovSG)")
    log.info("=" * 60)

    try:
        cgov_jobs = cgov.fetch_all()
        cgov_crawl_marker = datetime.now(timezone.utc).isoformat()

        # Health check unique postings so repeated source spam cannot retire the corpus.
        cgov_unique_keys = {
            semantic_key
            for job in cgov_jobs
            if (semantic_key := _crawl_semantic_key(job))
        }
        cgov_complete = len(cgov_unique_keys) >= CAREERSGOV_MIN_HEALTHY_JOBS
        if not cgov_complete:
            log.warning(
                f"[CareersGov] Only {len(cgov_unique_keys)} unique jobs "
                f"({len(cgov_jobs)} raw) — data may be stale or incomplete, skipping"
            )
            stats["errors"] += 1
            cgov_jobs = []
        else:
            log.info(f"[CareersGov] Health check passed: {len(cgov_jobs)} jobs")

        # Upsert approach (can't DELETE all — resume_versions has FK refs)
        seen_keys: set[str] = set()
        seen_semantic_keys: set[str] = set()
        cgov_new = 0
        cgov_updated = 0
        cgov_reactivated = 0
        cgov_retired = 0
        for job in cgov_jobs:
            semantic_key = _crawl_semantic_key(job)
            if semantic_key and semantic_key in seen_semantic_keys:
                stats["duplicates_collapsed"] += 1
                continue
            try:
                is_new = False
                was_hidden = False
                with db.begin_nested():
                    raw = asdict(job)
                    raw["dedup_key"] = job.dedup_key
                    if raw["dedup_key"] in seen_keys:
                        continue  # skip duplicate source postings in same batch
                    seen_keys.add(raw["dedup_key"])
                    clean = sanitize_job(raw)
                    clean["search_keyword"] = "all"
                    clean["scraped_at"] = cgov_crawl_marker
                    clean["posted_at_sort"] = _posted_sort_iso(
                        clean.get("posted_date", ""), clean.get("scraped_at", "")
                    )
                    apply_job_precomputes(clean)

                    if preparse_job_description and clean.get("description"):
                        clean["parsed_jd"] = preparse_job_description(
                            clean["description"], job_title=clean.get("title", "")
                        )

                    existing = find_existing_scraped_job(db, clean)
                    if existing:
                        was_hidden = bool(existing.hidden)
                        for key, val in clean.items():
                            if key != "id":
                                setattr(existing, key, val)
                        existing.hidden = 0
                        _build_term_preview(existing, db)
                    else:
                        job_row = ScrapedJob(**clean)
                        db.add(job_row)
                        _build_term_preview(job_row, db)
                        is_new = True
                if semantic_key:
                    seen_semantic_keys.add(semantic_key)
                cgov_new += int(is_new)
                cgov_updated += int(not is_new)
                cgov_reactivated += int(was_hidden)
            except Exception as e:
                log.error(f"[CareersGov] Job failed: {e}")
                stats["errors"] += 1
                cgov_complete = False

        if cgov_complete:
            cgov_retired = _retire_stale_jobs(db, "Careers@Gov", cgov_crawl_marker)
            log.info(f"[CareersGov] Retired {cgov_retired} stale jobs")

        db.commit()
        db.expunge_all()
        stats["new"] += cgov_new
        stats["updated"] += cgov_updated
        stats["reactivated"] += cgov_reactivated
        stats["retired"] += cgov_retired
        stats["pages"] += int(cgov_complete)
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
    log.info(f"  Jobs retired:     {stats['retired']}")
    log.info(f"  Jobs reactivated: {stats['reactivated']}")
    log.info(f"  Duplicates hidden: {stats['duplicates_collapsed']}")
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
