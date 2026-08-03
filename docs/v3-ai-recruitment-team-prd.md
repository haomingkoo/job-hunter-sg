# Job Hunter SG V3 — AI Recruitment Team PRD

Status: active whole-app delivery; the north-star journey is not yet production-accepted end to end

## Implementation status — 2026-08-03

Persistent threads, canonical resume versions, resumable Candidate Evidence Profiles,
current source-backed search, evidence-ranked matches, target selection, bounded
specialist assessment, user-approved edits, durable application handoff, streamed real
activity, configured heartbeats, and bounded run concurrency are implemented. Current
production evidence and remaining issue disposition live in
`PASSDOWN-2026-08-02.md` and `issue-audit-2026-08-03.md`; this PRD does not preserve
superseded July runtime failures as current status.

The deployed north-star journey now passes clarification, cited drafting, acceptance
into a reversible version, DOCX/PDF export, and continuation into new source-backed
matches grounded in that refined resume. PR #203 passed signed-in production acceptance
without opening the generic Jobs feed and retained the earlier conversation. Remaining
whole-app work is limited to the valid open outcomes in the issue audit; this journey
proof does not close those observability, recovery, calibration, accessibility, or
staging requirements.

The whole application is not complete until the north-star loop below passes as one
signed-in deployed journey. Existing isolated capabilities, HTTP success, or a green
suite do not satisfy that claim.
Working product name: AI Recruitment Team
Tracker: [GitHub issue #88](https://github.com/haomingkoo/job-hunter-sg/issues/88)

## Problem Statement

Job seekers currently move between job search, resume review, tailoring, and
application tracking as separate activities. Even when each feature is useful,
the experience does not feel like a team that understands the candidate, explores
the market with them, remembers prior decisions, and carries one opportunity from
discovery through application preparation.

The existing Resume Deep Agent proves that several specialist model calls can
produce and independently judge an evidence-backed assessment. It is still
presented as a bounded review rather than a persistent career conversation. Chat
state is process-local, job exploration is not the conversational starting point,
assessment and editing are not presented as explicit handoffs, and operational
traces are not yet a user-facing activity narrative or a durable improvement loop.

Users should feel that they have an AI recruitment team working with them: a team
that searches real jobs, explains recommendations, debates fit, asks for missing
evidence, critiques the resume, proposes safe edits, remembers the conversation,
and helps track the resulting application. Transparency must make the experience
trustworthy and impressive without exposing private chain-of-thought or inventing
theatrical agent activity.

## Solution

Add a persistent **AI Recruitment Team** panel to Job Hunter SG. A signed-in user
starts or resumes a multi-turn thread, selects or uploads a resume, describes what
they want, explores real jobs, shortlists opportunities, and hands a selected job
to a bounded specialist workflow.

The product presents a team activity stream alongside the conversation. It shows
which specialist is active, what operation it is performing, which evidence and
sources it used, what artifact it produced, whether it failed or retried, and what
handoff happens next. It shows concise evidence-backed rationale, confidence basis,
disagreement, and quality-judge feedback. It never exposes hidden chain-of-thought,
private prompts, secrets, or fabricated internal dialogue.

The primary end-to-end journey is a continuous loop:

```text
saved or uploaded resume
→ persistent candidate memory and career conversation
→ ask naturally for suitable jobs
→ current source-backed recommendations, not a raw result dump
→ selected target job
→ focused clarification only where evidence is materially missing
→ truthful target-specific draft
→ review and accept validated edits into a new reversible resume version
→ download the refined resume as DOCX or PDF
→ preserve its application and decision history
→ recommend the next suitable jobs from the refined evidence
→ repeat without re-entering stable candidate facts
```

Candidate memory spans conversations and resume revisions: stable facts, preferences,
evidence, prior clarifications, targets, applications, accepted edits, and downloads
remain attributable and reusable. A new conversation does not create a new person. An
explicit request to help another person creates or selects a separate candidate context;
their resume, evidence, preferences, history, and applications must never be silently
merged with the current candidate. An ordinary role or industry pivot is not an identity
switch.

The default interaction is **propose first, then refine**. For an open-ended request,
the coordinator gives the strongest useful answer, recommendation, or pending draft the
available evidence supports before asking questions. It then separates direct resume
evidence and candidate-confirmed facts from assumptions, transferable hypotheses, and
genuinely missing information. Follow-up questions target only gaps whose answers can
materially improve accuracy or impact, explain what they would improve, and update the
durable candidate context when answered. They do not block unrelated progress, repeat
known information, force the user through a funnel, or convert an assumption into a
resume claim. A pivot or unrelated question remains a valid conversational turn; the
coordinator adapts instead of forcing the current workflow to close.

The coordinator owns the task plan. It chooses which tools and specialists to use, their
order, whether to revisit prior work, and when enough evidence exists to propose a draft.
The application does not impose a conversational stage sequence. Deterministic code
enforces evidence provenance, user approval, privacy, idempotency, and durable state only
at the boundaries where those guarantees are required.

V3 reuses the existing job corpus, search tools, resume versions, application
workspace, tracker, multi-reviewer assessment, validation gates, and OpenTelemetry
instrumentation. It does not create a parallel job database, resume system, or
application tracker.

## Product Outcomes and Release Boundaries

V3 is delivered as dependency-ordered tracer bullets rather than one big-bang
release. Each slice must be usable through the real application interface, persist
its durable state, render its visible outcome, and emit its production telemetry.

- **Foundation:** persist and resume a two-turn recruitment conversation with an
  attached resume, truthful activity events, ownership isolation, and trace
  correlation.
- **Core journey:** search and shortlist real jobs, select a target, run the bounded
  recruitment-team assessment and independent judge, clarify missing evidence,
  approve safe edits, and create a linked application.
- **Learning and hardening:** connect traces to semantic evaluations and user
  outcomes, recover interrupted runs, prove provider portability, and pass an
  authenticated Railway staging canary.

Promotion decisions compare V3 against a checked-in labelled baseline. V3 must not
regress any blocking quality category, silently increase model calls, or trade a
material cost or latency increase for no measured quality gain. Initial baselines
determine thresholds; the PRD does not invent unsupported target percentages or
magic scores.

## User Stories

1. As a candidate, I want to open an AI Recruitment Team panel, so that my job search and application work happen in one coherent place.
2. As a candidate, I want to start a new conversation, so that I can explore a new career goal without mixing it with an older search.
3. As a candidate, I want to resume a saved conversation after signing in again, so that I do not lose prior context or decisions.
4. As a candidate, I want to rename and archive conversations, so that I can organize searches for different role families.
5. As a candidate, I want to delete a conversation and its retained artifacts, so that I control my personal data.
6. As a candidate, I want to select an existing resume version, so that the team works from the exact evidence I choose.
7. As a candidate, I want to upload a resume inside the conversation, so that I can begin without navigating to another feature first.
8. As a candidate, I want the team to preserve exact resume facts, dates, employers, and metrics, so that later turns do not degrade critical evidence.
9. As a candidate, I want to describe target titles, industries, locations, seniority, salary expectations, and constraints conversationally, so that recommendations reflect what I actually want.
10. As a candidate, I want the team to ask one focused clarification when essential preferences are missing, so that it does not search blindly.
11. As a candidate, I want to search the real Job Hunter SG job corpus from the conversation, so that recommendations are actionable rather than invented.
12. As a candidate, I want to refine a search over multiple turns, so that I can explore adjacent titles and change constraints naturally.
13. As a candidate, I want search results to show company, title, location, source, publication context, and current availability, so that I can assess each opportunity.
14. As a candidate, I want to open a job without leaving the conversation, so that exploration remains continuous.
15. As a candidate, I want to save and remove jobs from a shortlist with an immediate persisted state change, so that the team remembers opportunities I care about and the control never appears dead.
16. As a candidate, I want duplicate or expired jobs labelled clearly, so that the team does not present stale results as active opportunities.
17. As a candidate, I want every recommendation to explain why the job fits my resume, so that ranking is understandable.
18. As a candidate, I want recommendations to distinguish direct evidence, partial alignment, and missing evidence, so that similarity is not presented as proof.
19. As a candidate, I want recommendation confidence accompanied by its evidence basis, so that a number alone does not create false certainty.
20. As a candidate, I want conflicting job information preserved with source and date context, so that the system does not silently choose one value.
21. As a candidate, I want to select one shortlisted job as the target with truthful streamed progress while its role profile is built, so that the recruitment team can evaluate it deeply without making the interface appear frozen.
22. As a candidate, I want a Scout to summarize the target role and relevant market language, so that I understand the opportunity before tailoring.
23. As a candidate, I want a Recruiter reviewer to assess first-screen clarity, so that I know whether the resume communicates fit quickly.
24. As a candidate, I want a Hiring Manager reviewer to assess ownership and delivery scope, so that weak leadership claims are identified.
25. As a candidate, I want an ATS reviewer to assess structure and exact terminology, so that parsing risk is separated from actual capability.
26. As a candidate, I want a Skeptic reviewer to challenge unsupported or inflated claims, so that the application remains defensible.
27. As a candidate, I want a Market reviewer to compare the supplied evidence with relevant job expectations, so that the assessment has current role context.
28. As a candidate, I want an independent Quality Judge to grade the final assessment, so that reviewer agreement alone is not treated as proof.
29. As a candidate, I want the judge to report evidence-cited strengths, weaknesses, score, deductions, confidence bases, and evidence gaps, so that quality is inspectable.
30. As a candidate, I want blocking judge feedback to trigger one visible correction and re-check, so that errors are repaired without an unbounded loop.
31. As a candidate, I want the final assessment withheld when the quality gate fails, so that plausible text is not mistaken for validated advice.
32. As a candidate, I want the activity stream to show which team member is searching, reviewing, synthesizing, or judging, so that the workflow feels alive and understandable.
33. As a candidate, I want activity events to show status, elapsed time, source count, and artifact produced, so that progress is informative rather than theatrical.
34. As a candidate, I want to expand an activity event into concise rationale and citations, so that I can verify important decisions.
35. As a candidate, I want agent disagreements summarized without raw internal chatter, so that I see useful tradeoffs without noise.
36. As a candidate, I want failures and retries shown honestly, so that unavailable research is not presented as an empty result or success.
37. As a candidate, I want long-running activity streamed incrementally, so that the interface remains responsive during multi-agent work.
38. As a candidate, I want completed activity preserved when a later specialist fails, so that useful work is not discarded.
39. As a candidate, I want the team to ask me for missing automation scope, ownership boundaries, or metrics, so that it can improve evidence without fabrication.
40. As a candidate, I want assessment and editing to be separate actions, so that a review cannot silently change my resume.
41. As a candidate, I want to explicitly request resume edits after confirming missing evidence, so that rewrites use facts I approved.
42. As a candidate, I want every proposed edit validated against the original bullet, so that new numbers, ownership, tools, or outcomes cannot be invented.
43. As a candidate, I want each edit shown as an accept-or-reject diff, so that I remain in control of the final resume.
44. As a candidate, I want rejected edit attempts excluded from the visible resume, so that unsafe drafts cannot leak into an application artifact.
45. As a candidate, I want accepted edits saved as a new resume version, so that the source resume remains recoverable.
46. As a candidate, I want the selected job, assessment, accepted resume version, and application workspace linked, so that the proof chain remains intact.
47. As a candidate, I want to create a tracked application from the conversation, so that discovery flows naturally into execution.
48. As a candidate, I want application stage changes preserved as history, so that the team can later learn from actual outcomes.
49. As a candidate, I want the team to remember which recommendations and edits I accepted or rejected, so that future assistance becomes more relevant.
50. As a candidate, I want recommendations based on prior outcomes labelled as signals rather than causal proof, so that the system does not overlearn from limited data.
51. As a candidate, I want visible token, latency, and retry summaries hidden by default but available for diagnostics, so that normal use stays simple while failures remain inspectable.
52. As a candidate, I want an accessible reduced-motion activity view, so that streaming agent activity remains usable for everyone.
53. As a candidate, I want mobile and narrow-screen access to the conversation and shortlist, so that job exploration is not desktop-only.
54. As a candidate, I want clear retention and privacy controls, so that I understand what chat, resume, and trace data is stored.
55. As a product operator, I want trace-level call graphs, so that I can identify slow, duplicated, failed, or unnecessary model and tool calls.
56. As a product operator, I want quality metrics segmented by model, prompt version, workflow phase, and failure category, so that aggregate success does not hide regressions.
57. As a product operator, I want labelled end-to-end fixtures and literal-output assertions, so that HTTP 200 cannot pass a broken deployment.
58. As a product operator, I want user feedback and edit acceptance connected to trace keys without storing secrets in telemetry, so that quality can improve safely.
59. As a product operator, I want a separate Railway staging environment and authenticated canary account, so that the complete workflow is proven before production promotion.
60. As a product operator, I want model access behind provider-neutral LangChain interfaces, so that the team can change models without rewriting orchestration logic.
61. As a candidate, I want reviewer personas grounded in cited public recruiting practices, so that their advice reflects documented methods rather than invented authority.
62. As a candidate, I want every persona pack to show its sources, jurisdiction, version, and limitations, so that I can understand where its criteria came from.
63. As a candidate, I want salary benchmarks for a selected role from current attributable sources, so that I can distinguish market evidence from guesswork.
64. As a candidate, I want salary evidence to preserve whether a figure is monthly basic pay, monthly gross pay, annual base, or total package, so that incompatible figures are not averaged together.
65. As a candidate, I want conflicting salary ranges displayed with source dates and methodologies, so that the system does not manufacture a false single market rate.
66. As a candidate, I want a negotiation plan with an evidence-backed range, questions, trade-offs, and a rehearsal, so that I can prepare without the system making decisions for me.
67. As a candidate, I want my minimum acceptable package and non-salary priorities treated as private user choices, so that the model does not invent a walk-away point.
68. As a product operator, I want salary and persona sources to be refreshable and regression-tested, so that stale external guidance is detected before it affects advice.
69. As a candidate targeting a niche role, I want the team to define what excellent performance means for that exact role before scoring me, so that a generic recruiter rubric does not distort the assessment.
70. As a candidate, I want role-success criteria separated into required evidence, preferred evidence, transferable evidence, and unknowns, so that absence is not treated as failure automatically.
71. As a candidate, I want adjacent occupation data labelled as an analogy rather than direct evidence, so that niche-role recommendations remain honest.
72. As a product operator, I want niche-role fixtures and coverage diagnostics, so that common-role accuracy cannot hide failures on sparse occupations.
73. As a candidate, I want matched, shortlisted, targeted, applying, applied, interviewing, and archived states to form one durable pipeline, so that discovery does not become a disconnected card dump.
74. As a candidate, I want each saved job to retain its posting snapshot, fit evidence, resume version, notes, contacts, activity, and next action, so that I can resume work after the live posting disappears.
75. As a candidate, I want to hide a role or company and explain why a match is poor, so that future recommendations can improve without pretending feedback is ground truth.
76. As a candidate, I want the product to distinguish a curated match feed from broad manual search, so that I understand whether a result was ranked for me or merely matched a query.
77. As a candidate, I want the selected target to lead directly to evidence review, resume tailoring, application creation, and follow-up, so that the interface always offers one truthful next step.

## Implementation Decisions

- V3 is named **AI Recruitment Team**. “Career Agent” may be used as a short navigation label, but product copy should emphasize the team of specialists.
- Build V3 inside the existing authenticated Job Hunter SG application and host it with the existing Railway service architecture.
- Use one persistent recruitment-team thread as the primary product seam. The thread owns visible messages, durable case facts, selected resume, preferences, shortlist, selected target job, produced artifacts, and links to applications.
- Persist user and assistant messages. Do not persist hidden chain-of-thought. Persist concise rationale, citations, confidence basis, structured reviewer and judge outputs, tool summaries, and user-visible activity events.
- Use a coordinator with bounded hub-and-spoke specialist calls. Specialists do not communicate directly; the coordinator passes explicit evidence and aggregates results.
- Keep the proven assessment graph: isolated structured reviewers, read-only synthesis, independent structured quality judge, and at most one visible synthesis correction and re-judge.
- Keep assessment and editing as separate capabilities. Assessment receives no edit tool. Editing is entered only after an explicit user action and exposes the validated edit tool.
- Introduce a durable activity-event contract shared by streaming, persistence, observability, and UI. Events include team member, operation, phase, status, attempt, timestamps, trace key, input type metadata, output artifact reference, source count, and a concise user-safe summary.
- Present “what the team is doing” and “why this conclusion was reached,” not private reasoning. Never display raw prompts, hidden chain-of-thought, secrets, or invented agent dialogue.
- Every job-card action that starts a recruitment run uses the same durable activity
  stream as conversation turns. Shortlisting must acknowledge persisted state promptly;
  target selection must stream role-profile progress and finish with either a selected
  target or a visible structured failure. A deployment-interrupted run must not leave a
  card looking idle while a candidate-authored action remains in the transcript.
- Reuse the current internal job corpus and constrained job tools. A supplied target-job snapshot is durable context and must not trigger a redundant search or re-fetch.
- Use progressive disclosure for job tools: compact search results first, explicit detail expansion, source provenance, valid empty results, and structured access failures.
- Reuse existing resume versions and uploaded resume artifacts. Do not introduce a separate V3 resume store.
- Reuse the existing Application Workspace and application stage history. A V3 thread links to those records rather than duplicating them.
- Add persistent thread, message, activity-event, artifact-link, and user-feedback storage only where those records have an independent lifecycle. Keep high-volume OpenTelemetry spans in the trace backend rather than duplicating complete spans into PostgreSQL.
- Preserve transactional case facts outside summarized narrative history: resume version, target titles, locations, constraints, shortlisted job IDs, selected job snapshot, confirmed claims, and application identifiers.
- Never silently truncate chat or evidence. Named limits must expose original length, retained length, and truncation status, or fail visibly. Durable case facts and artifacts are never summarized away.
- Keep the V3 control plane explicit. Every model choice, timeout, retry bound,
  search/result limit, truncation decision, and fallback policy is a named validated
  setting or request policy and is recorded in run metadata when it affects a run.
  Delete stale environment variables and reject undocumented feature flags; secrets
  remain private and are never copied into artifacts or telemetry.
- Apply the versioned [retry and recovery policy](v3-retry-recovery-policy.md) at
  every model, tool, and workflow stage. Transport recovery, semantic correction,
  and workflow resume have separate persisted counters and never multiply or reset
  invisibly. Accepted stages are checkpointed and never repeated on resume.
- Continue metadata-only OpenTelemetry for operational spans by default. Do not export resume text, prompts, model output, credentials, email addresses, or raw session IDs as span attributes.
- Store visible chat content in the application database under user ownership and retention controls. Optional content-level LLM observability requires an explicit privacy decision and redaction policy.
- Use an OTLP-compatible backend so observability remains vendor-neutral. LangSmith or Langfuse integration may consume the same structured run metadata, but core workflow correctness must not depend on either service.
- Create a separate Railway staging environment before production deployment. Staging uses isolated secrets and a canary account and runs the authenticated two-turn E2E gate before promotion.
- Keep model selection behind the existing LangChain model factory and pass model instances into reviewer, synthesis, and judge interfaces. Do not spread provider names through prompts or orchestration code.
- Version prompts, structured schemas, and evaluation datasets independently from the pipeline. A prompt adjustment must not require changing session control flow.
- Store reviewer behavior as versioned, cited persona packs outside orchestration
  code. A pack contains its purpose, job scope, explicit criteria, examples,
  counterexamples, source manifest, jurisdiction, limitations, output schema, and
  evaluation fixtures. Public sources inform criteria; the product does not claim
  to impersonate a named recruiter or reproduce proprietary firm methodologies.
- Add a Compensation Advisor capability after target selection. It compares live
  job-posting ranges, Singapore official wage statistics, accessible public salary
  guides, and user-supplied evidence without flattening unlike definitions or
  reporting periods into one number.
- Do not scrape Glassdoor or another restricted platform. Glassdoor information is
  accepted only when supplied by the user or through an authorized integration and
  is labelled as dated, self-reported evidence with its limitations.
- Compensation output includes source-cited ranges, wage definition, data period,
  role/industry mapping, uncertainties, an optional negotiation anchor, questions,
  trade-offs, and a rehearsal. The user supplies the private walk-away point and
  decides what to communicate.
- Build one versioned Candidate Evidence Profile per immutable resume version before
  job-specific comparison. It records chronology, demonstrated capabilities,
  transferable capabilities, seniority and scope signals, domains, outcomes,
  credentials, and unresolved ambiguities as structured fields. Every field carries
  canonical resume evidence IDs, a raw evidence-support score with its reason, and
  labelled correctness when evaluation data exists. It is reusable across searches
  and target roles; free-form conversation text is not the canonical profile.
- Candidate profile extraction must remain role-neutral. Suggested role families are
  separately derived hypotheses and must not rewrite or suppress profile evidence.
  Missing salary, location, or target-title preferences never block resume study.
- Candidate profile decomposition follows complete semantic entities such as a role and
  its bullets, never character slices or half-sentences. A global semantic pass merges
  repeated claims with the union of exact citations; a separate correction pass applies
  deterministic evidence boundaries; and an independent evaluation records one result
  for every final field plus a profile disposition. Counts are observations, not quality
  targets or promotion thresholds.
- Build a versioned Role Success Profile before recommendation scoring or target
  assessment. The selected job description is primary evidence. Comparable live
  jobs, Singapore Skills Framework role descriptions, and public occupation
  taxonomies may add context but never override explicit target-job requirements.
- A Role Success Profile separates outcomes, responsibilities, technical skills,
  transferable skills, scope and seniority signals, work context, required
  credentials, preferred signals, unknowns, and prohibited criteria. Each criterion
  carries provenance and evidence strength.
- Every role criterion stores the exact source field path and a whitespace-normalized
  contiguous excerpt that must exist in that field. Every positive candidate claim
  stores resolvable canonical resume block IDs and a persisted verbatim evidence
  ledger. Candidate numbers must occur in cited resume blocks; numbers from the job
  requirement cannot validate a candidate claim.
- Compound criteria should be split when components can differ, while examples and
  source alternatives remain explicitly linked. Deterministic validation checks
  structure and provenance; it does not infer compound meaning from punctuation or
  rewrite candidate alignment. An independent evidence assessor decides whether
  several cited blocks collectively establish the criterion. Unresolved semantic
  defects return `quality_blocked` or `needs_clarification`, never a silently rewritten
  successful profile.
- Fair-hiring rules are assessment policy constraints, not candidate evidence rows,
  and are excluded from candidate alignment counts.
- For niche roles, report source coverage and taxonomy match quality. Adjacent-role
  evidence is marked `analogy`, not `direct`. When coverage is insufficient, the
  team asks the candidate or a domain expert for clarification and withholds false
  precision rather than forcing a generic fit score.
- Require explicit user approval before saving a tailored resume, creating an application, sending any external message, or taking any action outside the Job Hunter SG account.
- Use the existing fairness policy. Protected and demographic attributes are excluded from job-fit scoring and recommendation ranking.
- Avoid global “success rate” claims. Monitor by workflow phase, job source, model, prompt version, failure category, and quality segment.

## Architecture and Module Interface

V3 is implemented as one deep **recruitment-team module**. Its external interface
is the test seam and the only way HTTP routes, background work, deployment canaries,
and module E2E tests drive the workflow:

```text
execute(owner, command, idempotency_key) -> run receipt or completed result
events(owner, thread_id, after_sequence) -> ordered durable activity events
snapshot(owner, thread_id) -> current user-visible thread state and artifacts
```

Commands are a versioned tagged union for starting and updating a thread, attaching
a resume, searching or shortlisting jobs, selecting a target, requesting an
assessment, submitting clarification, requesting edits, deciding an edit, and
creating an application. The module owns validation, state transitions,
orchestration, persistence, event emission, trace correlation, and safe error
mapping. Callers do not orchestrate individual agents or tools.

The FastAPI routes are thin transport adapters: authenticate, validate the command,
call the module, and serialize the result or event stream. The React panel renders
snapshots and durable activity events; it contains no workflow rules. Local E2E,
public API E2E, and Railway canaries therefore exercise the same implementation.

Internal seams exist only where behavior genuinely varies:

- **Model port:** the production LangChain chat-model adapter and a deterministic
  scripted adapter both support structured output, tool calls, streaming metadata,
  token usage, cancellation, and explicit failure responses.
- **Tool port:** the production constrained LangChain/MCP tool registry and an
  in-memory fixture adapter expose the same versioned tool contracts. Tool
  descriptions state purpose, inputs, examples, limitations, error behavior, and
  explicit boundaries against related tools.
- **Telemetry port:** the production OpenTelemetry adapter and an in-memory span
  collector receive the same privacy-safe run metadata.

Role profiling remains one external module operation with two bounded internal
semantic stages. A role-definition generator extracts material criteria and exact
role-source citations. A fresh independent evidence assessor receives the validated
definition, canonical resume evidence, and original role sources, then returns one
structured judgment per criterion: alignment, evidence IDs, supported strength,
remaining gap, raw evidence-support score, and score reason. A correction reruns only
the invalid stage and preserves already validated artifacts.

Pure validation is deliberately role-agnostic. It verifies schema, unique and complete
criterion coverage, resolvable source/evidence IDs, literal source excerpts, quoted
evidence provenance, candidate-number provenance, source-strength labels, and call
bounds. It never changes a criterion, alignment, confidence, explanation, or evidence
citation. Semantic decisions—alternatives, cross-block duration, ownership, domain
equivalence, required versus illustrative tools, and direct/partial/transferable fit—
belong to the independent assessor and labelled evaluation suite.

Persistence does not gain a repository abstraction solely for testing. Production
and tests use the same SQLAlchemy persistence implementation against their
respective databases. Prompts, rubrics, tool descriptions, and output schemas live
in dedicated versioned folders and contain no session-control logic.

The workflow state machine is explicit:

```text
exploring
-> target_selected
-> assessing
-> assessment_ready | needs_clarification | quality_blocked
-> editing
-> ready_to_apply
-> application_linked
```

Thread lifecycle (`active`, `archived`) and run lifecycle
(`queued`, `running`, `waiting_for_user`, `completed`, `partial`, `failed`,
`cancelled`) are separate from workflow state. Commands are owner-bound and
idempotent. Deletion is an immediate, idempotent privacy action with a durable
provider-cleanup request, not another visible thread state. Every event has a
thread ID, run ID, monotonically increasing sequence,
event type, status, attempt, timestamp, trace key, artifact reference, and
user-safe summary. Reconnect resumes after the last acknowledged sequence without
replaying side effects.

The coordinator selects tools during exploration but does not invoke the complete
review team for ordinary chat. A target assessment intentionally runs the five
existing isolated reviewer contracts in parallel, followed by one synthesis and
one independent judge. Only blocking, actionable judge feedback may trigger one
synthesis correction and one re-judge. The call graph and token use are observable;
adding calls requires a measured quality gain against the reference benchmark.

After the fixed journey and evaluation plane are proven, a bounded **agent factory**
may compose a temporary specialist for an uncovered task. Activation requires an
explicit reason code: uncovered target criterion, low niche-role taxonomy coverage,
conflicting sources requiring a domain method, a judge-identified coverage gap, or
a user-requested specialist simulation. The factory produces a versioned
`AgentSpecification` containing objective, evidence/persona pack, approved tools,
structured output schema, source requirements, model policy, budget, deadline,
stop condition, and escalation rule. It may select and configure registered tools;
it cannot generate executable tool code, grant credentials, perform external
side effects, or recursively create agents. Missing approved capability returns a
visible `capability_gap`. Every specification, activation reason, call, result,
cost, and judgment is persisted and benchmarked against the fixed-team baseline.

The judge returns versioned structured dimensions rather than an unexplained pass
number: evidence-cited strengths, evidence-cited weaknesses, deductions, missing
evidence, rubric scores, confidence bases, and recommended disposition. A separate
versioned quality policy converts that judgment into `pass`, `revise`, or `block`.
The prompt does not embed the expected final score or a fixture-specific answer.

## Observability and Improvement Loop

Observability has two connected planes:

1. **Operational telemetry:** OpenTelemetry traces model calls, tool calls,
   coordinator phases, retries, failures, cancellation, latency, token usage,
   parentage, and shutdown flushing. Attributes contain metadata only.
2. **Semantic evaluation:** a durable evaluation record links the privacy-safe
   trace key to workflow, prompt, rubric, schema, model, tool, and dataset versions;
   judge dimensions; quality disposition; user feedback; recommendation decisions;
   edit acceptance; and application outcomes.

Structured outputs also retain a field-level evaluation report: field path,
value/artifact reference, supporting evidence references, validation findings,
raw confidence basis, calibrated confidence, labelled correctness when available,
failure pattern, retry history, and recommended intervention. Calibration is
segmented by field and relevant document or role type; raw model confidence is
never treated as accuracy. The intervention taxonomy distinguishes prompt/example
changes, schema changes, tool or retrieval changes, missing resume evidence that
requires a user question, genuine ambiguity requiring review, and model or
decomposition weaknesses.

The evaluation record stores references to user-owned artifacts rather than
copying resume or conversation content into spans. Labelled evaluation fixtures
may contain content only when explicitly curated and approved for that purpose.
Conversation deletion cascades through live user-owned records and creates a
deletion request for linked trace/evaluation records; backup expiry follows the
displayed platform retention policy.

Each candidate prompt, rubric, tool-description, orchestration, or model change is
evaluated against the same versioned dataset and compared with its baseline by
quality category, call graph, latency, and cost. Human feedback and downstream
outcomes are evaluation signals, not automatic ground truth. Fine-tuning model
weights is considered only after a consented labelled dataset exists and simpler
prompt, tool, rubric, and routing changes no longer explain the quality gap.

## Current Product Benchmark — 2026-08-03

The benchmark uses current first-party product and help documentation. It informs
the interaction contract; it does not justify copying another product's visual
design or unverifiable outcome claims.

- [Simplify Job Matches](https://help.simplify.jobs/en/help/articles/2166608-using-your-job-matches)
  separates a small personalized feed from broad search, explains why each role
  matches, accepts hide and feedback actions, and moves applied jobs into one
  tracker. Its [Job Tracker](https://help.simplify.jobs/en/articles/2140179-using-the-job-tracker)
  keeps stages, documents, history, filters, list/column views, and imports/exports
  together.
- [Teal's Job Tracker](https://help.tealhq.com/en/articles/14435727-how-to-track-your-job-applications)
  treats each saved posting as a durable workspace with stages, the full job
  description, contacts, notes, follow-ups, resume attachments, and stage-specific
  guidance. Its [tailoring flow](https://help.tealhq.com/en/articles/14435726-how-to-tailor-your-resume-for-a-specific-job)
  connects one saved job to evidence-level resume choices and preserves the master
  resume rather than rewriting it destructively.
- [Huntr's extension](https://help.huntr.co/en/articles/9859408-the-huntr-chrome-extension)
  makes saving a role from external job sites a one-click entry into the same job
  board and lets candidates explicitly move it to the applied stage after autofill.
- [Careerflow's feature overview](https://help.careerflow.ai/en/collections/16506159-core-features-overview)
  likewise connects a searchable job portal, tracker, resume tools, and networking
  contacts instead of presenting job discovery as an isolated transcript.

The V3 implication is deliberately small: keep the conversation as the coordinator,
but make the durable job/application record the product spine. A ranked match card is
one view of that record, not a temporary answer. Save, target, tailor, apply, and
follow-up actions update the same record and activity history. Curated recommendations
and manual search remain visibly distinct. Feedback can tune later ranking, but it is
stored as a user signal rather than silently treated as objective relevance.

Issue #186 delivered this contract through the existing `TrackedJob` and Application
Workspace. Shortlist creates or reuses that record; target selection enriches it with
the posting snapshot, fit evidence, resume artifact, activity, and next action. The
thread stores the durable record reference and bounded candidate feedback only. Hiding
an unsaved role or company is explicit, optional-reason feedback scoped to that
conversation; it does not become universal relevance truth. The implementation has
passed isolated authenticated desktop and mobile browser acceptance and production
acceptance at exact commit `7a44e740482f85afa761f1bd4e2e635ec8c77244` after PR #192.

## Source-Backed Persona and Compensation Packs

Persona and compensation knowledge is maintained as versioned evidence packs,
not copied into the coordinator. Every pack records source title, URL, publisher,
publication or data date, retrieval date, jurisdiction, methodology summary,
licensing or access constraint, supported criteria, and known limitations. A
source change produces a new pack version and runs its labelled regression set.

The initial recruiting pack may derive public criteria from:

- [TAFEP Tripartite Guidelines on Fair Employment Practices](https://www.tal.sg/tafep/getting-started/fair/tripartite-guidelines): merit-based, job-related, consistently applied selection criteria and fair-hiring constraints for Singapore.
- [TAFEP Fair Recruitment and Selection Handbook](https://www.tal.sg/tafep/resources/publications/2019/fair-recruitment-and-selection-handbook): public Singapore recruitment-process guidance.
- [CIPD Selection Methods](https://www.cipd.org/uk/knowledge/factsheets/selection-factsheet/): structured, job-relevant selection and evidence on skill-based assessment and multiple perspectives.
- [Korn Ferry skills-based hiring guidance](https://www.kornferry.com/insights/featured-topics/talent-recruitment/3-skills-based-hiring-practices-that-work): public guidance on transferable skills, careful resume reading, and ATS limitations. Proprietary Korn Ferry frameworks are not reproduced.
- [Spencer Stuart executive assessment overview](https://www.spencerstuart.com/what-we-do/our-capabilities/executive-assessment-services): public distinctions among career evidence, capability, capacity, motivation, and role context. Proprietary tools are not reproduced.
- [McKinsey interviewing guidance](https://www.mckinsey.com/careers/interviewing): public examples of evaluating specific role, actions, impact, problem solving, and job-relevant technical skills. The product does not represent itself as McKinsey.

Role Success Profiles may also use:

- [SkillsFuture Singapore Skills Framework](https://www.skillsfuture.gov.sg/skills-framework/skills-frameworks-faq): Singapore role descriptions and industry-developed technical and generic competencies, treated as adaptable benchmarks rather than guarantees of fit or salary.
- [O*NET OnLine](https://www.onetonline.org/) and [O*NET Web Services](https://services.onetcenter.org/about): versioned occupation tasks, knowledge, skills, abilities, and technology information for US occupations, labelled with its US jurisdiction.
- [European Commission ESCO API](https://esco.ec.europa.eu/en/use-esco/use-esco-services-api/esco-web-service-api): versioned multilingual occupation-skill mappings, labelled with its European scope.

For a niche role, the system starts with the exact job snapshot, searches comparable
live roles, then consults occupation frameworks. It records unmatched criteria and
asks focused questions about company context or domain-specific expectations. It
does not fabricate a universal definition of “great.”

The initial Singapore compensation pack uses this evidence hierarchy:

1. Salary ranges stated on the selected live job posting, preserved with the job
   snapshot and source date.
2. [Singapore MOM Occupational Wages](https://stats.mom.gov.sg/Pages/Occupational-Wages-Tables2025.aspx), including median, 25th percentile, and 75th percentile basic and gross monthly wages with occupation, industry, population, and data-period context.
3. Accessible public recruiter surveys such as the [2026 Hays Asia Salary Guide](https://www.hays.com.sg/salary-guide) and [Michael Page Singapore salary benchmark tool](https://www.michaelpage.com.sg/salary-benchmark-tool), labelled with their survey populations, package definitions, access conditions, and publication dates.
4. User-supplied offer, current package, benefits, and authorized third-party
   evidence, kept private and never exported to metadata telemetry.

The advisor presents ranges as separate observations when definitions, populations,
or dates differ. It may explain possible reasons for the variance but must not
silently average incompatible figures.

The #42/#44/#93 implementation uses the existing Application Workspace as that pack's
only durable owner. It queries the current visible job corpus, reads the versioned MOM
workbook with `openpyxl`, preserves explicit valid-empty/access-failure/stale states,
and exposes recruiter guides only as attributable leads when compatible numeric evidence
is unavailable. Interview scaffolds cite exact resume lines or say evidence is missing.
Negotiation remains interactive through the configured SEA-LION model, but the model can
order only user-supplied priorities; unsupported figures or terms fail before persistence,
and no canned fallback is substituted. PRs #194 and #195 are deployed and production
accepted; the browser run also proved that unsupported MOM title similarity is withheld
rather than converted into false precision. Exact evidence is recorded in the passdown.

## Testing Decisions

- The module interface is the primary E2E test seam. A suite of narrow tracer
  journeys covers persistence, discovery, assessment, editing, and application
  handoff; one final authenticated canary composes the complete journey.
- The module E2E uses the production orchestration and SQLAlchemy implementation
  with deterministic model and tool adapters. A separate opt-in live evaluation
  swaps in real production adapters without changing workflow code.
- Tests assert external behavior and durable artifacts, not internal function calls or private model reasoning.
- Reuse existing Resume Agent adversarial tests for isolated reviewers, structured submissions, semantic retries, quality correction, no hidden fallbacks, no presentation leakage, and span completeness.
- Reuse existing job-search tests for source visibility, valid empty results, access failures, deduplication, and constrained result payloads.
- Reuse existing resume-version and application-workspace tests for ownership, artifact linkage, accepted edits, and append-only stage history.
- Add persistence tests proving a conversation survives process restart, remains owner-isolated, and can be deleted with its artifacts according to retention policy.
- Add conversation and signed-in browser acceptance proving an open-ended request gets
  a useful proposal before clarification; confirmed evidence, assumptions, and missing
  information are distinguishable; a focused answer refines the pending draft and
  durable candidate context; and an unrelated pivot is answered without forced closure.
- Add streaming contract tests proving events are ordered, resumable, deduplicated, and do not expose private prompts or resume content in telemetry.
- Add activity-view component tests for live, completed, failed, retrying, partial, and reduced-motion states.
- Add labelled recommendation fixtures with known relevant and irrelevant jobs. Measure precision by role family and evidence segment rather than aggregate ranking alone.
- Include sparse and niche-role fixtures where occupation taxonomies are an exact
  match, adjacent analogy, and no match. Assert that provenance and coverage change
  the output and that the system withholds unsupported precision.
- Add labelled assessment fixtures comparing V3 output with independent reference agents. Assert literal output, cited gaps, judge verdict, presentation contract, model-call graph, and token budget.
- Add edit tests for fabricated metrics, leadership-to-ownership inflation, unsupported technology, stale resume revisions, acceptance, rejection, and artifact persistence.
- Add a real opt-in local model E2E that fails non-zero unless output, activity events, reviewer coverage, structured judge submissions, and final quality status pass.
- The local E2E must write its complete report on both success and failure, including
  structured failure type, retryability, root validation code, activity, and spans.
  It must audit literal source excerpts, resolvable resume evidence IDs, and candidate
  numbers rather than treating a completed request as semantic success.
- Add an authenticated Railway staging canary that runs two turns, resumes the same durable thread, verifies target context, inspects OpenTelemetry trace correlation, and rejects HTTP-only success.
- Add provider-swap contract tests using at least two LangChain-compatible fake models; run an opt-in second-provider live benchmark before claiming provider portability.
- Add observability tests that verify span parentage, redaction, model/tool duration, token counts, attempt numbers, error status, and shutdown flushing.
- Add product evaluation metrics for clean-pass rate, revision rate, judge score, blocking category frequency, recommendation saves, edit acceptance, application creation, and later outcomes.
- Add field-level calibration fixtures and reports that expose correctness,
  evidence coverage, calibrated confidence, failure patterns, and recommended
  prompt/tool/schema/user-evidence interventions without relying on aggregate
  accuracy or self-reported confidence.
- Add architecture tests proving FastAPI and the canary enter through the module
  interface, production orchestration is not duplicated in test helpers, and
  changing prompts or model adapters does not change session-control flow.
- Add the fault-injection matrix from the
  [retry and recovery policy](v3-retry-recovery-policy.md), including valid-empty,
  transport, semantic, truncation, restart, duplicate-delivery, and downstream
  checkpoint cases.

## Dependency-Ordered Delivery Map

1. [#89 Persist and resume a two-turn recruitment conversation](https://github.com/haomingkoo/job-hunter-sg/issues/89); delivered and closed.
2. [#90 Manage conversation lifecycle and privacy](https://github.com/haomingkoo/job-hunter-sg/issues/90); delivered by PR #191 after #89.
3. [#91 Search, define role success, explain, and shortlist jobs conversationally](https://github.com/haomingkoo/job-hunter-sg/issues/91); delivered and closed.
4. [#92 Assess one selected job with source-backed recruiting personas and the bounded recruitment team](https://github.com/haomingkoo/job-hunter-sg/issues/92); delivered and closed.
5. [#93 Research compensation and rehearse negotiation for a selected job](https://github.com/haomingkoo/job-hunter-sg/issues/93); delivered with #42/#44 by PRs #194 and #195 and production accepted.
6. [#94 Turn an evidence gap into a user-approved resume edit](https://github.com/haomingkoo/job-hunter-sg/issues/94); delivered and closed.
7. [#186 Connect ranked matches to one durable application pipeline](https://github.com/haomingkoo/job-hunter-sg/issues/186); includes the former #95 handoff contract and was delivered by PR #192.
8. [#42 Add a source-backed role and company research brief](https://github.com/haomingkoo/job-hunter-sg/issues/42); delivered with #44/#93 by PRs #194 and #195 and production accepted.
9. [#44 Save a source-backed interview preparation pack](https://github.com/haomingkoo/job-hunter-sg/issues/44); delivered with #42/#93 by PRs #194 and #195 and production accepted.
10. [#96 Close the trace-to-evaluation tuning loop](https://github.com/haomingkoo/job-hunter-sg/issues/96); ready after delivered #92 through #94.
11. [#97 Recover safely from failed, interrupted, and duplicate runs](https://github.com/haomingkoo/job-hunter-sg/issues/97); blocked by #90, #186, and #96.
12. [#98 Complete the journey on mobile and with reduced motion](https://github.com/haomingkoo/job-hunter-sg/issues/98); blocked by the complete core journey.
13. [#99 Validate model portability and Railway staging deployment](https://github.com/haomingkoo/job-hunter-sg/issues/99); includes the former #107 semantic E2E contract and is blocked by #186 and #96 through #98.
14. [#102 Preserve cumulative model-call evidence across resumable runs](https://github.com/haomingkoo/job-hunter-sg/issues/102); delivered by PR #205 and production accepted at exact commit `316bcd7b234f7acf76d11a7e955c7a72687e920a`.
15. [#108 Centralize retry classification and persist one attempt ledger](https://github.com/haomingkoo/job-hunter-sg/issues/108); delivered by PR #207 and production accepted at exact commit `9111ae74e3019dc902d30b25f0ef644fb79e3b5b`.
16. [#113 Enforce the remaining open-agent safety guardrails](https://github.com/haomingkoo/job-hunter-sg/issues/113); delivered by PR #189 and closed.

The dynamic-specialist factory formerly proposed in #100 is deliberately not in
the delivery map. Fixed, versioned personas remain the default; a narrow new issue
requires demonstrated benchmark evidence of an uncovered capability before adding
another orchestration path.

Every slice crosses persistence, module behavior, transport, visible UI, tests,
and telemetry where those layers participate. Issue 7 adds the semantic evaluation
plane, but operational trace correlation is required from slice 1 onward.

## Out of Scope

- Displaying or persisting hidden model chain-of-thought, private prompts, or raw internal scratchpads.
- Invented agent conversations or fake progress intended only to make the interface look busy.
- Fully autonomous job application submission.
- Sending recruiter messages, emails, or external forms without explicit user confirmation.
- Automatically accepting resume edits or creating a final submitted resume without approval.
- Scraping sources behind authentication, paywalls, CAPTCHAs, robots restrictions, or private communities.
- Replacing the existing job database, resume version system, application workspace, or tracker with V3-specific duplicates.
- Unbounded agent recursion, open-ended self-improvement, or arbitrary tool access.
- Treating model self-confidence, reviewer consensus, or HTTP success as proof of quality.
- Production self-hosting of a large observability platform before the OTLP volume, privacy requirement, and operating cost justify it.

## Further Notes

- The strongest visual moment is not simulated thinking. It is a truthful activity stream that shows real specialists, real tool use, cited evidence, visible disagreement, correction, and a final independent quality verdict.
- The current local assessment benchmark proves the core team workflow. V3 product work should preserve its bounded call graph and should not reintroduce edit tools into assessment.
- Current hosting is Railway production at `job.kooexperience.com`. A distinct staging environment does not yet exist and is a V3 prerequisite for deployment validation.
- Current OpenTelemetry export is disabled unless Railway receives OTLP configuration. V3 should configure a durable OTLP backend before calling observability production-ready.
- Full self-hosted LangSmith is an Enterprise/Kubernetes-scale decision. V3 should start with provider-neutral OpenTelemetry and choose managed or self-hosted trace storage based on privacy, volume, and operating cost.
