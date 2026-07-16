"""Shared result shapes for agent-facing tool adapters."""

from __future__ import annotations

from typing import Any

import config



SEARCH_JOBS_TOOL = "search_jobs"
GET_JOB_TOOL = "get_job"

SEARCH_RESULT_FIELDS = (
    "data_classification",
    "id",
    "title",
    "company",
    "location",
    "source",
    "score",
    "jd_summary",
    "skills",
)
JOB_DETAIL_FIELDS = SEARCH_RESULT_FIELDS + (
    "salary",
    "url",
    "description",
    "parsed_jd",
)


def limit_jobs(requested: int | None) -> int:
    if requested is None:
        return config.AGENT_SEARCH_JOBS_LIMIT
    try:
        value = int(requested)
    except (TypeError, ValueError):
        return config.AGENT_SEARCH_JOBS_LIMIT
    if value <= 0:
        return config.AGENT_SEARCH_JOBS_LIMIT
    return min(value, config.AGENT_SEARCH_JOBS_LIMIT)


def skills_list(skills: Any) -> list[str]:
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


def job_payload(
    job: Any,
    score: float | None = None,
    *,
    detail: bool = False,
    include_parsed: bool = True,
) -> dict:
    values = {
        "data_classification": "untrusted_job_data",
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": getattr(job, "location", ""),
        "source": getattr(job, "source", ""),
        "score": score,
        "jd_summary": getattr(job, "jd_summary", "") or "",
        "skills": skills_list(getattr(job, "skills", [])),
        "salary": getattr(job, "salary", ""),
        "url": getattr(job, "url", ""),
        "description": getattr(job, "description", "") or "",
        "parsed_jd": (
            job.parsed_jd if isinstance(getattr(job, "parsed_jd", None), dict) else {}
        ),
    }
    fields = JOB_DETAIL_FIELDS if detail else SEARCH_RESULT_FIELDS
    if not include_parsed:
        fields = tuple(field for field in fields if field != "parsed_jd")
    return {field: values[field] for field in fields if field != "score" or score is not None}


def search_jobs_result(query: str, limit: int, jobs: list[dict], *, detail: bool = False) -> dict:
    return {
        "ok": True,
        "status": "success",
        "tool": SEARCH_JOBS_TOOL,
        "query": query,
        "query_executed": True,
        "limit": limit,
        "detail": detail,
        "count": len(jobs),
        "result_count": len(jobs),
        "empty": len(jobs) == 0,
        "results": jobs,
        "detail_available": not detail,
        "detail_request": None
        if detail
        else "Call search_jobs with detail=true, or get_job with the id.",
    }


def search_jobs_error(
    query: str,
    code: str,
    message: str,
    *,
    failure_type: str = "unavailable",
) -> dict:
    return {
        "ok": False,
        "status": "error",
        "tool": SEARCH_JOBS_TOOL,
        "query": query,
        "query_executed": False,
        "results": None,
        "result_count": None,
        "failure_type": failure_type,
        "retryable": failure_type in {"timeout", "rate_limit", "unavailable"},
        "error": {
            "code": code,
            "message": message,
        },
    }


def get_job_result(job: dict) -> dict:
    return {
        "ok": True,
        "status": "success",
        "tool": GET_JOB_TOOL,
        "query_executed": True,
        "found": True,
        "job": job,
    }


def get_job_empty_result(job_id: int) -> dict:
    return {
        "ok": True,
        "status": "success",
        "tool": GET_JOB_TOOL,
        "query_executed": True,
        "found": False,
        "job": None,
        "job_id": job_id,
    }


def tool_error(
    tool: str,
    code: str,
    message: str,
    *,
    failure_type: str = "unavailable",
    retryable: bool | None = None,
    **context: Any,
) -> dict:
    payload = {
        "ok": False,
        "status": "error",
        "tool": tool,
        "query_executed": False,
        "results": None,
        "failure_type": failure_type,
        "retryable": (
            failure_type in {"timeout", "rate_limit", "unavailable"}
            if retryable is None
            else retryable
        ),
        "error": {
            "code": code,
            "message": message,
        },
    }
    if context:
        payload["context"] = context
    return payload
