from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import ScrapedJob, UsageLog


def _job(job_id: int, *, days_ago: int) -> ScrapedJob:
    return ScrapedJob(
        id=job_id,
        title="Semiconductor Quality Manager",
        company="Example Direct Employer",
        description="Lead quality transformation and deviation management.",
        url=f"https://example.test/{job_id}",
        source="test",
        dedup_key=f"embedding-{job_id}",
        posted_at_sort=(
            datetime.now(timezone.utc) - timedelta(days=days_ago)
        ).isoformat(),
    )


def _unit_vector(index: int = 0, *, scale: float = 1.0) -> list[float]:
    import embedding_service

    vector = [0.0] * embedding_service.EMBEDDING_DIMENSION
    vector[index] = scale
    return vector


def test_backfill_embeds_only_current_visible_jobs_and_publishes_generation(monkeypatch):
    import backfill_embeddings
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([_job(1, days_ago=1), _job(2, days_ago=400)])
        db.commit()

    monkeypatch.setattr(backfill_embeddings, "SessionLocal", sessions)
    monkeypatch.setattr(
        embedding_service,
        "encode_texts",
        lambda texts, batch_size: [_unit_vector() for _text in texts],
    )

    backfill_embeddings.backfill()

    with sessions() as db:
        embedded = db.get(ScrapedJob, 1)
        assert embedded.embedding_vector == _unit_vector()
        assert len(embedded.embedding_input_sha256) == 64
        assert embedded.embedding_model_identity == backfill_embeddings.EMBEDDING_MODEL_IDENTITY
        assert db.get(ScrapedJob, 2).embedding_vector is None
        marker = db.query(UsageLog).filter_by(action="job_embedding_refresh").one()
        assert marker.detail == (
            "scanned=1;refreshed=1;vector_rewrites=1;unresolved=0;complete=1;"
            f"model={backfill_embeddings.EMBEDDING_MODEL_IDENTITY}"
        )
        assert db.query(UsageLog).filter_by(action="job_embedding_ready").count() == 1


def test_clock_only_expiry_does_not_invalidate_completed_embedding_scan(monkeypatch):
    import embedding_service
    import job_visibility

    baseline = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        current = baseline

        @classmethod
        def now(cls, tz=None):
            current = cls.current
            return current if tz is not None else current.replace(tzinfo=None)

    monkeypatch.setattr(job_visibility, "datetime", FixedDateTime)
    monkeypatch.setattr(
        embedding_service,
        "encode_texts",
        lambda texts, batch_size: [_unit_vector() for _text in texts],
    )

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        expiring = _job(1, days_ago=1)
        expiring.posted_at_sort = (baseline - timedelta(days=59)).isoformat()
        expiring.scraped_at = baseline.isoformat()
        current = _job(2, days_ago=1)
        current.posted_at_sort = (baseline - timedelta(days=1)).isoformat()
        current.scraped_at = baseline.isoformat()
        db.add_all([expiring, current])
        db.commit()

        result = embedding_service.refresh_job_embeddings(db)
        assert result["searchable"] == 2
        assert embedding_service.embedding_readiness_is_current(db) is True

        FixedDateTime.current = baseline + timedelta(days=2)

        assert embedding_service.get_job_search_readiness(db)["searchable_jobs"] == 1
        assert embedding_service.embedding_readiness_is_current(db) is True


