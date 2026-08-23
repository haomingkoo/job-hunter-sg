"""Shared request/result types and the specialist/judge contracts for target
assessment, consumed by the open-agent runner. The mandatory judge is the
independent output-quality gate over whatever the open orchestrator produces.
Deterministic contract validation first cross-checks every required specialist,
criterion citation, profile field and resume evidence reference."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Literal, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

import config
from prompt_safety import xml_data_block

from .candidate_profile import CandidateEvidenceProfile
from .fair_hiring import mentions_protected_status
from .interface import ConfirmedEvidenceFact
from .model_transport_observer import transport_role
from .discovery import JobSnapshot
from .persona_packs import load_persona_pack_registry
from .prompts.target_assessment import (
    TARGET_JUDGE_PROMPT_VERSION,
    TARGET_SYNTHESIS_CORRECTION_PROMPT_VERSION,
)
from .role_success import RoleSuccessProfile
from .resume_edit_evidence import ResumeEditEvidenceValidator
from .telemetry import RecruitmentTelemetry


TARGET_ASSESSMENT_POLICY_VERSION = "open-agent-target-assessment-v3"


@dataclass(frozen=True)
class TargetAssessmentRequest:
    candidate_profile: CandidateEvidenceProfile
    role_profile: RoleSuccessProfile
    target_job: JobSnapshot
    trace_key: str
    edit_evidence_validator: ResumeEditEvidenceValidator
    resume_document: dict[str, Any] | None = None
    confirmed_evidence: tuple[ConfirmedEvidenceFact, ...] = ()


@dataclass(frozen=True)
class TargetAssessmentProgress:
    team_member: str
    status: Literal["running", "completed", "failed", "paused", "quality_blocked"]
    summary: str
    detail: dict


@dataclass(frozen=True)
class TargetAssessmentResult:
    status: Literal["completed", "quality_blocked", "failed"]
    specialist_runs: tuple[dict, ...]
    synthesis: str
    judge: dict | None
    correction: dict | None
    error: dict | None
    execution_policy: dict
    synthesis_claims: tuple[dict, ...] = ()
    proposed_edits: tuple[dict, ...] = ()
    execution_metrics: dict = field(default_factory=dict)
    # Internal cleanup debt; RecruitmentTeam persists it in hidden case facts.
    # It never crosses TargetAssessmentArtifactSnapshot.
    checkpoint_cleanup_token: str | None = None


TargetAssessmentUpdate = TargetAssessmentProgress | TargetAssessmentResult


class TargetAssessmentRunner(Protocol):
    def run(
        self,
        request: TargetAssessmentRequest,
        *,
        renew_lease: Callable[[], None] | None = None,
    ) -> Iterator[TargetAssessmentUpdate]: ...

    def resume(
        self,
        pause_token: str,
        answer: str,
        request: TargetAssessmentRequest,
        specialist_runs: list[dict],
        synthesis: str,
        proposed_edits: list[dict],
        ask_candidate_call_id: str | None = None,
        renew_lease: Callable[[], None] | None = None,
        synthesis_claims: list[dict] | None = None,
    ) -> Iterator[TargetAssessmentUpdate]: ...


class ScriptedTargetAssessmentRunner:
    def __init__(
        self,
        updates: list[TargetAssessmentUpdate],
        resume_updates: list[TargetAssessmentUpdate] | None = None,
    ):
        self._updates = tuple(updates)
        self._resume_updates = tuple(resume_updates) if resume_updates is not None else ()
        self.call_count = 0
        self.resume_calls: list[tuple[str, str]] = []
        self.resume_call_args: list[dict] = []

    def run(
        self,
        request: TargetAssessmentRequest,
        *,
        renew_lease: Callable[[], None] | None = None,
    ) -> Iterator[TargetAssessmentUpdate]:
        self.call_count += 1
        yield from self._updates

    def resume(
        self,
        pause_token: str,
        answer: str,
        request: TargetAssessmentRequest,
        specialist_runs: list[dict],
        synthesis: str,
        proposed_edits: list[dict],
        ask_candidate_call_id: str | None = None,
        renew_lease: Callable[[], None] | None = None,
        synthesis_claims: list[dict] | None = None,
    ) -> Iterator[TargetAssessmentUpdate]:
        self.resume_calls.append((pause_token, answer))
        self.resume_call_args.append(
            {
                "pause_token": pause_token,
                "answer": answer,
                "specialist_runs": specialist_runs,
                "synthesis": synthesis,
                "proposed_edits": proposed_edits,
                "ask_candidate_call_id": ask_candidate_call_id,
                "synthesis_claims": list(synthesis_claims or []),
            }
        )
        yield from self._resume_updates


class SpecialistFinding(BaseModel):
    """One specialist finding with its own evidence links."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["strength", "weakness", "evidence_gap"]
    statement: str = Field(min_length=1)
    criterion_ids: list[str] = Field(min_length=1)
    candidate_profile_field_ids: list[str] = Field(default_factory=list)
    resume_evidence_ids: list[str] = Field(default_factory=list)


class SpecialistSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    findings: list[SpecialistFinding] = Field(min_length=1)
    # Compatibility projections for stored v1 reports. New model submissions
    # use `findings`; these lists are derived when omitted.
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    criterion_ids: list[str] = Field(default_factory=list)
    candidate_profile_field_ids: list[str] = Field(default_factory=list)
    resume_evidence_ids: list[str] = Field(default_factory=list)
    score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def migrate_report_wide_findings(cls, value):
        if not isinstance(value, dict) or value.get("findings"):
            return value
        migrated = dict(value)
        citations = {
            "criterion_ids": list(value.get("criterion_ids") or []),
            "candidate_profile_field_ids": list(value.get("candidate_profile_field_ids") or []),
            "resume_evidence_ids": list(value.get("resume_evidence_ids") or []),
        }
        migrated["findings"] = [
            {"kind": kind, "statement": statement, **citations}
            for kind, key in (
                ("strength", "strengths"),
                ("weakness", "weaknesses"),
                ("evidence_gap", "evidence_gaps"),
            )
            for statement in value.get(key) or []
        ] or [{"kind": "evidence_gap", "statement": value.get("summary") or "No finding.", **citations}]
        return migrated

    @model_validator(mode="after")
    def project_findings(self):
        projections = {
            "strengths": [item.statement for item in self.findings if item.kind == "strength"],
            "weaknesses": [item.statement for item in self.findings if item.kind == "weakness"],
            "evidence_gaps": [item.statement for item in self.findings if item.kind == "evidence_gap"],
        }
        for field_name, statements in projections.items():
            if not getattr(self, field_name):
                object.__setattr__(self, field_name, statements)
        return self


TARGET_SYNTHESIS_MAX_CLAIMS = 8
TARGET_SYNTHESIS_MAX_STATEMENT_CHARS = 600
TARGET_SYNTHESIS_MAX_CITATIONS_PER_KIND = 12


