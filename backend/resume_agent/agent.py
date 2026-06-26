"""Deep-agent factory and turn helpers."""

from __future__ import annotations

from typing import Any, Sequence

import config as app_config
from langgraph.errors import GraphRecursionError

from .models import create_fast_model
from .personas import create_persona_subagents
from .prompts import ORCHESTRATOR_SYSTEM_PROMPT
from .tools import extract_skills, get_job, propose_edit, score_resume, search_jobs


DEFAULT_TOOLS = [search_jobs, get_job, score_resume, extract_skills, propose_edit]


def create_resume_agent(
    model: Any | None = None,
    tools: Sequence[Any] | None = None,
    subagents: Sequence[dict] | None = None,
    checkpointer: Any | None = None,
):
    """Create the Resume Deep Agent graph."""
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=model or create_fast_model(),
        tools=list(tools) if tools is not None else DEFAULT_TOOLS,
        subagents=list(subagents) if subagents is not None else create_persona_subagents(),
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


def run_agent_turn(agent: Any, message: str, session_id: str | None = None) -> dict:
    """Run one synchronous agent turn."""
    payload = {"messages": [{"role": "user", "content": message}]}
    run_config: dict[str, Any] = {
        "recursion_limit": app_config.AGENT_MAX_TOOL_ITERATIONS,
    }
    if session_id:
        run_config["configurable"] = {"thread_id": session_id}
    try:
        return agent.invoke(payload, config=run_config)
    except GraphRecursionError:
        return {
            "messages": [],
            "stopped": True,
            "reason": "tool_iteration_cap",
        }
