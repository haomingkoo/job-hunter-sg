"""Role-neutral prompt for the immutable Candidate Evidence Profile."""

from prompt_safety import UNTRUSTED_DATA_RULE


CANDIDATE_PROFILE_PROMPT_VERSION = "candidate-evidence-profile-v3"
CANDIDATE_PROFILE_VALIDATION_FEEDBACK_VERSION = "candidate-profile-validation-feedback-v3"
CANDIDATE_PROFILE_REVIEW_VERSION = "candidate-profile-global-review-v17"


CANDIDATE_PROFILE_GLOBAL_MERGE_PROMPT = f"""Consolidate semantic repetition in the
supplied compact index of every role-neutral candidate-profile field. Inspect the
complete index even when repeated facts use different wording. Co-citation and
exact-statement groups are navigation hints, not an exhaustive candidate filter. Every
group in required_exact_groups must merge because both its normalized statement and
exact provenance are identical. Exact wording with different provenance remains a
candidate, not proof that two distinct occurrences are one fact.
Source sections are provenance metadata. When a summary or profile field repeats a more
specific experience or project fact, enrich one canonical fact with the union of its
citations instead of preserving both projections. Returning only required corrections
is not a complete global review when repeated fields are present.
Return only decisions that merge two or more repeated fields.
Omit distinct and already-correct fields; the application preserves them without
asking you to retransmit them. A merge decision names every source field number and
supplies the canonical fact. The application preserves the union of their exact
citations. Do not combine distinct facts merely because they share a technology,
employer, or outcome.

Return reviewed_field_numbers containing every supplied field number exactly once.
This is the completeness receipt for the global review, including fields that remain
distinct. It is not a merge instruction.
Use each source field number in at most one decision. If candidate merge groups overlap,
combine the complete repeated fact into one decision or leave the weaker relationship
separate; never reuse a field across decisions. The application conservatively leaves
ambiguous overlapping proposals unchanged while retaining disjoint merges.

Field numbers are temporary input handles and disappear after consolidation. The
canonical score reason must explain only how the retained fact is supported by its
resume evidence. Do not mention field numbers or describe the merge operation in the
score reason.

Combine fields that split one evidence-backed clause into overlapping domain,
capability, scope, and outcome labels only when one canonical fact can retain every
material detail. Keep genuinely independent facts separate, including distinct skills
in a list. Merge decisions use the extracted statements and the application restores
exact citations. Do not return singleton or no-op decisions.

Retain all source citations. Do not add evidence, claims, numbers, employer knowledge,
or job-fit reasoning.

Submit exactly one
submit_globally_merged_candidate_profile tool call and no free text.

{UNTRUSTED_DATA_RULE}"""


CANDIDATE_PROFILE_CORRECTION_PROMPT = f"""Correct the supplied role-neutral
candidate-profile fields against the required deterministic validation codes. The
semantic consolidation pass has already completed, so return only correction decisions.
Every field number in required_corrections must appear in exactly one decision. Omit
already-correct fields; the application preserves them.

A correction must change the category, statement, evidence kind, score, or reason so
the supplied code no longer applies. Do not argue that a code is wrong or merely
describe its weakness. For chronology_without_time_evidence, the corrected category
cannot remain chronology. For direct_evidence_admits_inference, remove the unsupported
inference or mark the field transferable_hypothesis. When the corrected field is direct,
its statement and score reason must describe only the exact support; do not use inference
language even to explain what the old field did wrong. Outcomes require realized results,
awards belong under credential, and role identity is not a skill.

Field numbers are temporary input handles. Do not mention them or describe the
correction operation in the canonical score reason.

Retain all source citations. Do not add evidence, claims, numbers, employer knowledge,
or job-fit reasoning. Do not return no-op decisions. Submit exactly one
submit_globally_merged_candidate_profile tool call and no free text.

{UNTRUSTED_DATA_RULE}"""


CANDIDATE_PROFILE_EVALUATION_PROMPT = f"""Independently evaluate the supplied
role-neutral Candidate Evidence Profile as an extraction artifact. Evaluate profile
quality, not candidate quality or job fit. Review all fields and all cited evidence in
one pass.

Review every field. Put a field reference in supported_field_refs only when it has
exact citation support, no weakness, a score of 100, and the supported label. For
every other field, return one detailed field_evaluation with its strengths,
weaknesses, extraction-quality score, score reason, quality label, and canonical
cited evidence IDs. A field reference must appear in exactly one of those two buckets.
Copy every field reference exactly and verify that the two buckets together contain
the supplied field_count before submitting.
Check factual support, category, direct-versus-inferred wording, chronology, realized
outcomes, duplicate facts, and whether important distinctions or qualifiers were
lost. Then return profile-level
strengths, weaknesses, score, score reason, and pass, revise, or block. Do not rewrite
the profile or introduce evidence outside the supplied artifact.

Submit exactly one submit_candidate_profile_evaluation tool call and no free text.

{UNTRUSTED_DATA_RULE}"""


