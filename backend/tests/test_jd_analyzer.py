

from datetime import datetime, timezone


def test_promotional_signal_catches_the_mlm_title_shape():
    """Emoji and hashtags in a title are the tell; a real employer does not use them."""
    from jd_analyzer import detect_promotional_spam

    spam = detect_promotional_spam("URGENT 🍀 Junior Growth Associate (Training provided)")
    assert spam["is_promotional"] is True
    assert "emoji_in_title" in spam["signals"]

    hashtagged = detect_promotional_spam("📣 Events Executive #Trainingprovided #Highcommission")
    assert hashtagged["is_promotional"] is True
    assert "hashtags_in_title" in hashtagged["signals"]


def test_promotional_signal_leaves_ordinary_titles_alone():
    """An en-dash is not an emoji; a plain title must never be flagged."""
    from jd_analyzer import detect_promotional_spam

    for title in (
        "Senior Platform Engineer",
        "Project Manager (Electrical – Data Centre Construction)",
        "Software Engineer, Backend",
        "Head of Regional Engineering – Data Centres",
    ):
        assert detect_promotional_spam(title)["score"] == 0, title


def test_a_single_weak_phrase_is_not_enough_to_flag():
    """Real postings say "training provided"; one tell must not condemn a job."""
    from jd_analyzer import detect_promotional_spam

    result = detect_promotional_spam(
        "Apprentice Electrician", "Training provided for the right candidate."
    )
    assert result["is_promotional"] is False


def test_analysis_carries_the_promotional_verdict():
    from jd_analyzer import analyze_job_description

    analysis = analyze_job_description(
        title="🎯 Brand & Buzz Executive (Training provided + Entry level)",
        description="Join our vibrant team. No experience required, high commission.",
        parsed_jd={},
    )
    assert analysis["is_promotional"] is True
    assert analysis["promotional"]["score"] >= 40


def test_company_rollup_needs_a_ratio_not_a_count():
    """A big agency has more flagged postings than a small outfit has postings."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from database import Base
    from job_precompute import rollup_company_promotional_scores
    from models import ScrapedJob

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    now = datetime.now(timezone.utc).isoformat()

    def add(company, score, n, offset, **extra):
        for i in range(n):
            db.add(ScrapedJob(
                title=f"{company} {i}", company=company, source="s",
                dedup_key=f"{company}-{offset}-{i}", promotional_score=score,
                posted_at_sort=now, **extra,
            ))

    # A real agency: many postings, a few bad titles. Must NOT be tainted.
    add("BIG AGENCY", 55, 12, 0)
    add("BIG AGENCY", 0, 200, 1)
    # An outfit: most postings promotional, plus quiet ones hiding among them.
    add("TINY ORG", 55, 8, 2)
    add("TINY ORG", 0, 2, 3)
    add("TINY ORG", 0, 1, 4, hidden=1, company_promotional_score=77)
    db.commit()

    result = rollup_company_promotional_scores(db)

    assert "TINY ORG" in result["scores"]
    assert result["scores"]["TINY ORG"] == 80
    assert "BIG AGENCY" not in result["scores"], "a 6%-flagged agency was tainted"

    quiet = db.query(ScrapedJob).filter(
        ScrapedJob.company == "TINY ORG", ScrapedJob.promotional_score == 0
    ).all()
    assert all(job.company_promotional_score >= 40 for job in quiet)

    untouched = db.query(ScrapedJob).filter(ScrapedJob.company == "BIG AGENCY").first()
    assert untouched.company_promotional_score == 0
    retired = db.query(ScrapedJob).filter(ScrapedJob.hidden == 1).one()
    assert retired.company_promotional_score == 77


def test_a_qualifying_company_always_scores_high_enough_to_demote():
    """The stored value doubles as the demotion signal, so it must clear the bar."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import config
    from database import Base
    from jd_analyzer import PROMOTIONAL_THRESHOLD
    from job_precompute import rollup_company_promotional_scores
    from models import ScrapedJob

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    now = datetime.now(timezone.utc).isoformat()
    for i in range(10):
        db.add(ScrapedJob(
            title=f"t{i}", company="EDGE ORG", source="s", dedup_key=f"e{i}",
            promotional_score=55 if i < 4 else 0, posted_at_sort=now,
        ))
    db.commit()

    original = config.COMPANY_PROMOTIONAL_RATIO
    config.COMPANY_PROMOTIONAL_RATIO = 0.3  # 40% flagged qualifies, raw pct is 40
    try:
        result = rollup_company_promotional_scores(db)
        assert result["scores"]["EDGE ORG"] >= PROMOTIONAL_THRESHOLD
    finally:
        config.COMPANY_PROMOTIONAL_RATIO = original
