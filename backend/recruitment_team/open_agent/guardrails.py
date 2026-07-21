"""Efficiency guardrails: freedom limits are about volume, not choice.

These stop the specific failure mode this codebase already measured once
(wasted, duplicate, non-progressing calls) -- they never restrict which tool
or persona the orchestrator is allowed to pick."""

from __future__ import annotations

from typing import Any


def has_repeated_call(messages: list[Any], tool_name: str, args: dict[str, Any]) -> bool:
    """True if any AIMessage in `messages` already called `tool_name` with
    materially identical args.

    Scans the full list backward for the first match, oldest and newest
    calls alike -- it has no turn-boundary or staleness awareness. Callers
    are responsible for passing only the relevant message window (e.g. only
    messages since the last human turn) if a repeat should be allowed once
    new information has arrived."""
    for message in reversed(messages):
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            if call.get("name") == tool_name and call.get("args") == args:
                return True
    return False
