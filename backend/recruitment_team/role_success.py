"""Source-backed role-definition seam and LangChain adapter."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict

import config
from prompt_safety import unescape_xml_data, xml_data_block

from .discovery import JobSnapshot
from .prompts import ROLE_SUCCESS_PROMPT_VERSION, ROLE_SUCCESS_SYSTEM_PROMPT
from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry

if TYPE_CHECKING:
    from .candidate_profile import CandidateEvidenceProfile


CriterionCategory = Literal[
    "outcomes",
    "responsibilities",
    "technical_skills",
    "transferable_skills",
    "scope_seniority",
    "work_context",
    "credentials",
    "preferred_signals",
    "unknowns",
    "prohibited_criteria",
]
RequirementLevel = Literal["required", "preferred", "transferable", "unknown", "prohibited"]
Alignment = Literal["direct", "partial", "transferable", "missing", "unknown"]
TaxonomyMatchQuality = Literal["exact", "adjacent", "unmatched"]


@dataclass(frozen=True)
class OccupationSource:
    source_id: str
    title: str
    url: str
    jurisdiction: str
    match_quality: Literal["exact", "adjacent"]
    content: str


@dataclass(frozen=True)
class RoleSource:
    source_id: str
    source_type: Literal["target_job", "comparable_job", "occupation", "fairness_policy"]
    title: str
    url: str
    publication_date: str
    evidence_strength: Literal["primary", "supporting", "analogy", "policy"]
    evidence_fields: tuple[str, ...]


@dataclass(frozen=True)
class RoleCitation:
    source_id: str
    source_path: str
    relevant_excerpt: str


@dataclass(frozen=True)
class RoleCriterion:
    criterion_id: str
    category: CriterionCategory
    requirement_level: RequirementLevel
    statement: str
    source_ids: tuple[str, ...]
    source_citations: tuple[RoleCitation, ...] = ()
    alternative_group_id: str | None = None


@dataclass(frozen=True)
class CandidateEvidenceMatch:
    criterion_id: str
    alignment: Alignment
    resume_evidence_ids: tuple[str, ...]
    explanation: str
    confidence: float
    confidence_basis: str
    supported_strength: str = ""
    remaining_gap: str = ""
    evidence_support_score: int | None = None
    score_reason: str = ""
    candidate_profile_field_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResumeEvidenceRecord:
    evidence_id: str
    kind: str
    text: str
    source_locator: str
    section_key: str


@dataclass(frozen=True)
class PolicyConstraint:
    constraint_id: str
    statement: str
    source_id: str


@dataclass(frozen=True)
class SourceCoverage:
    exact_job: bool
    comparable_job_count: int
    occupation_source_count: int
    taxonomy_match_quality: TaxonomyMatchQuality
    notes: tuple[str, ...]


@dataclass(frozen=True)
class RoleSuccessProfile:
    profile_version: str
    target_job_id: int
    sources: tuple[RoleSource, ...]
    criteria: tuple[RoleCriterion, ...]
    candidate_evidence: tuple[CandidateEvidenceMatch, ...]
    source_coverage: SourceCoverage
    clarification_question: str | None
    validation_notes: tuple[str, ...] = ()
    cited_resume_evidence: tuple[ResumeEvidenceRecord, ...] = ()
    policy_constraints: tuple[PolicyConstraint, ...] = ()
    assessment_disposition: Literal["pass", "needs_clarification"] | None = None
    evidence_assessment_prompt_version: str = ""
    evidence_assessment_model: str = ""
    evidence_assessment_attempt_count: int = 0


@dataclass(frozen=True)
class RoleProfileRun:
    profile: RoleSuccessProfile
    model_name: str
    attempt_count: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    validation_codes: tuple[str, ...] = ()
    generator_attempt_count: int = 0
    assessor_attempt_count: int = 0
    generator_model_name: str = ""
    assessor_model_name: str = ""


class RoleDefinitionValidationError(ValueError):
    def __init__(self, validation_code: str, rejected_submission: dict | None):
        super().__init__(f"role definition validation failed: {validation_code}")
        self.validation_code = validation_code
        self.rejected_submission = rejected_submission


RoleProfileValidationError = RoleDefinitionValidationError


class RoleDefinitionGenerator(Protocol):
    def define(
        self,
        target: JobSnapshot,
        comparable_jobs: tuple[JobSnapshot, ...],
    ) -> RoleProfileRun: ...


class RoleSuccessProfiler(Protocol):
    """Compose role definition and candidate evidence into a usable profile."""

    def profile(
        self,
        candidate_profile: "CandidateEvidenceProfile",
        target: JobSnapshot,
        comparable_jobs: tuple[JobSnapshot, ...],
    ) -> RoleProfileRun: ...


class _RoleCitationSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_path: str
    relevant_excerpt: str


class _CriterionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    category: CriterionCategory
    requirement_level: RequirementLevel
    statement: str
    source_ids: list[str]
    source_citations: list[_RoleCitationSubmission]


class _RoleDefinitionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[_CriterionSubmission]
    clarification_question: str | None = None


def _submit_role_definition(**payload: Any) -> dict:
    return _RoleDefinitionSubmission(**payload).model_dump()


_SUBMIT_ROLE_DEFINITION_TOOL = StructuredTool.from_function(
    func=_submit_role_definition,
    name="submit_role_definition",
    description=(
        "Submit the complete source-backed definition of the selected role. Each "
        "criterion must cite an allowed role source, its top-level field path, and a "
        "contiguous verbatim excerpt. Use the optional clarification question only "
        "when source ambiguity prevents a defensible definition. Do not assess the "
        "candidate or submit resume evidence; use the independent evidence assessor "
        "for that."
    ),
    args_schema=_RoleDefinitionSubmission,
)


TAFEP_SOURCE = RoleSource(
    source_id="fairness_policy:tafep",
    source_type="fairness_policy",
    title="TAFEP Tripartite Guidelines on Fair Employment Practices",
    url="https://www.tal.sg/tafep/getting-started/fair/tripartite-guidelines",
    publication_date="",
    evidence_strength="policy",
    evidence_fields=("job_related_selection_policy",),
)


def _job_data(job: JobSnapshot, *, primary: bool) -> dict:
    data = {
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "skills": list(job.skills),
        "source": {
            "source": job.source.source,
            "url": job.source.url,
            "source_posting_id": job.source.source_posting_id,
            "posted_date": job.source.posted_date,
            "closing_date": job.source.closing_date,
            "availability": job.source.availability,
            "snapshot_sha256": job.source.snapshot_sha256,
        },
    }
    if primary:
        data.update(
            {
                "location": job.location,
                "salary": job.salary,
                "description": job.description,
            }
        )
    return data


def _source_text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(_source_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(_source_text(item) for item in value)
    return str(value or "")


def _normalize_source_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _tool_payload(response: AIMessage) -> tuple[dict | None, dict, str]:
    rejected = {"content": response.content, "tool_calls": response.tool_calls}
    call = next((call for call in response.tool_calls if call.get("name") == _SUBMIT_ROLE_DEFINITION_TOOL.name), None)
    if call is None:
        finish_reason = str(response.response_metadata.get("finish_reason") or "")
        failure = "output_truncated:length" if finish_reason == "length" else "missing_tool_call"
        return None, rejected, failure
    try:
        return _SUBMIT_ROLE_DEFINITION_TOOL.invoke(call.get("args") or {}), rejected, ""
    except Exception:
        return None, rejected, "schema_validation"


def _validate_submission(
    payload: dict | None,
    *,
    source_ids: set[str],
    role_source_fields: dict[str, dict[str, str]],
) -> tuple[dict | None, str]:
    if not isinstance(payload, dict):
        return None, "invalid_submission"
    criteria = payload.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return None, "missing_criteria"

    criterion_ids = [str(item.get("criterion_id") or "").strip() for item in criteria]
    if any(not criterion_id for criterion_id in criterion_ids):
        return None, "invalid_criterion_ids:empty"
    if len(criterion_ids) != len(set(criterion_ids)):
        return None, "invalid_criterion_ids:duplicate"

    for item in criteria:
        criterion_id = str(item["criterion_id"]).strip()
        if not str(item.get("statement") or "").strip():
            return None, f"criterion:{criterion_id}:missing_statement"
        refs = item.get("source_ids")
        if not isinstance(refs, list) or not refs:
            return None, f"criterion:{criterion_id}:missing_role_sources"
        if len(refs) != len(set(refs)) or any(ref not in source_ids for ref in refs):
            return None, f"criterion:{criterion_id}:invalid_role_source"

        citations = item.get("source_citations")
        if not isinstance(citations, list) or not citations:
            return None, f"criterion:{criterion_id}:missing_role_citations"
        cited_source_ids = {str(citation.get("source_id") or "") for citation in citations}
        if cited_source_ids != set(refs):
            return None, f"criterion:{criterion_id}:role_citation_source_mismatch"
        for citation in citations:
            source_id = str(citation.get("source_id") or "").strip()
            source_path = str(citation.get("source_path") or "").strip()
            unescaped_excerpt = unescape_xml_data(str(citation.get("relevant_excerpt") or ""))
            excerpt = _normalize_source_text(unescaped_excerpt)
            if not source_id or not source_path or not excerpt:
                return None, f"criterion:{criterion_id}:missing_role_citation_fields"
            source_value = role_source_fields.get(source_id, {}).get(source_path)
            if source_value is None:
                return None, f"criterion:{criterion_id}:invalid_role_citation_path"
            if excerpt not in _normalize_source_text(source_value):
                return None, f"criterion:{criterion_id}:role_citation_excerpt_not_found"
            citation["relevant_excerpt"] = unescaped_excerpt

    return payload, ""


class LangChainRoleDefinitionGenerator:
    """Generate a source-backed role definition with one provenance correction retry."""

    def __init__(
        self,
        model=None,
        occupation_sources: tuple[OccupationSource, ...] = (),
        telemetry: RecruitmentTelemetry | None = None,
    ):
        if model is None:
            from resume_agent.models import create_agent_model

            model = create_agent_model(
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            )
        if not hasattr(model, "bind_tools"):
            raise TypeError("Role definition model must support bind_tools")
        self._model = model
        self._occupation_sources = occupation_sources
        self._telemetry = telemetry or OpenTelemetryRecorder()

    def define(
        self,
        target: JobSnapshot,
        comparable_jobs: tuple[JobSnapshot, ...],
    ) -> RoleProfileRun:
        sources = [
            RoleSource(
                source_id=f"target_job:{target.job_id}",
                source_type="target_job",
                title=f"{target.title} — {target.company}",
                url=target.source.url,
                publication_date=target.source.posted_date,
                evidence_strength="primary",
                evidence_fields=(
                    "title",
                    "company",
                    "location",
                    "salary",
                    "employment_type",
                    "seniority",
                    "description",
                    "skills",
                    "source",
                ),
            )
        ]
        sources.extend(
            RoleSource(
                source_id=f"comparable_job:{job.job_id}",
                source_type="comparable_job",
                title=f"{job.title} — {job.company}",
                url=job.source.url,
                publication_date=job.source.posted_date,
                evidence_strength="supporting",
                evidence_fields=(
                    "title",
                    "company",
                    "employment_type",
                    "seniority",
                    "skills",
                    "source",
                ),
            )
            for job in comparable_jobs
        )
        sources.extend(
            RoleSource(
                source_id=f"occupation:{source.source_id}",
                source_type="occupation",
                title=source.title,
                url=source.url,
                publication_date="",
                evidence_strength="supporting" if source.match_quality == "exact" else "analogy",
                evidence_fields=("title", "jurisdiction", "match_quality", "content"),
            )
            for source in self._occupation_sources
        )
        sources.append(TAFEP_SOURCE)
        taxonomy_quality: TaxonomyMatchQuality = (
            "exact"
            if any(source.match_quality == "exact" for source in self._occupation_sources)
            else "adjacent"
            if self._occupation_sources
            else "unmatched"
        )
        allowed_source_ids = [source.source_id for source in sources if source != TAFEP_SOURCE]
        role_source_fields = {
            f"target_job:{target.job_id}": {
                key: _source_text(value) for key, value in _job_data(target, primary=True).items()
            },
            **{
                f"comparable_job:{job.job_id}": {
                    key: _source_text(value) for key, value in _job_data(job, primary=False).items()
                }
                for job in comparable_jobs
            },
            **{
                f"occupation:{source.source_id}": {
                    "title": source.title,
                    "jurisdiction": source.jurisdiction,
                    "match_quality": source.match_quality,
                    "content": source.content,
                }
                for source in self._occupation_sources
            },
        }
        source_contract = {
            "prompt_version": ROLE_SUCCESS_PROMPT_VERSION,
            "taxonomy_match_quality": taxonomy_quality,
            "allowed_role_source_ids": allowed_source_ids,
            "source_manifest": [source.__dict__ for source in sources],
        }
        messages = [
            SystemMessage(content=ROLE_SUCCESS_SYSTEM_PROMPT),
            HumanMessage(
                content="\n\n".join(
                    (
                        xml_data_block(
                            "role_source_contract_data",
                            json.dumps(source_contract, ensure_ascii=False, separators=(",", ":")),
                        ),
                        xml_data_block(
                            "target_job_data",
                            json.dumps(_job_data(target, primary=True), ensure_ascii=False, separators=(",", ":")),
                        ),
                        xml_data_block(
                            "comparable_jobs_data",
                            json.dumps(
                                [_job_data(job, primary=False) for job in comparable_jobs],
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        ),
                        xml_data_block(
                            "occupation_sources_data",
                            json.dumps(
                                [source.__dict__ for source in self._occupation_sources],
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        ),
                    )
                )
            ),
        ]
        failure = ""
        failed_payload: dict | None = None
        validation_codes: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0

        for attempt in range(1, config.ROLE_DEFINITION_VALIDATION_ATTEMPTS + 1):
            request = list(messages)
            if failure:
                request.append(
                    HumanMessage(
                        content="\n\n".join(
                            (
                                "Correct the structural or provenance error and resubmit the complete role definition.",
                                xml_data_block("validation_error_data", failure),
                                xml_data_block(
                                    "failed_role_definition_data",
                                    json.dumps(failed_payload, ensure_ascii=False, separators=(",", ":")),
                                ),
                            )
                        )
                    )
                )
            with self._telemetry.operation(
                "role_definition.model_attempt",
                {
                    "attempt": attempt,
                    "max_attempts": config.ROLE_DEFINITION_VALIDATION_ATTEMPTS,
                    "prompt_version": ROLE_SUCCESS_PROMPT_VERSION,
                    "configured_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                    "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
                },
            ) as attempt_span:
                try:
                    response = self._model.bind_tools(
                        [_SUBMIT_ROLE_DEFINITION_TOOL],
                        tool_choice=_SUBMIT_ROLE_DEFINITION_TOOL.name,
                    ).invoke(request)
                except BaseException as error:
                    attempt_span.set_attribute("status", "error")
                    attempt_span.set_attribute("error_type", type(error).__name__)
                    raise
                usage = getattr(response, "usage_metadata", None) or {}
                model_name = str(
                    getattr(response, "response_metadata", {}).get("model_name") or type(self._model).__name__
                )
                attempt_span.set_attribute("model", model_name)
                if usage.get("input_tokens") is not None:
                    attempt_span.set_attribute("input_tokens", int(usage["input_tokens"]))
                if usage.get("output_tokens") is not None:
                    attempt_span.set_attribute("output_tokens", int(usage["output_tokens"]))
                attempt_span.set_attribute(
                    "finish_reason",
                    str(getattr(response, "response_metadata", {}).get("finish_reason") or ""),
                )
                attempt_span.set_attribute("status", "success")
                attempt_span.set_attribute("error_type", "")
            total_input_tokens += int(usage.get("input_tokens") or 0)
            total_output_tokens += int(usage.get("output_tokens") or 0)
            with self._telemetry.operation(
                "role_definition.validation",
                {
                    "attempt": attempt,
                },
            ) as validation_span:
                submitted_payload, failed_output, failure = _tool_payload(response)
                accepted = None
                if not failure:
                    accepted, failure = _validate_submission(
                        submitted_payload,
                        source_ids=set(allowed_source_ids),
                        role_source_fields=role_source_fields,
                    )
                failed_payload = submitted_payload if submitted_payload is not None else failed_output
                validation_span.set_attribute("validation_code", failure)
                validation_span.set_attribute("accepted", accepted is not None)
                validation_span.set_attribute(
                    "retry_triggered",
                    accepted is None and attempt < config.ROLE_DEFINITION_VALIDATION_ATTEMPTS,
                )
            if accepted is not None:
                criteria = tuple(
                    RoleCriterion(
                        criterion_id=item["criterion_id"].strip(),
                        category=item["category"],
                        requirement_level=item["requirement_level"],
                        statement=item["statement"].strip(),
                        source_ids=tuple(item["source_ids"]),
                        source_citations=tuple(
                            RoleCitation(
                                source_id=citation["source_id"].strip(),
                                source_path=citation["source_path"].strip(),
                                relevant_excerpt=citation["relevant_excerpt"].strip(),
                            )
                            for citation in item["source_citations"]
                        ),
                    )
                    for item in accepted["criteria"]
                )
                return RoleProfileRun(
                    profile=RoleSuccessProfile(
                        profile_version=ROLE_SUCCESS_PROMPT_VERSION,
                        target_job_id=target.job_id,
                        sources=tuple(sources),
                        criteria=criteria,
                        candidate_evidence=(),
                        source_coverage=SourceCoverage(
                            exact_job=True,
                            comparable_job_count=len(comparable_jobs),
                            occupation_source_count=len(self._occupation_sources),
                            taxonomy_match_quality=taxonomy_quality,
                            notes=(
                                "The selected job is primary evidence.",
                                "Adjacent occupation evidence is analogy, not a direct requirement."
                                if taxonomy_quality == "adjacent"
                                else "No occupation taxonomy match was supplied; taxonomy precision is withheld."
                                if taxonomy_quality == "unmatched"
                                else "An exact occupation source was supplied.",
                            ),
                        ),
                        clarification_question=(str(accepted.get("clarification_question") or "").strip() or None),
                        policy_constraints=(
                            PolicyConstraint(
                                constraint_id="fair_hiring_job_related_only",
                                statement="Exclude protected and demographic attributes from fit assessment.",
                                source_id=TAFEP_SOURCE.source_id,
                            ),
                        ),
                    ),
                    model_name=model_name,
                    attempt_count=attempt,
                    input_tokens=total_input_tokens or None,
                    output_tokens=total_output_tokens or None,
                    validation_codes=tuple(validation_codes),
                    generator_attempt_count=attempt,
                    generator_model_name=model_name,
                )
            validation_codes.append(failure)
        raise RoleDefinitionValidationError(failure, failed_payload)


class ScriptedRoleDefinitionGenerator:
    def __init__(self, runs: list[RoleProfileRun]):
        self._runs = iter(runs)
        self.call_count = 0

    def define(
        self,
        target: JobSnapshot,
        comparable_jobs: tuple[JobSnapshot, ...],
    ) -> RoleProfileRun:
        self.call_count += 1
        return next(self._runs)


class ScriptedRoleSuccessProfiler:
    def __init__(self, runs: list[RoleProfileRun]):
        self._runs = iter(runs)
        self.call_count = 0

    def profile(
        self,
        candidate_profile: "CandidateEvidenceProfile",
        target: JobSnapshot,
        comparable_jobs: tuple[JobSnapshot, ...],
    ) -> RoleProfileRun:
        self.call_count += 1
        return next(self._runs)