class SynthesisClaim(BaseModel):
    """One candidate-facing conclusion and the exact records that support it."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["strength", "gap", "next_step"]
    statement: str = Field(min_length=1, max_length=TARGET_SYNTHESIS_MAX_STATEMENT_CHARS)
    criterion_ids: list[str] = Field(
        min_length=1,
        max_length=TARGET_SYNTHESIS_MAX_CITATIONS_PER_KIND,
    )
    candidate_profile_field_ids: list[str] = Field(
        default_factory=list,
        max_length=TARGET_SYNTHESIS_MAX_CITATIONS_PER_KIND,
    )
    resume_evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=TARGET_SYNTHESIS_MAX_CITATIONS_PER_KIND,
    )
    candidate_evidence_ids: list[str] = Field(
        default_factory=list,
        max_length=TARGET_SYNTHESIS_MAX_CITATIONS_PER_KIND,
    )


class TargetSynthesisSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[SynthesisClaim] = Field(
        min_length=1,
        max_length=TARGET_SYNTHESIS_MAX_CLAIMS,
        description=(
            f"Submit at most {TARGET_SYNTHESIS_MAX_CLAIMS} concise candidate-facing claims."
        ),
    )


_SYNTHESIS_QUANTIFIED_CLAIM = re.compile(
    r"(?<![\w.])(?:"
    r"\$\s*\d+(?:,\d{3})*(?:\.\d+)?|"
    r"\d+(?:\.\d+)?\s*(?:%|percent\b)|"
    r"\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?|"
    r"\d+(?:\.\d+)?\+?\s*(?:years?|months?)\b|"
    r"\d+(?:\.\d+)?\s*(?:-|–|—|to)\s*\d+(?:\.\d+)?"
    r")",
    re.IGNORECASE,
)
_SYNTHESIS_SPECULATION = re.compile(
    r"\b(?:suspicious(?:ly)?|hiring\s+(?:chance|probability|likelihood)|"
    r"competitive\s+(?:candidate|market)|(?:hot|growing|weak|strong)\s+(?:market|demand))\b"
    r"|\b(?:will\s+)?(?:not\s+)?(?:fail(?:s)?|pass(?:es)?)\s+"
    r"(?:the\s+)?(?:first\s+|initial\s+|automated\s+)?screen(?:ing)?\b"
    r"|\b(?:first[-\s]?screen|initial\s+screen|automated\s+screen(?:ing)?|screening)\s+pass\b"
    r"|\bunparseable\b",
    re.IGNORECASE,
)
def _normalized_quantified_claims(text: str) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for match in _SYNTHESIS_QUANTIFIED_CLAIM.finditer(text):
        raw = match.group(0)
        value = raw.casefold().replace(",", "")
        value = re.sub(r"\s+", "", value)
        value = value.replace("percent", "%")
        value = value.replace("years", "year").replace("months", "month")
        # "5+ years" and "at least 5 years" express the same lower bound;
        # the latter regex match starts at the numeral. Preserve ranges.
        if ("year" in value or "month" in value) and not re.search(r"[-–—]|to", value):
            value = value.replace("+", "")
        normalized[value] = raw
    return normalized


def _quantity_diagnostic(values: list[str]) -> str:
    """Render only the rejected quantities in a stable, log-safe validation code."""

    return ",".join(
        re.sub(r"[^0-9a-z%$+.-]+", "_", value.casefold()).strip("_")
        for value in values
    )


def validate_target_synthesis(
    request: TargetAssessmentRequest,
    submission: TargetSynthesisSubmission,
) -> tuple[str, ...]:
    """Fail closed before judging free prose that is not linked to supplied evidence.

    The model still chooses what conclusions matter and how to phrase them. This
    contract makes each published conclusion traceable to one role criterion and,
    for strengths, to candidate evidence. Risky quantified facts must occur in
    those cited records, while deterministic policy checks block market colour,
    protected-status reasoning, and character judgments before semantic review.
    """

    criteria = {item.criterion_id: item for item in request.role_profile.criteria}
    fields = {item.field_id: item for item in request.candidate_profile.fields}
    resume_evidence = {
        item.evidence_id: item.text
        for item in (
            *request.candidate_profile.cited_resume_evidence,
            *request.role_profile.cited_resume_evidence,
        )
    }
    for field in request.candidate_profile.fields:
        for index, evidence_id in enumerate(field.resume_evidence_ids):
            quote = (
                field.evidence_quotes[index]
                if index < len(field.evidence_quotes)
                else field.statement
            )
            resume_evidence.setdefault(evidence_id, quote)
    confirmed = {item.evidence_id: item.evidence_quote for item in request.confirmed_evidence}
    failures: list[str] = []

    for index, claim in enumerate(submission.claims):
        prefix = f"synthesis:claim:{index}"
        criterion_ids = set(claim.criterion_ids)
        field_ids = set(claim.candidate_profile_field_ids)
        resume_ids = set(claim.resume_evidence_ids)
        confirmed_ids = set(claim.candidate_evidence_ids)
        if not criterion_ids <= criteria.keys():
            failures.append(f"{prefix}:unknown_criterion_citation")
        if not field_ids <= fields.keys():
            failures.append(f"{prefix}:unknown_profile_citation")
        if not resume_ids <= resume_evidence.keys():
            failures.append(f"{prefix}:unknown_resume_citation")
        if not confirmed_ids <= confirmed.keys():
            failures.append(f"{prefix}:unknown_candidate_evidence_citation")

        linked_resume_ids = {
            evidence_id
            for field_id in field_ids
            if field_id in fields
            for evidence_id in fields[field_id].resume_evidence_ids
        }
        if resume_ids and not resume_ids <= linked_resume_ids:
            failures.append(f"{prefix}:unlinked_resume_citation")
        if claim.kind == "strength" and not (
            (field_ids and resume_ids) or confirmed_ids
        ):
            failures.append(f"{prefix}:strength_missing_candidate_evidence")
        if mentions_protected_status(claim.statement):
            failures.append(f"{prefix}:protected_status")
        if _SYNTHESIS_SPECULATION.search(claim.statement):
            failures.append(f"{prefix}:speculative_claim")

        cited_texts = [
            criteria[item].statement
            for item in criterion_ids
            if item in criteria
        ]
        cited_texts.extend(
            citation.relevant_excerpt
            for item in criterion_ids
            if item in criteria
            for citation in criteria[item].source_citations
        )
        cited_texts.extend(fields[item].statement for item in field_ids if item in fields)
        cited_texts.extend(resume_evidence[item] for item in resume_ids if item in resume_evidence)
        cited_texts.extend(confirmed[item] for item in confirmed_ids if item in confirmed)
        support = "\n".join(cited_texts)
        claim_quantities = _normalized_quantified_claims(claim.statement)
        support_quantities = _normalized_quantified_claims(support)
        unsupported_numbers = claim_quantities.keys() - support_quantities.keys()
        if unsupported_numbers:
            rejected = [claim_quantities[value] for value in sorted(unsupported_numbers)]
            failures.append(
                f"{prefix}:unsupported_numeric_claim:{_quantity_diagnostic(rejected)}"
            )
    return tuple(failures)


def render_target_synthesis(submission: TargetSynthesisSubmission) -> str:
    """Render only validated claims; provenance stays in the stored claim records."""

    headings = {"strength": "Strengths", "gap": "Evidence gaps", "next_step": "Next steps"}
    sections: list[str] = []
    for kind in ("strength", "gap", "next_step"):
        claims = [claim.statement.strip() for claim in submission.claims if claim.kind == kind]
        if claims:
            sections.append(f"{headings[kind]}\n" + "\n".join(f"- {claim}" for claim in claims))
    return "\n\n".join(sections)


_PUBLIC_SPECIALIST_VALIDATION_CATEGORIES = (
    "assessment_context_missing",
    "missing_criterion_citations",
    "unknown_criterion_citation",
    "missing_profile_citations",
    "unknown_profile_citation",
    "missing_resume_citations",
    "unlinked_resume_citation",
    "unsupported_numeric_claim",
    "protected_status",
    "speculative_claim",
)


def public_specialist_validation_code(value: str) -> str:
    """Keep a correction category without persisting IDs or rejected content."""
    code = value.strip()
    if not code:
        return ""
    for category in _PUBLIC_SPECIALIST_VALIDATION_CATEGORIES:
        if code == category or f":{category}" in code:
            return category
    return "specialist_submission_rejected"


def validate_specialist_submission(
    request: TargetAssessmentRequest,
    submission: SpecialistSubmission,
    expected_persona_id: str,
) -> tuple[str, ...]:
    """Validate one persona's grounded submission at its tool seam.

    The aggregate validator below uses this same contract as a final defence,
    but specialist tools call it before returning success. That gives the
    specialist an actionable rejection while it can still correct its own
    citations instead of persisting invalid work until the run ends.
    """

    failures: list[str] = []
    prefix = f"specialist:{expected_persona_id}"
    if submission.persona_id != expected_persona_id:
        failures.append(f"{prefix}:persona_mismatch")

    criteria = {criterion.criterion_id: criterion for criterion in request.role_profile.criteria}
    allowed_criteria = set(criteria)
    profile_fields = {field.field_id: field for field in request.candidate_profile.fields}
    assessed_text = "\n".join((
        submission.summary,
        *(finding.statement for finding in submission.findings),
        submission.score_reason,
    ))
    all_field_ids = {
        field_id
        for finding in submission.findings
        for field_id in finding.candidate_profile_field_ids
    }
    cited_profile_text = "\n".join(
        profile_fields[field_id].statement
        for field_id in all_field_ids
        if field_id in profile_fields
    )
    if mentions_protected_status(assessed_text) or mentions_protected_status(cited_profile_text):
        failures.append(f"{prefix}:protected_status")
    if _SYNTHESIS_SPECULATION.search(assessed_text):
        failures.append(f"{prefix}:speculative_claim")

    all_support: list[str] = []
    for finding_index, finding in enumerate(submission.findings):
        finding_prefix = f"{prefix}:finding:{finding_index}"
        criterion_ids = set(finding.criterion_ids)
        field_ids = set(finding.candidate_profile_field_ids)
        evidence_ids = set(finding.resume_evidence_ids)
        if not criterion_ids:
            failures.append(f"{finding_prefix}:missing_criterion_citations")
        elif not criterion_ids <= allowed_criteria:
            failures.append(f"{finding_prefix}:unknown_criterion_citation")
        if finding.kind != "evidence_gap" and not field_ids:
            failures.append(f"{finding_prefix}:missing_profile_citations")
        elif not field_ids <= profile_fields.keys():
            failures.append(f"{finding_prefix}:unknown_profile_citation")

        evidence_for_cited_fields = {
            evidence_id
            for field_id in field_ids
            if field_id in profile_fields
            for evidence_id in profile_fields[field_id].resume_evidence_ids
        }
        if finding.kind == "strength" and not evidence_ids:
            failures.append(f"{finding_prefix}:missing_resume_citations")
        elif evidence_ids and not evidence_ids <= evidence_for_cited_fields:
            failures.append(f"{finding_prefix}:unlinked_resume_citation")

        cited_support = [
            criteria[criterion_id].statement
            for criterion_id in criterion_ids
            if criterion_id in criteria
        ]
        cited_support.extend(
            citation.relevant_excerpt
            for criterion_id in criterion_ids
            if criterion_id in criteria
            for citation in criteria[criterion_id].source_citations
        )
        cited_support.extend(
            profile_fields[field_id].statement
            for field_id in field_ids
            if field_id in profile_fields
        )
        for field_id in field_ids:
            field = profile_fields.get(field_id)
            if field is not None:
                cited_support.extend(field.evidence_quotes)
        all_support.extend(cited_support)
        finding_quantities = _normalized_quantified_claims(finding.statement)
        supported_quantities = _normalized_quantified_claims("\n".join(cited_support))
        unsupported_finding_quantities = finding_quantities.keys() - supported_quantities.keys()
        if unsupported_finding_quantities:
            rejected = [
                finding_quantities[value]
                for value in sorted(unsupported_finding_quantities)
            ]
            failures.append(
                f"{finding_prefix}:unsupported_numeric_claim:{_quantity_diagnostic(rejected)}"
            )

    supported_report_quantities = _normalized_quantified_claims("\n".join(all_support))
    summary_quantities = _normalized_quantified_claims(submission.summary)
    unsupported_summary_quantities = summary_quantities.keys() - supported_report_quantities.keys()
    if unsupported_summary_quantities:
        rejected = [
            summary_quantities[value]
            for value in sorted(unsupported_summary_quantities)
        ]
        failures.append(
            f"{prefix}:summary:unsupported_numeric_claim:{_quantity_diagnostic(rejected)}"
        )
    # The required score is reviewer metadata, not a claim about the candidate.
    # A score reason may explain that exact value as either a percentage or
    # x/100, but it may not introduce any other unsupported quantity.
    own_score_quantities = _normalized_quantified_claims(
        f"{submission.score}% {submission.score}/100"
    )
    score_reason_quantities = _normalized_quantified_claims(submission.score_reason)
    unsupported_score_reason_quantities = score_reason_quantities.keys() - (
        supported_report_quantities.keys() | own_score_quantities.keys()
    )
    if unsupported_score_reason_quantities:
        rejected = [
            score_reason_quantities[value]
            for value in sorted(unsupported_score_reason_quantities)
        ]
        failures.append(
            f"{prefix}:score_reason:unsupported_numeric_claim:{_quantity_diagnostic(rejected)}"
        )
    return tuple(failures)


def validate_specialist_runs(
    request: TargetAssessmentRequest,
    specialist_runs: list[dict],
    required_persona_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Validate the evidence and coverage contract before a judge can publish.

    Delegation order and iteration remain model-chosen. This gate only proves
    that every configured reviewer actually returned one grounded submission.
    """

    failures: list[str] = []
    seen_personas: set[str] = set()
    for index, run in enumerate(specialist_runs):
        persona_id = str(run.get("persona_id") or "").strip()
        if not persona_id:
            failures.append(f"specialist:{index}:missing_persona_id")
            continue
        seen_personas.add(persona_id)
        if persona_id not in required_persona_ids:
            failures.append(f"specialist:{persona_id}:unexpected")

        try:
            submission = SpecialistSubmission.model_validate(run.get("submission") or {})
        except ValidationError:
            failures.append(f"specialist:{persona_id}:schema_invalid")
            continue
        if run.get("status") != "completed":
            failures.append(f"specialist:{persona_id}:not_completed")
        failures.extend(validate_specialist_submission(request, submission, persona_id))

    missing = set(required_persona_ids) - seen_personas
    for persona_id in required_persona_ids:
        if persona_id in missing:
            failures.append(f"specialist:{persona_id}:missing")
    return tuple(failures)


