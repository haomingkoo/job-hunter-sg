"""Deep-agent factory and turn helpers."""

from __future__ import annotations

from typing import Any, Sequence

from .models import create_fast_model
from .tools import extract_skills, get_job, propose_edit, score_resume, search_jobs


SYSTEM_PROMPT = """You are Resume Agent v2 for Job Hunter SG.

Tailor or strengthen resumes using only grounded information from the user's
resume and the internal jobs database. Never invent employers, dates, skills, or
metrics. Use tools when job context is needed.
"""

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
        subagents=list(subagents) if subagents is not None else [],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )


def run_agent_turn(agent: Any, message: str) -> dict:
    """Run one synchronous agent turn."""
    return agent.invoke({"messages": [{"role": "user", "content": message}]})
