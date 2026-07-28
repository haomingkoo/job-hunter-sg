"""The default job feed must not let one high-volume reposter own a page.

Production evidence (2026-07-29): page 1 of /api/jobs was 20/20 recruitment-agency
and MLM listings, owned by six companies, because the default sort is newest-first
and those companies repost constantly.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import config
import main
from database import Base, get_db
from models import ScrapedJob


SPAM_COMPANY = "GROWTH SYNDICATE"


@pytest.fixture()
def feed_client():
    """Newest 12 postings all belong to one company; 4 other employers are older."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    db = testing_session()
    now = datetime.now(timezone.utc)

    index = 0
    for _ in range(12):
        posted_at = (now - timedelta(minutes=index)).isoformat()
        db.add(
            ScrapedJob(
                title=f"Entry-Level Sales | Weekly Pay #{index}",
                company=SPAM_COMPANY,
                location="Singapore",
                source="MyCareersFuture",
                source_posting_id=f"mcf-spam-{index}",
                dedup_key=f"feed-diversity-spam-{index}",
                posted_at_sort=posted_at,
                scraped_at=posted_at,
            )
        )
        index += 1

    for employer in ("Acme Pte Ltd", "Beta Labs", "Gamma Health", "Delta Systems"):
        posted_at = (now - timedelta(minutes=index)).isoformat()
        db.add(
            ScrapedJob(
                title=f"Software Engineer at {employer}",
                company=employer,
                location="Singapore",
                source="MyCareersFuture",
                source_posting_id=f"mcf-real-{index}",
                dedup_key=f"feed-diversity-real-{index}",
                posted_at_sort=posted_at,
                scraped_at=posted_at,
            )
        )
        index += 1

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


def test_one_company_cannot_fill_the_whole_first_page(feed_client):
    response = feed_client.get("/api/jobs?per_page=10")

    assert response.status_code == 200
    companies = [job["company"] for job in response.json()["jobs"]]
    assert companies.count(SPAM_COMPANY) <= config.JOBS_MAX_PER_COMPANY


def test_other_employers_reach_the_first_page(feed_client):
    response = feed_client.get("/api/jobs?per_page=10")

    companies = {job["company"] for job in response.json()["jobs"]}
    assert companies - {SPAM_COMPANY}, "no employer other than the reposter surfaced"
