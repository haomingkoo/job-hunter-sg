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

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([_job(1, days_ago=1), _job(2, days_ago=400)])
        db.commit()

    monkeypatch.setattr(backfill_embeddings, "SessionLocal", sessions)
    monkeypatch.setattr(
        backfill_embeddings,
        "encode_texts",
        lambda texts, batch_size: [[0.1] * 384 for _text in texts],
    )

    backfill_embeddings.backfill()

    with sessions() as db:
        assert db.get(ScrapedJob, 1).embedding_vector == [0.1] * 384
        assert db.get(ScrapedJob, 2).embedding_vector is None
        marker = db.query(UsageLog).filter_by(action="job_embedding_refresh").one()
        assert marker.detail == "processed=1"
