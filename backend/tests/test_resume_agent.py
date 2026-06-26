from __future__ import annotations

import os
import sys
from typing import ClassVar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_model_factory_builds_fast_and_smart_models(monkeypatch):
    import config
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    fast = agent_models.create_fast_model()
    smart = agent_models.create_smart_model()

    assert fast.model_name == config.SEALION_FAST_MODEL
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

    results = agent_tools.search_jobs.invoke(
        {"query": "data engineer", "n": config.AGENT_SEARCH_JOBS_LIMIT + 20}
    )

    assert len(results) == config.AGENT_SEARCH_JOBS_LIMIT
    assert results[0] == {
        "id": 1,
        "title": "Data Engineer 1",
        "company": "GovTech",
        "location": "Singapore",
        "source": "careers.gov.sg",
        "score": 0.99,
        "jd_summary": "Build data platforms.",
        "skills": ["Python", "SQL"],
    }


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
