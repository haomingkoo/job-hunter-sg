"""Keep every pytest run isolated from the developer and production databases."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_test_database_dir: tempfile.TemporaryDirectory[str] | None = None
test_database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
if not test_database_url:
    _test_database_dir = tempfile.TemporaryDirectory(prefix="jobhunter-pytest-")
    test_database_url = f"sqlite:///{Path(_test_database_dir.name) / 'test.db'}"

# Never let an ambient DATABASE_URL point tests at a developer or production DB.
os.environ["DATABASE_URL"] = test_database_url

# The open-agent checkpointer opens config.OPEN_AGENT_CHECKPOINT_DB_PATH at import
# time (open_agent/runner.py:103), and its default is a repo-relative file. Left
# alone, a test run accumulates LangGraph checkpoints in the working tree and two
# runs can resume each other's paused graphs. Pin it to the same temp directory
# the test database uses.
if not os.environ.get("OPEN_AGENT_CHECKPOINT_DB_PATH", "").strip():
    _checkpoint_dir = _test_database_dir.name if _test_database_dir else tempfile.mkdtemp()
    os.environ["OPEN_AGENT_CHECKPOINT_DB_PATH"] = str(
        Path(_checkpoint_dir) / "open_agent_checkpoints.db"
    )


@pytest.fixture(scope="session", autouse=True)
def isolated_test_database():
    from database import engine, init_db

    init_db()
    yield
    engine.dispose()
    if _test_database_dir is not None:
        _test_database_dir.cleanup()
