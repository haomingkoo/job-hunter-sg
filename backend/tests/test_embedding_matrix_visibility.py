"""The similarity matrix holds only jobs a user could actually be shown.

Ranking the whole embedded history and filtering the winners afterwards starves
as the corpus ages: every nearest neighbour gets discarded after the fact and
search returns nothing while reporting success.
"""

import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _add_job(db, posted_at_sort: str, hidden: int = 0):
    from models import ScrapedJob

    tag = secrets.token_hex(6)
    job = ScrapedJob(
        title=f"role-{tag}",
        company="ACME",
        url=f"https://example.test/{tag}",
        source="test",
        dedup_key=f"test-{tag}",
        posted_at_sort=posted_at_sort,
        hidden=hidden,
        embedding_vector=[0.1] * 384,
    )
    db.add(job)
    db.commit()
    return job


def _rebuild_ids(db) -> list[int]:
    import embedding_service

    embedding_service.invalidate_matrix_cache()
    embedding_service._refresh_matrix_if_stale(db)
    return list(embedding_service._job_ids)


def test_shared_embedding_model_never_runs_parallel_forward_passes(monkeypatch):
    import embedding_service

    active = 0
    peak = 0
    state_lock = threading.Lock()

    class FakeModel:
        def encode(self, text, **_kwargs):
            nonlocal active, peak
            with state_lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with state_lock:
                active -= 1
            count = len(text) if isinstance(text, list) else 1
            values = np.ones((count, 384))
            return values if isinstance(text, list) else values[0]

    monkeypatch.setattr(embedding_service, "_model", FakeModel())
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(embedding_service.encode_text, ("a", "b", "c")))

    assert peak == 1
    assert [len(result) for result in results] == [384, 384, 384]


def test_matrix_excludes_jobs_past_the_age_cutoff():
    from database import SessionLocal

    db = SessionLocal()
    try:
        fresh = _add_job(db, _iso(1))
        stale = _add_job(db, _iso(400))

        ids = _rebuild_ids(db)

        assert fresh.id in ids
        assert stale.id not in ids
    finally:
        db.close()


def test_matrix_excludes_hidden_jobs():
    from database import SessionLocal

    db = SessionLocal()
    try:
        visible = _add_job(db, _iso(1))
        hidden = _add_job(db, _iso(1), hidden=1)

        ids = _rebuild_ids(db)

        assert visible.id in ids
        assert hidden.id not in ids
    finally:
        db.close()


def test_expired_corpus_does_not_starve_the_ranking():
    """The production failure: many embedded rows, almost all of them expired."""
    import embedding_service
    from database import SessionLocal

    db = SessionLocal()
    try:
        fresh = _add_job(db, _iso(2))
        expired = [_add_job(db, _iso(300 + offset)).id for offset in range(20)]

        embedding_service.invalidate_matrix_cache()
        matches = embedding_service.find_similar_jobs([0.1] * 384, db, top_k=10)
        matched_ids = [job_id for job_id, _ in matches]

        assert fresh.id in matched_ids
        assert not set(expired) & set(matched_ids)
    finally:
        db.close()
