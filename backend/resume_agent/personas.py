"""Persona sub-agent definitions for Resume Deep Agent v2."""

from __future__ import annotations

from typing import Any

import config

from .models import create_smart_model
from .prompts import FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS


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


def create_persona_subagents(smart_model: Any | None = None) -> list[dict]:
    """Return SMART, no-tool persona subagent specs."""
    model = smart_model or create_smart_model()
    subagents = []
    for name, description, prompt in _PERSONAS[: config.AGENT_PERSONA_COUNT]:
        subagents.append(
            {
                "name": name,
                "description": description,
                "system_prompt": (
                    f"{prompt}\n\n"
                    "Return structured findings with concise evidence and edit directions.\n\n"
                    f"{FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS}"
                ),
                "tools": [],
                "model": model,
            }
        )
    return subagents
