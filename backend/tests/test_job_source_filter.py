from datetime import datetime, timezone

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
            ),
            ScrapedJob(
                title="Policy Analyst",
                company="Singapore Public Service",
                source="Careers@Gov",
                source_posting_id="cgov-1",
                dedup_key="cgov-key",
                posted_at_sort=now,
                scraped_at=now,
            ),
        ]
    )
    db.commit()

    def override_db():
        try:
            yield db
        finally:
            pass

    main._filter_meta_cache = {}
    main._filter_meta_ts = 0.0
    main.app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(main.app).get("/api/jobs", params={"source": "Careers@Gov"})
    finally:
        main.app.dependency_overrides.pop(get_db, None)
        db.close()
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [job["source"] for job in payload["jobs"]] == ["Careers@Gov"]
