"""Vertical acceptance for one resume-bound recruitment turn.

This is deliberately narrower than a browser test: it drives the production
module boundary and its durable tables while keeping model and discovery calls
scripted.  The two intentionally different resumes make stale evidence reuse a
deterministic failure instead of a subjective prose review.
"""

from __future__ import annotations

import hashlib

from backend.tests.fakes import AllowingEditEvidenceValidator
from backend.tests.test_recruitment_team_module import _session_factory
from models import (
    CandidateProfileArtifact,
    ProposedResumeEdit,
    RecruitmentActivityEvent,
    RecruitmentMessage,
    RecruitmentRun,
    RecruitmentThread,
    ResumeVersion,
    User,
)
from recruitment_team import RecruitmentTeam
from recruitment_team.activity_publisher import RecordedActivityPublisher
from recruitment_team.candidate_profile import (
    DeterministicCandidateProfilerFactory,
)
from recruitment_team.conversation_model import ModelReply
from recruitment_team.discovery import JobSearchResult, JobSnapshot, JobSource
from recruitment_team.interface import StartThread
from recruitment_team.open_agent.tools import propose_resume_edit, search_jobs
from recruitment_team.role_success import ScriptedRoleSuccessProfiler
from recruitment_team.telemetry import RecordedTelemetry
from resume_document import create_resume_document


HUI_SHAN_RESUME = """Hui Shan Ang
Singapore

PROFESSIONAL EXPERIENCE
DBS Bank | AVP Business Analyst, Finance Platform | 2021 - Present
- Produced monthly management accounts and reconciliations for finance stakeholders.
- Translated finance reporting requirements into platform changes and user acceptance tests.

QUALIFICATIONS
- Chartered Accountant Singapore.
"""

STALE_SEMICONDUCTOR_RESUME = """Haoming Koo
Singapore

EXPERIENCE
- Led semiconductor wafer yield and computer vision programmes at Micron.
"""

STALE_TERMS = (
    "haoming",
    "micron",
    "semiconductor",
    "wafer",
    "yield",
    "computer vision",
)
def _current_finance_jobs() -> tuple[JobSnapshot, ...]:
    source = JobSource(
        source="MyCareersFuture",
        url="https://example.test/jobs/finance-platform-ba-2026",
        source_posting_id="MCF-FIN-2026",
        posted_date="2026-08-28",
        closing_date="2026-09-30",
        scraped_at="2026-09-01T00:15:00Z",
        availability="current",
        snapshot_sha256="a" * 64,
    )
    return (
        JobSnapshot(
            job_id=3201,
            title="Senior Finance Platform Business Analyst",
            company="Singapore Finance Services Ltd",
            location="Singapore",
            salary="$8,000 - $11,000",
            employment_type="Full Time",
            seniority="Senior Professional",
            description=(
                "Translate finance reporting requirements into platform changes, "
                "management-accounting controls, reconciliations, and user acceptance tests."
            ),
            skills=(
                "finance platform",
                "business analysis",
                "management accounts",
                "reconciliations",
                "user acceptance tests",
            ),
            similarity_score=0.94,
            source=source,
            employer_relationship="direct",
            employer_relationship_evidence="fixture_verified_employer_career_site",
        ),
    )


class _CurrentFinanceDiscovery:
    def __init__(self, jobs: tuple[JobSnapshot, ...]):
        self.jobs = jobs
        self.calls: list[dict] = []

    def search_jobs(self, query: str, **constraints) -> JobSearchResult:
        self.calls.append({"query": query, **constraints})
        return JobSearchResult(
            query=query,
            jobs=self.jobs,
            candidate_count=len(self.jobs),
            visible_candidate_count=len(self.jobs),
            eligible_candidate_count=len(self.jobs),
            truncated=False,
            valid_empty=False,
            company=str(constraints.get("company") or ""),
            direct_employers_only=bool(constraints.get("direct_employers_only", True)),
            exclude_junior=bool(constraints.get("exclude_junior", False)),
            singapore_only=bool(constraints.get("singapore_only", True)),
            title_phrase=str(constraints.get("title_phrase") or ""),
        )

    def get_job(self, job_id: int) -> JobSnapshot | None:
        return next((job for job in self.jobs if job.job_id == job_id), None)


