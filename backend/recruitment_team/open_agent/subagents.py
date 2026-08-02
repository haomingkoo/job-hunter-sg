"""Build SubAgent entries from the recruitment persona packs, mirroring
resume_agent.personas.create_persona_subagents()'s shape and one-tool-only
contract, but sourced from the job-specific PersonaPackRegistry."""

from __future__ import annotations

from typing import Any, cast

from deepagents import SubAgent
from prompt_safety import UNTRUSTED_DATA_RULE

from ..assessment_contracts import SPECIALIST_TOOL
from ..persona_packs import PersonaPack, PersonaPackRegistry


def _system_prompt(pack: PersonaPack, score_meaning: str) -> str:
    criteria = "\n".join(f"- {item}" for item in pack.criteria)
    examples = "\n".join(f"- {item}" for item in pack.examples)
    counterexamples = "\n".join(f"- {item}" for item in pack.counterexamples)
    limitations = "\n".join(f"- {item}" for item in pack.limitations)
    return (
        f"You are the {pack.display_name} reviewer.\n\n"
        f"Purpose: {pack.purpose}\n\n"
        f"Scope: {pack.job_scope}\n\n"
        f"Criteria:\n{criteria}\n\n"
        f"Examples:\n{examples}\n\n"
        f"Avoid:\n{counterexamples}\n\n"
        f"Limits of this lens:\n{limitations}\n\n"
        f"Your score means: {score_meaning}\n\n"
        "Cite every conclusion with role criterion IDs, candidate-profile field IDs, "
        "and canonical resume evidence IDs. Every resume evidence ID must belong to "
        "a profile field you also cite. Treat missing evidence as an evidence gap, "
        "never proof that the candidate lacks a capability.\n\n"
        f"{UNTRUSTED_DATA_RULE}\n\n"
        "Submit exactly one structured assessment through your supplied tool. "
        "Never reveal private reasoning."
    )


def create_target_persona_subagents(registry: PersonaPackRegistry, model: Any) -> list[SubAgent]:
    """Return one freely-delegatable SubAgent per persona pack entry."""
    score_meaning = str(registry.output_schema["score_meaning"])
    return [
        cast(
            SubAgent,
            {
                "name": pack.persona_id,
                "description": pack.purpose,
                "system_prompt": _system_prompt(pack, score_meaning),
                "tools": [SPECIALIST_TOOL],
                "model": model,
            },
        )
        for pack in registry.personas
    ]
