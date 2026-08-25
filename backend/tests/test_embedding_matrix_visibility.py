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
import pytest


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _add_job(db, posted_at_sort: str, hidden: int = 0):
    import embedding_service
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
        embedding_vector=[1.0] + [0.0] * 383,
        embedding_input_sha256=embedding_service.job_embedding_input_sha256(
            f"role-{tag}",
            "",
            None,
        ),
        embedding_model_identity=embedding_service.EMBEDDING_MODEL_IDENTITY,
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


def test_matrix_fails_closed_when_a_public_vector_lacks_current_provenance():
    import embedding_service
    from database import SessionLocal

    db = SessionLocal()
    legacy = None
    try:
        _add_job(db, _iso(1))
        legacy = _add_job(db, _iso(1))
        legacy.embedding_input_sha256 = ""
        legacy.embedding_model_identity = ""
        db.commit()

        embedding_service.invalidate_matrix_cache()
        with pytest.raises(embedding_service.EmbeddingIndexUnavailable):
            embedding_service.find_similar_jobs([0.1] * 384, db, top_k=10)
        with pytest.raises(embedding_service.EmbeddingIndexUnavailable):
            embedding_service.find_similar_jobs_for_ids(
                [0.1] * 384,
                db,
                {legacy.id},
                top_k=1,
            )
    finally:
        if legacy is not None:
            embedding_service.stamp_job_embedding(legacy, legacy.embedding_vector)
            db.commit()
            embedding_service.invalidate_matrix_cache()
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


def test_eligible_jobs_are_filtered_before_top_k():
    import embedding_service
    from database import SessionLocal

    query_vector = [1.0] + [0.0] * 383
    db = SessionLocal()
    try:
        higher_scoring = _add_job(db, _iso(1))
        eligible = _add_job(db, _iso(1))
        higher_scoring.embedding_vector = query_vector
        eligible.embedding_vector = [0.2, 0.98] + [0.0] * 382
        db.commit()

        embedding_service.invalidate_matrix_cache()
        matches = embedding_service.find_similar_jobs(
            query_vector,
            db,
            top_k=1,
            eligible_job_ids={eligible.id},
        )

        assert [job_id for job_id, _score in matches] == [eligible.id]
        assert higher_scoring.id not in {job_id for job_id, _score in matches}
    finally:
        db.close()


def test_small_eligible_set_does_not_load_the_global_matrix(monkeypatch):
    import embedding_service
    from database import SessionLocal

    query_vector = [1.0] + [0.0] * 383
    db = SessionLocal()
    try:
        eligible = _add_job(db, _iso(1))
        other = _add_job(db, _iso(1))
        eligible.embedding_vector = query_vector
        other.embedding_vector = query_vector
        db.commit()

        def fail_global_load(_db):
            raise AssertionError("global matrix loaded")

        monkeypatch.setattr(embedding_service, "_refresh_matrix_if_stale", fail_global_load)

        matches = embedding_service.find_similar_jobs_for_ids(
            query_vector,
            db,
            {eligible.id},
            top_k=1,
        )

        assert [job_id for job_id, _score in matches] == [eligible.id]
    finally:
        db.close()


def test_rank_ties_use_job_id_as_a_stable_secondary_key():
    import embedding_service

    query = [1.0, 0.0]
    matrix = np.array([[1.0, 0.0]] * 4, dtype=np.float32)

    first = embedding_service.rank_embedding_matrix(
        query,
        [40, 10, 30, 20],
        matrix,
        top_k=2,
    )
    second = embedding_service.rank_embedding_matrix(
        query,
        [20, 30, 10, 40],
        matrix,
        top_k=2,
    )

    assert [job_id for job_id, _score in first] == [10, 20]
    assert [job_id for job_id, _score in second] == [10, 20]


def test_changed_job_text_invalidates_the_stored_embedding():
    import embedding_service

    class Job:
        title = "Quality Manager"
        description = "Lead QMS."
        skills = ["ISO 9001"]
        embedding_vector = [1.0, 0.0]
        embedding_input_sha256 = embedding_service.job_embedding_input_sha256(
            title,
            description,
            skills,
        )
        embedding_model_identity = embedding_service.EMBEDDING_MODEL_IDENTITY

    job = Job()
    assert embedding_service.invalidate_job_embedding_if_stale(job) is False

    job.description = "Lead QMS and CAPA."
    assert embedding_service.invalidate_job_embedding_if_stale(job) is True
    assert job.embedding_vector is None
    assert job.embedding_input_sha256 == ""
    assert job.embedding_model_identity == ""


