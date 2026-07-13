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
def jobs_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = testing_session()
    now = datetime.now(timezone.utc)
    rows = [
        ("Central match", "Central Area", "3-5", 5_000),
        ("Central unstated", "Central Area", "", 0),
        ("West senior", "West Region", "7+", 9_000),
        ("East entry", "East Region", "2", 3_000),
        ("Central substring", "Central Business District", "3", 8_000),
    ]
    for index, (title, location, experience, salary_floor) in enumerate(rows):
        posted_at = (now - timedelta(minutes=index)).isoformat()
        db.add(
            ScrapedJob(
                title=title,
                company="Example Employer",
                location=location,
                salary=f"${salary_floor}",
                salary_floor=salary_floor,
                source="MyCareersFuture",
                source_posting_id=f"mcf-{index}",
                dedup_key=f"server-filter-{index}",
                posted_at_sort=posted_at,
                scraped_at=posted_at,
                parsed_jd={"experience_years": experience},
            )
        )
    db.commit()

    def override_db():
        yield db

    main._filter_meta_cache = {}
    main._filter_meta_ts = 0.0
    main.app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()


def test_location_and_experience_filters_apply_before_pagination(jobs_client):
    response = jobs_client.get(
        "/api/jobs",
        params={
            "location": "Central Area",
            "experience": "3-5 yrs",
            "page": 1,
            "per_page": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["pages"] == 2
    assert [job["title"] for job in payload["jobs"]] == ["Central match"]
    assert {item["value"]: item["count"] for item in payload["filter_meta"]["locations"]} == {
        "Central Area": 2,
        "Central Business District": 1,
        "East Region": 1,
        "West Region": 1,
    }


def test_multiple_locations_and_salary_sort_are_server_side(jobs_client):
    response = jobs_client.get(
        "/api/jobs",
        params=[
            ("location", "Central Area"),
            ("location", "West Region"),
            ("sort", "salary"),
            ("per_page", "2"),
        ],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["pages"] == 2
    assert [job["title"] for job in payload["jobs"]] == ["West senior", "Central match"]


def test_invalid_experience_bucket_is_rejected(jobs_client):
    response = jobs_client.get("/api/jobs", params={"experience": "many years"})

    assert response.status_code == 422
