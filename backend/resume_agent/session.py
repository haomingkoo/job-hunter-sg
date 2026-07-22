"""In-memory chat/session state for Resume Deep Agent v2."""

from __future__ import annotations

import json
import logging
import secrets
import statistics
import threading
import time
from datetime import datetime
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import config as app_config
from langchain_core.messages import AIMessage, ToolMessage
from openai import APITimeoutError
from prompt_safety import xml_data_block
from resume_document import apply_resume_patch, create_resume_document
from resume_structurer import get_all_bullets, structure_resume

from .agent import create_resume_agent, run_agent_turn
from .judge import judge_assessment
from .models import ResumeAgentConfigurationError
from .personas import iter_persona_worker_runs
from .prompts import (
    assessment_presentation_violation_snippets,
    assessment_presentation_violations,
    synthesis_score_context,
)
from .tooling import SYNTHESIS_TOOLS
from .tracing import ToolSpanRecorder
from .telemetry import trace_key, traced_events
from .tools import bullet_context


log = logging.getLogger("jobhunter.resume_agent")
_sessions: dict[str, dict] = {}
_checkpointer: Any | None = None
_active_runs: dict[str, int] = {}
_active_runs_lock = threading.Lock()
_sessions_lock = threading.Lock()


_ToolSpanRecorder = ToolSpanRecorder


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
        "_persona_revision": None,
        "mode": "general",
        "status": "idle",
        "review_status": "idle",
        "progress": "",
        "error": "",
        "response": "",
        "job_id": None,
        "job_context": {},
        "draft": "",
        "document": None,
        "profile_context": "",
        "todos": [],
        "persona_findings": [],
        "worker_runs": [],
        "multi_agent_assessment": {},
        "judge_assessment": {},
        "judge_run": {},
        "synthesis_revision": {},
        "presentation_violations": [],
        "tool_spans": [],
        "pending_diffs": [],
        "messages": [],
        "chat_history_dropped_count": 0,
    }


