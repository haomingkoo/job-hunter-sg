# Job Hunter SG

A free job aggregator and AI-powered resume coach built for job seekers in Singapore.

Search across multiple SG job portals in one place, get your resume scored and improved by AI, and track your applications — all in one app.

## Features

**Job Search**
- Search across MyCareersFuture, Careers@Gov, Adzuna, Jooble, and more simultaneously
- Pre-cached job database refreshed daily
- Similar job recommendations
- Salary data where available

**AI Resume Coach** (powered by AI)
- Upload your resume (PDF or DOCX)
- Get a 100-point score across Impact, Presentation, and Competencies
- AI-powered coaching with specific, actionable feedback
- Rewrite individual bullets with stronger action verbs
- Auto-format into ATS-friendly templates
- Download as DOCX in 4 template styles (Classic, Modern, Singapore Professional, Compact)

**Application Tracker** (requires sign-in)
- Track all your job applications in one place
- Follow-up reminders so nothing falls through the cracks
- Export to CSV
- Status tracking: Applied → Interview → Offer

**Privacy First**
- Free to use without signing in
- Resume data stored solely for AI coaching memory
- Never sold, shared, or used for training
- Delete your data anytime

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy and fill in your env vars
cp .env.example .env
# Edit .env with your API keys (see "API Keys" section below)

# Seed the job database
python seed_jobs.py --quick    # ~15 seconds, 5 keywords
python seed_jobs.py            # ~3 minutes, 20 keywords

# Start the server
python main.py
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

## API Keys

All API keys go in the `.env` file. See `.env.example` for the full list.

| Key | Where to get it | Cost | Required? |
|-----|----------------|------|-----------|
| `JWT_SECRET` | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` | Free | Yes (for auth) |
| `SKILLSFUTURE_CLIENTID` + `SKILLSFUTURE_SECRET` | [SSG Developer Portal](https://developer.ssg-wsg.sg) | Free | Optional (skills enrichment) |
| `sealion_api` | [SEA-LION](https://sea-lion.ai) by AI Singapore | Free (10 req/min) | Optional (AI features) |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | [Adzuna Developer](https://developer.adzuna.com) | Free tier | Optional (more job sources) |
| `JOOBLE_API_KEY` | [Jooble API](https://jooble.org/api/about) | Free | Optional (more job sources) |
| `ADMIN_EMAIL` + `ADMIN_PASSWORD` | You choose | - | Optional (admin account) |

**The app works with zero API keys** — MCF and CareersGov don't require authentication. API keys add more job sources and AI features.

## Architecture

```
frontend/          React + Vite + Tailwind CSS
backend/
  main.py          FastAPI app (30+ endpoints)
  scraper.py       7 job sources (MCF, CareersGov, Adzuna, Jooble, NodeFlair, Indeed, JobStreet)
  ai_service.py    AI integration with rate-limited round-robin
  resume_scorer.py 100-point scoring engine (Impact/Presentation/Competencies)
  resume_parser.py PDF + DOCX text extraction
  resume_templates.py  4 ATS-friendly DOCX templates
  auth.py          JWT + Cloudflare Access auth
  models.py        SQLAlchemy ORM (User, ScrapedJob, TrackedJob, UserMemory)
  database.py      SQLite (local) / PostgreSQL (production)
  sanitizer.py     Input sanitization (HTML, URL, resume text)
  seed_jobs.py     Pre-populate job database
```

## Deployment (Railway)

See [DEPLOY.md](DEPLOY.md) for full Railway deployment instructions.

```bash
# Quick deploy
railway login
railway init
railway add -p postgresql
cd backend && railway up
cd ../frontend && railway up
```

## Tiers

| Feature | Free (no login) | AISG (@aisg.sg) |
|---------|----------------|-----------------|
| Job search | Unlimited | Unlimited |
| ATS resume scoring | Unlimited | Unlimited |
| AI resume review | 3 sessions/day | 50/day |
| AI bullet rewrite | Unlimited in session | Unlimited in session |
| Save tracked jobs | No | Yes |
| Resume profile memory | No | Yes |
| CSV export | No | Yes |

## Contributing

This project is built to help job seekers in Singapore. If you have ideas or want to contribute, open an issue or reach out.

## License

MIT
