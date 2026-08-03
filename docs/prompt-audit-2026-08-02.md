# Prompt-coherence audit, closed 2026-08-03

This is the current disposition of the 13 findings that survived the 2026-08-02
adversarial prompt audit. The original report remains available in git history;
keeping obsolete line numbers and proposed fixes here would misdescribe the live
system.

## Outcome

All 13 findings are resolved or superseded by a verified current contract.

| Finding | Current disposition |
|---|---|
| Orchestrator withheld edits and named the wrong tool | Fixed: the live path drafts evidence-supported pending edits without a second permission gate. |
| `revise` destroyed the assessment | Fixed: one bounded correction is judged again; failure remains visibly quality-blocked. |
| Score explanation rejected its own score | Fixed: validation treats the model-generated score as evaluation metadata, not a resume claim. |
| Reviewer attribution was both forbidden and required | Fixed: distinct readings survive without naming reviewer identities or lenses. |
| `get_job` described the missing-row contract incorrectly | Fixed: missing is `found=false`; `ok=false` is a lookup failure. |
| Dead default tool registry implied a callable edit path | Removed: agent tools and subagents are explicit at every construction site. |
| Persona limitations and score meaning were parsed but hidden | Fixed: both reach every specialist prompt. |
| Receipts named deleted synthesis prompts | Superseded: the live receipt names `target-synthesis-correction-v2`, which is executed only by the correction path. |
| Judge claimed evidence and failure inputs it did not receive | Fixed: judge input includes the candidate profile and explicit `no_submission` records; correction receives the same candidate evidence. |
| Candidate-profile numeric retry contract was undisclosed | Fixed: the current prompt and retry feedback distinguish evidence numbers from evaluator metadata. |
| Resume quality judge lacked the XML untrusted-data rule | Fixed: it receives the shared rule used by the other evidence prompts. |
| Duplicate-call protection existed in special-case tool wrappers | Consolidated: one per-turn middleware covers every bound tool while each search tool keeps its own completed-empty and failure contract. |
| Coordinator rendering and length rules contradicted useful output | Superseded by coordinator prompt v11, paragraph rendering, and the current output budget. |

## Contract checks retained

- User, resume, job, and tool-returned text is reference data, never instructions.
- Missing evidence is unknown, not a negative fact.
- Salary context is descriptive and never substituted for an employer's unstated pay.
- Resume edits stay pending until the candidate accepts them.
- A repairable assessment receives at most the configured correction attempts and is
  independently judged again before publication.
- Tests assert prompt inputs and tool result shapes, not obsolete wording snapshots.

## Verification

PR #176 added payload-level coverage for specialist prompts, judge evidence,
missing-specialist records, and correction evidence. Its CI passed backend, frontend,
and secret-scan jobs. The full local backend suite after the change passed 930 tests
with 4 skipped.
