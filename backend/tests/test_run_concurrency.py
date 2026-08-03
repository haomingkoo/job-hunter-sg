from __future__ import annotations

import json

import pytest

import config
import run_concurrency
from recruitment_team.activity_publisher import IgnoreActivityPublisher
from recruitment_team.activity_stream import stream_command
from recruitment_team.errors import RunConcurrencyExceeded
from recruitment_team.interface import RunReceipt, SendMessage, ShortlistJob
from recruitment_team.recruitment_team import RecruitmentTeam
from recruitment_team.telemetry import RecordedTelemetry


@pytest.fixture(autouse=True)
def clear_active_runs():
    run_concurrency.active_runs.clear()
    yield
    run_concurrency.active_runs.clear()


def test_shared_gate_enforces_per_user_and_global_caps(monkeypatch):
    monkeypatch.setattr(config, "AGENT_MAX_CONCURRENT_RUNS_PER_USER", 1)
    monkeypatch.setattr(config, "AGENT_MAX_ACTIVE_RUNS", 2)

    assert run_concurrency.reserve_owner_run("user:1") is True
    assert run_concurrency.reserve_owner_run("user:1") is False
    assert run_concurrency.reserve_owner_run("user:2") is True
    assert run_concurrency.reserve_owner_run("user:3") is False

    run_concurrency.release_owner_run("user:1")
    assert run_concurrency.reserve_owner_run("user:3") is True


def test_v3_rejects_concurrent_work_before_reading_command_content():
    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    class Database:
        def query(self, *_args):
            return Query()

    owner_id = 7
    assert run_concurrency.reserve_owner_run(f"user:{owner_id}")
    team = RecruitmentTeam(
        Database(),
        None,
        None,
        None,
        RecordedTelemetry(),
        IgnoreActivityPublisher(),
    )

    with pytest.raises(RunConcurrencyExceeded) as caught:
        team.execute(
            owner_id,
            SendMessage(thread_id="thread-private", message="private candidate content"),
            "concurrent-command",
        )

    assert "private candidate content" not in str(caught.value)
    assert "thread-private" not in str(caught.value)


def test_deterministic_job_actions_remain_available_during_an_ai_run():
    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return None

    class Database:
        def query(self, *_args):
            return Query()

    receipt = RunReceipt(
        run_id="run-shortlist",
        thread_id="thread-shortlist",
        status="completed",
        trace_key="trace-shortlist",
    )

    class DeterministicTeam(RecruitmentTeam):
        def _execute_locked(self, *_args):
            return receipt

    owner_id = 9
    assert run_concurrency.reserve_owner_run(f"user:{owner_id}")
    team = DeterministicTeam(
        Database(),
        None,
        None,
        None,
        RecordedTelemetry(),
        IgnoreActivityPublisher(),
    )

    assert team.execute(
        owner_id,
        ShortlistJob(thread_id="thread-shortlist", job_id=42),
        "shortlist-now",
    ) == receipt


def test_streamed_concurrency_rejection_contains_only_authored_safe_metadata():
    class LimitedTeam:
        def execute(self, *_args):
            raise RunConcurrencyExceeded("Another AI run is active. Try again shortly.")

    body = "".join(stream_command(lambda _publisher: LimitedTeam(), 1, object(), "private-key"))
    payload = json.loads(body.split("data: ", 1)[1])

    assert payload == {
        "error_type": "RunConcurrencyExceeded",
        "message": "Another AI run is active. Try again shortly.",
        "retryable": True,
        "failure_type": "concurrency",
    }
    assert "private-key" not in body
