# Job Hunter SG — Railway Deployment Guide

## Project Structure

```
job-hunter-sg/
├── backend/              ← Python FastAPI + scraper + auth
│   ├── main.py           ← API server (FastAPI + SQLAlchemy)
│   ├── scraper.py        ← Multi-portal job scraper
│   ├── requirements.txt
│   └── .env.example
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
| `ALLOWED_ORIGINS` | No | `*` | Comma-separated CORS origins. Set to frontend URL in production. |
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
```

Railway uses `railway.toml`, which points at the root `Dockerfile`. The image
builds the Vite frontend, copies `frontend/dist` into `backend/static`, and runs
FastAPI as one service.

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
| `/api/auth/signup` | POST | No | Create account |
| `/api/auth/login` | POST | No | Login, returns JWT |
| `/api/auth/me` | GET | Yes | Current user info |
| `/api/search?q=keyword` | GET | Optional | Search all SG job portals (rate-limited) |
| `/api/jobs` | GET | No | Cached job listings |
| `/api/tracked` | GET | Yes | User's tracked jobs |
| `/api/tracked` | POST | Yes | Track a job |
| `/api/tracked/{id}` | PUT | Yes | Update tracked job |
| `/api/tracked/{id}` | DELETE | Yes | Remove tracked job |
| `/api/tracked/export` | GET | Pro | CSV export of tracked jobs |
| `/api/tiers` | GET | No | Pricing/tier info |
| `/api/contact` | POST | No | Contact form submission |

## Sources Scraped

| Source | Key | Method |
|--------|-----|--------|
| MyCareersFuture | `mcf` | API: `api.mycareersfuture.gov.sg/v2/search` |
| Careers@Gov | `careersgov` | API: Workday backend |
| NodeFlair | `nodeflair` | HTML scrape |
| Indeed SG | `indeed` | HTML scrape |
| JobStreet | `jobstreet` | HTML scrape |

## Tiers & Pricing

| Feature | Free | Pro ($5/mo) |
|---------|------|-------------|
| Searches per day | 5 | 50 |
| Tracked jobs | 20 | Unlimited |
| CSV export | No | Yes |

Tier limits are enforced server-side. Users default to the Free tier on signup. To upgrade a user to Pro, update their `tier` field in the database (payment integration TBD).

## Admin Setup

There is no admin UI yet. To manage users or tiers directly:

- **SQLite (local)**: Use `sqlite3 jobhunter.db` in the backend directory.
- **PostgreSQL (Railway)**: Connect via `railway connect postgres` or use the Railway dashboard SQL editor.

Example: upgrade a user to Pro:
```sql
UPDATE users SET tier = 'pro' WHERE email = 'user@example.com';
```
