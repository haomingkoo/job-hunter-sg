"""Role-neutral prompt for the immutable Candidate Evidence Profile."""

from prompt_safety import UNTRUSTED_DATA_RULE


CANDIDATE_PROFILE_PROMPT_VERSION = "candidate-evidence-profile-v3"
CANDIDATE_PROFILE_VALIDATION_FEEDBACK_VERSION = "candidate-profile-validation-feedback-v3"


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