def test_explicit_corpus_generation_invalidates_same_shape_visibility_swap(monkeypatch):
    import embedding_service

    monkeypatch.setattr(
        embedding_service,
        "encode_texts",
        lambda texts, batch_size: [_unit_vector() for _text in texts],
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        first = _job(1, days_ago=1)
        second = _job(2, days_ago=1)
        second.hidden = 1
        db.add_all([first, second])
        db.commit()
        embedding_service.refresh_job_embeddings(db)
        previous_marker = embedding_service.embedding_readiness_marker(db)
        assert embedding_service.embedding_readiness_is_current(db) is True

        embedding_service.begin_job_corpus_generation(db, "test_swap")
        first.hidden = 1
        second.hidden = 0
        db.commit()

        assert embedding_service.embedding_readiness_marker(db) != previous_marker
        assert embedding_service.embedding_readiness_is_current(db) is False


def test_explicit_corpus_generation_invalidates_non_max_content_update(monkeypatch):
    import embedding_service

    monkeypatch.setattr(
        embedding_service,
        "encode_texts",
        lambda texts, batch_size: [_unit_vector() for _text in texts],
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        older = _job(1, days_ago=1)
        older.scraped_at = "2026-08-29T00:00:00+00:00"
        newer = _job(2, days_ago=1)
        newer.scraped_at = "2026-08-30T00:00:00+00:00"
        db.add_all([older, newer])
        db.commit()
        embedding_service.refresh_job_embeddings(db)
        previous_marker = embedding_service.embedding_readiness_marker(db)

        embedding_service.begin_job_corpus_generation(db, "test_update")
        older = db.get(ScrapedJob, 1)
        older.title = "Finance Transformation Lead"
        embedding_service.invalidate_job_embedding_if_stale(older)
        db.commit()

        assert embedding_service.embedding_readiness_marker(db) != previous_marker
        assert embedding_service.embedding_readiness_is_current(db) is False


def test_backfill_reembeds_a_vector_without_current_provenance(monkeypatch):
    import backfill_embeddings
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        job = _job(1, days_ago=1)
        job.embedding_vector = _unit_vector()
        job.embedding_input_sha256 = "0" * 64
        job.embedding_model_identity = backfill_embeddings.EMBEDDING_MODEL_IDENTITY
        db.add(job)
        db.commit()

    monkeypatch.setattr(backfill_embeddings, "SessionLocal", sessions)
    monkeypatch.setattr(
        embedding_service,
        "encode_texts",
        lambda texts, batch_size: [_unit_vector(1) for _text in texts],
    )

    backfill_embeddings.backfill()

    with sessions() as db:
        embedded = db.get(ScrapedJob, 1)
        assert embedded.embedding_vector == _unit_vector(1)
        assert len(embedded.embedding_input_sha256) == 64
        assert embedded.embedding_model_identity == backfill_embeddings.EMBEDDING_MODEL_IDENTITY


def test_missing_only_embeds_new_jobs_without_rewriting_legacy_vectors(monkeypatch):
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        legacy = _job(1, days_ago=1)
        legacy.embedding_vector = _unit_vector()
        missing = _job(2, days_ago=1)
        db.add_all([legacy, missing])
        db.commit()
        monkeypatch.setattr(
            embedding_service,
            "encode_texts",
            lambda texts, batch_size: [_unit_vector(1) for _text in texts],
        )

        result = embedding_service.refresh_job_embeddings(db, missing_only=True)

        assert result == {
            "searchable": 2,
            "scanned": 2,
            "refreshed": 1,
            "vector_rewrites": 1,
            "unresolved": 1,
            "complete": False,
        }
        assert db.get(ScrapedJob, 1).embedding_vector == _unit_vector()
        assert not db.get(ScrapedJob, 1).embedding_input_sha256
        assert db.get(ScrapedJob, 2).embedding_vector == _unit_vector(1)
        assert db.query(UsageLog).filter_by(action="job_embedding_ready").count() == 0


def test_embedding_refresh_rejects_conflicting_modes():
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        with pytest.raises(ValueError, match="cannot be combined"):
            embedding_service.refresh_job_embeddings(
                db,
                force=True,
                missing_only=True,
            )


def test_backfill_stamps_matching_legacy_vector_without_rewriting_it(monkeypatch):
    import backfill_embeddings
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        job = _job(1, days_ago=1)
        job.embedding_vector = _unit_vector()
        db.add(job)
        db.commit()

    monkeypatch.setattr(backfill_embeddings, "SessionLocal", sessions)
    monkeypatch.setattr(
        embedding_service,
        "encode_texts",
        lambda texts, batch_size: [_unit_vector() for _text in texts],
    )

    backfill_embeddings.backfill()

    with sessions() as db:
        marker = db.query(UsageLog).filter_by(action="job_embedding_refresh").one()
        assert "vector_rewrites=0" in marker.detail
        embedded = db.get(ScrapedJob, 1)
        assert embedded.embedding_vector == _unit_vector()
        assert len(embedded.embedding_input_sha256) == 64


def test_stamp_uses_exact_float32_vector_identity():
    import embedding_service

    stored = np.linspace(-1.0, 1.0, 384, dtype=np.float32)
    stored /= np.linalg.norm(stored)
    distinct = np.nextafter(
        stored,
        np.where(stored >= 0, np.float32(np.inf), np.float32(-np.inf)),
    )
    distinct /= np.linalg.norm(distinct)
    job = _job(1, days_ago=1)
    job.embedding_vector = stored.tolist()

    assert embedding_service.stamp_job_embedding(job, distinct.tolist()) is True
    assert job.embedding_vector == distinct.tolist()

    job.embedding_vector[0] += abs(
        float(np.spacing(np.float32(job.embedding_vector[0])))
    ) / 4
    retained = list(job.embedding_vector)
    assert embedding_service.stamp_job_embedding(job, distinct.tolist()) is False
    assert job.embedding_vector == retained


def test_backfill_rewrites_a_malformed_vector(monkeypatch):
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        broadcastable = _job(1, days_ago=1)
        broadcastable.embedding_vector = [0.3]
        non_broadcastable = _job(2, days_ago=1)
        non_broadcastable.embedding_vector = [0.3] * 383
        db.add_all([broadcastable, non_broadcastable])
        db.commit()
        monkeypatch.setattr(
            embedding_service,
            "encode_texts",
            lambda texts, batch_size: [_unit_vector() for _text in texts],
        )

        result = embedding_service.refresh_job_embeddings(db)

        assert result["vector_rewrites"] == 2
        assert db.get(ScrapedJob, 1).embedding_vector == _unit_vector()
        assert db.get(ScrapedJob, 2).embedding_vector == _unit_vector()


def test_stamp_rewrites_direction_or_scale_changes():
    import embedding_service

    changed_direction = [0.991, (1 - 0.991**2) ** 0.5] + [0.0] * 382
    for stored, current in (
        (_unit_vector(), changed_direction),
        (_unit_vector(scale=2.0), _unit_vector()),
    ):
        job = _job(1, days_ago=1)
        job.embedding_vector = stored

        assert embedding_service.stamp_job_embedding(job, current) is True
        assert job.embedding_vector == np.asarray(current, dtype=np.float32).tolist()


def test_stamp_rewrites_invalid_stored_vectors():
    import embedding_service

    current = _unit_vector()
    for stored in (
        0.3,
        {"bad": "shape"},
        [0.0] * 384,
        [float("inf")] + [0.0] * 383,
        ["bad"] * 384,
    ):
        job = _job(1, days_ago=1)
        job.embedding_vector = stored

        assert embedding_service.stamp_job_embedding(job, current) is True
        assert job.embedding_vector == current


def test_stamp_rejects_invalid_new_vectors_without_certifying_them():
    import embedding_service

    for invalid in (
        [1.0],
        [1.0] + [0.0] * 382,
        [1.0] + [0.0] * 384,
        [0.0] * 384,
        [float("nan")] + [0.0] * 383,
        [float("inf")] + [0.0] * 383,
        [0.3] * 384,
        [[0.3]] * 384,
        ["bad"] * 384,
    ):
        job = _job(1, days_ago=1)
        original = _unit_vector()
        job.embedding_vector = original

        with pytest.raises(ValueError, match="embedding output"):
            embedding_service.stamp_job_embedding(job, invalid)

        assert job.embedding_vector == original
        assert not job.embedding_input_sha256
        assert not job.embedding_model_identity


def test_backfill_validates_the_whole_batch_before_mutating(monkeypatch):
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([_job(1, days_ago=1), _job(2, days_ago=1)])
        db.commit()
        invalid = [float("nan")] + [0.0] * 383
        monkeypatch.setattr(
            embedding_service,
            "encode_texts",
            lambda texts, batch_size: [_unit_vector(), invalid],
        )

        with pytest.raises(ValueError, match="embedding output"):
            embedding_service.refresh_job_embeddings(db)

        assert not db.dirty
        for job_id in (1, 2):
            job = db.get(ScrapedJob, job_id)
            assert job.embedding_vector is None
            assert not job.embedding_input_sha256
            assert not job.embedding_model_identity


@pytest.mark.parametrize("returned_count", [1, 3])
def test_backfill_rejects_encoder_count_mismatch_before_mutating(
    monkeypatch,
    returned_count,
):
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([_job(1, days_ago=1), _job(2, days_ago=1)])
        db.commit()
        monkeypatch.setattr(
            embedding_service,
            "encode_texts",
            lambda texts, batch_size: [_unit_vector() for _ in range(returned_count)],
        )

        with pytest.raises(ValueError, match="unexpected vector count"):
            embedding_service.refresh_job_embeddings(db)

        assert not db.dirty
        assert all(db.get(ScrapedJob, job_id).embedding_vector is None for job_id in (1, 2))


def test_limited_backfill_does_not_publish_false_readiness(monkeypatch):
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([_job(1, days_ago=1), _job(2, days_ago=1)])
        db.commit()
        monkeypatch.setattr(
            embedding_service,
            "encode_texts",
            lambda texts, batch_size: [_unit_vector() for _text in texts],
        )

        result = embedding_service.refresh_job_embeddings(db, limit=1)

        assert result["complete"] is False
        assert embedding_service.embedding_readiness_is_current(db) is False
        assert db.query(UsageLog).filter_by(action="job_embedding_ready").count() == 0
