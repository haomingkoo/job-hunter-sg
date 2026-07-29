"""Persona sub-agent definitions for Resume Deep Agent v2."""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from typing import Any, Literal, cast

import config
from deepagents.middleware.subagents import SubAgent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .models import create_agent_model
from .contracts import TARGET_JOB_PERSONAS
from .prompts import (
    REVIEWER_CONFIGS,
    REVIEWER_OUTPUT_INSTRUCTIONS,
    REVIEWER_SCORING_RUBRICS,
    build_reviewer_system_prompt,
)
from .tracing import ToolSpanRecorder
from .telemetry import operation, trace_key
from .tools import bullet_context
from prompt_safety import xml_data_block


log = logging.getLogger("jobhunter.resume_agent")


MIN_WORKER_FINDINGS = 2
MAX_WORKER_FINDINGS = 4
MAX_WORKER_ACTIONS = 2
MAX_CATEGORY_CHARS = 80
MAX_FINDING_CHARS = 700
MAX_METHOD_CHARS = 500
MAX_REASONING_CHARS = 1_600
MAX_SUMMARY_CHARS = 500
RELEVANCE_SCORE_DECIMALS = 2
MAX_SOURCE_EXCERPT_CHARS = 500

_PERSONAS = REVIEWER_CONFIGS
_PERSONA_BY_NAME = {name: (description, prompt) for name, description, prompt in _PERSONAS}
_SCORING_RUBRICS = REVIEWER_SCORING_RUBRICS
_OUTPUT_INSTRUCTIONS = REVIEWER_OUTPUT_INSTRUCTIONS


class _FindingSubmission(BaseModel):
    kind: Literal["strength", "weakness"]
    finding: str
    source: Literal["resume", "target_job", "internal_job"]
    source_location: str
    method: str
    relevance_score: float
    confidence: float | None = None
    confidence_basis: str | None = None


class _ConflictValueSubmission(BaseModel):
    value: str | int | float
    source: Literal["resume", "target_job", "internal_job"]
    source_location: str
    measurement_date: str | None = None
    scope: str | None = None


class _ConflictSubmission(BaseModel):
    topic: str
    status: Literal["conflict"]
    values: list[_ConflictValueSubmission]
    possible_explanation: str | None = None


class _AssessmentSubmission(BaseModel):
    summary: str
    category: str
    findings: list[_FindingSubmission]
    conflicts: list[_ConflictSubmission] = Field(default_factory=list)
    research_job_ids: list[int] = Field(default_factory=list)
    score: int
    reasoning: str
    suggested_actions: list[str]


