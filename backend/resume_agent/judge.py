"""Independent quality judge for the final resume assessment."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

import config
from prompt_safety import xml_data_block

from .models import create_smart_model
from .prompts import JUDGE_WEAKNESS_CATEGORIES, build_judge_system_prompt
from .tracing import ToolSpanRecorder


log = logging.getLogger("jobhunter.resume_agent")


class _JudgeStrength(BaseModel):
    finding: str
    source: str
    confidence: float = Field(ge=0, le=1)
    confidence_basis: str


class _JudgeWeakness(_JudgeStrength):
    category: Literal[
        "evidence_fidelity",
        "source_attribution",
        "required_structure",
        "coverage",
        "usefulness",
        "clarity",
    ]
    severity: Literal["blocking", "non_blocking"]


class _JudgeSubmission(BaseModel):
    verdict: str
    strengths: list[_JudgeStrength]
    weaknesses: list[_JudgeWeakness]
    score: int = Field(ge=0, le=100)
    reasoning: str
    evidence_gaps: list[str] = Field(default_factory=list)


def _submit_quality_judgment(**payload: Any) -> dict:
    """Submit one evidence-cited quality judgment for the final assessment."""
    return _JudgeSubmission(**payload).model_dump()


_SUBMIT_QUALITY_JUDGMENT_TOOL = StructuredTool.from_function(
    func=_submit_quality_judgment,
    name="submit_quality_judgment",
    description=(
        "Submit the independent quality verdict with evidence-cited strengths, "
        "weaknesses, score, score reasoning, confidence bases, and evidence gaps."
    ),
    args_schema=_JudgeSubmission,
)


def _parse(raw: str | dict, allowed_sources: set[str]) -> tuple[dict | None, str]:
    if isinstance(raw, dict):
        value = raw
    else:
        cleaned = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            return None, "missing_tool_call"
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None, "invalid_json"
    if not isinstance(value, dict):
        return None, "invalid_object"
    if not isinstance(value.get("score"), int) or isinstance(value.get("score"), bool):
        return None, "invalid_score"
    if not 0 <= value["score"] <= 100:
        return None, "invalid_score"
    if not all(isinstance(value.get(key), str) and value[key].strip() for key in ("verdict", "reasoning")):
        return None, "missing_required_text"
    for key in ("strengths", "weaknesses"):
        items = value.get(key)
        if not isinstance(items, list) or not items:
            return None, f"invalid_{key}"
        for item in items:
            if not isinstance(item, dict) or not str(item.get("finding") or "").strip():
                return None, f"invalid_{key}"
            if item.get("source") not in allowed_sources:
                return None, "invalid_source"
            confidence = item.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                return None, "invalid_confidence"
            if not isinstance(item.get("confidence_basis"), str) or not item["confidence_basis"].strip():
                return None, "missing_confidence_basis"
            if key == "weaknesses":
                if item.get("category") not in JUDGE_WEAKNESS_CATEGORIES:
                    return None, "invalid_weakness_category"
                if item.get("severity") not in {"blocking", "non_blocking"}:
                    return None, "invalid_weakness_severity"
    gaps = value.get("evidence_gaps")
    if not isinstance(gaps, list) or not all(isinstance(gap, str) for gap in gaps):
        return None, "invalid_evidence_gaps"
    return {
        "verdict": value["verdict"].strip(),
        "requires_revision": any(item["severity"] == "blocking" for item in value["weaknesses"]),
        "strengths": [
            {
                "finding": item["finding"].strip(),
                "source": item["source"],
                "confidence": round(float(item["confidence"]), 2),
                "confidence_basis": item["confidence_basis"].strip(),
            }
            for item in value["strengths"]
        ],
        "weaknesses": [
            {
                "finding": item["finding"].strip(),
                "category": item["category"],
                "severity": item["severity"],
                "source": item["source"],
                "confidence": round(float(item["confidence"]), 2),
                "confidence_basis": item["confidence_basis"].strip(),
            }
            for item in value["weaknesses"]
        ],
        "score": value["score"],
        "reasoning": value["reasoning"].strip(),
        "evidence_gaps": [gap.strip() for gap in gaps if gap.strip()],
    }, ""


def _model_failure(exc: Exception) -> tuple[str, bool]:
    name = type(exc).__name__
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        return "authentication", False
    if name == "RateLimitError":
        return "rate_limit", True
    if name in {"APITimeoutError", "ReadTimeout", "TimeoutException"}:
        return "timeout", True
    if name in {"APIConnectionError", "InternalServerError"}:
        return "unavailable", True
    return "model", False


def judge_assessment(
    final_assessment: str,
    persona_findings: list[dict],
    worker_runs: list[dict],
    *,
    resume_evidence: dict,
    job_context: dict,
    trace_id: str,
    model: Any | None = None,
) -> dict:
    """Grade a synthesis independently and return a terminal run envelope."""
    started_at = time.perf_counter()
    reviewers = {str(finding.get("persona")) for finding in persona_findings if finding.get("persona")}
    failed = {str(run.get("persona")) for run in worker_runs if run.get("status") != "success" and run.get("persona")}
    allowed_sources = {
        "final_assessment",
        "resume_evidence",
        "target_job",
        *(f"reviewer:{name}" for name in reviewers),
        *(f"worker_failure:{name}" for name in failed),
    }
    evidence = [
        {
            "persona": finding.get("persona"),
            "summary": finding.get("summary"),
            "findings": [
                {
                    key: item.get(key)
                    for key in (
                        "kind",
                        "finding",
                        "source",
                        "source_location",
                        "confidence",
                    )
                }
                for item in (finding.get("findings") or [])
                if isinstance(item, dict)
            ],
            "conflicts": finding.get("conflicts"),
            "score": finding.get("score"),
            "reasoning": finding.get("reasoning"),
        }
        for finding in persona_findings
    ]
    failures = [
        {key: run.get(key) for key in ("persona", "failure_type", "remaining_gap", "retryable")}
        for run in worker_runs
        if run.get("status") != "success"
    ]
    system_prompt = build_judge_system_prompt(allowed_sources)
    user_prompt = "\n\n".join(
        (
            xml_data_block("final_assessment_data", final_assessment),
            xml_data_block(
                "resume_evidence_data", json.dumps(resume_evidence, ensure_ascii=False, separators=(",", ":"))
            ),
            xml_data_block("target_job_data", json.dumps(job_context, ensure_ascii=False, separators=(",", ":"))),
            xml_data_block("reviewer_findings_data", json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))),
            xml_data_block("worker_failures_data", json.dumps(failures, ensure_ascii=False, separators=(",", ":"))),
        )
    )
    try:
        active_model = model or create_smart_model()
        if not hasattr(active_model, "bind_tools"):
            raise TypeError("Quality judge models must support bind_tools")
    except Exception as exc:
        reason = f"model_error:{type(exc).__name__}"
        failure_type, retryable = _model_failure(exc)
        log.warning(
            "resume_agent_judge_problem %s",
            json.dumps(
                {
                    "trace_id": trace_id,
                    "failure_type": failure_type,
                    "attempt_count": 0,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                    "error_code": reason,
                },
                separators=(",", ":"),
            ),
        )
        return {
            "status": "error",
            "failure_type": failure_type,
            "attempted_operation": "grade final resume assessment",
            "attempt_count": 0,
            "partial_results": [],
            "local_recovery_attempts": [],
            "remaining_gap": "The quality of the final write-up was not independently graded.",
            "suggested_alternatives": ["Retry the quality judge after model access is restored."],
            "retryable": retryable,
            "duration_ms": round((time.perf_counter() - started_at) * 1000),
            "tool_spans": [],
            "error": {"code": reason, "message": "The quality judge could not start."},
        }
    spans: list[dict] = []
    reason = ""
    failure_type = "validation"
    retryable = True
    attempted = 0
    recovery_attempts = []
    failed_output = ""
    for attempt in range(1, config.AGENT_JUDGE_VALIDATION_ATTEMPTS + 1):
        attempted = attempt
        recorder = ToolSpanRecorder("quality_judge", trace_id=trace_id, attempt=attempt)
        recorder.set_phase("assessment_quality_judge")
        correction = (
            ""
            if not reason
            else (
                f"\n\nYour prior output failed validation with code {reason}. "
                "Re-examine the original assessment and reviewer evidence above, correct the JSON, "
                "and re-check every source against the allowed source list. Weakness category must "
                f"be one of {', '.join(sorted(JUDGE_WEAKNESS_CATEGORIES))}.\n\n"
                + xml_data_block("failed_judge_output_data", failed_output)
            )
        )
        try:
            response = active_model.bind_tools(
                [_SUBMIT_QUALITY_JUDGMENT_TOOL],
                tool_choice=_SUBMIT_QUALITY_JUDGMENT_TOOL.name,
            ).invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt + correction)],
                config={"callbacks": [recorder]},
            )
            call = next(
                (
                    call
                    for call in getattr(response, "tool_calls", [])
                    if call.get("name") == _SUBMIT_QUALITY_JUDGMENT_TOOL.name
                ),
                None,
            )
            failed_output = json.dumps(
                (call or {}).get("args") or {"content": str(getattr(response, "content", "") or "")},
                ensure_ascii=False,
            )
            if call is None:
                parsed, reason = None, "missing_tool_call"
            else:
                submitted = call.get("args") or {}
                parsed, reason = _parse(submitted, allowed_sources)
                if parsed:
                    _SUBMIT_QUALITY_JUDGMENT_TOOL.invoke(
                        submitted,
                        config={"callbacks": [recorder]},
                    )
        except Exception as exc:
            parsed = None
            reason = f"model_error:{type(exc).__name__}"
            failure_type, retryable = _model_failure(exc)
        spans.extend(recorder.spans)
        if parsed:
            parsed["duration_ms"] = round((time.perf_counter() - started_at) * 1000)
            parsed["trace_id"] = trace_id
            for item in [*parsed["strengths"], *parsed["weaknesses"]]:
                item.update(
                    {
                        "trace_id": trace_id,
                        "worker": "quality_judge",
                        "attempt": attempt,
                    }
                )
            return {
                "status": "success",
                "attempt_count": attempt,
                "assessment": parsed,
                "tool_spans": spans,
                "error": None,
            }
        log.warning(
            "resume_agent_judge_attempt_problem %s",
            json.dumps(
                {
                    "trace_id": trace_id,
                    "attempt": attempt,
                    "error_code": reason,
                },
                separators=(",", ":"),
            ),
        )
        recovery_attempts.append(
            {
                "attempt": attempt,
                "outcome": "failed",
                "failure": reason,
            }
        )
        if reason.startswith("model_error:") and not retryable:
            break
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    run = {
        "status": "error",
        "failure_type": failure_type if reason.startswith("model_error:") else "validation",
        "attempted_operation": "grade final resume assessment",
        "attempt_count": attempted,
        "partial_results": [],
        "local_recovery_attempts": recovery_attempts,
        "remaining_gap": "The quality of the final write-up was not independently graded.",
        "suggested_alternatives": ["Retry the quality judge while preserving the completed review."],
        "retryable": retryable,
        "duration_ms": duration_ms,
        "tool_spans": spans,
        "error": {"code": reason, "message": "The quality judge did not return a valid assessment."},
    }
    log.warning(
        "resume_agent_judge_problem %s",
        json.dumps(
            {
                "trace_id": trace_id,
                "failure_type": run["failure_type"],
                "attempt_count": run["attempt_count"],
                "duration_ms": duration_ms,
                "error_code": reason,
            },
            separators=(",", ":"),
        ),
    )
    return run
