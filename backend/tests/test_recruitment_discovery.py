from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import ScrapedJob
from recruitment_team.discovery import JobSnapshot, _enrich_job_facts
from recruitment_team.open_agent.tools import _posting


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


def test_employer_relationship_survives_discovery_and_coordinator_adapter():
    snapshot = JobSnapshot.from_payload(
        {
            "id": 7,
            "title": "Quality Manager",
            "company": "Singapore Public Service",
            "employer_relationship": "direct",
            "employer_relationship_evidence": "careers_gov_official",
        }
    )

    assert snapshot.employer_relationship == "direct"
    assert snapshot.employer_relationship_evidence == "careers_gov_official"
    assert _posting(snapshot)["employer_relationship"] == "direct"
    assert _posting(snapshot)["employer_relationship_evidence"] == "careers_gov_official"


def test_production_discovery_forwards_explicit_employer_constraints(monkeypatch):
    import resume_agent.tools as agent_tools
    import recruitment_team.discovery as discovery_module

    captured = {}

    def fake_invoke(payload):
        captured.update(payload)
        return {
            "ok": True,
            "results": [],
            "candidate_count": 7,
            "eligible_candidate_count": 63,
            "visible_candidate_count": 7,
            "truncated": False,
        }

    monkeypatch.setattr(
        agent_tools.search_jobs.__class__,
        "invoke",
        lambda _tool, payload, **_kwargs: fake_invoke(payload),
    )
    result = discovery_module.LangChainJobDiscovery().search_jobs(
        "semiconductor quality transformation",
        company="Micron",
        direct_employers_only=True,
    )

    assert captured == {
        "query": "semiconductor quality transformation",
        "detail": True,
        "company": "Micron",
        "direct_employers_only": True,
        "exclude_junior": False,
        "singapore_only": True,
        "title_phrase": "",
    }
    assert result.eligible_candidate_count == 63
    assert result.candidate_count == 7
    assert result.visible_candidate_count == 7


def test_production_discovery_preserves_specific_index_failure_code(monkeypatch):
    import resume_agent.tools as agent_tools
    import recruitment_team.discovery as discovery_module

    monkeypatch.setattr(
        agent_tools.search_jobs.__class__,
        "invoke",
        lambda _tool, _payload, **_kwargs: {
            "ok": False,
            "failure_type": "unavailable",
            "retryable": True,
            "error": {
                "code": "employer_index_unavailable",
                "message": "The employer index is rebuilding.",
            },
        },
    )

    result = discovery_module.LangChainJobDiscovery().search_jobs("quality manager")

    assert result.failure_type == "business"
    assert result.failure_code == "employer_index_unavailable"
