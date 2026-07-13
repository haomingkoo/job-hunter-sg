from __future__ import annotations

import os
import secrets
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _create_workspace():
    from auth import hash_password
    from database import SessionLocal, init_db
    from models import TrackedJob, User

    init_db()
    db = SessionLocal()
    user = User(
        email=f"candidate_evidence_{secrets.token_hex(4)}@aisg.sg",
        password_hash=hash_password("TestPassword123!"),
        name="Evidence User",
        tier="pro",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = TrackedJob(
        user_id=user.id,
        company="GovTech",
        role="Senior AI Engineer",
        status="saved",
        job_description="Build agentic workflows for public-sector digital services.",
        role_metadata={
            "submitted_resume_artifacts": [
                {
                    "artifact_id": "submitted-resume-1",
                    "filename": "resume.pdf",
                }
            ]
        },
        stage_history=[],
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return db, user, workspace


def test_candidate_evidence_links_claim_source_application_and_artifact():
    import candidate_evidence

    db, user, workspace = _create_workspace()
    try:
        graph = candidate_evidence.record_claim_evidence(
            db,
            user.id,
            workspace.id,
            claim_key="python-data-pipelines",
            claim_text="Built Python data pipelines for public-sector services.",
            source_text="EXPERIENCE - Built Python data pipelines for public-sector services.",
            source_type="master_resume",
            proof_status=candidate_evidence.PROOF_SUPPORTED,
            artifact_id="submitted-resume-1",
            artifact_kind="submitted_resume",
        )

        assert len(graph[candidate_evidence.CLAIMS_KEY]) == 1
        assert len(graph[candidate_evidence.EVIDENCE_KEY]) == 1
        claim = next(iter(graph[candidate_evidence.CLAIMS_KEY].values()))
        evidence = next(iter(graph[candidate_evidence.EVIDENCE_KEY].values()))
        assert claim["resume_claim"] == "Built Python data pipelines for public-sector services."
        assert evidence["claim_id"] == claim["id"]
        assert graph[candidate_evidence.APPLICATION_LINKS_KEY] == [
            {
                "workspace_id": workspace.id,
                "claim_id": claim["id"],
                "evidence_id": evidence["id"],
                "proof_status": candidate_evidence.PROOF_SUPPORTED,
            }
        ]
        assert graph[candidate_evidence.ARTIFACT_LINKS_KEY] == [
            {
                "workspace_id": workspace.id,
                "artifact_id": "submitted-resume-1",
                "artifact_kind": "submitted_resume",
                "claim_id": claim["id"],
                "evidence_id": evidence["id"],
            }
        ]

        same_graph = candidate_evidence.record_claim_evidence(
            db,
            user.id,
            workspace.id,
            claim_key=" python-data-pipelines ",
            claim_text="Built Python data pipelines for public-sector services.",
            source_text="EXPERIENCE   - Built Python data pipelines for public-sector services.",
            source_type="master_resume",
            proof_status=candidate_evidence.PROOF_SUPPORTED,
            artifact_id="submitted-resume-1",
            artifact_kind="submitted_resume",
        )

        assert len(same_graph[candidate_evidence.CLAIMS_KEY]) == 1
        assert len(same_graph[candidate_evidence.EVIDENCE_KEY]) == 1
        assert len(same_graph[candidate_evidence.APPLICATION_LINKS_KEY]) == 1
        assert len(same_graph[candidate_evidence.ARTIFACT_LINKS_KEY]) == 1
    finally:
        db.close()


@pytest.mark.parametrize("proof_status", ["needs_confirmation", "unsupported"])
def test_uncertain_evidence_requires_confirmation_instead_of_resume_claim(proof_status):
    import candidate_evidence

    db, user, workspace = _create_workspace()
    try:
        graph = candidate_evidence.record_claim_evidence(
            db,
            user.id,
            workspace.id,
            claim_key="kubernetes-production",
            claim_text="Ran production Kubernetes services.",
            source_text="Profile note says Kubernetes, but resume has no production operations detail.",
            source_type="profile_context",
            proof_status=proof_status,
        )

        claim = next(iter(graph[candidate_evidence.CLAIMS_KEY].values()))
        assert claim["proof_status"] == proof_status
        assert claim["resume_claim"] == ""
        assert "Can you confirm" in claim["confirmation_question"]
    finally:
        db.close()
