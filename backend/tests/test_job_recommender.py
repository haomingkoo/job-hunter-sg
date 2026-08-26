from __future__ import annotations

from dataclasses import replace


def _profile(statement: str):
    from recruitment_team.candidate_profile import CandidateEvidenceProfile, CandidateProfileField

    return CandidateEvidenceProfile(
        profile_version="candidate-evidence-profile-v3",
        resume_document_id="resume-document",
        resume_revision="resume-revision",
        fields=(
            CandidateProfileField(
                field_id="field-1",
                category="demonstrated_capability",
                statement=statement,
                resume_evidence_ids=("evidence-1",),
                evidence_quotes=(statement,),
                evidence_kind="direct",
                evidence_support_score=100,
                score_reason="Direct fixture evidence.",
            ),
        ),
        cited_resume_evidence=(),
    )


def _job(
    job_id: int,
    skill: str,
    similarity: float,
    relationship: str,
    relationship_evidence: str,
):
    from recruitment_team.discovery import JobSnapshot, JobSource

    return JobSnapshot(
        job_id=job_id,
        title=f"{skill} role",
        company=f"Employer {job_id}",
        location="Singapore",
        salary="",
        employment_type="Full Time",
        seniority="Manager",
        description=f"Own {skill}.",
        skills=(skill,),
        similarity_score=similarity,
        source=JobSource(
            source="fixture",
            url=f"https://example.test/{job_id}",
            source_posting_id=str(job_id),
            posted_date="2026-08-01",
            closing_date="",
            scraped_at="2026-08-01T00:00:00Z",
            availability="current",
            snapshot_sha256="a" * 64,
        ),
        employer_relationship=relationship,
        employer_relationship_evidence=relationship_evidence,
    )


def _result(*jobs):
    from recruitment_team.discovery import JobSearchResult

    return JobSearchResult(
        query="manufacturing leadership",
        jobs=tuple(jobs),
        candidate_count=len(jobs),
        visible_candidate_count=len(jobs),
        truncated=False,
        valid_empty=not jobs,
    )


def test_profile_evidence_reranks_the_discovery_candidates_without_a_company_boost():
    from recruitment_team.job_recommender import JobRecommender

    semantic_first = _job(1, "software development", 0.99, "unknown", "unverified")
    profile_match = _job(2, "quality management", 0.40, "unknown", "unverified")

    batch = JobRecommender().recommend(
        _profile("Led quality management across semiconductor manufacturing sites."),
        _result(semantic_first, profile_match),
    )

    assert [job.job_id for job in batch.search_result.jobs] == [2, 1]
    assert batch.receipt.candidate_profile_used is True
    assert batch.receipt.candidate_generation_scope == "query_search_only"
    assert batch.receipt.candidate_queries == ("manufacturing leadership",)
    by_id = {item.job_id: item for item in batch.receipt.jobs}
    assert by_id[2].matched_profile_terms == ("quality management",)
    assert by_id[2].profile_term_match_count == 1
    assert by_id[2].profile_term_coverage == 1.0
    assert by_id[1].profile_term_coverage == 0.0


def test_relationship_grade_is_visible_and_breaks_equal_profile_coverage_without_relabeling_unknown():
    from recruitment_team.job_recommender import JobRecommender

    intermediary = _job(3, "quality management", 0.99, "intermediary", "ea_licence")
    unknown = _job(2, "quality management", 0.95, "unknown", "mcf_no_relationship_signal")
    direct = _job(1, "quality management", 0.80, "direct", "official_company_source")

    batch = JobRecommender().recommend(
        _profile("Led quality management."),
        _result(intermediary, unknown, direct),
    )

    assert [job.job_id for job in batch.search_result.jobs] == [1, 2, 3]
    receipts = {item.job_id: item for item in batch.receipt.jobs}
    assert receipts[1].employer_relationship == "direct"
    assert receipts[2].employer_relationship == "unknown"
    assert receipts[2].employer_relationship_evidence == "mcf_no_relationship_signal"
    assert receipts[3].employer_relationship == "intermediary"
    assert batch.receipt.component_order == (
        "profile_term_match_count",
        "profile_term_coverage",
        "employer_relationship_when_requested",
        "semantic_similarity",
        "source_order",
    )


def test_relationship_preference_does_not_override_fit_or_apply_when_not_requested():
    from recruitment_team.job_recommender import JobRecommender

    direct = _job(1, "quality management", 0.80, "direct", "official_company_source")
    unknown = _job(2, "quality management", 0.95, "unknown", "mcf_no_relationship_signal")
    profile = _profile("Led quality management.")

    preferred = JobRecommender().recommend(profile, _result(direct, unknown))
    not_preferred = JobRecommender().recommend(
        profile,
        replace(_result(direct, unknown), direct_employers_only=False),
    )

    assert [job.job_id for job in preferred.search_result.jobs] == [1, 2]
    assert [job.job_id for job in not_preferred.search_result.jobs] == [2, 1]


