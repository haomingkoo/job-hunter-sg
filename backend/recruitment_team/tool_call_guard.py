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
COMPLETED_SPECIALIST_REASON = (
    "specialist_already_completed_no_new_evidence: this reviewer already returned an "
    "accepted report and no candidate answer has changed the evidence. Use the accepted "
    "report instead of running the same reviewer again."
)
_specialist_slots = threading.BoundedSemaphore(
    config.RECRUITMENT_MAX_CONCURRENT_SPECIALISTS
)
_STATE_DEPENDENT_RETRY_TOOLS = frozenset({"submit_target_assessment_synthesis"})
_HIDE_AFTER_ACCEPTED_TOOLS = frozenset({
    "read_candidate_evidence",
    "read_shortlist",
    "read_target_job",
})


def _fingerprint(name: str, args: dict[str, Any]) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


def _accepted_result(result: Any) -> bool:
    payload = result
    if isinstance(result, ToolMessage):
        try:
            payload = json.loads(str(result.content))
        except (TypeError, ValueError):
            return False
    return isinstance(payload, dict) and (
        payload.get("accepted") is True or payload.get("ok") is True
    )


def _remaining_specialist_guidance(persona_ids: tuple[str, ...]) -> dict[str, Any]:
    if not persona_ids:
        return {}
    return {
        "missing_required_specialists": list(persona_ids),
        "next_action": (
            "Delegate one of the remaining required specialists: "
            + ", ".join(persona_ids)
            + "."
        ),
    }


class ToolCallGuardMiddleware(AgentMiddleware):
    """Reject identical calls within one candidate turn.

    A fresh instance per turn means new candidate information permits a formerly
    repeated call. The middleware does not prescribe tool order or availability.
    """

    def __init__(
        self,
        allowed_tools: set[str] | None = None,
        *,
        enforce_fresh_specialists: bool = False,
    ) -> None:
        super().__init__()
        self._allowed_tools = frozenset(allowed_tools) if allowed_tools is not None else None
        self._enforce_fresh_specialists = enforce_fresh_specialists
        self._seen: set[str] = set()
        self._hidden_tools: set[str] = set()
        self._seen_lock = threading.Lock()

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        """Remove exhausted no-argument reads from the next model decision."""
        with self._seen_lock:
            exhausted = frozenset(self._hidden_tools)
        if not exhausted:
            return handler(request)
        tools = [
            available_tool
            for available_tool in (getattr(request, "tools", None) or [])
            if getattr(available_tool, "name", "") not in exhausted
        ]
        return handler(request.override(tools=tools))

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        call = getattr(request, "tool_call", None) or {}
        name = call.get("name") or ""
        args = call.get("args") or {}
        if self._allowed_tools is not None and name not in self._allowed_tools:
            return ToolMessage(
                content=json.dumps(
                    {
                        "ok": False,
                        "failure_type": "validation",
                        "reason": "tool_not_available_for_this_workflow",
                        "retry": False,
                    }
                ),
                tool_call_id=call.get("id", ""),
                name=name,
            )
        if name == "task" and self._enforce_fresh_specialists:
            # Import lazily: the conversation graph also uses this guard, and
            # importing the assessment context at module load would create a
            # cycle through the open-agent runner.
            from .open_agent import context

            persona_id = str(args.get("subagent_type") or "").strip()
            missing_specialists = context.missing_required_specialists()
            missing = set(missing_specialists)
            if (
                persona_id
                and persona_id not in missing
                and not context.completed_specialist_revisit_allowed()
            ):
                # A rejected revisit exhausts this persona, not the delegation
                # capability. Other required reviewers must remain reachable.
                if not missing_specialists:
                    with self._seen_lock:
                        self._hidden_tools.add("task")
                return ToolMessage(
                    content=json.dumps({
                        "ok": False,
                        "accepted": False,
                        "failure_type": "validation",
                        "reason": COMPLETED_SPECIALIST_REASON,
                        "retry": False,
                        **_remaining_specialist_guidance(missing_specialists),
                    }),
                    tool_call_id=call.get("id", ""),
                    name=name,
                )
        fingerprint = _fingerprint(name, args)
        with self._seen_lock:
            repeated = fingerprint in self._seen
            self._seen.add(fingerprint)
        if repeated and name not in _STATE_DEPENDENT_RETRY_TOOLS:
            # A model that ignored the rejection guidance once is likely to
            # loop on the same tool. Hide it for the remainder of this turn;
            # a new middleware instance restores it on the next user turn.
            keep_task_available = (
                name == "task"
                and self._enforce_fresh_specialists
                and bool(missing_specialists)
            )
            if not keep_task_available:
                with self._seen_lock:
                    self._hidden_tools.add(name)
            return ToolMessage(
                content=json.dumps(
                    {
                        "ok": False,
                        "failure_type": "validation",
                        "reason": REPEATED_CALL_REASON,
                        "retry": False,
                        **(
                            _remaining_specialist_guidance(missing_specialists)
                            if name == "task" and self._enforce_fresh_specialists
                            else {}
                        ),
                    }
                ),
                tool_call_id=call.get("id", ""),
                name=name,
            )
        if name == "task":
            _specialist_slots.acquire()
            try:
                result = handler(request)
            finally:
                _specialist_slots.release()
        else:
            result = handler(request)
        if name in _HIDE_AFTER_ACCEPTED_TOOLS and _accepted_result(result):
            with self._seen_lock:
                self._hidden_tools.add(name)
        return result
