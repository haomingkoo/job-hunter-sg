# Contributing

Start with the [maintainer handbook](docs/README.md) and use a GitHub issue for
non-trivial work. Prefer a vertical slice that leaves one user or operator
journey working end to end over a horizontal layer with no reachable outcome.

## Issue and pull-request flow

1. Confirm the issue's outcome, acceptance criteria, blockers, and source/legal
   constraints against current code and configuration.
2. Branch from current `main`; keep unrelated work and generated artifacts out
   of the diff.
3. Implement the smallest complete slice with tests close to the behavior.
4. Run the checks relevant to the change and review the diff for secrets,
   private resumes, generated files, and accidental lockfile churn.
5. Open a PR that links the issue and records acceptance evidence.

Every PR description must include:

- user/operator outcome and linked issue;
- checks run with exact commands and results;
- live-smoke status: run, skipped with reason, or not applicable;
- browser evidence when required below;
- migration, source authorization, external-service, and rollback notes;
- known limitations or follow-up issues.

## Required checks

Run the canonical commands from [CI and local gates](docs/ci.md). At minimum,
run the focused test for the changed behavior plus the documentation check. CI
must pass without audit allowlists or lowered thresholds.

Use a live smoke only when it exercises behavior that deterministic tests
cannot. Declare the target environment and never place credentials or user data
in the command, log excerpt, screenshot, or PR body.

## Browser evidence

A real rendered browser check is required when the acceptance claim depends on
layout, responsive behavior, navigation, reload/persistence, authentication
continuity, streaming/recovery, file upload/download, clipboard, or the deployed
asset. Record the browser, viewport, URL/environment, tested journey, and
visible result. Use production only after the exact deployment is identified.

Static analysis, component tests, HTTP 200, and local rendering each prove
different things; report only the gate actually run.

## Repository hygiene

Do not commit:

- local `.env` variants (the synthetic `.env.example` is tracked), credentials,
  tokens, session files, database files, or logs;
- private resumes or live-run evidence under ignored evaluation directories;
- `frontend/node_modules`, `frontend/dist`, or `backend/static`;
- generated company/skills caches or local test output;
- screenshots containing account, resume, token, or production-user data.

Tracked fixtures are test data. Add only synthetic or explicitly approved,
non-secret material. Review `.gitignore`, `.gitleaks.toml`, and the staged diff;
ignore rules and scanners do not replace human review.

Dependency changes must be intentional. Use the existing package managers,
preserve manifests/lockfiles, run both audit gates, and do not add suppressions
to make CI green.
