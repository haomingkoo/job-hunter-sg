"""Deterministic recovery decisions and content-free attempt accounting."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Literal


FailureType = Literal[
    "transient",
    "validation",
    "business",
    "permission",
    "safety",
    "cancelled",
]
AttemptLayer = Literal["transport", "semantic", "workflow_resume"]


@dataclass(frozen=True)
class RecoveryDecision:
    failure_type: FailureType
    failure_code: str
    retryable: bool
    recovery_action: str
    retry_after_seconds: float | None = None


_FAILURE_TYPES: dict[str, FailureType] = {
    "transport_timeout": "transient",
    "connection_failure": "transient",
    "rate_limited": "transient",
    "capacity_exceeded": "transient",
    "process_interrupted": "transient",
    "checkpoint_state_unavailable": "transient",
    "checkpoint_cleanup_failed": "transient",
    "structured_output_invalid": "validation",
    "semantic_fixable": "validation",
    "information_absent": "validation",
    "output_truncated": "validation",
    "identical_output": "validation",
    "quality_gate_blocked": "validation",
    "permission_denied": "permission",
    "authentication_failed": "permission",
    "invalid_configuration": "business",
    "policy_block": "business",
    "attempt_budget_exhausted": "business",
    "specialist_attempt_budget_exhausted": "business",
    "missing_terminal_result": "business",
    "pause_token_not_found": "business",
    "checkpoint_mismatch": "business",
    "prompt_injection": "safety",
    "protected_candidate_question": "safety",
    "user_cancelled": "cancelled",
}

_RETRY_ACTIONS = {
    "transport_timeout": "retry_incomplete_stage",
    "connection_failure": "retry_incomplete_stage",
    "rate_limited": "retry_after",
    "capacity_exceeded": "retry_after",
    "process_interrupted": "retry_incomplete_stage",
    "checkpoint_state_unavailable": "retry_same_run",
    "checkpoint_cleanup_failed": "retry_same_run",
    "structured_output_invalid": "correct_rejected_output",
    "semantic_fixable": "correct_rejected_output",
}

_TERMINAL_ACTIONS = {
    "information_absent": "ask_candidate",
    "output_truncated": "start_smaller_explicit_run",
    "identical_output": "operator_review",
    "quality_gate_blocked": "review_quality_findings",
    "permission_denied": "request_authorization",
    "authentication_failed": "operator_action",
    "invalid_configuration": "operator_action",
    "policy_block": "request_user_direction",
    "attempt_budget_exhausted": "start_new_logical_run",
    "specialist_attempt_budget_exhausted": "start_new_logical_run",
    "missing_terminal_result": "operator_review",
    "pause_token_not_found": "start_new_logical_run",
    "checkpoint_mismatch": "start_new_logical_run",
    "prompt_injection": "operator_review",
    "protected_candidate_question": "operator_review",
    "user_cancelled": "await_explicit_user_action",
}

_LEGACY_FAILURE_CODES = {
    "timeout": "transport_timeout",
    "transport": "connection_failure",
    "unavailable": "connection_failure",
    "rate_limit": "rate_limited",
    "authentication": "permission_denied",
    "permission": "permission_denied",
    "validation": "structured_output_invalid",
    "quality": "quality_gate_blocked",
    "workflow": "missing_terminal_result",
    "concurrency": "capacity_exceeded",
}


def normalize_failure_code(value: str) -> str:
    code = value.strip()
    if code in _FAILURE_TYPES:
        return code
    return _LEGACY_FAILURE_CODES.get(code, "unclassified_failure")


def classify_failure(
    failure_code: str,
    *,
    attempts_remaining: bool = False,
    retry_after_seconds: float | None = None,
) -> RecoveryDecision:
    """Return one fail-closed decision from a stable code and persisted budget."""

    code = failure_code.strip()
    failure_type = _FAILURE_TYPES.get(code)
    if failure_type is None:
        return RecoveryDecision(
            failure_type="business",
            failure_code="unclassified_failure",
            retryable=False,
            recovery_action="operator_review",
        )
    action = _RETRY_ACTIONS.get(code)
    retryable = action is not None and attempts_remaining
    if not retryable:
        action = _TERMINAL_ACTIONS.get(code, "attempt_budget_exhausted")
    return RecoveryDecision(
        failure_type=failure_type,
        failure_code=code,
        retryable=retryable,
        recovery_action=action,
        retry_after_seconds=retry_after_seconds if retryable and code == "rate_limited" else None,
    )


def classify_exception(error: BaseException, *, attempts_remaining: bool = False) -> RecoveryDecision:
    """Classify known transport/provider failures; unknown exceptions fail closed."""

    status_code = getattr(error, "status_code", None)
    error_name = type(error).__name__
    if (
        status_code in {401, 403}
        or isinstance(error, PermissionError)
        or error_name in {"AuthenticationError", "PermissionDeniedError"}
    ):
        code = "permission_denied"
    elif status_code == 429 or error_name == "RateLimitError":
        code = "rate_limited"
    elif status_code == 408 or status_code in {500, 502, 503, 504}:
        code = "connection_failure"
    elif isinstance(error, TimeoutError) or error_name in {"APITimeoutError", "ReadTimeout", "ConnectTimeout"}:
        code = "transport_timeout"
    elif isinstance(error, ConnectionError) or error_name in {"APIConnectionError", "ConnectError"}:
        code = "connection_failure"
    elif error_name in {"CancelledError", "KeyboardInterrupt"}:
        code = "user_cancelled"
    elif isinstance(error, (TypeError, ValueError)):
        code = "invalid_configuration"
    else:
        code = "unclassified_failure"
    return classify_failure(code, attempts_remaining=attempts_remaining)


def empty_attempt_ledger(logical_run_id: str) -> dict:
    return {"logical_run_id": logical_run_id, "stages": {}}


def attempts_remaining(ledger: dict | None, stage: str, layer: AttemptLayer, limit: int) -> bool:
    used = int((((ledger or {}).get("stages") or {}).get(stage) or {}).get(layer, {}).get("used") or 0)
    return used < limit


def record_attempt(
    ledger: dict | None,
    *,
    logical_run_id: str,
    stage: str,
    layer: AttemptLayer,
    limit: int,
    status: str,
    attempt_id: str,
    decision: RecoveryDecision | None = None,
    model: str = "",
    validation_code: str = "",
    error_type: str = "",
) -> dict:
    """Append one idempotent, content-free attempt and update its stage budget."""

    updated = deepcopy(ledger) if ledger else empty_attempt_ledger(logical_run_id)
    updated.setdefault("logical_run_id", logical_run_id)
    updated.setdefault("stages", {})
    stage_ledger = updated["stages"].setdefault(stage, {})
    budget = dict(stage_ledger.get(layer) or {})
    attempts = [dict(item) for item in budget.get("attempts") or []]
    if any(item.get("attempt_id") == attempt_id for item in attempts):
        return updated
    used = int(budget.get("used") or 0) + 1
    attempt = {
        "attempt_id": attempt_id,
        "ordinal": used,
        "status": status,
    }
    for key, value in {
        "model": model,
        "validation_code": validation_code,
        "error_type": error_type,
    }.items():
        if value:
            attempt[key] = value
    if decision is not None:
        attempt["decision"] = asdict(decision)
        stage_ledger["last_decision"] = asdict(decision)
        updated["last_decision"] = asdict(decision)
    attempts.append(attempt)
    stage_ledger[layer] = {
        "used": used,
        "limit": limit,
        "exhausted": used >= limit,
        "attempts": attempts,
    }
    return updated


def merge_execution_attempts(
    ledger: dict | None,
    *,
    logical_run_id: str,
    metrics: dict | None,
    transport_limit: int,
    semantic_limit: int,
) -> dict:
    """Project persisted model events into the one per-stage attempt ledger."""

    updated = ledger or empty_attempt_ledger(logical_run_id)
    for event_index, event in enumerate((metrics or {}).get("attempts") or [], start=1):
        if not isinstance(event, dict):
            continue
        stage = str(event.get("stage") or (metrics or {}).get("stage") or "model")
        scope = str(event.get("scope_id") or event.get("team_member") or "")
        if scope:
            stage = f"{stage}:{scope}"
        status = str(event.get("status") or "unknown")
        model = str(event.get("model") or "")
        validation_code = str(event.get("validation_code") or "")
        error_type = str(event.get("error_type") or "")
        failure_code = str(event.get("failure_code") or "")
        count = max(1, int(event.get("attempt_count") or 1))
        event_semantic_limit = int(event.get("attempt_limit") or semantic_limit)
        for ordinal in range(1, count + 1):
            attempt_key = f"{event_index}:{ordinal}"
            transport_remaining = attempts_remaining(
                updated,
                stage,
                "transport",
                transport_limit,
            )
            decision = (
                classify_failure(failure_code, attempts_remaining=transport_remaining)
                if failure_code
                else None
            )
            updated = record_attempt(
                updated,
                logical_run_id=logical_run_id,
                stage=stage,
                layer="transport",
                limit=transport_limit,
                status="error" if status == "error" else "success",
                attempt_id=f"transport:{attempt_key}",
                decision=decision,
                model=model,
                error_type=error_type,
            )
            if status == "error":
                continue
            semantic_remaining = attempts_remaining(
                updated,
                stage,
                "semantic",
                event_semantic_limit,
            )
            semantic_decision = (
                classify_failure("semantic_fixable", attempts_remaining=semantic_remaining)
                if status == "validation_failed"
                else None
            )
            updated = record_attempt(
                updated,
                logical_run_id=logical_run_id,
                stage=stage,
                layer="semantic",
                limit=event_semantic_limit,
                status=status,
                attempt_id=f"semantic:{attempt_key}",
                decision=semantic_decision,
                model=model,
                validation_code=validation_code,
            )
    return updated
