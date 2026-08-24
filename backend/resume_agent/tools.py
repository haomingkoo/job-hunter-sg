"""LangChain tools backed by existing Job Hunter services."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import re
from typing import Any

import agent_tool_contract as contract
import config
from database import SessionLocal
from embedding_service import encode_text, find_similar_jobs
from employer_filter import company_name_matches, direct_employer_condition
from job_visibility import apply_public_job_visibility, is_junior_posting
from langchain_core.tools import tool
from models import ScrapedJob


MAX_SCORE_SUGGESTIONS = 5
MAX_SCORE_KEYWORDS = 20


def _search_failure_type(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "rate" in name and "limit" in name:
        return "rate_limit"
    if any(term in name for term in ("auth", "permission", "unauthorized")):
        return "authentication"
    return "unavailable"

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
def search_jobs(
    query: str,
    n: int | None = None,
    detail: bool = False,
    exclude_junior: bool = False,
    company: str = "",
    direct_employers_only: bool = False,
) -> dict:
    """Search the current internal Singapore job corpus by role or responsibility.

    Use this to compare a resume with similar active postings, not to make broad
    market claims. `query` should describe the role or capability, `n` is the
    desired result count, and `detail=True` includes descriptions. Returns job
    IDs and source fields that may be cited; an empty result is valid.
    `exclude_junior` drops traineeships and entry-level postings, which
    similarity alone cannot tell apart from senior work in the same field.
    `company` constrains results to that named employer on whole normalized
    words. `direct_employers_only` excludes recruitment agencies.
    """
    clean_query = (query or "").strip()
    if not clean_query:
        return contract.search_jobs_error(
            clean_query,
            "empty_query",
            "search_jobs requires a non-empty query.",
            failure_type="validation",
        )

    limit = contract.limit_jobs(n)
    db = None
    try:
        db = SessionLocal()
        clean_company = (company or "").strip()
        eligible_job_ids = None
        if clean_company or direct_employers_only:
            eligible_query = apply_public_job_visibility(
                db.query(ScrapedJob.id, ScrapedJob.company)
            )
            if direct_employers_only:
                eligible_query = eligible_query.filter(
                    direct_employer_condition(
                        ScrapedJob.company,
                        ScrapedJob.company_ssic_description,
                        ScrapedJob.description,
                    )
                )
            if clean_company:
                first_word = next(iter(re.findall(r"[a-z0-9]+", clean_company.casefold())), "")
                eligible_query = eligible_query.filter(
                    ScrapedJob.company.ilike(f"%{first_word}%")
                )
            eligible_job_ids = {
                job_id
                for job_id, employer in eligible_query.all()
                if not clean_company or company_name_matches(employer, clean_company)
            }
        query_vector = encode_text(clean_query)
        similar = find_similar_jobs(
            query_vector,
            db,
            top_k=max(limit * config.AGENT_SEARCH_CANDIDATE_MULTIPLIER, limit),
            eligible_job_ids=eligible_job_ids,
        )
        if not similar:
            return contract.search_jobs_result(
                clean_query,
                limit,
                [],
                detail=detail,
                candidate_count=0,
                eligible_candidate_count=(
                    len(eligible_job_ids) if eligible_job_ids is not None else None
                ),
                visible_candidate_count=0,
            )

        scores = {job_id: score for job_id, score in similar}
        jobs = (
            apply_public_job_visibility(db.query(ScrapedJob))
            .filter(ScrapedJob.id.in_(scores.keys()))
            .all()
        )
        if exclude_junior:
            jobs = [
                job for job in jobs
                if not is_junior_posting(job.seniority, job.title, job.salary_floor)
            ]
        by_id = {job.id: job for job in jobs}
        results = [
            contract.job_payload(
                by_id[job_id],
                scores[job_id],
                detail=detail,
                include_parsed=False,
            )
            for job_id, _score in similar
            if job_id in by_id
        ]
        deduplicated = contract.deduplicate_job_payloads(results)
        return contract.search_jobs_result(
            clean_query,
            limit,
            deduplicated,
            detail=detail,
            candidate_count=len(similar),
            eligible_candidate_count=(
                len(eligible_job_ids) if eligible_job_ids is not None else None
            ),
            visible_candidate_count=len(results),
        )
    except Exception as exc:
        return contract.search_jobs_error(
            clean_query,
            "search_failed",
            "The internal job search source was unavailable.",
            failure_type=_search_failure_type(exc),
        )
    finally:
        if db:
            db.close()


@tool
def get_job(job_id: int) -> dict:
    """Fetch one current internal job by an ID returned from search_jobs.

    Use this only when a search result needs its full description or source URL.
    It cannot recover an expired/deleted posting; use the supplied target-job
    snapshot for that. A missing row returns `found=false` and `job=null`; only
    a failed lookup returns `ok=false` with retry information.
    """
    db = None
    try:
        db = SessionLocal()
        job = apply_public_job_visibility(
            db.query(ScrapedJob).filter(ScrapedJob.id == job_id)
        ).first()
        if not job:
            return contract.get_job_empty_result(job_id)
        return contract.get_job_result(
            contract.job_payload(job, detail=True, include_parsed=False)
        )
    except Exception as exc:
        return contract.tool_error(
            contract.GET_JOB_TOOL,
            "get_job_failed",
            str(exc) or "Job lookup failed.",
            failure_type=_search_failure_type(exc),
            job_id=job_id,
        )
    finally:
        if db:
            db.close()


@tool
def score_resume(resume_text: str) -> dict:
    """Run the deterministic resume baseline on the exact supplied resume text.

    Use this for structural, presentation, action/impact, and competency signals.
    This is not an LLM judgment and does not prove claims or role fit. Returns the
    existing rule-based score breakdown; do not present it as an ATS vendor score.
    """
    from resume_scorer import ResumeScorer

    result = ResumeScorer().analyze(resume_text or "")
    matched = result.get("keyword_match", {}).get("matched", [])
    missing = result.get("keyword_match", {}).get("missing", [])
    suggestions = result.get("top_suggestions", [])
    return {
        "overall_score": result.get("overall_score", 0),
        "dimensions": {
            name: {
                key: dimension.get(key)
                for key in ("score", "max", "status")
            }
            for name, dimension in result.get("dimensions", {}).items()
        },
        "keyword_match": {
            "score_percent": result.get("keyword_match", {}).get("score_percent", 0),
            "matched": matched[:MAX_SCORE_KEYWORDS],
            "matched_truncated": len(matched) > MAX_SCORE_KEYWORDS,
            "matched_original_length": len(matched),
            "matched_display_length": min(len(matched), MAX_SCORE_KEYWORDS),
            "missing": missing[:MAX_SCORE_KEYWORDS],
            "missing_truncated": len(missing) > MAX_SCORE_KEYWORDS,
            "missing_original_length": len(missing),
            "missing_display_length": min(len(missing), MAX_SCORE_KEYWORDS),
        },
        "top_suggestions": suggestions[:MAX_SCORE_SUGGESTIONS],
        "top_suggestions_truncated": len(suggestions) > MAX_SCORE_SUGGESTIONS,
        "top_suggestions_original_length": len(suggestions),
        "top_suggestions_display_length": min(len(suggestions), MAX_SCORE_SUGGESTIONS),
    }


@tool
def extract_skills(text: str) -> list[str]:
    """Extract normalized skill phrases from resume or job-description text.

    Use it to compare terminology already present in evidence. The returned list
    is lexical evidence, not proof that the candidate owns a missing skill.
    """
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
    """Validate one evidence-safe bullet rewrite without changing the resume.

    `bullet_id` must be a supplied canonical resume block ID. `rewrite` must keep
    the original facts and numbers. A valid proposal remains pending user review
    and is never applied or described as accepted by the user; rejection means
    the worker should recommend clarification instead.
    """
    from validation_gates import extract_numbers, validate_and_fix

    bullets = _current_bullets.get()
    original = bullets.get(bullet_id)
    if not original:
        return {
            "accepted": False,
            "application_status": "rejected",
            "bullet_id": bullet_id,
            "rewrite": "",
            "reason": "Unknown bullet_id.",
            "gates": [],
        }

    clean_rewrite = (rewrite or "").strip()
    new_numbers = extract_numbers(clean_rewrite) - extract_numbers(original)
    if new_numbers:
        return {
            "accepted": False,
            "application_status": "rejected",
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
            "application_status": "rejected",
            "bullet_id": bullet_id,
            "rewrite": "",
            "reason": "; ".join(gate.message for gate in failed)
            or "Validation gates rejected rewrite.",
            "gates": _gate_payload(gates),
        }

    return {
        "accepted": True,
        "application_status": "pending_user_review",
        "bullet_id": bullet_id,
        "rewrite": final_text,
        "reason": "",
        "gates": _gate_payload(gates),
    }
