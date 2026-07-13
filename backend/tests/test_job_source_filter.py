from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from database import Base, get_db
from models import ScrapedJob


def test_jobs_can_be_filtered_by_exact_source():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = TestingSession()
    now = datetime.now(timezone.utc).isoformat()
    db.add_all(
        [
            ScrapedJob(
                title="Data Engineer",
                company="Example One",
                source="MyCareersFuture",
                source_posting_id="mcf-1",
                dedup_key="mcf-key",
                posted_at_sort=now,
                scraped_at=now,
                job_terms_preview=["Python"],
            ),
            ScrapedJob(
                title="Policy Analyst",
                company="Singapore Public Service",
                source="Careers@Gov",
                source_posting_id="cgov-1",
                dedup_key="cgov-key",
                posted_at_sort=now,
                scraped_at=now,
                job_terms_preview=["Policy"],
            ),
            ScrapedJob(
                title="Hidden duplicate",
                company="Example One",
                source="MyCareersFuture",
                source_posting_id="mcf-hidden",
                dedup_key="mcf-hidden-key",
                posted_at_sort=now,
                scraped_at=now,
                hidden=1,
            ),
            ScrapedJob(
                title="Old listing",
                company="Example One",
                source="MyCareersFuture",
                source_posting_id="mcf-old",
                dedup_key="mcf-old-key",
                posted_at_sort=(datetime.now(timezone.utc) - timedelta(days=61)).isoformat(),
                scraped_at=now,
            ),
            ScrapedJob(
                title="Expired policy role",
                company="Singapore Public Service",
                source="Careers@Gov",
                source_posting_id="cgov-expired",
                dedup_key="cgov-expired-key",
                posted_at_sort=now,
                scraped_at=now,
                closing_date=(datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat(),
            ),
        ]
    )
    db.commit()

    def override_db():
        try:
            yield db
        finally:
            pass

    main._clear_analytics_cache()
    main.app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(main.app)
        response = client.get("/api/jobs", params={"source": "Careers@Gov"})
        source_counts = {
            item["value"]: item["count"]
            for item in response.json()["filter_meta"]["sources"]
        }
        assert source_counts == {"Careers@Gov": 1, "MyCareersFuture": 1}
        assert sum(source_counts.values()) == 2
        analytics = client.get("/api/analytics/skills")
        assert analytics.json()["total_jobs_with_terms"] == 2

        db.query(ScrapedJob).filter(ScrapedJob.source_posting_id == "mcf-1").update(
            {"hidden": 1}
        )
        db.commit()
        refreshed = client.get("/api/jobs", params={"source": "Careers@Gov"})
        refreshed_counts = {
            item["value"]: item["count"]
            for item in refreshed.json()["filter_meta"]["sources"]
        }
        assert refreshed_counts == {"Careers@Gov": 1}
        refreshed_analytics = client.get("/api/analytics/skills")
        assert refreshed_analytics.json()["total_jobs_with_terms"] == 1
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        main._clear_analytics_cache()
        db.close()
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [job["source"] for job in payload["jobs"]] == ["Careers@Gov"]
