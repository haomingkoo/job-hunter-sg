from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import cleanup_legacy_jobs
from database import Base
from models import ScrapedJob


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _seed(factory, *, candidates: int) -> None:
    db = factory()
    db.add_all(
        [
            ScrapedJob(
                title=f"Legacy {index}",
                company="Example",
                dedup_key=f"legacy-{index}",
                hidden=1,
            )
            for index in range(candidates)
        ]
        + [
            ScrapedJob(
                title="Visible",
                company="Example",
                dedup_key="visible",
                hidden=0,
            )
        ]
    )
    db.commit()
    db.close()


def test_dry_run_reports_candidates_without_deleting(monkeypatch):
    engine, factory = _database()
    _seed(factory, candidates=2)
    monkeypatch.setattr(cleanup_legacy_jobs, "SessionLocal", factory)

    result = cleanup_legacy_jobs.cleanup_legacy_jobs(execute=False)

    assert result == {
        "mode": "dry-run",
        "initial_candidates": 2,
        "deleted": 0,
        "final_candidates": 2,
        "backup_id": "",
    }
    assert factory().query(ScrapedJob).count() == 3
    engine.dispose()


@pytest.mark.parametrize(
    ("expected_candidates", "backup_id", "message"),
    [
        (None, str(uuid4()), "--expected-candidates"),
        (1, "not-a-backup-id", "--backup-id"),
    ],
)
def test_execute_requires_count_and_backup_evidence(
    expected_candidates,
    backup_id,
    message,
):
    with pytest.raises(ValueError, match=message):
        cleanup_legacy_jobs.cleanup_legacy_jobs(
            execute=True,
            expected_candidates=expected_candidates,
            backup_id=backup_id,
        )


def test_execute_refuses_a_stale_candidate_count(monkeypatch):
    engine, factory = _database()
    _seed(factory, candidates=1)
    monkeypatch.setattr(cleanup_legacy_jobs, "SessionLocal", factory)

    with pytest.raises(RuntimeError, match="candidate count changed"):
        cleanup_legacy_jobs.cleanup_legacy_jobs(
            execute=True,
            expected_candidates=2,
            backup_id=str(uuid4()),
        )

    assert factory().query(ScrapedJob).count() == 2
    engine.dispose()


def test_execute_deletes_exact_candidate_count_in_bounded_batches(monkeypatch):
    engine, factory = _database()
    _seed(factory, candidates=3)
    monkeypatch.setattr(cleanup_legacy_jobs, "SessionLocal", factory)
    backup_id = str(uuid4())

    result = cleanup_legacy_jobs.cleanup_legacy_jobs(
        execute=True,
        expected_candidates=3,
        backup_id=backup_id,
        batch_size=2,
    )

    assert result == {
        "mode": "execute",
        "initial_candidates": 3,
        "deleted": 3,
        "final_candidates": 0,
        "backup_id": backup_id,
    }
    assert [job.dedup_key for job in factory().query(ScrapedJob)] == ["visible"]
    engine.dispose()
