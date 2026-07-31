"""The default job feed must not let one high-volume reposter own a page.

Production evidence (2026-07-29): page 1 of /api/jobs was 20/20 recruitment-agency
and MLM listings, owned by six companies, because the default sort is newest-first
and those companies repost constantly.

The `balanced` sort demotes a company's 4th and later postings rather than dropping
them, so these tests pin both halves of that contract: the first page gets variety,
and nothing disappears from `total`, from search, or from deep pages.
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
OTHER_EMPLOYERS = ("Acme Pte Ltd", "Beta Labs", "Gamma Health", "Delta Systems")


def _build_client(rows):
    """Spin up a client over an in-memory DB seeded with `rows`, newest first.

    `rows` is a sequence of (company, salary_floor) in the order they were posted,
    newest first. Returns a context-manager-free (client, teardown) pair.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    now = datetime.now(timezone.utc)

    for index, (company, salary_floor) in enumerate(rows):
        posted_at = (now - timedelta(minutes=index)).isoformat()
        db.add(
            ScrapedJob(
                title=f"Role {index} at {company or 'unnamed'}",
                company=company,
                location="Singapore",
                source="MyCareersFuture",
                source_posting_id=f"mcf-{index}",
                dedup_key=f"feed-diversity-{index}",
                posted_at_sort=posted_at,
                scraped_at=posted_at,
                salary_floor=salary_floor,
            )
        )
    db.commit()

    def override_db():
        yield db

    main._filter_meta_cache = {}
    main._filter_meta_ts = 0.0
    main.app.dependency_overrides[get_db] = override_db

    def teardown():
        main.app.dependency_overrides.pop(get_db, None)
        db.close()

    return TestClient(main.app), teardown


@pytest.fixture()
def feed_client():
    """Newest 12 postings all belong to one company; 4 other employers are older."""
    rows = [(SPAM_COMPANY, 0)] * 12 + [(employer, 9000) for employer in OTHER_EMPLOYERS]
    client, teardown = _build_client(rows)
    try:
        yield client
    finally:
        teardown()


def test_every_other_employer_outranks_the_reposters_surplus(feed_client):
    """A company's 4th posting must never beat another company's 1st."""
    jobs = feed_client.get("/api/jobs?per_page=10").json()["jobs"]

    # 3 spam + 4 distinct employers all rank ahead of any 4th-and-later spam posting.
    head = [job["company"] for job in jobs[: config.JOBS_MAX_PER_COMPANY + len(OTHER_EMPLOYERS)]]

    assert head.count(SPAM_COMPANY) == config.JOBS_MAX_PER_COMPANY
    assert set(head) - {SPAM_COMPANY} == set(OTHER_EMPLOYERS)


def test_total_counts_every_match_and_no_job_is_unreachable(feed_client):
    """The cap reorders the feed; it must not delete rows from the corpus."""
    first = feed_client.get("/api/jobs?per_page=10&page=1").json()
    second = feed_client.get("/api/jobs?per_page=10&page=2").json()

    assert first["total"] == 16, f"corpus shrank to {first['total']} of 16 visible jobs"

    seen = [job["id"] for job in first["jobs"]] + [job["id"] for job in second["jobs"]]
    assert len(seen) == len(set(seen)), "a job appeared on both page 1 and page 2"
    assert len(seen) == 16, "some visible jobs are unreachable through any page"


def test_search_results_are_not_truncated_by_the_cap(feed_client):
    """Searching an employer must return all their openings, not the first three."""
    body = feed_client.get(f"/api/jobs?q=SYNDICATE&per_page=10").json()

    assert body["total"] == 12
    assert len(body["jobs"]) == 10
    assert {job["company"] for job in body["jobs"]} == {SPAM_COMPANY}


def test_newest_sort_stays_raw_chronological(feed_client):
    """`sort=newest` is the documented escape hatch and must skip the cap entirely."""
    jobs = feed_client.get("/api/jobs?per_page=10&sort=newest").json()["jobs"]

    companies = [job["company"] for job in jobs]

    assert companies == [SPAM_COMPANY] * 10


