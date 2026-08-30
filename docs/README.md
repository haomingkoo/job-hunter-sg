# Maintainer Handbook

This is the authoritative starting point for maintaining Job Hunter SG. The
root [README](../README.md) describes the product; this page routes operational
and engineering work to the current source of truth.

## Current maintainer path

Read these in order when joining the project:

1. [Fresh-clone setup](getting-started.md) — local backend/frontend setup and
   the shortest useful checks.
2. [Architecture and trust boundaries](architecture.md) — data flow,
   persistence, external systems, and ownership boundaries.
3. [Source status matrix](sources.md) — which job portals are scheduled,
   optional, absent, or authorization-blocked.
4. [Operations runbook](operations.md) — schedules, health, freshness,
   incidents, deployment receipts, rollback, and browser acceptance.
5. [Contributing](../CONTRIBUTING.md) — issue/PR flow and evidence expected for
   each change.

Supporting current references:

- [Railway deployment reference](../DEPLOY.md) — service construction and
  environment configuration.
- [CI and local gates](ci.md) — exact automated checks.
- [Quality gates](quality-gates.md) — acceptance evidence for AI, research,
  resume, and UI work.
- [Resume Agent MCP](resume-agent-mcp.md) — optional MCP surface.

When a current document conflicts with code or deployed configuration, code and
configuration win. Correct the document in the same change and record the
correction in the PR.

## Historical evidence

These files are useful records, not current runbooks:

- dated `audit-*`, `prompt-audit-*`, `issue-audit-*`, and `PASSDOWN-*` files;
- [resume-agent reference benchmark](resume-agent-reference-benchmark-2026-07-19.md);
- [maintainer dry-run for this handbook](maintainer-dry-run-2026-08-15.md);
- [product screenshots](screenshots/), which demonstrate an earlier UI and may
  not match the current deployment.

Treat dates and commit references in these records as part of their evidence.
Do not silently refresh a historical record into a current instruction.

## Design records

The following explain intended designs and past decisions. They do not prove
that every described feature is deployed:

- [resume-bound Recruitment Team PRD](resume-bound-recruitment-prd.md)
- [immutable resume-bound thread ADR](adr/0001-immutable-resume-bound-recruitment-threads.md)
- [original AI recruitment team PRD](v3-ai-recruitment-team-prd.md)
- [retry and recovery policy](v3-retry-recovery-policy.md)
- [study-first design](v4-141-study-first.md)
- [coordinator-loop design](v4-146-coordinator-loop.md)
- [open-agent design](superpowers/specs/2026-07-20-recruitment-team-open-agent-design.md)

Verify design claims against current modules, tests, configuration, and the
real user-facing path before relying on them operationally.
