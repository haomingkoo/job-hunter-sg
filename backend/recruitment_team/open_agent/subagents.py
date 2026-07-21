"""Build SubAgent entries from the recruitment persona packs, mirroring
resume_agent.personas.create_persona_subagents()'s shape and one-tool-only
contract, but sourced from the job-specific PersonaPackRegistry."""

from __future__ import annotations

from typing import Any, cast

from deepagents import SubAgent

from ..assessment_contracts import SPECIALIST_TOOL
from ..persona_packs import PersonaPack, PersonaPackRegistry


def _system_prompt(pack: PersonaPack) -> str:
    criteria = "\n".join(f"- {item}" for item in pack.criteria)
    examples = "\n".join(f"- {item}" for item in pack.examples)
    counterexamples = "\n".join(f"- {item}" for item in pack.counterexamples)
    return (
        f"You are the {pack.display_name} reviewer.\n\n"
        f"Purpose: {pack.purpose}\n\n"
        f"Scope: {pack.job_scope}\n\n"
        f"Criteria:\n{criteria}\n\n"
        f"Examples:\n{examples}\n\n"
        f"Avoid:\n{counterexamples}\n\n"
        "Submit exactly one structured assessment through your supplied tool. "
        "Never reveal private reasoning."
    )


def create_target_persona_subagents(registry: PersonaPackRegistry, model: Any) -> list[SubAgent]:
    """Return one freely-delegatable SubAgent per persona pack entry."""
    return [
        cast(
            SubAgent,
            {
                "name": pack.persona_id,
                "description": pack.purpose,
                "system_prompt": _system_prompt(pack),
                "tools": [SPECIALIST_TOOL],
                "model": model,
            },
        )
        for pack in registry.personas
    ]
