from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from recruitment_team.open_agent.guardrails import has_repeated_call


def test_detects_a_materially_identical_prior_call():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "search_jobs", "args": {"query": "backend engineer"}, "id": "1"}]),
        ToolMessage(content="{}", name="search_jobs", tool_call_id="1"),
    ]
    assert has_repeated_call(messages, "search_jobs", {"query": "backend engineer"}) is True


def test_allows_a_call_with_different_arguments():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "search_jobs", "args": {"query": "backend engineer"}, "id": "1"}]),
        ToolMessage(content="{}", name="search_jobs", tool_call_id="1"),
    ]
    assert has_repeated_call(messages, "search_jobs", {"query": "platform engineer"}) is False


def test_allows_the_first_call():
    assert has_repeated_call([], "search_jobs", {"query": "backend engineer"}) is False
