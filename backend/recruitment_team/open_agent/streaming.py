"""Real-time progress extraction from agent.stream(..., stream_mode="updates",
subgraphs=True).

Verified directly against the installed deepagents/langgraph/langchain
versions: a plain top-level stream (subgraphs=True omitted) only shows the
orchestrator's own node updates -- a delegated subagent's internal execution
is as invisible there as it is via .invoke(). Passing subgraphs=True
additionally yields items under a non-empty namespace tuple per active
subagent invocation (e.g. ("tools:<uuid>",)), carrying that subagent's own
model/tools node updates in real time -- including the AIMessage.name field
identifying which persona it is, and the real structured ToolMessage content
when that persona calls its own submission tool (not a paraphrase). This
module is the one place that knows this shape; nothing downstream should
re-derive it.

Confirmed 2026-07-20 with two sequential persona delegations (recruiter then
ats) in one run, not just one: each subagent invocation gets its own
namespace tuple, so `active_persona_by_namespace` never collides between
them -- the recruiter's and the ats persona's tool_call/tool_result/message
events are attributed correctly and independently, with their distinct
submit_assessment scores (80 vs 65) intact. The single-persona shape holds
unchanged for the two-persona case."""

from __future__ import annotations

from typing import Any, Iterator


def iter_progress_events(agent: Any, payload: Any, run_config: dict) -> Iterator[dict]:
    """Yield one normalized event per meaningful message anywhere in the run,
    at the top level (team_member="coordinator") or inside a delegated
    persona subagent (team_member=<persona_id>, learned from that subagent's
    own AIMessage.name the first time it's seen in that subgraph's
    namespace). Three event kinds: "tool_call" (a model decided to call a
    tool), "tool_result" (a tool's return value, structured JSON when the
    tool is a schema-enforced submission), "message" (a plain final reply
    with no tool call -- how a turn, the orchestrator's or a persona
    subagent's own, naturally ends; the last coordinator-level one of these
    is the run's synthesis text)."""
    active_persona_by_namespace: dict[tuple, str] = {}

    for namespace, chunk in agent.stream(
        payload, config=run_config, stream_mode="updates", subgraphs=True
    ):
        for node_update in (chunk or {}).values():
            if not isinstance(node_update, dict):
                continue
            for message in node_update.get("messages", []) or []:
                persona_name = getattr(message, "name", None)
                tool_calls = getattr(message, "tool_calls", None) or []
                if tool_calls:
                    if persona_name:
                        active_persona_by_namespace[namespace] = persona_name
                    team_member = active_persona_by_namespace.get(namespace, "coordinator")
                    for call in tool_calls:
                        yield {
                            "kind": "tool_call",
                            "team_member": team_member,
                            "tool_name": call.get("name"),
                            "args": call.get("args"),
                        }
                elif hasattr(message, "tool_call_id"):
                    team_member = active_persona_by_namespace.get(namespace, "coordinator")
                    yield {
                        "kind": "tool_result",
                        "team_member": team_member,
                        "tool_name": getattr(message, "name", None),
                        "content": message.content,
                    }
                elif message.content:
                    # A plain final reply with no tool call -- this is how a
                    # turn (the orchestrator's or a persona subagent's own)
                    # naturally ends. The runner needs the LAST coordinator-
                    # level one of these as its synthesis text; without this
                    # branch it would never see it at all.
                    team_member = active_persona_by_namespace.get(namespace, "coordinator")
                    yield {
                        "kind": "message",
                        "team_member": team_member,
                        "content": message.content,
                    }
