"""Run an authenticated Resume Deep Agent canary against a deployed environment."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import config
from resume_agent.contracts import TARGET_JOB_PERSONAS
from resume_agent.telemetry import trace_key

SAMPLE_RESUME = """Jane Tan
jane@example.com

EXPERIENCE
GovTech | AI Project Lead | Jan 2022 - Present
- Led delivery of an internal document assistant for operations teams
- Coordinated engineers, policy users, and QA reviewers across rollout
"""
SAMPLE_JOB = {
    "title": "AI Project Lead",
    "company": "Deployment Canary",
    "description": "Own document automation delivery and stakeholder rollout.",
    "terms": ["document automation", "stakeholder rollout"],
    "location": "Singapore",
    "source": "deployment-canary",
}
SYNTHESIS_PHASES = {"orchestrator", "orchestrator_revision"}


def validate_terminal_state(state: dict) -> None:
    """Fail unless a deployed review completed every required stage successfully."""
    assert state.get("status") == "completed", state.get("error") or state.get("status")
    assert state.get("review_status") == "success", state.get("review_status")
    assert state.get("mode") == "target_job", state.get("mode")
    assert state.get("job_context") == SAMPLE_JOB, "target-job context was lost"
    assert str(state.get("response") or "").strip(), "synthesis response is empty"
    assert not state.get("presentation_violations"), state.get("presentation_violations")

    runs = state.get("worker_runs") or []
    personas = {run.get("persona") for run in runs}
    expected_personas = set(TARGET_JOB_PERSONAS)
    assert personas == expected_personas, f"reviewer coverage mismatch: {sorted(personas)}"
    failed = [run for run in runs if run.get("status") != "success"]
    assert not failed, f"reviewers did not succeed: {failed}"
    assert (state.get("judge_run") or {}).get("status") == "success", "quality judge failed"
    assert not (state.get("judge_assessment") or {}).get("requires_revision", True), (
        "quality judge still requires a synthesis revision"
    )
    revision = state.get("synthesis_revision") or {}
    assert not revision.get("attempted") or revision.get("resolved"), (
        "synthesis revision did not resolve the evidence issue"
    )

    spans = state.get("tool_spans") or []
    successful_model_spans = [
        span
        for span in spans
        if span.get("kind") == "llm" and span.get("status") == "success"
    ]
    successful_model_workers = {
        span.get("worker")
        for span in successful_model_spans
    }
    expected_model_workers = {*TARGET_JOB_PERSONAS, "orchestrator", "quality_judge"}
    assert expected_model_workers <= successful_model_workers, (
        f"missing successful model workers: {sorted(expected_model_workers - successful_model_workers)}"
    )
    reviewer_model_spans = [
        span for span in successful_model_spans
        if span.get("worker") in TARGET_JOB_PERSONAS
    ]
    assert len(reviewer_model_spans) == len(TARGET_JOB_PERSONAS), (
        "reviewers made duplicate or missing model calls"
    )
    synthesis_model_spans = [
        span for span in successful_model_spans
        if span.get("worker") == "orchestrator"
    ]
    judge_model_spans = [
        span for span in successful_model_spans
        if span.get("worker") == "quality_judge"
    ]
    assert len(synthesis_model_spans) == len(judge_model_spans), (
        "each synthesis pass must have one independent judge pass"
    )
    assert {span.get("phase") for span in synthesis_model_spans} <= SYNTHESIS_PHASES
    assert 0 < len(synthesis_model_spans) <= len(SYNTHESIS_PHASES), (
        "quality recovery exceeded the bounded synthesis passes"
    )
    submission_workers = {
        span.get("worker")
        for span in spans
        if span.get("kind") == "tool"
        and span.get("name") == "submit_assessment"
        and span.get("status") == "success"
    }
    assert set(TARGET_JOB_PERSONAS) <= submission_workers, (
        "not every reviewer used the structured assessment contract"
    )
    judge_submissions = [
        span for span in spans
        if span.get("kind") == "tool"
        and span.get("worker") == "quality_judge"
        and span.get("name") == "submit_quality_judgment"
        and span.get("status") == "success"
    ]
    assert len(judge_submissions) == len(judge_model_spans), (
        "each judge pass must use the native structured judgment contract"
    )
    assessment_edit_calls = [
        span for span in spans
        if span.get("kind") == "tool"
        and span.get("worker") == "orchestrator"
        and span.get("name") == "propose_edit"
    ]
    assert not assessment_edit_calls, "read-only assessment invoked the edit tool"


def _request(session: requests.Session, method: str, url: str, **kwargs) -> dict:
    response = session.request(
        method,
        url,
        timeout=config.AGENT_E2E_REQUEST_TIMEOUT_SECONDS,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def _wait_for_terminal(
    session: requests.Session,
    base_url: str,
    session_id: str,
    timeout_seconds: int,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state = _request(session, "GET", f"{base_url}/api/resume/agent/{session_id}/state")
        if state.get("status") in {"completed", "failed"}:
            return state
        time.sleep(config.AGENT_E2E_POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"review did not reach a terminal state within {timeout_seconds}s")


def run_canary(base_url: str, token: str) -> str:
    base_url = base_url.rstrip("/")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})

    health = _request(session, "GET", f"{base_url}/api/health")
    assert health.get("status") == "ok", f"health check failed: {health}"

    started = _request(session, "POST", f"{base_url}/api/resume/agent/start", json={
        "message": "Run a concise evidence-backed target-job review.",
        "resume_text": SAMPLE_RESUME,
        "job_context": SAMPLE_JOB,
    })
    session_id = str(started.get("session_id") or "")
    assert session_id, "start endpoint returned no session_id"
    validate_terminal_state(_wait_for_terminal(
        session,
        base_url,
        session_id,
        config.AGENT_E2E_TERMINAL_TIMEOUT_SECONDS,
    ))

    follow_up = _request(session, "POST", f"{base_url}/api/resume/agent/start", json={
        "session_id": session_id,
        "message": "Give one concrete non-fabricated improvement to the review.",
    })
    assert follow_up.get("session_id") == session_id, "follow-up changed session"
    validate_terminal_state(_wait_for_terminal(
        session,
        base_url,
        session_id,
        config.AGENT_E2E_TERMINAL_TIMEOUT_SECONDS,
    ))
    return trace_key(session_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("JOB_HUNTER_E2E_BASE_URL", ""),
        help="Staging base URL; can also use JOB_HUNTER_E2E_BASE_URL.",
    )
    args = parser.parse_args()
    token = os.getenv("JOB_HUNTER_E2E_TOKEN", "")
    if not args.base_url or not token:
        parser.error("set JOB_HUNTER_E2E_BASE_URL and JOB_HUNTER_E2E_TOKEN")

    try:
        trace_key = run_canary(args.base_url, token)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: deployed Resume Deep Agent completed two turns; trace_key={trace_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
