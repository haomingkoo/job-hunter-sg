"""Independent quality judge for the final resume assessment."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from prompt_safety import xml_data_block

from .models import create_smart_model
from .tracing import ToolSpanRecorder


log = logging.getLogger("jobhunter.resume_agent")
MAX_JUDGE_ATTEMPTS = 2
_RUBRIC = """Score the assessment, not the candidate, out of 100:
- evidence fidelity, confidence calibration, and accurate citations: 30
- balanced coverage of material strengths and weaknesses: 20
- honest disclosure of unavailable evidence and failed worker coverage: 20
- specificity and practical usefulness: 15
- clear, concise, non-duplicative structure: 15
Do not use or reward conclusions based on protected or demographic attributes.
Do not reward confident language when the supplied evidence does not support it."""
_OUTPUT = """Return only this JSON object:
{"verdict":"one-sentence quality conclusion","strengths":[{"finding":"assessment strength","source":"final_assessment","confidence":0.9,"confidence_basis":"directly visible in the final write-up"}],"weaknesses":[{"finding":"assessment weakness","source":"reviewer:ats","confidence":0.8,"confidence_basis":"the cited reviewer finding is absent from the synthesis"}],"score":80,"reasoning":"concise score rationale and largest deductions","evidence_gaps":["unavailable or unverified item"]}
Each source must be final_assessment, reviewer:<supplied persona>, or
worker_failure:<supplied persona>. Include at least one strength and one weakness.
The score must be an integer from 0 to 100. Use an empty evidence_gaps list only
when no evidence or specialist coverage is unavailable. Confidence is field-level
evidence support from 0 to 1 and requires a concise confidence_basis."""


def _parse(raw: str, allowed_sources: set[str]) -> tuple[dict | None, str]:
    cleaned = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        return None, "invalid_json"
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
    gaps = value.get("evidence_gaps")
    if not isinstance(gaps, list) or not all(isinstance(gap, str) for gap in gaps):
        return None, "invalid_evidence_gaps"
    return {
        "verdict": value["verdict"].strip(),
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
    trace_id: str,
    model: Any | None = None,
) -> dict:
    """Grade a synthesis independently and return a terminal run envelope."""
    started_at = time.perf_counter()
    reviewers = {
        str(finding.get("persona"))
        for finding in persona_findings
        if finding.get("persona")
    }
    failed = {
        str(run.get("persona"))
        for run in worker_runs
        if run.get("status") != "success" and run.get("persona")
    }
    allowed_sources = {
        "final_assessment",
        *(f"reviewer:{name}" for name in reviewers),
        *(f"worker_failure:{name}" for name in failed),
    }
    evidence = [{
        key: finding.get(key)
        for key in ("persona", "summary", "findings", "conflicts", "score", "reasoning")
    } for finding in persona_findings]
    failures = [{
        key: run.get(key)
        for key in ("persona", "failure_type", "remaining_gap", "retryable")
    } for run in worker_runs if run.get("status") != "success"]
    system_prompt = (
        "You are an independent quality judge. Grade the final resume-review write-up "
        "against the supplied reviewer evidence. Do not reassess the candidate and do "
        "not invent missing facts. First check evidence fidelity, then coverage, honesty, "
        "usefulness, clarity, and fairness.\n\n"
        f"<rubric>\n{_RUBRIC}\n</rubric>\n\n"
        f"<output_contract>\n{_OUTPUT}\n</output_contract>\n\n"
        "Before returning, verify the arithmetic, citations, both assessment strengths "
        "and weaknesses, and explicit treatment of unavailable evidence."
    )
    user_prompt = "\n\n".join((
        xml_data_block("final_assessment_data", final_assessment),
        xml_data_block("reviewer_findings_data", json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))),
        xml_data_block("worker_failures_data", json.dumps(failures, ensure_ascii=False, separators=(",", ":"))),
    ))
    try:
        active_model = model or create_smart_model()
    except Exception as exc:
        reason = f"model_error:{type(exc).__name__}"
        failure_type, retryable = _model_failure(exc)
        log.warning("resume_agent_judge_problem %s", json.dumps({
            "trace_id": trace_id,
            "failure_type": failure_type,
            "attempt_count": 0,
            "duration_ms": round((time.perf_counter() - started_at) * 1000),
            "error_code": reason,
        }, separators=(",", ":")))
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
    for attempt in range(1, MAX_JUDGE_ATTEMPTS + 1):
        attempted = attempt
        recorder = ToolSpanRecorder("quality_judge", trace_id=trace_id, attempt=attempt)
        recorder.set_phase("assessment_quality_judge")
        correction = "" if not reason else (
            f"\n\nYour prior output failed validation with code {reason}. "
            "Correct the JSON and re-check every source against the allowed source list."
        )
        try:
            response = active_model.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt + correction)],
                config={"callbacks": [recorder]},
            )
            parsed, reason = _parse(str(getattr(response, "content", "") or ""), allowed_sources)
        except Exception as exc:
            parsed = None
            reason = f"model_error:{type(exc).__name__}"
            failure_type, retryable = _model_failure(exc)
        spans.extend(recorder.spans)
        if parsed:
            parsed["duration_ms"] = round((time.perf_counter() - started_at) * 1000)
            parsed["trace_id"] = trace_id
            for item in [*parsed["strengths"], *parsed["weaknesses"]]:
                item.update({
                    "trace_id": trace_id,
                    "worker": "quality_judge",
                    "attempt": attempt,
                })
            return {
                "status": "success",
                "attempt_count": attempt,
                "assessment": parsed,
                "tool_spans": spans,
                "error": None,
            }
        log.warning("resume_agent_judge_attempt_problem %s", json.dumps({
            "trace_id": trace_id,
            "attempt": attempt,
            "error_code": reason,
        }, separators=(",", ":")))
        recovery_attempts.append({
            "attempt": attempt,
            "outcome": "failed",
            "failure": reason,
        })
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
    log.warning("resume_agent_judge_problem %s", json.dumps({
        "trace_id": trace_id,
        "failure_type": run["failure_type"],
        "attempt_count": run["attempt_count"],
        "duration_ms": duration_ms,
        "error_code": reason,
    }, separators=(",", ":")))
    return run
