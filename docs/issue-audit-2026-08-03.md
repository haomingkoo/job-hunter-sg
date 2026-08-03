# Issue backlog audit — 2026-08-03

This is the current disposition ledger after checking the latest passdown,
current `main`, focused tests, production acceptance records, and every open
GitHub issue. Closing an issue as `not planned` means its proposed architecture
is obsolete, duplicated, or unsupported by evidence; it does not mean the old
acceptance contract was implemented.

## Closed as completed

Issues #42, #44, #86, #90, #91, #93, #101, #103, #104, #110, #111, #112, #113,
#186, and #201 were closed only after their current
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
| #102 | Preserve cumulative call, token, latency, validation, checkpoint, model, and trace evidence across replay. |
| #106 | Globally merge and independently calibrate candidate evidence without losing exact provenance. |
| #108 | Replace scattered retry flags with one persisted deterministic attempt ledger. |
| #88 | Keep the umbrella PRD open until its surviving delivery outcomes are complete. |

## Verification boundary

The focused candidate-profile, open-agent, role-evidence, and recruitment-module
suite passed 124 tests during classification. After guard consolidation, the
broader affected suite passed 208 tests and the current full repository run passed 951
backend and repository-level tests with four explicit skips, 92 frontend tests,
and the frontend production build. Compile, Ruff, ty, `pip check`, and
`pip-audit` also passed. Production acceptance is documented in the V4 slice
passdown. These facts support completed-item closure; they do not waive the open
outcomes above.

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