def test_min_salary_priority_survives_the_balanced_sort(feed_client):
    """Jobs clearing the salary floor still rank above salary-unknown ones."""
    body = feed_client.get("/api/jobs?min_salary=8000&per_page=10").json()

    # Spam rows carry salary_floor=0, which the filter deliberately lets through.
    assert body["total"] == 16
    leading = [job["company"] for job in body["jobs"][: len(OTHER_EMPLOYERS)]]

    assert set(leading) == set(OTHER_EMPLOYERS), "salary-unknown jobs outranked real matches"


def test_blank_company_rows_are_still_all_reachable():
    """Adzuna/Jooble rows arrive with no company and must not collapse into 3 slots."""
    client, teardown = _build_client([("", 0)] * 8 + [("Acme Pte Ltd", 0)])
    try:
        first = client.get("/api/jobs?per_page=5&page=1").json()
        second = client.get("/api/jobs?per_page=5&page=2").json()

        assert first["total"] == 9
        seen = [job["id"] for job in first["jobs"]] + [job["id"] for job in second["jobs"]]
        assert len(set(seen)) == 9, "blank-company rows were dropped by the cap"
    finally:
        teardown()


def _promotional_client():
    """Newest postings are all promotional; two plain employers are older."""
    rows = [("SIMPLE RECRUIT", 0)] * 6 + [(e, 0) for e in ("Acme Pte Ltd", "Beta Labs")]
    client, teardown = _build_client(rows)
    return client, teardown


def test_promotional_postings_sink_below_ordinary_ones():
    """The company cap cannot reach these: many separate outfits post a few each."""
    from database import get_db
    from models import ScrapedJob

    client, teardown = _promotional_client()
    try:
        db = next(main.app.dependency_overrides[get_db]())
        for job in db.query(ScrapedJob).filter(ScrapedJob.company == "SIMPLE RECRUIT"):
            job.promotional_score = 55
        db.commit()

        jobs = client.get("/api/jobs?per_page=8").json()["jobs"]
        leading = [job["company"] for job in jobs[:2]]

        assert set(leading) == {"Acme Pte Ltd", "Beta Labs"}, (
            "promotional postings still outranked ordinary employers"
        )
    finally:
        teardown()


def test_exclude_promotional_removes_them_entirely():
    from database import get_db
    from models import ScrapedJob

    client, teardown = _promotional_client()
    try:
        db = next(main.app.dependency_overrides[get_db]())
        for job in db.query(ScrapedJob).filter(ScrapedJob.company == "SIMPLE RECRUIT"):
            job.promotional_score = 55
        db.commit()

        body = client.get("/api/jobs?per_page=8&exclude_promotional=true").json()

        assert body["total"] == 2
        assert {job["company"] for job in body["jobs"]} == {"Acme Pte Ltd", "Beta Labs"}
    finally:
        teardown()


def test_ordinary_postings_are_untouched_by_the_promotional_filter():
    """A zero score must never be filtered, and defaults must not change."""
    client, teardown = _build_client([("Acme Pte Ltd", 0), ("Beta Labs", 0)])
    try:
        assert client.get("/api/jobs?exclude_promotional=true").json()["total"] == 2
    finally:
        teardown()

def test_every_sort_mode_is_reachable_from_a_client(feed_client):
    """The UI used to omit sort for "newest", so it silently returned balanced."""
    for mode in ("balanced", "newest", "salary"):
        assert feed_client.get(f"/api/jobs?per_page=5&sort={mode}").status_code == 200


def test_placeholder_salaries_are_not_shown_as_offers():
    """Scraped strings like "$1 - $1" are filler, not a wage."""
    from job_precompute import display_salary

    assert display_salary("$1 - $1") == ""
    assert display_salary("$1 - $2") == ""
    assert display_salary("") == ""

    # A junk floor with a real ceiling still carries information.
    assert display_salary("$1 - $10,000") == "Up to $10,000"

    # Real ranges pass through untouched.
    assert display_salary("$7,000 - $10,000") == "$7,000 - $10,000"
    assert display_salary("$500 - $800") == "$500 - $800"
