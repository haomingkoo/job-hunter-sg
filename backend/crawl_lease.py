"""Single-flight lease shared by scheduled and API-triggered job crawls."""

from __future__ import annotations

import hashlib
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import text

import database


_POSTGRES_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"job-hunter-sg:job-crawl:v1").digest()[:8],
    byteorder="big",
    signed=True,
)
_LOCAL_LOCK = threading.Lock()


@contextmanager
def job_crawl_lease() -> Iterator[bool]:
    """Yield whether this process owns the one allowed crawl slot.

    PostgreSQL advisory locks coordinate the web and scheduled containers. Local
    SQLite uses a non-blocking file lock as well as a thread lock, so separate
    development processes cannot crawl the same database concurrently.
    """

    engine = database.engine
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            acquired = bool(
                connection.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": _POSTGRES_LOCK_KEY},
                ).scalar()
            )
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": _POSTGRES_LOCK_KEY},
                    )
        return

    acquired = _LOCAL_LOCK.acquire(blocking=False)
    if not acquired:
        yield False
        return

    lock_file = None
    file_locked = False
    try:
        database_path = engine.url.database
        if database_path and database_path != ":memory:":
            try:
                import fcntl
            except ImportError:
                # Windows has no fcntl. The thread lock still keeps a local
                # SQLite process safe; hosted multi-process use is PostgreSQL.
                yield True
                return

            database_key = hashlib.sha256(
                str(Path(database_path).expanduser().resolve()).encode()
            ).hexdigest()[:16]
            lock_path = Path(tempfile.gettempdir()) / f"job-hunter-crawl-{database_key}.lock"
            lock_file = lock_path.open("a+")
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if lock_file is not None:
                    lock_file.close()
                    lock_file = None
                yield False
                return
            file_locked = True
        yield True
    finally:
        if lock_file is not None:
            if file_locked:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
        _LOCAL_LOCK.release()