def candidate_profile_validation_feedback(validation_code: str) -> str:
    """Return actionable correction guidance without weakening validation."""

    if any(code.endswith(":quote_not_found") for code in validation_code.split("|")):
        return (
            "Every evidence quote must occur verbatim inside the cited resume block or inside "
            "the contiguous text of all cited adjacent blocks. If the quote crosses a block "
            "boundary, add every adjacent block ID it crosses; otherwise shorten the quote to "
            "verbatim text contained by the cited block."
        )
    return "Correct the exact validation error while preserving all supported source facts."


CANDIDATE_PROFILE_SYSTEM_PROMPT = f"""Build a role-neutral evidence profile from
the supplied semantic scope of immutable resume blocks. Do not use or infer a job, role preference,
location preference, salary preference, or seniority preference.

Submit fields only when the resume supports them. Use these categories:
chronology, stated_skill, demonstrated_capability, outcome,
scope_seniority_signal, domain, credential, and ambiguity. Every field needs a stable unique ID, a concise
statement, one or more canonical resume evidence IDs, verbatim contiguous evidence
quotes from those blocks, evidence_kind direct or transferable_hypothesis, a raw
evidence-support score from 0 to 100, and a short score reason. The score measures
resume support only, never candidate quality or role fit.

The field ID is a correction handle and must be unique only within this supplied
scope. The pipeline derives the final globally stable ID from the accepted fact and
its provenance; do not try to coordinate IDs with unseen scopes.

Preserve qualifiers, dates, ranges, currencies, approximations, targets, and
potential-versus-realized wording exactly. A transferable hypothesis must say what
the evidence may transfer to without claiming the candidate already performed that
new work. Record unresolved or conflicting resume wording as ambiguity. Do not
invent missing facts, normalize away material wording, hard-code technologies,
truncate prose, or treat source silence as negative evidence.

Profile only the supplied scope. It may contain a whole resume section or one
structurally distinct record within a section. Do not assume that omitted blocks
are absent from the resume. Return an empty fields array when this scope contains
no evidence belonging to the allowed categories. Scope results are validated and
merged deterministically; do not summarize across unseen scopes.

Apply these boundaries:
- chronology is a dated role, education, credential, or availability fact. A role
  title belongs in its dated chronology field, not in credential.
- stated_skill is a skill or technology listed without an action showing its use.
- demonstrated_capability requires an action the candidate performed. A title or
  skill-list entry alone is not demonstrated capability.
- outcome requires a realized result. Preserve words such as building, potential,
  target, contributed, supported, and shared; never rewrite them as delivered, led,
  saved, or owned.
- scope_seniority_signal records explicit ownership, team, stakeholder, geography,
  portfolio, budget, or decision scope. A title alone is not proof of that scope.
- domain is the industry, function, regulated setting, or problem context; it is not
  a substitute category for a list of skills.
- credential is a qualification, certification, degree, award, or formal programme
  status; it is not a job title.
- ambiguity records a conflict, unclear status, missing boundary, or wording that
  supports more than one material interpretation.

Do not profile name, email, phone number, generic location, or links. Avoid duplicate
fields that restate the same evidence at different levels of detail. A support score
of 100 means the complete field statement is explicitly supported with no material
inference. Lower it when the field combines evidence, depends on interpretation, or
is a transferable hypothesis, and explain the exact uncertainty in score_reason.

Terse role-generic examples:
1. Operations/finance: "Reduced close from 8 days to 5 days." -> outcome, direct,
support 100; quote the full sentence and preserve both numbers.
2. Healthcare: "Supported clinic workflow redesign; ownership was shared." ->
scope_seniority_signal, direct, preserve "supported" and "shared".
3. Ongoing credential: "Completing the apprenticeship; available after July." ->
chronology or credential, direct, say "completing", never "completed".
4. Listed versus demonstrated: "Skills: Python, SQL" -> two stated_skill fields,
direct, not demonstrated_capability. "Built a Python ingestion pipeline" ->
demonstrated_capability, direct.
5. Creative/research assessment: "Built a campaign prototype for a portfolio
assessment." -> demonstrated_capability, direct, preserve that it was an assessment
rather than claiming professional production delivery. "Interviewed users and
synthesized recurring themes" may support a demonstrated_capability with
evidence_kind transferable_hypothesis only when describing a plausible adjacent
capability; do not infer a target role.

Return exactly one submit_candidate_evidence_profile tool call and no free text.
Never reveal private reasoning.

{UNTRUSTED_DATA_RULE}"""
