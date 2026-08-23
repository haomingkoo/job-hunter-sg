"""Independent semantic grounding for proposed resume edits."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

import config
from prompt_safety import UNTRUSTED_DATA_RULE, xml_data_block

from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry
from .model_transport_observer import create_observed_agent_model, transport_role


RESUME_EDIT_EVIDENCE_PROMPT_VERSION = "resume-edit-evidence-v1"


@dataclass(frozen=True)
class ResumeEditEvidenceRequest:
    original: str
    supporting_evidence: str
    rewrite: str


@dataclass(frozen=True)
class ResumeEditEvidenceResult:
    supported: bool
    unsupported_claims: tuple[str, ...] = ()
    reason: str = ""
    failure_code: str = ""


class ResumeEditEvidenceValidator(Protocol):
    def validate(self, request: ResumeEditEvidenceRequest) -> ResumeEditEvidenceResult: ...


class _EvidenceVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool
    unsupported_claims: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


def _submit_resume_edit_evidence(**payload: Any) -> dict:
    return _EvidenceVerdict(**payload).model_dump()


_SUBMIT_TOOL = StructuredTool.from_function(
    func=_submit_resume_edit_evidence,
    name="submit_resume_edit_evidence_verdict",
    description=(
        "Submit whether every material factual claim in one proposed resume rewrite "
        "is entailed by the supplied candidate evidence."
    ),
    args_schema=_EvidenceVerdict,
)


_SYSTEM_PROMPT = f"""You are an independent resume evidence verifier.
Judge only whether every material factual claim in the proposed rewrite is directly
entailed by the supplied candidate evidence. The job posting, desired keywords, and
common industry practice are never candidate evidence.

Return supported=true only when all responsibilities, methods, outcomes, scope,
seniority, tools, and operating contexts in the rewrite are established by the evidence.
Related experience and lexical overlap are not proof. A rewrite may paraphrase or shorten
the evidence, but it may not add a plausible detail.

When unsupported, list each shortest unsupported claim and explain the evidence gap.
When supported, return an empty unsupported_claims list. Use the required tool once and
do not reveal private reasoning.

{UNTRUSTED_DATA_RULE}"""


class LangChainResumeEditEvidenceValidator:
    """Fail closed on one independent structured evidence review."""

    def __init__(self, model=None, telemetry: RecruitmentTelemetry | None = None):
        if model is not None and not hasattr(model, "bind_tools"):
            raise TypeError("Resume edit evidence model must support bind_tools")
        self._model = model
        self._telemetry = telemetry or OpenTelemetryRecorder()

    def _bound_model(self):
        if self._model is None:
            self._model = create_observed_agent_model(
                self._telemetry,
                role="resume_edit_evidence",
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
                model=config.COORDINATOR_MODEL,
                max_completion_tokens=config.RECRUITMENT_EDIT_EVIDENCE_MAX_TOKENS,
            )
        return self._model.bind_tools(
            [_SUBMIT_TOOL],
            tool_choice=_SUBMIT_TOOL.name,
        )

    def validate(self, request: ResumeEditEvidenceRequest) -> ResumeEditEvidenceResult:
        evidence = {
            "prompt_version": RESUME_EDIT_EVIDENCE_PROMPT_VERSION,
            "original_block": request.original,
            "cited_candidate_evidence": request.supporting_evidence,
            "proposed_rewrite": request.rewrite,
        }
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=xml_data_block(
                    "resume_edit_evidence",
                    json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                )
            ),
        ]
        with self._telemetry.operation(
            "resume_edit_evidence.model",
            {"prompt_version": RESUME_EDIT_EVIDENCE_PROMPT_VERSION},
        ) as span:
            try:
                with transport_role("resume_edit_evidence"):
                    response = self._bound_model().invoke(messages)
            except Exception as error:
                span.set_attribute("status", "error")
                span.set_attribute("error_type", type(error).__name__)
                return ResumeEditEvidenceResult(
                    supported=False,
                    reason="Independent evidence review was unavailable; the edit was not drafted.",
                    failure_code=f"transport:{type(error).__name__}",
                )
            call = next(
                (call for call in response.tool_calls if call.get("name") == _SUBMIT_TOOL.name),
                None,
            )
            if call is None:
                span.set_attribute("status", "invalid")
                return ResumeEditEvidenceResult(
                    supported=False,
                    reason="Independent evidence review returned no verdict; the edit was not drafted.",
                    failure_code="missing_tool_call",
                )
            try:
                verdict = _SUBMIT_TOOL.invoke(call.get("args") or {})
            except Exception:
                span.set_attribute("status", "invalid")
                return ResumeEditEvidenceResult(
                    supported=False,
                    reason="Independent evidence review returned an invalid verdict; the edit was not drafted.",
                    failure_code="schema_validation",
                )
            unsupported_claims = tuple(
                dict.fromkeys(claim.strip() for claim in verdict["unsupported_claims"] if claim.strip())
            )
            supported = bool(verdict["supported"]) and not unsupported_claims
            if not verdict["supported"] and not unsupported_claims:
                span.set_attribute("status", "invalid")
                return ResumeEditEvidenceResult(
                    supported=False,
                    reason="Independent evidence review named no supportable verdict; the edit was not drafted.",
                    failure_code="inconsistent_verdict",
                )
            span.set_attribute("status", "supported" if supported else "unsupported")
            return ResumeEditEvidenceResult(
                supported=supported,
                unsupported_claims=unsupported_claims,
                reason=str(verdict["reason"]).strip(),
            )
