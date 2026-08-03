# Issue backlog audit — 2026-08-03

This is the current disposition ledger after checking the latest passdown,
current `main`, focused tests, production acceptance records, and every open
GitHub issue. Closing an issue as `not planned` means its proposed architecture
is obsolete, duplicated, or unsupported by evidence; it does not mean the old
acceptance contract was implemented.

## Closed as completed

Issues #42, #44, #86, #90, #91, #93, #101, #102, #103, #104, #108, #110, #111, #112,
#113, #186, and #201 were closed only after their current
implementation and focused regression coverage were verified. Issue #184 was
closed after production browser acceptance of streamed Shortlist and Select
Target behavior. Issue #90 was merged in PR #191 and deployed on Railway at exact
commit `e425b50aa6690a4d2c69e12e20a9add9042b6868`. Issue #186 was merged in PR #192,
deployed at exact commit `7a44e740482f85afa761f1bd4e2e635ec8c77244`, and production-browser verified.
Issues #42, #44, and #93 were merged in PR #194. Production acceptance found two
evidence defects, so #93 was reopened, corrected in PR #195, and closed only after
Railway deployment `f47cd26b-47ec-48c4-8f20-53571a9075b2` ran exact commit
`b3f49bc9ded4b3acf51819997af53583a7e7449d` and the corrected browser journey passed.
Issue #113 was delivered by PR #189.

Issue #103 was delivered by PR #197 at commit
`2375d7991b20af669055761eaff04adb73de8f1c`. Signed-in production acceptance kept a
real multi-minute candidate study visibly alive and exposed a team-member identity
defect missed by the suite, so #103 was reopened. PR #198 corrected that seam and
merged as `efcc87c7f5371d5818f9fe7cb62c8f73c97cb1fc`. Railway deployment
`9fd23aef-a598-4456-938f-0bda12102e60` ran that exact commit successfully. A second
production study emitted real scope, correction, checkpoint, and completion events;
Candidate profiler and Coordinator both ended `Reported`, and the panel ended
`Run complete · 1 of 1 reported`. The isolated UAT conversations were deleted.

Issue #111 was corrected in PR #200 and deployed at exact commit
`fa4edba979927bc337178e0c06def22fa6da9b7e`. Production accepted an exact
candidate-confirmed number that the prior gate rejected, displayed its quote on the
pending edit, created a separate resume version on acceptance, and exported both DOCX
and PDF. The original resume remained available.

Issue #201 was corrected in PR #203 and deployed at exact commit
`5f46af2ece06ff49d56176f12a731fbf09e0ffd4`. Production continued from the refined
export into five source-backed, resume-ranked matches without opening the generic Jobs
feed. The exact confirmed edit appeared in match evidence, and prior conversation and
candidate history remained available.

Issue #102 was delivered by PR #205 and merged as
`316bcd7b234f7acf76d11a7e955c7a72687e920a`. Candidate-profile, role-profile, and
target-assessment artifacts now expose cumulative content-free calls, tokens, latency,
validation outcomes, checkpoint hits, model identities, and trace correlation across
resumptions. The replay regression retains earlier rejection and timeout evidence while
making no duplicate model request. All CI jobs passed. Railway deployment
`0a1b8c9b-1136-4ea4-95ef-d36809aa8689` ran the exact commit successfully; a read-only
query inside the service confirmed both artifact columns were created as non-nullable
JSON with an empty-object default.

Issue #108 was delivered by PR #207 and merged as
`9111ae74e3019dc902d30b25f0ef644fb79e3b5b`. The recruitment-team boundary now uses
one six-category failure classifier with stable cause codes and a content-free run
ledger that keeps transport, semantic, and workflow-resume attempts separate. Restart
and duplicate-delivery regressions prove budgets survive a new database session without
duplicating threads or messages, valid-empty search does not retry, and exhaustion makes
no surprise model call. Railway deployment
`f697c5b4-fe16-4dfd-b9e5-48a7a583a99c` succeeded; startup and `/api/health` passed, and a
read-only production query confirmed `recruitment_runs.attempt_ledger` is non-nullable
JSON with an empty-object default.

## Closed as obsolete or duplicate

