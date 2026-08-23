from __future__ import annotations

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from recruitment_team.open_agent.checkpoint_store import (
    _psycopg_url,
    build_checkpoint_store,
)


def test_sqlite_checkpoint_store_is_initialized_and_deletable(tmp_path):
    saver, close = build_checkpoint_store(
        "sqlite:///local.db",
        str(tmp_path / "checkpoints.db"),
    )
    try:
        assert isinstance(saver, SqliteSaver)
        saver.delete_thread("missing-thread")
    finally:
        close()

    with sqlite3.connect(tmp_path / "checkpoints.db") as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "checkpoints" in tables


def test_psycopg_url_removes_sqlalchemy_driver_names():
    assert _psycopg_url("postgres://host/db") == "postgresql://host/db"
    assert _psycopg_url("postgresql+psycopg2://host/db") == "postgresql://host/db"


def test_postgres_checkpoint_store_uses_pool_and_runs_setup(monkeypatch):
    calls: list[object] = []

    class FakePool:
        def __init__(self, **kwargs):
            calls.append(("pool", kwargs))

        def open(self, *, wait):
            calls.append(("open", wait))

        def close(self):
            calls.append("close")

    class FakeSaver:
        def __init__(self, pool, *, serde):
            calls.append(("saver", pool, serde))

        def setup(self):
            calls.append("setup")

    import recruitment_team.open_agent.checkpoint_store as module

    monkeypatch.setattr(module, "ConnectionPool", FakePool)
    monkeypatch.setattr(module, "PostgresSaver", FakeSaver)

    saver, close = build_checkpoint_store(
        "postgresql+psycopg2://host/db",
        "unused.db",
    )

    assert isinstance(saver, FakeSaver)
    assert calls[0][1]["conninfo"] == "postgresql://host/db"
    assert calls[1] == ("open", True)
    assert calls[-1] == "setup"
    close()
    assert calls[-1] == "close"
