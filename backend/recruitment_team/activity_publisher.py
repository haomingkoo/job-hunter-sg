"""Publisher port for committed, user-safe recruitment activity events."""

from __future__ import annotations

from typing import Protocol

from .interface import ActivityEvent


class ActivityPublisher(Protocol):
    def publish(self, event: ActivityEvent) -> None: ...


class IgnoreActivityPublisher:
    """Adapter for callers that read durable events after command completion."""

    def publish(self, event: ActivityEvent) -> None:
        return None


class RecordedActivityPublisher:
    """Adapter for tests that assert publication timing and content."""

    def __init__(self):
        self.events: list[ActivityEvent] = []

    def publish(self, event: ActivityEvent) -> None:
        self.events.append(event)
