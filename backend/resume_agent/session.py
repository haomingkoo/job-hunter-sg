"""In-memory chat/session state for Resume Deep Agent v2."""

from __future__ import annotations

import json
import secrets
import threading
import time
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
_MAX_ACTIVE_RUNS = 4
_sessions_lock = threading.Lock()


def _get_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver

        _checkpointer = MemorySaver()
    return _checkpointer


def _new_state(session_id: str) -> dict:
    now = time.time()
    return {
        "session_id": session_id,
        "_owner_key": None,
        "_updated_at": now,
        "mode": "general",
        "job_id": None,
        "draft": "",
        "profile_context": "",
        "todos": [],
        "persona_findings": [],
        "pending_diffs": [],
        "messages": [],
    }


def _drop_sessions(session_ids: list[str]) -> None:
    """Drop session metadata and its checkpoint while holding `_sessions_lock`."""
    for session_id in session_ids:
        if _checkpointer is not None:
            _checkpointer.delete_thread(session_id)
        _sessions.pop(session_id, None)


def _cleanup_sessions() -> None:
    now = time.time()
    expired = [
        session_id
        for session_id, state in _sessions.items()
        if now - float(state.get("_updated_at") or 0) > app_config.AGENT_SESSION_TTL_SECONDS
    ]
    _drop_sessions(expired)

    overflow = len(_sessions) - app_config.AGENT_MAX_SESSIONS
    if overflow <= 0:
        return
    oldest = sorted(_sessions, key=lambda sid: float(_sessions[sid].get("_updated_at") or 0))
    _drop_sessions(oldest[:overflow])


def _public_state(state: dict) -> dict:
    return {
        key: value
        for key, value in state.items()
        if not key.startswith("_") and key != "messages"
    }


def _state_visible_to_owner(state: dict, owner_key: str | None) -> bool:
    state_owner = state.get("_owner_key")
    if not state_owner:
        return True
    if str(state_owner).startswith("session:") and owner_key is None:
        return True
    return state_owner == owner_key


def get_state(session_id: str, owner_key: str | None = None) -> dict:
    with _sessions_lock:
        _cleanup_sessions()
        state = _sessions.get(session_id)
        if not state:
            raise KeyError(session_id)
        if not _state_visible_to_owner(state, owner_key):
            raise PermissionError("Agent session is not visible to this user.")
        state["_updated_at"] = time.time()
        return _public_state(state)


def owner_has_active_sessions(owner_key: str) -> bool:
    with _active_runs_lock:
        return _active_runs.get(owner_key, 0) > 0


def purge_owner_sessions(owner_key: str) -> None:
    with _sessions_lock:
        session_ids = [
            session_id
            for session_id, state in _sessions.items()
            if state.get("_owner_key") == owner_key
        ]
        _drop_sessions(session_ids)


