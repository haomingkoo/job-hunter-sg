from __future__ import annotations

import importlib
import json
import os
import secrets
from pathlib import Path

import pytest
from resume_agent.contracts import TARGET_JOB_PERSONAS


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_backend_env() -> None:
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


_load_backend_env()

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_SEALION") != "1",
    reason="Set RUN_LIVE_SEALION=1 plus SEALION_API or sealion_api in the environment or backend/.env.",
)


def _reload_live_agent_modules():
    for module_name in (
        "config",
        "ai_service",
        "resume_agent.models",
        "resume_agent.personas",
        "resume_agent.agent",
        "resume_agent.session",
    ):
        importlib.reload(importlib.import_module(module_name))

    import ai_service
    import resume_agent.session as agent_session
    import resume_agent.telemetry as telemetry

    telemetry.configure_telemetry()

    return ai_service, agent_session


def _assert_completed(events: list[dict]) -> None:
    errors = [event.get("message", "") for event in events if event.get("event") == "error"]
    assert not errors
    assert events[0]["event"] == "session"
    assert events[-1] == {"event": "done", "session_id": events[0]["session_id"]}
    assert any(event.get("event") == "token" and str(event.get("content", "")).strip() for event in events)


def test_live_sealion_agent_completes_small_multi_turn_review():
    ai_service, agent_session = _reload_live_agent_modules()
    if not ai_service._get_api_key():
        pytest.fail("RUN_LIVE_SEALION=1 requires SEALION_API or sealion_api in the environment or backend/.env.")

    session_id = f"live-smoke-{secrets.token_hex(4)}"
    owner_key = f"live-smoke-owner-{secrets.token_hex(4)}"
    resume_text = """
Jane Tan
jane@example.com

EXPERIENCE
GovTech | AI Project Lead | Jan 2022 - Present
- Led delivery of an internal document assistant for operations teams
- Coordinated engineers, policy users, and QA reviewers across rollout
"""

    first_events = list(
        agent_session.stream_chat_events(
            {
                "session_id": session_id,
                "message": "Give one concise recruiter review of this resume. Do not search jobs.",
                "resume_text": resume_text,
                "job_context": {
                    "title": "AI Project Lead",
                    "company": "Example Agency",
                    "description": "Own document automation delivery and stakeholder rollout.",
                    "terms": ["document automation", "stakeholder rollout"],
                    "location": "Singapore",
                    "source": "live-smoke",
                },
            },
            owner_key=owner_key,
        )
    )
    _assert_completed(first_events)
    first_assessment = next(
        event["content"]
        for event in reversed(first_events)
        if event.get("event") == "token" and event.get("content")
    )
    assessment_headings = ["Summary", "Strengths", "Weaknesses", "Independent reviewer score", "Reasoning", "Next actions"]
    assessment_positions = [first_assessment.index(heading) for heading in assessment_headings]
    assert assessment_positions == sorted(assessment_positions)

    second_events = list(
        agent_session.stream_chat_events(
            {
                "session_id": session_id,
                "message": "Now give one concrete non-fabricated improvement to make the review more useful.",
            },
            owner_key=owner_key,
        )
    )
    _assert_completed(second_events)

    state = agent_session.get_state(session_id, owner_key=owner_key)
    assistant_outputs = [
        event["content"]
        for event in [*first_events, *second_events]
        if event.get("event") == "token" and event.get("content")
    ]
    assert state["draft"].strip() == resume_text.strip()
    assert len(assistant_outputs) >= 2
    assert {finding["persona"] for finding in state["persona_findings"]} == {
        "recruiter",
        "hiring_manager",
        "ats",
        "skeptic",
        "market_researcher",
    }
    evidence_ids = {
        block["id"] for block in state["document"]["blocks"]
    }
    assert all(
        set(finding["evidence_ids"]) <= evidence_ids
        for finding in state["persona_findings"]
    )
    assert all(finding["rationale"] for finding in state["persona_findings"])
    assert len({
        finding["category"].strip().lower()
        for finding in state["persona_findings"]
    }) >= 3
    assert all(
        placeholder not in json.dumps(finding)
        for finding in state["persona_findings"]
        for placeholder in ("[X]", "[Y]", "TBD")
    )
    assert all(
        finding["target_job_fields"]
        for finding in state["persona_findings"]
        if finding["persona"] == "market_researcher"
    )
    successful_model_workers = {
        span.get("worker")
        for span in state["tool_spans"]
        if span.get("kind") == "llm" and span.get("status") == "success"
    }
    assert {*TARGET_JOB_PERSONAS, "orchestrator", "quality_judge"} <= successful_model_workers


def test_live_sealion_agent_calls_search_jobs_for_role_research(monkeypatch):
    ai_service, agent_session = _reload_live_agent_modules()
    if not ai_service._get_api_key():
        pytest.fail("RUN_LIVE_SEALION=1 requires SEALION_API or sealion_api in the environment or backend/.env.")

    import resume_agent.agent as agent_module
    import resume_agent.tools as agent_tools

    class Job:
        def __init__(self, job_id: int, title: str, company: str):
            self.id = job_id
            self.title = title
            self.company = company
            self.location = "Singapore"
            self.source = "live-smoke"
            self.jd_summary = "Agentic product role for AI workflow delivery."
            self.skills = ["AI product", "Python", "stakeholder management"]

    jobs = [
        Job(1, "Senior AI Product Manager", "GovTech"),
        Job(2, "AI Workflow Lead", "DBS"),
    ]
    search_calls = []

    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return jobs

    class FakeDb:
        def query(self, *_args):
            return Query()

        def close(self):
            return None

    def fake_find_similar_jobs(query_vector, _db, top_k):
        search_calls.append({"query_vector": query_vector, "top_k": top_k})
        return [(1, 0.98), (2, 0.94)]

    monkeypatch.setattr(agent_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(agent_tools, "encode_text", lambda _query: [0.1, 0.2])
    monkeypatch.setattr(agent_tools, "find_similar_jobs", fake_find_similar_jobs)

    agent = agent_module.create_resume_agent(
        tools=[agent_tools.search_jobs],
        subagents=[],
    )
    recorder = agent_session._ToolSpanRecorder()
    result = agent_module.run_agent_turn(
        agent,
        (
            "Find similar Singapore jobs for a candidate targeting AI product "
            "and workflow automation roles. Use the internal jobs database, "
            "then answer with the best matching title and company."
        ),
        session_id=f"live-search-jobs-smoke-{secrets.token_hex(4)}",
        callbacks=[recorder],
    )

    tool_messages = [
        message
        for message in result.get("messages", [])
        if getattr(message, "name", "") == "search_jobs"
    ]

    assert search_calls
    assert tool_messages
    assert "Senior AI Product Manager" in str(tool_messages[0].content)
    assert any(
        span["name"] == "search_jobs" and span["status"] == "success"
        for span in recorder.spans
    )
