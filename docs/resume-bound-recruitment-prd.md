# PRD: Resume-bound Recruitment Team

Status: Accepted; implementation verified locally, production acceptance pending

Owner: Job Hunter SG

Parent product epic: #88

## Problem

Before this change, a candidate could upload a new resume, navigate to Recruitment
Team, and receive analysis based on an older saved resume. The upload remained only
a browser draft, the team silently restored an active conversation, and the resume
selector listed only saved versions. A second latent defect allowed saved resume
content to change in place while completed candidate profiles were reused by version
ID.

This is an evidence-identity failure. It can produce polished but irrelevant job
recommendations and makes the system's provenance claims untrustworthy.

## Outcome

A candidate can upload any supported resume, save it as a distinct immutable
version, explicitly start a new conversation with it, and see which exact resume
every recommendation and proposed edit used. Stale or ambiguous evidence fails
closed before a model call or recommendation. Hui Shan's accounting resume must
produce accounting/finance-grounded analysis without semiconductor-manufacturing
evidence from an older resume.

## Users and jobs to be done

- As a candidate, I can keep several resumes without one silently overwriting or
  replacing another.
- As a candidate, I explicitly choose the resume for a new conversation.
- As a candidate, I can see the bound resume identity after reload and in the
  conversation list.
- As an auditor, I can trace profiles, recommendations, assessments, and edits to
  one resume identity.
- As a candidate, I can retry a failed profile stage without switching evidence or
  repeating completed stages.
- As a candidate, accepting an edit creates a derived resume and leaves the
  original resume and conversation unchanged.

## Product contract

### Save and select

Authenticated PDF/DOCX upload parses and persists one resume version in the same
successful operation. The response includes its version ID and identity. Guest
upload remains parse-only. Paste/manual editing remains a draft until the user
chooses Save or Use with Recruitment Team.

Starting a conversation requires an explicit version selection. The product must
not silently choose the master, newest, or previously active resume. Direct Team
navigation may offer to continue a named prior thread, but it must identify that
thread's resume. A new conversation makes no model request until the user confirms
the resume.

### Bind and verify

The server computes resume identity from canonical stored content. Every thread is
permanently bound to one version ID and SHA-256. A central resolver checks
ownership, version ID, and hash before workflow commands
and evidence reads. A mismatch returns a stable conflict error and performs no
model call, cache reuse, or mutation.

Candidate profiles are reusable only when their embedded document ID/revision and
profiling policy match the bound resume. Legacy or mismatched artifacts stay on
record but are excluded from selection.

### Recommend and tailor

Recommendation receipts identify the bound resume and candidate-profile artifact.
External job text remains untrusted reference material and cannot become durable
candidate evidence merely because it contains instruction-like language.

Proposed edits remain pending until explicit acceptance. Acceptance creates a new
derived resume version and returns an action to start a new conversation with it;
it never rebinds the source thread.

## System design

```text
authenticated upload or explicit save
                |
                v
       immutable ResumeVersion
          (id + SHA)
                |
        explicit confirmation
                v
        RecruitmentThread
         (fixed identity)
                |
       bound-resume resolver
                v
 CandidateProfile -> ranking -> assessment -> pending edit
```

Deepen two existing modules rather than add a parallel store:

- `resume_versions` owns validation, canonicalisation, identity, creation, metadata
  updates, and archival.
- `RecruitmentTeam._bound_resume` owns owner-scoped resolution and identity checks.

Thread facts remain the persisted identity receipt for this change. Decision code
must use the resolver rather than reading those JSON fields independently.

## Trust and safety

- Server hashes are authoritative; do not trust a browser hash as proof.
- Every lookup includes authenticated owner ID and returns the same not-found
  behaviour for foreign IDs.
- Resume text, hashes, and filenames do not enter URLs, telemetry, or errors.
- Free-text agent turns cannot write durable candidate preferences or evidence;
  external job and pasted reference text remains untrusted input.
- Authenticated upload storage is bounded by the existing file/text/version limits
  and rate limit.
- Original submitted application files must not accumulate as unbounded base64 in
  workspace JSON. New writes retain bounded parsed metadata, cap count and aggregate
  bytes, and omit stored file bodies from workspace responses.

## Non-goals

- A global current-resume pointer.
- Automatic latest/master resume selection.
- Event sourcing, a generic workflow engine, or a new content-addressed snapshot
  service.
