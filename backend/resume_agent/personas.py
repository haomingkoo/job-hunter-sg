"""Persona sub-agent definitions for Resume Deep Agent v2."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, cast

import config
from deepagents.middleware.subagents import SubAgent
from langchain_core.messages import HumanMessage, SystemMessage

from .models import create_smart_model
from .prompts import FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS
from prompt_safety import xml_data_block


log = logging.getLogger("jobhunter.resume_agent")


_PERSONAS = [
    (
        "recruiter",
        "Screens for role fit, clarity, and credible impact in a first-pass review.",
        """You are the first-screen recruiter.
Workflow:
1. Scan for a clear target-role narrative and credible first-pass signal.
2. Check whether the most relevant experience is easy to find quickly.
3. Choose one screening issue or strength, not metric verification, technical
   depth, or keyword coverage owned by another reviewer.
4. Support it with resume evidence and give one practical action.
Good: explain why the target-role story is or is not obvious on a quick scan.
Avoid: auditing a percentage baseline or listing missing keywords.""",
    ),
    (
        "hiring_manager",
        "Reviews depth of ownership, execution quality, and team/business impact.",
        """You are the hiring manager.
Workflow:
1. Compare demonstrated ownership, scope, and delivery depth with the target job.
2. Distinguish hands-on delivery from participation, training, or exposure.
3. Choose one execution-risk or capability signal, not general recruiter polish.
4. Support it with resume evidence and give one practical action.
Good: assess whether the evidence demonstrates ownership at the target role's scope.
Avoid: calling the profile "rare" without assessing delivery depth.""",
    ),
    (
        "ats",
        "Checks keyword coverage and parsable resume language without keyword stuffing.",
        """You are the ATS and parsing reviewer.
Workflow:
1. Compare exact target-job terminology with resume wording when job context exists.
2. Check section and bullet text for machine-readable boundaries.
3. Choose one keyword or parsing issue; do not judge whether metrics are credible.
4. Never recommend adding a skill the resume does not support.
Good: recommend an exact target term only when cited resume evidence supports it.
Avoid: challenging whether a percentage is independently verified.""",
    ),
    (
        "skeptic",
        "Challenges vague, inflated, or unsupported claims before edits reach the user.",
        """You are the evidence skeptic.
Workflow:
1. Challenge the strongest claim for missing baseline, ownership, qualifier, or proof.
2. Treat resume metrics as candidate-reported, never independently verified.
3. Choose the single highest-risk overclaim or ambiguity.
4. Suggest clarification or verification without inventing replacement facts.
Good: identify the missing baseline behind a candidate-reported impact claim.
Avoid: calling the claim proven or supplying an imagined before-and-after figure.""",
    ),
    (
        "market_researcher",
        "Interprets provided internal market/job context and highlights practical gaps.",
        """You are the target-market researcher.
