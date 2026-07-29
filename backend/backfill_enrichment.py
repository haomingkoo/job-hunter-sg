"""
One-time backfill script: populate parsed_jd, job_terms_preview, and jd_summary
for all existing jobs.

Usage:
    # Phase 1 only (local computation, no LLM):
    python backfill_enrichment.py --preview-only

    # Full backfill (preview + summaries, needs SEA-LION keys):
    python backfill_enrichment.py

    # Limit to N summaries (useful for testing or batching):
    python backfill_enrichment.py --summary-limit 500

    # Resume from where you left off (skips already-done jobs):
    python backfill_enrichment.py  # always safe to re-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

# Ensure local imports work
sys.path.insert(0, ".")

from database import SessionLocal, init_db
from models import ScrapedJob
from jd_preparser import preparse_job_description as preparse_jd
from ats_terms import build_job_ats_terms
from jd_analyzer import analyze_job_description
import re


def _normalize_skill_strings(skills: list | dict | None) -> list[str]:
    if isinstance(skills, list):
        return [str(s).strip() for s in skills if str(s).strip()]
    return []


_SKILL_ACRONYMS = {"ai", "ml", "bi", "hr", "it", "ux", "ui", "qa", "pm", "sql",
                   "api", "aws", "gcp", "ci", "cd", "iot", "erp", "crm", "sop",
                   "kpi", "roi", "seo", "cet", "amr", "dna", "wsq", "rpa", "gis"}


def _title_case_skill(skill: str) -> str:
    if not skill:
        return skill
    if skill != skill.lower() and skill != skill.upper():
        return skill
    words = skill.split()
    result = []
    for w in words:
        if w.lower() in _SKILL_ACRONYMS:
            result.append(w.upper())
        elif w.lower() in {"and", "&", "of", "for", "in", "to", "the", "with", "on", "or"}:
            result.append(w.lower())
        else:
            result.append(w.capitalize())
    if result:
        result[0] = result[0].capitalize() if result[0] == result[0].lower() else result[0]
    return " ".join(result)


def _job_term_labels(terms: list[dict], limit: int = 8) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for term in terms or []:
        raw = re.sub(r"\s+", " ", str(term.get("skill", "")).strip())
        lower = raw.lower()
        if not raw or lower in seen:
            continue
        seen.add(lower)
        labels.append(_title_case_skill(raw))
        if len(labels) >= limit:
            break
    return labels


def _is_power_skill_noise(skill: str) -> bool:
    lower = skill.lower().strip()
    return lower in {
        "experience", "skills", "ability", "knowledge", "team",
        "communication", "management", "work", "support", "business",
        "development", "service", "good", "strong", "working",
        "years", "year", "relevant", "related", "preferred",
    }


def backfill_previews(
    batch_size: int = 200,
    progress_callback: Callable[..., None] | None = None,
    refresh_preview: bool = False,
    reparse: bool = False,
) -> int:
    """Backfill parsed_jd + job_terms_preview for all jobs. No LLM needed.
    If refresh_preview=True, recompute all previews.
    If reparse=True, re-run the JD parser on all jobs (after improving extraction).
    """
    db = SessionLocal()
    total_done = 0
    start_time = time.time()
    try:
        has_desc = (
            db.query(ScrapedJob)
            .filter(ScrapedJob.description != "", ScrapedJob.description.isnot(None))
        )
        if reparse or refresh_preview:
            total_need = has_desc.count()
        else:
            total_need = has_desc.filter(
                (ScrapedJob.parsed_jd.is_(None))
                | (ScrapedJob.job_terms_preview.is_(None))
            ).count()
        log.info(f"Need preview backfill: {total_need} (refresh={refresh_preview})")
        if progress_callback:
            progress_callback(
                preview_total=total_need,
                preview_done=0,
                rate_per_min=0.0,
                eta_minutes=0.0,
            )

        offset = 0
        while True:
            query = has_desc
            if not refresh_preview and not reparse:
                query = query.filter(
                    (ScrapedJob.parsed_jd.is_(None))
                    | (ScrapedJob.job_terms_preview.is_(None))
                )
            else:
                # Refresh/reparse walks a fixed snapshot of all described jobs, so
                # pagination must be deterministic to avoid skipping/duplicating rows.
                query = query.order_by(ScrapedJob.id.asc()).offset(offset)
            jobs = query.limit(batch_size).all()
            if not jobs:
                break
            offset += len(jobs)

            for job in jobs:
                if reparse or not job.parsed_jd:
                    db_skills = _normalize_skill_strings(job.skills)
                    job.parsed_jd = preparse_jd(
                        job.description or "",
                        skills=db_skills,
                        db_session=db,
                        job_title=job.title or "",
                    )

                if refresh_preview or not job.job_terms_preview:
                    db_skills = _normalize_skill_strings(job.skills)
                    parsed_jd = job.parsed_jd if isinstance(job.parsed_jd, dict) else None
                    terms = build_job_ats_terms(
                        jd_text=job.description or "",
                        job_skills=db_skills,
                        parsed_jd=parsed_jd,
                        job_title=job.title or "",
                        limit=24,
                        db_session=db,
                    )
                    labels = _job_term_labels(
                        [t for t in terms if not _is_power_skill_noise(t.get("skill", ""))],
                        limit=8,
                    )
                    job.job_terms_preview = labels

                parsed = job.parsed_jd if isinstance(job.parsed_jd, dict) else {}
                if "_analysis" not in parsed:
                    analysis = analyze_job_description(
                        title=job.title or "",
                        description=job.description or "",
                        parsed_jd=parsed,
                        salary=job.salary or "",
                        company=job.company or "",
                        agency=job.agency or "",
                    )
                    parsed["_analysis"] = analysis
                    job.parsed_jd = parsed

            db.commit()
            total_done += len(jobs)
            elapsed = time.time() - start_time
            rate_per_min = total_done / max(1, elapsed) * 60
            remaining = max(0, total_need - total_done)
            eta_min = remaining / max(0.1, rate_per_min) if remaining else 0.0
            log.info(
                f"Preview backfill: {total_done}/{total_need} "
                f"| {rate_per_min:.1f}/min | ETA {eta_min:.0f}min"
            )
            if progress_callback:
                progress_callback(
                    preview_done=total_done,
                    preview_total=total_need,
                    rate_per_min=round(rate_per_min, 1),
                    eta_minutes=round(eta_min, 1),
                )

    finally:
        db.close()

    elapsed = time.time() - start_time
    if progress_callback:
        progress_callback(
            preview_done=total_done,
            preview_total=total_need,
            rate_per_min=round(total_done / max(1, elapsed) * 60, 1) if total_done else 0.0,
            eta_minutes=0.0,
        )
    return total_done


def backfill_summaries(
    limit: int = 0,
    batch_size: int = 10,
    progress_callback: Callable[..., None] | None = None,
) -> int:
    """Backfill jd_summary for jobs that have parsed_jd but no summary."""
    from jd_summary import summarize_job_description
    from ai_service import _api_keys, get_ai_health

    if not _api_keys:
        log.error("No SEA-LION API keys found. Set sealion_api env var.")
        return 0

    db = SessionLocal()
    total_done = 0
    total_failed = 0
    start_time = time.time()
    try:
        query = (
            db.query(ScrapedJob)
            .filter(
                ScrapedJob.description != "",
                ScrapedJob.description.isnot(None),
                ScrapedJob.parsed_jd.isnot(None),
            )
            .filter(
                (ScrapedJob.jd_summary.is_(None))
                | (ScrapedJob.jd_summary == "")
            )
            .filter(
                ScrapedJob.jd_summary_status != "unavailable",
            )
            .order_by(ScrapedJob.id.desc())
        )

        total_need = query.count()
        if limit > 0:
            total_need = min(total_need, limit)
        log.info(f"Need summaries: {total_need} (limit={limit or 'none'})")
        if progress_callback:
            progress_callback(summary_total=total_need, summary_done=0, summary_failed=0)

        processed = 0
        while True:
            if limit > 0 and processed >= limit:
                break
            jobs = query.offset(0).limit(batch_size).all()
            if not jobs:
                break

            for job in jobs:
                if not get_ai_health()["is_healthy"]:
                    log.warning("AI service unhealthy, pausing 60s...")
                    time.sleep(60)
                    if not get_ai_health()["is_healthy"]:
                        log.error("AI service still unhealthy, stopping.")
                        return total_done

                try:
                    parsed = job.parsed_jd if isinstance(job.parsed_jd, dict) else {}
                    summary, model_used = summarize_job_description(
                        job_title=job.title or "",
                        description=job.description or "",
                        parsed_jd=parsed,
                    )

                    now_iso = datetime.now(timezone.utc).isoformat()
                    if summary:
                        job.jd_summary = summary
                        job.jd_summary_generated_at = now_iso
                        job.jd_summary_status = model_used
                        total_done += 1
                    else:
                        job.jd_summary_generated_at = now_iso
                        job.jd_summary_status = "unavailable"
                        total_failed += 1

                except Exception as exc:
                    log.warning(f"Summary failed for job {job.id}: {exc}")
                    job.jd_summary_status = "failed"
                    job.jd_summary_generated_at = datetime.now(timezone.utc).isoformat()
                    total_failed += 1

                processed += 1
                if limit > 0 and processed >= limit:
                    break

                if processed % 10 == 0:
                    db.commit()
                    elapsed = time.time() - start_time
                    rate_per_min = processed / max(1, elapsed) * 60
                    remaining = total_need - processed
                    eta_min = remaining / max(0.1, rate_per_min)
                    log.info(
                        f"Summaries: {processed}/{total_need} "
                        f"({total_done} ok, {total_failed} fail) "
                        f"| {rate_per_min:.1f}/min | ETA {eta_min:.0f}min"
                    )
                    if progress_callback:
                        progress_callback(
                            summary_done=total_done,
                            summary_failed=total_failed,
                            summary_total=total_need,
                            rate_per_min=round(rate_per_min, 1),
                            eta_minutes=round(eta_min, 1),
                        )

            db.commit()

    finally:
        db.close()

    elapsed = time.time() - start_time
    log.info(
        f"Summary backfill complete: {total_done} ok, {total_failed} failed "
        f"out of {processed} processed in {elapsed / 60:.1f}min"
    )
    if progress_callback:
        progress_callback(
            summary_done=total_done,
            summary_failed=total_failed,
            summary_total=total_need,
            rate_per_min=round(processed / max(1, elapsed) * 60, 1),
            eta_minutes=0.0,
        )
    return total_done


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill JD enrichment data")
    parser.add_argument("--preview-only", action="store_true", help="Only backfill parsed_jd + preview (no LLM)")
    parser.add_argument("--summary-only", action="store_true", help="Only backfill summaries (skip preview)")
    parser.add_argument("--summary-limit", type=int, default=0, help="Max summaries to generate (0=all)")
    parser.add_argument("--batch-size", type=int, default=200, help="Batch size for preview backfill")
    parser.add_argument("--refresh-preview", action="store_true", help="Recompute ALL previews (after fixing term extraction)")
    parser.add_argument("--reparse", action="store_true", help="Re-run JD parser on ALL jobs (after improving extraction logic)")
    args = parser.parse_args()

    init_db()

    if not args.summary_only:
        log.info("=== Phase 1: Backfill parsed_jd + job_terms_preview ===")
        start = time.time()
        count = backfill_previews(
            batch_size=args.batch_size,
            refresh_preview=args.refresh_preview,
            reparse=args.reparse,
        )
        elapsed = time.time() - start
        log.info(f"Phase 1 done: {count} jobs in {elapsed:.1f}s ({count / max(1, elapsed):.1f} jobs/s)")

    if not args.preview_only:
        log.info("=== Phase 2: Backfill jd_summary (SEA-LION) ===")
        start = time.time()
        count = backfill_summaries(limit=args.summary_limit)
        elapsed = time.time() - start
        log.info(f"Phase 2 done: {count} summaries in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
