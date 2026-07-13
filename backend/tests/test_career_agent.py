import json

from career_agent import _extract_resume_bullets, build_application_pack


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


def test_application_pack_does_not_treat_job_numbers_as_candidate_evidence(monkeypatch):
    monkeypatch.setattr(
        "career_agent.call_sealion_json",
        lambda *args, **kwargs: json.dumps({
            "resume": {
                "bullet_upgrades": [{
                    "original": "Built React applications.",
                    "rewrite": "Built React applications used by 10,000 customers.",
                    "reason": "Matches the role.",
                    "needs_user_fact": False,
                }],
            },
        }),
    )

    pack = build_application_pack(
        resume_text="Built React applications.",
        job_title="Frontend Engineer",
        job_company="Acme",
        job_description="Build products used by 10,000 customers.",
        job_terms=[],
        match_result={},
    )

    upgrade = pack["resume"]["bullet_upgrades"][0]
    assert upgrade["needs_user_fact"] is True
    assert upgrade["unverified_numbers"] == ["10,000"]


def test_application_pack_flags_unsupported_scope_inflation(monkeypatch):
    monkeypatch.setattr(
        "career_agent.call_sealion_json",
        lambda *args, **kwargs: json.dumps({
            "resume": {
                "bullet_upgrades": [{
                    "original": "Built a multi-agent prototype with three apprentices.",
                    "rewrite": "Led three apprentices to deploy a production-grade multi-agent platform.",
                    "reason": "Uses stronger verbs.",
                    "needs_user_fact": False,
                }],
            },
        }),
    )

    pack = build_application_pack(
        resume_text="Built a multi-agent prototype with three apprentices.",
        job_title="AI Engineer",
        job_company="Acme",
        job_description="Lead production AI deployments.",
        job_terms=[],
        match_result={},
    )

    assert pack["resume"]["bullet_upgrades"][0]["needs_user_fact"] is True


def test_application_pack_flags_changed_metric_meaning(monkeypatch):
    monkeypatch.setattr(
        "career_agent.call_sealion_json",
        lambda *args, **kwargs: json.dumps({
            "resume": {
                "bullet_upgrades": [{
                    "original": "Built a platform targeting a ~90% reduction in investigation time.",
                    "rewrite": "Built a platform that reduced investigation time by up to 90%.",
                    "reason": "Adds impact.",
                    "needs_user_fact": False,
                }],
            },
        }),
    )

    pack = build_application_pack(
        resume_text="Built a platform targeting a ~90% reduction in investigation time.",
        job_title="AI Engineer",
        job_company="Acme",
        job_description="Reduce investigation time.",
        job_terms=[],
        match_result={},
    )

    assert pack["resume"]["bullet_upgrades"][0]["needs_user_fact"] is True


def test_application_pack_withholds_unsafe_generated_assets(monkeypatch):
    unsafe = "At AMD Singapore, I reduced investigation time by 90% and delivered USD 50M in savings."
    monkeypatch.setattr(
        "career_agent.call_sealion_json",
        lambda *args, **kwargs: json.dumps({
            "resume": {"summary": unsafe, "bullet_upgrades": []},
            "application_assets": {
                "cover_letter": unsafe,
                "recruiter_dm": unsafe,
                "follow_up_email": unsafe,
            },
            "interview": {
                "star_answers": [{
                    "question": "Tell me about the project.",
                    "answer": unsafe,
                    "source": "AI project",
                }],
            },
        }),
    )

    pack = build_application_pack(
        resume_text=(
            "PROFESSIONAL EXPERIENCE\n"
            "Associate AI Engineer | AI Singapore | Jan 2026 - Present\n"
            "Built an AMD Singapore-sponsored platform targeting a ~90% reduction.\n"
            "Identified USD 50M in opportunities."
        ),
        job_title="AI Engineer",
        job_company="Example Company",
        job_description="Build AI systems.",
        job_terms=[],
        match_result={},
    )

    assert pack["resume"]["summary"] == ""
    assert set(pack["application_assets"].values()) == {""}
    assert pack["interview"]["star_answers"] == []
    assert any("withheld" in warning.lower() for warning in pack["guardrails"])


