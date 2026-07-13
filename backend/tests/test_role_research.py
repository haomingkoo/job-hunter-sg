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
        email=f"role_research_{secrets.token_hex(4)}@aisg.sg",
        password_hash=hash_password("TestPassword123!"),
        name="Role Research User",
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
        role_metadata={},
        stage_history=[],
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return db, user, workspace


def _fake_research_source() -> dict:
    return {
        "company_notes": "GovTech builds digital public services in Singapore.",
        "role_notes": "Role signals applied AI, platform work, and public-sector delivery.",
        "comparable_titles": [
            {
                "value": "AI Engineer",
                "source_url": "https://www.tech.gov.sg/careers/ai-engineer/",
                "source_type": "company",
                "retrieved_at": "2026-07-04T03:30:00+00:00",
                "confidence": "high",
                "evidence_note": "Company careers page uses AI Engineer title.",
            },
            {
                "value": "Applied AI Engineer",
                "source_url": "https://www.reddit.com/r/singaporefi/comments/example",
                "source_type": "reddit",
                "retrieved_at": "2026-07-04T03:31:00+00:00",
                "confidence": "low",
                "evidence_note": "Public Reddit discussion mentions similar local role wording.",
            },
        ],
        "ats_keywords": [
            {
                "value": "Python",
                "source_url": "https://www.mycareersfuture.gov.sg/job/example",
                "source_type": "job_board",
                "retrieved_at": "2026-07-04T03:32:00+00:00",
                "confidence": "high",
                "evidence_note": "Job board listing repeats Python as a required skill.",
            },
            {
                "value": "stakeholder management",
                "source_url": "https://www.glassdoor.sg/Interview/govtech-interview-questions.htm",
                "source_type": "glassdoor",
                "retrieved_at": "2026-07-04T03:33:00+00:00",
                "confidence": "medium",
                "evidence_note": "Public Glassdoor interview reports emphasize stakeholder scenarios.",
            },
        ],
        "source_leads": [
            {
                "value": "Company careers page",
                "source_url": "https://www.tech.gov.sg/careers/ai-engineer",
                "source_type": "company",
                "retrieved_at": "2026-07-04T03:34:00+00:00",
                "confidence": "high",
                "evidence_note": "Duplicate company URL should dedupe with the title source.",
            },
            {
                "value": "Generic web search lead",
                "source_url": "https://example.com/govtech-ai-engineer",
                "source_type": "web",
                "retrieved_at": "2026-07-04T03:35:00+00:00",
                "confidence": "unknown",
                "evidence_note": "Generic web result for later review.",
            },
        ],
    }


def test_role_research_saves_sourced_brief_and_dedupes_sources():
    import role_research

    db, user, workspace = _create_workspace()
    try:
        brief = role_research.save_role_brief(
            db,
            user.id,
            workspace.id,
            **_fake_research_source(),
        )

        assert brief["status"] == role_research.STATUS_READY
        assert brief["empty"] is False
        assert brief["company_notes"] == "GovTech builds digital public services in Singapore."
        assert brief["candidate_experience_used"] is False
        assert brief["resume_claims"] == []

        source_types = {source["source_type"] for source in brief[role_research.SOURCES_KEY]}
        assert source_types == {"company", "job_board", "glassdoor", "reddit", "web"}
        assert len(brief[role_research.SOURCES_KEY]) == 5

        for group_key in (
            role_research.COMPARABLE_TITLES_KEY,
            role_research.ATS_KEYWORDS_KEY,
            role_research.SOURCE_LEADS_KEY,
        ):
            for item in brief[group_key]:
                assert item["source_url"].startswith("https://")
                assert item["source_type"] in role_research.SOURCE_TYPES
                assert item["retrieved_at"]
                assert item["confidence"] in role_research.CONFIDENCE_LABELS
                assert item["evidence_note"]
    finally:
        db.close()


def test_role_research_empty_source_result_is_degraded_and_visible():
    import role_research

    db, user, workspace = _create_workspace()
    try:
        brief = role_research.save_role_brief(
            db,
            user.id,
            workspace.id,
            company_notes="",
            role_notes="",
            comparable_titles=[],
            ats_keywords=[],
            source_leads=[],
        )

        assert brief["status"] == role_research.STATUS_DEGRADED
        assert brief["empty"] is True
        assert brief["degraded_reason"] == role_research.DEGRADED_REASON_NO_SOURCES
        assert brief[role_research.SOURCES_KEY] == []
    finally:
        db.close()
