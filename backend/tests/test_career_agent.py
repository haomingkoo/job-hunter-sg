import json

from career_agent import build_application_pack


def test_application_pack_flags_unverified_rewrite_numbers(monkeypatch):
    def fake_call(*args, **kwargs):
        return json.dumps({
            "verdict": {
                "decision": "maybe",
                "fit_score": 68,
                "rationale": "Relevant experience, but proof is thin.",
                "strengths": ["React experience"],
                "risks": ["No cloud evidence"],
            },
            "ats": {
                "matched_terms": ["react"],
                "missing_terms": ["aws"],
                "critical_gaps": ["AWS"],
            },
            "evidence_questions": [],
            "resume": {
                "summary": "Software engineer with React experience.",
                "bullet_upgrades": [
                    {
                        "original": "Built web applications using React.",
                        "rewrite": "Built React applications that improved release speed by 40%.",
                        "reason": "Adds impact.",
                        "needs_user_fact": False,
                    }
                ],
            },
            "application_assets": {
                "cover_letter": "Dear Hiring Team, I am interested in the role.",
                "recruiter_dm": "Hi, I am interested in this role.",
                "follow_up_email": "Hi, following up on my application.",
            },
            "interview": {
                "likely_questions": ["Tell me about your React experience."],
                "star_answers": [],
                "interviewer_questions": ["How is the frontend team structured?"],
            },
            "guardrails": [],
        })

    monkeypatch.setattr("career_agent.call_sealion_json", fake_call)

    pack = build_application_pack(
        resume_text="Built web applications using React.",
        job_title="Frontend Engineer",
        job_company="Acme",
        job_description="React role requiring AWS.",
        job_terms=[{"skill": "react"}, {"skill": "aws"}],
        match_result={
            "matched": [{"skill": "react"}],
            "missing": [{"skill": "aws"}],
        },
    )

    upgrade = pack["resume"]["bullet_upgrades"][0]
    assert pack["degraded"] is False
    assert upgrade["needs_user_fact"] is True
    assert upgrade["unverified_numbers"] == ["40%"]


def test_application_pack_returns_local_fallback_when_model_unavailable(monkeypatch):
    monkeypatch.setattr("career_agent.call_sealion_json", lambda *args, **kwargs: None)

    pack = build_application_pack(
        resume_text="Built web applications using React.\nLed code reviews for junior engineers.",
        job_title="Frontend Engineer",
        job_company="Acme",
        job_description="React role requiring AWS.",
        job_terms=[{"skill": "react"}, {"skill": "aws"}],
        match_result={
            "matched": [{"skill": "react"}],
            "missing": [{"skill": "aws"}],
        },
    )

    assert pack["degraded"] is True
    assert pack["ats"]["matched_terms"] == ["react"]
    assert pack["ats"]["missing_terms"] == ["aws"]
    assert len(pack["evidence_questions"]) >= 1