| Issues | Disposition |
|---|---|
| #41, #71 | A general runtime MCP/workbench surface would duplicate the small approved application tool set and widen authority. |
| #43 | The vendor-specific Graphify path is superseded by canonical resume blocks, the Candidate Evidence Profile, and cited application artifacts. |
| #72-#75 | The retired V2 ingestion and autonomous refresh stack would duplicate the maintained job corpus and explicit search states. |
| #76 | Durable recruitment threads already own messages, preferences, plan, events, artifacts, failures, and resume/target links. |
| #95 | Consolidated into #186; its explicit-confirmation, idempotency, provenance, history, and ownership requirements were preserved there. |
| #100 | A dynamic specialist factory has no supporting benchmark or demonstrated capability gap. Fixed, versioned personas remain the bounded default. |
| #107 | Consolidated into #99; its literal semantic, two-model, trace, checkpoint, judge, edit, and Railway canary checks were preserved there. |

## Still valid and open

| Issue | Observed remaining outcome |
|---|---|
| #96 | Connect traces, semantic evaluation, field-level calibration, and regression decisions. |
| #97 | Complete restart, disconnect, duplicate-delivery, partial-artifact, and idempotent recovery. |
| #98 | Prove the complete journey on narrow screens, keyboard, live regions, and reduced motion. |
| #99 | Prove two-model portability and the authenticated semantic journey in isolated Railway staging. |
| #106 | PRs #209 and #210 and both private canaries pass. Production now rebuilds and exposes the current profile truthfully. Two target attempts found one remaining stale-quality seam: a targeted evidence correction buried exact repair IDs in the full 113-field profile and failed identically. Merge/deploy the compact v7 correction and pass target -> pending draft -> reload acceptance. |
| #88 | Keep the umbrella PRD open until its surviving delivery outcomes are complete. |

## Verification boundary

PR #209 passed 994 backend and repository-level tests with four explicit skips and 94
frontend tests. Its focused production follow-up passes 996 tests with four explicit skips,
95 frontend tests, and the frontend production build. Compile, Ruff, ty, project
`pip-audit`, `npm audit`, `pip check`, and Gitleaks pass. The installed-environment audit
is intentionally not used as project
evidence because it includes unrelated development packages; the same requirements-file
audit CI runs reports no known vulnerabilities. Production acceptance for completed
items is documented in the passdown. These facts do not waive the open deployment and
browser outcomes above.

The #42/#44/#93 production journey tracked a current MyCareersFuture job, built its
research pack, exercised a real SEA-LION negotiation turn, and verified persistence
after a true document reload. The first deployment exposed that the Jobs UI tracking
path retained salary on the selected corpus record rather than in pipeline metadata,
and that a generic shared `engineer` token could produce a false MOM occupation match.
The follow-up uses the selected record as the primary posting observation and returns
valid-empty when no defensible MOM occupation exists. Production then showed the exact
`$7,000 - $9,000` employer range first, withheld the former `Lift engineer` match,
retained self-reported evidence and private priorities, and produced cited questions,
trade-offs, and concessions. The explicitly labelled UAT application was deleted after
verification.

## Dependency check

`langchain-mcp-adapters` was removed because current code neither imports it nor
depends on it; the hosted MCP surface uses the `mcp` package directly.
`react-is` remains an explicit frontend dependency because Recharts declares it
as a peer dependency, even though application source does not import it.

## Over-engineering cleanup

- Replaced two per-path duplicate-call implementations and their tool-history
  context with one middleware used by both agent loops.
- Removed one white-box test that asserted the deleted tool-local architecture;
  equivalent behavior remains covered at middleware, coordinator-loop, and
  assessment-stream levels.
- Removed the completed 1,899-line open-agent build plan, whose instructions
  would have recreated the deleted wrappers. Current design and acceptance live
  in the PRD, issue ledger, and focused design record.
- Replaced duplicate backend/browser resume semantics with one canonical document
  interface, removed the obsolete V2 plan and its phrase-lock test, retained the
  still-current gates in the version-neutral `docs/quality-gates.md`, removed the
  duplicate parser test runner, and moved PDF fixture generation out of production
  dependencies.
- Kept `react-is` after peer-dependency evidence refuted its apparent redundancy.
- Reused the existing `TrackedJob`, corpus search, ATS extraction, telemetry, and
  SEA-LION request paths for #42/#44/#93. The research builder is passed as one callable;
  no provider registry, second job store, general tool loader, or hidden coaching
  fallback was added.
- Reused one standard-library run gate for Resume Agent and V3, one existing SSE
  transport, and the existing candidate-profile transition callbacks for #103. The
  Ponytail gate removed the only attributable dead compatibility alias; no new
  dependency, event-bus abstraction, provider registry, duplicate run path, or hidden
  fallback was added.

This cleanup removes 1,920 net lines and one direct dependency from the working
change.
