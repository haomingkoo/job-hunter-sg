"""A streamed failure must tell the candidate what actually went wrong.

Every streamed error used to collapse into "The recruitment team could not
complete this turn", so a stale saved resume, a missing thread and the model
being down were indistinguishable and none of them were actionable. The REST
routes already returned the authored reason via _raise_http_error; only the
stream threw it away.
"""

from __future__ import annotations

import json

from recruitment_team.activity_stream import stream_command
from recruitment_team.errors import CandidateProfilingUnavailable, ThreadNotFound


class _ExplodingTeam:
    def __init__(self, error):
        self._error = error

    def execute(self, *_args, **_kwargs):
        raise self._error


def _error_payload(error) -> dict:
    blocks = "".join(stream_command(lambda _publisher: _ExplodingTeam(error), 1, object(), "k"))
    for block in blocks.split("\n\n"):
        if "event: error" in block:
            data = block.split("data: ", 1)[1].strip()
            return json.loads(data)
    raise AssertionError(f"no error event in stream: {blocks!r}")


def test_a_module_error_reaches_the_candidate_verbatim():
    from recruitment_team.recovery import classify_failure

    payload = _error_payload(
        CandidateProfilingUnavailable(
            "saved resume structure does not match its immutable text",
            decision=classify_failure("checkpoint_mismatch"),
        )
    )

    assert payload["message"] == "saved resume structure does not match its immutable text"
    assert payload["error_type"] == "CandidateProfilingUnavailable"
    assert payload["retryable"] is False
    assert payload["failure_type"] == "business"
    assert payload["failure_code"] == "checkpoint_mismatch"
    assert payload["recovery_action"] == "start_new_logical_run"


def test_a_simple_module_error_still_carries_its_reason():
    payload = _error_payload(ThreadNotFound("recruitment thread not found"))

    assert payload["message"] == "recruitment thread not found"
    assert "retryable" not in payload


def test_role_profile_failure_exposes_only_safe_resume_metadata():
    from recruitment_team.errors import RoleProfilingUnavailable
    from recruitment_team.recovery import classify_failure

    payload = _error_payload(
        RoleProfilingUnavailable(
            "role evidence correction timed out",
            decision=classify_failure("transport_timeout", attempts_remaining=True),
            detail={
                "attempted_stage": "role_evidence",
                "validation_code": "literal_quote:unsupported:c1",
                "correction_scope": "single_criterion",
                "partial_artifact_id": "artifact-1",
                "alternatives": ["retry_incomplete_stage", "start_new_logical_run"],
                "private_resume_text": "must never be streamed",
            },
        )
    )

    assert payload["attempted_stage"] == "role_evidence"
    assert payload["correction_scope"] == "single_criterion"
    assert payload["partial_artifact_id"] == "artifact-1"
    assert payload["validation_code"] == "literal_quote:unsupported"
    assert payload["retryable"] is True
    assert "private_resume_text" not in payload


def test_an_unexpected_exception_stays_generic(caplog):
    """Its text is not written for a user, and may carry internals."""
    payload = _error_payload(RuntimeError("psycopg2.OperationalError: FATAL password auth failed"))

    assert payload["message"] == "The recruitment team could not complete this turn."
    assert "password" not in payload["message"]
    assert payload["error_type"] == "RuntimeError"
    assert "password auth failed" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text


def test_team_factory_failure_emits_one_error_and_terminates(monkeypatch):
    import config

    monkeypatch.setattr(config, "RECRUITMENT_STREAM_HEARTBEAT_SECONDS", 0.01)

    def broken_factory(_publisher):
        raise RuntimeError("factory unavailable")

    blocks = list(stream_command(broken_factory, 1, object(), "k"))

    assert len(blocks) == 1
    assert blocks[0].startswith("event: error\n")
    assert "heartbeat" not in blocks[0]
