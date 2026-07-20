"""V3-specific tools bound to the open-agent orchestrator. search_jobs is reused
unmodified from resume_agent.tools -- it needs no per-request context."""

from __future__ import annotations

from dataclasses import asdict

from langchain_core.tools import tool

from . import context


@tool
def read_candidate_evidence() -> dict:
    """Read the candidate's evidence-cited profile fields for the active run.

    Returns each field with its resume_evidence_ids, so a citation in a
    persona submission or a proposed edit can point at real evidence.
    """
    request = context.current_request()
    if request is None:
        return {"ok": False, "failure_type": "business", "reason": "No active assessment context."}
    return {
        "ok": True,
        "fields": [asdict(field) for field in request.candidate_profile.fields],
    }


@tool
def read_target_job() -> dict:
    """Read the target job posting and its derived role-success criteria for the active run."""
    request = context.current_request()
    if request is None:
        return {"ok": False, "failure_type": "business", "reason": "No active assessment context."}
    return {
        "ok": True,
        "target_job": asdict(request.target_job),
        "role_profile": asdict(request.role_profile),
    }
