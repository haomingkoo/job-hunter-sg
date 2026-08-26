"""Normalize top-level and delegated agent progress events."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
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
    model_attempts_by_member: dict[str, int] = {}
    pending_skip_ids = set(skip_tool_call_ids or ())

    for namespace, chunk in agent.stream(payload, config=run_config, stream_mode="updates", subgraphs=True):
        for node_update in (chunk or {}).values():
            if not isinstance(node_update, dict):
                continue
            for message in node_update.get("messages", []) or []:
                persona_name = getattr(message, "name", None)
                usage = getattr(message, "usage_metadata", None) or {}
                response_metadata = getattr(message, "response_metadata", None) or {}
                model_name = str(response_metadata.get("model_name") or response_metadata.get("model") or "")
                if usage or model_name:
                    team_member = active_persona_by_namespace.get(namespace, persona_name or "coordinator")
                    model_attempts_by_member[team_member] = model_attempts_by_member.get(team_member, 0) + 1
                    yield {
                        "kind": "model_attempt",
                        "team_member": team_member,
                        "id": getattr(message, "id", None),
                        "attempt": model_attempts_by_member[team_member],
                        "model": model_name,
                        "input_tokens": int(usage.get("input_tokens") or 0),
                        "output_tokens": int(usage.get("output_tokens") or 0),
                    }
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


def describe_progress(event: dict) -> tuple[str, dict] | None:
    """Build safe candidate-facing progress from one normalized event."""
    if event.get("kind") == "model_attempt":
        team_member = event.get("team_member") or "coordinator"
        detail = {"stage": "model"}
        if isinstance(event.get("attempt"), int):
            detail["attempt"] = event["attempt"]
        if event.get("id"):
            detail["model_attempt_id"] = event["id"]
        return f"{team_member} completed a model step.", detail

    tool_name = event.get("tool_name")
    if not tool_name:
        return None
    team_member = event.get("team_member") or "coordinator"

    if event.get("kind") == "tool_call":
        detail = {"tool_name": tool_name, "stage": "call"}
        if event.get("id"):
            detail["tool_call_id"] = event["id"]
        if tool_name == "search_jobs" and isinstance(event.get("args"), dict):
            args = event["args"]
            detail["company_filter_applied"] = bool(str(args.get("company") or "").strip())
            detail["direct_employers_only"] = args.get("direct_employers_only", True) is True
            detail["exclude_junior"] = args.get("exclude_junior", False) is True
            detail["singapore_only"] = args.get("singapore_only", True) is True
            detail["title_filter_applied"] = bool(str(args.get("title_phrase") or "").strip())
        return f"{team_member} called {tool_name}.", detail

    if event.get("kind") == "tool_result":
        outcome = _outcome(tool_name, event.get("content"))
        if outcome is None:
            return None
        detail = {"tool_name": tool_name, "stage": "result", "outcome": outcome}
        if event.get("id"):
            detail["tool_call_id"] = event["id"]
        payload = _payload(event.get("content"))
        if isinstance(payload, dict) and payload.get("ok") is False:
            for key in (
                "failure_code",
                "failure_type",
                "retryable",
                "recovery_action",
                "validation_code",
            ):
                value = payload.get(key)
                if isinstance(value, (str, bool, int, float)):
                    detail[key] = value
        found = _postings_found(payload) if isinstance(payload, dict) else None
        if found is not None:
            detail["result_count"] = found
        if tool_name == "search_jobs" and isinstance(payload, dict):
            for key in (
                "candidate_count",
                "eligible_candidate_count",
                "visible_candidate_count",
                "truncated",
            ):
                value = payload.get(key)
                if isinstance(value, (bool, int)):
                    detail[key] = value
        return (
            f"{team_member} finished {tool_name}.",
            detail,
        )

    return None


def _outcome(tool_name: str, content: Any) -> str | None:
    """Summarize a useful tool result without exposing raw content."""
    payload = _payload(content)
    if not isinstance(payload, dict):
        return "tool completed"

    if payload.get("ok") is False:
        return "tool completed without an accepted result"

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
        return "no resume edit passed the evidence gate"

    return "tool completed"


def _payload(content: Any) -> Any:
    payload = content
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    return payload


def rejected_tool_result(event: dict) -> bool:
    """Whether a normalized tool result explicitly forbids another attempt."""
    if event.get("kind") != "tool_result":
        return False
    payload = _payload(event.get("content"))
    return isinstance(payload, dict) and (
        payload.get("retry") is False or (payload.get("ok") is False and payload.get("retryable") is False)
    )


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


def _question_strings(value: Any) -> Iterator[str]:
    """Recover question text without rendering model-produced containers."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return
        if text[:1] in {"[", "{"}:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                quoted_values = []
                for match in re.finditer(r'"(?:\\.|[^"\\])*"', text):
                    try:
                        decoded = json.loads(match.group(0)).strip()
                    except (json.JSONDecodeError, AttributeError):
                        continue
                    if decoded:
                        quoted_values.append(decoded)
                if quoted_values:
                    yield from quoted_values
                    return
            else:
                yield from _question_strings(parsed)
                return
        yield text
        return
    if isinstance(value, Mapping):
        for nested in value.values():
            yield from _question_strings(nested)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            yield from _question_strings(nested)


def format_questions(args: dict) -> str:
    """One pause can carry several questions, rendered as clean text."""
    questions = list(dict.fromkeys(_question_strings(args.get("questions"))))
    if not questions:
        return ""
    if len(questions) == 1:
        return questions[0]
    return "\n".join(f"{index}. {question}" for index, question in enumerate(questions, 1))
