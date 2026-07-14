from scraper import MyCareersFutureScraper


def test_mcf_agency_office_is_not_used_as_job_location():
    item = {
        "postedCompany": {"ssicCode2020": "78104"},
        "address": {
            "building": "BOAT QUAY",
            "districts": [{"region": "Central"}],
        },
    }

    assert MyCareersFutureScraper._location(item) == "Singapore"


def test_mcf_direct_employer_uses_region_instead_of_building():
    item = {
        "postedCompany": {"ssicCode2020": "26112"},
        "address": {
            "building": "EXAMPLE BUSINESS PARK",
            "districts": [{"region": "East"}],
        },
    }

    assert MyCareersFutureScraper._location(item) == "East"


def test_mcf_location_falls_back_and_preserves_overseas_country():
    assert MyCareersFutureScraper._location({}) == "Singapore"
    assert MyCareersFutureScraper._location({
        "postedCompany": {"ssicCode": "78104"},
        "address": {"isOverseas": True, "overseasCountry": "Malaysia"},
    }) == "Malaysia"
