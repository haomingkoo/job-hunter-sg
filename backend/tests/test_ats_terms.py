from ats_terms import job_term_labels


def test_job_term_labels_share_acronym_casing_and_deduplication():
    terms = [
        {"skill": "rpa and gis"},
        {"skill": "RPA AND GIS"},
        {"skill": "Power BI"},
    ]

    assert job_term_labels(terms) == ["RPA and GIS", "Power BI"]
