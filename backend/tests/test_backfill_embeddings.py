from datetime import datetime, timedelta, timezone

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
        lambda texts, batch_size: [[0.1] * 384 for _text in texts],
    )

    backfill_embeddings.backfill()

    with sessions() as db:
        embedded = db.get(ScrapedJob, 1)
        assert embedded.embedding_vector == [0.1] * 384
        assert len(embedded.embedding_input_sha256) == 64
        assert embedded.embedding_model_identity == backfill_embeddings.EMBEDDING_MODEL_IDENTITY
        assert db.get(ScrapedJob, 2).embedding_vector is None
        marker = db.query(UsageLog).filter_by(action="job_embedding_refresh").one()
        assert marker.detail == (
            "scanned=1;refreshed=1;vector_rewrites=1;complete=1;"
            f"model={backfill_embeddings.EMBEDDING_MODEL_IDENTITY}"
        )
        assert db.query(UsageLog).filter_by(action="job_embedding_ready").count() == 1


def test_backfill_reembeds_a_vector_without_current_provenance(monkeypatch):
    import backfill_embeddings
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        job = _job(1, days_ago=1)
        job.embedding_vector = [0.9] * 384
        job.embedding_input_sha256 = "0" * 64
        job.embedding_model_identity = backfill_embeddings.EMBEDDING_MODEL_IDENTITY
        db.add(job)
        db.commit()

    monkeypatch.setattr(backfill_embeddings, "SessionLocal", sessions)
    monkeypatch.setattr(
        embedding_service,
        "encode_texts",
        lambda texts, batch_size: [[0.2] * 384 for _text in texts],
    )

    backfill_embeddings.backfill()

    with sessions() as db:
        embedded = db.get(ScrapedJob, 1)
        assert embedded.embedding_vector == [0.2] * 384
        assert len(embedded.embedding_input_sha256) == 64
        assert embedded.embedding_model_identity == backfill_embeddings.EMBEDDING_MODEL_IDENTITY


def test_backfill_stamps_matching_legacy_vector_without_rewriting_it(monkeypatch):
    import backfill_embeddings
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        job = _job(1, days_ago=1)
        job.embedding_vector = [0.3] * 384
        db.add(job)
        db.commit()

    monkeypatch.setattr(backfill_embeddings, "SessionLocal", sessions)
    monkeypatch.setattr(
        embedding_service,
        "encode_texts",
        lambda texts, batch_size: [[0.3] * 384 for _text in texts],
    )

    backfill_embeddings.backfill()

    with sessions() as db:
        marker = db.query(UsageLog).filter_by(action="job_embedding_refresh").one()
        assert "vector_rewrites=0" in marker.detail
        embedded = db.get(ScrapedJob, 1)
        assert embedded.embedding_vector == [0.3] * 384
        assert len(embedded.embedding_input_sha256) == 64


def test_backfill_does_not_rewrite_platform_float_noise(monkeypatch):
    import embedding_service

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        job = _job(1, days_ago=1)
        job.embedding_vector = [0.3] * 384
        db.add(job)
        db.commit()
        monkeypatch.setattr(
            embedding_service,
            "encode_texts",
            lambda texts, batch_size: [[0.3000001] * 384 for _text in texts],
        )

        result = embedding_service.refresh_job_embeddings(db)

        assert result["vector_rewrites"] == 0
        assert db.get(ScrapedJob, 1).embedding_vector == [0.3] * 384


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
            lambda texts, batch_size: [[0.3] * 384 for _text in texts],
        )

        result = embedding_service.refresh_job_embeddings(db)

        assert result["vector_rewrites"] == 2
        assert db.get(ScrapedJob, 1).embedding_vector == [0.3] * 384
        assert db.get(ScrapedJob, 2).embedding_vector == [0.3] * 384


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
            lambda texts, batch_size: [[0.4] * 384 for _text in texts],
        )

        result = embedding_service.refresh_job_embeddings(db, limit=1)

        assert result["complete"] is False
        assert embedding_service.embedding_readiness_is_current(db) is False
        assert db.query(UsageLog).filter_by(action="job_embedding_ready").count() == 0
