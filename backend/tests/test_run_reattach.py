from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from auth import get_current_user
from database import Base, get_db
from models import (
    ProposedResumeEdit,
    RecruitmentActivityEvent,
    RecruitmentMessage,
    RecruitmentRun,
    RecruitmentThread,
    ResumeVersion,
    User,
)
from recruitment_team.http_routes import get_recruitment_telemetry
from recruitment_team.telemetry import RecordedTelemetry


def _sse(response):
    return [
        {
            line.split(": ", 1)[0]: line.split(": ", 1)[1]
            for line in block.splitlines()
        }
        for block in response.text.strip().split("\n\n")
    ]


def test_accepted_run_replays_only_new_events_and_its_stored_receipt():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        owner = User(email="owner@example.com", password_hash="x", name="Owner")
        stranger = User(email="stranger@example.com", password_hash="x", name="Stranger")
        db.add_all([owner, stranger])
        db.flush()
        resume = ResumeVersion(user_id=owner.id, label="Resume", resume_text="Evidence")
        db.add(resume)
        db.flush()
        thread = RecruitmentThread(
            id="thread-1",
            user_id=owner.id,
            resume_version_id=resume.id,
            case_facts={},
            next_event_sequence=4,
        )
        run = RecruitmentRun(
            id="run-1",
            user_id=owner.id,
            thread_id=thread.id,
            idempotency_key="key-1",
            command_type="send_message",
            status="completed",
            trace_key="trace-1",
            result={
                "run_id": "run-1",
                "thread_id": "thread-1",
                "status": "completed",
                "trace_key": "trace-1",
                "workflow_state": "exploring",
            },
        )
        db.add_all([thread, run])
        for sequence, status in ((1, "running"), (2, "working"), (3, "completed")):
            db.add(RecruitmentActivityEvent(
                thread_id=thread.id,
                run_id=run.id,
                sequence=sequence,
                event_type="run",
                status=status,
                team_member="coordinator",
                trace_key=run.trace_key,
                summary=status,
                detail={},
            ))
        db.commit()
        owner_id, stranger_id = owner.id, stranger.id

    def override_db():
        with sessions() as db:
            yield db

    current_user = {"id": owner_id}
    main.app.dependency_overrides[get_db] = override_db
    main.app.dependency_overrides[get_current_user] = lambda: type("User", (), current_user)()
    main.app.dependency_overrides[get_recruitment_telemetry] = RecordedTelemetry
    try:
        client = TestClient(main.app)
        with sessions() as db:
            before = (
                db.query(RecruitmentRun).count(),
                db.query(RecruitmentMessage).count(),
                db.query(ProposedResumeEdit).count(),
            )

        replay = client.get(
            "/api/recruitment-team/runs/run-1/stream",
            params={"after_sequence": 1},
        )
        blocks = _sse(replay)
        assert replay.status_code == 200
        assert [block["event"] for block in blocks] == ["activity", "activity", "receipt"]
        assert [block["id"] for block in blocks[:2]] == ["2", "3"]
        assert [json.loads(block["data"])["sequence"] for block in blocks[:2]] == [2, 3]
        assert json.loads(blocks[-1]["data"])["run_id"] == "run-1"

        terminal = _sse(client.get(
            "/api/recruitment-team/runs/run-1/stream",
            params={"after_sequence": 3},
        ))
        assert [block["event"] for block in terminal] == ["receipt"]
        assert json.loads(terminal[0]["data"]) == json.loads(blocks[-1]["data"])

        with sessions() as db:
            assert (
                db.query(RecruitmentRun).count(),
                db.query(RecruitmentMessage).count(),
                db.query(ProposedResumeEdit).count(),
            ) == before

        current_user["id"] = stranger_id
        assert client.get("/api/recruitment-team/runs/run-1/stream").status_code == 404
        assert client.get(
            "/api/recruitment-team/runs/run-1/stream",
            params={"after_sequence": "bad"},
        ).status_code == 422
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()


def test_failed_run_replays_the_exact_original_safe_error_without_new_work():
    from recruitment_team.errors import ConversationUnavailable
    from recruitment_team.http_routes import (
        get_candidate_profiler_factory_provider,
        get_conversation_model,
        get_job_discovery,
        get_role_success_profiler,
    )
    from recruitment_team.recovery import classify_failure
    from recruitment_team.candidate_profile import ScriptedCandidateProfilerFactory
    from backend.tests.test_recruitment_team_module import _candidate_profile_run

    class FailingModel:
        def __init__(self):
            self.calls = 0

        def respond(self, *_args, **_kwargs):
            self.calls += 1
            raise ConversationUnavailable(
                "The coordinator could not produce a complete reply. Try this turn again.",
                decision=classify_failure("structured_output_invalid", attempts_remaining=True),
            )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        owner = User(email="owner@example.com", password_hash="x", name="Owner")
        db.add(owner)
        db.flush()
        resume = ResumeVersion(user_id=owner.id, label="Resume", resume_text="Evidence")
        db.add(resume)
        db.commit()
        owner_id, resume_id = owner.id, resume.id

    def override_db():
        with sessions() as db:
            yield db

    model = FailingModel()
    main.app.dependency_overrides[get_db] = override_db
    main.app.dependency_overrides[get_current_user] = lambda: type("User", (), {"id": owner_id})()
    main.app.dependency_overrides[get_recruitment_telemetry] = RecordedTelemetry
    main.app.dependency_overrides[get_conversation_model] = lambda: model
    main.app.dependency_overrides[get_job_discovery] = lambda: None
    main.app.dependency_overrides[get_role_success_profiler] = lambda: None
    main.app.dependency_overrides[get_candidate_profiler_factory_provider] = (
        lambda: lambda: ScriptedCandidateProfilerFactory([_candidate_profile_run()])
    )
    try:
        client = TestClient(main.app)
        original = _sse(client.post(
            "/api/recruitment-team/threads/stream",
            json={
                "resume_version_id": resume_id,
                "message": "Find roles for me.",
                "idempotency_key": "failed-reattach",
            },
        ))
        assert original[-1]["event"] == "error"
        assert all(block["event"] == "activity" for block in original[:-1])
        run_id = json.loads(original[0]["data"])["run_id"]
        original_error = json.loads(original[-1]["data"])
        assert original_error["message"] == (
            "The coordinator could not produce a complete reply. Try this turn again."
        )

        with sessions() as db:
            before = (
                db.query(RecruitmentRun).count(),
                db.query(RecruitmentMessage).count(),
                db.query(ProposedResumeEdit).count(),
            )
            failed = db.get(RecruitmentRun, run_id)
            assert failed.status == "failed"

        replay = _sse(client.get(
            f"/api/recruitment-team/runs/{run_id}/stream",
            params={"after_sequence": 0},
        ))
        assert [block["event"] for block in replay] == [block["event"] for block in original]
        assert json.loads(replay[-1]["data"]) == original_error
        assert model.calls == 1
        with sessions() as db:
            assert (
                db.query(RecruitmentRun).count(),
                db.query(RecruitmentMessage).count(),
                db.query(ProposedResumeEdit).count(),
            ) == before
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
