"""LangChain tools backed by existing Job Hunter services."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import config
from database import SessionLocal
from embedding_service import encode_text, find_similar_jobs
from langchain_core.tools import tool
from models import ScrapedJob


_current_bullets: ContextVar[dict[str, str]] = ContextVar(
    "resume_agent_current_bullets",
    default={},
)


@contextmanager
def bullet_context(bullets: dict[str, str]):
    token = _current_bullets.set(dict(bullets))
    try:
        yield
    finally:
        _current_bullets.reset(token)


def _limit_jobs(n: int | None) -> int:
    if n is None:
        return config.AGENT_SEARCH_JOBS_LIMIT
    try:
        requested = int(n)
    except (TypeError, ValueError):
        return config.AGENT_SEARCH_JOBS_LIMIT
    if requested <= 0:
        return config.AGENT_SEARCH_JOBS_LIMIT
    return min(requested, config.AGENT_SEARCH_JOBS_LIMIT)


def _skills_list(skills: Any) -> list[str]:
    if isinstance(skills, list):
        return [str(skill) for skill in skills if skill]
    if isinstance(skills, dict):
        values: list[str] = []
        for value in skills.values():
            if isinstance(value, list):
                values.extend(str(skill) for skill in value if skill)
            elif value:
                values.append(str(value))
        return values
    if isinstance(skills, str) and skills.strip():
        return [skills.strip()]
    return []


def _job_result(job: ScrapedJob, score: float) -> dict:
    return {
        "data_classification": "untrusted_job_data",
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "source": job.source,
        "score": score,
        "jd_summary": job.jd_summary or "",
        "skills": _skills_list(job.skills),
    }


@tool
def search_jobs(query: str, n: int | None = None) -> list[dict]:
    """Search the internal jobs database semantically for matching roles."""
    clean_query = (query or "").strip()
    if not clean_query:
        return []

    limit = _limit_jobs(n)
    db = SessionLocal()
    try:
        query_vector = encode_text(clean_query)
        similar = find_similar_jobs(query_vector, db, top_k=limit)
        if not similar:
            return []

        scores = {job_id: score for job_id, score in similar[:limit]}
        jobs = (
            db.query(ScrapedJob)
            .filter(ScrapedJob.id.in_(scores.keys()))
            .all()
        )
        by_id = {job.id: job for job in jobs}
        return [
            _job_result(by_id[job_id], scores[job_id])
            for job_id, _score in similar[:limit]
            if job_id in by_id
        ]
    finally:
        db.close()


@tool
def get_job(job_id: int) -> dict:
    """Return parsed job context for one internal job id."""
    db = SessionLocal()
    try:
        job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
        if not job:
            return {"found": False, "id": job_id}
        return {
            "data_classification": "untrusted_job_data",
            "found": True,
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "description": job.description or "",
            "parsed_jd": job.parsed_jd or {},
            "jd_summary": job.jd_summary or "",
            "skills": _skills_list(job.skills),
        }
    finally:
        db.close()


@tool
def score_resume(resume_text: str) -> dict:
    """Score resume text with the existing resume scorer."""
    from resume_scorer import ResumeScorer

    return ResumeScorer().analyze(resume_text or "")


@tool
def extract_skills(text: str) -> list[str]:
    """Extract skill phrases from text with the existing skill extractor."""
    from skill_extractor import extract_skill_phrases

    return extract_skill_phrases(text or "")


def _gate_payload(gates: list[Any]) -> list[dict]:
    return [
        {
            "gate": gate.gate_name,
            "passed": gate.passed,
            "message": gate.message,
        }
        for gate in gates
    ]


@tool
def propose_edit(bullet_id: str, rewrite: str) -> dict:
    """Validate a proposed rewrite for one resume bullet id."""
    from validation_gates import _extract_numbers, validate_and_fix

    bullets = _current_bullets.get()
    original = bullets.get(bullet_id)
    if not original:
        return {
            "accepted": False,
            "bullet_id": bullet_id,
            "rewrite": "",
            "reason": "Unknown bullet_id.",
            "gates": [],
        }

    clean_rewrite = (rewrite or "").strip()
    new_numbers = _extract_numbers(clean_rewrite) - _extract_numbers(original)
    if new_numbers:
        return {
            "accepted": False,
            "bullet_id": bullet_id,
            "rewrite": "",
            "reason": f"Unsupported numeric facts: {', '.join(sorted(new_numbers))}",
            "gates": [],
        }

    final_text, gates = validate_and_fix(original=original, tailored=clean_rewrite)
    failed = [gate for gate in gates if not gate.passed]
    if final_text == original and clean_rewrite != original:
        return {
            "accepted": False,
            "bullet_id": bullet_id,
            "rewrite": "",
            "reason": "; ".join(gate.message for gate in failed)
            or "Validation gates rejected rewrite.",
            "gates": _gate_payload(gates),
        }

    return {
        "accepted": True,
        "bullet_id": bullet_id,
        "rewrite": final_text,
        "reason": "",
        "gates": _gate_payload(gates),
    }
