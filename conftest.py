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


@pytest.fixture(scope="session", autouse=True)
def isolated_test_database():
    from database import engine, init_db

    init_db()
    yield
    engine.dispose()
    if _test_database_dir is not None:
        _test_database_dir.cleanup()
