"""In-memory chat/session state for Resume Deep Agent v2."""

from __future__ import annotations

import secrets
from typing import Any, Iterator

from langchain_core.messages import AIMessage, ToolMessage

from .agent import create_resume_agent, run_agent_turn


_sessions: dict[str, dict] = {}
_checkpointer: Any | None = None


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


def _build_prompt(body: dict) -> str:
    message = str(body.get("message", ""))
    resume_text = str(body.get("resume_text", ""))
    job_id = body.get("job_id")

    parts = [message]
    if resume_text:
        parts.append(f"Resume:\n{resume_text}")
    if job_id:
        parts.append(f"Target job id: {job_id}")
    else:
        parts.append(
            "General strengthening mode: no target job was selected. "
            "Do not invent job-specific requirements."
        )
    return "\n\n".join(part for part in parts if part)


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


def stream_chat_events(body: dict, agent: Any | None = None) -> Iterator[dict]:
    session_id = str(body.get("session_id") or secrets.token_urlsafe())
    state = _sessions.setdefault(session_id, _new_state(session_id))
    resume_text = str(body.get("resume_text") or state.get("draft") or "")
    job_id = body.get("job_id")

    state["mode"] = "target_job" if job_id else "general"
    state["job_id"] = job_id
    if resume_text:
        state["draft"] = resume_text

    yield {"event": "session", "session_id": session_id}

    active_agent = agent or create_resume_agent(checkpointer=_get_checkpointer())
    prompt = _build_prompt({**body, "resume_text": resume_text})
    result = run_agent_turn(active_agent, prompt, session_id=session_id)
    state["messages"].append({"role": "user", "content": str(body.get("message", ""))})

    for event in _event_messages(result, session_id):
        if event["event"] == "token":
            state["messages"].append({"role": "assistant", "content": event["content"]})
        yield event

    yield {"event": "done", "session_id": session_id}
