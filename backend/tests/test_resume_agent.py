from __future__ import annotations

import os
import sys
from typing import ClassVar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_model_factory_builds_agent_and_smart_models(monkeypatch):
    import config
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    agent = agent_models.create_agent_model()
    smart = agent_models.create_smart_model()

    assert agent.model_name == config.SEALION_AGENT_MODEL
    assert smart.model_name == config.SEALION_SMART_MODEL
    assert smart.max_tokens >= config.SMART_MIN_MAX_TOKENS


def test_search_jobs_returns_results_capped_at_config_limit(monkeypatch):
    import config
    import resume_agent.tools as agent_tools

    class Job:
        def __init__(self, job_id: int):
            self.id = job_id
            self.title = f"Data Engineer {job_id}"
            self.company = "GovTech"
            self.location = "Singapore"
            self.source = "careers.gov.sg"
            self.jd_summary = "Build data platforms."
            self.salary = "S$8k-S$10k"
            self.url = f"https://example.com/jobs/{job_id}"
            self.description = "Full job description with responsibilities."
            self.parsed_jd = {"required_skills": ["Python"]}
            self.skills = ["Python", "SQL"]

    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return [
                Job(job_id)
                for job_id in range(1, config.AGENT_SEARCH_JOBS_LIMIT + 3)
            ]

    class FakeDb:
        def query(self, *_args):
            return Query()

        def close(self):
            return None

    monkeypatch.setattr(agent_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(agent_tools, "encode_text", lambda _query: [0.1, 0.2])
    monkeypatch.setattr(
        agent_tools,
        "find_similar_jobs",
        lambda _vector, _db, top_k: [
            (job_id, 1.0 - (job_id / 100))
            for job_id in range(1, top_k + 3)
        ],
    )

    result = agent_tools.search_jobs.invoke(
        {"query": "data engineer", "n": config.AGENT_SEARCH_JOBS_LIMIT + 20}
    )

    assert result["ok"] is True
    assert result["count"] == config.AGENT_SEARCH_JOBS_LIMIT
    assert result["empty"] is False
    assert result["detail"] is False
    assert result["results"][0] == {
        "id": 1,
        "title": "Data Engineer 1",
        "company": "GovTech",
        "location": "Singapore",
        "source": "careers.gov.sg",
        "score": 0.99,
        "jd_summary": "Build data platforms.",
        "skills": ["Python", "SQL"],
    }
    assert "description" not in result["results"][0]


def test_search_jobs_detail_expands_job_payload(monkeypatch):
    import resume_agent.tools as agent_tools

    class Job:
        id = 7
        title = "AI Engineer"
        company = "GovTech"
        location = "Singapore"
        source = "careers.gov.sg"
        jd_summary = "Build AI services."
        salary = "S$8k-S$10k"
        url = "https://example.com/jobs/7"
        description = "Build agentic AI workflows for public services."
        parsed_jd = {"required_skills": ["Python"]}
        skills = ["Python"]

    class Query:
        def filter(self, *_args):
            return self

        def all(self):
            return [Job()]

    class FakeDb:
        def query(self, *_args):
            return Query()

        def close(self):
            return None

    monkeypatch.setattr(agent_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(agent_tools, "encode_text", lambda _query: [0.1, 0.2])
    monkeypatch.setattr(agent_tools, "find_similar_jobs", lambda *_args, **_kwargs: [(7, 0.9)])

    result = agent_tools.search_jobs.invoke({"query": "ai engineer", "detail": True})

    assert result["detail"] is True
    assert result["results"][0]["description"] == "Build agentic AI workflows for public services."
    assert result["results"][0]["parsed_jd"] == {"required_skills": ["Python"]}


def test_search_jobs_empty_results_are_explicit(monkeypatch):
    import resume_agent.tools as agent_tools

    class FakeDb:
        def close(self):
            return None

    monkeypatch.setattr(agent_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(agent_tools, "encode_text", lambda _query: [0.1, 0.2])
    monkeypatch.setattr(agent_tools, "find_similar_jobs", lambda *_args, **_kwargs: [])

    result = agent_tools.search_jobs.invoke({"query": "rare role"})

    assert result["ok"] is True
    assert result["empty"] is True
    assert result["count"] == 0
    assert result["results"] == []


def test_search_jobs_errors_are_structured(monkeypatch):
    import resume_agent.tools as agent_tools

    class FakeDb:
        def close(self):
            return None

    def broken_search(*_args, **_kwargs):
        raise RuntimeError("vector index unavailable")

    monkeypatch.setattr(agent_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(agent_tools, "encode_text", lambda _query: [0.1, 0.2])
    monkeypatch.setattr(agent_tools, "find_similar_jobs", broken_search)

    result = agent_tools.search_jobs.invoke({"query": "data engineer"})

    assert result["ok"] is False
    assert result["error"]["code"] == "search_failed"
    assert "vector index unavailable" in result["error"]["message"]


def test_agent_calls_search_jobs_for_role_query():
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool

    import resume_agent.agent as agent_module

    class ToolCallingFakeModel(FakeMessagesListChatModel):
        bound_tools: ClassVar[list] = []

        def bind_tools(self, tools, **_kwargs):
            type(self).bound_tools = tools
            return self

    calls = []

    @tool
    def search_jobs(query: str, n: int | None = None) -> list[dict]:
        """Search the jobs database."""
        calls.append((query, n))
        return [{"title": "Data Engineer", "company": "GovTech"}]

    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_jobs",
                        "args": {"query": "data engineer", "n": 2},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="Found Data Engineer at GovTech."),
        ]
    )
    agent = agent_module.create_resume_agent(
        model=model,
        tools=[search_jobs],
        subagents=[],
    )

    result = agent_module.run_agent_turn(agent, "Find data engineer jobs")

    assert calls == [("data engineer", 2)]
    assert result["messages"][-1].content == "Found Data Engineer at GovTech."
    assert any(getattr(msg, "name", "") == "search_jobs" for msg in result["messages"])


def test_propose_edit_accepts_clean_rewrite():
    import resume_agent.tools as agent_tools

    original = "Built data pipeline processing 10M events daily"
    rewrite = "Built reliable data pipeline processing 10M events daily"

    with agent_tools.bullet_context({"bullet-1": original}):
        result = agent_tools.propose_edit.invoke(
            {"bullet_id": "bullet-1", "rewrite": rewrite}
        )

    assert result["accepted"] is True
    assert result["bullet_id"] == "bullet-1"
    assert result["rewrite"] == rewrite


def test_propose_edit_rejects_fabricated_metric():
    import resume_agent.tools as agent_tools

    original = "Built data pipeline processing 10M events daily"
    rewrite = "Built data pipeline processing 10M events daily and improved uptime by 50%"

    with agent_tools.bullet_context({"bullet-1": original}):
        result = agent_tools.propose_edit.invoke(
            {"bullet_id": "bullet-1", "rewrite": rewrite}
        )

    assert result["accepted"] is False
    assert "Unsupported numeric facts" in result["reason"]


def test_persona_subagent_uses_smart_model_and_no_tools(monkeypatch):
    import config
    import resume_agent.models as agent_models
    import resume_agent.personas as personas

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    subagents = personas.create_persona_subagents()

    assert len(subagents) == config.AGENT_PERSONA_COUNT
    assert {subagent["name"] for subagent in subagents} == {
        "recruiter",
        "hiring_manager",
        "ats",
        "skeptic",
        "market_researcher",
    }
    for subagent in subagents:
        assert subagent["tools"] == []
        assert subagent["model"].model_name == config.SEALION_SMART_MODEL
        assert subagent["model"].max_tokens >= config.SMART_MIN_MAX_TOKENS


def test_per_bullet_diff_preserves_bullet_ids():
    from resume_structurer import get_all_bullets, structure_resume

    import resume_agent.diffs as agent_diffs

    resume_text = """
Jane Doe
jane@example.com

EXPERIENCE
GovTech | Data Engineer | Jan 2020 - Present
- Built data pipeline processing 10M events daily
- Led analytics migration for reporting workloads
"""
    bullets = get_all_bullets(structure_resume(resume_text))

    pending = agent_diffs.build_pending_diffs(
        resume_text,
        [
            {
                "bullet_id": bullets[0]["id"],
                "rewrite": "Built reliable data pipeline processing 10M events daily",
            },
            {
                "bullet_id": bullets[1]["id"],
                "rewrite": "Led analytics migration for reporting workloads and improved uptime by 50%",
            },
        ],
    )

    assert [diff["bullet_id"] for diff in pending] == [bullets[0]["id"]]
    assert pending[0]["original"] == bullets[0]["text"]
    assert pending[0]["rewrite"] == "Built reliable data pipeline processing 10M events daily"


def test_general_mode_runs_without_target_job():
    from langchain_core.messages import AIMessage

    import resume_agent.session as agent_session

    class FakeAgent:
        def __init__(self):
            self.message = ""

        def invoke(self, payload, config=None):
            self.message = payload["messages"][0]["content"]
            assert config["configurable"]["thread_id"]
            return {"messages": [AIMessage(content="General critique with safe edits.")]}

    fake_agent = FakeAgent()

    events = list(
        agent_session.stream_chat_events(
            {
                "message": "Strengthen this resume",
                "resume_text": "EXPERIENCE\n- Built data pipeline processing 10M events daily",
            },
            agent=fake_agent,
        )
    )

    session_id = events[0]["session_id"]
    state = agent_session.get_state(session_id)

    assert state["job_id"] is None
    assert state["mode"] == "general"
    assert "General strengthening mode" in fake_agent.message
    assert events[-1] == {"event": "done", "session_id": session_id}


def test_agent_prompt_includes_bounded_profile_context(monkeypatch):
    from langchain_core.messages import AIMessage

    import config as app_config
    import resume_agent.session as agent_session

    monkeypatch.setattr(app_config, "AGENT_MAX_PROFILE_CONTEXT_CHARS", 40)

    class FakeAgent:
        def __init__(self):
            self.message = ""

        def invoke(self, payload, config=None):
            self.message = payload["messages"][0]["content"]
            return {"messages": [AIMessage(content="Checked profile consistency.")]}

    fake_agent = FakeAgent()
    events = list(
        agent_session.stream_chat_events(
            {
                "message": "Review the candidate packet",
                "resume_text": "EXPERIENCE\n- Built Python data pipelines",
                "profile_context": "LinkedIn: Python, SQL, Tableau, stakeholder leadership, public speaking",
                "session_id": "profile-context",
            },
            agent=fake_agent,
            owner_key="profile-owner",
        )
    )

    state = agent_session.get_state("profile-context", owner_key="profile-owner")
    assert events[-1] == {"event": "done", "session_id": "profile-context"}
    assert "Optional LinkedIn/profile context" in fake_agent.message
    assert "Do not turn this into resume claims" in fake_agent.message
    assert "stakeholder leadership" not in fake_agent.message
    assert len(state["profile_context"]) == app_config.AGENT_MAX_PROFILE_CONTEXT_CHARS


def test_missing_agent_credentials_return_error_event(monkeypatch):
    import resume_agent.models as agent_models
    import resume_agent.session as agent_session

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "")

    events = list(
        agent_session.stream_chat_events(
            {
                "message": "Strengthen this resume",
                "resume_text": "EXPERIENCE\n- Built data pipeline processing 10M events daily",
            }
        )
    )

    assert events[0]["event"] == "session"
    assert events[1] == {
        "event": "error",
        "session_id": events[0]["session_id"],
        "message": "Agent v2 needs SEALION_API configured before it can run.",
    }
    assert events[-1] == {"event": "done", "session_id": events[0]["session_id"]}


