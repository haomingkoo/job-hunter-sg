import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from main import (  # noqa: E402
    _analytics_agency_subset_options,
    _analytics_company_label,
    _analytics_job_matches_agency_subset,
    _analytics_skill_display,
    _analytics_skill_key,
    _build_label_movers,
    _split_multi_value_filter,
)
from employer_filter import is_recruitment_employer  # noqa: E402


def test_analytics_uses_agency_when_careersgov_company_is_generic():
    job = SimpleNamespace(
        company="Singapore Public Service",
        agency="MTI",
        title="Manager, Industry Development",
    )

    assert _analytics_company_label(job) == "Ministry of Trade and Industry"


def test_analytics_derives_careersgov_agency_from_title_prefix():
    job = SimpleNamespace(
        company="Singapore Public Service",
        agency="LTA BCO B6 L2",
        title="[LTA-RSE] Executive Engineer / Engineer, Communications",
    )

    assert _analytics_company_label(job) == "Land Transport Authority"


def test_analytics_keeps_real_company_when_available():
    job = SimpleNamespace(
        company="Example Pte Ltd",
        agency="Example Department",
        title="Software Engineer",
    )

    assert _analytics_company_label(job) == "Example Pte Ltd"


def test_analytics_filters_non_skill_org_terms_and_formats_ai():
    assert _analytics_skill_key("Ministry Of Home Affairs") == ""
    assert _analytics_skill_key("Learning & Putting Skills") == ""
    assert _analytics_skill_key("AI") == "ai"
    assert _analytics_skill_display("ai") == "AI"


def test_label_movers_surfaces_recently_rising_and_cooling_orgs():
    recent = {
        "agency a": {"display": "Agency A", "count": 40},
        "agency b": {"display": "Agency B", "count": 5},
    }
    older = {
        "agency a": {"display": "Agency A", "count": 10},
        "agency b": {"display": "Agency B", "count": 40},
    }

    movers = _build_label_movers(recent, 100, older, 100, "company")

    assert movers["rising"][0]["company"] == "Agency A"
    assert movers["cooling"][0]["company"] == "Agency B"


def test_split_multi_value_filter_trims_dedupes_and_preserves_order():
    assert _split_multi_value_filter("Full-time, Full Time, full-time, Contract") == [
        "Full-time",
        "Full Time",
        "Contract",
    ]


def test_direct_employer_filter_classifies_common_recruiters():
    assert is_recruitment_employer("RECRUIT EXPRESS PTE LTD")
    assert is_recruitment_employer("Example Pte Ltd", "Employment Agencies")
    assert not is_recruitment_employer("Land Transport Authority")


def test_agency_subset_options_include_public_sector_groups():
    options = {item["id"]: item["label"] for item in _analytics_agency_subset_options()}

    assert options["public_sector"] == "Public sector"
    assert options["ministries"] == "Ministries"
    assert options["digital_gov"] == "Digital Gov"


def test_agency_subset_matching_uses_agency_codes_and_labels():
    lta_job = SimpleNamespace(
        source="Careers@Gov",
        company="Singapore Public Service",
        agency="LTA BCO B6 L2",
        title="[LTA-RSE] Executive Engineer / Engineer, Communications",
    )
    govtech_job = SimpleNamespace(
        source="Careers@Gov",
        company="Singapore Public Service",
        agency="GOVTECH",
        title="Software Engineer",
    )
    private_job = SimpleNamespace(
        source="MyCareersFuture",
        company="Example Pte Ltd",
        agency="",
        title="Software Engineer",
    )

    assert _analytics_job_matches_agency_subset(lta_job, "public_sector")
    assert _analytics_job_matches_agency_subset(lta_job, "transport")
    assert _analytics_job_matches_agency_subset(govtech_job, "digital_gov")
    assert not _analytics_job_matches_agency_subset(private_job, "public_sector")
