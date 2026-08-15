from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from database import Base, get_db
from models import ScrapedJob


@pytest.fixture()
def archive_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = testing_session()
    now = datetime.now(timezone.utc)

    def add_job(title, *, hidden=0, reason="", retired_at="", closing_date="", source="MyCareersFuture", location="Central Area", salary_floor=5000):
        index = db.query(ScrapedJob).count() + 1
        posted = (now - timedelta(minutes=index)).isoformat()
        db.add(ScrapedJob(
            title=title,
            company="Example Employer",
            location=location,
            salary=f"${salary_floor}",
            salary_floor=salary_floor,
            source=source,
            source_posting_id=f"archive-{index}",
            dedup_key=f"archive-{index}",
            posted_at_sort=posted,
            scraped_at=posted,
            hidden=hidden,
            retirement_reason=reason,
            retired_at=retired_at,
            closing_date=closing_date,
        ))

    add_job("Active role")
    add_job("Source retired role", hidden=1, reason="source_retired", retired_at=now.isoformat())
    add_job("Age retired role", hidden=1, reason="age_retired", retired_at=now.isoformat())
    add_job("Legacy hidden duplicate", hidden=1)
    add_job("Closed role", closing_date=(now.date() - timedelta(days=1)).isoformat())
    db.commit()

    def override_db():
        yield db

    main._filter_meta_cache = {}
    main._filter_meta_ts = 0.0
    main.app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(main.app), db
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()


def test_active_and_expired_views_are_truthfully_separated(archive_client):
    client, _ = archive_client

    active = client.get("/api/jobs").json()
    expired = client.get("/api/jobs", params={"view": "expired"}).json()

    assert active["view"] == "active"
    assert [job["title"] for job in active["jobs"]] == ["Active role"]
    assert expired["view"] == "expired"
    assert {job["title"] for job in expired["jobs"]} == {
        "Source retired role", "Age retired role", "Closed role",
    }
    assert "Legacy hidden duplicate" not in {job["title"] for job in expired["jobs"]}
    reasons = {job["title"]: job["archive_reason"] for job in expired["jobs"]}
    assert reasons == {
        "Source retired role": "source_retired",
        "Age retired role": "age_retired",
        "Closed role": "closing_date",
    }
    assert all(job["last_seen"] for job in expired["jobs"])


def test_archive_filters_before_count_and_pagination(archive_client):
    client, _ = archive_client
    response = client.get(
        "/api/jobs",
        params={"view": "expired", "q": "retired", "source": "MyCareersFuture", "per_page": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["pages"] == 2
    assert len(payload["jobs"]) == 1


def test_age_retirement_records_evidence(archive_client):
    _, db = archive_client
    old = db.query(ScrapedJob).filter(ScrapedJob.title == "Active role").one()
    old.scraped_at = "2020-01-01T00:00:00+00:00"
    db.commit()

    retired = main._retire_jobs_older_than(
        db,
        datetime.now(timezone.utc) - timedelta(days=30),
        "2026-08-15T00:00:00+00:00",
    )
    db.commit()

    db.refresh(old)
    assert retired == 1
    assert old.hidden == 1
    assert old.retirement_reason == "age_retired"
    assert old.retired_at == "2026-08-15T00:00:00+00:00"


def test_invalid_archive_view_is_rejected(archive_client):
    client, _ = archive_client
    assert client.get("/api/jobs", params={"view": "unknown"}).status_code == 422