def _append_message(state: dict, message: dict) -> None:
    messages = state.setdefault("messages", [])
    messages.append(message)
    del messages[:-app_config.AGENT_CHAT_HISTORY_LIMIT]


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
    profile_context = str(body.get("profile_context", ""))[: app_config.AGENT_MAX_PROFILE_CONTEXT_CHARS]
    job_id = body.get("job_id")

    parts = [
        "Review this like a senior recruiter and Head of HR. Be direct, evidence-bound, and practical.",
        message,
    ]
    if resume_text:
        parts.append(f"Resume:\n{resume_text}")
        bullet_texts, _bullet_meta = _resume_bullet_maps(resume_text)
        if bullet_texts:
            parts.append(
                "Resume bullet IDs:\n"
                + "\n".join(f"- {bullet_id}: {text}" for bullet_id, text in bullet_texts.items())
            )
    if profile_context:
        parts.append(
            "Optional LinkedIn/profile context for consistency review only. "
            "Do not turn this into resume claims unless the resume already supports them or the user confirms them:\n"
            f"{profile_context}"
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
    return list(pending_by_id.values())[: app_config.AGENT_PENDING_DIFFS_LIMIT]


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


def reserve_owner_run(owner_key: str) -> bool:
    with _active_runs_lock:
        current = _active_runs.get(owner_key, 0)
        if (
            current >= app_config.AGENT_MAX_CONCURRENT_RUNS_PER_USER
            or sum(_active_runs.values()) >= _MAX_ACTIVE_RUNS
        ):
            return False
        _active_runs[owner_key] = current + 1
        return True


def release_owner_run(owner_key: str) -> None:
    with _active_runs_lock:
        current = _active_runs.get(owner_key, 0)
        if current <= 1:
            _active_runs.pop(owner_key, None)
        else:
            _active_runs[owner_key] = current - 1


def stream_chat_events(
    body: dict,
    agent: Any | None = None,
    owner_key: str | None = None,
    owner_run_reserved: bool = False,
) -> Iterator[dict]:
    session_id = str(body.get("session_id") or secrets.token_urlsafe())
    owner = _run_owner(body, session_id, owner_key)
    if not owner_run_reserved:
        yield from _stream_chat_events(body, agent, session_id, owner, False)
        return
    try:
        yield from _stream_chat_events(body, agent, session_id, owner, True)
    finally:
        release_owner_run(owner)


def _stream_chat_events(
    body: dict,
    agent: Any | None,
    session_id: str,
    owner: str,
    owner_run_reserved: bool,
) -> Iterator[dict]:
    visibility_error = False
    with _sessions_lock:
        _cleanup_sessions()
        state = _sessions.setdefault(session_id, _new_state(session_id))
        visibility_error = not _state_visible_to_owner(state, owner)
        if not visibility_error:
            state["_owner_key"] = owner
            state["_updated_at"] = time.time()

    if visibility_error:
        yield {
            "event": "error",
            "session_id": session_id,
            "message": "Agent session is not visible to this user.",
        }
        yield {"event": "done", "session_id": session_id}
        return

    resume_text = str(body.get("resume_text") or state.get("draft") or "")
    profile_context = str(body.get("profile_context") or state.get("profile_context") or "")
    if len(resume_text) > app_config.AGENT_MAX_DRAFT_CHARS:
        yield {"event": "session", "session_id": session_id}
        yield {
            "event": "error",
            "session_id": session_id,
            "message": "Resume draft is too large for Agent Review.",
        }
        yield {"event": "done", "session_id": session_id}
        return
    if len(profile_context) > app_config.AGENT_MAX_PROFILE_CONTEXT_CHARS:
        profile_context = profile_context[: app_config.AGENT_MAX_PROFILE_CONTEXT_CHARS]

    job_id = body.get("job_id")
    bullet_texts, bullet_meta = _resume_bullet_maps(resume_text)

    state["mode"] = "target_job" if job_id else "general"
    state["job_id"] = job_id
    if resume_text:
        state["draft"] = resume_text
    if profile_context:
        state["profile_context"] = profile_context

    yield {"event": "session", "session_id": session_id}

    if not owner_run_reserved and not reserve_owner_run(owner):
        yield {
            "event": "error",
            "session_id": session_id,
            "message": "Agent v2 is already running for this user.",
        }
        yield {"event": "done", "session_id": session_id}
        return

    try:
        active_agent = agent or create_resume_agent(checkpointer=_get_checkpointer())
        prompt = _build_prompt({**body, "resume_text": resume_text, "profile_context": profile_context})
        with bullet_context(bullet_texts):
            result = run_agent_turn(active_agent, prompt, session_id=session_id)
        state["pending_diffs"] = _collect_pending_diffs(
            result,
            bullet_texts,
            bullet_meta,
            state.get("pending_diffs", []),
        )
        _append_message(state, {"role": "user", "content": str(body.get("message", ""))})

        for event in _event_messages(result, session_id):
            if event["event"] == "token":
                _append_message(state, {"role": "assistant", "content": event["content"]})
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
        if not owner_run_reserved:
            release_owner_run(owner)

    yield {"event": "done", "session_id": session_id}
