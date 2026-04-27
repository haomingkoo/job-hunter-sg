import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from legal_pages import render_privacy_html, render_terms_html


def test_terms_include_hobby_and_liability_disclaimers():
    html = render_terms_html("use the contact form")

    assert "hobby project" in html
    assert "No Guarantees" in html
    assert "Limitation of Liability" in html
    assert "Job match alerts are optional" in html


def test_privacy_notice_includes_alert_consent_and_controls():
    html = render_privacy_html("use the contact form")

    assert "Job match alerts are disabled by default" in html
    assert "unsubscribe" in html
    assert "AI and Third-Party Processing" in html
    assert "Your Controls" in html
