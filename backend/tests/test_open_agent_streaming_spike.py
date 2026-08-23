from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

import config
from resume_agent.agent import create_resume_agent
from recruitment_team.open_agent.streaming import iter_progress_events


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_iter_progress_events_yields_tool_call_ids(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    read_call = AIMessage(
        content="", tool_calls=[{"name": "some_tool", "args": {}, "id": "call-abc"}]
    )
    model = _ScriptedModel(responses=[read_call, AIMessage(content="Done.")])
    agent = create_resume_agent(model=model, tools=[], subagents=[])

    events = list(iter_progress_events(
        agent,
        {"messages": [{"role": "user", "content": "Go."}]},
        {"recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS},
    ))

    tool_call = next(e for e in events if e["kind"] == "tool_call")
    assert tool_call["id"] == "call-abc"


def test_iter_progress_events_exposes_safe_model_usage_without_message_content():
    message = AIMessage(
        id="model-message-1",
        content="private synthesis",
        response_metadata={"model_name": "model-a"},
        usage_metadata={"input_tokens": 13, "output_tokens": 5, "total_tokens": 18},
    )

    class Agent:
        def stream(self, *_args, **_kwargs):
            yield (), {"model": {"messages": [message]}}

    events = list(iter_progress_events(Agent(), {}, {}))
    model_event = next(event for event in events if event["kind"] == "model_attempt")

    assert model_event == {
        "kind": "model_attempt",
        "team_member": "coordinator",
        "id": "model-message-1",
        "attempt": 1,
        "model": "model-a",
        "input_tokens": 13,
        "output_tokens": 5,
    }
    assert "private synthesis" not in str(model_event)


def test_iter_progress_events_skips_a_tool_call_id_exactly_once(monkeypatch):
    """Proves the skip_tool_call_ids mechanism the resume path relies on to
    suppress LangGraph's replay of an interrupted ask_candidate call: a
    matching id is dropped the first time and the set is consumed, so a
    second, genuinely distinct call sharing no id is never affected."""
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    first_call = AIMessage(
        content="", tool_calls=[{"name": "some_tool", "args": {"n": 1}, "id": "call-skip-me"}]
    )
    second_call = AIMessage(
        content="", tool_calls=[{"name": "some_tool", "args": {"n": 2}, "id": "call-keep-me"}]
    )
    model = _ScriptedModel(responses=[first_call, second_call, AIMessage(content="Done.")])
    agent = create_resume_agent(model=model, tools=[], subagents=[])

    events = list(iter_progress_events(
        agent,
        {"messages": [{"role": "user", "content": "Go."}]},
        {"recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS},
        skip_tool_call_ids={"call-skip-me"},
    ))

    tool_calls = [e for e in events if e["kind"] == "tool_call"]
    ids = [e["id"] for e in tool_calls]
    assert "call-skip-me" not in ids
    assert "call-keep-me" in ids
