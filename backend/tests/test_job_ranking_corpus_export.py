from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import ScrapedJob
from scripts.export_job_ranking_corpus import export


def _job(job_id: int, *, posted_at: datetime) -> ScrapedJob:
    return ScrapedJob(
        id=job_id,
        title=f"Role {job_id}",
        company="Direct Employer",
        description="Public job text.",
        source="MyCareersFuture",
        source_posting_id=f"source-{job_id}",
        dedup_key=f"job-{job_id}",
        posted_at_sort=posted_at.isoformat(),
    )


def test_export_uses_one_injected_snapshot_time(tmp_path, monkeypatch):
    import scripts.export_job_ranking_corpus as exporter

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    as_of = datetime(2026, 8, 25, tzinfo=timezone.utc)
    with sessions() as db:
        db.add_all([
            _job(1, posted_at=as_of - timedelta(days=1)),
            _job(2, posted_at=as_of - timedelta(days=61)),
        ])
        db.commit()
    monkeypatch.setattr(exporter, "SessionLocal", sessions)
    output = tmp_path / "corpus.jsonl"

    receipt = export(output, as_of)
    records = [json.loads(line) for line in output.read_text().splitlines()]

    assert receipt["job_count"] == 1
    assert [record["key"] for record in records] == ["MyCareersFuture:source-1"]
    assert len(receipt["sha256"]) == 64
