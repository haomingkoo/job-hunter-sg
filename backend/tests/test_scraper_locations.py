from scraper import AdzunaScraper, CareersGovScraper, JoobleScraper, MyCareersFutureScraper


def test_mcf_agency_office_without_scope_evidence_stays_unknown():
    item = {
        "postedCompany": {"ssicCode2020": "78104"},
        "address": {
            "building": "BOAT QUAY",
            "districts": [{"region": "Central"}],
        },
    }

    assert MyCareersFutureScraper._work_location(item) == ("", "unknown")


def test_mcf_direct_employer_uses_region_instead_of_building():
    item = {
        "postedCompany": {"ssicCode2020": "26112"},
        "address": {
            "building": "EXAMPLE BUSINESS PARK",
            "isOverseas": False,
            "districts": [{"region": "East"}],
        },
    }

    assert MyCareersFutureScraper._location(item) == "East"


def test_mcf_location_fails_closed_and_preserves_overseas_country():
    assert MyCareersFutureScraper._work_location({}) == ("", "unknown")
    assert MyCareersFutureScraper._work_location(
        {
            "postedCompany": {"ssicCode": "78104"},
            "address": {"isOverseas": True, "overseasCountry": "Malaysia"},
        }
    ) == ("Malaysia", "overseas")


def test_mcf_preserves_posted_company_ssic_evidence():
    assert MyCareersFutureScraper._company_identity(
        {
            "postedCompany": {
                "name": "Example Staffing",
                "ssicCode2020": "78104",
                "ssicDescription2020": "Employment agencies",
            },
        }
    ) == ("Example Staffing", "78104", "Employment agencies")


def test_source_adapters_do_not_invent_singapore_for_missing_location():
    assert CareersGovScraper._location({}) == ""
    assert AdzunaScraper._location({}) == ""
    assert AdzunaScraper._location({"location": {}}) == ""
    assert JoobleScraper._location({}) == ""
    assert CareersGovScraper._work_location({}) == ("", "unknown")
    assert AdzunaScraper._work_location({}) == ("", "unknown")
    assert JoobleScraper._work_location({}) == ("", "unknown")


def test_source_adapters_preserve_explicit_singapore_location():
    assert CareersGovScraper._location({"location": "Singapore"}) == "Singapore"
    assert (
        AdzunaScraper._location(
            {
                "location": {"display_name": "Singapore"},
            }
        )
        == "Singapore"
    )
    assert JoobleScraper._location({"location": "Singapore"}) == "Singapore"
    assert CareersGovScraper._work_location(
        {
            "location": "Singapore",
        }
    ) == ("Singapore", "singapore")


def test_sanitizer_labels_text_scope_override_provenance():
    from sanitizer import sanitize_job

    sanitized = sanitize_job(
        {
            "title": "Data Analyst",
            "location": "Singapore",
            "description": "Location: Shanghai, China",
            "work_location_scope": "singapore",
            "work_location_scope_source": "mcf_address_is_overseas",
        }
    )

    assert sanitized["work_location_scope"] == "overseas"
    assert sanitized["work_location_scope_source"] == "text_override_v1"