class Deduction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rubric: Literal[
        "evidence_grounding",
        "role_coverage",
        "decision_usefulness",
        "fairness_and_boundaries",
    ]
    reason: str = Field(
        min_length=1,
        description=(
            "Concise deduction about synthesis output quality only; never candidate fit, "
            "screening, hiring probability, market demand, or protected status."
        ),
    )
    points: int = Field(ge=0, le=100)


class RubricScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_grounding: int = Field(ge=0, le=100)
    role_coverage: int = Field(ge=0, le=100)
    decision_usefulness: int = Field(ge=0, le=100)
    fairness_and_boundaries: int = Field(ge=0, le=100)


class JudgeSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strengths: list[str] = Field(
        description=(
            "Strengths of the synthesis output only; never claims about candidate fit, "
            "screening, hiring probability, market demand, or protected status."
        )
    )
    weaknesses: list[str] = Field(
        description=(
            "Weaknesses of the synthesis output only; never claims about candidate fit, "
            "screening, hiring probability, market demand, or protected status."
        )
    )
    deductions: list[Deduction]
    evidence_gaps: list[str] = Field(
        description=(
            "Evidence or coverage missing from the synthesis; do not turn absence of evidence "
            "into a claim that the candidate lacks capability."
        )
    )
    rubric_scores: RubricScores
    score: int = Field(ge=0, le=100)
    score_reason: str = Field(
        min_length=1,
        description=(
            "Reason for the synthesis-output quality score only, not a candidate fit or "
            "screening score."
        ),
    )
    confidence: int = Field(ge=0, le=100)
    confidence_reason: str = Field(
        min_length=1,
        description=(
            "Reason for confidence in this output-quality audit only; never predict hiring "
            "or screening outcomes."
        ),
    )
    disposition: Literal["pass", "revise", "block"]


