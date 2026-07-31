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
