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


def test_an_unexpected_exception_stays_generic():
    """Its text is not written for a user, and may carry internals."""
    payload = _error_payload(RuntimeError("psycopg2.OperationalError: FATAL password auth failed"))

    assert payload["message"] == "The recruitment team could not complete this turn."
    assert "password" not in payload["message"]
    assert payload["error_type"] == "RuntimeError"