class _FinanceRecruitmentModel:
    def __init__(self, *, edit_block_id: str):
        self.edit_block_id = edit_block_id
        self.call_count = 0
        self.tool_results: list[dict] = []

    def respond(self, _messages, resume_text, _preferences=(), context=None):
        self.call_count += 1
        assert resume_text == HUI_SHAN_RESUME
        assert context is not None
        assert context.candidate_profile is not None
        evidence_field = next(
            field
            for field in context.candidate_profile.fields
            if field.statement
            == "Produced monthly management accounts and reconciliations for finance stakeholders."
        )
        self.tool_results.append(search_jobs.invoke({
            "query": "finance platform business analyst accounting Singapore",
            "direct_employers_only": True,
            "singapore_only": True,
        }))
        self.tool_results.append(propose_resume_edit.invoke({
            "block_id": self.edit_block_id,
            "rewrite": (
                "Produced monthly management accounts and reconciliations for finance "
                "stakeholders, supporting finance leadership review."
            ),
            "candidate_evidence_ids": [evidence_field.field_id],
        }))
        assert all(result.get("accepted", result.get("ok")) for result in self.tool_results)
        return ModelReply(
            content=(
                "The Senior Finance Platform Business Analyst role is relevant to Hui Shan's "
                "DBS finance-platform, management-accounting, reconciliation, and UAT evidence. "
                "One evidence-supported resume edit is pending for review."
            ),
            model_name="scripted-finance-recruitment-model",
            input_tokens=120,
            output_tokens=45,
        )


