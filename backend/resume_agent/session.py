"""In-memory chat/session state for Resume Deep Agent v2."""

from __future__ import annotations

import json
import secrets
import threading
from typing import Any, Iterator

import config as app_config
from langchain_core.messages import AIMessage, ToolMessage
from resume_structurer import get_all_bullets, structure_resume

from .agent import create_resume_agent, run_agent_turn
from .models import ResumeAgentConfigurationError
from .tools import bullet_context


_sessions: dict[str, dict] = {}
_checkpointer: Any | None = None
_active_runs: dict[str, int] = {}
_active_runs_lock = threading.Lock()


def _get_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer = MemorySaver()
    return _checkpointer


def _new_state(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "mode": "general",
        "job_id": None,
        "draft": "",
        "todos": [],
        "persona_findings": [],
        "pending_diffs": [],
        "messages": [],
    }


def get_state(session_id: str) -> dict:
    return dict(_sessions.get(session_id, _new_state(session_id)))


def _resume_bullet_maps(resume_text: str) -> tuple[dict[str, str], dict[str, dict]]:
    if not resume_text.strip():
        return {}, {}
    bullets = get_all_bullets(structure_resume(resume_text))
    return (
        {bullet["id"]: bullet["text"] for bullet in bullets},
        {bullet["id"]: bullet for bullet in bullets},
    )


def _build_prompt(body: dict) -> str:
    message = str(body.get("message", ""))
    resume_text = str(body.get("resume_text", ""))
    job_id = body.get("job_id")

    parts = [message]
    if resume_text:
        parts.append(f"Resume:\n{resume_text}")
        bullet_texts, _bullet_meta = _resume_bullet_maps(resume_text)
        if bullet_texts:
            parts.append(
                "Resume bullet IDs:\n"
                + "\n".join(f"- {bullet_id}: {text}" for bullet_id, text in bullet_texts.items())
            )
    if job_id:
        parts.append(f"Target job id: {job_id}")
    else:
        parts.append(
            "General strengthening mode: no target job was selected. "
            "Do not invent job-specific requirements."
        )
    return "\n\n".join(part for part in parts if part)


def _collect_pending_diffs(
    result: dict,
    text_by_id: dict[str, str],
    meta_by_id: dict[str, dict],
    existing: list[dict],
) -> list[dict]:
    pending_by_id = {diff.get("bullet_id"): diff for diff in existing if diff.get("bullet_id")}
    for message in result.get("messages", []):
        if not isinstance(message, ToolMessage) or message.name != "propose_edit":
            continue
        try:
            payload = json.loads(message.content if isinstance(message.content, str) else "")
        except json.JSONDecodeError:
            continue
        bullet_id = str(payload.get("bullet_id", ""))
        rewrite = str(payload.get("rewrite", ""))
        if not payload.get("accepted") or bullet_id not in text_by_id or not rewrite:
            continue
        original = text_by_id[bullet_id]
        if rewrite == original:
            continue
        meta = meta_by_id.get(bullet_id, {})
        pending_by_id[bullet_id] = {
            "bullet_id": bullet_id,
            "section_key": meta.get("section_key", ""),
            "entry_id": meta.get("entry_id", ""),
            "original": original,
            "rewrite": rewrite,
            "status": "pending",
        }
    return list(pending_by_id.values())


def _event_messages(result: dict, session_id: str) -> Iterator[dict]:
    for message in result.get("messages", []):
        if isinstance(message, ToolMessage):
            yield {
                "event": "tool",
                "session_id": session_id,
                "name": message.name or "",
                "content": message.content,
            }
        elif isinstance(message, AIMessage) and message.content:
            yield {
                "event": "token",
                "session_id": session_id,
                "content": message.content,
            }


def _run_owner(body: dict, session_id: str, owner_key: str | None) -> str:
    if owner_key:
        return owner_key
    if body.get("_owner_key"):
        return str(body["_owner_key"])
    return f"session:{session_id}"


def _try_start_run(owner: str) -> bool:
    with _active_runs_lock:
        current = _active_runs.get(owner, 0)
        if current >= app_config.AGENT_MAX_CONCURRENT_RUNS_PER_USER:
            return False
        _active_runs[owner] = current + 1
        return True


def _finish_run(owner: str) -> None:
    with _active_runs_lock:
        current = _active_runs.get(owner, 0)
        if current <= 1:
            _active_runs.pop(owner, None)
        else:
            _active_runs[owner] = current - 1


def stream_chat_events(
    body: dict,
    agent: Any | None = None,
    owner_key: str | None = None,
) -> Iterator[dict]:
    session_id = str(body.get("session_id") or secrets.token_urlsafe())
    state = _sessions.setdefault(session_id, _new_state(session_id))
    resume_text = str(body.get("resume_text") or state.get("draft") or "")
    job_id = body.get("job_id")
    owner = _run_owner(body, session_id, owner_key)
    bullet_texts, bullet_meta = _resume_bullet_maps(resume_text)

    state["mode"] = "target_job" if job_id else "general"
    state["job_id"] = job_id
    if resume_text:
        state["draft"] = resume_text

    yield {"event": "session", "session_id": session_id}

    if not _try_start_run(owner):
        yield {
            "event": "error",
            "session_id": session_id,
            "message": "Agent v2 is already running for this user.",
        }
        yield {"event": "done", "session_id": session_id}
        return

    try:
        active_agent = agent or create_resume_agent(checkpointer=_get_checkpointer())
        prompt = _build_prompt({**body, "resume_text": resume_text})
        with bullet_context(bullet_texts):
            result = run_agent_turn(active_agent, prompt, session_id=session_id)
        state["pending_diffs"] = _collect_pending_diffs(
            result,
            bullet_texts,
            bullet_meta,
            state.get("pending_diffs", []),
        )
        state["messages"].append({"role": "user", "content": str(body.get("message", ""))})

        for event in _event_messages(result, session_id):
            if event["event"] == "token":
                state["messages"].append({"role": "assistant", "content": event["content"]})
            yield event
    except ResumeAgentConfigurationError as exc:
        yield {
            "event": "error",
            "session_id": session_id,
            "message": str(exc),
        }
    except Exception:
        yield {
            "event": "error",
            "session_id": session_id,
            "message": "Agent v2 hit an internal error. Check the backend logs.",
        }
    finally:
        _finish_run(owner)

    yield {"event": "done", "session_id": session_id}
