"""Autopilot search derives its query from a resume, not from contact details."""

from types import SimpleNamespace

from recruitment_team.recruitment_team import RecruitmentTeam



LINKEDIN_EXPORT = """Contact Hui Shan Ang
candidate@example.com
Chartered Accountant & AI Engineer | Process Transformation
www.linkedin.com/in/someone Intelligent Automation | Python
(LinkedIn)
Singapore
Top Skills
Summary
I'm a chartered accountant who fell in love with building AI. For
Robotic Process Automation (RPA)
Experience
Associate AI Engineer
"""


def test_query_from_resume_omits_contact_details():
    resume = SimpleNamespace(resume_text=LINKEDIN_EXPORT, label="CV")

    query = RecruitmentTeam._query_from_resume(resume)

    assert "@" not in query
    assert "linkedin.com" not in query
    assert "Hui Shan Ang" not in query


def test_query_from_resume_prefers_titles_over_prose():
    resume = SimpleNamespace(resume_text=LINKEDIN_EXPORT, label="CV")

    query = RecruitmentTeam._query_from_resume(resume)

    assert "Associate AI Engineer" in query
    assert "fell in love" not in query


def test_query_from_resume_uses_prose_when_a_resume_has_no_title_lines():
    resume = SimpleNamespace(
        resume_text="Built a production agent platform with traced model calls.",
        label="Data roles",
    )

    assert "agent platform" in RecruitmentTeam._query_from_resume(resume)


def test_query_from_resume_falls_back_to_label_when_the_resume_is_empty():
    resume = SimpleNamespace(resume_text="", label="Data roles")

    assert RecruitmentTeam._query_from_resume(resume) == "Data roles"


def _thread(case_facts):
    return SimpleNamespace(id="t1", case_facts=case_facts)


def test_model_composed_query_wins_over_preference_fields():
    """The model read the thread; a field whitelist did not."""
    thread = _thread({
        "search_query": "AI engineer financial services tax automation",
        "preferences": [{"field": "role", "value": "something vaguer"}],
    })

    query = RecruitmentTeam._query_from_candidate(
        RecruitmentTeam.__new__(RecruitmentTeam), thread, SimpleNamespace(resume_text="", label="CV")
    )

    assert query == "AI engineer financial services tax automation"


def test_exclusions_never_reach_the_query_when_the_model_offers_none():
    thread = _thread({"preferences": [
        {"field": "role", "value": "AI engineer"},
        {"field": "constraints", "value": "not computer vision"},
    ]})

    query = RecruitmentTeam._query_from_candidate(
        RecruitmentTeam.__new__(RecruitmentTeam), thread, SimpleNamespace(resume_text="", label="CV")
    )

    assert "computer vision" not in query
    assert query == "AI engineer"


def test_a_long_career_excludes_junior_postings_without_being_asked():
    """Nobody with a decade behind them should have to rule out internships."""
    thread = _thread({})
    resume = SimpleNamespace(resume_text="Tax Senior 2011 - 2016. Manager 2019 - 2023.")

    assert RecruitmentTeam._wants_experienced_roles(thread, resume) is True


def test_a_short_career_still_sees_junior_postings():
    thread = _thread({})
    resume = SimpleNamespace(resume_text="Bachelor of Computing, 2025. Internship 2024.")

    assert RecruitmentTeam._wants_experienced_roles(thread, resume) is False


def test_a_stated_level_overrides_the_resume():
    """Stepping down deliberately is the candidate's call."""
    thread = _thread({"preferences": [{"field": "seniority", "value": "Junior Executive"}]})
    resume = SimpleNamespace(resume_text="Tax Senior 2011 - 2016.")

    assert RecruitmentTeam._wants_experienced_roles(thread, resume) is False
