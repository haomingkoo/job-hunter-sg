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
    agent = agent_module.create_resume_agent(model=model, tools=[search_jobs])

    result = agent_module.run_agent_turn(agent, "Find data engineer jobs")

    assert calls == [("data engineer", 2)]
    assert result["messages"][-1].content == "Found Data Engineer at GovTech."
    assert any(getattr(msg, "name", "") == "search_jobs" for msg in result["messages"])
