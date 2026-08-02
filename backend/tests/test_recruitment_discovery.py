from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import ScrapedJob
from recruitment_team.discovery import _enrich_job_facts


def _job(job_id: int, salary_floor: int, *, salary: str | None = None) -> ScrapedJob:
    return ScrapedJob(
        id=job_id,
        title="AI Platform Engineer",
        company=f"Employer {job_id}",
        salary=salary if salary is not None else f"${salary_floor:,}",
        salary_floor=salary_floor,
        seniority="Manager",
        sector="Information & Communications",
        parsed_jd={"required_skills": ["LangGraph"], "experience_years": "5"},
        job_terms_preview=["LangGraph", "RAG"],
        dedup_key=f"job-{job_id}",
        posted_at_sort=datetime.now(timezone.utc).isoformat(),
    )


def test_discovery_exposes_stored_requirements_and_observed_salary_context(monkeypatch):
    import database

    engine = create_engine("sqlite://")
    ScrapedJob.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all(
            [
                _job(1, 4000),
                _job(2, 6000),
                _job(3, 8000),
                _job(4, 10000),
            ]
        )
        db.commit()
    monkeypatch.setattr(database, "SessionLocal", sessions)

    [result] = _enrich_job_facts([{"id": 1, "salary": "$4,000"}])

    assert result["parsed_jd"]["required_skills"] == ["LangGraph"]
    assert set(result["parsed_jd"]) == {"required_skills", "experience_years"}
    assert result["fact_context_status"] == "available"
    assert result["job_terms_preview"] == ["LangGraph", "RAG"]
    assert result["salary_context"] == {
        "basis": "current visible postings with stated salary",
        "sector": "Information & Communications",
        "self_reported_seniority": "Manager",
        "sample_count": 4,
        "median_salary_floor": 7000.0,
        "posting_salary_floor": 4000,
        "posting_floor_percentile": 25.0,
    }


def test_discovery_never_imputes_a_missing_posting_salary(monkeypatch):
    import database

    engine = create_engine("sqlite://")
    ScrapedJob.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([_job(1, 6000), _job(2, 8000), _job(3, 0, salary="")])
        db.commit()
    monkeypatch.setattr(database, "SessionLocal", sessions)

    [result] = _enrich_job_facts([{"id": 3, "salary": ""}])

    assert result["salary"] == ""
    assert result["salary_context"]["median_salary_floor"] == 7000.0
    assert result["salary_context"]["posting_salary_floor"] is None
    assert result["salary_context"]["posting_floor_percentile"] is None


def test_discovery_reports_when_a_result_can_no_longer_be_enriched(monkeypatch):
    import database

    engine = create_engine("sqlite://")
    ScrapedJob.__table__.create(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)

    [result] = _enrich_job_facts([{"id": 99, "salary": "$8,000"}])

    assert result["fact_context_status"] == "source_row_unavailable"
    assert "salary_context" not in result