- Automatic acceptance of model-generated resume edits or application submission.
- Proving job-search outcome quality from a single candidate acceptance run.
- Migrating password authentication to cookies in this feature.

## Vertical delivery slices

### 1. Immutable uploads

Persist authenticated uploads through the existing resume-version service, return
identity metadata, and make content changes create a new row. `PUT` becomes
metadata-only. Show the saved upload in the resume library after reload.

### 2. Explicit thread binding

Require resume confirmation before thread creation, remove silent master/first
selection for new threads, display the bound identity, and route recruitment work
through one fail-closed resolver.

### 3. Profile identity

Require exact document ID/revision plus current policy for completed-profile reuse.
Ignore mismatched legacy artifacts and prove exact-content reuse versus
one-character-change invalidation.

### 4. Durable semantic retry

Expose the failed scope and retryability, retain completed checkpoints, and retry
only incomplete work against the same bound identity after reload.

### 5. Bound recommendations and derived tailoring

Put resume/profile identity on recommendation receipts, validate it through target
assessment and edit creation, and create accepted edits as a derived version while
leaving the source thread unchanged.

### 6. Storage and mixed-trust hardening

Cap submitted-resume history and aggregate bytes, stop returning base64 histories,
add endpoint-specific rate limiting, validate file signatures, and prevent pasted
external instructions from becoming durable candidate evidence or automatic edits.

### 7. Production acceptance

Run the signed-in browser journey with two intentionally different resumes,
including Hui Shan's accounting resume, and verify visible identity, request
payloads, returned artifacts, reload persistence, pending-only edits, and a
read-only database trace. Record failures as failures; HTTP 200 alone is not a
pass.

## Acceptance criteria

- Uploading an authenticated resume creates exactly one durable version and it
  remains selectable after reload.
- Resume A remains byte-identical after saving Resume B; content mutation through
  the version update route is rejected.
- Starting a new conversation sends no request until a resume is explicitly
  selected and confirmed.
- The active-thread UI and conversation list show label, version ID, saved time,
  word count, and a short server identity.
- Every recruitment command fails before model execution if stored bytes do not
  match the thread identity.
- An exact profile may be reused; a different revision, mismatched profile, or
  hashless legacy artifact may not.
- Profile failure survives reload and retry resumes only incomplete scopes against
  the same resume.
- Recommendations and assessments expose one consistent resume/profile receipt.
- Accepted edits create a new version; the source version and source thread remain
  unchanged, with an explicit Start conversation action for the derived version.
- A cross-owner version, thread, profile, or edit ID returns 404 without revealing
  whether it exists.
- Adversarial pasted job text cannot become candidate evidence or preferences
  without an explicit candidate statement.
- Submitted-resume storage stays within tested per-file, item-count, and aggregate
  limits and workspace responses do not return stored file bodies by default.
- Production browser acceptance uses the Hui Shan resume and returns
  accounting/finance-grounded recommendations with zero unsupported semiconductor
  career claims; all tailoring remains pending until accepted.

## Verification gates

1. Focused service and API tests for immutability, ownership, binding mismatch,
   profile reuse, idempotency, and accepted-edit lineage.
2. Frontend tests for explicit selection, identity display, reload, failure, and
   derived-version handoff.
3. Security tests for mixed-trust prompts and bounded upload history.
4. Full backend suite, frontend suite/build, static checks, dependency audit, and
   secret scan.
5. Migration rehearsal if schema changes become necessary; otherwise explicitly
   record that no migration was introduced.
6. Deployment of the exact verified commit and signed-in production browser plus
   database-trace acceptance.

## Success measures

- Zero resume-binding mismatches in the invariant audit.
- Zero silent new-thread starts with an unconfirmed resume.
- Zero stale-profile reuse in adversarial tests.
- 100% of recruitment results in the acceptance journey trace to one visible resume
  identity.
- The two-resume E2E detects any cross-resume evidence term deterministically.

## Rollout and recovery

Deploy fail-closed readers before relying on new UI behaviour. Existing exact-match
threads continue to work. A legacy mismatch is preserved for audit and shown as
requiring a new conversation; it is never silently repaired. The change is
reversible by deployment rollback because it adds no new dependency or destructive
data migration. Content immutability remains the forward contract.
