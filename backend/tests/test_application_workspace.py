from __future__ import annotations

import os
import io
import secrets
import sys
from datetime import datetime, timezone

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _signup(client: TestClient) -> dict:
    from auth import create_token
    from database import SessionLocal
    from models import User

    with SessionLocal() as db:
        user = User(
            email=f"workspace_{secrets.token_hex(4)}@aisg.sg",
            password_hash="test-only",  # pragma: allowlist secret
            name="Workspace User",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_token(user.id, user.token_version)
    return {"Authorization": f"Bearer {token}"}


def _create_workspace_with_resume(client: TestClient, headers: dict, role_metadata: dict | None = None) -> dict:
    resume = client.post("/api/resume/versions", json={
        "label": "Master resume",
        "resume_text": "EXPERIENCE\n- Built Python data pipelines for public-sector services.",
        "is_master": True,
    }, headers=headers)
    assert resume.status_code == 200

    created = client.post("/api/applications/workspaces", json={
        "company": "GovTech",
        "title": "Senior AI Engineer",
        "job_description": "Build agentic workflows for public-sector digital services.",
        "status": "saved",
        "resume_version_id": resume.json()["id"],
        "role_metadata": role_metadata or {},
    }, headers=headers)
    assert created.status_code == 201
    return created.json()


def test_application_workspace_stores_job_context_and_append_only_history():
    from database import init_db
    from main import app

    init_db()
    client = TestClient(app)
    headers = _signup(client)

    version = client.post("/api/resume/versions", json={
        "label": "Master resume",
        "resume_text": "Built AI job-search workflows with Python, React, FastAPI, and reliable tests.",
        "is_master": True,
    }, headers=headers)
    assert version.status_code == 200
    stored_version = client.get(
        f"/api/resume/versions/{version.json()['id']}",
        headers=headers,
    ).json()
    from resume_document import is_resume_document

    assert is_resume_document(stored_version["resume_structured"])
    assert stored_version["resume_structured"]["raw_text"] == stored_version["resume_text"]

    created = client.post("/api/applications/workspaces", json={
        "company": "GovTech",
        "title": "Senior AI Engineer",
        "job_description": "Build agentic workflows for public-sector digital services.",
        "source_url": "https://example.com/jobs/ai-engineer",
        "source": "manual",
        "status": "saved",
        "date_applied": "2026-07-04",
        "resume_version_id": version.json()["id"],
        "role_metadata": {"seniority": "senior", "location": "Singapore"},
    }, headers=headers)
    assert created.status_code == 201
    workspace = created.json()

    assert workspace["company"] == "GovTech"
    assert workspace["title"] == "Senior AI Engineer"
    assert workspace["job_description"] == "Build agentic workflows for public-sector digital services."
    assert workspace["source_url"] == "https://example.com/jobs/ai-engineer"
    assert workspace["resume_version_id"] == version.json()["id"]
    assert workspace["role_metadata"] == {"seniority": "senior", "location": "Singapore"}
    assert [event["stage"] for event in workspace["stage_history"]] == ["saved"]

    updated = client.put(
        f"/api/tracked/{workspace['id']}",
        json={"status": "interview"},
        headers=headers,
    )
    assert updated.status_code == 200

    loaded = client.get(f"/api/applications/workspaces/{workspace['id']}", headers=headers)
    assert loaded.status_code == 200
    assert [event["stage"] for event in loaded.json()["stage_history"]] == [
        "saved",
        "interview",
    ]


def test_application_outcomes_are_queryable_by_status_history_and_resume_version():
    from database import init_db
    from main import app

    init_db()
    client = TestClient(app)
    headers = _signup(client)
    workspace = _create_workspace_with_resume(client, headers)
    version_id = workspace["resume_version_id"]

    moved = client.put(
        f"/api/tracked/{workspace['id']}",
        json={"status": "interview"},
        headers=headers,
    )
    assert moved.status_code == 200

    for company, status, resume_version_id in [
        ("Submitted Co", "applied", version_id),
        ("Offer Co", "accepted", version_id),
        ("Rejected Co", "rejected", None),
        ("Withdrawn Co", "withdrawn", None),
        ("Silent Co", "no_response", None),
    ]:
        response = client.post("/api/tracked", json={
            "company": company,
            "role": "AI Program Manager",
            "date_applied": "2026-07-04",
            "status": status,
            "resume_version_id": resume_version_id,
        }, headers=headers)
        assert response.status_code == 201

    response = client.get("/api/applications/outcomes", headers=headers)
    assert response.status_code == 200
    summary = response.json()

    assert summary["total_applications"] == 6
    assert summary["counts"] == {
        "submitted": 1,
        "interview": 1,
        "offer": 1,
        "rejected": 1,
        "withdrawn": 1,
        "no_response": 1,
    }
    assert summary["stage_counts"]["interview"] == 1
    assert summary["stage_counts"]["submitted"] == 1
    assert summary["unlinked_applications"] == 3
    assert summary["resume_versions"] == [
        {
            "resume_version_id": version_id,
            "applications": 3,
            "counts": {
                "submitted": 1,
                "interview": 1,
                "offer": 1,
                "rejected": 0,
                "withdrawn": 0,
                "no_response": 0,
            },
        }
    ]


def test_application_workspace_requires_company_title_and_job_description():
    from database import init_db
    from main import app

    init_db()
    client = TestClient(app)
    headers = _signup(client)

    response = client.post("/api/applications/workspaces", json={
        "company": "GovTech",
        "title": "Senior AI Engineer",
    }, headers=headers)

    assert response.status_code == 422
    assert "job_description" in response.text


def test_application_workspace_module_creates_and_moves_workspace():
    from application_workspace import (
        create_application_workspace,
        get_application_workspace,
        update_tracked_job,
    )
    from database import SessionLocal, init_db
    from models import User
    from schemas import ApplicationWorkspaceCreate, TrackedJobUpdate

    init_db()
    db = SessionLocal()
    try:
        from auth import hash_password

        user = User(
            email=f"workspace_module_{secrets.token_hex(4)}@aisg.sg",
            password_hash=hash_password("TestPassword123!"),
            name="Workspace Module User",
            tier="pro",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        workspace = create_application_workspace(
            db,
            user,
            ApplicationWorkspaceCreate(
                company="GovTech",
                title="Senior AI Engineer",
                job_description="Build agentic workflows for public-sector digital services.",
                status="saved",
            ),
        )
        assert workspace["title"] == "Senior AI Engineer"
        assert [event["stage"] for event in workspace["stage_history"]] == ["saved"]

        moved = update_tracked_job(
            db,
            user,
            workspace["id"],
            TrackedJobUpdate(status="interview"),
        )
        loaded = get_application_workspace(db, user.id, moved.id)

        assert loaded["status"] == "interview"
        assert [event["stage"] for event in loaded["stage_history"]] == [
            "saved",
            "interview",
        ]
    finally:
        db.close()


def test_recruitment_pipeline_reuses_record_and_preserves_user_workspace_data():
    from application_workspace import create_tracked_job, ensure_recruitment_application
    from database import SessionLocal, init_db
    from models import ResumeVersion, TrackedJob, User
    from schemas import TrackedJobCreate

    init_db()
    db = SessionLocal()
    try:
        user = User(
            email=f"pipeline_{secrets.token_hex(4)}@aisg.sg",
            password_hash="test-only",  # pragma: allowlist secret
            name="Pipeline User",
            tier="pro",
        )
        db.add(user)
        db.flush()
        resume = ResumeVersion(
            user_id=user.id,
            label="Operations resume",
            resume_text="Led semiconductor manufacturing transformation.",
            is_master=True,
        )
        db.add(resume)
        db.commit()

        existing = create_tracked_job(
            db,
            user,
            TrackedJobCreate(
                company="Example Semiconductor",
                role="Operations Manager",
                status="interview",
                notes="Follow up with the hiring manager.",
                role_metadata={
                    "contacts": [{"name": "Hiring Manager", "details": "Introduced at SEMICON"}],
                    "activity": [{"type": "contact_added", "recorded_at": "2026-08-01T00:00:00Z"}],
                },
                resume_version_id=resume.id,
            ),
        )
        original_history = list(existing.stage_history)

        reused = ensure_recruitment_application(
            db,
            user,
            TrackedJobCreate(
                company="Example Semiconductor",
                role="Operations Manager",
                status="saved",
                source="MyCareersFuture",
                source_url="https://example.test/jobs/901",
                job_description="Lead fab operations and continuous improvement.",
                scraped_job_id=901,
                resume_version_id=resume.id,
            ),
            thread_id="thread-pipeline",
            source_job_id=901,
            posting_snapshot={"job_id": 901, "description": "Original posting snapshot"},
            fit_evidence={"matched": [{"statement": "Manufacturing leadership"}]},
            selected=True,
            existing_tracked_job_id=existing.id,
        )
        db.commit()
        db.refresh(reused)

        assert db.query(TrackedJob).filter(TrackedJob.user_id == user.id).count() == 1
        assert reused.id == existing.id
        assert reused.status == "interview"
        assert reused.notes == "Follow up with the hiring manager."
        assert reused.stage_history == original_history
        assert reused.role_metadata["contacts"][0]["name"] == "Hiring Manager"
        assert reused.role_metadata["activity"][0]["type"] == "contact_added"
        assert reused.role_metadata["recruitment_pipeline"]["state"] == "selected"
        assert reused.role_metadata["recruitment_pipeline"]["posting_snapshot"]["job_id"] == 901
    finally:
        db.close()


def test_application_workspace_agent_review_saves_artifacts(monkeypatch):
    from database import init_db
    import main
    from main import app

    init_db()
    client = TestClient(app)
    headers = _signup(client)
    workspace = _create_workspace_with_resume(
        client,
        headers,
        role_metadata={"submitted_resume": {"artifact_id": "submitted-1"}},
    )
    workspace_id = workspace["id"]
    source_resume_version_id = workspace["resume_version_id"]

    seen_body = {}

    def fake_stream(body):
        seen_body.update(body)
        yield {"event": "session", "session_id": "workspace-agent-review"}
        yield {"event": "token", "session_id": "workspace-agent-review", "content": "Emphasize agentic workflow delivery."}
        yield {"event": "done", "session_id": "workspace-agent-review"}

    monkeypatch.setattr(main, "_stream_resume_agent_events", fake_stream)
    monkeypatch.setattr(
        main,
        "_get_resume_agent_state",
        lambda session_id, owner_key=None: {
            "session_id": session_id,
            "pending_diffs": [
                {
                    "bullet_id": "exp-0-b0",
                    "original": "Built Python data pipelines for public-sector services.",
                    "rewrite": "Built agentic Python data workflows for public-sector services.",
                    "status": "pending",
                }
            ],
            "debate_summary": {
                "roles": ["recruiter", "ats", "skeptic"],
                "key_disagreements": ["ATS wants more keyword coverage; skeptic wants proof before adding claims."],
                "final_recommendation": "Revise one bullet, then rerun review.",
                "confidence": "medium",
                "trace_id": "trace-123",
            },
        },
    )

    response = client.post(f"/api/applications/workspaces/{workspace_id}/agent-review", headers=headers)
    assert response.status_code == 200
    workspace = response.json()
    review = workspace["role_metadata"]["agent_review"]

    assert "GovTech" in seen_body["message"]
    assert seen_body["resume_text"] == "EXPERIENCE\n- Built Python data pipelines for public-sector services."
    assert review["status"] == "completed"
    assert review["role_brief"]["title"] == "Senior AI Engineer"
    assert review["recommendations"] == ["Emphasize agentic workflow delivery."]
    assert review["pending_diffs"][0]["bullet_id"] == "exp-0-b0"
    assert review["debate_summary"] == {
        "roles": ["recruiter", "ats", "skeptic"],
        "key_disagreements": ["ATS wants more keyword coverage; skeptic wants proof before adding claims."],
        "final_recommendation": "Revise one bullet, then rerun review.",
        "confidence": "medium",
        "trace_id": "trace-123",
    }
    assert review["tailored_draft"]["source_resume_version_id"] == source_resume_version_id
    assert workspace["role_metadata"]["submitted_resume"] == {"artifact_id": "submitted-1"}
    assert workspace["stage_history"][-1]["source"] == "agent_review"

    draft = client.get(f"/api/resume/versions/{review['tailored_draft']['resume_version_id']}", headers=headers)
    assert draft.status_code == 200
    assert draft.json()["source"] == "agent_review"
    assert "Built agentic Python data workflows for public-sector services." in draft.json()["resume_text"]

    source = client.get(f"/api/resume/versions/{source_resume_version_id}", headers=headers)
    assert source.status_code == 200
    assert "Built Python data pipelines for public-sector services." in source.json()["resume_text"]


def test_application_workspace_agent_review_returns_clean_config_error(monkeypatch):
    import resume_agent.models as agent_models
    from database import init_db
    from main import app

    init_db()
    client = TestClient(app)
    headers = _signup(client)
    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "")
    workspace_id = _create_workspace_with_resume(client, headers)["id"]

    response = client.post(f"/api/applications/workspaces/{workspace_id}/agent-review", headers=headers)
    assert response.status_code == 503
    assert response.json()["detail"] == "Agent v2 needs SEALION_API_KEYS or SEALION_API configured before it can run."

    loaded = client.get(f"/api/applications/workspaces/{workspace_id}", headers=headers)
    review = loaded.json()["role_metadata"]["agent_review"]
    assert review["status"] == "error"
    assert loaded.json()["stage_history"][-1]["source"] == "agent_review_error"


def test_application_workspace_submitted_resume_artifact_survives_draft_generation(monkeypatch):
    from docx import Document

    from database import init_db
    import main
    from main import app

    init_db()
    client = TestClient(app)
    headers = _signup(client)
    workspace = _create_workspace_with_resume(client, headers)
    workspace_id = workspace["id"]

    doc = Document()
    doc.add_paragraph("Submitted resume for GovTech Senior AI Engineer.")
    doc.add_paragraph("Built agentic workflows with Python and FastAPI.")
    buffer = io.BytesIO()
    doc.save(buffer)

    uploaded = client.post(
        f"/api/applications/workspaces/{workspace_id}/submitted-resume",
        headers=headers,
        data={"submitted_date": "2026-07-04", "notes": "Submitted through company portal."},
        files={
            "file": (
                "submitted.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert uploaded.status_code == 200
    submitted = uploaded.json()["role_metadata"]["submitted_resume"]
    assert submitted["filename"] == "submitted.docx"
    assert submitted["submitted_date"] == "2026-07-04"
    assert submitted["notes"] == "Submitted through company portal."
    assert "Submitted resume for GovTech" in submitted["text"]
    assert len(uploaded.json()["role_metadata"]["submitted_resume_artifacts"]) == 1
    assert uploaded.json()["role_metadata"]["submitted_resume_artifacts"][0]["content_base64"]

    monkeypatch.setattr(
        main,
        "_stream_resume_agent_events",
        lambda _body: iter(
            [
                {"event": "session", "session_id": "submitted-artifact-review"},
                {"event": "token", "session_id": "submitted-artifact-review", "content": "Draft saved."},
                {"event": "done", "session_id": "submitted-artifact-review"},
            ]
        ),
    )
    monkeypatch.setattr(
        main,
        "_get_resume_agent_state",
        lambda session_id, owner_key=None: {
            "session_id": session_id,
            "pending_diffs": [
                {
                    "bullet_id": "exp-0-b0",
                    "original": "Built Python data pipelines for public-sector services.",
                    "rewrite": "Built agentic Python data workflows for public-sector services.",
                    "status": "pending",
                }
            ],
        },
    )

    reviewed = client.post(f"/api/applications/workspaces/{workspace_id}/agent-review", headers=headers)
    assert reviewed.status_code == 200
    metadata = reviewed.json()["role_metadata"]
    assert metadata["submitted_resume"]["artifact_id"] == submitted["artifact_id"]
    assert len(metadata["submitted_resume_artifacts"]) == 1
    assert metadata["agent_review"]["tailored_draft"]["resume_version_id"]


def test_application_workspace_rejects_submitted_resume_over_five_megabytes():
    from database import init_db
    from main import app
    from resume_parser import MAX_FILE_SIZE

    init_db()
    client = TestClient(app)
    headers = _signup(client)
    workspace_id = _create_workspace_with_resume(client, headers)["id"]

    response = client.post(
        f"/api/applications/workspaces/{workspace_id}/submitted-resume",
        headers=headers,
        files={"file": ("oversized.pdf", b"x" * (MAX_FILE_SIZE + 1), "application/pdf")},
    )

    assert response.status_code == 413
