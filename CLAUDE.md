# CLAUDE.md

Start at [docs/README.md](docs/README.md). Setup is in [docs/getting-started.md](docs/getting-started.md), gates in [docs/ci.md](docs/ci.md), PR rules in [CONTRIBUTING.md](CONTRIBUTING.md), domain terms in [CONTEXT.md](CONTEXT.md).

## Test and build (what CI runs, from repo root)

```bash
python scripts/check_docs.py                         # Markdown link check; covers this file too
python -m compileall -q backend
ruff check backend tests
ty check --output-format concise                     # scoped to backend/schemas.py + backend/resume_agent
PYTHONPATH=backend python -m pytest backend/tests tests -q
cd frontend && npm ci --legacy-peer-deps && npm test -- --run && npm run build
```

- Root `conftest.py` forces `DATABASE_URL` to a temp SQLite DB, so tests never touch a real DB.
- Default tests must never call SEA-LION, MCP or other live sources. Live model tests are opt-in with `RUN_LIVE_SEALION=1`.
- Pre-commit blocks commits to `main` and runs detect-secrets against `.secrets.baseline`.

## Deploy

- Railway project `victorious-rejoicing` auto-deploys every push to `main` via the GitHub integration. Services: web `job-hunter-sg`, crawl cron `enthusiastic-gratitude` (22:00 UTC) and alerts cron `job-alerts-daily` (23:00 UTC).
- Service config lives in `.railway/railway.ts`. The `railway*.toml` files are empty stubs and must stay that way.
- No watch paths are set, so a docs-only merge still rebuilds and redeploys.
- Never `railway up` or `railway init` for a release. Merge to `main` and let Railway build that commit.
- A release counts only when `Production acceptance` confirms `/api/health` serves the merged SHA. See [docs/production-release.md](docs/production-release.md).
- Keep the web service at one replica and one Python worker. Agent, rate-limit and deletion coordination is in-process.

## Gotchas

- A green suite does not prove an agent turn works, because scripted agents always terminate. Check agent-path changes in the real UI or with the live opt-in tests.
- Qwen SEA-LION v4.5 returns `reasoning_content` unless thinking is disabled (`SEALION_DISABLE_THINKING_MODELS`). The SMART model returns nothing under a tight token budget, so keep the `SMART_MIN_MAX_TOKENS` floor.
- Add tunables to `backend/config.py` as validated constants, not scattered `os.getenv` calls.
- Resume heading and bullet rules have one source, `shared/resume-classification.json`, read by both backend and frontend.

## Hard constraints

- No agent path writes a resume directly. Proposed edits stay pending until the candidate accepts them.
- V3 target assessment always needs the independent judge pass.
- HTTP 200 is not success. Use no fallback model, no truncation, and never return fake success on missing credentials ([docs/v3-retry-recovery-policy.md](docs/v3-retry-recovery-policy.md)).
- Wrap untrusted text with `prompt_safety.xml_data_block` before it reaches a prompt.
- Private resume tools stay on the stdio `mcp_server.py`. Hosted `mcp_public.py` (`/mcp`) is read-only job tools behind `MCP_API_KEY`.
- Never surface chain-of-thought in persona, judge or activity output.
