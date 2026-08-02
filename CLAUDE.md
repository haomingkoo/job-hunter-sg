# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Job Hunter SG

Singapore job aggregator + AI resume coach + AI recruitment team, multi-user.

## Architecture

- **Backend**: FastAPI + SQLAlchemy + SQLite (Postgres on Railway). Entry point `backend/main.py` (~9k lines, most REST routes live there).
- **Frontend**: React + Vite + Tailwind. Tabs in `frontend/src/App.jsx`: `team`, `jobs`, `resume`, `stories`, `tracker`, `reminders`, `analytics`, `power`, `account`.
- **Scraping**: requests + BeautifulSoup. `JobAggregator.SOURCE_MAP` in `scraper.py`: API-based (mcf, careersgov, adzuna, jooble) + HTML scrapers that may 403 (nodeflair, indeed, jobstreet).
- **Embeddings**: sentence-transformers/all-MiniLM-L6-v2 (384-dim) via `embedding_service.py`.
- **Agent runtime**: LangChain 1.x + LangGraph + `deepagents` (`create_deep_agent`), SEA-LION through `langchain-openai`.
- **AI**: SEA-LION API (OpenAI-compatible, AI Singapore). Free tier, 10 req/min/key, up to 5 keys.
- **Auth**: JWT + bcrypt by default; `AUTH_MODE=cloudflare` switches to validated Cloudflare Access.
- **Deploy**: Railway, three services from one repo — app (`railway.toml`), nightly crawl cron (`railway.seed.toml`, 22:00 UTC), alert cron (`railway.alerts.toml`, 23:00 UTC).

## Commands

```bash
# Backend (venv lives at backend/.venv)
cd backend && pip install -r requirements.txt
python main.py                          # serves API on PORT=8000, static frontend from ./static

# Frontend
cd frontend && npm install
npm run dev                             # :5173, proxies /api to :8000
npm test                                # vitest run
```

### Tests

799 tests across two roots. Both need `PYTHONPATH=backend`, and the root `conftest.py` forces
`DATABASE_URL` to a temp SQLite file so a run can never touch `jobhunter.db`. Run from the repo root:

```bash
PYTHONPATH=backend python -m pytest backend/tests tests -q     # what CI runs
PYTHONPATH=backend python -m pytest backend/tests/test_validation_gates.py -q          # single file
PYTHONPATH=backend python -m pytest backend/tests/test_open_agent_runner.py -k judge    # single test
RUN_LIVE_SEALION=1 PYTHONPATH=backend python -m pytest backend/tests/test_resume_agent_live.py -q
```

Live-model tests are opt-in and skipped otherwise (`RUN_LIVE_SEALION=1`, plus `SEALION_API`/`sealion_api`
in env or `backend/.env`). Default tests must never call SEA-LION, MCP, or any external research source —
see `docs/v2-quality-gates.md`.

### Lint / types / hooks

```bash
ruff check backend tests                # select = E9,F63,F7,F82 only (see pyproject.toml)
ty check --output-format concise        # scoped to backend/schemas.py + backend/resume_agent
python -m compileall -q backend
backend/.venv/bin/pre-commit run --all-files
```

Pre-commit also blocks commits to `main` and runs `detect-secrets` against `.secrets.baseline`.
CI additionally runs `pip-audit`, `npm audit --audit-level=high`, and Gitleaks.

### Live validation scripts (`backend/scripts/`)

Not tests — they hit the real model and write JSON traces to `backend/evals/live-runs/`.

| Script | Purpose |
|--------|---------|
| `validate_recruitment_team_local.py` | Full V3 tracer journey against the configured live model |
| `validate_candidate_profile_local.py` | Candidate-profile build on a real resume |
| `validate_resume_agent_deployment.py` | Post-deploy semantic canary |
| `benchmark_resume_agent_reference.py` | Literal-output reference benchmark |
| `compare_candidate_profile_canaries.py` | Diff two canary runs |

## AI Models (SEA-LION)

Four tiers in `backend/config.py`, all env-overridable. Tier choice came from an empirical eval
(2026-06-26, see `.claude/projects/.../reference_sealion_model_eval.md`).