def _reduce_worker_scores(findings: list[dict]) -> dict:
    """Combine independent scores without giving the synthesizer scoring power."""
    scores = {
        finding["persona"]: finding["score"]
        for finding in findings
        if isinstance(finding.get("persona"), str)
        and isinstance(finding.get("score"), int)
        and not isinstance(finding.get("score"), bool)
    }
    if not scores:
        return {}
    return {
        "score": round(statistics.median(scores.values())),
        "scores_by_worker": scores,
        "score_method": "median of independent worker scores",
        "score_range": max(scores.values()) - min(scores.values()),
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
    overflow = max(0, len(messages) - app_config.AGENT_CHAT_HISTORY_LIMIT)
    if overflow:
        del messages[:overflow]
        state["chat_history_dropped_count"] = (
            int(state.get("chat_history_dropped_count") or 0) + overflow
        )


def _resume_bullet_maps(
    resume_text: str,
    document: dict | None = None,
) -> tuple[dict[str, str], dict[str, dict]]:
    if not resume_text.strip():
        return {}, {}
    canonical = document or create_resume_document(resume_text)
    bullets = [block for block in canonical.get("blocks", []) if block.get("kind") == "bullet"]
    if not bullets:
        bullets = get_all_bullets(structure_resume(resume_text))
    return (
        {bullet["id"]: bullet["text"] for bullet in bullets},
        {bullet["id"]: bullet for bullet in bullets},
    )


def _build_prompt(body: dict) -> str:
    message = str(body.get("message", ""))
    resume_text = str(body.get("resume_text", ""))
    profile_context = str(body.get("profile_context", ""))
    job_id = body.get("job_id")
    job_context = body.get("job_context", {})
    score_context = body.get("score_context", {})
    if not isinstance(job_context, dict):
        raise TypeError("job_context must be an object")
    if not isinstance(score_context, dict):
        raise TypeError("score_context must be an object")

    parts = [
        (
            "Current Singapore date: "
            f"{datetime.now(ZoneInfo('Asia/Singapore')).date().isoformat()}. "
            "Judge resume dates relative to this date; do not call a past or "
            "current date future-dated."
        ),
        "Review this like a senior recruiter and Head of HR. Be direct, evidence-bound, and practical.",
        message,
    ]
    if resume_text:
        parts.append(xml_data_block("resume_data", resume_text))
        bullet_texts, _bullet_meta = _resume_bullet_maps(resume_text)
        if bullet_texts:
            parts.append(
                xml_data_block(
                    "resume_bullet_ids_data",
                    "\n".join(
                        f"- {bullet_id}: {text}"
                        for bullet_id, text in bullet_texts.items()
                    ),
                )
            )
    if profile_context:
        parts.append(
            "Optional LinkedIn/profile context for consistency review only. "
            "Do not turn this into resume claims unless the resume already supports them or the user confirms them:\n"
            f"{xml_data_block('profile_data', profile_context)}"
        )
    if job_id:
        parts.append(f"Target job id: {job_id}")
    if not job_id and not job_context:
        parts.append(
            "General strengthening mode: no target job was selected. "
            "Do not invent job-specific requirements."
        )
    if job_context:
        parts.append(
            "Use this selected-job snapshot even if its internal database row is no longer active. "
            "Do not call get_job merely to re-fetch it.\n"
            + xml_data_block(
                "target_job_data",
                json.dumps(job_context, ensure_ascii=False, separators=(",", ":")),
            )
        )
    if score_context:
        parts.append(
            "Reuse this current rule-based score snapshot as a deterministic baseline. "
            "Do not call score_resume again unless the user explicitly requests a rescore.\n"
            + xml_data_block(
                "resume_score_data",
                json.dumps(score_context, ensure_ascii=False, separators=(",", ":")),
            )
        )
    persona_findings = body.get("persona_findings")
    if persona_findings:
        synthesis_findings = [
            {
                "summary": finding.get("summary"),
                "category": finding.get("category"),
                "findings": [
                    {
                        key: item.get(key)
                        for key in (
                            "kind",
                            "finding",
                            "source",
                            "source_location",
                            "confidence",
                        )
                    }
                    for item in (finding.get("findings") or [])
                    if isinstance(item, dict)
                ],
                "conflicts": finding.get("conflicts"),
            }
            for finding in persona_findings
            if isinstance(finding, dict)
        ]
        parts.append(
            "Independent evidence reviews are provided below without internal reviewer identities or "
            "scores. Synthesize them; do not delegate another review.\n"
            + xml_data_block(
                "persona_findings_data",
                json.dumps(synthesis_findings, ensure_ascii=False, separators=(",", ":")),
            )
        )
    worker_runs = body.get("worker_runs")
    failed_workers = [
        {
            key: run.get(key)
            for key in (
                "persona",
                "status",
                "failure_type",
                "attempted_operation",
                "source",
                "attempted_queries",
                "attempt_count",
                "duration_ms",
                "partial_results",
                "local_recovery_attempts",
                "remaining_gap",
                "suggested_alternatives",
                "retryable",
                "error",
            )
        }
        for run in (worker_runs or [])
        if isinstance(run, dict) and run.get("status") != "success"
    ]
    if failed_workers:
        parts.append(
            "Some independent workers returned partial results or failed after their own retries. "
            "Continue with validated findings, clearly label incomplete specialist coverage, and never "
            "interpret a failed search as an empty result.\n"
            + xml_data_block(
                "worker_failures_data",
                json.dumps(failed_workers, ensure_ascii=False, separators=(",", ":")),
            )
        )
    multi_agent_assessment = body.get("multi_agent_assessment")
    if multi_agent_assessment:
        score_context = synthesis_score_context(multi_agent_assessment)
        parts.append(
            "This independent-worker score is a deterministic median. Report it unchanged; "
            "do not invent a replacement score or expose reviewer counts, roles, or individual "
            "scores. Describe only substantive differences in how the evidence can be weighed.\n"
            + xml_data_block(
                "multi_agent_assessment_data",
                json.dumps(score_context, ensure_ascii=False, separators=(",", ":")),
            )
        )
    return "\n\n".join(part for part in parts if part)


def _collect_pending_diffs(
    result: dict,
    text_by_id: dict[str, str],
    meta_by_id: dict[str, dict],
    existing: list[dict],
    document_revision: str,
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
            "document_revision": document_revision,
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


def _run_synthesis(
    active_agent: Any,
    prompt: str,
    *,
    session_id: str,
    bullet_texts: dict[str, str],
    phase: str,
) -> tuple[dict, list[dict]]:
    recorder = _ToolSpanRecorder(trace_id=session_id)
    recorder.set_phase(phase)
    with bullet_context(bullet_texts):
        result = run_agent_turn(
            active_agent,
            prompt,
            session_id=session_id,
            callbacks=[recorder],
        )
    return result, recorder.spans


def _run_quality_judge(
    final_assessment: str,
    state: dict,
    document: dict,
    job_context: dict,
    session_id: str,
) -> dict:
    return judge_assessment(
        final_assessment,
        state.get("persona_findings", []),
        state.get("worker_runs", []),
        resume_evidence={
            "blocks": [
                {
                    key: block.get(key)
                    for key in ("id", "kind", "text", "section_key")
                }
                for block in document.get("blocks", [])
            ]
        },
        job_context=job_context,
        trace_id=session_id,
    )


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
            or sum(_active_runs.values()) >= app_config.AGENT_MAX_ACTIVE_RUNS
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
    with _sessions_lock:
        prior_state = _sessions.get(session_id, {})
    attributes = {
        "trace_key": trace_key(session_id),
        "target_job": bool(
            body.get("job_id")
            or body.get("job_context")
            or prior_state.get("job_id")
            or prior_state.get("job_context")
        ),
    }
    if not owner_run_reserved:
        yield from traced_events(
            _stream_chat_events(body, agent, session_id, owner, False),
            **attributes,
        )
        return
    try:
        yield from traced_events(
            _stream_chat_events(body, agent, session_id, owner, True),
            **attributes,
        )
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

    resume_text = str(body["resume_text"]) if "resume_text" in body else str(state.get("draft") or "")
    profile_context = (
        str(body["profile_context"])
        if "profile_context" in body
        else str(state.get("profile_context") or "")
    )
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
        yield {
            "event": "error",
            "session_id": session_id,
            "message": "Profile context is too large for Agent Review. Shorten it and try again.",
        }
        yield {"event": "done", "session_id": session_id}
        return

    if "job_context" in body and not isinstance(body["job_context"], dict):
        yield {
            "event": "error",
            "session_id": session_id,
            "message": "Job context must be an object.",
        }
        yield {"event": "done", "session_id": session_id}
        return
    job_id = body.get("job_id") if "job_id" in body else state.get("job_id")
    job_context = body["job_context"] if "job_context" in body else state.get("job_context", {})
    if "job_context" in body and not job_context and "job_id" not in body:
        job_id = None
    previous_document = state.get("document")
    document = previous_document
    if not isinstance(document, dict) or document.get("raw_text") != resume_text:
        document = create_resume_document(resume_text)
    if (
        isinstance(previous_document, dict)
        and previous_document.get("revision") != document.get("revision")
    ):
        state["pending_diffs"] = []
    bullet_texts, bullet_meta = _resume_bullet_maps(resume_text, document)

    state["mode"] = "target_job" if job_id or job_context else "general"
    state["job_id"] = job_id
    state["job_context"] = job_context
    if "resume_text" in body or resume_text:
        state["draft"] = resume_text
        state["document"] = document
    if "profile_context" in body or profile_context:
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
        persona_revision = json.dumps(
            [document.get("revision"), job_id, job_context],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if agent is None and state.get("_persona_revision") != persona_revision:
            state["persona_findings"] = []
            state["worker_runs"] = []
            state["review_status"] = "running"
            state["multi_agent_assessment"] = {}
            state["judge_assessment"] = {}
            state["judge_run"] = {}
            state["synthesis_revision"] = {}
            state["presentation_violations"] = []
            yield {
                "event": "progress",
                "session_id": session_id,
                "message": "Running independent resume reviewers",
            }
            for run in iter_persona_worker_runs(
                document,
                include_market=bool(job_context),
                job_context=job_context,
                session_id=session_id,
            ):
                state["worker_runs"].append(run)
                if run.get("status") == "error":
                    yield {
                        "event": "persona_error",
                        "session_id": session_id,
                        "persona": run.get("persona"),
                        "failure": run,
                    }
                    continue
                finding = run["assessment"]
                state["persona_findings"].append(finding)
                yield {
                    "event": "persona",
                    "session_id": session_id,
                    "persona": finding["persona"],
                    "finding": finding,
                }
                if run.get("status") == "partial":
                    yield {
                        "event": "persona_error",
                        "session_id": session_id,
                        "persona": run.get("persona"),
                        "failure": run,
                    }
            completed_count = len(state["persona_findings"])
            incomplete_count = sum(
                run.get("status") != "success" for run in state["worker_runs"]
            )
            state["review_status"] = (
                "partial_success" if completed_count and incomplete_count
                else "success" if completed_count
                else "error"
            )
            if incomplete_count:
                log.warning("resume_agent_workflow_problem %s", json.dumps({
                    "trace_id": session_id,
                    "status": state["review_status"],
                    "successful_worker_count": completed_count,
                    "failed_workers": [
                        {
                            "persona": run.get("persona"),
                            "failure_type": run.get("failure_type"),
                            "error_code": (run.get("error") or {}).get("code"),
                        }
                        for run in state["worker_runs"]
                        if run.get("status") != "success"
                    ],
                }, separators=(",", ":")))
            state["multi_agent_assessment"] = _reduce_worker_scores(
                state["persona_findings"]
            )
            state["_persona_revision"] = persona_revision
            if state["review_status"] == "error":
                yield {
                    "event": "error",
                    "session_id": session_id,
                    "message": "No independent reviewer completed successfully. Please retry.",
                }
                yield {"event": "done", "session_id": session_id}
                return
            yield {
                "event": "progress",
                "session_id": session_id,
                "message": "Synthesizing reviewer findings",
            }

        active_agent = agent or create_resume_agent(
            tools=SYNTHESIS_TOOLS,
            subagents=[],
            checkpointer=_get_checkpointer(),
        )
        prompt = _build_prompt({
            **body,
            "resume_text": resume_text,
            "profile_context": profile_context,
            "persona_findings": state.get("persona_findings", []),
            "worker_runs": state.get("worker_runs", []),
            "multi_agent_assessment": state.get("multi_agent_assessment", {}),
        })
        worker_spans = [
            span
            for run in state.get("worker_runs", [])
            for span in run.get("tool_spans", [])
        ]
        state["tool_spans"] = worker_spans
        result, synthesis_spans = _run_synthesis(
            active_agent,
            prompt,
            session_id=session_id,
            bullet_texts=bullet_texts,
            phase="orchestrator",
        )
        state["tool_spans"] = [*worker_spans, *synthesis_spans]
        if result.get("stopped"):
            yield {
                "event": "error",
                "session_id": session_id,
                "message": (
                    "The reviewers finished, but the final synthesis reached its safety limit. "
                    "Their completed findings are preserved; try a narrower edit request."
                ),
            }
        final_assessment = next((
            str(message.content)
            for message in reversed(result.get("messages", []))
            if isinstance(message, AIMessage) and message.content
        ), "")
        if final_assessment and not result.get("stopped") and agent is None:
            yield {
                "event": "progress",
                "session_id": session_id,
                "message": "Quality-checking final assessment",
            }
            state["judge_run"] = _run_quality_judge(
                final_assessment,
                state,
                document,
                job_context,
                session_id,
            )
            state["judge_assessment"] = state["judge_run"].get("assessment", {})
            state["tool_spans"] = [
                *state["tool_spans"],
                *state["judge_run"].get("tool_spans", []),
            ]
            initial_presentation_violations = assessment_presentation_violations(
                final_assessment
            )
            if (
                state["judge_assessment"].get("requires_revision")
                or initial_presentation_violations
            ):
                initial_judge = state["judge_assessment"]
                yield {
                    "event": "progress",
                    "session_id": session_id,
                    "message": "Correcting evidence issues found by the quality check",
                }
                violation_snippets = assessment_presentation_violation_snippets(
                    final_assessment
                )
                revision_instruction = (
                    "Revise your immediately preceding assessment using the quality feedback. "
                    "Correct factual, evidence, attribution, consensus, and placeholder issues. "
                    "Preserve the required section order and deterministic reviewer score."
                )
                if violation_snippets:
                    quoted = "; ".join(
                        f'{name}: "{snippet}"' for name, snippet in violation_snippets
                    )
                    revision_instruction += (
                        f" Remove these exact policy-violating fragments entirely -- do not "
                        f"rephrase them into another example, hypothetical figure, or placeholder: {quoted}."
                    )
                revision_prompt = "\n\n".join((
                    revision_instruction,
                    xml_data_block("failed_assessment_data", final_assessment),
                    xml_data_block(
                        "quality_feedback_data",
                        json.dumps({
                            "verdict": initial_judge.get("verdict"),
                            "weaknesses": initial_judge.get("weaknesses"),
                            "evidence_gaps": initial_judge.get("evidence_gaps"),
                            "presentation_violations": initial_presentation_violations,
                        }, ensure_ascii=False, separators=(",", ":")),
                    ),
                ))
                revised_result, revision_spans = _run_synthesis(
                    active_agent,
                    revision_prompt,
                    session_id=session_id,
                    bullet_texts=bullet_texts,
                    phase="orchestrator_revision",
                )
                if not revised_result.get("stopped"):
                    revised_assessment = next((
                        str(message.content)
                        for message in reversed(revised_result.get("messages", []))
                        if isinstance(message, AIMessage) and message.content
                    ), "")
                    if revised_assessment:
                        result = revised_result
                        final_assessment = revised_assessment
                state["tool_spans"] = [*state["tool_spans"], *revision_spans]
                state["judge_run"] = _run_quality_judge(
                    final_assessment,
                    state,
                    document,
                    job_context,
                    session_id,
                )
                state["judge_assessment"] = state["judge_run"].get("assessment", {})
                state["synthesis_revision"] = {
                    "attempted": True,
                    "initial_judge": initial_judge,
                    "resolved": not state["judge_assessment"].get("requires_revision", True),
                }
                state["tool_spans"] = [
                    *state["tool_spans"],
                    *state["judge_run"].get("tool_spans", []),
                ]
            yield {
                "event": "judge" if state["judge_run"].get("status") == "success" else "judge_error",
                "session_id": session_id,
                "judge_run": state["judge_run"],
            }
            state["presentation_violations"] = assessment_presentation_violations(
                final_assessment
            )
            quality_gate_failed = (
                state["judge_run"].get("status") != "success"
                or state["judge_assessment"].get("requires_revision", True)
                or bool(state["presentation_violations"])
            )
            if quality_gate_failed:
                yield {
                    "event": "error",
                    "session_id": session_id,
                    "message": (
                        "The review was generated, but it did not pass the independent quality "
                        "gate. No assessment or resume changes were published; retry the review."
                    ),
                }
                result = {"messages": []}
        state["pending_diffs"] = _collect_pending_diffs(
            result,
            bullet_texts,
            bullet_meta,
            state.get("pending_diffs", []),
            str(document.get("revision") or ""),
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
    except APITimeoutError:
        yield {
            "event": "error",
            "session_id": session_id,
            "message": (
                "The review model took too long to respond. No resume changes were applied. "
                "Try a narrower review request."
            ),
        }
    except Exception:
        log.exception("Resume agent run failed for session_id=%s", session_id)
        yield {
            "event": "error",
            "session_id": session_id,
            "message": "Agent v2 hit an internal error. Check the backend logs.",
        }
    finally:
        if not owner_run_reserved:
            release_owner_run(owner)

    yield {"event": "done", "session_id": session_id}


def apply_pending_diff(
    session_id: str,
    bullet_id: str,
    expected_revision: str,
    owner_key: str,
) -> dict:
    """Apply one pending agent edit to its canonical document."""
    with _sessions_lock:
        _cleanup_sessions()
        state = _sessions.get(session_id)
        if not state:
            raise KeyError(session_id)
        if not _state_visible_to_owner(state, owner_key):
            raise PermissionError("Agent session is not visible to this user.")
        diff = next(
            (
                item
                for item in state.get("pending_diffs", [])
                if item.get("bullet_id") == bullet_id and item.get("status") == "pending"
            ),
            None,
        )
        if not diff:
            raise KeyError(bullet_id)
        if diff.get("document_revision") != expected_revision:
            from resume_document import StaleResumeRevision

            raise StaleResumeRevision("Resume changed after this suggestion was created.")

        document = apply_resume_patch(
            state["document"],
            {
                "block_id": bullet_id,
                "expected_revision": expected_revision,
                "expected_text": diff["original"],
                "text": diff["rewrite"],
            },
        )
        remaining = [
            item for item in state.get("pending_diffs", []) if item.get("bullet_id") != bullet_id
        ]
        for item in remaining:
            item["document_revision"] = document["revision"]
        state["document"] = document
        state["draft"] = document["raw_text"]
        state["pending_diffs"] = remaining
        state["_updated_at"] = time.time()
        return _public_state(state)


def dismiss_pending_diff(session_id: str, bullet_id: str, owner_key: str) -> dict:
    """Dismiss one pending edit without changing the resume document."""
    with _sessions_lock:
        _cleanup_sessions()
        state = _sessions.get(session_id)
        if not state:
            raise KeyError(session_id)
        if not _state_visible_to_owner(state, owner_key):
            raise PermissionError("Agent session is not visible to this user.")
        before = state.get("pending_diffs", [])
        remaining = [item for item in before if item.get("bullet_id") != bullet_id]
        if len(remaining) == len(before):
            raise KeyError(bullet_id)
        state["pending_diffs"] = remaining
        state["_updated_at"] = time.time()
        return _public_state(state)


def start_background_review(
    body: dict,
    owner_key: str,
    agent: Any | None = None,
) -> str:
    """Start a detached in-process review and return its session ID immediately."""
    session_id = str(body.get("session_id") or secrets.token_urlsafe())
    with _sessions_lock:
        _cleanup_sessions()
        state = _sessions.setdefault(session_id, _new_state(session_id))
        if not _state_visible_to_owner(state, owner_key):
            raise PermissionError("Agent session is not visible to this user.")
        state.update({
            "_owner_key": owner_key,
            "_updated_at": time.time(),
            "status": "queued",
            "progress": "Waiting for reviewers",
            "error": "",
            "response": "",
        })

    def run() -> None:
        failed = False
        for event in stream_chat_events(
            {**body, "session_id": session_id},
            agent=agent,
            owner_key=owner_key,
            owner_run_reserved=True,
        ):
            with _sessions_lock:
                state = _sessions.get(session_id)
                if not state:
                    continue
                event_type = event.get("event")
                if event_type == "session":
                    state["status"] = "running"
                    state["progress"] = "Reading resume evidence"
                elif event_type == "progress":
                    state["progress"] = str(event.get("message") or "Reviewing resume")
                elif event_type == "persona":
                    state["progress"] = f"{event.get('persona') or 'Reviewer'} review complete"
                elif event_type == "tool":
                    state["progress"] = "Checking proposed changes"
                elif event_type == "token":
                    state["response"] = str(event.get("content") or "")
                    state["progress"] = "Finalizing review"
                elif event_type == "error":
                    failed = True
                    state["status"] = "failed"
                    state["error"] = str(event.get("message") or "Review failed")
                elif event_type == "done" and not failed:
                    if state.get("review_status") == "error":
                        failed = True
                        state["status"] = "failed"
                        state["error"] = "No independent reviewer completed successfully. Please retry."
                    else:
                        state["status"] = "completed"
                        state["progress"] = "Review complete"
                state["_updated_at"] = time.time()

    threading.Thread(target=run, daemon=True).start()
    return session_id