def test_session_collects_propose_edit_tool_diffs():
    import json

    from langchain_core.messages import AIMessage, ToolMessage
    from resume_structurer import get_all_bullets, structure_resume

    import resume_agent.session as agent_session

    resume_text = "EXPERIENCE\n- Built data pipeline processing 10M events daily"
    bullet_id = get_all_bullets(structure_resume(resume_text))[0]["id"]

    class FakeAgent:
        def invoke(self, _payload, config=None):
            return {
                "messages": [
                    ToolMessage(
                        name="propose_edit",
                        tool_call_id="call_1",
                        content=json.dumps(
                            {
                                "accepted": True,
                                "bullet_id": bullet_id,
                                "rewrite": "Built reliable data pipeline processing 10M events daily",
                            }
                        ),
                    ),
                    AIMessage(content="Prepared one validated diff."),
                ]
            }

    events = list(
        agent_session.stream_chat_events(
            {"message": "Improve this", "resume_text": resume_text, "session_id": "diff-session"},
            agent=FakeAgent(),
            owner_key="diff-owner",
        )
    )
    state = agent_session.get_state(events[0]["session_id"], owner_key="diff-owner")

    assert state["pending_diffs"] == [
        {
            "bullet_id": bullet_id,
            "section_key": "experience",
            "entry_id": "exp-0",
            "original": "Built data pipeline processing 10M events daily",
            "rewrite": "Built reliable data pipeline processing 10M events daily",
            "status": "pending",
        }
    ]