| Constant | Default | Used for |
|----------|---------|----------|
| `SEALION_FAST_MODEL` | `Qwen-SEA-LION-v4-32B-IT` | Interactive rewrites, JD summaries. Reliable tool-calling. |
| `SEALION_PIPELINE_MODEL` | falls back to FAST | Classic tailoring pipeline. v4.5 leaks reasoning into strict-JSON prompts on this path. |
| `SEALION_AGENT_MODEL` | `Qwen-SEA-LION-v4.5-27B-IT` | Resume Agent v2 + V3 open-agent orchestration and tool loop. |
| `SEALION_SMART_MODEL` | `Qwen-SEA-LION-v4.5-27B-IT` | Persona reviews (single-shot, no tools, latency-tolerant). |

Gotchas baked into config:
- v4.5 Qwen returns `reasoning_content` instead of `content` unless run in non-thinking mode — that is what `SEALION_DISABLE_THINKING_MODELS` is for.
- SMART is a reasoning model: under a tight budget it spends every token thinking and returns empty. `SMART_MIN_MAX_TOKENS` (3000) floors it at every call site.
- Retired `Llama-SEA-LION-v3.5-70B-R`: could not tool-call on this endpoint and leaked chain-of-thought.
- Throttle with `SEALION_REQ_PER_MIN` (default 9, per key, headroom against 429s).

## The three AI layers

The repo has accumulated three generations of resume AI. They coexist; know which one you are in.

### 1. Classic tailoring pipeline (v1) — `tailoring_pipeline.py`

Deterministic 7-stage pass, background thread + progress polling. No agent, no tools.

```
Stage 0: Local (200ms)   Parse resume into sections/bullets + load pre-parsed JD + baseline score
Stage 1: FAST  (~8s)     Strategic analysis: which bullets to prioritize, where to inject keywords
Stage 2: Local (50ms)    AI phrase cleanup (107 replacements, protected if the phrase appears in the JD)
Stage 3: FAST  (~12s)    Per-bullet rewrites (batched 4/call, validation-gated)
Stage 4: Local (50ms)    Section coherence: verb dedup with synonym map, tense consistency
Stage 5: FAST  (~10s)    Executive summary generated from the already-polished content below it
Stage 6: Local (50ms)    Validation gates (fact preservation, hallucination) + final score
```

Intensity levels: `nudge` = stages 0/2/4/6 (local only, ~5s) · `keywords` = 0-4, 6 (~30s) · `full` = all (~45-60s).

| File | Purpose |
|------|---------|
| `jd_preparser.py` | Pre-parse JDs at scrape time: skills, experience years, education, responsibilities. Pure regex, ~50ms/job. |
| `resume_structurer.py` | Parse resume text into `{sections: [{key, entries: [{bullets: [{id, text, issues}]}]}]}`. Shares logic with `resume_scorer.py`. |
| `ai_phrases.py` | 107 AI-sounding phrase→replacement mappings. Phrases present in the JD are protected. |
| `validation_gates.py` | 5 gates on every AI rewrite: fact_preservation, ai_phrases, keyword_verbatim, length_sanity, hallucination. |
| `resume_scorer.py` | Scores 0-100 across Impact / Presentation / Competencies. |
| `ai_service.py` | SEA-LION client: rate limiting, round-robin keys, progressive retry (`call_sealion_json`). |

### 2. Resume Deep Agent (v2) — `backend/resume_agent/`

A `deepagents` graph: one orchestrator plus five persona sub-agents, each with exactly one submission tool.

