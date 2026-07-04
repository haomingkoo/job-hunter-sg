# V2 Quality Gates

Every V2 Deep Career Agent slice must leave one runnable check tied to its
acceptance criteria. Keep the check close to the changed behavior.

## Required per PR

- List the acceptance test or smoke command in the PR body.
- State live-smoke status: not applicable, skipped with reason, or run with command.
- State known skipped checks.
- Keep normal CI deterministic. Default tests must not call SEA-LION, MCP
  servers, Glassdoor, Reddit, or other live research sources.

## Agent Workflows

- Normal agent tests use fake agents or fake tools by default.
- Live SEA-LION checks are opt-in with `RUN_LIVE_SEALION=1`.
- Live MCP checks are opt-in with `RUN_LIVE_MCP=1`.
- Missing live credentials must fail or skip clearly; never return fake success.

## Research Outputs

Research artifacts must save:

- `source_url`
- `source_type`
- `retrieved_at`
- `confidence`
- short evidence note

Public Glassdoor, Reddit, company, job-board, and generic web signals must be
labeled by source type. Do not bypass login walls, paywalls, robots restrictions,
CAPTCHAs, or private communities.

## Resume And Interview Outputs

Resume and interview artifacts must distinguish candidate evidence from market research.
Unsupported candidate claims must be flagged for user confirmation instead of
being written as facts.

## UI Smoke

Critical workspace flows need a minimal UI smoke path. Vitest component coverage
is acceptable for stable flows; use Playwright when browser layout, navigation,
or file interaction is the behavior under test.
