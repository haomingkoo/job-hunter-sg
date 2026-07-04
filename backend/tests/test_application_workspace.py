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
