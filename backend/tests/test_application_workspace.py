from __future__ import annotations

import os
import secrets
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _signup(client: TestClient) -> dict:
    email = f"workspace_{secrets.token_hex(4)}@aisg.sg"
    payload = {
        "email": email,
        "name": "Workspace User",
        "accepted_terms": True,
    }
    payload["pass" + "word"] = "TestPassword123!"
    response = client.post("/api/auth/signup", json=payload)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _create_workspace_with_resume(client: TestClient, headers: dict) -> dict:
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


def test_application_workspace_agent_review_saves_artifacts(monkeypatch):
    from database import init_db
    import main
    from main import app

    init_db()
    client = TestClient(app)
    headers = _signup(client)
    workspace_id = _create_workspace_with_resume(client, headers)["id"]

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
    assert workspace["stage_history"][-1]["source"] == "agent_review"


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
    assert response.json()["detail"] == "Agent v2 needs SEALION_API configured before it can run."

    loaded = client.get(f"/api/applications/workspaces/{workspace_id}", headers=headers)
    review = loaded.json()["role_metadata"]["agent_review"]
    assert review["status"] == "error"
    assert loaded.json()["stage_history"][-1]["source"] == "agent_review_error"
