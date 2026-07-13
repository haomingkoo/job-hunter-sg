from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import job_alerts
from database import Base
from job_alerts import AlertMatch, find_alert_matches
from models import ScrapedJob


def test_find_alert_matches_ranks_all_bounded_candidates_before_limiting(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)

    with Session(engine) as db:
        high_match = ScrapedJob(
            title="High match",
            company="Direct Employer",
            dedup_key="high-match",
            scraped_at=now.isoformat(),
        )
        low_match = ScrapedJob(
            title="Low match",
            company="Another Direct Employer",
            dedup_key="low-match",
            scraped_at=now.isoformat(),
        )
        db.add_all([high_match, low_match])
        db.commit()

        scores = {high_match.id: 99, low_match.id: 75}
        monkeypatch.setattr(job_alerts, "extract_resume_alert_skills", lambda _resume: [])
        monkeypatch.setattr(
            job_alerts,
            "score_job_for_alert",
            lambda _resume, _skills, job: AlertMatch(
                job=job,
                score=scores[job.id],
                matched_skills=[],
                missing_skills=[],
                why="Regression fixture",
            ),
        )
        preference = SimpleNamespace(
            user_id=1,
            last_run_at=now - timedelta(hours=1),
            keywords="",
            direct_employers_only=False,
            min_score=75,
            max_jobs=1,
        )

        matches = find_alert_matches(db, preference, "resume", now=now)

    assert [(match.job.title, match.score) for match in matches] == [("High match", 99)]
