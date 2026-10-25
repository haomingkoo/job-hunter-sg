import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from legal_pages import render_privacy_html, render_terms_html

CONTACT = "privacy@kooexperience.com"


def test_terms_include_liability_disclaimers():
    html = render_terms_html(CONTACT)

    assert "No Guarantees" in html
    assert "Limitation of Liability" in html
    assert "Job match alerts are optional" in html


def test_terms_include_minimum_age_and_upload_licence():
    html = render_terms_html(CONTACT)

    assert "at least 13 years old" in html
    assert "limited, non-exclusive, royalty-free licence" in html
    assert "Koo Haoming (individual, Singapore)" in html


def test_privacy_notice_includes_alert_consent_and_controls():
    html = render_privacy_html(CONTACT)

    assert "Job match alerts are disabled by default" in html
    assert "unsubscribe" in html
    assert "AI and Third-Party Processing" in html
    assert "Your Rights and Controls" in html


def test_privacy_notice_names_dpo_contact_and_processors():
    html = render_privacy_html(CONTACT)

    assert f'href="mailto:{CONTACT}"' in html
    assert "Data Protection Officer" in html
    for processor in ("SEA-LION", "Railway", "Resend", "Google", "Cloudflare Web Analytics"):
        assert processor in html


def test_privacy_notice_states_retention_and_rights():
    html = render_privacy_html(CONTACT)

    assert "12 months" in html
    assert "Export my data" in html
    assert "backups" in html
    assert "Using the Service Without an Account" in html


def test_privacy_notice_lists_llm_tracing_only_when_enabled():
    assert "LangSmith (LangChain, Inc.)" not in render_privacy_html(CONTACT)
    assert "LangSmith (LangChain, Inc.)" in render_privacy_html(CONTACT, llm_tracing_enabled=True)


def test_legal_pages_have_site_header_and_footer():
    for page in (render_terms_html(CONTACT), render_privacy_html(CONTACT)):
        assert '<header class="site-header">' in page
        assert '<a href="/#jobs">Search jobs</a>' in page
        assert '<footer class="site-footer">' in page
        assert 'href="/api/privacy"' in page and 'href="/api/terms"' in page
        assert f'href="mailto:{CONTACT}"' in page
