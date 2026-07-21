# backend/tests/test_open_agent_delegation_spike.py
#
# Spike for issue #110: does deepagents' `task`-based subagent delegation
# (the mechanism `create_persona_subagents()` is built for) actually work?
# The only production call site (`resume_agent/session.py`) has always passed
# `subagents=[]`, so this had never been exercised end-to-end before this file.
#
# The brief's illustrative script (docs/superpowers/plans task-1-brief.md) does
# not run as literally written -- three things about real `deepagents`/
# `langchain` behavior contradicted its assumptions, found by running it and
# reading `deepagents/middleware/subagents.py` + `langchain/agents/factory.py`:
#
# CONFIRMED 2026-07-20 (1/3) -- delegation itself works: `task(subagent_type=
# "recruiter", ...)` resolves the subagent by `SubAgent["name"]` and really
# invokes the compiled persona graph (its own `submit_assessment` tool
# function executes for real -- verified below by spying on the underlying
# function object).
#
# CONFIRMED 2026-07-20 (2/3) -- but the persona's own messages (its
# AIMessage/ToolMessage pairs, including any `submit_assessment` ToolMessage)
# never surface in the parent's `result["messages"]`. Per
# `SubAgentMiddleware._build_task_tool`'s `_return_command_with_state_update`,
# only a *single* synthesized `ToolMessage` is appended to the parent trace:
# `name` is forced to `"task"` (langgraph's `ToolNode` sets
# `message.name = call["name"]` for any `Command`-returned `ToolMessage`
# matching the calling `tool_call_id` -- see
# `langgraph/prebuilt/tool_node.py`), and `content` is the subagent's last
# non-empty `AIMessage` text (or its `structured_response` if one is
# configured -- persona subagents here have none). So the brief's proposed
# assertion (`getattr(m, "name", None) == "submit_assessment"`) can never
# match; the real, matchable signal is a `ToolMessage` named `"task"`.
#
# CONFIRMED 2026-07-20 (3/3) -- a persona subagent's own step budget is
# *separate* from the top-level `recursion_limit` passed to `agent.invoke()`,
# not shared/inherited. Every graph compiled by `langchain.agents.create_agent`
# (which is what `create_sub_agent()` uses for persona subagents) is bound via
# `.with_config({"recursion_limit": 9_999})` (see
# `langchain/agents/factory.py`, referencing langgraph#7313) -- and the `task`
# tool invokes the subagent with a config that carries no `recursion_limit`
# key (`{"configurable": {"ls_agent_type": "subagent"}}`), so nothing
# overrides that bound 9_999. First observed accidentally: the brief's literal
# persona script has only one scripted response, and `FakeMessagesListChatModel`
# cycles back to that same tool-calling response forever once exhausted, so
# the persona looped until it hit "Recursion limit of 9999" -- not the
# `recursion_limit=20` (`config.AGENT_MAX_TOOL_ITERATIONS`) passed to the
# *top-level* `agent.invoke()` call. Reproduced deliberately below: a
# top-level `recursion_limit=8` (empirically the minimum required for the
# orchestrator's own single delegate-call round trip is 7, given today's
# deepagents/langchain middleware stack) is nowhere near enough budget for a
# persona needing 3 of its own model calls *if that budget were shared* --
# yet the persona completes both of its `submit_assessment` calls without
# incident, because it draws from its own independent 9_999, not the parent's
# 8. This matters for Task 8's guardrail design: bounding the orchestrator's
# `recursion_limit` does **not** bound how many internal steps a delegated
# persona can take.
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from resume_agent.agent import create_resume_agent


class _ScriptedOrchestratorModel(FakeMessagesListChatModel):
    """Always delegates to the 'recruiter' subagent via the `task` tool, then stops."""

    def bind_tools(self, tools, **kwargs):
        return self


def _delegate_call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "task",
            "args": {
                "description": "Review this candidate as the recruiter persona.",
                "subagent_type": "recruiter",
            },
            "id": "call-1",
        }],
    )


def _valid_assessment_args(summary: str) -> dict[str, Any]:
    """Args matching the real `_AssessmentSubmission` schema.

    The brief's illustrative `{"strength": ..., "gap": ..., "score": ...}`
    payload does not match `resume_agent.personas._AssessmentSubmission`
    (which requires `summary`/`category`/`findings`/`reasoning`/
    `suggested_actions`). With the mismatched payload, `submit_assessment`
    fails pydantic validation inside the persona subagent's own `ToolNode`
    and the underlying Python function is never actually called -- the
    error is silently absorbed into the persona's own internal message
    history, invisible to a fake model that doesn't read tool output. Using
    schema-valid args here is what lets the spy assertions below prove real
    execution rather than a swallowed validation error.
    """
    return {
        "summary": summary,
        "category": "ownership",
        "findings": [
            {
                "kind": "strength",
                "finding": "Shipped a feature end-to-end.",
                "source": "resume",
                "source_location": "bullet-1",
                "method": "Read the bullet describing feature delivery.",
                "relevance_score": 0.8,
            },
            {
                "kind": "weakness",
                "finding": "No quantified impact metric given.",
                "source": "resume",
                "source_location": "bullet-1",
                "method": "Checked the bullet for numeric outcomes.",
                "relevance_score": 0.5,
            },
        ],
        "score": 80,
        "reasoning": "Ownership is clear but impact isn't quantified.",
        "suggested_actions": ["Add a quantified outcome metric."],
    }


