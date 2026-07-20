"""Run the V3 recruitment-team tracer journey with the configured live model."""

from __future__ import annotations

import json
import argparse
import sys
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from database import Base  # noqa: E402
import config  # noqa: E402
from models import ResumeVersion, User  # noqa: E402
from recruitment_team import (  # noqa: E402
    EvidenceAssessedRoleSuccessProfiler,
    LangChainConversationModel,
    LangChainRoleEvidenceAssessor,
    LangChainRoleDefinitionGenerator,
    RecruitmentTeam,
)
from recruitment_team.activity_publisher import RecordedActivityPublisher  # noqa: E402
from recruitment_team.candidate_profile import (  # noqa: E402
    CandidateProfileRun,
    LangChainCandidateProfilerFactory,
    ScriptedCandidateProfilerFactory,
    candidate_profile_execution_policy,
    candidate_profile_from_dict,
)
from recruitment_team.discovery import LangChainJobDiscovery  # noqa: E402
from recruitment_team.errors import (  # noqa: E402
    CandidateProfilingUnavailable,
    RoleProfilingUnavailable,
    TargetAssessmentUnavailable,
)
from recruitment_team.interface import (  # noqa: E402
    AssessTargetJob,
    BuildCandidateProfile,
    SearchJobs,
    SelectTargetJob,
    SendMessage,
    StartThread,
)
from recruitment_team.telemetry import RecordedTelemetry  # noqa: E402
from recruitment_team.open_agent.runner import OpenAgentTargetAssessmentRunner  # noqa: E402
from resume_agent.models import create_agent_model  # noqa: E402
from resume_parser import parse_resume_isolated  # noqa: E402
from resume_document import create_resume_document  # noqa: E402


SAMPLE_RESUME = """Jane Tan
Singapore

EXPERIENCE
GovTech | AI Project Lead | Jan 2022 - Present
- Led delivery of an internal document assistant for operations teams
- Coordinated engineers, policy users, and QA reviewers across rollout
"""

DEFAULT_INITIAL_MESSAGE = (
    "Study my resume and build an evidence-backed candidate profile. Suggest plausible "
    "role families as hypotheses, then ask one decision-useful question."
)
DEFAULT_FOLLOW_UP_MESSAGE = (
    "Keep the analysis broad. Distinguish direct evidence, transferable strengths, "
    "and gaps. Do not assume a role, location, seniority, or salary preference that "
    "I have not stated."
)


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


_RESUME_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _resume_input(path: str) -> tuple[str, str, dict, dict]:
    if not path:
        document = create_resume_document(SAMPLE_RESUME)
        return (
            SAMPLE_RESUME,
            "V3 local canary resume",
            {
                "source": "embedded_sample",
                "word_count": len(SAMPLE_RESUME.split()),
            },
            document,
        )

    resume_path = Path(path).expanduser().resolve()
    content_type = _RESUME_CONTENT_TYPES.get(resume_path.suffix.lower())
    if content_type is None:
        raise ValueError(
            f"Unsupported resume file extension {resume_path.suffix!r}; "
            f"expected one of {sorted(_RESUME_CONTENT_TYPES)}"
        )
    parsed = parse_resume_isolated(
        resume_path.name,
        content_type,
        resume_path.read_bytes(),
    )
    return (
        str(parsed["text"]),
        resume_path.stem,
        {
            "source": "local_file",
            "filename": resume_path.name,
            "file_type": parsed["file_type"],
            "word_count": parsed["word_count"],
            "line_count": parsed["line_count"],
            "page_estimate": parsed["page_estimate"],
            "parse_quality": parsed["parse_quality"],
            "content_warnings": parsed["content_warnings"],
            "document_block_count": len(parsed["document"]["blocks"]),
        },
        parsed["document"],
    )