- `agent.py` — `create_resume_agent()` wraps `create_deep_agent(model, tools, subagents, system_prompt, checkpointer, interrupt_on)`. Recursion limit is `AGENT_MAX_TOOL_ITERATIONS`; a `GraphRecursionError` returns `{"stopped": True, "reason": "tool_iteration_cap"}` rather than raising.
- `personas.py` — the five reviewers, fixed in `contracts.py::TARGET_JOB_PERSONAS`: `recruiter`, `hiring_manager`, `ats`, `skeptic`, `market_researcher`.
- `tooling/registry.py` — tool access by role. `ORCHESTRATOR_TOOLS` = search_jobs, get_job, score_resume, extract_skills, propose_edit. `SYNTHESIS_TOOLS` is deliberately empty: **synthesis is read-only, editing is a separate explicit capability**.
- `judge.py` — independent assessment judge. `session.py` — in-memory session/run state and concurrency caps. `tracing.py` / `telemetry.py` — OTel spans, metadata only.

Endpoints: `POST /api/resume/agent/start`, `/chat`, `GET /api/resume/agent/{session_id}/state`, `POST .../apply`, `POST .../dismiss`.

### 3. AI Recruitment Team (V3) — `backend/recruitment_team/`

Persistent, multi-turn, DB-backed threads. This is the current active surface
(`RecruitmentTeamPanel.jsx`, `POST /api/recruitment-team/*`). PRD: `docs/v3-ai-recruitment-team-prd.md`.

**Ports and adapters.** Every model-touching collaborator has a `Scripted*` double and a
`LangChain*` live adapter, both exported from `recruitment_team/__init__.py`. Tests use Scripted;
`http_routes.py` FastAPI `Depends` wires LangChain. Add a new capability as a port, not an inline call.

| Port | Live adapter | Role |
|------|--------------|------|
| `ConversationModel` | `LangChainConversationModel` | Thread turns, preference extraction with evidence quotes |
| `DiscoveryPort` | `LangChainJobDiscovery` | Job search inside a thread |
| `RoleSuccessProfiler` | `EvidenceAssessedRoleSuccessProfiler` (generator + evidence assessor) | What success in the target role requires |
| `CandidateProfilerFactory` | `LangChainCandidateProfilerFactory` | Evidence-cited candidate profile |
| `TargetAssessmentRunner` | `OpenAgentTargetAssessmentRunner` | The open-agent assessment below |

**Open agent** (`recruitment_team/open_agent/`) — an open-ended orchestrator over the target-assessment
tool set. It reuses `resume_agent.create_resume_agent` but swaps in job-specific persona sub-agents built
from the versioned persona packs.

- `runner.py` — drives the graph, streams `TargetAssessmentUpdate`s, then runs a **mandatory independent judge**. The judge is the single non-optional step whatever reasoning path the orchestrator took; there is no separate synthesis-submission or per-specialist cross-check (those belonged to the retired bounded runner).
- `tools.py` — `ask_candidate` (HITL), `read_candidate_evidence`, `read_target_job`, `propose_resume_edit`.
- `guardrails.py` — `has_repeated_call`, called by name inside two tools on this path. **Guardrails limit volume, never choice**: they reject a materially identical repeat call, they never restrict which tool or persona the orchestrator may pick.
- `streaming.py` / `context.py` — SSE progress events and per-run contextvars.
- `persona_packs/v1/personas.json` — versioned, cited persona definitions loaded outside orchestration code (`RECRUITMENT_PERSONA_PACK_VERSION`).

**HITL pause.** `ask_candidate` is bound with `interrupt_on={"ask_candidate": True}`. Calling it pauses the
graph before any further tool executes; the candidate's next message resumes it via a LangGraph `Command`,
and that answer becomes citable evidence for later `propose_resume_edit` calls. Enforced by the interrupt,
not by prompt convention. Checkpoints persist to `OPEN_AGENT_CHECKPOINT_DB_PATH` (SqliteSaver) so a pause
survives a process restart and can resume on any worker.

**Handoff to v2:** `POST /api/recruitment-team/threads/{thread_id}/resume-agent-handoff` passes
target-assessment findings to the Resume Deep Agent for edit drafting.

