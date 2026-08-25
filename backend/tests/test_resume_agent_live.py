from __future__ import annotations

import importlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv
from resume_agent.contracts import TARGET_JOB_PERSONAS


BACKEND_DIR = Path(__file__).resolve().parents[1]


load_dotenv(BACKEND_DIR / ".env", override=False)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_SEALION") != "1",
    reason="Set RUN_LIVE_SEALION=1 plus SEALION_API or sealion_api in the environment or backend/.env.",
)

LIVE_PROMPT_EVAL_REPEATS = int(os.getenv("LIVE_PROMPT_EVAL_REPEATS", "3"))


def _prompt_eval_source(posting_id: str, url: str):
    from recruitment_team.discovery import JobSource

    return JobSource(
        source="prompt-eval",
        url=url,
        source_posting_id=posting_id,
        posted_date="2026-08-20",
        closing_date="",
        scraped_at="2026-08-24",
        availability="current",
        snapshot_sha256="prompt-eval",
    )


def _prompt_eval_discovery(jobs, *, company: str = ""):
    from recruitment_team.discovery import JobSearchResult

    class RecordingDiscovery:
        def __init__(self):
            self.calls = []

        def search_jobs(
            self,
            query: str,
            *,
            company: str = "",
            direct_employers_only: bool = True,
            exclude_junior: bool = False,
            singapore_only: bool = True,
            title_phrase: str = "",
        ):
            self.calls.append({
                "query": query,
                "company": company,
                "direct_employers_only": direct_employers_only,
                "exclude_junior": exclude_junior,
                "singapore_only": singapore_only,
                "title_phrase": title_phrase,
            })
            company_matches = company.casefold() == expected_company.casefold()
            visible = jobs if direct_employers_only and company_matches else ()
            if exclude_junior:
                from job_visibility import is_junior_posting

                visible = tuple(
                    job for job in visible
                    if not is_junior_posting(job.seniority, job.title)
                )
            if title_phrase:
                from job_visibility import job_title_matches

                visible = tuple(
                    job for job in visible
                    if job_title_matches(job.title, title_phrase)
                )
            return JobSearchResult(
                query=query,
                jobs=visible,
                candidate_count=len(visible),
                visible_candidate_count=len(visible),
                truncated=False,
                valid_empty=not visible,
                eligible_candidate_count=len(visible),
                company=company,
                direct_employers_only=direct_employers_only,
                exclude_junior=exclude_junior,
                singapore_only=singapore_only,
                title_phrase=title_phrase,
            )

        def get_job(self, job_id: int):
            return next((item for item in jobs if item.job_id == job_id), None)

    expected_company = company
    return RecordingDiscovery()


