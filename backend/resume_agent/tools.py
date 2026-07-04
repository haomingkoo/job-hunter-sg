"""LangChain tools backed by existing Job Hunter services."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import agent_tool_contract as contract
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


@tool
def search_jobs(query: str, n: int | None = None, detail: bool = False) -> dict:
    """Search matching jobs. Use detail=True only when full descriptions are needed."""
    clean_query = (query or "").strip()
    if not clean_query:
        return contract.tool_error(
            contract.SEARCH_JOBS_TOOL,
            "empty_query",
            "search_jobs requires a non-empty query.",
        )

    limit = contract.limit_jobs(n)
    db = None
    try:
        db = SessionLocal()
        query_vector = encode_text(clean_query)
        similar = find_similar_jobs(query_vector, db, top_k=limit)
        if not similar:
            return contract.search_jobs_result(clean_query, limit, [], detail=detail)

        scores = {job_id: score for job_id, score in similar[:limit]}
        jobs = (
            db.query(ScrapedJob)
            .filter(ScrapedJob.id.in_(scores.keys()))
            .all()
        )
        by_id = {job.id: job for job in jobs}
        results = [
            contract.job_payload(by_id[job_id], scores[job_id], detail=detail)
            for job_id, _score in similar[:limit]
            if job_id in by_id
        ]
        return contract.search_jobs_result(clean_query, limit, results, detail=detail)
    except Exception as exc:
        return contract.tool_error(
            contract.SEARCH_JOBS_TOOL,
            "search_failed",
            str(exc) or "Job search failed.",
            query=clean_query,
        )
    finally:
        if db:
            db.close()


@tool
def get_job(job_id: int) -> dict:
    """Return parsed job context for one internal job id."""
    db = None
    try:
        db = SessionLocal()
        job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
        if not job:
            return contract.tool_error(
                contract.GET_JOB_TOOL,
                "job_not_found",
                "No job exists for this id.",
                job_id=job_id,
            )
        return contract.get_job_result(contract.job_payload(job, detail=True))
    except Exception as exc:
        return contract.tool_error(
            contract.GET_JOB_TOOL,
            "get_job_failed",
            str(exc) or "Job lookup failed.",
            job_id=job_id,
        )
    finally:
        if db:
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