def _submit_assessment(**payload: Any) -> dict:
    """Submit the final reviewer assessment using the required JSON schema."""

    def plain(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump()
        if isinstance(value, list):
            return [plain(item) for item in value]
        if isinstance(value, dict):
            return {key: plain(item) for key, item in value.items()}
        return value

    return plain(payload)


_SUBMIT_ASSESSMENT_TOOL = StructuredTool.from_function(
    func=_submit_assessment,
    name="submit_assessment",
    description="Submit one final evidence-bound reviewer assessment.",
    args_schema=_AssessmentSubmission,
)


_worker_system_prompt = build_reviewer_system_prompt


def create_persona_subagents(smart_model: Any | None = None) -> list[SubAgent]:
    """Return least-privilege persona worker specifications."""
    model = smart_model or create_agent_model()
    subagents = []
    assert tuple(name for name, _description, _prompt in _PERSONAS) == TARGET_JOB_PERSONAS
    for name, description, prompt in _PERSONAS:
        subagents.append(
            cast(
                SubAgent,
                {
                    "name": name,
                    "description": description,
                    "system_prompt": _worker_system_prompt(name, prompt),
                    "tools": [_SUBMIT_ASSESSMENT_TOOL],
                    "model": model,
                },
            )
        )
    return subagents


def parse_persona_output(raw: str) -> dict:
    """Parse SMART persona JSON after removing reasoning wrappers."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}

    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_mapping(
    source: str,
    source_location: str,
    document: dict,
    job_context: dict | None,
) -> dict:
    excerpt: str | None = None
    name = "Internal job search result"
    if source == "resume":
        name = "Uploaded resume"
        block = next((block for block in document.get("blocks", []) if str(block.get("id")) == source_location), None)
        excerpt = str((block or {}).get("text") or "") or None
    elif source == "target_job":
        name = "Selected job snapshot"
        value = (job_context or {}).get(source_location)
        if value is not None:
            excerpt = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    original_length = len(excerpt) if excerpt else 0
    display_excerpt = excerpt[:MAX_SOURCE_EXCERPT_CHARS] if excerpt else None
    excerpt_truncated = original_length > MAX_SOURCE_EXCERPT_CHARS
    return {
        "type": source,
        "name": name,
        "url": None,
        "location": source_location,
        "relevant_excerpt": excerpt if excerpt and not excerpt_truncated else None,
        "evidence_reference": {
            "type": source,
            "location": source_location,
        },
        "display_excerpt": display_excerpt,
        "excerpt_truncated": excerpt_truncated,
        "original_length": original_length,
        "display_length": len(display_excerpt) if display_excerpt else 0,
        "publication_date": None,
        "data_period": None,
    }


def _validated_finding(
    name: str,
    parsed: dict,
    document: dict,
    job_context: dict | None,
    recorder: ToolSpanRecorder | None = None,
) -> tuple[dict | None, str]:
    if not parsed:
        return None, "invalid_json"

    valid_ids = {str(block.get("id")) for block in document.get("blocks", [])}
    allowed_job_fields = {
        key for key in (job_context or {}) if key in {"title", "company", "description", "terms", "location", "source"}
    }
    category = str(parsed.get("category") or "").strip()
    summary = str(parsed.get("summary") or "").strip()
    findings = parsed.get("findings")
    conflicts = parsed.get("conflicts", [])
    declared_research_job_ids = parsed.get("research_job_ids", [])
    suggested_actions = parsed.get("suggested_actions")
    reasoning = str(parsed.get("reasoning") or "").strip()
    score = parsed.get("score")
    if not isinstance(findings, list) or not MIN_WORKER_FINDINGS <= len(findings) <= MAX_WORKER_FINDINGS:
        return None, "invalid_findings"
    if not isinstance(conflicts, list):
        return None, "invalid_conflicts"
    if not isinstance(declared_research_job_ids, list) or any(
        isinstance(job_id, bool) or not isinstance(job_id, int) for job_id in declared_research_job_ids
    ):
        return None, "invalid_research_job_ids"
    if recorder is not None and any(job_id not in recorder.source_job_ids for job_id in declared_research_job_ids):
        return None, "unknown_research_job_id"
    if (
        not isinstance(suggested_actions, list)
        or not suggested_actions
        or not all(isinstance(v, str) and v.strip() for v in suggested_actions)
    ):
        return None, "invalid_suggested_actions"
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        return None, "invalid_score"
    if not summary or not category or not reasoning:
        return None, "missing_required_text"
    if len(category) > MAX_CATEGORY_CHARS:
        return None, "oversized_category"
    if len(summary) > MAX_SUMMARY_CHARS:
        return None, "oversized_summary"
    if len(reasoning) > MAX_REASONING_CHARS:
        return None, "oversized_reasoning"

    clean_findings = []
    for item in findings:
        if not isinstance(item, dict):
            return None, "invalid_finding"
        kind = str(item.get("kind") or "")
        finding_text = str(item.get("finding") or "").strip()
        source = str(item.get("source") or "")
        source_location = str(item.get("source_location") or "")
        method = str(item.get("method") or "").strip()
        relevance_score = item.get("relevance_score")
        confidence = item.get("confidence")
        confidence_basis = str(item.get("confidence_basis") or "").strip()
        if kind not in {"strength", "weakness"} or not finding_text or not method:
            return None, "invalid_finding_fields"
        if len(finding_text) > MAX_FINDING_CHARS:
            return None, "oversized_finding"
        if len(method) > MAX_METHOD_CHARS:
            return None, "oversized_method"
        if len(confidence_basis) > MAX_METHOD_CHARS:
            return None, "oversized_confidence_basis"
        if (
            isinstance(relevance_score, bool)
            or not isinstance(relevance_score, (int, float))
            or not 0 <= relevance_score <= 1
        ):
            return None, "invalid_relevance_score"
        if confidence is not None and (
            isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1
        ):
            return None, "invalid_confidence"
        if confidence is not None and not confidence_basis:
            return None, "missing_confidence_basis"
        if source == "resume" and source_location not in valid_ids:
            return None, "unknown_evidence_id"
        if source == "target_job" and source_location not in allowed_job_fields:
            return None, "unknown_target_job_field"
        if source == "internal_job":
            try:
                source_job_id = int(source_location)
            except ValueError:
                return None, "invalid_research_job_id"
            if recorder is None or source_job_id not in recorder.source_job_ids:
                return None, "unknown_research_job_id"
        elif source not in {"resume", "target_job"}:
            return None, "invalid_source"
        clean_findings.append(
            {
                "kind": kind,
                "finding": finding_text,
                "source": source,
                "source_location": source_location,
                "method": method,
                "relevance_score": round(float(relevance_score), RELEVANCE_SCORE_DECIMALS),
                "confidence": (round(float(confidence), RELEVANCE_SCORE_DECIMALS) if confidence is not None else None),
                "confidence_basis": confidence_basis or "Confidence was not reported by this reviewer.",
                "source_mapping": _source_mapping(
                    source,
                    source_location,
                    document,
                    job_context,
                ),
            }
        )

    clean_conflicts = []
    for conflict in conflicts:
        if not isinstance(conflict, dict) or conflict.get("status") != "conflict":
            return None, "invalid_conflict"
        topic = str(conflict.get("topic") or "").strip()
        values = conflict.get("values")
        if not topic or not isinstance(values, list) or len(values) < 2:
            return None, "invalid_conflict_values"
        if len(topic) > MAX_CATEGORY_CHARS:
            return None, "oversized_conflict_topic"
        clean_values = []
        for value in values:
            if (
                not isinstance(value, dict)
                or isinstance(value.get("value"), bool)
                or not isinstance(value.get("value"), (str, int, float))
            ):
                return None, "invalid_conflict_value"
            if value.get("measurement_date") is not None and not isinstance(value.get("measurement_date"), str):
                return None, "invalid_conflict_measurement_date"
            if value.get("scope") is not None and not isinstance(value.get("scope"), str):
                return None, "invalid_conflict_scope"
            if isinstance(value["value"], str) and len(value["value"]) > MAX_FINDING_CHARS:
                return None, "oversized_conflict_value"
            if value.get("measurement_date") and len(value["measurement_date"]) > MAX_CATEGORY_CHARS:
                return None, "oversized_conflict_measurement_date"
            if value.get("scope") and len(value["scope"]) > MAX_METHOD_CHARS:
                return None, "oversized_conflict_scope"
            value_source = str(value.get("source") or "")
            value_location = str(value.get("source_location") or "")
            if value_source == "resume" and value_location not in valid_ids:
                return None, "unknown_conflict_evidence_id"
            if value_source == "target_job" and value_location not in allowed_job_fields:
                return None, "unknown_conflict_job_field"
            if value_source == "internal_job":
                try:
                    conflict_job_id = int(value_location)
                except ValueError:
                    return None, "invalid_conflict_job_id"
                if recorder is None or conflict_job_id not in recorder.source_job_ids:
                    return None, "unknown_conflict_job_id"
            elif value_source not in {"resume", "target_job"}:
                return None, "invalid_conflict_source"
            clean_values.append(
                {
                    "value": value["value"],
                    "source_mapping": _source_mapping(
                        value_source,
                        value_location,
                        document,
                        job_context,
                    ),
                    "measurement_date": value.get("measurement_date"),
                    "scope": value.get("scope"),
                }
            )
        possible_explanation = str(conflict.get("possible_explanation") or "").strip()
        if len(possible_explanation) > MAX_METHOD_CHARS:
            return None, "oversized_conflict_explanation"
        clean_conflicts.append(
            {
                "topic": topic,
                "status": "conflict",
                "values": clean_values,
                "possible_explanation": possible_explanation,
            }
        )

    clean_strengths = [item["finding"] for item in clean_findings if item["kind"] == "strength"]
    clean_weaknesses = [item["finding"] for item in clean_findings if item["kind"] == "weakness"]
    if not clean_strengths or not clean_weaknesses:
        return None, "missing_strength_or_weakness"
    evidence_ids = list(dict.fromkeys(item["source_location"] for item in clean_findings if item["source"] == "resume"))
    target_job_fields = list(
        dict.fromkeys(item["source_location"] for item in clean_findings if item["source"] == "target_job")
    )
    research_job_ids = list(
        dict.fromkeys(
            [
                *declared_research_job_ids,
                *(int(str(item["source_location"])) for item in clean_findings if item["source"] == "internal_job"),
            ]
        )
    )
    if name == "market_researcher" and job_context and not target_job_fields and not research_job_ids:
        return None, "missing_job_citation"
    if (
        recorder is not None
        and name in {"hiring_manager", "market_researcher"}
        and recorder.source_job_ids
        and not research_job_ids
    ):
        return None, "missing_research_citation"

    if len(suggested_actions) > MAX_WORKER_ACTIONS:
        return None, "too_many_suggested_actions"
    clean_actions = [str(value).strip() for value in suggested_actions]
    if any(len(value) > MAX_FINDING_CHARS for value in clean_actions):
        return None, "oversized_suggested_action"

    return {
        "persona": name,
        "summary": summary,
        "category": category,
        "findings": clean_findings,
        "conflicts": clean_conflicts,
        "strengths": clean_strengths,
        "weaknesses": clean_weaknesses,
        "score": score,
        "evidence_ids": [str(item) for item in evidence_ids],
        "target_job_fields": [str(item) for item in target_job_fields],
        "research_job_ids": research_job_ids,
        "message": clean_weaknesses[0],
        "reasoning": reasoning,
        "rationale": reasoning,
        "suggested_actions": clean_actions,
        "suggested_action": clean_actions[0],
        "tool_spans": list(recorder.spans) if recorder is not None else [],
    }, ""


def _submitted_assessment(response: AIMessage, recorder: ToolSpanRecorder) -> str:
    call = next((call for call in response.tool_calls if call.get("name") == _SUBMIT_ASSESSMENT_TOOL.name), None)
    if call is None:
        content = str(response.content or "")
        try:
            json.loads(content)
        except json.JSONDecodeError:
            return content
        return json.dumps({"invalid_submission_content": content})
    result = _SUBMIT_ASSESSMENT_TOOL.invoke(
        call.get("args") or {},
        config={"callbacks": [recorder]},
    )
    return json.dumps(result, ensure_ascii=False, default=str)


def _invoke_worker(model: Any, name: str, system_prompt: str, user_prompt: str, recorder: ToolSpanRecorder) -> str:
    """Run one isolated worker with one schema-enforced model call."""
    if not hasattr(model, "bind_tools"):
        raise TypeError("Resume reviewer models must support bind_tools")

    messages = [
        SystemMessage(content=f"Persona: {name}\n{system_prompt}"),
        HumanMessage(content=user_prompt),
    ]
    recorder.set_phase("assessment")
    assessment = model.bind_tools(
        [_SUBMIT_ASSESSMENT_TOOL],
        tool_choice=_SUBMIT_ASSESSMENT_TOOL.name,
    ).invoke(messages, config={"callbacks": [recorder]})
    return _submitted_assessment(assessment, recorder)


def _error_stage(reason: str) -> str:
    if reason.startswith("model_error:"):
        return "model"
    if "tool" in reason:
        return "tool"
    if any(term in reason for term in ("source", "citation", "evidence", "job_id", "job_field")):
        return "citation"
    return "validation"


def _retry_feedback(reason: str, failed_output: str) -> str:
    detail = {
        "unknown_target_job_field": (
            "For target_job findings, source_location must be exactly one of: "
            "title, company, description, terms, location, source."
        ),
        "unknown_evidence_id": (
            "For resume findings, source_location must exactly match a canonical ID from resume_evidence_data."
        ),
        "invalid_json": "Return the assessment through the required structured submission tool.",
    }.get(reason, "Correct the rejected field while preserving all supported evidence.")
    return (
        "<retry_feedback>\n"
        f"Your prior response failed at {_error_stage(reason)} with code: {reason}. "
        f"{detail} Re-examine the original evidence above and the rejected extraction below. "
        "Resubmit the structured assessment, correct only what failed, and self-verify the complete result.\n"
        "</retry_feedback>\n\n" + xml_data_block("failed_extraction_data", failed_output)
    )


def _retryable_exception(exc: Exception) -> bool:
    return type(exc).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
        "ReadTimeout",
        "TimeoutException",
    }


def _failure_alternatives(stage: str) -> list[str]:
    if stage == "model":
        return [
            "Retry the reviewer after the model service recovers.",
            "Continue with completed reviewers and label the assessment incomplete.",
        ]
    if stage == "tool":
        return [
            "Rerun the reviewer's structured submission.",
            "Inspect the tool trace for a rejected structured input.",
            "Continue with completed reviewers and label the missing specialist lens.",
        ]
    if stage == "citation":
        return [
            "Regenerate using only supplied resume blocks and tool-returned job IDs.",
            "Use the selected-job snapshot when the current internal job row is unavailable.",
        ]
    return [
        "Regenerate the structured output from the supplied evidence.",
        "Continue with completed reviewers and label the assessment incomplete.",
    ]


def _partial_tool_results(spans: list[dict]) -> list[dict]:
    return [
        {
            "tool": span.get("name"),
            "status": span.get("status"),
            "result": span.get("result", {}),
        }
        for span in spans
        if span.get("kind", "tool") == "tool" and span.get("status") in {"success", "error"}
    ]


def _optional_tool_failures(spans: list[dict]) -> list[dict]:
    return [
        span
        for span in spans
        if span.get("kind", "tool") == "tool"
        and span.get("name") != _SUBMIT_ASSESSMENT_TOOL.name
        and (span.get("status") == "error" or span.get("result", {}).get("ok") is False)
    ]


def _failure_type(reason: str, stage: str) -> str:
    lowered = reason.lower()
    if "timeout" in lowered:
        return "timeout"
    if "ratelimit" in lowered or "rate_limit" in lowered:
        return "rate_limit"
    if "authentication" in lowered or "permission" in lowered or "unauthorized" in lowered:
        return "authentication"
    if "connection" in lowered or "unavailable" in lowered or "internalserver" in lowered:
        return "unavailable"
    return stage


def _failure_run(
    name: str,
    reason: str,
    attempts: int,
    spans: list[dict],
    *,
    stage: str | None = None,
    retryable: bool,
    message: str,
    recovery_attempts: list[dict] | None = None,
    duration_ms: int | None = None,
    trace_id: str = "",
) -> dict:
    failure_stage = stage or _error_stage(reason)
    tool_names = {str(span.get("name")) for span in spans if span.get("kind", "tool") == "tool" and span.get("name")}
    remaining_gap = (
        "The search did not complete, so we do not know whether matching jobs exist."
        if failure_stage == "tool" and "search_jobs" in tool_names
        else f"The {name.replace('_', ' ')} assessment is not validated, so its conclusions remain unknown."
    )
    run = {
        "persona": name,
        "trace_id": trace_id,
        "status": "error",
        "findings": [],
        "failure_type": _failure_type(reason, failure_stage),
        "attempted_operation": f"{name} resume assessment",
        "source": ", ".join(sorted(tool_name for tool_name in tool_names if tool_name != _SUBMIT_ASSESSMENT_TOOL.name))
        or "language model",
        "attempted_queries": list(
            dict.fromkeys(
                str(span["attempted_query"]) for span in spans if isinstance(span.get("attempted_query"), str)
            )
        ),
        "attempt_count": attempts,
        "duration_ms": duration_ms,
        "partial_results": [],
        "tool_results": _partial_tool_results(spans),
        "local_recovery_attempts": recovery_attempts or [],
        "remaining_gap": remaining_gap,
        "suggested_alternatives": _failure_alternatives(failure_stage),
        "retryable": retryable,
        "tool_spans": spans,
        "error": {
            "code": reason,
            "stage": failure_stage,
            "retryable": retryable,
            "message": message,
        },
    }
    log.warning(
        "resume_agent_problem %s",
        json.dumps(
            {
                "trace_id": trace_id,
                "worker": name,
                "status": run["status"],
                "failure_type": run["failure_type"],
                "attempted_operation": run["attempted_operation"],
                "attempt_count": attempts,
                "duration_ms": duration_ms,
                "remaining_gap": remaining_gap,
                "retryable": retryable,
                "error_code": reason,
            },
            separators=(",", ":"),
        ),
    )
    return run


def _log_attempt_problem(
    trace_id: str,
    worker: str,
    attempt: int,
    reason: str,
    spans: list[dict],
) -> None:
    log.warning(
        "resume_agent_attempt_problem %s",
        json.dumps(
            {
                "trace_id": trace_id,
                "worker": worker,
                "attempt": attempt,
                "stage": _error_stage(reason),
                "error_code": reason,
                "completed_spans": sum(1 for span in spans if span.get("status") in {"success", "error"}),
            },
            separators=(",", ":"),
        ),
    )


def _worker_run_impl(
    name: str,
    document: dict,
    model: Any | None,
    job_context: dict | None = None,
    session_id: str = "",
) -> dict:
    started_at = time.perf_counter()
    spec = _PERSONA_BY_NAME.get(name)
    if not spec:
        return _failure_run(
            name,
            "unknown_worker",
            0,
            [],
            stage="configuration",
            retryable=False,
            message="The requested reviewer is not configured.",
            duration_ms=round((time.perf_counter() - started_at) * 1000),
            trace_id=session_id,
        )
    _description, prompt = spec
    evidence = [
        {
            "id": block.get("id"),
            "kind": block.get("kind"),
            "section": block.get("section_key"),
            "text": block.get("text"),
        }
        for block in document.get("blocks", [])
        if block.get("id") and block.get("text")
    ]
    data_blocks = [
        xml_data_block(
            "resume_evidence_data",
            json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        )
    ]
    if job_context:
        data_blocks.append(
            xml_data_block(
                "target_job_data",
                json.dumps(job_context, ensure_ascii=False, separators=(",", ":")),
            )
        )
    if name in {"recruiter", "ats"}:
        data_blocks.append(
            xml_data_block(
                "resume_text_data",
                str(document.get("raw_text") or ""),
            )
        )
    active_model = model or create_agent_model()
    system_prompt = _worker_system_prompt(name, prompt)
    user_prompt = "\n\n".join(data_blocks)
    reason = ""
    failed_output = ""
    all_spans = []
    recovery_attempts = []
    for attempt in range(config.AGENT_PERSONA_VALIDATION_ATTEMPTS):
        recorder = (
            ToolSpanRecorder(worker=name, trace_id=session_id, attempt=attempt + 1)
            if hasattr(active_model, "bind_tools")
            else None
        )
        correction = "" if attempt == 0 else "\n\n" + _retry_feedback(reason, failed_output)
        try:
            with bullet_context(
                {
                    str(block.get("id")): str(block.get("text"))
                    for block in document.get("blocks", [])
                    if block.get("id") and block.get("kind") == "bullet"
                }
            ):
                raw = _invoke_worker(
                    active_model,
                    name,
                    system_prompt,
                    user_prompt + correction,
                    recorder
                    or ToolSpanRecorder(
                        name,
                        trace_id=session_id,
                        attempt=attempt + 1,
                    ),
                )
        except Exception as exc:
            if recorder:
                all_spans.extend(recorder.spans)
            is_tool_failure = False
            reason = f"model_error:{type(exc).__name__}"
            log.warning(
                "resume reviewer failed persona=%s attempt=%d reason=%s",
                name,
                attempt + 1,
                reason,
            )
            recovery_attempts.append(
                {
                    "attempt": attempt + 1,
                    "outcome": "failed",
                    "failure": reason,
                }
            )
            _log_attempt_problem(
                session_id,
                name,
                attempt + 1,
                reason,
                recorder.spans if recorder else [],
            )
            if not is_tool_failure and not _retryable_exception(exc):
                break
            continue
        if recorder:
            all_spans.extend(recorder.spans)
        parsed = parse_persona_output(raw)
        finding, reason = _validated_finding(name, parsed, document, job_context, recorder)
        if finding:
            for index, item in enumerate(finding["findings"], start=1):
                item.update(
                    {
                        "claim_id": f"{name}-{attempt + 1}-{index}",
                        "trace_id": session_id,
                        "worker": name,
                        "attempt": attempt + 1,
                    }
                )
                log.info(
                    "resume_agent_claim %s",
                    json.dumps(
                        {
                            "claim_id": item["claim_id"],
                            "trace_id": session_id,
                            "worker": name,
                            "attempt": attempt + 1,
                            "source_type": item["source"],
                            "source_location": item["source_location"],
                            "confidence": item["confidence"],
                        },
                        separators=(",", ":"),
                    ),
                )
            for index, conflict in enumerate(finding["conflicts"], start=1):
                conflict.update(
                    {
                        "conflict_id": f"{name}-{attempt + 1}-conflict-{index}",
                        "trace_id": session_id,
                        "worker": name,
                        "attempt": attempt + 1,
                    }
                )
            finding["tool_spans"] = all_spans
            duration_ms = round((time.perf_counter() - started_at) * 1000)
            finding["duration_ms"] = duration_ms
            optional_failures = _optional_tool_failures(recorder.spans if recorder else [])
            partial = bool(optional_failures)
            failed_optional = optional_failures[0] if optional_failures else {}
            failure_result = failed_optional.get("result", {})
            failure_code = str(
                failure_result.get("failure_type") or failure_result.get("error_code") or "optional_tool_failure"
            )
            retryable = bool(failure_result.get("retryable", True))
            partial_results = [
                {
                    "claim_id": item["claim_id"],
                    "reference": f"findings[{index}]",
                }
                for index, item in enumerate(finding["findings"])
            ]
            remaining_gap = (
                f"The validated findings are available, but {failed_optional.get('name')} evidence is incomplete."
                if partial
                else None
            )
            partial_error = (
                {
                    "status": "partial",
                    "failure_type": _failure_type(failure_code, "tool"),
                    "attempted_operation": f"{failed_optional.get('name')} optional evidence lookup",
                    "attempted_queries": [
                        span["attempted_query"]
                        for span in optional_failures
                        if isinstance(span.get("attempted_query"), str)
                    ],
                    "attempt_count": len(optional_failures),
                    "retryable": retryable,
                    "partial_results_count": len(finding["findings"]),
                    "remaining_gap": remaining_gap,
                    "suggested_alternatives": _failure_alternatives("tool"),
                }
                if partial
                else None
            )
            return {
                "persona": name,
                "trace_id": session_id,
                "status": "partial" if partial else "success",
                "findings": finding["findings"],
                "failure_type": partial_error["failure_type"] if partial_error else None,
                "attempted_operation": f"{name} resume assessment",
                "source": ", ".join(
                    sorted(
                        {
                            str(span.get("name"))
                            for span in all_spans
                            if span.get("kind", "tool") == "tool"
                            and span.get("name")
                            and span.get("name") != _SUBMIT_ASSESSMENT_TOOL.name
                        }
                    )
                )
                or "language model",
                "attempted_queries": list(
                    dict.fromkeys(
                        str(span["attempted_query"])
                        for span in all_spans
                        if isinstance(span.get("attempted_query"), str)
                    )
                ),
                "attempt_count": attempt + 1,
                "duration_ms": duration_ms,
                "partial_results": partial_results if partial else [],
                "tool_results": _partial_tool_results(all_spans),
                "local_recovery_attempts": recovery_attempts,
                "remaining_gap": remaining_gap,
                "suggested_alternatives": partial_error["suggested_alternatives"] if partial_error else [],
                "retryable": retryable if partial else False,
                "tool_spans": all_spans,
                "assessment": finding,
                "error": partial_error,
            }
        failed_output = raw
        log.warning(
            "resume reviewer output rejected persona=%s attempt=%d reason=%s",
            name,
            attempt + 1,
            reason,
        )
        recovery_attempts.append(
            {
                "attempt": attempt + 1,
                "outcome": "rejected",
                "failure": reason,
            }
        )
        _log_attempt_problem(
            session_id,
            name,
            attempt + 1,
            reason,
            recorder.spans if recorder else [],
        )
    return _failure_run(
        name,
        reason or "worker_failed",
        min(config.AGENT_PERSONA_VALIDATION_ATTEMPTS, attempt + 1),
        all_spans,
        retryable=reason.startswith("model_error:") or not reason.startswith("unknown_"),
        message=(
            "The reviewer could not produce a validated assessment after retrying. No unvalidated finding was used."
        ),
        recovery_attempts=recovery_attempts,
        duration_ms=round((time.perf_counter() - started_at) * 1000),
        trace_id=session_id,
    )


def _worker_run(
    name: str,
    document: dict,
    model: Any | None,
    job_context: dict | None = None,
    session_id: str = "",
) -> dict:
    with operation(
        "worker",
        worker=name,
        trace_key=trace_key(session_id),
    ):
        return _worker_run_impl(name, document, model, job_context, session_id)


def iter_persona_worker_runs(
    document: dict,
    model: Any | None = None,
    *,
    include_market: bool,
    job_context: dict | None = None,
    persona_names: tuple[str, ...] | None = None,
    session_id: str = "",
):
    """Yield one explicit terminal run envelope per isolated worker."""
    active_model = model or create_agent_model()
    names = persona_names or tuple(
        name for name, _description, _prompt in _PERSONAS if include_market or name != "market_researcher"
    )
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        futures = {
            pool.submit(
                copy_context().run,
                _worker_run,
                name,
                document,
                active_model,
                job_context,
                session_id,
            ): name
            for name in names
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                yield future.result()
            except Exception as exc:
                log.exception("resume reviewer crashed persona=%s", name)
                yield _failure_run(
                    name,
                    f"worker_crash:{type(exc).__name__}",
                    1,
                    [],
                    stage="worker",
                    retryable=_retryable_exception(exc),
                    message="The reviewer stopped unexpectedly. No finding was used.",
                    trace_id=session_id,
                )