_CANDIDATE_SCORING_CLAIM = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent)\s+(?:alignment|fit|match)\b"
    r"|\b(?:candidate|applicant).{0,40}\b(?:fit|alignment|match)\s+(?:score|percentage)\b",
    re.IGNORECASE,
)
_JUDGE_SPECULATION_ASSERTION = re.compile(
    r"(?:^|[.!?]\s+)(?:the\s+)?(?:candidate|applicant|resume)\b[^.!?]{0,120}\b(?:"
    r"hiring\s+(?:chance|probability|likelihood)|competitive(?:\s+candidate)?|"
    r"(?:fail(?:s)?|pass(?:es)?)\s+(?:the\s+)?(?:first\s+|initial\s+|automated\s+)?"
    r"screen(?:ing)?|unparseable)\b"
    r"|(?:^|[.!?]\s+)(?:the\s+)?(?:market|demand)\s+is\s+(?:hot|growing|weak|strong)\b",
    re.IGNORECASE,
)


def validate_judge_submission(submission: JudgeSubmission) -> tuple[str, ...]:
    """Keep the output-quality judge from publishing candidate-screening claims."""

    narrative = "\n".join(
        (
            *submission.strengths,
            *submission.weaknesses,
            *submission.evidence_gaps,
            *(item.reason for item in submission.deductions),
            submission.score_reason,
            submission.confidence_reason,
        )
    )
    failures: list[str] = []
    if mentions_protected_status(narrative):
        failures.append("judge:protected_status")
    # A quality review may truthfully say that the synthesis *avoids* a
    # screening-pass claim. The synthesis validator's broader expression also
    # catches that meta-language, so the judge contract rejects only direct
    # candidate assertions here.
    if _JUDGE_SPECULATION_ASSERTION.search(narrative):
        failures.append("judge:speculative_claim")
    if _CANDIDATE_SCORING_CLAIM.search(narrative):
        failures.append("judge:candidate_scoring_claim")
    return tuple(failures)


class SynthesisCorrectionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[SynthesisClaim] = Field(
        min_length=1,
        max_length=TARGET_SYNTHESIS_MAX_CLAIMS,
        description=(
            f"Submit at most {TARGET_SYNTHESIS_MAX_CLAIMS} concise corrected claims."
        ),
    )


def _dump_specialist(**payload: Any) -> dict:
    return SpecialistSubmission(**payload).model_dump()


def _dump_judge(**payload: Any) -> dict:
    return JudgeSubmission(**payload).model_dump()


def _dump_correction(**payload: Any) -> dict:
    return SynthesisCorrectionSubmission(**payload).model_dump()


SPECIALIST_TOOL = StructuredTool.from_function(
    func=_dump_specialist,
    name="submit_target_specialist_assessment",
    description=(
        "Submit this persona's complete bounded assessment with strengths, weaknesses, "
        "evidence gaps, raw evidence-support score, reason, and all provenance IDs."
    ),
    args_schema=SpecialistSubmission,
)
JUDGE_TOOL = StructuredTool.from_function(
    func=_dump_judge,
    name="submit_target_assessment_judgment",
    description=(
        "Submit the independent output-quality judgment with strengths, weaknesses, "
        "deductions, gaps, rubric scores, score reason, confidence basis, and disposition."
    ),
    args_schema=JudgeSubmission,
)
SYNTHESIS_CORRECTION_TOOL = StructuredTool.from_function(
    func=_dump_correction,
    name="submit_corrected_target_assessment",
    description=(
        "Submit corrected candidate-facing claims with exact criterion and candidate-evidence "
        "citations. Unsupported prose is rejected deterministically before rejudging."
    ),
    args_schema=SynthesisCorrectionSubmission,
)


