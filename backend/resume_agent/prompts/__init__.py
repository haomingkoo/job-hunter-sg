"""Declarative prompt configuration for the resume-agent pipeline."""

from .judge import JUDGE_WEAKNESS_CATEGORIES, build_judge_system_prompt
from .orchestrator import ORCHESTRATOR_SYSTEM_PROMPT, synthesis_score_context
from .policy import (
    FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS,
    assessment_presentation_violation_snippets,
    assessment_presentation_violations,
    assessment_structure_violations,
)
from .reviewers import (
    REVIEWER_CONFIGS,
    REVIEWER_OUTPUT_INSTRUCTIONS,
    REVIEWER_SCORING_RUBRICS,
    build_reviewer_system_prompt,
)


__all__ = [
    "FAIRNESS_AND_ANTI_FABRICATION_GUARDRAILS",
    "JUDGE_WEAKNESS_CATEGORIES",
    "ORCHESTRATOR_SYSTEM_PROMPT",
    "REVIEWER_CONFIGS",
    "REVIEWER_OUTPUT_INSTRUCTIONS",
    "REVIEWER_SCORING_RUBRICS",
    "build_judge_system_prompt",
    "build_reviewer_system_prompt",
    "assessment_presentation_violations",
    "assessment_presentation_violation_snippets",
    "assessment_structure_violations",
    "synthesis_score_context",
]
