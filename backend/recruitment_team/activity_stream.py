"""Server-sent event transport for recruitment-team commands."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict
from queue import Empty, Queue
from threading import Thread
from typing import Callable, Iterator

from fastapi.encoders import jsonable_encoder

import config

from .activity_publisher import ActivityPublisher
from .errors import safe_terminal_error_payload
from .interface import ActivityEvent, Command
from .recruitment_team import RecruitmentTeam

log = logging.getLogger("jobhunter.recruitment_team")
RUN_REATTACH_POLL_SECONDS = 1.0


class _QueueActivityPublisher(ActivityPublisher):
    def __init__(
        self,
        output: Queue,
        stream_open: threading.Event,
        stream_lock: threading.Lock,
    ):
        self._output = output
        self._stream_open = stream_open
        self._stream_lock = stream_lock

    def publish(self, event: ActivityEvent) -> None:
        with self._stream_lock:
            if self._stream_open.is_set():
                self._output.put(("activity", event))


def _encode_event(event_name: str, payload: object) -> str:
    body = json.dumps(jsonable_encoder(asdict(payload)), separators=(",", ":"))
    event_id = f"id: {payload.sequence}\n" if isinstance(payload, ActivityEvent) else ""
    return f"event: {event_name}\ndata: {body}\n{event_id}\n"


def _encode_payload(event_name: str, payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"))
    return f"event: {event_name}\ndata: {body}\n\n"


def stream_command(
    team_factory,
    owner_id: int,
    command: Command,
    idempotency_key: str,
) -> Iterator[str]:
    """Yield committed activity followed by the command receipt or a safe error."""

    yield from _stream_operation(
        team_factory,
        lambda team: team.execute(owner_id, command, idempotency_key),
        operation_name=type(command).__name__,
        thread_id=getattr(command, "thread_id", None),
    )


def stream_retry(team_factory, owner_id: int, thread_id: str, run_id: str) -> Iterator[str]:
    """Stream a durable retry through the same activity transport as commands."""

    yield from _stream_operation(
        team_factory,
        lambda team: team.retry_conversation_run(owner_id, thread_id, run_id),
        operation_name="RetryConversationRun",
        thread_id=thread_id,
    )


def _stream_operation(
    team_factory,
    operation: Callable[[RecruitmentTeam], object],
    *,
    operation_name: str,
    thread_id: str | None,
) -> Iterator[str]:

    output: Queue = Queue()
    stream_open = threading.Event()
    stream_lock = threading.Lock()
    stream_open.set()

    def publish(event_name: str, payload: object) -> None:
        with stream_lock:
            if stream_open.is_set():
                output.put((event_name, payload))

    def execute() -> None:
        team: RecruitmentTeam | None = None
        try:
            team = team_factory(
                _QueueActivityPublisher(output, stream_open, stream_lock)
            )
            publish("receipt", operation(team))
        except Exception as error:
            # This runs in a background Thread fully decoupled from the SSE
            # client's connection (see the class docstring), so a client that
            # has already disconnected leaves nothing reading `output` --
            # without this log line, the failure would be completely
            # invisible server-side, exactly what made a real production
            # incident (a dropped candidate-profile stream) unable to be
            # diagnosed from the logs alone.
            log.error(
                "recruitment-team command failed: command=%s thread_id=%s error_type=%s",
                operation_name,
                thread_id,
                type(error).__name__,
            )
            # Module errors carry an authored, user-facing message, and the REST
            # routes already return exactly that via _raise_http_error. Streaming
            # replaced every one of them with a single sentence, so a candidate
            # could not tell a stale saved resume from the model being down, and
            # had nothing to act on. Anything else stays generic: an unexpected
            # exception's text is not written for a user to read.
            publish("error", safe_terminal_error_payload(error))
        finally:
            if team is not None:
                close = getattr(team, "close", None)
                if close is not None:
                    close()

    worker = Thread(target=execute, name="recruitment-team-command")
    worker.start()

    try:
        while True:
            try:
                event_name, payload = output.get(
                    timeout=config.RECRUITMENT_STREAM_HEARTBEAT_SECONDS
                )
            except Empty:
                yield _encode_payload("heartbeat", {"status": "running"})
                continue
            if event_name == "error":
                yield _encode_payload("error", payload)
                break
            yield _encode_event(event_name, payload)
            if event_name == "receipt":
                break
    finally:
        with stream_lock:
            stream_open.clear()

    worker.join()


def stream_run(team: RecruitmentTeam, owner_id: int, run_id: str, after_sequence: int) -> Iterator[str]:
    """Replay one accepted durable run without executing its command again."""

    cursor = after_sequence
    heartbeat_at = time.monotonic() + config.RECRUITMENT_STREAM_HEARTBEAT_SECONDS
    while True:
        events, terminal = team.run_replay(owner_id, run_id, cursor)
        for event in events:
            yield _encode_event("activity", event)
            cursor = event.sequence
        if terminal is not None:
            event_name, payload = terminal
            if event_name == "receipt":
                yield _encode_event(event_name, payload)
            else:
                yield _encode_payload(event_name, payload)
            return
        time.sleep(RUN_REATTACH_POLL_SECONDS)
        if time.monotonic() >= heartbeat_at:
            yield _encode_payload("heartbeat", {"status": "running"})
            heartbeat_at = time.monotonic() + config.RECRUITMENT_STREAM_HEARTBEAT_SECONDS
