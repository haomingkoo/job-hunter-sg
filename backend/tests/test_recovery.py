from __future__ import annotations

import asyncio

import pytest

from recruitment_team.recovery import (
    attempts_remaining,
    classify_exception,
    classify_failure,
    empty_attempt_ledger,
    merge_execution_attempts,
    record_attempt,
)


def test_failure_taxonomy_is_deterministic_and_budget_aware():
    retry = classify_failure("transport_timeout", attempts_remaining=True)
    exhausted = classify_failure("transport_timeout", attempts_remaining=False)
    absent = classify_failure("information_absent", attempts_remaining=True)

    assert (retry.failure_type, retry.retryable, retry.recovery_action) == (
        "transient", True, "retry_incomplete_stage",
    )
    assert (exhausted.failure_type, exhausted.retryable, exhausted.recovery_action) == (
        "transient", False, "attempt_budget_exhausted",
    )
    assert (absent.failure_type, absent.retryable, absent.recovery_action) == (
        "validation", False, "ask_candidate",
    )


def test_unknown_and_permission_failures_fail_closed():
    unknown = classify_failure("provider_said_maybe")
    permission = classify_exception(type("PermissionDeniedError", (Exception,), {})())

    assert (unknown.failure_type, unknown.failure_code, unknown.retryable) == (
        "business", "unclassified_failure", False,
    )
    assert (permission.failure_type, permission.failure_code, permission.retryable) == (
        "permission", "permission_denied", False,
    )


@pytest.mark.parametrize(
    ("error", "failure_type", "failure_code"),
    [
        (TimeoutError(), "transient", "transport_timeout"),
        (type("RateLimitError", (Exception,), {})(), "transient", "rate_limited"),
        (PermissionError(), "permission", "permission_denied"),
        (ValueError(), "business", "invalid_configuration"),
        (asyncio.CancelledError(), "cancelled", "user_cancelled"),
    ],
)
def test_exception_fault_classes_are_stable_and_fail_closed(
    error,
    failure_type,
    failure_code,
):
    decision = classify_exception(error, attempts_remaining=True)

    assert decision.failure_type == failure_type
    assert decision.failure_code == failure_code
    assert decision.retryable is (failure_type == "transient")


@pytest.mark.parametrize(
    ("failure_code", "recovery_action"),
    [
        ("information_absent", "ask_candidate"),
        ("output_truncated", "start_smaller_explicit_run"),
        ("prompt_injection", "operator_review"),
        ("attempt_budget_exhausted", "start_new_logical_run"),
    ],
)
def test_terminal_faults_never_retry(failure_code, recovery_action):
    decision = classify_failure(failure_code, attempts_remaining=True)

    assert decision.retryable is False
    assert decision.recovery_action == recovery_action


def test_attempt_ledger_is_idempotent_and_keeps_retry_layers_separate():
    ledger = empty_attempt_ledger("run-1")
    timeout = classify_failure("transport_timeout", attempts_remaining=True)
    ledger = record_attempt(
        ledger,
        logical_run_id="run-1",
        stage="candidate_profile:experience_01",
        layer="transport",
        limit=3,
        status="error",
        attempt_id="transport-1",
        decision=timeout,
        model="model-a",
        error_type="APITimeoutError",
    )
    ledger = record_attempt(
        ledger,
        logical_run_id="run-1",
        stage="candidate_profile:experience_01",
        layer="transport",
        limit=3,
        status="error",
        attempt_id="transport-1",
        decision=timeout,
    )
    ledger = record_attempt(
        ledger,
        logical_run_id="run-1",
        stage="candidate_profile:experience_01",
        layer="semantic",
        limit=2,
        status="validation_failed",
        attempt_id="semantic-1",
        decision=classify_failure("semantic_fixable", attempts_remaining=True),
        validation_code="field:outcome:quote_not_found",
    )

    stage = ledger["stages"]["candidate_profile:experience_01"]
    assert stage["transport"]["used"] == 1
    assert stage["semantic"]["used"] == 1
    assert attempts_remaining(ledger, "candidate_profile:experience_01", "transport", 3) is True
    assert "resume" not in str(ledger).lower()
    assert "job" not in str(ledger).lower()


def test_valid_empty_is_not_represented_as_a_failure_code():
    assert classify_failure("valid_empty").failure_code == "unclassified_failure"


def test_execution_events_feed_one_idempotent_transport_and_semantic_ledger():
    metrics = {
        "stage": "candidate_profile",
        "attempts": [
            {
                "stage": "candidate_profile",
                "scope_id": "experience_01",
                "status": "validation_failed",
                "model": "model-a",
                "validation_code": "field:outcome:quote_not_found",
            },
            {
                "stage": "candidate_profile",
                "scope_id": "experience_01",
                "status": "success",
                "model": "model-a",
            },
        ],
    }

    first = merge_execution_attempts(
        None,
        logical_run_id="run-1",
        metrics=metrics,
        transport_limit=3,
        semantic_limit=2,
    )
    replay = merge_execution_attempts(
        first,
        logical_run_id="run-1",
        metrics=metrics,
        transport_limit=3,
        semantic_limit=2,
    )

    stage = replay["stages"]["candidate_profile:experience_01"]
    assert stage["transport"]["used"] == 2
    assert stage["semantic"]["used"] == 2
    assert stage["semantic"]["exhausted"] is True
    assert stage["semantic"]["attempts"][0]["validation_code"] == (
        "field:outcome:quote_not_found"
    )
