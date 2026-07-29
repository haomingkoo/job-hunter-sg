"""Server-sent event transport for recruitment-team commands."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from queue import Queue
from threading import Thread
from typing import Iterator

from fastapi.encoders import jsonable_encoder

from .activity_publisher import ActivityPublisher
from .errors import RecruitmentTeamError
from .interface import ActivityEvent, Command, RunReceipt
from .recruitment_team import RecruitmentTeam

log = logging.getLogger("jobhunter.recruitment_team")


class _QueueActivityPublisher(ActivityPublisher):
    def __init__(self, output: Queue):
        self._output = output

    def publish(self, event: ActivityEvent) -> None:
        self._output.put(("activity", event))


def _encode_event(event_name: str, payload: object) -> str:
    body = json.dumps(jsonable_encoder(asdict(payload)), separators=(",", ":"))
    return f"event: {event_name}\ndata: {body}\n\n"


def stream_command(
    team_factory,
    owner_id: int,
    command: Command,
    idempotency_key: str,
) -> Iterator[str]:
    """Yield committed activity followed by the command receipt or a safe error."""

    output: Queue = Queue()

    def execute() -> None:
        team: RecruitmentTeam = team_factory(_QueueActivityPublisher(output))
        try:
            output.put(("receipt", team.execute(owner_id, command, idempotency_key)))
        except Exception as error:
            # This runs in a background Thread fully decoupled from the SSE
            # client's connection (see the class docstring), so a client that
            # has already disconnected leaves nothing reading `output` --
            # without this log line, the failure would be completely
            # invisible server-side, exactly what made a real production
            # incident (a dropped candidate-profile stream) unable to be
            # diagnosed from the logs alone.
            log.exception(
                "recruitment-team command failed: owner_id=%s command=%s thread_id=%s",
                owner_id,
                type(command).__name__,
                getattr(command, "thread_id", None),
            )
            # Module errors carry an authored, user-facing message, and the REST
            # routes already return exactly that via _raise_http_error. Streaming
            # replaced every one of them with a single sentence, so a candidate
            # could not tell a stale saved resume from the model being down, and
            # had nothing to act on. Anything else stays generic: an unexpected
            # exception's text is not written for a user to read.
            payload = {
                "error_type": type(error).__name__,
                "message": "The recruitment team could not complete this turn.",
            }
            if isinstance(error, RecruitmentTeamError):
                payload["message"] = str(error)
                if hasattr(error, "retryable"):
                    payload["retryable"] = bool(error.retryable)
                if hasattr(error, "failure_type"):
                    payload["failure_type"] = error.failure_type
            output.put(("error", payload))

    worker = Thread(target=execute, name="recruitment-team-command")
    worker.start()

    while True:
        event_name, payload = output.get()
        if event_name == "error":
            yield (f"event: error\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n")
            break
        yield _encode_event(event_name, payload)
        if event_name == "receipt":
            break

    worker.join()