def test_careersgov_term_refresh_invalidates_changed_embedding(monkeypatch):
    import embedding_service
    import main
    from models import ScrapedJob

    job = ScrapedJob(
        title="Quality Manager",
        company="Public Agency",
        source="Careers@Gov",
        description="Lead the quality system.",
        skills=["quality"],
        dedup_key="careersgov-refresh",
    )
    embedding_service.stamp_job_embedding(job, [1.0] + [0.0] * 383)
    monkeypatch.setattr(main, "_build_canonical_job_terms", lambda *_args: [])
    monkeypatch.setattr(main, "_has_rich_job_terms", lambda _terms: False)
    monkeypatch.setattr(
        main,
        "_derive_careersgov_skill_cues",
        lambda **_kwargs: (["quality systems"], {"required_skills": ["quality systems"]}),
    )
    monkeypatch.setattr(main, "_compute_and_cache_term_preview", lambda *_args: [])

    changed = main._refresh_careersgov_terms_if_weak(job, None)

    assert changed is True
    assert job.embedding_vector is None
    assert job.embedding_input_sha256 == ""
    assert job.embedding_model_identity == ""


def test_experienced_hire_sql_prefilter_plus_python_matches_classification():
    import embedding_service
    from database import SessionLocal
    from job_visibility import experienced_hire_prefilter_condition, is_junior_posting
    from models import ScrapedJob

    cases = [
        ("Fresh/entry level", "Quality Engineer", 0),
        ("Manager", "Production Manager", 0),
        ("Professional", "Graduate Trainee", 0),
        ("Non-executive", "Project Manager", 12_500),
        ("Executive", "Process Engineer", 6_000),
        ("Executive", "Assistant Quality Manager", 4_500),
        ("Senior Executive", "Staff Engineer", 6_000),
        ("Manager", "Quality Manager", 3_500),
    ]
    db = SessionLocal()
    try:
        jobs = []
        for index, (seniority, title, salary_floor) in enumerate(cases, start=1):
            job = _add_job(db, _iso(1))
            job.seniority = seniority
            job.title = title
            job.salary_floor = salary_floor
            embedding_service.stamp_job_embedding(job, job.embedding_vector)
            jobs.append(job)
        db.commit()

        prefiltered_ids = {
            job_id
            for (job_id,) in db.query(ScrapedJob.id).filter(
                ScrapedJob.id.in_([job.id for job in jobs]),
                experienced_hire_prefilter_condition(
                    ScrapedJob.seniority,
                    ScrapedJob.title,
                ),
            )
        }
        sql_ids = {
            job.id
            for job in jobs
            if job.id in prefiltered_ids
            and not is_junior_posting(job.seniority, job.title, job.salary_floor)
        }
        python_ids = {
            job.id for job in jobs
            if not is_junior_posting(job.seniority, job.title, job.salary_floor)
        }

        assert sql_ids == python_ids
    finally:
        db.close()


def test_singapore_sql_prefilter_plus_python_matches_classification():
    import embedding_service
    from database import SessionLocal
    from job_visibility import (
        is_singapore_job_location,
        singapore_job_prefilter_condition,
    )
    from models import ScrapedJob

    db = SessionLocal()
    try:
        jobs = []
        cases = (
            ("Singapore", "Quality Manager"),
            ("Central", "Quality Manager"),
            ("North-East", "Quality Manager"),
            ("Indonesia", "Quality Manager"),
            ("Islandwide", "Quality Manager (Based in Batam)"),
            ("", "Quality Manager"),
        )
        for location, title in cases:
            job = _add_job(db, _iso(1))
            job.location = location
            job.title = title
            embedding_service.stamp_job_embedding(job, job.embedding_vector)
            jobs.append(job)
        db.commit()

        prefiltered_ids = {
            job_id
            for (job_id,) in db.query(ScrapedJob.id).filter(
                ScrapedJob.id.in_([job.id for job in jobs]),
                singapore_job_prefilter_condition(ScrapedJob.location),
            )
        }
        sql_ids = {
            job.id
            for job in jobs
            if job.id in prefiltered_ids
            and is_singapore_job_location(job.location, job.title)
        }
        python_ids = {
            job.id
            for job in jobs
            if is_singapore_job_location(job.location, job.title)
        }

        assert sql_ids == python_ids
    finally:
        db.close()


def test_persisted_embedding_generation_invalidates_another_process_cache():
    import embedding_service
    from database import SessionLocal
    from models import UsageLog

    db = SessionLocal()
    try:
        first = _add_job(db, _iso(1))
        assert first.id in _rebuild_ids(db)

        second = _add_job(db, _iso(1))
        embedding_service._refresh_matrix_if_stale(db)
        assert second.id not in embedding_service._job_ids

        db.add(UsageLog(
            user_id=None,
            action="job_embedding_refresh",
            detail="processed=1",
        ))
        db.commit()
        embedding_service._refresh_matrix_if_stale(db)

        assert second.id in embedding_service._job_ids
    finally:
        db.close()
