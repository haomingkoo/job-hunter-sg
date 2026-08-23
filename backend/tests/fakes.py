from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from recruitment_team.resume_edit_evidence import ResumeEditEvidenceResult
from resume_agent.contracts import TARGET_JOB_PERSONAS


class AllowingEditEvidenceValidator:
    def validate(self, request):
        return ResumeEditEvidenceResult(supported=True, reason="Supported by the test fixture.")


def valid_target_specialist_args(
    persona_id: str,
    summary: str,
    score: int,
) -> dict[str, Any]:
    """One schema-valid, provenance-linked target specialist submission."""
    return {
        "persona_id": persona_id,
        "summary": summary,
        "findings": [{
            "kind": "strength",
            "statement": "Directly relevant leadership experience.",
            "criterion_ids": ["design_agent_systems"],
            "candidate_profile_field_ids": ["demonstrated_agent_platform"],
            "resume_evidence_ids": ["b_test"],
        }],
        "score": score,
        "score_reason": "Grounded in directly supplied evidence.",
    }


def valid_target_synthesis_args() -> dict[str, Any]:
    return {
        "claims": [{
            "kind": "strength",
            "statement": "Built a production agent platform with traced model and tool calls.",
            "criterion_ids": ["design_agent_systems"],
            "candidate_profile_field_ids": ["demonstrated_agent_platform"],
            "resume_evidence_ids": ["b_test"],
            "candidate_evidence_ids": [],
        }]
    }


def target_synthesis_call(call_id: str = "submit-target-synthesis") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_target_assessment_synthesis",
            "args": valid_target_synthesis_args(),
            "id": call_id,
        }],
    )


def five_target_persona_responses(
    final_reply: AIMessage | None,
    *coordinator_calls: AIMessage,
) -> list[AIMessage]:
    """Drive the real task tool through all required target personas in tests."""
    responses: list[AIMessage] = []
    for index, persona_id in enumerate(TARGET_JOB_PERSONAS, start=1):
        responses.extend([
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "task",
                    "args": {
                        "description": f"Review as {persona_id}.",
                        "subagent_type": persona_id,
                    },
                    "id": f"delegate-{index}",
                }],
            ),
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "submit_target_specialist_assessment",
                    "args": valid_target_specialist_args(
                        persona_id,
                        f"{persona_id} found grounded delivery evidence.",
                        80 + index,
                    ),
                    "id": f"submit-{index}",
                }],
            ),
        ])
    responses.extend(coordinator_calls)
    if final_reply is not None:
        responses.append(target_synthesis_call())
        responses.append(final_reply)
    return responses
