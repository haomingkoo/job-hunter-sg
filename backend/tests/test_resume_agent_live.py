from __future__ import annotations

import importlib
import os
import secrets
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_backend_env() -> None:
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if key:
            os.environ.setdefault(key, value)


_load_backend_env()

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_SEALION") != "1",
    reason="Set RUN_LIVE_SEALION=1 plus SEALION_API or sealion_api in the environment or backend/.env.",
)


def _reload_live_agent_modules():
    for module_name in (
        "config",
        "ai_service",
        "resume_agent.models",
        "resume_agent.personas",
        "resume_agent.agent",
        "resume_agent.session",
    ):
        importlib.reload(importlib.import_module(module_name))

    import ai_service
    import resume_agent.session as agent_session

    return ai_service, agent_session


def _assert_completed(events: list[dict]) -> None:
    errors = [event.get("message", "") for event in events if event.get("event") == "error"]
    assert not errors
    assert events[0]["event"] == "session"
    assert events[-1] == {"event": "done", "session_id": events[0]["session_id"]}
    assert any(event.get("event") == "token" and str(event.get("content", "")).strip() for event in events)


def test_live_sealion_agent_completes_small_multi_turn_review():
    ai_service, agent_session = _reload_live_agent_modules()
    if not ai_service._get_api_key():
        pytest.fail("RUN_LIVE_SEALION=1 requires SEALION_API or sealion_api in the environment or backend/.env.")

    session_id = f"live-smoke-{secrets.token_hex(4)}"
    owner_key = f"live-smoke-owner-{secrets.token_hex(4)}"
    resume_text = """
Jane Tan
jane@example.com

EXPERIENCE
GovTech | AI Project Lead | Jan 2022 - Present
- Led delivery of an internal document assistant for operations teams
- Coordinated engineers, policy users, and QA reviewers across rollout
"""

    first_events = list(
        agent_session.stream_chat_events(
            {
                "session_id": session_id,
                "message": "Give one concise recruiter review of this resume. Do not search jobs.",
                "resume_text": resume_text,
            },
            owner_key=owner_key,
        )
    )
    _assert_completed(first_events)

    second_events = list(
        agent_session.stream_chat_events(
            {
                "session_id": session_id,
                "message": "Now give one concrete non-fabricated improvement to make the review more useful.",
            },
            owner_key=owner_key,
        )
    )
    _assert_completed(second_events)

    state = agent_session.get_state(session_id, owner_key=owner_key)
    assistant_outputs = [
        message["content"]
        for message in state["messages"]
        if message.get("role") == "assistant" and message.get("content")
    ]
    assert state["draft"].strip() == resume_text.strip()
    assert len(assistant_outputs) >= 2
