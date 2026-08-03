"""Normalize top-level and delegated agent progress events."""

from __future__ import annotations

import json
from typing import Any, Iterator


def iter_progress_events(
    agent: Any,
    payload: Any,
    run_config: dict,
    *,
    skip_tool_call_ids: set[str] | None = None,
) -> Iterator[dict]:
    """Yield normalized tool and message events, skipping replayed calls."""
    active_persona_by_namespace: dict[tuple, str] = {}
    pending_skip_ids = set(skip_tool_call_ids or ())

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
                        call_id = call.get("id")
                        if call_id is not None and call_id in pending_skip_ids:
                            pending_skip_ids.discard(call_id)
                            continue
                        yield {
                            "kind": "tool_call",
                            "team_member": team_member,
                            "tool_name": call.get("name"),
                            "args": call.get("args"),
                            "id": call_id,
                        }
                elif hasattr(message, "tool_call_id"):
                    team_member = active_persona_by_namespace.get(namespace, "coordinator")
                    yield {
                        "kind": "tool_result",
                        "team_member": team_member,
                        "tool_name": getattr(message, "name", None),
                        "content": message.content,
                        "id": getattr(message, "tool_call_id", None),
                    }
                elif message.content:
                    # Without this branch the runner would never see its
                    # synthesis text -- the last coordinator-level plain reply.
                    team_member = active_persona_by_namespace.get(namespace, "coordinator")
                    yield {
                        "kind": "message",
                        "team_member": team_member,
                        "content": message.content,
                    }


# Text long enough to fill the activity panel is text the candidate cannot read
# anyway. Gate messages and discovery failure reasons have no length bound.
MAX_ACTIVITY_TEXT_CHARS = 120


def _clip(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_ACTIVITY_TEXT_CHARS else text[: MAX_ACTIVITY_TEXT_CHARS - 1] + "…"


def describe_progress(event: dict) -> tuple[str, dict] | None:
    """Build safe candidate-facing progress from one normalized event."""
    tool_name = event.get("tool_name")
    if not tool_name:
        return None
    team_member = event.get("team_member") or "coordinator"

    if event.get("kind") == "tool_call":
        # `{member} called {tool}.` is the shape TeamActivityPanel's humanize()
        # parses, and the shape the #146 activity assertions pin.
        detail = {"tool_name": tool_name, "stage": "call"}
        query = (event.get("args") or {}).get("query")
        if isinstance(query, str) and query.strip():
            detail["query"] = _clip(query)
        if event.get("id"):
            detail["tool_call_id"] = event["id"]
        return f"{team_member} called {tool_name}.", detail

    if event.get("kind") == "tool_result":
        outcome = _outcome(tool_name, event.get("content"))
        if outcome is None:
            return None
        detail = {"tool_name": tool_name, "stage": "result", "outcome": _clip(outcome)}
        if event.get("id"):
            detail["tool_call_id"] = event["id"]
        payload = _payload(event.get("content"))
        found = _postings_found(payload) if isinstance(payload, dict) else None
        if found is not None:
            detail["result_count"] = found
        return (
            f"{team_member} finished {tool_name}.",
            detail,
        )

    return None


def _outcome(tool_name: str, content: Any) -> str | None:
    """Summarize a useful tool result without exposing raw content."""
    payload = _payload(content)
    if not isinstance(payload, dict):
        return None

    if payload.get("ok") is False:
        reason = payload.get("reason") or payload.get("failure_type") or "unavailable"
        return f"nothing returned ({str(reason).replace('_', ' ')})"

    # read_shortlist is the only tool that reports both lists, and reporting one
    # of them would be a half-truth.
    recommended = payload.get("recommendations")
    shortlisted = payload.get("shortlisted_jobs")
    if isinstance(recommended, list) and isinstance(shortlisted, list):
        return f"{len(recommended)} found earlier, {len(shortlisted)} shortlisted"

    found = _postings_found(payload)
    if found is not None:
        return f"{found} matching {'posting' if found == 1 else 'postings'}"

    published_job_ids = payload.get("published_job_ids")
    if tool_name == "write_shortlist" and isinstance(published_job_ids, list):
        count = len(published_job_ids)
        return f"{count} {'role' if count == 1 else 'roles'} ranked with resume evidence"

    recorded = payload.get("recorded")
    if tool_name == "record_preferences" and isinstance(recorded, int):
        return f"{recorded} {'preference' if recorded == 1 else 'preferences'} recorded"
    if tool_name == "record_candidate_evidence" and isinstance(recorded, int):
        return f"{recorded} candidate {'fact' if recorded == 1 else 'facts'} confirmed"
    if tool_name == "write_plan" and isinstance(recorded, int):
        action = "unchanged" if payload.get("changed") is False else "updated"
        return f"plan {action} with {recorded} {'step' if recorded == 1 else 'steps'}"

    if tool_name == "propose_resume_edit" and payload.get("accepted") is True:
        return "one resume edit drafted, waiting on your approval"
    if tool_name == "propose_resume_edit" and payload.get("accepted") is False:
        return f"no edit drafted ({payload.get('reason') or 'rejected'})"

    return None


def _payload(content: Any) -> Any:
    payload = content
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    return payload


def _postings_found(payload: dict) -> int | None:
    """How many postings a search returned, across both search tools' shapes.

    `agent_tool_contract.search_jobs_result` reports a count and `results`; the
    coordinator's own search tool reports `jobs`.
    """
    for key in ("result_count", "count"):
        if isinstance(payload.get(key), int):
            return payload[key]
    for key in ("jobs", "results"):
        if isinstance(payload.get(key), list):
            return len(payload[key])
    return None


def format_questions(args: dict) -> str:
    """One pause can carry several questions, so render them as one message."""
    questions = args.get("questions")
    if isinstance(questions, str):
        questions = [questions]
    questions = [str(item).strip() for item in (questions or []) if str(item).strip()]
    if not questions:
        return ""
    if len(questions) == 1:
        return questions[0]
    return "\n".join(f"{index}. {question}" for index, question in enumerate(questions, 1))
