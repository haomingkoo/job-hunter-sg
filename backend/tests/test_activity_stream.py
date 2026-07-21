from __future__ import annotations

import logging
import time

from recruitment_team.activity_stream import stream_command
from recruitment_team.interface import RunReceipt, SendMessage


class _FakeTeam:
    def __init__(self, activity_publisher, *, error: Exception | None = None, receipt: RunReceipt | None = None):
        self._activity_publisher = activity_publisher
        self._error = error
        self._receipt = receipt

    def execute(self, owner_id, command, idempotency_key):
        if self._error is not None:
            raise self._error
        return self._receipt


def test_stream_command_yields_activity_then_receipt_on_success():
    receipt = RunReceipt(run_id="run-1", thread_id="thread-1", status="completed", trace_key="trace-1")
    events = list(
        stream_command(
            lambda activity_publisher: _FakeTeam(activity_publisher, receipt=receipt),
            owner_id=1,
            command=SendMessage(thread_id="thread-1", message="Hello."),
            idempotency_key="key-1",
        )
    )
    assert any("event: receipt" in event for event in events)


def test_stream_command_logs_the_failure_even_if_the_client_never_finishes_reading():
    """Regression guard for a real production incident: a client that
    disconnects mid-stream leaves nothing reading the output queue, so
    without server-side logging a command failure was completely invisible.
    stream_command's worker Thread runs independently of generator
    iteration -- pulling only the first item (simulating a client that
    disconnects immediately after) must still let the background thread run
    to completion and log the failure."""

    def team_factory(activity_publisher):
        return _FakeTeam(activity_publisher, error=ValueError("boom"))

    generator = stream_command(
        team_factory,
        owner_id=42,
        command=SendMessage(thread_id="thread-disconnect", message="Hello."),
        idempotency_key="key-disconnect",
    )

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("jobhunter.recruitment_team")
    handler = _Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    try:
        next(generator)  # kicks off the worker Thread; simulates reading only the first chunk
        # Deliberately do not continue iterating `generator` -- simulates the
        # client disconnecting right after. The worker Thread does not care
        # whether anything keeps reading its output queue, so it must still
        # run to completion and log the failure on its own.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not records:
            time.sleep(0.05)
    finally:
        logger.removeHandler(handler)

    assert records, "expected the background worker to log the failure even though nothing kept reading its output"
    assert "thread-disconnect" in records[0].getMessage()
    assert records[0].exc_info is not None
