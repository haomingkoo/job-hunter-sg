"""Deep role-success profile composed from definition and independent assessment."""

from __future__ import annotations

from dataclasses import replace

from .candidate_profile import CandidateEvidenceProfile
from .discovery import JobSnapshot
from .role_evidence_assessor import (
    RoleEvidenceAssessmentRequest,
    RoleEvidenceAssessor,
)
from .role_success import (
    CandidateEvidenceMatch,
    ResumeEvidenceRecord,
    RoleProfileRun,
    RoleDefinitionGenerator,
)


class EvidenceAssessedRoleSuccessProfiler:
    """Keep generation details private behind one source-backed profile interface."""

    def __init__(
        self,
        definition_generator: RoleDefinitionGenerator,
        evidence_assessor: RoleEvidenceAssessor,
    ):
        self._definition_generator = definition_generator
        self._evidence_assessor = evidence_assessor

    def profile(
        self,
        candidate_profile: CandidateEvidenceProfile,
        target: JobSnapshot,
        comparable_jobs: tuple[JobSnapshot, ...],
    ) -> RoleProfileRun:
        generated = self._definition_generator.define(
            target,
            comparable_jobs,
        )
        resume_blocks = tuple(
            ResumeEvidenceRecord(
                evidence_id=block.evidence_id,
                kind=block.kind,
                text=block.text,
                source_locator=block.source_locator,
                section_key=block.section_key,
            )
            for block in candidate_profile.cited_resume_evidence
        )
        assessed = self._evidence_assessor.assess(
            RoleEvidenceAssessmentRequest(
                criteria=generated.profile.criteria,
                resume_blocks=resume_blocks,
                role_sources=generated.profile.sources,
                candidate_profile_fields=candidate_profile.fields,
                proposed_evidence=generated.profile.candidate_evidence,
            )
        )
        judgments = {judgment.criterion_id: judgment for judgment in assessed.judgments}
        candidate_evidence = tuple(
            self._candidate_match(judgments[criterion.criterion_id]) for criterion in generated.profile.criteria
        )
        cited_ids = {evidence_id for match in candidate_evidence for evidence_id in match.resume_evidence_ids}
        needs_clarification = any(
            criterion.requirement_level == "required" and judgments[criterion.criterion_id].alignment == "unknown"
            for criterion in generated.profile.criteria
        )
        profile = replace(
            generated.profile,
            candidate_evidence=candidate_evidence,
            cited_resume_evidence=tuple(block for block in resume_blocks if block.evidence_id in cited_ids),
            assessment_disposition=("needs_clarification" if needs_clarification else "pass"),
            evidence_assessment_prompt_version=assessed.prompt_version,
            evidence_assessment_model=assessed.model_name,
            evidence_assessment_attempt_count=assessed.attempt_count,
        )
        return RoleProfileRun(
            profile=profile,
            model_name=assessed.model_name,
            attempt_count=generated.attempt_count + assessed.attempt_count,
            input_tokens=(generated.input_tokens or 0) + (assessed.input_tokens or 0) or None,
            output_tokens=(generated.output_tokens or 0) + (assessed.output_tokens or 0) or None,
            validation_codes=tuple(
                (
                    *(f"generator:{code}" for code in generated.validation_codes),
                    *(f"assessor:{code}" for code in assessed.validation_codes),
                )
            ),
            generator_attempt_count=(generated.generator_attempt_count or generated.attempt_count),
            assessor_attempt_count=assessed.attempt_count,
            generator_model_name=(generated.generator_model_name or generated.model_name),
            assessor_model_name=assessed.model_name,
        )

    @staticmethod
    def _candidate_match(judgment) -> CandidateEvidenceMatch:
        gap = judgment.remaining_gap.strip()
        explanation = judgment.supported_strength.strip()
        if gap.casefold() not in {"none", "none.", "n/a", "not applicable"}:
            explanation = f"{explanation} Remaining gap: {gap}"
        return CandidateEvidenceMatch(
            criterion_id=judgment.criterion_id,
            alignment=judgment.alignment,
            resume_evidence_ids=judgment.resume_evidence_ids,
            explanation=explanation,
            confidence=judgment.evidence_support_score / 100,
            confidence_basis=judgment.score_reason,
            supported_strength=judgment.supported_strength,
            remaining_gap=judgment.remaining_gap,
            evidence_support_score=judgment.evidence_support_score,
            score_reason=judgment.score_reason,
            candidate_profile_field_ids=judgment.candidate_profile_field_ids,
        )
