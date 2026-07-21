# backend/tests/test_open_agent_streaming_spike.py
from __future__ import annotations

import json

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

import config
from resume_agent.agent import create_resume_agent
from resume_agent.personas import create_persona_subagents
from recruitment_team.open_agent.streaming import iter_progress_events


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _delegate_call(subagent_type: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "task",
            "args": {"description": f"Review as {subagent_type}.", "subagent_type": subagent_type},
            "id": call_id,
        }],
    )


def _submission_args(summary: str, score: int) -> dict:
    return {
        "summary": summary, "category": "ownership",
        "findings": [{
            "kind": "strength", "finding": "Shipped a feature end-to-end.", "source": "resume",
            "source_location": "bullet-1", "method": "Read the bullet.", "relevance_score": 0.8,
        }],
        "score": score, "reasoning": "Ownership is clear.", "suggested_actions": ["Add a metric."],
    }


def test_iter_progress_events_reports_two_sequential_persona_delegations(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    orchestrator_model = _ScriptedModel(responses=[
        _delegate_call("recruiter", "call-1"),
        _delegate_call("ats", "call-2"),
        AIMessage(content="Consulted both personas."),
    ])

    recruiter_submit = AIMessage(content="", tool_calls=[{"name": "submit_assessment", "args": _submission_args("Recruiter view.", 80), "id": "r-1"}])
    recruiter_model = _ScriptedModel(responses=[recruiter_submit, AIMessage(content="Recruiter done.")])

    ats_submit = AIMessage(content="", tool_calls=[{"name": "submit_assessment", "args": _submission_args("ATS view.", 65), "id": "a-1"}])
    ats_model = _ScriptedModel(responses=[ats_submit, AIMessage(content="ATS done.")])

    subagents = create_persona_subagents(smart_model=recruiter_model)
    subagents = [s if s["name"] != "ats" else {**s, "model": ats_model} for s in subagents]

    agent = create_resume_agent(model=orchestrator_model, tools=[], subagents=subagents)

    events = list(iter_progress_events(
        agent,
        {"messages": [{"role": "user", "content": "Assess this candidate."}]},
        {"recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS},
    ))

    tool_calls = [e for e in events if e["kind"] == "tool_call"]
    assert any(e["team_member"] == "coordinator" and e["tool_name"] == "task" for e in tool_calls)
    assert any(e["team_member"] == "recruiter" and e["tool_name"] == "submit_assessment" for e in tool_calls)
    assert any(e["team_member"] == "ats" and e["tool_name"] == "submit_assessment" for e in tool_calls)

    results = [e for e in events if e["kind"] == "tool_result"]
    recruiter_result = next(e for e in results if e["team_member"] == "recruiter" and e["tool_name"] == "submit_assessment")
    ats_result = next(e for e in results if e["team_member"] == "ats" and e["tool_name"] == "submit_assessment")
    assert json.loads(recruiter_result["content"])["score"] == 80
    assert json.loads(ats_result["content"])["score"] == 65

    messages = [e for e in events if e["kind"] == "message"]
    assert any(e["team_member"] == "coordinator" and e["content"] == "Consulted both personas." for e in messages)
    assert any(e["team_member"] == "recruiter" and e["content"] == "Recruiter done." for e in messages)
    assert any(e["team_member"] == "ats" and e["content"] == "ATS done." for e in messages)