def test_agent_state_is_owner_bound():
    from langchain_core.messages import AIMessage

    import resume_agent.session as agent_session

    class FakeAgent:
        def invoke(self, _payload, config=None):
            return {"messages": [AIMessage(content="owner bound")]}

    events = list(
        agent_session.stream_chat_events(
            {"message": "Review this", "session_id": "owner-bound"},
            agent=FakeAgent(),
            owner_key="user:1",
        )
    )

    assert events[0] == {"event": "session", "session_id": "owner-bound"}
    assert agent_session.get_state("owner-bound", owner_key="user:1")["session_id"] == "owner-bound"
    try:
        agent_session.get_state("owner-bound", owner_key="user:2")
    except PermissionError:
        pass
    else:
        raise AssertionError("state should not be visible to another owner")


def test_agent_rejects_oversized_draft(monkeypatch):
    import config as app_config
    import resume_agent.session as agent_session

    monkeypatch.setattr(app_config, "AGENT_MAX_DRAFT_CHARS", 10)

    events = list(
        agent_session.stream_chat_events(
            {"message": "Review this", "resume_text": "x" * 11},
            agent=object(),
        )
    )

    assert events[0]["event"] == "session"
    assert events[1]["event"] == "error"
    assert "too large" in events[1]["message"]
    assert events[-1] == {"event": "done", "session_id": events[0]["session_id"]}