def test_relationship_preference_only_breaks_ties_after_profile_coverage():
    from recruitment_team.job_recommender import JobRecommender

    direct = replace(
        _job(1, "quality management", 0.99, "direct", "official_company_source"),
        skills=("quality management", "software development"),
        description="Own quality management and software development.",
    )
    unknown = _job(2, "quality management", 0.80, "unknown", "mcf_no_relationship_signal")

    batch = JobRecommender().recommend(
        _profile("Led quality management."),
        _result(direct, unknown),
    )

    assert [job.job_id for job in batch.search_result.jobs] == [2, 1]
    receipts = {item.job_id: item for item in batch.receipt.jobs}
    assert receipts[2].profile_term_match_count == receipts[1].profile_term_match_count == 1
    assert receipts[2].profile_term_coverage > receipts[1].profile_term_coverage


def test_no_profile_is_reported_truthfully_and_does_not_fabricate_profile_matches():
    from recruitment_team.job_recommender import JobRecommender

    unknown = _job(1, "quality management", 0.99, "unknown", "unverified")
    direct = _job(2, "software development", 0.10, "direct", "official_company_source")

    batch = JobRecommender().recommend(None, _result(unknown, direct))

    assert [job.job_id for job in batch.search_result.jobs] == [1, 2]
    assert batch.receipt.candidate_profile_used is False
    assert batch.receipt.employer_preference_applied is False
    assert batch.receipt.candidate_profile_version == ""
    assert all(item.matched_profile_terms == () for item in batch.receipt.jobs)
    assert all(item.profile_term_coverage == 0.0 for item in batch.receipt.jobs)


def test_profile_candidate_generation_can_recover_a_relevant_prior_industry_employer():
    from recruitment_team.discovery import ScriptedDiscovery
    from recruitment_team.job_recommender import JobRecommender

    generic = _job(1, "general management", 0.90, "unknown", "mcf_no_relationship_signal")
    micron = _job(2, "quality management", 0.75, "unknown", "mcf_no_relationship_signal")
    discovery = ScriptedDiscovery([
        _result(generic),
        _result(micron),
    ])

    batch = JobRecommender().search(
        _profile("Led semiconductor manufacturing and quality management across sites."),
        discovery,
        "manager roles",
    )

    assert discovery.search_count == 2
    assert [job.job_id for job in batch.search_result.jobs] == [2, 1]
    assert batch.receipt.candidate_generation_scope == "query_and_profile_search_union"
    assert batch.receipt.candidate_queries[0] == "manager roles"
    assert "semiconductor manufacturing" in batch.receipt.candidate_queries[1].casefold()
    assert "quality management" in batch.receipt.candidate_queries[1].casefold()


def test_profile_candidate_query_keeps_late_domain_and_skill_evidence_without_section_order_truncation():
    from recruitment_team.candidate_profile import CandidateEvidenceProfile, CandidateProfileField
    from recruitment_team.discovery import ScriptedDiscovery
    from recruitment_team.job_recommender import JobRecommender

    fields = tuple(
        CandidateProfileField(
            field_id=f"capability-{index}",
            category="demonstrated_capability",
            statement=f"Delivered custom internal capability number {index}.",
            resume_evidence_ids=(f"evidence-{index}",),
            evidence_quotes=(f"Delivered custom internal capability number {index}.",),
            evidence_kind="direct",
            evidence_support_score=100,
            score_reason="Direct fixture evidence.",
        )
        for index in range(40)
    ) + (
        CandidateProfileField(
            field_id="domain-semiconductor",
            category="domain",
            statement="Semiconductor manufacturing",
            resume_evidence_ids=("evidence-domain",),
            evidence_quotes=("Semiconductor manufacturing",),
            evidence_kind="direct",
            evidence_support_score=100,
            score_reason="Direct fixture evidence.",
        ),
        CandidateProfileField(
            field_id="skill-fmea",
            category="stated_skill",
            statement="FMEA",
            resume_evidence_ids=("evidence-skill",),
            evidence_quotes=("FMEA",),
            evidence_kind="direct",
            evidence_support_score=100,
            score_reason="Direct fixture evidence.",
        ),
    )
    profile = CandidateEvidenceProfile(
        profile_version="candidate-evidence-profile-v3",
        resume_document_id="resume-document",
        resume_revision="resume-revision",
        fields=fields,
        cited_resume_evidence=(),
    )
    discovery = ScriptedDiscovery([_result(), _result()])

    batch = JobRecommender().search(profile, discovery, "manager roles")
    profile_query = batch.receipt.candidate_queries[1]

    assert "Semiconductor manufacturing" in profile_query
    assert "FMEA" in profile_query
    assert "custom internal capability" not in profile_query