def test_application_pack_rejects_sponsor_as_employer_without_numbers(monkeypatch):
    monkeypatch.setattr(
        "career_agent.call_sealion_json",
        lambda *args, **kwargs: json.dumps({
            "application_assets": {
                "cover_letter": "As an AI engineer at AMD Singapore, I built an AI platform.",
            },
        }),
    )

    for project in (
        "Built an industry project sponsored by AMD Singapore, delivered with a team.",
        "Built an AMD Singapore-sponsored platform, delivered with a team.",
    ):
        pack = build_application_pack(
            resume_text=(
                "PROFESSIONAL EXPERIENCE\n"
                "Associate AI Engineer | AI Singapore | Jan 2026 - Present\n"
                f"{project}"
            ),
            job_title="AI Engineer",
            job_company="Example Company",
            job_description="Build AI systems.",
            job_terms=[],
            match_result={},
        )

        assert pack["application_assets"]["cover_letter"] == ""


def test_application_pack_checks_claims_against_the_named_role(monkeypatch):
    monkeypatch.setattr(
        "career_agent.call_sealion_json",
        lambda *args, **kwargs: json.dumps({
            "resume": {
                "summary": "In my current AI Singapore role, I led a production AI team.",
            },
        }),
    )

    pack = build_application_pack(
        resume_text=(
            "PROFESSIONAL EXPERIENCE\n"
            "AI Engineer | AI Singapore | Jan 2026 - Present\n"
            "- Built an AI prototype.\n"
            "Engineering Manager | Micron Technology | Jan 2022 - Jan 2025\n"
            "- Led six engineers."
        ),
        job_title="AI Engineer",
        job_company="Example Company",
        job_description="Build AI systems.",
        job_terms=[],
        match_result={},
    )

    assert pack["resume"]["summary"] == ""


def test_application_pack_coerces_malformed_nested_lists(monkeypatch):
    monkeypatch.setattr(
        "career_agent.call_sealion_json",
        lambda *args, **kwargs: json.dumps({
            "evidence_questions": {"prompt": "not a list"},
            "resume": {"bullet_upgrades": "not a list"},
            "interview": {"star_answers": 42},
        }),
    )

    pack = build_application_pack(
        resume_text="Built web applications using React and Python for internal teams.",
        job_title="Frontend Engineer",
        job_company="Acme",
        job_description="Build web applications.",
        job_terms=[],
        match_result={},
    )

    assert pack["evidence_questions"] == []
    assert pack["resume"]["bullet_upgrades"] == []
    assert pack["interview"]["star_answers"] == []


def test_application_pack_uses_logical_wrapped_resume_bullets():
    bullets = _extract_resume_bullets(
        """PROFESSIONAL EXPERIENCE
AI Engineer
Example Labs | Jan 2024 - Present
• Built a multi-agent system with Python and SQL,
  serving operations teams across Singapore.
• Added deterministic validation gates."""
    )

    assert bullets == [
        "Built a multi-agent system with Python and SQL, serving operations teams across Singapore.",
        "Added deterministic validation gates.",
    ]


def test_application_pack_keeps_later_resume_evidence_in_model_context(monkeypatch):
    captured = {}

    def fake_call(*args, **kwargs):
        captured["messages"] = kwargs["messages"]
        return "{}"

    monkeypatch.setattr("career_agent.call_sealion_json", fake_call)
    resume_text = f"PROFESSIONAL SUMMARY\n{'context ' * 800}\nLATER_ROLE_EVIDENCE"

    build_application_pack(
        resume_text=resume_text,
        job_title="AI Engineer",
        job_company="Acme",
        job_description="Build AI systems.",
        job_terms=[],
        match_result={"matched": [], "missing": []},
    )

    assert "LATER_ROLE_EVIDENCE" in captured["messages"][1]["content"]


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
