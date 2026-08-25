from datetime import datetime, time as datetime_time, timedelta, timezone
from zoneinfo import ZoneInfo
import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from database import Base, get_db
from employer_filter import EMPLOYER_RELATIONSHIP_PRECOMPUTE_MARKER
from models import ScrapedJob, UsageLog


def test_job_search_readiness_requires_a_bound_exact_provenance_scan(jobs_client):
    import embedding_service

    db = jobs_client.test_db
    for job in db.query(ScrapedJob).all():
        embedding_service.stamp_job_embedding(job, [1.0] + [0.0] * 383)
    db.commit()

    unproven = jobs_client.get("/api/job-search/readiness").json()
    assert unproven["current_embeddings"] == unproven["searchable_jobs"]
    assert unproven["content_provenance_verified"] is False
    assert unproven["ready"] is False
    assert unproven["employer_classifier_current"] is False

    db.add(UsageLog(
        action="job_embedding_ready",
        detail=embedding_service.embedding_readiness_marker(db),
    ))
    db.add(
        UsageLog(
            action="job_precompute",
            detail=EMPLOYER_RELATIONSHIP_PRECOMPUTE_MARKER,
        )
    )
    db.commit()

    proven = jobs_client.get("/api/job-search/readiness").json()
    assert proven["content_provenance_verified"] is True
    assert proven["employer_classifier_current"] is True
    assert proven["ready"] is True

    newest = db.query(ScrapedJob).order_by(ScrapedJob.id.desc()).first()
    newest.scraped_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    changed = jobs_client.get("/api/job-search/readiness").json()
    assert changed["content_provenance_verified"] is False
    assert changed["ready"] is False


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
                direct_employer=1,
                employer_relationship="unknown",
                employer_relationship_evidence="mcf_no_relationship_signal",
            )
        )
    db.commit()

    def override_db():
        yield db

    main._filter_meta_cache = {}
    main._filter_meta_ts = 0.0
    main.app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(main.app)
        client.test_db = db
        yield client
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
                direct_employer=1,
                employer_relationship="unknown",
                employer_relationship_evidence=(
                    "legacy_no_relationship_signal"
                    if title == "Wrong source"
                    else "mcf_no_relationship_signal"
                ),
            )
        )
    db.add(
        UsageLog(
            action="job_precompute",
            detail=EMPLOYER_RELATIONSHIP_PRECOMPUTE_MARKER,
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


def test_persisted_power_scores_filter_before_count_and_pagination(jobs_client):
    from auth import create_token
    from models import PowerMatchSnapshot, User, UserMemory

    db = jobs_client.test_db
    user = User(
        email=f"scored-browse-{secrets.token_hex(6)}@example.com",
        password_hash="test-only",  # pragma: allowlist secret
        name="Scored Browse",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    resume_text = ("Experienced Python platform engineer delivering reliable AI systems. " * 3).strip()
    db.add(UserMemory(user_id=user.id, resume_text=resume_text))
    jobs = db.query(ScrapedJob).order_by(ScrapedJob.id).all()
    recommendations = [
        {
            "job": {"id": jobs[0].id},
            "suitability_score": 80,
            "suitability_label": "Strong Match",
        },
        {
            "job": {"id": jobs[1].id},
            "suitability_score": 60,
            "suitability_label": "Good Match",
        },
        {
            "job": {"id": jobs[3].id},
            "suitability_score": 40,
            "suitability_label": "Stretch Match",
        },
    ]
    corpus_marker = f"{main._job_corpus_marker(db)}:direct=0"
    snapshot = PowerMatchSnapshot(
        user_id=user.id,
        resume_hash=main._resume_snapshot_hash(resume_text),
        corpus_marker=corpus_marker,
        limit=main._BROWSE_POWER_MATCH_LIMIT,
        result={
            "result_version": main._POWER_MATCH_RESULT_VERSION,
            "resume_ready": True,
            "recommendations": recommendations,
        },
    )
    db.add(snapshot)
    db.commit()
    main._power_match_cache.pop(user.id, None)
    headers = {"Authorization": f"Bearer {create_token(user.id, user.token_version)}"}

    response = jobs_client.get(
        "/api/jobs",
        params={"min_match_score": 55, "per_page": 1, "page": 1},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["total"] == 2
    assert payload["pages"] == 2
    assert payload["power_match"]["status"] == "ready"
    assert payload["jobs"][0]["power_match_score"] == 80
    assert payload["jobs"][0]["power_match_label"] == "Strong Match"

    second_page = jobs_client.get(
        "/api/jobs",
        params={"min_match_score": 55, "per_page": 1, "page": 2},
        headers=headers,
    ).json()
    assert second_page["jobs"][0]["power_match_score"] == 60
    assert all(job.get("power_match_score") != 0 for job in payload["jobs"] + second_page["jobs"])

    anonymous = jobs_client.get("/api/jobs")
    assert anonymous.status_code == 200
    assert "power_match" not in anonymous.json()
    assert all("power_match_score" not in job for job in anonymous.json()["jobs"])
    denied = jobs_client.get("/api/jobs", params={"min_match_score": 55})
    assert denied.status_code == 401

    main._power_match_cache.pop(user.id, None)


def test_power_match_readiness_is_read_only_and_typed_for_invalidations(jobs_client, monkeypatch):
    from auth import create_token
    from models import PowerMatchSnapshot, User, UserMemory

    db = jobs_client.test_db
    user = User(
        email=f"readiness-{secrets.token_hex(6)}@example.com",
        password_hash="test-only",  # pragma: allowlist secret
        name="Readiness",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    resume_text = ("Experienced Python platform engineer delivering reliable AI systems. " * 3).strip()
    memory = UserMemory(user_id=user.id, resume_text=resume_text)
    db.add(memory)
    snapshot = PowerMatchSnapshot(
        user_id=user.id,
        resume_hash=main._resume_snapshot_hash(resume_text),
        corpus_marker=f"{main._job_corpus_marker(db)}:direct=0",
        limit=main._BROWSE_POWER_MATCH_LIMIT,
        result={
            "result_version": main._POWER_MATCH_RESULT_VERSION,
            "resume_ready": True,
            "recommendations": [],
        },
    )
    db.add(snapshot)
    db.commit()
    headers = {"Authorization": f"Bearer {create_token(user.id, user.token_version)}"}
    monkeypatch.setattr(
        main,
        "_consume_ai_credit",
        lambda *_args, **_kwargs: pytest.fail("readiness must not consume quota"),
    )

    main._power_match_cache.pop(user.id, None)
    ready = jobs_client.get("/api/jobs/power-match/readiness", headers=headers)
    assert ready.status_code == 200
    assert ready.headers["cache-control"] == "no-store"
    assert ready.json()["status"] == "ready"
    main._power_match_cache.pop(user.id, None)
    employer_mode = jobs_client.get(
        "/api/jobs/power-match/readiness",
        params={"direct_employers_only": "true"},
        headers=headers,
    )
    assert employer_mode.json()["reason"] == "employer_mode_changed"

    main._power_match_cache.pop(user.id, None)
    memory.resume_text = "Changed resume with different evidence and platform leadership. " * 3
    db.commit()
    assert jobs_client.get("/api/jobs/power-match/readiness", headers=headers).json()["reason"] == "resume_changed"

    memory.resume_text = resume_text
    corpus_timestamp = datetime.now(timezone.utc).isoformat()
    db.add(ScrapedJob(
        title="New corpus job",
        company="New Co",
        dedup_key=f"new-{secrets.token_hex(6)}",
        posted_at_sort=corpus_timestamp,
        scraped_at=corpus_timestamp,
    ))
    db.commit()
    main._power_match_cache.pop(user.id, None)
    assert jobs_client.get("/api/jobs/power-match/readiness", headers=headers).json()["reason"] == "corpus_changed"

    snapshot.corpus_marker = f"{main._job_corpus_marker(db)}:direct=0"
    snapshot.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()
    main._power_match_cache.pop(user.id, None)
    assert jobs_client.get("/api/jobs/power-match/readiness", headers=headers).json()["reason"] == "snapshot_stale"

    db.delete(snapshot)
    db.commit()
    main._power_match_cache.pop(user.id, None)
    assert jobs_client.get("/api/jobs/power-match/readiness", headers=headers).json()["reason"] == "snapshot_missing"
    blocked_filter = jobs_client.get(
        "/api/jobs",
        params={"min_match_score": 55},
        headers=headers,
    )
    assert blocked_filter.status_code == 409
    assert blocked_filter.headers["cache-control"] == "no-store"
    assert blocked_filter.json()["detail"]["code"] == "power_match_not_ready"
    assert blocked_filter.json()["detail"]["reason"] == "snapshot_missing"