def _candidate_profile_run_from_report(path: str, resume_document: dict) -> CandidateProfileRun:
    report_path = Path(path).expanduser().resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "completed" or not isinstance(report.get("profile"), dict):
        raise ValueError("Candidate profile report must contain one completed profile")
    observed_policy = dict(report.get("execution_policy") or {})
    observed_policy.pop("checkpoint_enabled", None)
    if observed_policy != candidate_profile_execution_policy():
        raise ValueError("Candidate profile report execution policy does not match this runtime")
    profile = candidate_profile_from_dict(report["profile"])
    if profile.resume_document_id != resume_document.get(
        "document_id"
    ) or profile.resume_revision != resume_document.get("revision"):
        raise ValueError("Candidate profile report does not belong to the parsed resume revision")
    run = report.get("run") or {}
    if not run.get("model_name") or not run.get("checkpoint_id"):
        raise ValueError("Candidate profile report is missing model or checkpoint identity")
    return CandidateProfileRun(
        profile=profile,
        model_name=str(run["model_name"]),
        attempt_count=int(run.get("attempt_count") or 0),
        input_tokens=int(run["input_tokens"]) if run.get("input_tokens") is not None else None,
        output_tokens=int(run["output_tokens"]) if run.get("output_tokens") is not None else None,
        validation_codes=tuple(str(value) for value in run.get("validation_codes") or []),
        scope_count=int(run.get("scope_count") or 0),
        model_call_count=int(run.get("model_call_count") or 0),
        checkpoint_hit_count=int(run.get("checkpoint_hit_count") or 0),
        checkpoint_id=str(run["checkpoint_id"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume-pdf",
        default="",
        help="Optional local PDF or DOCX to parse losslessly before the live journey.",
    )
    parser.add_argument(
        "--search-query",
        required=True,
        help="Explicit query for the real local job corpus used by the full journey.",
    )
    parser.add_argument(
        "--candidate-profile-resume-attempts",
        required=True,
        type=int,
        help=(
            "Explicit number of workflow-level checkpoint resumes allowed after a "
            "retryable candidate-profile transport failure. This is separate from "
            "model transport retries and is recorded in the report."
        ),
    )
    parser.add_argument(
        "--role-profile-resume-attempts",
        required=True,
        type=int,
        help="Explicit workflow-level retries after a retryable role-profile failure.",
    )
    parser.add_argument(
        "--target-assessment-resume-attempts",
        required=True,
        type=int,
        help="Explicit workflow-level retries after a retryable target-assessment failure.",
    )
    parser.add_argument(
        "--target-job-id",
        required=True,
        type=int,
        help="Explicit target job ID from the search results; the canary never picks the first result implicitly.",
    )
    parser.add_argument("--conversation-model", required=True, help="Explicit model for conversation turns.")
    parser.add_argument("--role-definition-model", required=True, help="Explicit role-definition model.")
    parser.add_argument("--role-evidence-model", required=True, help="Explicit role-evidence model.")
    parser.add_argument("--assessment-model", required=True, help="Explicit specialist, synthesis, and judge model.")
    parser.add_argument(
        "--max-output-tokens",
        required=True,
        type=int,
        help="Explicit maximum completion-token budget for every live canary model call.",
    )
    parser.add_argument(
        "--candidate-profile-report",
        default="",
        help=(
            "Explicit completed real-resume profile report to reuse for downstream E2E. "
            "Its execution policy and resume identity are validated before use."
        ),
    )
    parser.add_argument(
        "--initial-message",
        default=DEFAULT_INITIAL_MESSAGE,
        help="Explicit first-turn scenario input.",
    )
    parser.add_argument(
        "--follow-up-message",
        default=DEFAULT_FOLLOW_UP_MESSAGE,
        help="Explicit second-turn scenario input.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path for the complete JSON report.",
    )
    args = parser.parse_args()
    if args.candidate_profile_resume_attempts < 0:
        parser.error("--candidate-profile-resume-attempts must be zero or greater")
    if args.role_profile_resume_attempts < 0:
        parser.error("--role-profile-resume-attempts must be zero or greater")
    if args.target_assessment_resume_attempts < 0:
        parser.error("--target-assessment-resume-attempts must be zero or greater")
    if args.max_output_tokens <= 0:
        parser.error("--max-output-tokens must be greater than zero")
    resume_text, resume_label, parse_report, resume_document = _resume_input(args.resume_pdf)
    imported_profile_run = (
        _candidate_profile_run_from_report(args.candidate_profile_report, resume_document)
        if args.candidate_profile_report
        else None
    )

    sessions = _session_factory()
    telemetry = RecordedTelemetry()
    activity = RecordedActivityPublisher()

    def live_model(model_name: str):
        return create_agent_model(
            model=model_name,
            max_completion_tokens=args.max_output_tokens,
            timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
            max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
        )

    model = LangChainConversationModel(
        model=live_model(args.conversation_model),
        telemetry=telemetry,
    )

    with sessions() as db:
        user = User(
            email="v3-local-canary@example.com",
            password_hash="local-canary",  # pragma: allowlist secret
            name="V3 Local Canary",
        )
        db.add(user)
        db.flush()
        resume = ResumeVersion(
            user_id=user.id,
            label=resume_label,
            resume_text=resume_text,
            resume_structured=resume_document,
            is_master=True,
        )
        db.add(resume)
        db.commit()
        owner_id = user.id
        resume_id = resume.id

        candidate_profiler_factory = (
            ScriptedCandidateProfilerFactory(
                [imported_profile_run],
                model_name=imported_profile_run.model_name,
                enforce_resume_identity=True,
            )
            if imported_profile_run is not None
            else LangChainCandidateProfilerFactory(telemetry=telemetry)
        )
        team = RecruitmentTeam(
            db,
            model,
            LangChainJobDiscovery(),
            EvidenceAssessedRoleSuccessProfiler(
                LangChainRoleDefinitionGenerator(
                    model=live_model(args.role_definition_model),
                    telemetry=telemetry,
                ),
                LangChainRoleEvidenceAssessor(
                    model=live_model(args.role_evidence_model),
                    telemetry=telemetry,
                ),
            ),
            telemetry,
            activity,
            candidate_profiler_factory,
            OpenAgentTargetAssessmentRunner(
                model_factory=lambda: live_model(args.assessment_model),
                telemetry=telemetry,
            ),
        )
        started_at = time.perf_counter()
        receipts = []
        # RecruitmentTeam.execute() always persists a "user" message before
        # attempting a command, and only adds the "assistant" reply on
        # success (recruitment_team.py) -- so a failed attempt that gets
        # resumed with a new idempotency_key leaves an orphaned "user"
        # message behind, one that a resumed command's own successful
        # receipt never accounts for. Tracking every attempt here (not just
        # the successful receipts) is what lets the role-sequence assertion
        # below match what's actually persisted.
        expected_message_roles = []
        journey_error = None
        attempted_target = None
        thread_id = ""

        def execute_phase(phase, command, idempotency_key):
            phase_started = time.perf_counter()
            print(json.dumps({"phase": phase, "status": "running"}), file=sys.stderr, flush=True)
            expected_message_roles.append("user")
            try:
                receipt = team.execute(
                    owner_id,
                    command,
                    idempotency_key=idempotency_key,
                )
            except BaseException as error:
                print(
                    json.dumps(
                        {
                            "phase": phase,
                            "status": "failed",
                            "error_type": type(error).__name__,
                            "elapsed_ms": round((time.perf_counter() - phase_started) * 1000),
                        }
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                raise
            print(
                json.dumps(
                    {
                        "phase": phase,
                        "status": "completed",
                        "elapsed_ms": round((time.perf_counter() - phase_started) * 1000),
                        "trace_key": receipt.trace_key,
                    }
                ),
                file=sys.stderr,
                flush=True,
            )
            expected_message_roles.append("assistant")
            receipts.append(receipt)
            return receipt

        try:
            first = execute_phase(
                "first_conversation_turn",
                StartThread(
                    resume_version_id=resume_id,
                    message=args.initial_message,
                ),
                "v3-local-first-turn",
            )
            thread_id = first.thread_id
            execute_phase(
                "second_conversation_turn",
                SendMessage(
                    thread_id=thread_id,
                    message=args.follow_up_message,
                ),
                "v3-local-second-turn",
            )
            candidate_profile_resume_count = 0
            while True:
                phase = (
                    "candidate_profile"
                    if candidate_profile_resume_count == 0
                    else f"candidate_profile_resume_{candidate_profile_resume_count}"
                )
                try:
                    execute_phase(
                        phase,
                        BuildCandidateProfile(thread_id=thread_id),
                        f"v3-local-{phase.replace('_', '-')}",
                    )
                    break
                except CandidateProfilingUnavailable as error:
                    if not error.retryable or candidate_profile_resume_count >= args.candidate_profile_resume_attempts:
                        raise
                    candidate_profile_resume_count += 1
            execute_phase(
                "job_search",
                SearchJobs(thread_id=thread_id, query=args.search_query),
                "v3-local-job-search",
            )
            searched_snapshot = team.snapshot(owner_id, thread_id)
            if not searched_snapshot.case_facts.recommendations:
                raise RuntimeError("The explicit search returned no target candidate.")
            attempted_target = next(
                (job for job in searched_snapshot.case_facts.recommendations if job.job_id == args.target_job_id),
                None,
            )
            if attempted_target is None:
                raise RuntimeError("The explicit target job ID was not present in the search results.")
            role_profile_resume_count = 0
            while True:
                phase = (
                    "target_selection_and_role_profile"
                    if role_profile_resume_count == 0
                    else f"target_selection_and_role_profile_resume_{role_profile_resume_count}"
                )
                try:
                    execute_phase(
                        phase,
                        SelectTargetJob(
                            thread_id=thread_id,
                            job_id=attempted_target.job_id,
                        ),
                        f"v3-local-{phase.replace('_', '-')}",
                    )
                    break
                except RoleProfilingUnavailable as error:
                    if not error.retryable or role_profile_resume_count >= args.role_profile_resume_attempts:
                        raise
                    role_profile_resume_count += 1
            target_assessment_resume_count = 0
            while True:
                phase = (
                    "bounded_target_assessment"
                    if target_assessment_resume_count == 0
                    else f"bounded_target_assessment_resume_{target_assessment_resume_count}"
                )
                try:
                    execute_phase(
                        phase,
                        AssessTargetJob(thread_id=thread_id),
                        f"v3-local-{phase.replace('_', '-')}",
                    )
                    break
                except TargetAssessmentUnavailable as error:
                    if not error.retryable or target_assessment_resume_count >= args.target_assessment_resume_attempts:
                        raise
                    target_assessment_resume_count += 1
        except Exception as error:
            cause = error
            validation_code = None
            failed_scope_id = None
            rejected_submission = None
            cursor = error
            while cursor is not None:
                validation_code = validation_code or getattr(cursor, "validation_code", None)
                failed_scope_id = failed_scope_id or getattr(cursor, "scope_id", None)
                rejected_submission = rejected_submission or getattr(
                    cursor,
                    "rejected_submission",
                    None,
                )
                cursor = cursor.__cause__
            while cause.__cause__ is not None:
                cause = cause.__cause__
            journey_error = {
                "type": type(error).__name__,
                "message": str(error),
                "failure_type": getattr(error, "failure_type", None),
                "retryable": getattr(error, "retryable", None),
                "root_cause_type": type(cause).__name__,
                "validation_code": validation_code,
                "failed_scope_id": failed_scope_id,
                "rejected_submission": rejected_submission,
            }
        if not thread_id:
            owned_threads = team.threads(owner_id)
            if not owned_threads:
                raise RuntimeError("The failed start turn did not persist a recoverable thread.")
            thread_id = owned_threads[0].thread_id
        snapshot = team.snapshot(owner_id, thread_id)
        events = team.events(owner_id, thread_id, after_sequence=0)
        candidate_profile_artifact = team.candidate_profile(owner_id, thread_id)
        target_assessment_artifact = team.target_assessment(owner_id, thread_id)

    if journey_error is None:
        assert [message.role for message in snapshot.messages] == expected_message_roles
    assert all(message.content.strip() for message in snapshot.messages)
    if journey_error is None:
        assert candidate_profile_artifact is not None
        assert candidate_profile_artifact.status == "completed"
        assert candidate_profile_artifact.profile
        assert candidate_profile_artifact.profile["fields"]
        assert snapshot.case_facts.recommendations
        assert snapshot.case_facts.selected_target is not None
        assert snapshot.case_facts.role_success_profile is not None
        assert snapshot.case_facts.role_success_profile.criteria
        assert target_assessment_artifact is not None
        assert target_assessment_artifact.execution_policy["fallback_model"] is None
        assert target_assessment_artifact.execution_policy["content_truncation"] is False
        expected_specialists = set(target_assessment_artifact.execution_policy["specialists"])
        observed_specialists = {run["persona_id"] for run in target_assessment_artifact.specialist_runs}
        # The open-agent orchestrator decides which personas to consult and how
        # many times, so a live run is no longer guaranteed to touch every
        # registered persona -- only that whichever it did consult are real.
        assert observed_specialists <= expected_specialists
        if target_assessment_artifact.status == "paused":
            # A genuinely autonomous run: the orchestrator decided to call
            # ask_candidate instead of completing. This is a real, legitimate
            # terminal state (Tasks 10-11), not a failure -- synthesis stays
            # withheld and the judge never runs, since there is nothing
            # approved yet to judge.
            assert snapshot.workflow_state == "awaiting_candidate_answer"
            assert not target_assessment_artifact.synthesis.strip()
            assert target_assessment_artifact.judge is None
        else:
            assert target_assessment_artifact.status == "completed"
            assert target_assessment_artifact.synthesis.strip()
            assert target_assessment_artifact.judge
            assert target_assessment_artifact.judge["strengths"]
            assert target_assessment_artifact.judge["score_reason"]
    assert all(receipt.thread_id == thread_id for receipt in receipts)
    assert len({receipt.trace_key for receipt in receipts}) == len(receipts)
    if journey_error is None:
        assert [span.name for span in telemetry.spans].count("model") == 2
        non_success_spans = [span for span in telemetry.spans if span.status != "success"]
        # A phase that failed once and then succeeded on an explicit resume
        # (candidate_profile_resume_attempts / role_profile_resume_attempts /
        # target_assessment_resume_attempts) legitimately leaves the failed
        # attempt's top-level "command" span recorded as non-success -- that's
        # the telemetry doing its job, not a bug. What must never happen is a
        # non-success span anywhere else (an unexpected inner failure), or
        # more non-success spans than the resumes actually taken account for.
        assert all(span.name == "command" for span in non_success_spans)
        total_resumes = candidate_profile_resume_count + role_profile_resume_count + target_assessment_resume_count
        assert len(non_success_spans) <= total_resumes
        if imported_profile_run is None:
            assert any(span.name == "candidate_profile.model_attempt" for span in telemetry.spans)
        else:
            assert not any(span.name == "candidate_profile.model_attempt" for span in telemetry.spans)
        assert any(span.name == "role_definition.model_attempt" for span in telemetry.spans)
        assert any(span.name == "role_evidence_assessment.model_attempt" for span in telemetry.spans)
        # Specialists now run as delegated subagents (streamed, not invoked via
        # invoke_structured), so only the mandatory fresh judge call still
        # produces its own telemetry span -- except on a paused run, where the
        # judge never runs at all (nothing approved yet to judge).
        if target_assessment_artifact.status != "paused":
            assert any(span.name == "open_agent_assessment.judge_attempt" for span in telemetry.spans)
        forbidden_span_content = (resume_text, args.initial_message, args.follow_up_message)
        assert not any(
            secret and secret in str(value)
            for span in telemetry.spans
            for value in span.attributes.values()
            for secret in forbidden_span_content
        )
    else:
        assert [span.name for span in telemetry.spans].count("model") <= 2
        assert any(span.status == "error" for span in telemetry.spans)

    report = {
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
        "status": "failed" if journey_error else "completed",
        "error": journey_error,
        "scenario": {
            "initial_message": args.initial_message,
            "follow_up_message": args.follow_up_message,
            "search_query": args.search_query,
            "candidate_profile_resume_attempts": args.candidate_profile_resume_attempts,
            "role_profile_resume_attempts": args.role_profile_resume_attempts,
            "target_assessment_resume_attempts": args.target_assessment_resume_attempts,
            "target_job_id": args.target_job_id,
            "runtime_models": {
                "conversation": args.conversation_model,
                "role_definition": args.role_definition_model,
                "role_evidence": args.role_evidence_model,
                "assessment": args.assessment_model,
            },
            "max_output_tokens": args.max_output_tokens,
            "candidate_profile_source": ("validated_report" if imported_profile_run is not None else "live_model"),
            "candidate_profile_report": (
                str(Path(args.candidate_profile_report).expanduser().resolve())
                if args.candidate_profile_report
                else None
            ),
        },
        "parse_report": parse_report,
        "thread_id": thread_id,
        "run_ids": [receipt.run_id for receipt in receipts],
        "trace_keys": [receipt.trace_key for receipt in receipts],
        "assistant_outputs": [message.content for message in snapshot.messages if message.role == "assistant"],
        "activity": [asdict(event) for event in events],
        "spans": [asdict(span) for span in telemetry.spans],
        "recommendations": [
            {
                "job_id": job.job_id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "salary": job.salary,
                "seniority": job.seniority,
                "similarity_score": job.similarity_score,
                "source": asdict(job.source),
                "duplicate_count": max(0, len(job.posting_variants) - 1),
                "posting_variants": [asdict(variant) for variant in job.posting_variants],
            }
            for job in snapshot.case_facts.recommendations
        ],
        "selected_target": (
            asdict(snapshot.case_facts.selected_target) if snapshot.case_facts.selected_target else None
        ),
        "candidate_profile_artifact": (asdict(candidate_profile_artifact) if candidate_profile_artifact else None),
        "attempted_target": asdict(attempted_target) if attempted_target else None,
        "role_success_profile": (
            asdict(snapshot.case_facts.role_success_profile) if snapshot.case_facts.role_success_profile else None
        ),
        "target_assessment_artifact": (asdict(target_assessment_artifact) if target_assessment_artifact else None),
    }
    rendered = json.dumps(report, indent=2, default=str, ensure_ascii=False)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.write_text(rendered + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(output_path),
                    "elapsed_ms": report["elapsed_ms"],
                    "runs": len(report["run_ids"]),
                    "spans": len(report["spans"]),
                    "recommendations": len(report["recommendations"]),
                    "criteria": len((report["role_success_profile"] or {}).get("criteria") or []),
                    "candidate_profile_fields": len(
                        ((report["candidate_profile_artifact"] or {}).get("profile") or {}).get("fields") or []
                    ),
                    "specialist_runs": len((report["target_assessment_artifact"] or {}).get("specialist_runs") or []),
                    "judge_score": (((report["target_assessment_artifact"] or {}).get("judge") or {}).get("score")),
                },
                indent=2,
            )
        )
    else:
        print(rendered)
    return 1 if journey_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
