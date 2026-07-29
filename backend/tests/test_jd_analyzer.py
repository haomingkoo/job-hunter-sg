

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
