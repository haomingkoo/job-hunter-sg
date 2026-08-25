# Job Hunter SG — Railway Deployment Guide

Start with the [maintainer handbook](docs/README.md). Use the
[operations runbook](docs/operations.md) for live health, freshness, incidents,
deployment receipts, rollback, and production-browser acceptance.

## Project Structure

```
job-hunter-sg/
├── backend/              ← Python FastAPI + scraper + auth
│   ├── main.py           ← API server (FastAPI + SQLAlchemy)
│   ├── scraper.py        ← Multi-portal job scraper
│   ├── requirements.txt
├── frontend/             ← React + Vite + Tailwind
│   ├── src/App.jsx       ← Main React app
│   ├── package.json
│   └── ...
├── Dockerfile            ← Builds frontend, then serves it from FastAPI
├── Dockerfile.crawler    ← Scheduled crawl and embedding worker
├── Dockerfile.alerts     ← Scheduled alert worker
├── .railway/railway.ts   ← All Railway services and schedules
├── .env.example          ← Environment variable reference
└── DEPLOY.md             ← This file
```

## Database

The backend uses SQLAlchemy with auto-migration. Tables are created automatically on startup — no manual migration step needed.

- **Local dev**: SQLite at `backend/jobhunter.db`
- **Production**: PostgreSQL on Railway (set `DATABASE_URL` env var)

On deploy, the app may backfill derived job metadata (`sector`, `salary_floor`,
`skills_flat`) in bounded batches. This keeps `/api/jobs` filters in SQL instead
of doing full-result filtering in Python.

## Environment Variables

Use [`.env.example`](.env.example) as the canonical variable reference. Configure
hosted values on the intended Railway service; Railway supplies `PORT`. Do not
maintain a second variable inventory in this deployment guide.

## Deploy to Railway

### 1. Install Railway CLI
```bash
npm install -g @railway/cli
railway login
```

### 2. Deploy through GitHub

GitHub is the release source of truth for the existing production project:

1. Push a branch and open a pull request.
2. Wait for the repository's GitHub Actions checks to pass, then merge into
   `main`.
3. Let Railway's GitHub integration deploy that `main` commit.
4. Match the Railway deployment commit to the merged Git SHA before accepting
   the release.

Do not use `railway init` for this repository's routine releases: it creates or
links a project rather than selecting the established production service. Do
not use `railway up` for a routine release either, because it can deploy local
files that have not passed through GitHub. The current auto-deploy path must not
be described as CI-gated until issue #223 verifies Railway's Wait for CI setting
and branch protection.

Use the Railway CLI only after confirming the linked project, environment, and
service with `railway status`, or use the provider dashboard. A new fork should
connect its GitHub repository to a new Railway project through the dashboard.

Set the variables documented in [`.env.example`](.env.example) only after
confirming the intended Railway target.

Railway infrastructure is defined once in `.railway/railway.ts`. The web image
builds the Vite frontend, copies `frontend/dist` into `backend/static`, and runs
FastAPI as one service.

Keep the web service at exactly one Railway replica and one Python worker. Agent,
tailoring, rate-limit, and account-deletion coordination is intentionally
in-process. Move those controls to shared storage before enabling multiple
replicas or workers.

## After Deployment

Use the [operations runbook](docs/operations.md) for deployment receipts, health
and freshness checks, incident diagnosis, rollback, and production-browser
acceptance. A Railway deployment status or health response alone is not release
acceptance.

## Quality Gates

The authoritative [CI and local gates](docs/ci.md) cover documentation links,
both dependency audits, backend compile/Ruff/ty/tests, frontend tests/build, and
Gitleaks. Dependabot tracks GitHub Actions, npm, and pip updates.

Run the canonical commands in that guide before pushing.

## API Reference

The canonical routes and authorization dependencies are defined by the
[FastAPI application](backend/main.py). In non-production environments, inspect
its generated `/docs` or `/openapi.json`; those endpoints are disabled in
production. Do not maintain a partial endpoint inventory here.

## Job Sources

The authoritative [source status matrix](docs/sources.md) distinguishes the two
scheduled sources, optional credentialed APIs, absent adapters, and
authorization-blocked planned portals. Do not infer production source coverage
from an adapter class or `/api/sources` alone.

## Accounts

There is one normal account type. Expensive RAG and AI work is authenticated
and throttled per account. `admin` is an operational role, not a paid plan.

## Admin Setup

Use the Account admin view for metrics. To assign the operational admin role directly:

- **SQLite (local)**: Use `sqlite3 jobhunter.db` in the backend directory.
- **PostgreSQL (Railway)**: Connect via `railway connect postgres` or use the Railway dashboard SQL editor.

Example: assign the admin role:
```sql
UPDATE users SET tier = 'admin' WHERE email = 'admin@example.com';
```
