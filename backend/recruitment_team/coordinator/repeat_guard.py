"""Refuse a tool call that repeats one already made this turn.

`has_repeated_call` existed but was invoked by two tools by name, so every other
tool could be called without limit. Live on 2026-08-02 the coordinator wrote the
same eleven-item todo list eleven times and died on the iteration cap.

A guard applied per tool is a special case. This applies to all of them, which is
what "guardrails limit volume, never choice" already claimed: the agent still picks
any tool in any order, it just cannot ask the same question twice and expect a
different answer.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

REPEATED_CALL_REASON = (
    "identical_call_no_new_information: this exact call was already made in this "
    "turn and returned the same result. Do not repeat it. Either act on what you "
    "already have, call a different tool, or reply to the candidate."
)


def _fingerprint(name: str, args: dict[str, Any]) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


class RepeatedCallMiddleware(AgentMiddleware):
    """One refusal per repeated call, with a reason the model can act on.

    Scoped to a single turn: a fresh instance per agent build, so a question
    worth asking again after the candidate replies is not blocked forever.
    """

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[str] = set()

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        call = getattr(request, "tool_call", None) or {}
        name = call.get("name") or ""
        args = call.get("args") or {}
        fingerprint = _fingerprint(name, args)
        if fingerprint in self._seen:
            return ToolMessage(
                content=json.dumps(
                    {"ok": False, "failure_type": "validation", "reason": REPEATED_CALL_REASON, "retry": False}
                ),
                tool_call_id=call.get("id", ""),
                name=name,
            )
        self._seen.add(fingerprint)
        return handler(request)
