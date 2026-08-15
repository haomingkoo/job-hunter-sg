from datetime import datetime, time as datetime_time, timedelta, timezone
from zoneinfo import ZoneInfo

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


@pytest.fixture()
def dated_jobs_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = testing_session()
    singapore = ZoneInfo("Asia/Singapore")
    selected_date = datetime.now(singapore).date()
    start = datetime.combine(selected_date, datetime_time.min, singapore).astimezone(timezone.utc)
    next_start = start + timedelta(days=1)
    rows = [
        ("Boundary start", start.isoformat(), "Central Area", 8_000),
        # Writers before #224 stored UTC without an offset. Keep both real shapes
        # around the Singapore boundary to lock compatibility.
        ("Boundary end", (next_start - timedelta(microseconds=1)).replace(tzinfo=None).isoformat(), "Central Area", 7_000),
        ("Before boundary", (start - timedelta(microseconds=1)).replace(tzinfo=None).isoformat(), "Central Area", 9_000),
        ("After boundary", next_start.isoformat(), "Central Area", 10_000),
        ("Wrong source", (start + timedelta(hours=1)).isoformat(), "West Region", 12_000),
    ]
    for index, (title, timestamp, location, salary_floor) in enumerate(rows):
        db.add(
            ScrapedJob(
                title=title,
                company="Example Employer",
                location=location,
                salary=f"${salary_floor}",
                salary_floor=salary_floor,
                source="Careers@Gov" if title == "Wrong source" else "MyCareersFuture",
                source_posting_id=f"dated-{index}",
                dedup_key=f"dated-filter-{index}",
                posted_at_sort=timestamp if timestamp.endswith("+00:00") else f"{timestamp}+00:00",
                scraped_at=timestamp,
                seniority="Senior",
                description="Build a Python data platform.",
                parsed_jd={"experience_years": "5"},
            )
        )
    db.commit()

    def override_db():
        yield db

    main._filter_meta_cache = {}
    main._filter_meta_ts = 0.0
    main.app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(main.app), selected_date.isoformat()
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


def test_posted_and_scraped_ranges_use_inclusive_singapore_days(dated_jobs_client):
    client, selected_date = dated_jobs_client

    response = client.get(
        "/api/jobs",
        params={
            "posted_from": selected_date,
            "posted_to": selected_date,
            "scraped_from": selected_date,
            "scraped_to": selected_date,
            "sort": "newest",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert [job["title"] for job in payload["jobs"]] == [
        "Boundary end",
        "Wrong source",
        "Boundary start",
    ]


def test_date_ranges_compose_before_count_and_pagination(dated_jobs_client):
    client, selected_date = dated_jobs_client

    response = client.get(
        "/api/jobs",
        params={
            "q": "Boundary",
            "source": "MyCareersFuture",
            "location": "Central Area",
            "seniority": "Senior",
            "min_salary": 6_000,
            "direct_employers_only": True,
            "posted_from": selected_date,
            "scraped_to": selected_date,
            "sort": "salary",
            "per_page": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["pages"] == 2
    assert [job["title"] for job in payload["jobs"]] == ["Boundary start"]


@pytest.mark.parametrize(
    ("start_name", "end_name"),
    [("posted_from", "posted_to"), ("scraped_from", "scraped_to")],
)
def test_reversed_date_ranges_are_rejected(dated_jobs_client, start_name, end_name):
    client, selected_date = dated_jobs_client
    next_date = (datetime.fromisoformat(selected_date) + timedelta(days=1)).date().isoformat()

    response = client.get(
        "/api/jobs",
        params={start_name: next_date, end_name: selected_date},
    )

    assert response.status_code == 422
    assert "from date must be on or before to date" in response.json()["detail"]


def test_invalid_date_is_rejected_by_fastapi(dated_jobs_client):
    client, _selected_date = dated_jobs_client

    response = client.get("/api/jobs", params={"posted_from": "not-a-date"})

    assert response.status_code == 422
