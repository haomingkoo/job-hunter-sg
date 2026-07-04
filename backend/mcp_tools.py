"""Small MCP-facing wrappers around existing Job Hunter SG resume tools."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

import agent_tool_contract as contract
from database import SessionLocal
from embedding_service import encode_text, find_similar_jobs
from models import ScrapedJob
from resume_scorer import ResumeScorer
from resume_structurer import get_all_bullets, structure_resume
from skill_extractor import extract_skill_phrases
from skills_taxonomy import TIER1_SKILLS
from validation_gates import _extract_numbers, validate_and_fix


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


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


def get_job(job_id: int) -> str:
    """Fetch one job from the internal jobs DB."""
    db = None
    try:
        db = SessionLocal()
        job = db.get(ScrapedJob, job_id)
        if not job:
            return _json(
                contract.tool_error(
                    contract.GET_JOB_TOOL,
                    "job_not_found",
                    "No job exists for this id.",
                    job_id=job_id,
                )
            )
        return _json(contract.get_job_result(contract.job_payload(job, detail=True)))
    except Exception as exc:
        return _json(
            contract.tool_error(
                contract.GET_JOB_TOOL,
                "get_job_failed",
                str(exc) or "Job lookup failed.",
                job_id=job_id,
            )
        )
    finally:
        if db:
            db.close()


def search_jobs(query: str, limit: int | None = None, detail: bool = False) -> str:
    """Search internal jobs DB semantically. Use detail=true for full job text."""
    clean_query = (query or "").strip()
    if not clean_query:
        return _json(
            contract.tool_error(
                contract.SEARCH_JOBS_TOOL,
                "empty_query",
                "search_jobs requires a non-empty query.",
            )
        )

    capped = contract.limit_jobs(limit)
    db = None
    try:
        db = SessionLocal()
        matches = find_similar_jobs(encode_text(clean_query), db, top_k=capped)
        jobs = []
        for job_id, similarity in matches:
            job = db.get(ScrapedJob, job_id)
            if job:
                jobs.append(contract.job_payload(job, similarity, detail=detail))
        return _json(contract.search_jobs_result(clean_query, capped, jobs, detail=detail))
    except Exception as exc:
        return _json(
            contract.tool_error(
                contract.SEARCH_JOBS_TOOL,
                "search_failed",
                str(exc) or "Job search failed.",
                query=clean_query,
            )
        )
    finally:
        if db:
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