def _submit_assessment_call(call_id: str, summary: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_assessment",
            "args": _valid_assessment_args(summary),
            "id": call_id,
        }],
    )


def test_orchestrator_can_delegate_to_a_real_persona_subagent(monkeypatch):
    import config
    import resume_agent.models as agent_models
    import resume_agent.personas as personas

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    # Spy on the real submit_assessment function (bound into the tool at
    # module load) to prove the persona subagent actually executed it,
    # since -- per the finding above -- its ToolMessage never reaches the
    # parent's result["messages"].
    submitted_calls: list[dict] = []
    original_submit = personas._SUBMIT_ASSESSMENT_TOOL.func

    def _spy_submit(**payload):
        submitted_calls.append(payload)
        return original_submit(**payload)

    monkeypatch.setattr(personas._SUBMIT_ASSESSMENT_TOOL, "func", _spy_submit)

    final_reply = AIMessage(content="Delegated to recruiter; no further action needed.")
    orchestrator_model = _ScriptedOrchestratorModel(responses=[_delegate_call(), final_reply])

    persona_final = AIMessage(content="Recruiter assessment complete.")
    persona_model = _ScriptedOrchestratorModel(
        responses=[_submit_assessment_call("call-2", "Clear ownership of a shipped feature."), persona_final]
    )

    subagents = personas.create_persona_subagents(smart_model=persona_model)
    agent = create_resume_agent(model=orchestrator_model, tools=[], subagents=subagents)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Assess this candidate against the target role."}]},
        config={"recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS},
    )

    assert len(submitted_calls) == 1, "the recruiter subagent's own submit_assessment function must run for real"
    assert submitted_calls[0]["summary"] == "Clear ownership of a shipped feature."

    task_messages = [m for m in result["messages"] if getattr(m, "name", None) == "task"]
    assert task_messages, "the parent trace must show a completed `task` delegation"
    assert task_messages[0].content == "Recruiter assessment complete."


def test_persona_subagent_recursion_budget_is_independent_of_parent_limit(monkeypatch):
    """A persona needing 3 internal model calls completes under a top-level
    `recursion_limit` too tight to cover that -- if the budget were shared."""
    import resume_agent.models as agent_models
    import resume_agent.personas as personas

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    submitted_calls: list[dict] = []
    original_submit = personas._SUBMIT_ASSESSMENT_TOOL.func

    def _spy_submit(**payload):
        submitted_calls.append(payload)
        return original_submit(**payload)

    monkeypatch.setattr(personas._SUBMIT_ASSESSMENT_TOOL, "func", _spy_submit)

    final_reply = AIMessage(content="Delegated to recruiter; no further action needed.")
    orchestrator_model = _ScriptedOrchestratorModel(responses=[_delegate_call(), final_reply])

    # 3 internal model calls to complete: two rounds of submit_assessment,
    # then a final non-tool-calling reply.
    persona_final = AIMessage(content="Recruiter assessment complete after 3 internal steps.")
    persona_model = _ScriptedOrchestratorModel(
        responses=[
            _submit_assessment_call("call-a", "Round 1 finding."),
            _submit_assessment_call("call-b", "Round 2 finding."),
            persona_final,
        ]
    )

    subagents = personas.create_persona_subagents(smart_model=persona_model)
    agent = create_resume_agent(model=orchestrator_model, tools=[], subagents=subagents)

    # 8 is empirically 1 step above the minimum (7) the orchestrator's own
    # graph needs for a single delegate-call round trip on today's
    # deepagents/langchain middleware stack -- i.e. it has ~zero slack to
    # also cover the persona's own internal steps. If the persona's budget
    # were drawn from this same limit, it could not complete 3 of its own
    # model calls on top of the orchestrator's own overhead, and this
    # `invoke()` would raise `GraphRecursionError`.
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Assess this candidate against the target role."}]},
        config={"recursion_limit": 8},
    )

    assert len(submitted_calls) == 2, "the persona must complete both of its own internal tool calls"
    task_messages = [m for m in result["messages"] if getattr(m, "name", None) == "task"]
    assert task_messages
    assert task_messages[0].content == "Recruiter assessment complete after 3 internal steps."
