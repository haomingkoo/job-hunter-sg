from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import seed_jobs
from database import Base
from models import ScrapedJob
from scraper import CareersGovScraper, Job, MyCareersFutureScraper


def _job(source: str, posting_id: str, title: str = "Software Engineer") -> Job:
    return Job(
        title=title,
        company="Example Company",
        source=source,
        source_posting_id=posting_id,
        url=f"https://example.test/jobs/{posting_id}",
    )


def _prepare_crawl(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    monkeypatch.setattr(seed_jobs, "init_db", lambda: None)
    monkeypatch.setattr(seed_jobs, "SessionLocal", testing_session)
    monkeypatch.setattr(seed_jobs, "apply_job_precomputes", lambda clean: None)
    monkeypatch.setattr(seed_jobs, "preparse_job_description", None)
    monkeypatch.setattr(seed_jobs, "_posted_sort_iso", lambda *_: "2026-07-13T00:00:00")
    monkeypatch.setattr(seed_jobs, "MCF_MIN_HEALTHY_JOBS", 1)
    monkeypatch.setattr(seed_jobs.time, "sleep", lambda _: None)
    return engine, testing_session


def _seed(db, job: Job, *, hidden: int = 0) -> None:
    db.add(
        ScrapedJob(
            title=job.title,
            company=job.company,
            source=job.source,
            source_posting_id=job.source_posting_id,
            url=job.url,
            dedup_key=job.dedup_key,
            scraped_at="2020-01-01T00:00:00",
            hidden=hidden,
        )
    )
    db.commit()


def test_mcf_bad_job_does_not_rollback_siblings_or_retire_stale_rows(monkeypatch):
    engine, testing_session = _prepare_crawl(monkeypatch)
    stale = _job("MyCareersFuture", "stale")
    db = testing_session()
    _seed(db, stale)
    db.close()

    jobs = [_job("MyCareersFuture", "good-1"), _job("MyCareersFuture", "bad", "Bad"), _job("MyCareersFuture", "good-2")]
    monkeypatch.setattr(MyCareersFutureScraper, "search", lambda self, keyword, limit, page: jobs if page == 0 else [])
    monkeypatch.setattr(CareersGovScraper, "fetch_all", lambda self: [])
    real_sanitize = seed_jobs.sanitize_job

    def fail_one_job(raw):
        if raw["title"] == "Bad":
            raise ValueError("bad row")
        return real_sanitize(raw)

    monkeypatch.setattr(seed_jobs, "sanitize_job", fail_one_job)

    stats = seed_jobs.crawl_all_jobs()

    db = testing_session()
    assert db.query(ScrapedJob).filter(ScrapedJob.source_posting_id.in_(["good-1", "good-2"])).count() == 2
    assert db.query(ScrapedJob).filter(ScrapedJob.source_posting_id == "stale").one().hidden == 0
    assert stats["new"] == 2
    assert stats["retired"] == 0
    assert stats["errors"] >= 1
    db.close()
    engine.dispose()


def test_mcf_completed_crawl_retires_unseen_and_reactivates_seen(monkeypatch):
    engine, testing_session = _prepare_crawl(monkeypatch)
    stale = _job("MyCareersFuture", "stale")
    seen = _job("MyCareersFuture", "seen")
    db = testing_session()
    _seed(db, stale)
    _seed(db, seen, hidden=1)
    db.close()

    monkeypatch.setattr(
        MyCareersFutureScraper,
        "search",
        lambda self, keyword, limit, page: [seen] if page == 0 else [],
    )
    monkeypatch.setattr(CareersGovScraper, "fetch_all", lambda self: [])

    stats = seed_jobs.crawl_all_jobs()

    db = testing_session()
    assert db.query(ScrapedJob).filter(ScrapedJob.source_posting_id == "stale").one().hidden == 1
    assert db.query(ScrapedJob).filter(ScrapedJob.source_posting_id == "seen").one().hidden == 0
    assert stats["retired"] == 1
    assert stats["reactivated"] == 1
    db.close()
    engine.dispose()


def test_mcf_page_error_skips_retirement(monkeypatch):
    engine, testing_session = _prepare_crawl(monkeypatch)
    stale = _job("MyCareersFuture", "stale")
    db = testing_session()
    _seed(db, stale)
    db.close()

    def search(self, keyword, limit, page):
        if page == 0:
            return [_job("MyCareersFuture", "seen")]
        if page == 1:
            raise RuntimeError("upstream failed")
        return []

    monkeypatch.setattr(MyCareersFutureScraper, "search", search)
    monkeypatch.setattr(CareersGovScraper, "fetch_all", lambda self: [])

    stats = seed_jobs.crawl_all_jobs()

    db = testing_session()
    assert db.query(ScrapedJob).filter(ScrapedJob.source_posting_id == "stale").one().hidden == 0
    assert stats["retired"] == 0
    assert stats["errors"] >= 1
    db.close()
    engine.dispose()


def test_mcf_ambiguous_empty_page_skips_retirement(monkeypatch):
    engine, testing_session = _prepare_crawl(monkeypatch)
    stale = _job("MyCareersFuture", "stale")
    db = testing_session()
    _seed(db, stale)
    db.close()

    full_page = [_job("MyCareersFuture", f"seen-{index}") for index in range(100)]
    monkeypatch.setattr(
        MyCareersFutureScraper,
        "search",
        lambda self, keyword, limit, page: full_page if page == 0 else [],
    )
    monkeypatch.setattr(CareersGovScraper, "fetch_all", lambda self: [])

    stats = seed_jobs.crawl_all_jobs()

    db = testing_session()
    assert db.query(ScrapedJob).filter(ScrapedJob.source_posting_id == "stale").one().hidden == 0
    assert stats["retired"] == 0
    assert stats["errors"] >= 1
    db.close()
    engine.dispose()


def test_careersgov_completed_crawl_retires_unseen_and_reactivates_seen(monkeypatch):
    engine, testing_session = _prepare_crawl(monkeypatch)
    stale = _job("Careers@Gov", "stale")
    seen = _job("Careers@Gov", "seen")
    db = testing_session()
    _seed(db, stale)
    _seed(db, seen, hidden=1)
    db.close()

    monkeypatch.setattr(MyCareersFutureScraper, "search", lambda self, keyword, limit, page: [])
    monkeypatch.setattr(CareersGovScraper, "fetch_all", lambda self: [seen])
    monkeypatch.setattr(seed_jobs, "CAREERSGOV_MIN_HEALTHY_JOBS", 1)

    stats = seed_jobs.crawl_all_jobs()

    db = testing_session()
    assert db.query(ScrapedJob).filter(ScrapedJob.source_posting_id == "stale").one().hidden == 1
    assert db.query(ScrapedJob).filter(ScrapedJob.source_posting_id == "seen").one().hidden == 0
    assert stats["retired"] == 1
    assert stats["reactivated"] == 1
    db.close()
    engine.dispose()


def test_careersgov_failed_health_check_does_not_retire(monkeypatch):
    engine, testing_session = _prepare_crawl(monkeypatch)
    stale = _job("Careers@Gov", "stale")
    db = testing_session()
    _seed(db, stale)
    db.close()

    monkeypatch.setattr(MyCareersFutureScraper, "search", lambda self, keyword, limit, page: [])
    monkeypatch.setattr(CareersGovScraper, "fetch_all", lambda self: [_job("Careers@Gov", "only-result")])
    monkeypatch.setattr(seed_jobs, "CAREERSGOV_MIN_HEALTHY_JOBS", 2)

    stats = seed_jobs.crawl_all_jobs()

    db = testing_session()
    assert db.query(ScrapedJob).filter(ScrapedJob.source_posting_id == "stale").one().hidden == 0
    assert stats["retired"] == 0
    assert stats["errors"] >= 1
    db.close()
    engine.dispose()
