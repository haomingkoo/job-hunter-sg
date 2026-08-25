# Quality Gates

Every product slice must leave one runnable check tied to its acceptance
criteria. Keep the check close to the changed behavior.

## Required per PR

- List the acceptance test or smoke command in the PR body.
- State live-smoke status: not applicable, skipped with reason, or run with command.
- State known skipped checks.
- Keep normal CI deterministic. Default tests must not call SEA-LION, MCP
  servers, Glassdoor, Reddit, or other live research sources.

## Agent Workflows

- Normal agent tests use fake agents or fake tools by default.
- Live SEA-LION checks are opt-in with `RUN_LIVE_SEALION=1`.
- Claims about autonomous tool use need a live opt-in tool-choice smoke with a
  relevant app tool such as `search_jobs`, not only a chat-completion smoke.
- Live MCP checks are opt-in with `RUN_LIVE_MCP=1`.
- Missing live credentials must fail or skip clearly; never return fake success.
- Agent-facing tools should return capped, minimal, structured results with
  explicit empty states. Add detail expansion only when needed.

The semantic retrieval backtest is mandatory in CI inside the offline crawler
image and opt-in for local development because it loads the pinned embedding
model and revision. It uses synthetic job text and human-authored ordering/constraint
invariants; NDCG is reported for diagnosis but no unexplained score threshold
controls the gate.

```bash
cd backend
.venv/bin/python -m scripts.evaluate_job_ranking
```

The full frozen-corpus command is a development diagnostic, not a CI or release
gate. Its manifest must hash-bind a public-only JSONL export and label every
returned job. It always reports `release_qualified: false` because it does not
execute a released checkout:

```bash
cd backend
.venv/bin/python -m scripts.compare_job_ranking /path/to/manifest.json
```

A ranking release requires the hash-bound protocol under `backend/evals`, arm
captures from clean exact-SHA checkouts, and three complete arm-blinded judgment
files. `evaluate_job_ranking_release prepare` creates a judge-visible union pool
and a separate private mapping. `score` validates the pool bindings, aggregates
median relevance and majority boolean labels, reports disagreement, and applies
the precommitted per-case gates:

```bash
cd backend
.venv/bin/python -m scripts.evaluate_job_ranking_release prepare \
  --protocol evals/job-ranking-release-v1.protocol.json \
  --corpus /path/to/corpus.jsonl --released /path/to/released.json \
  --candidate /path/to/candidate.json --pool-output /path/to/pool.json \
  --mapping-output /path/to/private-mapping.json
.venv/bin/python -m scripts.evaluate_job_ranking_release score \
  --protocol evals/job-ranking-release-v1.protocol.json \
  --pool /path/to/pool.json --mapping /path/to/private-mapping.json \
  --judgment /path/to/judge-1.json --judgment /path/to/judge-2.json \
  --judgment /path/to/judge-3.json --output /path/to/report.json
```

## Research Outputs

Research artifacts must save:

- `source_url`
- `source_type`
- `retrieved_at`
- `confidence`
- short evidence note

Public job-board, company, forum, and generic web signals must be labelled by
source type. Do not bypass login walls, paywalls, robots restrictions, CAPTCHAs,
or private communities.

## Resume And Interview Outputs

Resume and interview artifacts must distinguish candidate evidence from market
research. Unsupported candidate claims must be flagged for user confirmation
instead of being written as facts.

## UI Smoke

Critical workspace flows need a minimal UI smoke path. Component coverage is
acceptable for stable flows; use a real browser when layout, navigation, reload,
streaming, or file interaction is the behavior under test.

## Staging Resume-Agent E2E

Run the authenticated deployment canary against staging before promoting the
same build to production. It runs two complete review turns on the canary account.

```bash
export JOB_HUNTER_E2E_BASE_URL=https://staging.example.com
export JOB_HUNTER_E2E_TOKEN=replace-with-short-lived-canary-token
cd backend
.venv/bin/python scripts/validate_resume_agent_deployment.py
```

The gate requires a healthy API, all five independent reviewers, successful
synthesis and judge stages, native structured reviewer/judge submissions,
read-only assessment synthesis, successful model/tool spans, a clean literal
output contract, and target-job continuity across a second turn. A target-job
snapshot must not trigger a redundant `search_jobs` call. Use the printed hashed
`trace_key` to inspect the matching OpenTelemetry spans. A partial result is a
failed deployment gate even when the endpoint returned HTTP 200.
