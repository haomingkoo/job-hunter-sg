"""Internal persistence seam for ordered, user-safe recruitment activity."""

from __future__ import annotations

import threading
import weakref

from sqlalchemy import update
from sqlalchemy.orm import Session

from models import RecruitmentActivityEvent, RecruitmentRun, RecruitmentThread

from .interface import ActivityEvent


_PUBLIC_DETAIL_KEYS = frozenset({
    "artifact_id",
    "attempt",
    "attempt_count",
    "attempt_limit",
    "candidate_count",
    "company_filter_applied",
    "candidate_profile_artifact_id",
    "candidate_profile_field_count",
    "candidate_profile_version",
    "checkpoint_hit_count",
    "command_type",
    "completed_scope_count",
    "correction_scope",
    "criterion_count",
    "disposition",
    "direct_employers_only",
    "error_type",
    "eligible_candidate_count",
    "failed_scope_id",
    "failure_code",
    "failure_type",
    "field_count",
    "finding_count",
    "hidden_result_count",
    "model_attempt_count",
    "model_attempt_id",
    "model_call_count",
    "operation",
    "outcome",
    "partial_artifact_id",
    "question_count",
    "question_limit",
    "recovery_action",
    "result_count",
    "retry_after_seconds",
    "retryable",
    "scope_count",
    "scope_id",
    "source_count",
    "stage",
    "status",
    "tool_call_id",
    "tool_name",
    "tracked_job_id",
    "transition",
    "truncated",
    "valid_empty",
    "validation_code",
    "visible_candidate_count",
})
_PUBLIC_ATTRIBUTE_KEYS = frozenset({
    "attempt_count",
    "attempt_limit",
    "command_type",
    "error_type",
    "failure_code",
    "failure_type",
    "model",
    "recovery_action",
    "result_count",
    "retryable",
    "span_id",
    "stage",
    "tool_name",
    "validation_code",
})


def _public_metadata(payload: dict | None, allowed_keys: frozenset[str]) -> dict:
    return {
        key: value
        for key, value in (payload or {}).items()
        if key in allowed_keys and isinstance(value, (str, int, float, bool))
    }


def public_detail(payload: dict | None) -> dict:
    """Keep only content-free scalar metadata suitable for a durable event."""
    return _public_metadata(payload, _PUBLIC_DETAIL_KEYS)


def trace_attributes(item: dict, detail: dict) -> dict:
    """Project raw trace context to the operational fields safe to persist."""
    attributes = {}
    for key in ("tool_name", "stage"):
        if isinstance(detail.get(key), str):
            attributes[key] = detail[key]
    if isinstance(detail.get("result_count"), int):
        attributes["result_count"] = detail["result_count"]
    if item.get("id"):
        attributes["span_id"] = str(item["id"])
    return attributes


# The lock is process-local. Database leases provide cross-worker claiming.
_THREAD_LOCKS: "weakref.WeakValueDictionary[str, threading.Lock]" = weakref.WeakValueDictionary()
_THREAD_LOCKS_REGISTRY_LOCK = threading.Lock()


def thread_lock(thread_id: str) -> threading.Lock:
    """Serialize command transitions and event sequencing for one thread."""
    with _THREAD_LOCKS_REGISTRY_LOCK:
        lock = _THREAD_LOCKS.get(thread_id)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[thread_id] = lock
        return lock


def _reserve_sequence(db: Session, thread_id: str) -> int:
    next_value = db.execute(
        update(RecruitmentThread)
        .where(RecruitmentThread.id == thread_id)
        .values(next_event_sequence=RecruitmentThread.next_event_sequence + 1)
        .returning(RecruitmentThread.next_event_sequence)
    ).scalar_one()
    return int(next_value) - 1


def create_record(
    db: Session,
    *,
    thread: RecruitmentThread,
    run: RecruitmentRun,
    event_type: str,
    status: str,
    summary: str,
    detail: dict | None = None,
    team_member: str = "coordinator",
    parent_id: str | None = None,
    duration_ms: float | None = None,
    attributes: dict | None = None,
) -> RecruitmentActivityEvent:
    """Create one ordered activity record with user-safe metadata."""
    detail_payload = detail or {}
    observed_attempt = detail_payload.get("attempt", detail_payload.get("attempt_count", 1))
    attempt = max(1, int(observed_attempt)) if isinstance(observed_attempt, int) else 1
    event = RecruitmentActivityEvent(
        thread_id=thread.id,
        run_id=run.id,
        sequence=_reserve_sequence(db, thread.id),
        event_type=event_type,
        status=status,
        team_member=team_member,
        attempt=attempt,
        trace_key=run.trace_key,
        summary=summary,
        detail=public_detail(detail_payload),
        parent_id=parent_id,
        duration_ms=duration_ms,
        attributes=_public_metadata(attributes, _PUBLIC_ATTRIBUTE_KEYS),
    )
    db.add(event)
    return event


def to_activity_event(item: RecruitmentActivityEvent) -> ActivityEvent:
    """Project a persisted row to the recruitment-team interface."""
    return ActivityEvent(
        sequence=item.sequence,
        run_id=item.run_id,
        event_type=item.event_type,
        status=item.status,
        team_member=item.team_member,
        attempt=item.attempt,
        trace_key=item.trace_key,
        summary=item.summary,
        detail=item.detail,
        parent_id=item.parent_id,
        duration_ms=item.duration_ms,
        attributes=item.attributes or {},
        created_at=item.created_at,
    )
