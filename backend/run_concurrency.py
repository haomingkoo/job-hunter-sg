"""One in-process admission gate for model-backed user runs."""

from __future__ import annotations

import threading

import config


active_runs: dict[str, int] = {}
_lock = threading.Lock()


def reserve_owner_run(owner_key: str) -> bool:
    """Reserve capacity without waiting, or return False when either cap is full."""
    with _lock:
        owner_count = active_runs.get(owner_key, 0)
        if (
            owner_count >= config.AGENT_MAX_CONCURRENT_RUNS_PER_USER
            or sum(active_runs.values()) >= config.AGENT_MAX_ACTIVE_RUNS
        ):
            return False
        active_runs[owner_key] = owner_count + 1
        return True


def release_owner_run(owner_key: str) -> None:
    with _lock:
        owner_count = active_runs.get(owner_key, 0)
        if owner_count <= 1:
            active_runs.pop(owner_key, None)
        else:
            active_runs[owner_key] = owner_count - 1


def owner_has_active_run(owner_key: str) -> bool:
    with _lock:
        return active_runs.get(owner_key, 0) > 0
