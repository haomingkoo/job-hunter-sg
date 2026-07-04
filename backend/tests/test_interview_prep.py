from __future__ import annotations

import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _create_workspace():
    from auth import hash_password
    from database import SessionLocal, init_db
    from models import TrackedJob, User

    init_db()
    db = SessionLocal()
    user = User(
        email=f"interview_prep_{secrets.token_hex(4)}@aisg.sg",
        password_hash=hash_password("TestPassword123!"),
        name="Interview Prep User",
        tier="pro",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = TrackedJob(
        user_id=user.id,
        company="GovTech",
        role="Senior AI Engineer",
        status="interview",
        job_description="Build agentic workflows for public-sector digital services.",
        role_metadata={},
        stage_history=[],
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return db, user, workspace


def _save_fake_role_research(db, user, workspace):
    import role_research

    return role_research.save_role_brief(
        db,
        user.id,
        workspace.id,
        company_notes="GovTech builds digital public services in Singapore.",
        role_notes="Role signals applied AI and platform delivery.",
        comparable_titles=[
            {
                "value": "AI Engineer",
                "source_url": "https://www.tech.gov.sg/careers/ai-engineer",
                "source_type": role_research.SOURCE_COMPANY,
                "retrieved_at": "2026-07-04T03:30:00+00:00",
                "confidence": role_research.CONFIDENCE_HIGH,
                "evidence_note": "Company careers page uses AI Engineer title.",
            }
        ],
        ats_keywords=[
            {
                "value": "Python",
                "source_url": "https://www.mycareersfuture.gov.sg/job/example",
                "source_type": role_research.SOURCE_JOB_BOARD,
                "retrieved_at": "2026-07-04T03:32:00+00:00",
                "confidence": role_research.CONFIDENCE_HIGH,
                "evidence_note": "Job board listing repeats Python as a required skill.",
            },
            {
                "value": "Python",
                "source_url": "https://www.mycareersfuture.gov.sg/job/example/",
                "source_type": role_research.SOURCE_JOB_BOARD,
                "retrieved_at": "2026-07-04T03:32:00+00:00",
                "confidence": role_research.CONFIDENCE_HIGH,
                "evidence_note": "Duplicate keyword/source should not create another question.",
            },
        ],
        source_leads=[
            {
                "value": "Company careers page",
                "source_url": "https://www.tech.gov.sg/careers/ai-engineer",
                "source_type": role_research.SOURCE_COMPANY,
                "retrieved_at": "2026-07-04T03:34:00+00:00",
                "confidence": role_research.CONFIDENCE_HIGH,
                "evidence_note": "Company role source for later review.",
            }
        ],
    )


def test_interview_prep_pack_links_research_sources_and_candidate_evidence():
    import candidate_evidence
    import interview_prep

    db, user, workspace = _create_workspace()
    try:
        _save_fake_role_research(db, user, workspace)
        candidate_evidence.record_claim_evidence(
            db,
            user.id,
            workspace.id,
            claim_key="python-data-pipelines",
            claim_text="Built Python data pipelines for public-sector services.",
            source_text="EXPERIENCE - Built Python data pipelines for public-sector services.",
            source_type="master_resume",
            proof_status=candidate_evidence.PROOF_SUPPORTED,
        )

        pack = interview_prep.generate_prep_pack(db, user.id, workspace.id)

        assert pack["status"] == interview_prep.STATUS_READY
        assert pack["summary"]["question_count"] == 2
        assert pack["summary"]["source_count"] == 2
        assert len(pack[interview_prep.SOURCE_LEADS_KEY]) == 1
        assert {cluster["type"] for cluster in pack[interview_prep.QUESTION_CLUSTERS_KEY]} == {
            interview_prep.QUESTION_TECHNICAL,
            interview_prep.QUESTION_ROLE_FIT,
        }
        python_cluster = next(
            cluster
            for cluster in pack[interview_prep.QUESTION_CLUSTERS_KEY]
            if "Python" in cluster["question"]
        )
        title_cluster = next(
            cluster
            for cluster in pack[interview_prep.QUESTION_CLUSTERS_KEY]
            if "AI Engineer" in cluster["question"]
        )
        assert python_cluster["confidence"] == "high"
        assert python_cluster["source_url"].startswith("https://")
        assert python_cluster["retrieved_at"]
        assert python_cluster["answer_scaffold"]["status"] == interview_prep.SCAFFOLD_EVIDENCE_BACKED
        assert python_cluster["answer_scaffold"]["claim_id"]
        assert python_cluster["answer_scaffold"]["evidence_id"]
        assert title_cluster["answer_scaffold"]["status"] == interview_prep.SCAFFOLD_NEEDS_USER_INPUT
        assert pack["summary"]["evidence_question_count"] == 1
    finally:
        db.close()


def test_interview_prep_missing_candidate_evidence_asks_for_input():
    import interview_prep

    db, user, workspace = _create_workspace()
    try:
        _save_fake_role_research(db, user, workspace)

        pack = interview_prep.generate_prep_pack(db, user.id, workspace.id)

        assert pack["status"] == interview_prep.STATUS_READY
        assert pack["summary"]["evidence_question_count"] > 0
        assert pack[interview_prep.EVIDENCE_QUESTIONS_KEY][0]["question"].startswith(
            "What specific candidate evidence"
        )
        assert all(
            cluster["answer_scaffold"]["status"] == interview_prep.SCAFFOLD_NEEDS_USER_INPUT
            for cluster in pack[interview_prep.QUESTION_CLUSTERS_KEY]
        )
    finally:
        db.close()


def test_interview_prep_missing_role_research_is_degraded_not_generic():
    import interview_prep

    db, user, workspace = _create_workspace()
    try:
        pack = interview_prep.generate_prep_pack(db, user.id, workspace.id)

        assert pack["status"] == interview_prep.STATUS_DEGRADED
        assert pack["degraded_reason"] == interview_prep.DEGRADED_REASON_NO_RESEARCH
        assert pack[interview_prep.QUESTION_CLUSTERS_KEY] == []
        assert pack[interview_prep.EVIDENCE_QUESTIONS_KEY] == []
    finally:
        db.close()
