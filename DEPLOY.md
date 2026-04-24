# Job Hunter SG — Railway Deployment Guide

## Project Structure

```
job-hunter-sg/
├── backend/              ← Python FastAPI + scraper + auth
│   ├── main.py           ← API server (FastAPI + SQLAlchemy)
│   ├── scraper.py        ← Multi-portal job scraper
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/             ← React + Vite + Tailwind
│   ├── src/App.jsx       ← Main React app
│   ├── package.json
│   ├── Dockerfile
│   └── ...
├── .env.example          ← Environment variable reference
├── CLAUDE.md             ← Project context for Claude Code
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

## Deploy to Railway with Claude Code

Open Claude Code in this directory and say:

```
Deploy this to Railway as two services:
1. Backend (Python FastAPI) from the /backend folder
2. Frontend (React/Vite) from the /frontend folder

The frontend needs VITE_API_URL env var pointing to the backend Railway URL.
The backend needs DATABASE_URL, JWT_SECRET, PORT=8000, and ALLOWED_ORIGINS.
Use `railway init` and `railway up` for each service.
```

## Manual Railway Deployment

### 1. Install Railway CLI
```bash
npm install -g @railway/cli
railway login
```

### 2. Deploy Backend
```bash
cd backend
railway init          # Creates a new Railway project
railway up            # Deploys the backend
railway domain        # Get the public URL (e.g., backend-xxx.up.railway.app)
```

Set environment variables for the backend service:
```bash
railway variables set JWT_SECRET=<your-random-secret>
railway variables set DATABASE_URL=<postgres-url-from-railway>
railway variables set PORT=8000
railway variables set ALLOWED_ORIGINS=https://frontend-xxx.up.railway.app
```

### 3. Deploy Frontend
```bash
cd ../frontend

railway init
railway variables set VITE_API_URL=https://backend-xxx.up.railway.app
railway up
railway domain        # Get the frontend URL
```

### 4. Alternative: Single-Service Deploy
If you prefer one service, you can serve the frontend from FastAPI:
```bash
cd frontend && npm install && npm run build
cp -r dist/ ../backend/static/
# Then add StaticFiles mount in backend/main.py
```

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

GitHub Actions runs backend compile checks, Ruff critical lint, frontend build,
and Gitleaks secret scanning. Dependabot tracks GitHub Actions, npm, and pip
updates.

Recommended local checks before pushing:

```bash
python -m compileall -q backend
ruff check backend tests
cd frontend && npm run build
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
