import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from job_alerts import create_unsubscribe_token, score_job_for_alert, verify_unsubscribe_token


def test_alert_score_uses_resume_skills_and_job_terms():
    job = SimpleNamespace(
        id=1,
        title="Cloud Platform Engineer",
        company="Direct Employer Pte Ltd",
        description="Build AWS, Terraform, and Kubernetes automation.",
        skills=["AWS", "Terraform", "Kubernetes"],
        job_terms_preview=["AWS", "Terraform", "Kubernetes"],
    )

    result = score_job_for_alert(
        "Cloud engineer with AWS, Terraform, Kubernetes, and Python delivery experience.",
        ["AWS", "Terraform", "Kubernetes", "Python"],
        job,
    )

    assert result is not None
    assert result.score >= 75
    assert result.matched_skills[:3] == ["AWS", "Terraform", "Kubernetes"]


def test_alert_score_returns_none_without_resume_overlap():
    job = SimpleNamespace(
        id=2,
        title="Finance Manager",
        company="Direct Employer Pte Ltd",
        description="Financial planning and statutory reporting.",
        skills=["Financial Planning", "Statutory Reporting"],
        job_terms_preview=["Financial Planning", "Statutory Reporting"],
    )

    result = score_job_for_alert(
        "Cloud engineer with AWS and Kubernetes delivery experience.",
        ["AWS", "Kubernetes"],
        job,
    )

    assert result is None


def test_unsubscribe_token_round_trip(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    user = SimpleNamespace(id=42, api_key="account-nonce-a")

    class Query:
        def __init__(self, current_user):
            self.current_user = current_user

        def filter(self, _condition):
            return self

        def populate_existing(self):
            return self

        def first(self):
            return self.current_user

    class DB:
        def __init__(self, current_user):
            self.current_user = current_user

        def query(self, _model):
            return Query(self.current_user)

    token = create_unsubscribe_token(user)

    assert verify_unsubscribe_token(token, DB(user)) == 42
    assert verify_unsubscribe_token(token + "bad", DB(user)) is None
    assert verify_unsubscribe_token(f"{'9' * 100}.bad", DB(user)) is None
    replacement = SimpleNamespace(id=42, api_key="account-nonce-b")
    assert verify_unsubscribe_token(token, DB(replacement)) is None