def target_assessment_execution_policy() -> dict:
    registry = load_persona_pack_registry()
    return {
        "policy_version": TARGET_ASSESSMENT_POLICY_VERSION,
        "persona_pack_version": registry.pack_version,
        "specialists": [pack.persona_id for pack in registry.personas],
        "synthesis_validation_attempts": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
        "maximum_synthesis_corrections": config.RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS,
        "model_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
        "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
        "correction_prompt_version": TARGET_SYNTHESIS_CORRECTION_PROMPT_VERSION,
        "judge_prompt_version": TARGET_JUDGE_PROMPT_VERSION,
        "fallback_model": None,
        "raw_resume_passed_to_assessment": False,
        "content_truncation": False,
    }


def tool_payload(response: AIMessage, tool: StructuredTool, schema: type[BaseModel]) -> tuple[dict | None, str]:
    calls = [call for call in response.tool_calls if call.get("name") == tool.name]
    if len(response.tool_calls) != 1 or len(calls) != 1:
        return None, "tool_call:required_exactly_one"
    try:
        return schema(**(calls[0].get("args") or {})).model_dump(), ""
    except ValidationError:
        return None, "schema_validation"


def usage_from_response(response: AIMessage) -> tuple[int, int, str]:
    usage = getattr(response, "usage_metadata", None) or {}
    model_name = str(getattr(response, "response_metadata", {}).get("model_name") or "unknown")
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), model_name


def invoke_structured(
    model,
    tool: StructuredTool,
    system_prompt: str,
    data_name: str,
    data: dict,
    *,
    telemetry: RecruitmentTelemetry,
    operation: str,
    attempt: int,
    max_attempts: int,
    attributes: dict[str, str | int | float | bool],
) -> tuple[dict | None, str, int, int, str]:
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=xml_data_block(
                data_name,
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            )
        ),
    ]
    with telemetry.operation(
        operation,
        {
            **attributes,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "configured_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
            "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
        },
    ) as span:
        with transport_role(str(attributes.get("stage") or "structured_model_call")):
            response = model.bind_tools([tool], tool_choice=tool.name).invoke(messages)
        input_tokens, output_tokens, model_name = usage_from_response(response)
        span.set_attribute("input_tokens", input_tokens)
        span.set_attribute("output_tokens", output_tokens)
        span.set_attribute("model", model_name)
        payload, failure = tool_payload(response, tool, tool.args_schema)
        span.set_attribute("validation_code", failure)
        span.set_attribute("accepted", payload is not None)
    return payload, failure, input_tokens, output_tokens, model_name
