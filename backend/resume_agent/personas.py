"""Persona sub-agent definitions for Resume Deep Agent v2."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, cast

import config
from deepagents.middleware.subagents import SubAgent
from langchain_core.messages import HumanMessage, SystemMessage

from .models import create_smart_model
from .prompts import FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS
from prompt_safety import xml_data_block


_PERSONAS = [
    (
        "recruiter",
        "Screens for role fit, clarity, and credible impact in a first-pass review.",
        "You are a recruiter reviewing resume bullets for fast signal and relevance.",
    ),
    (
        "hiring_manager",
        "Reviews depth of ownership, execution quality, and team/business impact.",
        "You are a hiring manager assessing whether the candidate can do the target job.",
    ),
    (
        "ats",
        "Checks keyword coverage and parsable resume language without keyword stuffing.",
        "You are an ATS reviewer focused on skill coverage, terminology, and clarity.",
    ),
    (
        "skeptic",
        "Challenges vague, inflated, or unsupported claims before edits reach the user.",
        "You are a skeptical reviewer looking for unsupported claims and weak evidence.",
    ),
    (
        "market_researcher",
        "Interprets provided internal market/job context and highlights practical gaps.",
        "You are a market researcher using only provided internal job-market context.",
    ),
]
_PERSONA_BY_NAME = {name: (description, prompt) for name, description, prompt in _PERSONAS}
_OUTPUT_INSTRUCTIONS = """Return only one JSON object with exactly these fields:
{"category":"short label","evidence_ids":["canonical block id"],"message":"one concise finding","suggested_action":"one evidence-bound action"}
Use only evidence IDs supplied in resume_evidence_data. Do not wrap the JSON in Markdown."""


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


def _persona_review(name: str, document: dict, model: Any) -> dict | None:
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
    response = model.invoke([
        SystemMessage(content=(
            f"Persona: {name}\n{prompt}\n\n{_OUTPUT_INSTRUCTIONS}\n\n"
            f"{FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS}"
        )),
        HumanMessage(content=xml_data_block(
            "resume_evidence_data",
            json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        )),
    ])
    parsed = parse_persona_output(str(getattr(response, "content", "") or ""))
    valid_ids = {str(block.get("id")) for block in document.get("blocks", [])}
    evidence_ids = parsed.get("evidence_ids")
    if (
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or any(str(item) not in valid_ids for item in evidence_ids)
    ):
        return None
    category = str(parsed.get("category") or "").strip()[:80]
    message = str(parsed.get("message") or "").strip()[:1000]
    suggested_action = str(parsed.get("suggested_action") or "").strip()[:1000]
    if not category or not message or not suggested_action:
        return None
    return {
        "persona": name,
        "category": category,
        "evidence_ids": [str(item) for item in evidence_ids],
        "message": message,
        "suggested_action": suggested_action,
    }


def iter_persona_reviews(
    document: dict,
    model: Any | None = None,
    *,
    include_market: bool,
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
            pool.submit(_persona_review, name, document, active_model): name
            for name in names
        }
        for future in as_completed(futures):
            try:
                finding = future.result()
            except Exception:
                finding = None
            if finding:
                yield finding
