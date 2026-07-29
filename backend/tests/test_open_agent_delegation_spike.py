# Pins one third-party behaviour production depends on: a persona subagent's
# step budget is *separate* from the top-level `recursion_limit` the runner
# passes to `agent.invoke()` (`config.AGENT_MAX_TOOL_ITERATIONS`, see
# `recruitment_team/open_agent/runner.py`), not shared or inherited. Every
# graph compiled by `langchain.agents.create_agent` (which is what
# `create_sub_agent()` uses for persona subagents) is bound via
# `.with_config({"recursion_limit": 9_999})` (see `langchain/agents/
# factory.py`, referencing langgraph#7313) -- and the `task` tool invokes the
# subagent with a config that carries no `recursion_limit` key
# (`{"configurable": {"ls_agent_type": "subagent"}}`), so nothing overrides
# that bound 9_999. Consequence for guardrail design: bounding the
# orchestrator's `recursion_limit` does **not** bound how many internal steps
# a delegated persona can take. If a langchain upgrade changes this, the
# runner's own cap silently starts throttling personas -- this test is the
# only place that would notice.
#
# Note on the assertions below: a persona's own messages (its AIMessage/
# ToolMessage pairs, including any `submit_assessment` ToolMessage) never
# surface in the parent's `result["messages"]`. Per
# `SubAgentMiddleware._build_task_tool`'s `_return_command_with_state_update`,
# only a *single* synthesized `ToolMessage` is appended to the parent trace,
# with `name` forced to `"task"` (langgraph's `ToolNode` sets
# `message.name = call["name"]` for any `Command`-returned `ToolMessage`
# matching the calling `tool_call_id`) and `content` set to the subagent's
# last non-empty `AIMessage` text. So the matchable signal is a `ToolMessage`
# named `"task"`, and proving the persona's tool really ran needs a spy on the
# underlying function object.
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

    Schema-invalid args would fail pydantic validation inside the persona
    subagent's own `ToolNode`, the underlying Python function would never be
    called, and the error would be silently absorbed into the persona's own
    internal message history -- invisible to a fake model that doesn't read
    tool output. Using schema-valid args here is what lets the spy assertions
    below prove real execution rather than a swallowed validation error.
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
