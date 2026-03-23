# Job Hunter SG

Singapore job aggregator + application tracker with multi-user support.

## Architecture

- **Backend**: FastAPI + SQLAlchemy + SQLite (Postgres on Railway)
- **Frontend**: React + Vite + Tailwind CSS
- **Scraping**: requests + BeautifulSoup (MCF, CareersGov, NodeFlair, Indeed, JobStreet)
- **Auth**: JWT + bcrypt
- **Deploy**: Railway (Docker)

## Commands

```bash
# Backend
cd backend
pip install -r requirements.txt
python main.py  # starts on PORT=8000

# Frontend
cd frontend
npm install
npm run dev     # starts on :5173, proxies /api to :8000

# Both (production)
# Deploy backend and frontend as separate Railway services
```

## API Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| POST /api/auth/signup | No | Create account |
| POST /api/auth/login | No | Login |
| GET /api/auth/me | Yes | Current user |
| GET /api/search?q=... | Optional | Search jobs (rate-limited) |
| GET /api/jobs | No | Cached jobs |
| GET /api/tracked | Yes | User's tracked jobs |
| POST /api/tracked | Yes | Track a job |
| PUT /api/tracked/{id} | Yes | Update tracked job |
| DELETE /api/tracked/{id} | Yes | Remove tracked job |
| GET /api/tracked/export | Pro | CSV export |
| GET /api/tiers | No | Pricing info |
| POST /api/contact | No | Contact form |

## Tiers

- **Free**: 5 searches/day, 20 tracked jobs
- **Pro** ($5/mo): 50 searches/day, unlimited tracking, CSV export

## Environment Variables

- `DATABASE_URL` — DB connection string (default: sqlite:///./jobhunter.db)
- `JWT_SECRET` — Secret for JWT tokens
- `PORT` — Server port (default: 8000)
- `ALLOWED_ORIGINS` — CORS origins (default: *)

## Security

- All scraped data is sanitized (HTML stripped) before storage and display
- JWT auth with bcrypt password hashing
- Rate limiting by tier
- No raw HTML rendering in frontend
