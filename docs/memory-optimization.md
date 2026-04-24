# Memory & Performance Optimization Log

Started: 2026-04-20 after Railway memory usage spiked and a production log
review found a frontend polling bug generating ~800 requests in 2.5 hours
from a single idle tab.

## Shipped

### PR #12 — polling throttle + backend memory
- **Frontend** (`ResumeTab.jsx`): `/api/ai/status` polls every 60s instead of
  10s, and pauses entirely when the browser tab is hidden (Page Visibility
  API). Unmount handled by `useEffect` cleanup.
- **Backend** (`embedding_service.py`): `_MATRIX_TTL` 5min → 24h. Scrapes
  already call `invalidate_matrix_cache()` on new data, so the 5-min rebuild
  was pure waste. `_refresh_matrix_if_stale` now releases the old matrix
  before loading new rows, streams via `yield_per(500)`, and clears the
  Python `vectors` list after numpy conversion. Peak rebuild memory
  roughly 3× → 1× matrix size.
- **Backend** (`main.py`): `_power_match_cache` now sweeps expired entries
  on every read. Was unbounded — grew one entry per user forever.

### PR #13 — pipeline eviction + stdout logging
- **Backend** (`tailoring_pipeline.py`): `_cleanup_expired_pipelines` now
  evicts errored and stuck-mid-run sessions, not just completed ones.
  `set_error` stamps `_completed_at`; `PipelineState.__init__` stamps
  `_created_at` as fallback. `run_pipeline` sweeps on insert.
- **Backend** (`main.py`): `logging.basicConfig(stream=sys.stdout,
  force=True)` so Railway stops tagging every INFO line as `[err]`.

### Current change — precompute request-time work + quality gates
- **Backend** (`ScrapedJob`): added stored `sector`, `salary_floor`, and
  `skills_flat` fields. New/updated jobs compute these on ingest, and startup
  backfills older rows in bounded batches.
- **Backend** (`GET /api/jobs`): sector and salary filters now stay in SQL
  pagination instead of loading the full result set into Python.
- **Backend** (`skill_extractor.py`): dynamic skill dictionary rebuild streams
  rows with `yield_per(500)` instead of materializing all JD descriptions.
- **Backend** (`backfill_embeddings.py`, `/api/admin/backfill-embeddings`):
  embedding backfills process bounded ID batches instead of `query.all()`.
- **Backend** (`PowerMatchSnapshot`): Power Match stores ranked results by
  resume hash + job corpus marker + limit. Repeat visits return the persisted
  result while preserving first-run matching quality.
- **Tooling**: added GitHub Actions, Ruff critical checks, Gitleaks, Dependabot,
  and lightweight pre-commit hooks.
- **SEO/AI search**: added explicit OpenAI crawler robots rules, sitemap,
  `llms.txt`, and richer social/structured metadata.

## Monitoring after deploy

- Railway memory chart — expect flatter baseline and no 5-min sawtooth.
- Log tags — INFO lines should now appear as `[inf]`, not `[err]`.
- `/api/ai/status` request rate — should drop ~85% (60s poll + hidden-tab
  pause vs prior 10s unconditional).
- `/api/jobs` latency with `sector` or `min_salary` filters — should stop
  spiking from Python-side full-result slicing.
- `/api/jobs/power-match` repeat visits — should return from snapshot when
  resume and job corpus are unchanged.

Wait at least 24 hours after deploy before doing more memory work. Need a
clean baseline to judge whether the next tier is worth the effort.

## Outstanding — Tier 2 (medium effort)

- **Add proper migration tooling**: lightweight auto-migrations are convenient,
  but Alembic would make production schema changes auditable.
- **Move embedding model out of the web process** if Railway memory remains
  high after the snapshot/precompute pass. Keep match quality, but run model
  work in a worker or scheduled job.

## Outstanding — Tier 3 (migration work, biggest gains)

- **`skills_flat` pg_trgm GIN index** on Postgres. The column now exists; a
  trigram index would make text matching cheaper on large job corpora.
- **`yield_per()` on admin endpoints** that load all jobs before batching:
  `/api/admin/jd-analysis`. Low priority — only hits memory when an admin
  triggers it.
- **Precompute analytics snapshots** into DB or static JSON so
  `/api/analytics/skills` does not need to scan jobs on cache misses.

## Small items (unrelated to memory)

- Duplicate `POST /api/resume/score` seen at 14:32:25 in prod logs — same
  millisecond, two POSTs from different Railway proxy IPs. Could be React
  StrictMode-style double-fire or a UI double-click. Add debounce or
  idempotency if it recurs.
- Git history rewrite `@aiap.sg` → `haomingkoo@gmail.com` for this repo.
  Requires force-push to main; Railway would redeploy but code identical.
  Paused because of the force-push-to-main caveat.

## Verified safe (not issues)

- `POST /api/admin/backfill` and `POST /api/admin/backfill-embeddings`
  both require a valid `ADMIN_API_KEY` via `Authorization: Bearer <key>`
  header — 403 otherwise. The 11:32 probe that got a 404 was a GET
  against a POST-only route, unrelated to auth.
- Module-scope singletons `_filter_meta_cache`, `_analytics_cache`,
  `_backfill_progress`, `_embedding_backfill_progress`, `_dynamic_cache`,
  `_tier2_cache` are bounded dicts overwritten in place — no leak.
