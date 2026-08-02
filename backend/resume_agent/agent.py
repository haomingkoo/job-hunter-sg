"""Deep-agent factory and turn helpers."""

from __future__ import annotations

from typing import Any, Sequence

import config as app_config
from deepagents.middleware.subagents import SubAgent
from langgraph.errors import GraphRecursionError

from .models import create_agent_model
from .personas import create_persona_subagents
from .prompts import ORCHESTRATOR_SYSTEM_PROMPT
from .tooling import ORCHESTRATOR_TOOLS


DEFAULT_TOOLS = list(ORCHESTRATOR_TOOLS)


def create_resume_agent(
    model: Any | None = None,
    tools: Sequence[Any] | None = None,
    subagents: Sequence[SubAgent] | None = None,
    checkpointer: Any | None = None,
    interrupt_on: dict[str, Any] | None = None,
    system_prompt: str | None = None,
    response_format: Any | None = None,
):
    """Create a deep-agent graph.

    `system_prompt` and `response_format` are pass-throughs with defaults, so
    the Resume Deep Agent v2 and the target-assessment runner are unaffected.
    They exist because a second orchestrator (the conversational coordinator)
    has a different goal statement and terminates on a structured submission
    rather than on a plain final message.
    """
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=model or create_agent_model(),
        tools=list(tools) if tools is not None else DEFAULT_TOOLS,
        subagents=list(subagents) if subagents is not None else create_persona_subagents(),
        system_prompt=system_prompt if system_prompt is not None else ORCHESTRATOR_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        interrupt_on=interrupt_on,
        response_format=response_format,
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