**Coordinator loop (V4 slice 1, #146)** — `recruitment_team/coordinator/`. Ordinary chat turns used to be
one blind `model.invoke()` that could not see the jobs the thread had just found. `DeepAgentConversationModel`
replaces it with a real tool loop over `read_shortlist`, `search_jobs`, `read_target_job`,
`read_candidate_evidence`, `propose_resume_edit` and `ask_candidate`. It is the wired `ConversationModel`;
`LangChainConversationModel` stays as the single-shot adapter it is measured against.
Design and acceptance: `docs/v4-146-coordinator-loop.md`.

- Termination is `ToolStrategy(ConversationReply)`, not a hand-scan. `search_query` is now overwritten with
  the query that actually ran, so the field records an observation.
- `RepeatedCallMiddleware` (`coordinator/repeat_guard.py`) applies the volume guard to **every** bound tool,
  unlike the by-name calls on the assessment path above.
- `write_todos` is deliberately not bound. The model rewrote the same list until the turn died; see #147.
- Every turn gets its own graph id and replays the DB transcript. The checkpoint holds one thing, a paused
  graph between two HTTP requests, and the DB stays the system of record.
- `backend/scripts/trace_coordinator_turn.py` runs one live turn and writes a trace. The unit suite cannot
  see a model that will not stop; a scripted agent terminates by construction.

## MCP surfaces

Three files, two very different trust levels — do not blur them.

| File | Surface |
|------|---------|
| `mcp_tools.py` | Plain functions returning JSON strings. Both servers below are thin wrappers over it. |
| `mcp_server.py` | Local stdio server. Full set including private resume parsing, scoring, rewrite validation. |
| `mcp_public.py` | Hosted Streamable HTTP surface mounted at `/mcp` by `main.py`. Read-only job tools only, annotated `readOnlyHint`. Disabled unless `MCP_API_KEY` is set; bearer auth + rate limit run before any MCP work. |

Keep private resume tooling on the stdio server. See `docs/resume-agent-mcp.md`.

## Database

`init_db()` runs on startup; migrations are additive in `database.py` (see `test_database_migrations.py`).

- `users`, `usage_logs`, `password_reset_tokens`, `email_verification_tokens`
- `scraped_jobs` — cached jobs from all sources
  - `parsed_jd` JSON — skills, experience, education, responsibilities, `_analysis` (quality score, red flags, content hash)
  - `job_terms_preview` JSON — cached 8 ATS skill labels for fast list rendering
  - `jd_summary` / `jd_summary_status` — AI summary + generating/model_name/unavailable/failed
- `tracked_jobs`, `user_memories`, `power_match_snapshots`
- `tailored_resumes` (v1 pipeline sessions), `resume_versions` (labelled saves, master flag)
- V3: `recruitment_threads`, `recruitment_messages`, `recruitment_runs`, `recruitment_activity_events`, `candidate_profile_artifacts`, `target_assessment_artifacts`, `proposed_resume_edits`
- `interview_stories`, `story_usages`, `job_alert_preferences`, `job_alert_deliveries`

### Supporting modules

| File | Purpose |
|------|---------|
| `job_precompute.py` / `job_store.py` / `job_visibility.py` | Precomputed sector, salary floor, SSIC, skill-search fields; source-aware dedupe; public age cutoff |
| `company_taxonomy.py` | ACRA SSIC mapping from data.gov.sg; cache-only for user-facing searches |
| `jd_summary.py` / `jd_analyzer.py` / `backfill_enrichment.py` | Summary generation, quality/red-flag/injection scoring, batch backfill |
| `application_workspace.py` / `candidate_evidence.py` | Application workspaces and the candidate evidence graph |
| `interview_prep.py`, `job_alerts.py`, `send_job_alerts.py` | Stories/interview prep, matched-job alert emails (cron) |
| `prompt_safety.py` | `UNTRUSTED_DATA_RULE` + `xml_data_block` — wrap all untrusted text before it reaches a prompt |
| `security.py` / `sanitizer.py` | Rate limiter, body-size limit and security-header middleware; HTML stripping |

### Shared config

`shared/resume-classification.json` — single source of truth for section heading synonyms, bullet markers,
and classification rules. Consumed by both `resume_structurer.py` and `resumeHelpers.jsx`. Change it in one place.

## API surface

Full REST surface is in `backend/main.py` and `recruitment_team/http_routes.py`; `/docs` is served in
non-production. The non-obvious groups:

| Group | Notes |
|-------|-------|
| `POST /api/resume/tailor` → `/status` → `/result` | v1 pipeline: start returns `session_id`, poll status, fetch result (auto-saves a version when logged in) |
| `/api/resume/agent/*` | Resume Deep Agent v2 sessions |
| `/api/recruitment-team/threads/...` | V3. Every mutating call takes an `idempotency_key`; most have a `/stream` twin plus `GET /threads/{id}/events` for SSE |
| `/api/applications/workspaces/*` | Workspace create, agent review, submitted-resume upload |
| `/api/jobs/power-match`, `/api/jobs/{id}/match` | RAG matching, snapshot-cached |
| `/api/analytics/skills`, `/api/analytics/trends` | Market insights, TTL-cached (`ANALYTICS_*` knobs) |
| `/api/admin/*` | Backfill, embeddings backfill, JD analysis, skills-taxonomy rebuild, metrics |

Error mapping in V3 is centralised in `http_routes.py::_raise_http_error`: not-found → 404,
`InvalidCommand` → 422, any `*Unavailable` → 503.

## Environment variables

See `.env.example` for the full list. Load-bearing ones:

- `DATABASE_URL`, `JWT_SECRET`, `PORT`, `APP_ENV` (Railway also fails closed as production)
- `ALLOWED_ORIGINS` — CORS. Wildcard `*` raises at startup in production.
- `AUTH_MODE` (`password` | `cloudflare`) + `CF_ACCESS_*`; `TRUST_CLOUDFLARE_IP_HEADER`
- `sealion_api` … `sealion_api5` — SEA-LION keys, round-robin
- `MCP_API_KEY`, `MCP_REQUESTS_PER_MINUTE` — hosted MCP stays off until the key is set
- `ALLOWED_EMAIL_DOMAINS` (`*` = open signup), `ADMIN_EMAIL` / `ADMIN_PASSWORD`
- `TEST_DATABASE_URL` — overrides the temp DB the root `conftest.py` creates

Everything else in `config.py` is a named constant or a `_*_env()` helper with validation. Add new tunables
there, not as scattered `os.getenv` calls, and put product values in named constants rather than magic numbers.

## Invariants

1. **Pre-parse JDs at scrape time.** `parsed_jd` on `ScrapedJob` makes skill-gap analysis instant when the user clicks Tailor.
2. **Structured resume model.** Resume is sections/entries/bullets with stable IDs, not flat text. Enables surgical edits.
3. **Validation gates on every rewrite.** Numbers and dates must survive; hallucinated terms are rejected; AI phrases auto-replaced; critical gate failure reverts to the original. `propose_resume_edit` re-runs `run_all_gates` and additionally rejects any new numeric fact.
4. **Injectable vs non-injectable keywords.** Only inject skills the user plausibly has. Never fabricate.
5. **Proposed edits are pending until the candidate accepts.** No agent path writes a resume directly. Per-run cap: `OPEN_AGENT_MAX_PROPOSED_EDITS`.
6. **The judge is mandatory.** V3 target assessment is not complete without an independent judge pass; at most one configured correction and re-judge (`RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS`).
7. **HTTP 200 is not an acceptance criterion.** A request succeeds only when its semantic output validates and its durable artifact is complete. No fallback model, no truncation, no fake success on missing credentials. See `docs/v3-retry-recovery-policy.md`.
8. **Retries are ledgered, not nested.** Every retry belongs to one `logical_run_id` + stage + persisted attempt ledger; restarting a process does not reset a budget.
9. **Never leak private reasoning.** Persona prompts, judge output, and activity streams surface conclusions and citations, never chain-of-thought.

## Security

- All scraped data is sanitized (HTML stripped) before storage and display; no raw HTML rendering in the frontend
- Untrusted text goes through `prompt_safety.xml_data_block` before reaching any prompt
- JWT + bcrypt; per-account throttling for RAG and AI work; body-size and rate-limit middleware
- Validation gates prevent AI from fabricating metrics or skills
- API keys come from env, never logged or echoed
