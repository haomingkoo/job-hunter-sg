# backend/tests/test_open_agent_checkpoint_spike.py
#
# Spike for issue #112 / #113: does `deepagents.create_deep_agent(...,
# interrupt_on={...})` produce a real LangGraph interrupt that pauses
# execution before the next tool call runs, and does `Command(resume=...)`
# actually continue that same paused run? No code in this repo has ever used
# `interrupt_on` or a resume flow before, so this was genuinely unverified
# integration, not known-working reuse.
#
# `recruitment_team.open_agent.tools` (where `ask_candidate` permanently
# lives) did not exist when this spike was written -- it was created by
# Task 6, which depended on this spike's finding. `ask_candidate` was
# originally defined inline below, matching the exact shape Task 6's brief
# specifies (`{"ok": True, "question": question}`); Task 6 swapped in an
# import of the permanent tool for that inline definition, unchanged.
#
# The brief's illustrative test (docs/superpowers/plans task-2-brief.md) does
# not run as literally written -- two things about real `deepagents`/
# `langchain` behavior contradicted its assumptions, found by running it and
# reading `langchain/agents/middleware/human_in_the_loop.py`:
#
# CONFIRMED 2026-07-20 (1/2) -- `"__interrupt__"` really is the signal key,
# and it is a real pause, not a post-hoc filter: with `interrupt_on` unset,
# the scripted `ask_candidate` tool call executes for real and the run keeps
# going (proved by the RED run below, which hits `GraphRecursionError`
# instead of stopping). With `interrupt_on={"ask_candidate": True}` wired
# through `create_resume_agent`, `agent.invoke(...)` returns *before* the
# `ask_candidate` tool (or anything after it) executes:
# `result["__interrupt__"]` is a list of `langgraph.types.Interrupt`, whose
# `.value` is a `HITLRequest` (`{"action_requests": [...],
# "review_configs": [...]}`) built by `HumanInTheLoopMiddleware.after_model`
# -- i.e. the middleware calls `langgraph.types.interrupt(...)` from an
# `after_model` hook, which raises internally and unwinds the graph run
# before the `ToolNode` for that AIMessage's tool calls ever runs. No
# `ask_candidate` `ToolMessage` and no `propose_resume_edit` call appear in
# `result["messages"]` at this point.
#
# CONFIRMED 2026-07-20 (2/2) -- the brief's `Command(resume="12 engineers.")`
# (a bare string) does not match the real resume contract and raises
# `TypeError: string indices must be integers, not 'str'` inside
# `HumanInTheLoopMiddleware.after_model`, because that method does
# `interrupt(hitl_request)["decisions"]` on whatever value `resume=` carries.
# The real shape is `HITLResponse = {"decisions": list[Decision]}`, one
# `Decision` per interrupted tool call, in the same order. For an "ask the
# human, treat their reply as the tool's result" tool like `ask_candidate`,
# the right `Decision` is `RespondDecision`: `{"type": "respond", "message":
# "<candidate's answer>"}` -- this skips real execution of `ask_candidate`
# and injects a synthetic `ToolMessage` (`status="success"`, `name=
# "ask_candidate"`, `content=<message>`) in its place, which is exactly
# `ask_candidate`'s intended semantics (the tool's real "return value" is the
# human's answer). So: `agent.invoke(Command(resume={"decisions": [{"type":
# "respond", "message": "12 engineers."}]}), config=run_config)`. This
# resumed call is a real continuation of the paused run, not a fresh one: it
# reuses `run_config`'s `thread_id`, and the resumed `result["messages"]`
# contains the *original* pre-interrupt messages (the `HumanMessage` and the
# `ask_candidate`-calling `AIMessage`) plus everything that happened after
# resuming, proving LangGraph replayed from the checkpoint rather than
# starting over.
#
# Incidental finding while building this test: `FakeMessagesListChatModel`
# *cycles* back to `responses[0]` once its list is exhausted (see
# `langchain_core.language_models.fake_chat_models`), it does not repeat the
# last response forever. A 2-response script (`ask_candidate` call, then
# `propose_resume_edit` call) therefore loops back to another
# `ask_candidate` call after `propose_resume_edit` executes, triggering a
# second interrupt the test does not resume -- which manifests as
# `GraphRecursionError` on the *resumed* invoke, not a clean pass. A 3rd,
# non-tool-calling terminal response is required so the resumed run actually
# reaches a stop condition.
#
# No checkpointer-type requirement beyond "a checkpointer must be present":
# `interrupt()` needs somewhere to persist the pending interrupt across the
# pause, so an in-memory `MemorySaver` (used here, and in
# `resume_agent.session._get_checkpointer()`) is sufficient for this
# mechanism to work at all. It is not durable across a process restart --
# that is a separate, unaddressed concern for Task 9's runner, not something
# this spike tests.
from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from recruitment_team.open_agent.tools import ask_candidate
from resume_agent.agent import create_resume_agent


