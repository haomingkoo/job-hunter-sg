"""Small MCP-facing wrappers around existing Job Hunter SG resume tools."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from sqlalchemy import func

import config
from ats_terms import build_job_ats_terms, match_resume_against_job_terms
from database import SessionLocal
from embedding_service import encode_text, find_similar_jobs
from job_visibility import apply_public_job_visibility
from models import ScrapedJob
from resume_scorer import ResumeScorer
from resume_structurer import get_all_bullets, structure_resume
from sanitizer import sanitize_resume_text
from skill_extractor import extract_skill_phrases
from skillsfuture_courses import recommend_courses_for_skills
from skills_taxonomy import TIER1_SKILLS
from validation_gates import _extract_numbers, validate_and_fix


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _limit(value: int, default: int = 20, maximum: int = 50) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = default
    return max(1, min(requested, maximum))


def _get_public_job(db, job_id: int, include_old: bool = False) -> ScrapedJob | None:
    return apply_public_job_visibility(
        db.query(ScrapedJob).filter(ScrapedJob.id == job_id),
        include_old=include_old,
    ).first()


def parse_resume(resume_text: str) -> str:
    """Parse resume text into sections, stats, and stable bullet IDs."""
    structured = structure_resume(resume_text or "")
    return _json(
        {
            "contact": structured.get("contact", {}),
            "stats": structured.get("stats", {}),
            "bullets": get_all_bullets(structured),
            "sections": structured.get("sections", []),
        }
    )


def score_resume(
    resume_text: str,
    job_description: str = "",
    job_id: int | None = None,
) -> str:
    """Score a resume with optional job-specific ATS blending."""
    parsed_jd = None
    if job_id:
        db = SessionLocal()
        try:
            job = db.get(ScrapedJob, job_id)
            if job:
                parsed_jd = job.parsed_jd if isinstance(job.parsed_jd, dict) else None
                if not job_description:
                    job_description = job.description or ""
        finally:
            db.close()
    result = ResumeScorer().analyze(
        resume_text=resume_text or "",
        job_description=job_description or "",
        parsed_jd=parsed_jd,
    )
    return _json(result)


def extract_skills(text: str) -> str:
    """Extract ATS-style skill phrases from text."""
    return _json({"skills": extract_skill_phrases(text or "")})


def _candidate_signals(text: str) -> dict[str, str]:
    signals = {skill.lower(): skill for skill in extract_skill_phrases(text or "")}
    lowered = (text or "").lower()
    for skill in TIER1_SKILLS:
        if re.search(rf"\b{re.escape(skill)}\b", lowered):
            signals.setdefault(skill, skill.upper() if len(skill) <= 3 else skill.title())
    return signals


def compare_candidate_profile(resume_text: str, profile_context: str) -> str:
    """Compare resume text with optional LinkedIn/profile text for consistency gaps."""
    resume_skills = _candidate_signals(resume_text or "")
    profile_skills = _candidate_signals(profile_context or "")
    resume_lower = (resume_text or "").lower()
    profile_lower = (profile_context or "").lower()
    missing_from_resume = [
        display
        for key, display in profile_skills.items()
        if key not in resume_skills and key not in resume_lower
    ][:20]
    missing_from_profile = [
        display
        for key, display in resume_skills.items()
        if key not in profile_skills and key not in profile_lower
    ][:20]
    return _json(
        {
            "resume_skills": list(resume_skills.values()),
            "profile_skills": list(profile_skills.values()),
            "profile_only_skills": missing_from_resume,
            "resume_only_skills": missing_from_profile,
            "guidance": (
                "Use these as consistency gaps or user questions. Do not add "
                "profile-only claims to the resume without user confirmation."
            ),
        }
    )


def get_job(job_id: int, include_old: bool = False) -> str:
    """Fetch one job from the internal jobs DB."""
    db = SessionLocal()
    try:
        job = _get_public_job(db, job_id, include_old=include_old)
        if not job:
            return _json({"error": "job_not_found", "job_id": job_id})
        return _json(_job_payload(job))
    finally:
        db.close()


def search_jobs(query: str, limit: int = config.AGENT_SEARCH_JOBS_LIMIT) -> str:
    """Search internal jobs DB semantically."""
    cleaned_query = re.sub(r"\s+", " ", query or "").strip()
    if not cleaned_query:
        return _json({"error": "query_required"})
    if len(cleaned_query) > 200:
        return _json({"error": "query_too_long", "max_characters": 200})
    capped = max(1, min(int(limit or 1), config.AGENT_SEARCH_JOBS_LIMIT))
    db = SessionLocal()
    try:
        matches = find_similar_jobs(encode_text(cleaned_query), db, top_k=max(capped * 10, capped))
        jobs = []
        for job_id, similarity in matches:
            job = _get_public_job(db, job_id)
            if job:
                jobs.append({**_job_payload(job), "similarity": round(similarity, 4)})
            if len(jobs) >= capped:
                break
        return _json({"jobs": jobs})
    finally:
        db.close()


def latest_jobs(limit: int = 10, source: str | None = None) -> str:
    """Return the latest public jobs from the internal jobs DB."""
    db = SessionLocal()
    try:
        query = apply_public_job_visibility(db.query(ScrapedJob))
        if source:
            query = query.filter(ScrapedJob.source == source)
        jobs = query.order_by(
            ScrapedJob.posted_at_sort.desc(),
            ScrapedJob.scraped_at.desc(),
            ScrapedJob.id.desc(),
        ).limit(_limit(limit, default=10, maximum=25)).all()
        return _json({"jobs": [_latest_job_payload(job) for job in jobs]})
    finally:
        db.close()


def latest_careersgov_jobs(limit: int = 10) -> str:
    """Return the latest public Careers@Gov jobs."""
    return latest_jobs(limit=limit, source="Careers@Gov")


def latest_mycareersfuture_jobs(limit: int = 10) -> str:
    """Return the latest public MyCareersFuture jobs."""
    return latest_jobs(limit=limit, source="MyCareersFuture")


def source_stats() -> str:
    """Return public job counts and freshness by source."""
    db = SessionLocal()
    try:
        visible = apply_public_job_visibility(db.query(ScrapedJob))
        total = visible.count()
        rows = (
            apply_public_job_visibility(
                db.query(
                    ScrapedJob.source,
                    func.count(ScrapedJob.id),
                    func.max(ScrapedJob.scraped_at),
                    func.max(ScrapedJob.posted_at_sort),
                )
            )
            .filter(ScrapedJob.source != "")
            .group_by(ScrapedJob.source)
            .order_by(func.count(ScrapedJob.id).desc())
            .all()
        )
        return _json(
            {
                "visible_jobs": total,
                "source_count": len(rows),
                "sources": [
                    {
                        "source": source,
                        "count": count,
                        "latest_scraped_at": latest_scraped_at or "",
                        "latest_posted_at": latest_posted_at or "",
                    }
                    for source, count, latest_scraped_at, latest_posted_at in rows
                    if source
                ],
            }
        )
    finally:
        db.close()


def recommend_skillsfuture_courses(skills: list[str], per_skill: int = 3) -> str:
    """Recommend official MySkillsFuture courses for skill gaps."""
    bounded_skills = [str(skill).strip()[:100] for skill in (skills or []) if str(skill).strip()][:10]
    return _json(
        recommend_courses_for_skills(
            bounded_skills,
            per_skill=_limit(per_skill, default=3, maximum=5),
        )
    )


def match_resume_to_jobs(resume_text: str, limit: int = 10) -> str:
    """Rank public jobs against pasted resume text without storing it."""
    clean_resume = sanitize_resume_text(resume_text or "")[:15000]
    if not clean_resume:
        return _json({"error": "resume_required", "jobs": []})

    capped = _limit(limit, default=10, maximum=20)
    candidate_limit = min(50, max(20, capped * 4))
    db = SessionLocal()
    try:
        matches = find_similar_jobs(encode_text(clean_resume), db, top_k=candidate_limit)
        if not matches:
            fallback_jobs = (
                apply_public_job_visibility(db.query(ScrapedJob))
                .filter(ScrapedJob.job_terms_preview.isnot(None))
                .order_by(ScrapedJob.posted_at_sort.desc(), ScrapedJob.id.desc())
                .limit(candidate_limit)
                .all()
            )
            matches = [(job.id, 0.0) for job in fallback_jobs]
        recommendations = []
        for job_id, similarity in matches:
            job = _get_public_job(db, job_id)
            if not job:
                continue
            job_terms, terms_source = _job_terms_for_match(job, db)
            result = match_resume_against_job_terms(
                resume_text=clean_resume,
                job_terms=job_terms,
                jd_text=job.description or "",
            )
            ats_percent = int(result.get("match_percent") or 0)
            fit_score = round(min(99, (float(similarity or 0) * 35) + (ats_percent * 0.65)))
            recommendations.append(
                {
                    "job": _latest_job_payload(job),
                    "fit_score": fit_score,
                    "ats_match_percent": ats_percent,
                    "semantic_similarity": round(float(similarity or 0), 4),
                    "matched_terms": _term_labels(result.get("matched", []), limit=8),
                    "missing_terms": _term_labels(result.get("missing", []), limit=8),
                    "total_terms": len(job_terms),
                    "terms_source": terms_source,
                }
            )
        recommendations.sort(key=lambda item: item["fit_score"], reverse=True)
        return _json(
            {
                "privacy": {
                    "stored": False,
                    "uses_private_applications": False,
                    "uses_stored_resume": False,
                },
                "candidate_jobs_checked": len(matches),
                "jobs": recommendations[:capped],
            }
        )
    finally:
        db.close()


def ats_precompute_status() -> str:
    """Report whether public jobs have ATS precompute fields ready."""
    db = SessionLocal()
    try:
        visible = apply_public_job_visibility(db.query(ScrapedJob))
        total = visible.count()
        parsed = visible.filter(ScrapedJob.parsed_jd.isnot(None)).count()
        previews = visible.filter(ScrapedJob.job_terms_preview.isnot(None)).count()
        embeddings = visible.filter(ScrapedJob.embedding_vector.isnot(None)).count()
        return _json(
            {
                "visible_jobs": total,
                "parsed_jd_ready": parsed,
                "job_terms_preview_ready": previews,
                "embedding_ready": embeddings,
                "parsed_jd_ready_percent": _percent(parsed, total),
                "job_terms_preview_ready_percent": _percent(previews, total),
                "embedding_ready_percent": _percent(embeddings, total),
                "backfill_command": "./backend/.venv/bin/python backend/backfill_enrichment.py --preview-only",
            }
        )
    finally:
        db.close()


def validate_bullet_edit(
    original: str,
    rewrite: str,
    job_description: str = "",
    required_keywords: list[str] | None = None,
) -> str:
    """Validate one proposed bullet rewrite and return gates plus final text."""
    original_numbers = _extract_numbers(original or "")
    rewrite_numbers = _extract_numbers(rewrite or "")
    fabricated_numbers = sorted(rewrite_numbers - original_numbers)
    final_text, gates = validate_and_fix(
        original=original or "",
        tailored=rewrite or "",
        jd_text=job_description or "",
        required_keywords=required_keywords,
    )
    gate_payloads = [asdict(gate) for gate in gates]
    if fabricated_numbers:
        final_text = original or ""
        gate_payloads.append(
            {
                "passed": False,
                "gate_name": "numeric_fabrication",
                "message": f"Rewrite introduced unsupported numeric facts: {', '.join(fabricated_numbers)}",
                "auto_fixed": False,
                "fixed_text": None,
            }
        )
    return _json(
        {
            "accepted": final_text == (rewrite or ""),
            "final_text": final_text,
            "gates": gate_payloads,
        }
    )


def propose_resume_diff(
    resume_text: str,
    bullet_id: str,
    rewrite: str,
    job_description: str = "",
    required_keywords: list[str] | None = None,
) -> str:
    """Validate a rewrite against a resume bullet ID."""
    bullets = {bullet["id"]: bullet for bullet in get_all_bullets(structure_resume(resume_text or ""))}
    bullet = bullets.get(bullet_id)
    if not bullet:
        return _json({"accepted": False, "error": "unknown_bullet_id", "bullet_id": bullet_id})
    original = bullet.get("text", "")
    payload = json.loads(validate_bullet_edit(original, rewrite, job_description, required_keywords))
    return _json(
        {
            **payload,
            "bullet_id": bullet_id,
            "section_key": bullet.get("section_key", ""),
            "entry_id": bullet.get("entry_id", ""),
            "original": original,
            "rewrite": rewrite,
        }
    )


def _job_payload(job: ScrapedJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "salary": job.salary,
        "source": job.source,
        "url": job.url,
        "description": job.description,
        "skills": job.skills or [],
        "parsed_jd": job.parsed_jd if isinstance(job.parsed_jd, dict) else {},
    }


def _normalize_skill_strings(raw_skills: Any) -> list[str]:
    if isinstance(raw_skills, list):
        return [str(skill).strip() for skill in raw_skills if str(skill).strip()]
    if isinstance(raw_skills, dict):
        return [str(skill).strip() for skill in raw_skills.values() if str(skill).strip()]
    if isinstance(raw_skills, str):
        return [part.strip() for part in re.split(r"[;,|/]", raw_skills) if part.strip()]
    return []


def _job_terms_for_match(job: ScrapedJob, db) -> tuple[list[dict[str, Any]], str]:
    parsed_jd = job.parsed_jd if isinstance(job.parsed_jd, dict) else None
    if parsed_jd or (job.description or "").strip():
        return (
            build_job_ats_terms(
                jd_text=job.description or "",
                job_skills=_normalize_skill_strings(job.skills),
                parsed_jd=parsed_jd,
                job_title=job.title or "",
                limit=24,
                db_session=db,
            ),
            "parsed_jd" if parsed_jd else "description",
        )
    preview = job.job_terms_preview if isinstance(job.job_terms_preview, list) else []
    return ([{"skill": str(skill)} for skill in preview if str(skill).strip()], "job_terms_preview")


def _term_labels(items: list[dict[str, Any]], limit: int = 8) -> list[str]:
    labels = []
    seen = set()
    for item in items or []:
        label = re.sub(r"\s+", " ", str(item.get("skill", "")).strip())
        lower = label.lower()
        if not label or lower in seen:
            continue
        seen.add(lower)
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _percent(value: int, total: int) -> int:
    return round((value / total) * 100) if total else 0


def _latest_job_payload(job: ScrapedJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "salary": job.salary,
        "source": job.source,
        "url": job.url,
        "posted_date": job.posted_date,
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "skills": job.skills or [],
        "jd_summary": job.jd_summary or "",
    }
