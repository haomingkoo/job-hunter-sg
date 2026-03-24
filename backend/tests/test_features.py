#!/usr/bin/env python3
"""
Feature test suite for Job Hunter SG backend.
Run: cd backend && python -m pytest tests/test_features.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════════
# 1. Skill Extractor
# ═══════════════════════════════════════════════════════════════════════════


class TestSkillExtractor:
    """Tests for skill_extractor.py"""

    def test_extract_known_skills_from_jd(self):
        """Should find multi-word skills that exist in KNOWN_SKILLS."""
        from skill_extractor import extract_skill_phrases

        jd = (
            "We need someone with experience in machine learning, "
            "project management, and data analysis. "
            "Cloud computing skills preferred."
        )
        skills = extract_skill_phrases(jd)
        skill_set = set(skills)
        assert "machine learning" in skill_set
        assert "project management" in skill_set
        assert "data analysis" in skill_set
        assert "cloud computing" in skill_set

    def test_no_skills_from_empty_text(self):
        from skill_extractor import extract_skill_phrases

        assert extract_skill_phrases("") == []
        assert extract_skill_phrases("   ") == []

    def test_metadata_skills_in_jd_text_are_included(self):
        """If a metadata skill appears in the JD text, always include it."""
        from skill_extractor import extract_skill_phrases

        jd = "This role requires strong quality management experience."
        skills = extract_skill_phrases(jd, job_skills=["Quality Management"])
        assert "quality management" in skills

    def test_metadata_skills_not_in_jd_and_not_known_are_excluded(self):
        """Metadata skills that don't appear in JD and aren't known should be filtered."""
        from skill_extractor import extract_skill_phrases

        jd = "We need a program manager with data analysis skills."
        skills = extract_skill_phrases(jd, job_skills=["Medical Study", "Basket Weaving"])
        assert "medical study" not in skills
        assert "basket weaving" not in skills

    def test_metadata_skills_known_but_not_in_jd_are_included(self):
        """Metadata skills in KNOWN_SKILLS but not in JD text should still be included."""
        from skill_extractor import extract_skill_phrases

        jd = "We need a software engineer."
        skills = extract_skill_phrases(jd, job_skills=["Machine Learning"])
        assert "machine learning" in skills

    def test_ngram_extraction(self):
        """The n-gram tokenizer should produce clean bigrams/trigrams."""
        from skill_extractor import _tokenize_for_ngrams, _extract_ngrams

        tokens = _tokenize_for_ngrams("strong project management skills required")
        ngrams = _extract_ngrams(tokens, 2)
        assert "project management" in ngrams
        # "skills required" should be filtered (stop-word-heavy)
        assert "skills required" not in ngrams

    def test_stop_words_filtered_from_ngrams(self):
        """N-grams starting or ending with stop words should be excluded."""
        from skill_extractor import _tokenize_for_ngrams, _extract_ngrams

        tokens = _tokenize_for_ngrams("the ability to work in a team")
        bigrams = _extract_ngrams(tokens, 2)
        # "the ability" starts with stop word
        assert not any(bg.startswith("the ") for bg in bigrams)
        # "a team" starts with stop word
        assert not any(bg.startswith("a ") for bg in bigrams)

    def test_resume_skill_matching(self):
        """Should correctly match/miss skills against resume text."""
        from skill_extractor import match_resume_skills

        resume = "Led machine learning projects and managed cross-functional teams."
        jd_skills = ["machine learning", "project management", "data analysis"]
        result = match_resume_skills(resume, jd_skills)

        matched_skills = [m["skill"] for m in result["matched"]]
        missing_skills = [m["skill"] for m in result["missing"]]
        assert "machine learning" in matched_skills
        assert "data analysis" in missing_skills
        assert result["match_percent"] > 0

    def test_resume_matching_empty_skills(self):
        from skill_extractor import match_resume_skills

        result = match_resume_skills("some resume text", [])
        assert result["matched"] == []
        assert result["missing"] == []


# ═══════════════════════════════════════════════════════════════════════════
# 2. Resume Parser
# ═══════════════════════════════════════════════════════════════════════════


class TestResumeParser:
    """Tests for resume_parser.py"""

    def test_validate_upload_pdf(self):
        from resume_parser import validate_upload

        result = validate_upload("resume.pdf", "application/pdf", 1024)
        assert result == "pdf"

    def test_validate_upload_docx(self):
        from resume_parser import validate_upload

        result = validate_upload(
            "resume.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            1024,
        )
        assert result == "docx"

    def test_validate_upload_rejects_too_large(self):
        from resume_parser import validate_upload

        with pytest.raises(ValueError, match="too large"):
            validate_upload("resume.pdf", "application/pdf", 10 * 1024 * 1024)

    def test_validate_upload_rejects_empty(self):
        from resume_parser import validate_upload

        with pytest.raises(ValueError, match="empty"):
            validate_upload("resume.pdf", "application/pdf", 0)

    def test_validate_upload_rejects_unsupported(self):
        from resume_parser import validate_upload

        with pytest.raises(ValueError, match="Unsupported"):
            validate_upload("resume.txt", "text/plain", 1024)

    def test_join_broken_lines_hyphenated(self):
        """Hyphenated line breaks should be joined."""
        from resume_parser import _join_broken_lines

        text = "Led cross-\nfunctional delivery"
        result = _join_broken_lines(text)
        assert "crossfunctional" in result or "cross-functional" in result.replace("\n", "")

    def test_join_broken_lines_preserves_sections(self):
        """Section headers should stay on their own lines."""
        from resume_parser import _join_broken_lines

        text = "PROFESSIONAL EXPERIENCE\nSoftware Engineer at Google"
        result = _join_broken_lines(text)
        lines = [l for l in result.split("\n") if l.strip()]
        assert lines[0].strip() == "PROFESSIONAL EXPERIENCE"

    def test_name_detection(self):
        """parse_resume metadata should extract a name from the first lines."""
        from resume_parser import parse_resume
        import io

        # Create a minimal DOCX for testing
        try:
            from docx import Document

            doc = Document()
            doc.add_paragraph("John Smith")
            doc.add_paragraph("john@example.com")
            doc.add_paragraph("EXPERIENCE")
            doc.add_paragraph("Software Engineer at Google")
            buf = io.BytesIO()
            doc.save(buf)
            result = parse_resume("test.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buf.getvalue())
            assert result["name"] == "John Smith"
        except ImportError:
            pytest.skip("python-docx not installed")


# ═══════════════════════════════════════════════════════════════════════════
# 3. Resume Scorer
# ═══════════════════════════════════════════════════════════════════════════


class TestResumeScorer:
    """Tests for resume_scorer.py"""

    def test_scorer_returns_all_dimensions(self):
        from resume_scorer import ResumeScorer

        scorer = ResumeScorer()
        result = scorer.analyze(
            resume_text="Led machine learning projects at Google. Managed a team of 10 engineers. "
            "Delivered $5M in cost savings through automation. Built CI/CD pipelines.",
            job_description="",
        )
        assert "overall_score" in result
        assert "dimensions" in result
        assert result["overall_score"] >= 0

    def test_scorer_with_jd_returns_keyword_match(self):
        from resume_scorer import ResumeScorer

        scorer = ResumeScorer()
        result = scorer.analyze(
            resume_text="Experienced in machine learning, data analysis, and project management. "
            "Led cross-functional teams. Built data pipelines.",
            job_description="Looking for machine learning engineer with data analysis and cloud computing skills.",
        )
        assert "keyword_match" in result
        kw = result["keyword_match"]
        assert "matched" in kw
        assert "missing" in kw

    def test_competencies_include_matched_and_missing_keywords(self):
        """Each competency item should have matched_keywords and missing_keywords."""
        from resume_scorer import ResumeScorer

        scorer = ResumeScorer()
        result = scorer.analyze(
            resume_text="Collaborated with teams. Led initiatives. Analyzed data. "
            "Managed stakeholders. Presented findings.",
        )
        competencies = result.get("dimensions", {}).get("competencies", {})
        if competencies and "items" in competencies:
            for name, item in competencies["items"].items():
                assert "matched_keywords" in item, f"{name} missing matched_keywords"
                assert "missing_keywords" in item, f"{name} missing missing_keywords"
                assert isinstance(item["matched_keywords"], list)
                assert isinstance(item["missing_keywords"], list)

    def test_action_verb_scoring(self):
        """Bullets starting with action verbs should score higher."""
        from resume_scorer import ResumeScorer

        scorer = ResumeScorer()
        strong = scorer.analyze(
            resume_text=(
                "EXPERIENCE\n"
                "• Led a team of 10 engineers to deliver $5M platform\n"
                "• Designed microservices architecture for 1M users\n"
                "• Implemented CI/CD pipeline reducing deploy time by 40%\n"
                "• Managed cross-functional collaboration across 3 offices\n"
            ),
        )
        weak = scorer.analyze(
            resume_text=(
                "EXPERIENCE\n"
                "• Was responsible for team management\n"
                "• Helped with architecture design\n"
                "• Assisted in pipeline setup\n"
                "• Various duties as assigned\n"
            ),
        )
        assert strong["overall_score"] > weak["overall_score"]

    def test_empty_resume_returns_low_score(self):
        from resume_scorer import ResumeScorer

        scorer = ResumeScorer()
        result = scorer.analyze(resume_text="")
        assert result["overall_score"] < 50


# ═══════════════════════════════════════════════════════════════════════════
# 4. Sanitizer
# ═══════════════════════════════════════════════════════════════════════════


class TestSanitizer:
    """Tests for sanitizer.py"""

    def test_sanitize_strips_html(self):
        from sanitizer import sanitize_user_input

        result = sanitize_user_input("<script>alert('xss')</script>Hello")
        assert "<script>" not in result
        assert "Hello" in result

    def test_sanitize_resume_text(self):
        from sanitizer import sanitize_resume_text

        result = sanitize_resume_text("  Normal resume text  \n  With lines  ")
        assert result.strip() == result  # Should be stripped

    def test_sanitize_job(self):
        from sanitizer import sanitize_job

        job = {
            "title": "<b>Engineer</b>",
            "company": "Google<script>",
            "description": "Normal description",
            "dedup_key": "abc123",
        }
        result = sanitize_job(job)
        assert "<b>" not in result["title"]
        assert "<script>" not in result["company"]


# ═══════════════════════════════════════════════════════════════════════════
# 5. Auth
# ═══════════════════════════════════════════════════════════════════════════


class TestAuth:
    """Tests for auth.py"""

    def test_password_hashing(self):
        from auth import hash_password, verify_password

        pw = "SecurePass123!"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed)
        assert not verify_password("wrong", hashed)

    def test_password_validation(self):
        from auth import validate_password
        from fastapi import HTTPException

        # Too short — raises HTTPException, not ValueError
        with pytest.raises(HTTPException):
            validate_password("short")

        # Valid — should not raise
        validate_password("LongEnoughPassword123")

    def test_token_creation(self):
        from auth import create_token

        token = create_token(user_id=1)
        assert isinstance(token, str)
        assert len(token) > 0


# ═══════════════════════════════════════════════════════════════════════════
# 6. API Endpoints (integration)
# ═══════════════════════════════════════════════════════════════════════════


class TestAPIEndpoints:
    """Integration tests for FastAPI endpoints."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_jobs_endpoint(self, client):
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.json()
        # Returns paginated response with jobs list
        assert "jobs" in data or isinstance(data, list)

    def test_tiers_endpoint(self, client):
        resp = client.get("/api/tiers")
        assert resp.status_code == 200

    def test_trending_skills_endpoint(self, client):
        resp = client.get("/api/skills/trending")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_resume_score_requires_text(self, client):
        resp = client.post("/api/resume/score", json={
            "resume_text": "",
            "job_description": "",
        })
        # Should return 200 with zero score or 422 validation error
        assert resp.status_code in (200, 422)

    def test_admin_seed_rejects_bad_key(self, client):
        resp = client.post(
            "/api/admin/seed",
            json={"sources": "mcf", "limit": 1},
            headers={"Authorization": "Bearer wrong_key"},
        )
        assert resp.status_code == 403

    def test_signup_and_login_flow(self, client):
        import secrets
        email = f"test_{secrets.token_hex(4)}@aisg.sg"
        pw = "TestPassword123!"

        # Signup
        resp = client.post("/api/auth/signup", json={
            "email": email,
            "password": pw,
            "name": "Test User",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["user"]["email"] == email

        # Login
        resp = client.post("/api/auth/login", json={
            "email": email,
            "password": pw,
        })
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_static_frontend_or_no_static(self, client):
        """/ should serve frontend if static dir exists, or 404 otherwise."""
        resp = client.get("/")
        # 200 if static dir exists, 404 if not (local dev without build)
        assert resp.status_code in (200, 307, 404)