def test_hui_shan_start_thread_is_bound_relevant_reload_safe_and_pending_only():
    sessions = _session_factory()
    hui_document = create_resume_document(HUI_SHAN_RESUME)
    edit_block = next(
        block
        for block in hui_document["blocks"]
        if block.get("text")
        == "Produced monthly management accounts and reconciliations for finance stakeholders."
    )
    jobs = _current_finance_jobs()
    discovery = _CurrentFinanceDiscovery(jobs)
    model = _FinanceRecruitmentModel(edit_block_id=str(edit_block["id"]))
    profile_factory = DeterministicCandidateProfilerFactory()
    telemetry = RecordedTelemetry()
    activity = RecordedActivityPublisher()

    with sessions() as db:
        owner = User(
            email="hui-shan-acceptance@example.com",
            password_hash="test-only",  # pragma: allowlist secret
            name="Hui Shan Ang",
        )
        db.add(owner)
        db.flush()
        stale = ResumeVersion(
            user_id=owner.id,
            label="Haoming semiconductor resume",
            resume_text=STALE_SEMICONDUCTOR_RESUME,
            is_master=True,
        )
        hui = ResumeVersion(
            user_id=owner.id,
            label="Hui Shan DBS Finance Platform resume",
            resume_text=HUI_SHAN_RESUME,
            resume_structured=hui_document,
        )
        db.add_all([stale, hui])
        db.commit()
        owner_id = owner.id
        hui_resume_id = hui.id
        stale_resume_id = stale.id
        hui_hash = hashlib.sha256(HUI_SHAN_RESUME.encode()).hexdigest()

        team = RecruitmentTeam(
            db,
            model,
            discovery,
            ScriptedRoleSuccessProfiler([]),
            telemetry,
            activity,
            edit_evidence_validator=AllowingEditEvidenceValidator(),
            candidate_profiler_factory_provider=lambda: profile_factory,
        )
        receipt = team.execute(
            owner_id,
            StartThread(
                resume_version_id=hui_resume_id,
                message="Find current Singapore accounting and finance-platform roles for me.",
            ),
            idempotency_key="hui-shan-finance-vertical-slice",
        )
        snapshot = team.snapshot(owner_id, receipt.thread_id)
        profile = team.candidate_profile(owner_id, receipt.thread_id)
        pending = team.proposed_edits(owner_id, receipt.thread_id)

        assert db.query(RecruitmentRun).count() == 1
        run = db.query(RecruitmentRun).one()
        assert receipt.run_id == run.id
        assert receipt.status == run.status == "completed"
        assert run.trace_key
        assert run.completed_at is not None
        assert run.lease_owner is None and run.lease_expires_at is None
        assert run.result and run.result["status"] == "completed"
        assert db.query(RecruitmentMessage).filter_by(run_id=run.id, role="assistant").count() == 1
        terminal_events = db.query(RecruitmentActivityEvent).filter_by(
            run_id=run.id,
            event_type="run",
            status="completed",
        ).all()
        assert len(terminal_events) == 1
        assert terminal_events[0].trace_key == run.trace_key

        thread = db.get(RecruitmentThread, receipt.thread_id)
        assert thread.resume_version_id == hui_resume_id
        assert snapshot.case_facts.resume_version_id == hui_resume_id
        assert snapshot.case_facts.resume_sha256 == hui_hash
        assert stale_resume_id != hui_resume_id

        assert profile is not None and profile.status == "completed"
        artifact = db.get(CandidateProfileArtifact, profile.artifact_id)
        assert artifact is not None and artifact.resume_version_id == hui_resume_id
        assert profile.execution_metrics["model_call_count"] == 0
        assert db.query(CandidateProfileArtifact).count() == 1
        assert profile.execution_metrics["terminal_status"] == "completed"
        receipt_provenance = snapshot.case_facts.latest_ranking_receipt
        assert receipt_provenance is not None
        assert receipt_provenance.candidate_profile_used is True
        assert receipt_provenance.resume_version_id == hui_resume_id
        assert receipt_provenance.resume_sha256 == hui_hash
        assert receipt_provenance.candidate_profile_artifact_id == profile.artifact_id

        assert snapshot.case_facts.recommendations
        assert all(job.location == "Singapore" for job in snapshot.case_facts.recommendations)
        assert all(job.source.availability == "current" for job in snapshot.case_facts.recommendations)
        assert all(job.source.source_posting_id for job in snapshot.case_facts.recommendations)
        assert all(job.source.snapshot_sha256 for job in snapshot.case_facts.recommendations)
        assert all(job.source.scraped_at >= "2026-08-29" for job in snapshot.case_facts.recommendations)
        recommendation_text = " ".join(
            f"{job.title} {job.description} {' '.join(job.skills)}"
            for job in snapshot.case_facts.recommendations
        ).casefold()
        assert any(term in recommendation_text for term in ("finance", "account", "reconciliation"))

        candidate_attribution = " ".join(
            [
                *(field["statement"] for field in artifact.profile["fields"]),
                *(quote for field in artifact.profile["fields"] for quote in field["evidence_quotes"]),
                *(message.content for message in snapshot.messages),
                *receipt_provenance.candidate_queries,
            ]
        ).casefold()
        assert not any(term in candidate_attribution for term in STALE_TERMS)

        assert len(pending) == 1
        assert pending[0]["status"] == "pending"
        pending_row = db.query(ProposedResumeEdit).filter_by(status="pending").one()
        evidence_field = next(
            field
            for field in artifact.profile["fields"]
            if field["statement"]
            == "Produced monthly management accounts and reconciliations for finance stakeholders."
        )
        assert pending_row.resume_version_id == hui_resume_id
        assert pending_row.run_id == run.id
        assert pending_row.evidence_ids == [evidence_field["field_id"]]
        assert db.query(ResumeVersion).count() == 2
        assert db.get(ResumeVersion, hui_resume_id).resume_text == HUI_SHAN_RESUME
        assert db.get(ResumeVersion, stale_resume_id).resume_text == STALE_SEMICONDUCTOR_RESUME

    calls_before_reload = model.call_count
    discovery_calls_before_reload = len(discovery.calls)
    with sessions() as db:
        reloaded = RecruitmentTeam(
            db,
            model,
            discovery,
            ScriptedRoleSuccessProfiler([]),
            telemetry,
            activity,
            edit_evidence_validator=AllowingEditEvidenceValidator(),
            candidate_profiler_factory_provider=lambda: profile_factory,
        )
        reloaded_snapshot = reloaded.snapshot(owner_id, receipt.thread_id)
        reloaded_profile = reloaded.candidate_profile(owner_id, receipt.thread_id)
        reloaded_pending = reloaded.proposed_edits(owner_id, receipt.thread_id)

        assert db.query(RecruitmentRun).count() == 1
        assert db.query(ResumeVersion).count() == 2
        assert db.get(ResumeVersion, hui_resume_id).resume_text == HUI_SHAN_RESUME

    assert model.call_count == calls_before_reload == 1
    assert len(discovery.calls) == discovery_calls_before_reload
    assert reloaded_snapshot.case_facts.resume_sha256 == hui_hash
    assert reloaded_profile is not None and reloaded_profile.artifact_id == profile.artifact_id
    assert [edit["id"] for edit in reloaded_pending] == [edit["id"] for edit in pending]
