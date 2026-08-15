# Operations Runbook

This runbook covers the current Railway topology. Use the provider dashboard or
Railway CLI from a repository already linked to the intended project and
environment. Confirm the target before any command that changes state.

## Service map and schedule

| Service | Configuration | Command | Schedule/health |
|---|---|---|---|
| Web | `railway.toml`, `Dockerfile` | `python main.py` | Continuous; `/api/health` |
| Full job crawl | `railway.seed.toml`, `Dockerfile` | `python seed_jobs.py --full` | Daily 22:00 UTC |
| Matched alerts | `railway.alerts.toml`, `Dockerfile.alerts` | `python send_job_alerts.py` | Daily 23:00 UTC |

Keep the web service at one replica and one Python worker. Active-run
coordination, caches, and rate limiting are not all shared across processes.

## Routine health

1. Confirm the intended Railway project, environment, and service.
2. Check both API and database connectivity:

   ```bash
   curl --fail https://job.kooexperience.com/api/health
   ```

   A 200 response proves only that the process can answer and run `SELECT 1`.
3. Inspect recent web logs for startup migration/backfill failures, client error
   reports, exhausted provider retries, or repeated 5xx responses.
4. Inspect the last crawl and alert executions separately. A healthy web service
   does not prove either cron ran.
5. Check live source freshness in PostgreSQL with a read-only query:

   ```sql
   SELECT source,
          COUNT(*) AS public_visible_jobs,
          MAX(scraped_at) AS newest_scrape,
          MAX(posted_at_sort) AS newest_posting
   FROM scraped_jobs
   WHERE hidden = 0
     AND posted_at_sort IS NOT NULL
     AND posted_at_sort <> ''
     AND posted_at_sort::timestamptz >= NOW() - INTERVAL '60 days'
     AND (closing_date IS NULL OR closing_date = '' OR closing_date >= CURRENT_DATE::text)
   GROUP BY source
   ORDER BY source;
   ```

Replace `60 days` when production overrides `PUBLIC_JOB_MAX_AGE_DAYS`. The
public `/api/jobs` response remains the acceptance check because application
visibility is authoritative. Compare counts and newest timestamps with the
previous successful crawl. A PID, green schedule badge, or unchanged total is
not proof of fresh writes.

## Crawl diagnosis

The full crawl is healthy only when logs show each active source completed,
row counts passed its minimum-health guard, writes committed, and stale rows
were retired after completion. Diagnose in this order:

1. Upstream request/parse errors and timeouts.
2. Raw and unique row counts versus the source health threshold.
3. New, updated, reactivated, duplicate, retired, and error totals.
4. The read-only freshness query above.
5. A public `/api/jobs?source=...` request and a rendered Jobs filter check.

Do not manually hide/delete rows after an incomplete crawl. Fix or retry the
source; the crawler deliberately preserves the prior corpus on partial failure.

## Alert diagnosis

Alert delivery requires PostgreSQL access, due opted-in preferences, and SMTP
configuration. Run a local or Railway-shell dry run before sending:

```bash
cd backend
../.venv/bin/python send_job_alerts.py --dry-run
```

Inside the Railway image, where the backend is the working directory, use
`python send_job_alerts.py --dry-run`.

The dry run must not send mail or write delivery history. For a real run, treat
a missing email configuration or any non-zero `errors` count as failure even if
the process started successfully.

## Deployment receipt

For every production release, record in the PR or release note:

- immutable Git commit SHA;
- GitHub Actions run and conclusion;
- Railway deployment ID/status for that same commit;
- database migration/backfill outcome from startup logs;
- health response after deployment;
- production-browser acceptance result and tested viewport(s);
- any skipped live checks with a reason.

GitHub CI success, image build success, Railway “running,” HTTP 200, and browser
acceptance are separate gates. Do not collapse them into a single “deployed”
claim.

## Incident diagnosis

| Symptom | First checks | Avoid |
|---|---|---|
| Health 503 | PostgreSQL availability, `DATABASE_URL`, pool errors, startup logs | Restart loops before preserving error evidence |
| Jobs stale/empty | Cron receipt, source health counts, newest writes, public visibility cutoff | Deleting the cached corpus after a partial crawl |
| AI unavailable | Provider status, configured key count, timeout/retry telemetry, account quota | Logging prompts, resumes, or API keys |
| Recruitment run stuck | Durable run/message/event rows, latest event sequence, server logs, process restart timing, and persistence of `OPEN_AGENT_CHECKPOINT_DB_PATH` | Treating a connected SSE request or container-local checkpoint as proof the run can resume |
| Frontend blank/error | `/api/health`, browser console/network, `/api/client-error` logs, deployed asset SHA | Using a backend 200 as UI acceptance |
| Alerts missing | Alert cron receipt, dry-run stats, SMTP settings, due preferences, delivery history | Sending a live test to all users |

Preserve timestamps, deployment ID, commit SHA, request/run ID, safe error type,
and affected counts. Never paste tokens, resumes, prompt contents, or private job
notes into an issue.

## Database safety

- Production is PostgreSQL; local development is SQLite. Never copy a local
  SQLite file over production or point local tests at production.
- Startup migrations in `backend/database.py` are lightweight and additive,
  not a substitute for a backup before destructive schema/data work.
- Use read-only queries first and resolve exact row counts before mutation.
- Prefer application-level soft deletion/retirement where implemented.
- Do not use `railway run` for private-network database commands: it runs on the
  local machine. Use a Railway shell/session or the provider's database tools.
- Back up and verify restore scope before bulk update, delete, or schema work.

## Rollback

1. Stop further rollout and record the failing deployment ID/commit.
2. Preserve logs and browser/network evidence.
3. Redeploy the last known-good immutable commit/image in Railway.
4. Recheck startup logs, `/api/health`, source freshness, and the affected user
   journey in a browser.
5. Treat database rollback separately. Additive schema may be left in place;
   never reverse data changes without a verified backup and explicit plan.

## Production-browser acceptance

Use a real browser after the exact production deployment when a change affects
layout, navigation, authentication continuity, streaming, reload/recovery,
downloads/uploads, or other browser-owned behavior. At minimum:

1. Record URL, commit/deployment, browser, viewport, and account type.
2. Exercise the changed journey, not just the landing page.
3. Verify visible success, persistence after reload when applicable, and the
   absence of console/network errors.
4. For responsive work, inspect at least one desktop and one mobile viewport and
   record geometry or screenshots without private data.
5. State exactly what was not tested.

Component tests and local browser checks are valuable but do not prove the
deployed production journey.
