"""Deterministic visibility and level rules used by Recruitment Team search."""


def test_salary_does_not_override_an_explicit_junior_constraint():
    from job_visibility import is_junior_posting

    assert is_junior_posting("Non-executive", "IT Project Manager (Banking)", 10500) is True
    assert is_junior_posting("Fresh/entry level", "Full-Stack AI Engineer", 5200) is True


def test_experienced_title_evidence_only_overrides_the_ambiguous_executive_label():
    from job_visibility import is_junior_posting

    assert is_junior_posting("Executive", "Process Engineer", 6000) is True
    assert is_junior_posting("Executive", "Assistant Quality Manager", 4500) is False
    assert is_junior_posting("Junior Executive", "Product Manager", 8500) is True


def test_a_genuine_internship_is_still_excluded():
    from job_visibility import is_junior_posting

    assert is_junior_posting("Fresh/entry level", "ML Engineer Intern", 1100) is True
    assert is_junior_posting("Executive", "Automation Trainee", 2800) is True
