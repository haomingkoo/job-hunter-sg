# Job Hunter SG — Railway Deployment Guide

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
├── railway.toml          ← Main Railway service
├── railway.alerts.toml   ← Scheduled alert worker
├── .env.example          ← Environment variable reference
└── DEPLOY.md             ← This file
```

## Database

The backend uses SQLAlchemy with auto-migration. Tables are created automatically on startup — no manual migration step needed.

- **Local dev**: SQLite (default `sqlite:///./jobhunter.db`)
- **Production**: PostgreSQL on Railway (set `DATABASE_URL` env var)

On deploy, the app may backfill derived job metadata (`sector`, `salary_floor`,
`skills_flat`) in bounded batches. This keeps `/api/jobs` filters in SQL instead
of doing full-result filtering in Python.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | No | `sqlite:///./jobhunter.db` | DB connection string. Use Postgres URL on Railway. |
| `JWT_SECRET` | **Yes** (prod) | — | Secret key for signing JWT tokens. Generate a random string. |
| `PORT` | No | `8000` | Server port. Railway sets this automatically. |
| `APP_ENV` | **Yes** (prod) | development | Set to `production` on hosted deployments. Railway presence also fails closed. |
| `ALLOWED_ORIGINS` | No | local frontend URLs | Comma-separated CORS origins. Wildcards are rejected in production. |
| `TRUST_CLOUDFLARE_IP_HEADER` | No | `0` | Set to `1` only when all public origins are Cloudflare-proxied and direct Railway domains are removed. Restores per-visitor throttling from `CF-Connecting-IP`. |
| `AUTH_MODE` | No | `password` | Use verified email/password accounts for public signup, or `cloudflare` for a restricted Access deployment. |
| `CF_ACCESS_TEAM_DOMAIN` | Cloudflare mode | — | Cloudflare Access team domain used to validate JWT issuer and keys. |
| `CF_ACCESS_AUD` | Cloudflare mode | — | Access application audience tag. |
| `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` | Password signup | — | Required to deliver verification and password-reset links. Signup fails closed when email is unavailable. |
| `ACCOUNT_AI_PER_DAY` | No | `500` | Daily AI/RAG requests allowed per account. |
| `VITE_API_URL` | No | `""` | (Frontend) Backend API URL. Empty = same-origin. |

## Deploy to Railway

### 1. Install Railway CLI
```bash
npm install -g @railway/cli
railway login
```

### 2. Deploy Main Service
```bash
railway init
railway up
railway domain
```

Set environment variables:
```bash
railway variables set JWT_SECRET=<your-random-secret>
railway variables set DATABASE_URL=<postgres-url-from-railway>
railway variables set ALLOWED_ORIGINS=https://job.kooexperience.com
railway variables set AUTH_MODE=password
railway variables set APP_ENV=production
railway variables set ACCOUNT_AI_PER_DAY=500
railway variables set TRUST_CLOUDFLARE_IP_HEADER=0
```

Keep `TRUST_CLOUDFLARE_IP_HEADER=0` unless the origin rejects every request that
did not come through Cloudflare. A custom domain alone does not provide that
boundary.

Railway uses `railway.toml`, which points at the root `Dockerfile`. The image
builds the Vite frontend, copies `frontend/dist` into `backend/static`, and runs
FastAPI as one service.

Keep the web service at exactly one Railway replica and one Python worker. Agent,
tailoring, rate-limit, and account-deletion coordination is intentionally
in-process. Move those controls to shared storage before enabling multiple
replicas or workers.

## Post-Deploy Checks

Run these checks after a production deploy:

- `https://job.kooexperience.com/api/health` returns healthy.
- `https://job.kooexperience.com/robots.txt` is reachable.
- `https://job.kooexperience.com/sitemap.xml` is reachable.
- `https://job.kooexperience.com/llms.txt` is reachable.
- Railway memory chart is stable after startup backfills complete.
- `/api/jobs?sector=Engineering&per_page=20` returns quickly and does not spike memory.

Submit the canonical URL and sitemap in Google Search Console and Bing Webmaster
Tools. ChatGPT search visibility depends on normal web indexing plus allowing
OpenAI's search crawler in `robots.txt`.

## Quality Gates

GitHub Actions runs backend compile checks, Ruff, the scoped ty baseline,
backend tests, frontend tests/build, and Gitleaks secret scanning. Dependabot
tracks GitHub Actions, npm, and pip updates.

Recommended local checks before pushing:

```bash
python -m compileall -q backend
ruff check backend tests
ty check
cd frontend && npm test -- --run && npm run build
```

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/auth/signup` | POST | No | Create an unverified account and send a verification link |
| `/api/auth/verify-email` | POST | No | Verify email and return the first JWT |
| `/api/auth/login` | POST | No | Login, returns JWT |
| `/api/auth/me` | GET | Yes | Current user info |
| `/api/auth/change-password` | POST | Yes | Change password and invalidate older JWTs |
| `/api/account` | DELETE | Yes | Permanently delete the account and user-owned data |
| `/api/search?q=keyword` | POST | Admin | Run a live multi-source refresh |
| `/api/jobs` | GET | No | Cached job listings |
| `/api/tracked` | GET | Yes | User's tracked jobs |
| `/api/tracked` | POST | Yes | Track a job |
| `/api/tracked/{id}` | PUT | Yes | Update tracked job |
| `/api/tracked/{id}` | DELETE | Yes | Remove tracked job |
| `/api/tracked/export` | GET | Yes | CSV export of tracked jobs |
| `/api/contact` | POST | No | Contact form submission |

## Sources Scraped

| Source | Key | Method |
|--------|-----|--------|
| MyCareersFuture | `mcf` | API: `api.mycareersfuture.gov.sg/v2/search` |
| Careers@Gov | `careersgov` | OpenGovSG pre-parsed JSON |
| NodeFlair | `nodeflair` | HTML scrape |
| Indeed SG | `indeed` | HTML scrape |
| JobStreet | `jobstreet` | HTML scrape |

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
