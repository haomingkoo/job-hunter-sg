"""Deep-agent factory and turn helpers."""

from __future__ import annotations

from typing import Any, Callable, Sequence

import config as app_config
from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphRecursionError

from .models import create_agent_model
from .prompts import ORCHESTRATOR_SYSTEM_PROMPT


# DeepAgents adds a general-purpose subagent plus planning, filesystem (including
# delete) and shell tools to every graph, and new releases add more. Job Hunter
# supplies its own named personas and domain tools, so the graph is limited to an
# explicit allowlist instead of a denylist that each upgrade can outgrow.
register_harness_profile(
    "openai",
    HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ),
)


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        name = tool.get("name")
    else:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
    return name if isinstance(name, str) else None


class ToolAllowlistMiddleware(AgentMiddleware):
    """Expose and execute only the tools the caller declared."""

    def __init__(self, allowed: frozenset[str]) -> None:
        super().__init__()
        self.allowed = allowed

    def _filter(self, request: Any) -> Any:
        return request.override(
            tools=[tool for tool in request.tools if _tool_name(tool) in self.allowed]
        )

    def _refusal(self, request: Any) -> ToolMessage | None:
        call = request.tool_call
        if call.get("name") in self.allowed:
            return None
        return ToolMessage(
            content="tool_not_available_for_this_workflow",
            tool_call_id=call.get("id", ""),
            name=call.get("name"),
            status="error",
        )

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(self._filter(request))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return await handler(self._filter(request))

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return self._refusal(request) or handler(request)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return self._refusal(request) or await handler(request)


def create_resume_agent(
    *,
    tools: Sequence[Any],
    subagents: Sequence[SubAgent | CompiledSubAgent],
    model: Any | None = None,
    checkpointer: Any | None = None,
    interrupt_on: dict[str, Any] | None = None,
    system_prompt: str | None = None,
    response_format: Any | None = None,
    middleware: Sequence[Any] = (),
):
    """Create a deep-agent graph.

    `system_prompt` and `response_format` are pass-throughs with defaults, so
    the Resume Deep Agent v2 and the target-assessment runner are unaffected.
    They exist because a second orchestrator (the conversational coordinator)
    has a different goal statement and terminates on a structured submission
    rather than on a plain final message.
    """
    from deepagents import create_deep_agent

    allowed = frozenset(name for tool in tools if (name := _tool_name(tool)))
    if subagents:
        allowed |= {"task"}
    return create_deep_agent(
        model=model or create_agent_model(),
        tools=list(tools),
        subagents=list(subagents),
        system_prompt=system_prompt if system_prompt is not None else ORCHESTRATOR_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        interrupt_on=interrupt_on,
        response_format=response_format,
        middleware=[ToolAllowlistMiddleware(allowed), *middleware],
    )


def run_agent_turn(
    agent: Any,
    message: str,
    session_id: str | None = None,
    callbacks: list[Any] | None = None,
) -> dict:
    """Run one synchronous agent turn."""
    payload = {"messages": [{"role": "user", "content": message}]}
    run_config: dict[str, Any] = {
        "recursion_limit": app_config.AGENT_MAX_TOOL_ITERATIONS,
    }
    if session_id:
        run_config["configurable"] = {"thread_id": session_id}
    if callbacks:
        run_config["callbacks"] = callbacks
    try:
        return agent.invoke(payload, config=run_config)
    except GraphRecursionError:
        return {
            "messages": [],
            "stopped": True,
            "reason": "tool_iteration_cap",
        }