def _prompt_eval_context(thread_id, discovery, resume_text, message):
    from backend.tests.fakes import AllowingEditEvidenceValidator
    from recruitment_team.coordinator.context import ConversationContext

    return ConversationContext(
        thread_id=thread_id,
        trace_key=f"trace-{thread_id}",
        candidate_profile=None,
        role_profile=None,
        target_job=None,
        resume_document={"blocks": [{"id": "b_experience", "text": resume_text}]},
        latest_search_query="",
        recommendations=(),
        shortlisted_jobs=(),
        preferences=(),
        published_matches=(),
        discovery=discovery,
        edit_evidence_validator=AllowingEditEvidenceValidator(),
        latest_user_message=message,
        latest_user_message_id=1,
        latest_user_run_id=thread_id,
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
            self.seniority = "Mid"
            self.salary_floor = 8_000

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


@pytest.mark.parametrize("repeat", range(LIVE_PROMPT_EVAL_REPEATS))
def test_live_recruitment_coordinator_preserves_named_employer_intent(repeat):
    """Prompt eval: a named employer must survive intent-to-tool translation."""
    import ai_service
    from recruitment_team.coordinator.model import DeepAgentConversationModel
    from recruitment_team.discovery import JobSnapshot
    from recruitment_team.interface import Message
    from recruitment_team.telemetry import RecordedTelemetry

    if not ai_service._get_api_key():
        pytest.fail("RUN_LIVE_SEALION=1 requires a configured SEA-LION API key.")

    source = _prompt_eval_source("prompt-eval-micron", "https://example.test/micron-quality")
    micron_job = JobSnapshot(
        job_id=1,
        title="Senior Manager, FE Central PQE (Deviation Management)",
        company="MICRON SEMICONDUCTOR ASIA OPERATIONS PTE. LTD.",
        location="Singapore",
        salary="$10,000 - $18,000",
        employment_type="Full Time",
        seniority="Manager",
        description=(
            "Lead global semiconductor deviation management, quality transformation, "
            "yield improvement, analytics, and technical teams."
        ),
        skills=("Quality Management", "Semiconductor Fabrication", "Transformation Programme"),
        similarity_score=0.9,
        source=source,
    )

    discovery = _prompt_eval_discovery((micron_job,), company="micron")
    telemetry = RecordedTelemetry()
    thread_id = f"live-employer-intent-{repeat}-{secrets.token_hex(4)}"
    resume_text = (
        "Led multi-site semiconductor quality transformation, deviation management, "
        "yield improvement, and analytics across four regions."
    )
    context = _prompt_eval_context(thread_id, discovery, resume_text, "micron")
    model = DeepAgentConversationModel(telemetry=telemetry)
    reply = model.respond(
        [Message(1, "user", "micron", thread_id, datetime.now(timezone.utc))],
        resume_text,
        context=context,
    )

    assert discovery.calls
    assert not reply.checkpoint_cleanup_token
    assert all(call["company"].casefold() == "micron" for call in discovery.calls)
    assert all(call["direct_employers_only"] is True for call in discovery.calls)
    assert any(
        update.field == "company"
        and update.value.casefold() == "micron"
        and update.evidence_quote == "micron"
        for update in context.drafted_preferences
    )
    assert any(
        span.name == "model_transport"
        and span.status == "success"
        and span.attributes.get("role") == "coordinator"
        for span in telemetry.spans
    )
    assert any(
        span.name == "checkpoint_cleanup"
        and span.status == "success"
        and span.attributes.get("cleanup_succeeded") is True
        for span in telemetry.spans
    )


@pytest.mark.parametrize("repeat", range(LIVE_PROMPT_EVAL_REPEATS))
def test_live_recruitment_coordinator_keeps_general_search_employer_neutral_and_ranks_fit(
    repeat,
):
    """Prompt eval: general discovery must not invent a company constraint."""
    import ai_service
    from recruitment_team.coordinator.model import DeepAgentConversationModel
    from recruitment_team.discovery import JobSnapshot
    from recruitment_team.interface import Message
    from recruitment_team.telemetry import RecordedTelemetry

    if not ai_service._get_api_key():
        pytest.fail("RUN_LIVE_SEALION=1 requires a configured SEA-LION API key.")

    source = _prompt_eval_source("prompt-eval-general", "https://example.test/job")

    def job(job_id, title, company, description, skills, seniority):
        return JobSnapshot(
            job_id=job_id,
            title=title,
            company=company,
            location="Singapore",
            salary="$8,000 - $12,000",
            employment_type="Full Time",
            seniority=seniority,
            description=description,
            skills=tuple(skills),
            similarity_score=0.8,
            source=source,
            salary_context={
                "basis": "synthetic prompt evaluation",
                "sample_count": 4,
                "median_salary_floor": 8_000,
                "posting_salary_floor": 8_000,
                "posting_floor_percentile": 50.0,
            },
        )

    jobs = (
        job(
            11,
            "Senior Manufacturing Transformation Manager",
            "Atlas Semiconductor Pte Ltd",
            "Lead multi-site semiconductor manufacturing transformation, quality governance, yield improvement and engineering teams.",
            ("semiconductor manufacturing", "quality", "yield", "change management"),
            "Manager",
        ),
        job(
            12,
            "Quality Systems Manager",
            "Lumina Microelectronics Pte Ltd",
            "Own QMS, CAPA, ISO 9001, 8D and FMEA across manufacturing sites.",
            ("QMS", "CAPA", "ISO 9001", "8D", "FMEA"),
            "Manager",
        ),
        job(
            13,
            "Semiconductor Sales Manager",
            "Commercial Components Pte Ltd",
            "Own regional sales targets, accounts and distributor relationships.",
            ("sales", "account management"),
            "Manager",
        ),
        job(
            14,
            "Junior Laboratory Technician",
            "Atlas Semiconductor Pte Ltd",
            "Prepare samples and perform routine measurements under supervision.",
            ("sample preparation",),
            "Fresh/entry level",
        ),
    )

    resume_text = (
        "Led multi-site semiconductor manufacturing and quality transformation across "
        "four regions, improving yield and mentoring 12 engineers in 8D and 5 Why."
    )
    discovery = _prompt_eval_discovery(jobs)
    telemetry = RecordedTelemetry()
    thread_id = f"live-general-match-{repeat}-{secrets.token_hex(4)}"
    context = _prompt_eval_context(
        thread_id,
        discovery,
        resume_text,
        "Find manager roles for me.",
    )

    reply = DeepAgentConversationModel(telemetry=telemetry).respond(
        [
            Message(
                1,
                "user",
                "Find manager roles for me.",
                thread_id,
                datetime.now(timezone.utc),
            )
        ],
        resume_text,
        context=context,
    )

    assert discovery.calls
    assert not reply.checkpoint_cleanup_token
    assert all(call["company"] == "" for call in discovery.calls)
    assert all(call["direct_employers_only"] is True for call in discovery.calls)
    assert all(call["singapore_only"] is True for call in discovery.calls)
    assert all(call["title_phrase"].casefold() == "manager" for call in discovery.calls)
    assert all(
        call["exclude_junior"] is True
        or call["title_phrase"].casefold() == "manager"
        for call in discovery.calls
    )
    assert any(
        term in " ".join(call["query"] for call in discovery.calls).casefold()
        for term in ("semiconductor", "manufacturing", "quality", "yield")
    )
    assert context.drafted_matches
    published_ids = [match["job_id"] for match in context.drafted_matches]
    assert published_ids[0] == 11
    assert 13 not in published_ids
    assert 14 not in published_ids
    assert any(
        span.name == "model_transport"
        and span.status == "success"
        and span.attributes.get("role") == "coordinator"
        and span.attributes.get("model")
        for span in telemetry.spans
    )
    assert any(
        span.name == "checkpoint_cleanup"
        and span.status == "success"
        and span.attributes.get("cleanup_succeeded") is True
        for span in telemetry.spans
    )
