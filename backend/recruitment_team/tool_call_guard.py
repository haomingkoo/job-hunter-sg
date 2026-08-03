"""Reject duplicate tool calls without restricting tool choice."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

import config

REPEATED_CALL_REASON = (
    "identical_call_no_new_information: this exact call was already made in this "
    "turn and returned the same result. Do not repeat it. Either act on what you "
    "already have, call a different tool, or reply to the candidate."
)
_specialist_slots = threading.BoundedSemaphore(
    config.RECRUITMENT_MAX_CONCURRENT_SPECIALISTS
)


def _fingerprint(name: str, args: dict[str, Any]) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


class ToolCallGuardMiddleware(AgentMiddleware):
    """Reject identical calls within one candidate turn.

    A fresh instance per turn means new candidate information permits a formerly
    repeated call. The middleware does not prescribe tool order or availability.
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
                    {
                        "ok": False,
                        "failure_type": "validation",
                        "reason": REPEATED_CALL_REASON,
                        "retry": False,
                    }
                ),
                tool_call_id=call.get("id", ""),
                name=name,
            )
        self._seen.add(fingerprint)
        if name != "task":
            return handler(request)
        _specialist_slots.acquire()
        try:
            return handler(request)
        finally:
            _specialist_slots.release()
