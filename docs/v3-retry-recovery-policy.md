# Job Hunter SG V3 — Retry and Recovery Policy

Status: implementation contract

Related work: [#97](https://github.com/haomingkoo/job-hunter-sg/issues/97),
[#102](https://github.com/haomingkoo/job-hunter-sg/issues/102),
[#104](https://github.com/haomingkoo/job-hunter-sg/issues/104), and
[#105](https://github.com/haomingkoo/job-hunter-sg/issues/105).

## Objective

Recover useful work without hiding failures, repeating accepted model calls, or
turning one configured retry into several nested retries. A request is successful
only when its semantic output is valid and its durable artifact is complete. HTTP
200, a parseable tool call, or a non-empty string is not sufficient.

The recovery seam has one conceptual operation:

```text
classify(failure, stage state, persisted attempt ledger) -> recovery decision
```

The decision must be deterministic from persisted inputs. Prompts describe how a
model corrects fixable output; they do not decide attempt limits, sleep policy,
checkpoint reuse, or terminal state.

## Non-negotiable invariants

1. Every retry belongs to one `logical_run_id`, stage, and persisted attempt ledger.
2. Restarting a process or reconnecting a client does not reset an attempt budget.
3. Accepted stage output is immutable for that input, prompt, schema, model, and
   tool-policy version. Resume starts at the first incomplete stage.
4. The system never repeats a completed external side effect. Commands and writes
   use stable idempotency keys.
5. Transport retries, semantic corrections, and workflow resumes are separate and
   are reported separately. They never multiply implicitly.
6. Retry only when another attempt can plausibly change the result.
7. A valid empty result is success. An access failure is not an empty result.
8. Partial or rejected output is never presented as validated final output.
9. Exhaustion is terminal for the logical run. Continuing requires an explicit new
   run or a relevant version change.
10. Every configured timeout, attempt bound, output budget, and delay policy is
    named, validated, and recorded in the execution artifact.

## Failure taxonomy and decisions

`failure_type` is a small stable category: `transient`, `validation`, `business`,
`permission`, `safety`, or `cancelled`. `failure_code` carries the specific cause.
Successful empty results use `status=success` and `result_kind=valid_empty`; they
are not failures. This keeps coordinator routing stable while allowing precise
diagnostics without inventing a new top-level type for every provider error.

| Failure type / code | Example | Automatic action | Terminal or user action |
| --- | --- | --- | --- |
| success / `valid_empty` | Job query executed and found no matches | Accept the result; do not retry | Offer a user-visible query change |
| `transient` / `transport_timeout` | Provider call exceeded its configured timeout | Retry the incomplete stage only when its persisted transport budget remains | Preserve accepted checkpoints; expose timeout and exhaustion |
| `transient` / `connection_failure` | Connection reset before a response | Same as transport timeout | Preserve checkpoints and partial results |
| `transient` / `rate_limited` | Provider returns a rate limit and `Retry-After` | Honour a valid bounded `Retry-After`; otherwise use the named delay policy | Stop visibly when the wait or attempt budget is exhausted |
| `validation` / `structured_output_invalid` | Missing tool call, wrong type, missing required field | Retry with the original input, rejected output, and exact schema error | Fail closed after the semantic attempt budget |
| `validation` / `semantic_fixable` | Duplicate criterion IDs, misplaced value, inconsistent total | Retry with the original input, rejected output, exact validation code, and correction instruction | Fail closed after the semantic attempt budget |
| `validation` / `information_absent` | Resume does not contain required evidence | Do not retry | Return `needs_clarification`, an honest null, or human review |
| `validation` / `output_truncated` | Provider reports `finish_reason=length` | Do not repeat the identical call blindly | Re-plan an explicitly smaller semantic scope or start a new run with an explicit output-budget change |
| `permission` / `permission_denied` | Tool or provider credentials lack access | Do not retry | Operator action or explicit user authorisation |
| `business` / `invalid_configuration` | Missing model, timeout, or unsupported provider option | Do not retry | Operator action; no fallback model |
| `business` / `policy_block` | Requested action is outside policy | Do not retry | Ask the user or route to human review |
| `safety` / `prompt_injection` | Untrusted text attempts to alter tool or system policy | Fail closed; do not retry attacker instructions | Preserve a safe diagnostic without echoing secrets or hidden prompts |
| `cancelled` / `user_cancelled` | User cancels the run | Stop new work and persist completed stages | Resume only after an explicit user action |

Unknown failure types fail closed. They are never silently converted to retryable
transport errors.

## Three retry layers

### 1. Transport recovery

Transport recovery repeats the same model or tool request only for a classified
transient access failure. The configured values are supplied through the run
policy and recorded in the artifact:

- transport attempt limit;
- request timeout;
- initial delay;
- delay multiplier;
- maximum delay; and
- maximum accepted `Retry-After`.

The production default is 2 transport retries (`RECRUITMENT_MODEL_TRANSPORT_RETRIES`),
raised from zero on 2026-07-21 on direct live evidence: three back-to-back local
runs against the real candidate-profile pipeline showed the identical
`document_header_01` scope complete in anywhere from 2.5s to 62s with no code
change between runs, and two heavier scopes (`summary_01`, `experience_01`) each
failed at least once with a transport error (`APITimeoutError` at the configured
300s ceiling, and separately an `InternalServerError` after ~600s) before
succeeding on a later attempt. Enabling retries let `summary_01` and `skills_01`
complete in a run where they had failed outright without retries. Retries are not
a complete fix -- the same run still hit an `experience_01` failure after ~900s
even with retries exhausted -- so the existing per-scope checkpoint-and-resume
design remains the correct backstop for whatever retries don't catch. There is no
silent provider fallback. A fallback model is a new, explicitly identified run,
not a retry.

### 2. Semantic correction

A semantic correction is another model call after a syntactically valid response
fails an external validator. Its message contains all of the following:

```xml
<original_input_data>...</original_input_data>
<rejected_output_data>...</rejected_output_data>
<validation_error_data code="stable_validation_code">...</validation_error_data>
<correction_instruction_data>Correct only the identified failure.</correction_instruction_data>
```

The validator, not the model, classifies the error as fixable or unfixable. The
attempt ledger stores the rejected output and exact validation code before another
call starts. An identical rejected output and validation code may terminate early
as non-progress rather than consume the remaining budget.

### 3. Workflow resume

Workflow resume is an explicit continuation of an interrupted logical run. It
loads accepted checkpoints and invokes only the first incomplete stage. It is not
a loop around the whole pipeline.

Checkpoint stages are:

1. candidate-profile scope;
2. role definition;
3. role-evidence assessment;
4. each independent recruitment specialist;
5. synthesis;
6. independent judge;
7. optional corrected synthesis; and
8. optional re-judge.

A role-evidence timeout therefore reuses the accepted role definition. A judge
timeout reuses all accepted specialist and synthesis outputs. A process restart
does not reset either stage attempts or the total logical-run budget.

## Attempt accounting

The execution artifact records these counters separately:

```json
{
  "logical_run_id": "...",
  "stage": "role_evidence",
  "transport_attempts_used": 1,
  "transport_attempt_limit": 1,
  "semantic_attempts_used": 2,
  "semantic_attempt_limit": 2,
  "workflow_resume_count": 1,
  "workflow_resume_limit": 1,
  "checkpoint_source": "accepted_role_definition",
  "last_failure_type": "validation",
  "last_failure_code": "semantic_fixable",
  "last_validation_code": "criterion_coverage:duplicate_ids",
  "exhausted": true
}
```

The numbers above illustrate the shape only; the actual values come from the
recorded run policy. Reports must also preserve cumulative model calls, tokens,
latency, timeouts, and rejected-output counts across every resume. A final
zero-call checkpoint replay must not erase the cost of the earlier attempts.

## Structured failure contract

Every failed or partial stage returns and persists:

- `failure_type` and stable `failure_code`;
- `stage`, `logical_run_id`, and checkpoint identity;
- attempted operation and privacy-safe input metadata;
- attempt counts and configured limits for all three layers;
- `retryable` and the exact permitted recovery action;
- `retry_after_seconds` when supplied and accepted;
- validation code plus a reference to the rejected output;
- completed stages and partial artifact references;
- terminal reason when exhausted; and
- safe alternatives such as clarification, operator action, or a new scoped run.

Raw resumes, prompts, model outputs, credentials, email addresses, and hidden
reasoning do not enter OpenTelemetry attributes. Durable user-owned artifacts may
store visible content under the product retention policy.

## Observability

One trace represents one logical run. Each attempt is a child span of its stage;
workflow resumes link back to the original run and checkpoint. Required metadata:

- logical run, stage, attempt layer, attempt number, and configured limit;
- model, prompt, schema, tool-policy, persona-pack, and validator versions;
- timeout, output-token budget, finish reason, and accepted `Retry-After`;
- checkpoint hit or miss and reused-stage count;
- validation code, retry decision, exhaustion, and terminal state;
- input/output token counts, latency, and cost metadata when available; and
- artifact and evaluation references, never raw private content.

The activity stream uses the same durable decisions to show `retrying`, `resumed`,
`waiting_for_user`, `partial`, `failed`, or `completed`. It does not infer status
from whether an HTTP response was successful.

## Required fault-injection tests

The recovery policy is not complete until the module and public-interface E2E prove:

1. a valid empty job search causes zero retries;
2. a transient timeout retries only within the explicit transport budget;
3. a role-evidence timeout reuses the accepted role definition;
4. a specialist timeout preserves the other accepted specialist outputs;
5. a synthesis or judge timeout does not repeat specialist calls;
6. a fixable validation failure receives original input, rejected output, and the
   exact validation error;
7. absent resume evidence asks the user instead of retrying;
8. `finish_reason=length` is rejected and never accepted as a partial tool result;
9. exhaustion survives process restart and causes zero surprise model calls;
10. duplicate command delivery causes no duplicate messages, artifacts, or side effects;
11. cumulative model-call and token evidence survives checkpoint replay; and
12. local and Railway canaries fail non-zero when semantic artifacts, trace
    parentage, retry accounting, or visible output are wrong despite HTTP 200.

## Current implementation gap

Candidate-profile semantic feedback and scope checkpointing already implement part
of this contract. The local canary exposes separate workflow resume limits. Role
definition, role evidence, specialists, synthesis, and judge still need durable
accepted-stage checkpoints and cumulative attempt evidence before the whole flow
can claim safe recovery. Existing errors also mix `transport`, `transient`,
`workflow`, `quality`, and `validation` as top-level failure types; these must be
normalised to the category-plus-code contract above at the module interface. Until
then, repeating a downstream phase may repeat costly accepted calls and is not
considered production-ready.
