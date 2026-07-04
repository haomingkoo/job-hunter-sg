"""Shared result shapes for agent-facing tool adapters."""

from __future__ import annotations

from typing import Any

import config


SEARCH_JOBS_TOOL = "search_jobs"
GET_JOB_TOOL = "get_job"

SEARCH_RESULT_FIELDS = (
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


def job_payload(job: Any, score: float | None = None, *, detail: bool = False) -> dict:
    values = {
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
    return {field: values[field] for field in fields if field != "score" or score is not None}


def search_jobs_result(query: str, limit: int, jobs: list[dict], *, detail: bool = False) -> dict:
    return {
        "ok": True,
        "tool": SEARCH_JOBS_TOOL,
        "query": query,
        "limit": limit,
        "detail": detail,
        "count": len(jobs),
        "empty": len(jobs) == 0,
        "results": jobs,
        "detail_available": not detail,
        "detail_request": None
        if detail
        else "Call search_jobs with detail=true, or get_job with the id.",
    }


def get_job_result(job: dict) -> dict:
    return {
        "ok": True,
        "tool": GET_JOB_TOOL,
        "found": True,
        "job": job,
    }


def tool_error(tool: str, code: str, message: str, **context: Any) -> dict:
    payload = {
        "ok": False,
        "tool": tool,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if context:
        payload["context"] = context
    return payload
