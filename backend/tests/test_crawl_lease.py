from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine

import crawl_lease
import database
import seed_jobs


def test_sqlite_crawl_lease_blocks_a_second_process(monkeypatch, tmp_path):
    database_path = tmp_path / "crawl.db"
    engine = create_engine(f"sqlite:///{database_path}")
    monkeypatch.setattr(database, "engine", engine)

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database_path}"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    command = (
        "from crawl_lease import job_crawl_lease; "
        "ctx = job_crawl_lease(); acquired = ctx.__enter__(); "
        "print('acquired' if acquired else 'blocked'); ctx.__exit__(None, None, None)"
    )

    with crawl_lease.job_crawl_lease() as acquired:
        assert acquired
        blocked = subprocess.run(
            [sys.executable, "-c", command],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        assert blocked.stdout.strip() == "blocked"

    with crawl_lease.job_crawl_lease() as reacquired:
        assert reacquired
    engine.dispose()


@contextmanager
def _lease(acquired: bool = True):
    yield acquired


def test_full_crawl_cli_exits_nonzero_when_crawl_is_incomplete(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["seed_jobs.py", "--full"])
    monkeypatch.setattr(seed_jobs, "job_crawl_lease", _lease)
    monkeypatch.setattr(seed_jobs, "crawl_all_jobs", lambda: {"errors": 1})

    assert seed_jobs.main() == 1


def test_full_crawl_cli_exits_zero_only_after_complete_crawl(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["seed_jobs.py", "--full"])
    monkeypatch.setattr(seed_jobs, "job_crawl_lease", _lease)
    monkeypatch.setattr(seed_jobs, "crawl_all_jobs", lambda: {"errors": 0})

    assert seed_jobs.main() == 0


def test_full_crawl_cli_rejects_an_overlapping_run(monkeypatch):
    called = False

    def crawl() -> dict:
        nonlocal called
        called = True
        return {"errors": 0}

    monkeypatch.setattr(sys, "argv", ["seed_jobs.py", "--full"])
    monkeypatch.setattr(seed_jobs, "job_crawl_lease", lambda: _lease(False))
    monkeypatch.setattr(seed_jobs, "crawl_all_jobs", crawl)

    assert seed_jobs.main() == 2
    assert not called
