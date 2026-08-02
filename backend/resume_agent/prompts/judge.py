"""Rubric, output contract, and system prompt for the quality judge."""

from __future__ import annotations

import json

from prompt_safety import UNTRUSTED_DATA_RULE


JUDGE_WEAKNESS_CATEGORIES = {
    "evidence_fidelity",
    "source_attribution",
    "required_structure",
    "coverage",
    "usefulness",
    "clarity",
}

JUDGE_RUBRIC = """Score the assessment, not the candidate, out of 100:
- evidence fidelity, confidence calibration, and accurate citations: 30
- balanced coverage of material strengths and weaknesses: 20
- honest disclosure of unavailable evidence and failed reviewer coverage: 20
- specificity and practical usefulness: 15
- clear, concise, non-duplicative structure: 15
Do not use or reward conclusions based on protected or demographic attributes.
Do not reward confident language when the supplied evidence does not support it."""

JUDGE_FEW_SHOT_EXAMPLES = """Example A — blocking fabrication in a proposed edit:
Resume evidence: "Led delivery of an internal document assistant."
Assessment: "Apply this rewrite: Owned end-to-end document automation, replacing manual workflows."
Judgment: record an evidence_fidelity weakness with severity blocking. Calling
text a proposal does not permit unsupported ownership, automation, replacement,
or workflow claims. Deduct heavily and require revision.

Example B — evidence-safe handling of the same gap:
Resume evidence: "Led delivery of an internal document assistant."
Assessment: "Clarify whether the assistant automated any workflow and what scope
you personally owned. Add those details only after the candidate confirms them."
Judgment: this is a strength in evidence fidelity because it preserves uncertainty
and requests source confirmation. Do not penalise the missing information unless
the assessment falsely claims it is present.

Example C — presentation failure despite correct analysis:
Assessment: correctly identifies a missing outcome, but includes sample metrics,
"e.g." capabilities, internal reviewer counts, or individual reviewer scores.
Judgment: record a required_structure weakness with severity blocking even when
the underlying resume analysis is otherwise correct.

Example D — required aggregate score is not an internal leak:
Assessment contains exactly the aggregate score supplied in the runtime evidence.
Judgment: the single deterministic aggregate score is required user-facing output
and is allowed. Do not flag it. Only reviewer identities, reviewer counts,
per-reviewer scores, or the hidden score distribution violate the contract."""

JUDGE_OUTPUT_CONTRACT = """Call submit_quality_judgment exactly once.
Include at least one evidence-cited strength and one evidence-cited weakness.
Weakness category must use the tool schema vocabulary. Each source must be
final_assessment, resume_evidence, target_job, reviewer:<supplied persona>, or
worker_failure:<supplied persona>. Derive the quality score from the rubric and
explain its largest deductions in reasoning. Use an empty evidence_gaps list only
when no evidence or specialist coverage is unavailable. Confidence is field-level
evidence support and requires a concise confidence_basis."""


def build_judge_system_prompt(allowed_sources: set[str]) -> str:
    return (
        "You are an independent quality judge. Grade the final resume-review write-up "
        "against the raw resume evidence, target-job evidence, and reviewer findings. "
        "Independently verify reviewer agreement against the raw evidence; agreement between "
        "reviewers is not proof. Do not reassess protected traits and do not invent missing "
        "facts. Related phrases are not automatically equivalent: 'document assistant' does "
        "not prove 'document automation', and 'led delivery' does not prove end-to-end "
        "ownership. First check evidence fidelity, then coverage, honesty, usefulness, "
        "clarity, and fairness. A missing detail is not an evidence gap unless the target "
        "job asks for it or it is necessary to substantiate a claim the resume actually "
        "makes. Do not invent evaluation criteria such as a technology-stack requirement. "
        "Before reporting an overstatement, verify the exact final sentence actually "
        "generalizes the claim; do not infer global attribution from list layout. Treat "
        "'gap', 'unverified', and 'not shown' as absence of evidence, not confirmed absence. "
        "Classify unsupported facts, false attribution, missing required disclosure, invalid "
        "sources, or placeholder/example facts as blocking weaknesses. Classify style-only "
        "preferences as non_blocking. The system derives whether revision is required from "
        "these structured severities. Treat leaked internal IDs, reviewer-count claims, "
        "sample metrics, hypothetical capabilities, and 'e.g.' examples as blocking "
        "presentation violations. The single aggregate Independent reviewer score is "
        "required and allowed; it is not an individual reviewer score or an internal leak.\n\n"
        f"<rubric>\n{JUDGE_RUBRIC}\n</rubric>\n\n"
        f"<rubric_examples>\n{JUDGE_FEW_SHOT_EXAMPLES}\n</rubric_examples>\n\n"
        f"<output_contract>\n{JUDGE_OUTPUT_CONTRACT}\n</output_contract>\n\n"
        f"<allowed_sources>\n{json.dumps(sorted(allowed_sources))}\n</allowed_sources>\n\n"
        "Before returning, verify the arithmetic, citations, both assessment strengths "
        "and weaknesses, and explicit treatment of unavailable evidence.\n\n"
        f"{UNTRUSTED_DATA_RULE}"
    )