Workflow:
1. Use only the supplied target-job snapshot; make no broad market claims.
2. Compare its responsibilities and terminology with demonstrated resume evidence.
3. Choose one role-specific alignment or gap not already reducible to generic ATS wording.
4. Do not run when target-job context is absent.
Good: connect one supplied responsibility to evidence of related delivery.
Avoid: making broad Singapore-market claims or repeating generic profile praise.""",
    ),
]
_PERSONA_BY_NAME = {name: (description, prompt) for name, description, prompt in _PERSONAS}
_OUTPUT_INSTRUCTIONS = """Return only one JSON object with exactly these fields:
{"category":"short label","evidence_ids":["canonical block id"],"target_job_fields":["description","terms"],"message":"one concise observation","rationale":"brief evidence-based explanation","suggested_action":"one evidence-bound action"}
Use only evidence IDs supplied in resume_evidence_data. target_job_fields must
contain field NAMES, never field values or quoted job terms. Choose only from:
title, company, description, terms, location, source. Use [] when no target-job
field supports the finding. Do not wrap the JSON in Markdown."""


def create_persona_subagents(smart_model: Any | None = None) -> list[SubAgent]:
    """Return SMART, no-tool persona subagent specs."""
    model = smart_model or create_smart_model()
    subagents = []
    for name, description, prompt in _PERSONAS[: config.AGENT_PERSONA_COUNT]:
        subagents.append(
            cast(SubAgent, {
                "name": name,
                "description": description,
                "system_prompt": (
                    f"{prompt}\n\n"
                    f"{_OUTPUT_INSTRUCTIONS}\n\n"
                    f"{FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS}"
                ),
                "tools": [],
                "model": model,
            })
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


def _validated_finding(
    name: str,
    parsed: dict,
    document: dict,
    job_context: dict | None,
) -> tuple[dict | None, str]:
    if not parsed:
        return None, "invalid_json"

    valid_ids = {str(block.get("id")) for block in document.get("blocks", [])}
    evidence_ids = parsed.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        return None, "missing_evidence_ids"
    if any(str(item) not in valid_ids for item in evidence_ids):
        return None, "unknown_evidence_id"

    allowed_job_fields = {
        key for key in (job_context or {})
        if key in {"title", "company", "description", "terms", "location", "source"}
    }
    target_job_fields = parsed.get("target_job_fields", [])
    if not isinstance(target_job_fields, list):
        return None, "invalid_target_job_fields"
    if any(str(item) not in allowed_job_fields for item in target_job_fields):
        return None, "unknown_target_job_field"
    if name == "market_researcher" and job_context and not target_job_fields:
        return None, "missing_target_job_citation"

    category = str(parsed.get("category") or "").strip()[:80]
    message = str(parsed.get("message") or "").strip()[:1000]
    rationale = str(parsed.get("rationale") or "").strip()[:1000]
    suggested_action = str(parsed.get("suggested_action") or "").strip()[:1000]
    if not category or not message or not rationale or not suggested_action:
        return None, "missing_required_text"

    return {
        "persona": name,
        "category": category,
        "evidence_ids": [str(item) for item in evidence_ids],
        "target_job_fields": [str(item) for item in target_job_fields],
        "message": message,
        "rationale": rationale,
        "suggested_action": suggested_action,
    }, ""


def _persona_review(
    name: str,
    document: dict,
    model: Any,
    job_context: dict | None = None,
) -> dict | None:
    spec = _PERSONA_BY_NAME.get(name)
    if not spec:
        return None
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
    data_blocks = [xml_data_block(
        "resume_evidence_data",
        json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
    )]
    if job_context:
        data_blocks.append(xml_data_block(
            "target_job_data",
            json.dumps(job_context, ensure_ascii=False, separators=(",", ":")),
        ))
    messages = [
        SystemMessage(content=(
            f"Persona: {name}\n{prompt}\n\n{_OUTPUT_INSTRUCTIONS}\n\n"
            f"{FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS}"
        )),
        HumanMessage(content="\n\n".join(data_blocks)),
    ]
    for attempt in range(2):
        response = model.invoke(messages)
        parsed = parse_persona_output(str(getattr(response, "content", "") or ""))
        finding, reason = _validated_finding(name, parsed, document, job_context)
        if finding:
            return finding
        log.warning(
            "resume reviewer output rejected persona=%s attempt=%d reason=%s",
            name,
            attempt + 1,
            reason,
        )
        messages = [*messages, HumanMessage(content=(
            f"Your response failed validation: {reason}. Return one corrected JSON "
            "object using only the supplied evidence IDs and allowed target-job field names."
        ))]
    return None


def iter_persona_reviews(
    document: dict,
    model: Any | None = None,
    *,
    include_market: bool,
    job_context: dict | None = None,
    persona_names: tuple[str, ...] | None = None,
):
    """Yield valid persona findings independently as each reviewer completes."""
    names = persona_names or tuple(
        name
        for name, _description, _prompt in _PERSONAS
        if include_market or name != "market_researcher"
    )
    active_model = model or create_smart_model()
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        futures = {
            pool.submit(_persona_review, name, document, active_model, job_context): name
            for name in names
        }
        for future in as_completed(futures):
            try:
                finding = future.result()
            except Exception:
                finding = None
            if finding:
                yield finding