@tool
def propose_resume_edit(block_id: str, rewrite: str) -> dict:
    """Spike stand-in for the real `propose_resume_edit` tool (built in Task 5).

    Only used here so the scripted post-interrupt tool call has somewhere to
    land, proving the resumed graph reaches a further tool call. Not a
    functional implementation.
    """
    return {"block_id": block_id, "rewrite": rewrite}


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_ask_candidate_interrupts_before_any_further_tool_call(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    ask_call = AIMessage(
        content="",
        tool_calls=[{"name": "ask_candidate", "args": {"question": "How large was the team you led?"}, "id": "call-1"}],
    )
    would_be_next_call = AIMessage(
        content="",
        tool_calls=[{"name": "propose_resume_edit", "args": {"block_id": "b1", "rewrite": "Led a team of 12."}, "id": "call-2"}],
    )
    final_reply = AIMessage(content="Recorded the candidate's answer and proposed an edit.")
    model = _ScriptedModel(responses=[ask_call, would_be_next_call, final_reply])

    agent = create_resume_agent(
        model=model,
        tools=[ask_candidate, propose_resume_edit],
        subagents=[],
        checkpointer=MemorySaver(),
        interrupt_on={"ask_candidate": True},
    )
    run_config = {"configurable": {"thread_id": "spike-thread-1"}, "recursion_limit": 20}

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Assess this candidate."}]},
        config=run_config,
    )

    assert "__interrupt__" in result, (
        "expected create_deep_agent(interrupt_on={'ask_candidate': True}) to pause the graph; "
        "if this fails, read deepagents/middleware and langchain.agents.middleware.HumanInTheLoopMiddleware "
        "to find the actual signal key and fix this assertion to match reality"
    )
    executed_tool_messages = [m for m in result["messages"] if m.__class__.__name__ == "ToolMessage"]
    assert not executed_tool_messages, (
        "no tool -- not ask_candidate itself, not anything after it -- should have executed before the interrupt"
    )
    proposed_after = [m for m in result["messages"] if getattr(m, "name", None) == "propose_resume_edit"]
    assert not proposed_after, "no tool call after ask_candidate should have executed before the interrupt"

    resumed = agent.invoke(
        Command(resume={"decisions": [{"type": "respond", "message": "12 engineers."}]}),
        config=run_config,
    )
    assert resumed["messages"], "resuming with the candidate's answer must continue the graph"

    pre_interrupt_human = [m for m in resumed["messages"] if m.__class__.__name__ == "HumanMessage"]
    assert pre_interrupt_human and pre_interrupt_human[0].content == "Assess this candidate.", (
        "the resumed trace must still carry the original pre-interrupt message history, proving this "
        "is a real continuation of the paused run, not a fresh, unrelated invocation"
    )

    answer_messages = [m for m in resumed["messages"] if getattr(m, "name", None) == "ask_candidate"]
    assert answer_messages, "the synthesized ToolMessage answering ask_candidate must be in the resumed trace"
    assert answer_messages[0].content == "12 engineers.", (
        "the resumed run must carry the candidate's actual answer, not a placeholder"
    )

    proposed_after_resume = [m for m in resumed["messages"] if getattr(m, "name", None) == "propose_resume_edit"]
    assert proposed_after_resume, (
        "resuming must let the graph continue past the interrupt point into the next scripted tool call "
        "(propose_resume_edit) -- proving this is a real continuation that keeps executing, not just a "
        "no-op replay"
    )
