"""Compact, source-backed evidence views for assessment models."""

from __future__ import annotations

from dataclasses import asdict

from ..assessment_contracts import TargetAssessmentRequest
from ..fair_hiring import without_protected_status_sentences


def candidate_evidence_view(request: TargetAssessmentRequest) -> dict:
    """Return citations and claims once, without profile-generation metadata."""
    return {
        "fields": [
            {
                "field_id": field.field_id,
                "category": field.category,
                "statement": field.statement,
                "resume_evidence_ids": list(field.resume_evidence_ids),
                "evidence_quotes": list(field.evidence_quotes),
                "evidence_kind": field.evidence_kind,
                "evidence_support_score": field.evidence_support_score,
            }
            for field in request.candidate_profile.fields
        ],
        "candidate_confirmed": [
            {
                "evidence_id": fact.evidence_id,
                "evidence_quote": fact.evidence_quote,
            }
            for fact in request.confirmed_evidence
        ],
    }


def target_role_view(request: TargetAssessmentRequest) -> dict:
    """Return the raw posting facts and cited criteria without duplicate assessments."""
    job = request.target_job
    return {
        "target_job": {
            "job_id": job.job_id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "salary": job.salary,
            "employment_type": job.employment_type,
            "seniority": job.seniority,
            "description": without_protected_status_sentences(job.description),
            "skills": list(job.skills),
            "sector": job.sector,
            "parsed_requirements": job.parsed_jd or {},
            "ats_terms": list(job.job_terms_preview),
            "salary_context": job.salary_context,
            "fact_context_status": job.fact_context_status,
        },
        "role_success_profile": {
            "criteria": [asdict(criterion) for criterion in request.role_profile.criteria],
            "policy_constraints": [
                asdict(constraint) for constraint in request.role_profile.policy_constraints
            ],
        },
    }


def assessment_evidence_view(request: TargetAssessmentRequest) -> dict:
    """Return the common compact evidence packet used by review and correction."""
    return {
        **target_role_view(request),
        "candidate_profile": candidate_evidence_view(request),
    }