def test_tool_iteration_cap_stops_runaway_loop():
    from langgraph.errors import GraphRecursionError

    import config as app_config
    import resume_agent.agent as agent_module

    class RunawayAgent:
        def invoke(self, _payload, config=None):
            assert config["recursion_limit"] == app_config.AGENT_MAX_TOOL_ITERATIONS
            raise GraphRecursionError("runaway")

    result = agent_module.run_agent_turn(
        RunawayAgent(),
        "Keep searching forever",
        session_id="cap-test",
    )

    assert result == {
        "messages": [],
        "stopped": True,
        "reason": "tool_iteration_cap",
    }


def test_active_run_gate_rejects_concurrent_same_owner():
    from langchain_core.messages import AIMessage

    import resume_agent.session as agent_session

    class NestedAgent:
        def invoke(self, _payload, config=None):
            nested_events = list(
                agent_session.stream_chat_events(
                    {"message": "nested", "session_id": "nested"},
                    agent=InstantAgent(),
                    owner_key="user:1",
                )
            )
            assert nested_events[1]["event"] == "error"
            return {"messages": [AIMessage(content="outer done")]}

    class InstantAgent:
        def invoke(self, _payload, config=None):
            return {"messages": [AIMessage(content="inner done")]}

    events = list(
        agent_session.stream_chat_events(
            {"message": "outer", "session_id": "outer"},
            agent=NestedAgent(),
            owner_key="user:1",
        )
    )

    assert events[-1] == {"event": "done", "session_id": "outer"}


