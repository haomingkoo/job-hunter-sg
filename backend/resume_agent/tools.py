"""LangChain tools backed by existing Job Hunter services."""

from __future__ import annotations

from typing import Any

import config
from database import SessionLocal
from embedding_service import encode_text, find_similar_jobs
from langchain_core.tools import tool
from models import ScrapedJob


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