def test_chat_endpoint_streams_token_and_tool_events(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(
        main,
        "_stream_resume_agent_events",
        lambda _body: iter(
            [
                {"event": "session", "session_id": "sid-1"},
                {
                    "event": "tool",
                    "session_id": "sid-1",
                    "name": "search_jobs",
                    "content": "[]",
                },
                {
                    "event": "token",
                    "session_id": "sid-1",
                    "content": "Found a role.",
                },
                {"event": "done", "session_id": "sid-1"},
            ]
        ),
    )

    response = TestClient(main.app).post(
        "/api/resume/agent/chat",
        json={"message": "Find data jobs"},
    )

    assert response.status_code == 200
    body = response.text
    assert body.index("event: tool") < body.index("event: token")
    assert '"name": "search_jobs"' in body
    assert '"content": "Found a role."' in body


def test_state_endpoint_returns_draft_todos_and_pending_diffs(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(
        main,
        "_get_resume_agent_state",
        lambda session_id, owner_key=None: {
            "session_id": session_id,
            "draft": "Resume draft",
            "todos": ["Review bullets"],
            "persona_findings": [{"persona": "recruiter", "finding": "Clear"}],
            "pending_diffs": [{"bullet_id": "exp-0-b0", "status": "pending"}],
        },
    )

    response = TestClient(main.app).get("/api/resume/agent/sid-1/state")

    assert response.status_code == 200
    data = response.json()
    assert data["draft"] == "Resume draft"
    assert data["todos"] == ["Review bullets"]
    assert data["pending_diffs"][0]["bullet_id"] == "exp-0-b0"


def test_smart_persona_output_strips_think_tags():
    import resume_agent.personas as personas

    raw = """
<think>private reasoning</think>
```json
{"findings": [{"persona": "recruiter", "message": "Clear impact."}]}
```
"""

    assert personas.parse_persona_output(raw) == {
        "findings": [{"persona": "recruiter", "message": "Clear impact."}]
    }


def test_fairness_counterfactual_name_school_swap():
    from resume_structurer import get_all_bullets, structure_resume

    import resume_agent.diffs as agent_diffs
    from resume_agent.prompts import FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS

    resume_a = """
Jane Doe
Singapore

EDUCATION
National University of Singapore | BSc Computer Science

EXPERIENCE
GovTech | Data Engineer | Jan 2020 - Present
- Built data pipeline processing 10M events daily
"""
    resume_b = resume_a.replace("Jane Doe", "Alex Tan").replace(
        "National University of Singapore",
        "Example Regional University",
    ).replace("Singapore", "Jurong")

    for term in ["name", "school/university", "GPA", "location"]:
        assert term in FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS

    bullet_a = get_all_bullets(structure_resume(resume_a))[0]
    bullet_b = get_all_bullets(structure_resume(resume_b))[0]
    proposal_a = {
        "bullet_id": bullet_a["id"],
        "rewrite": "Built reliable data pipeline processing 10M events daily",
    }
    proposal_b = {**proposal_a, "bullet_id": bullet_b["id"]}

    pending_a = agent_diffs.build_pending_diffs(resume_a, [proposal_a])
    pending_b = agent_diffs.build_pending_diffs(resume_b, [proposal_b])

    assert [diff["rewrite"] for diff in pending_a] == [
        diff["rewrite"] for diff in pending_b
    ]


def test_existing_pipeline_endpoints_unchanged():
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)

    tailor_response = client.post(
        "/api/resume/tailor",
        json={"resume_text": "too short", "job_id": 1, "intensity": "full"},
    )
    score_response = client.post(
        "/api/resume/score",
        json={"resume_text": "", "job_description": ""},
    )

    assert tailor_response.status_code == 400
    assert score_response.status_code in (200, 422)
