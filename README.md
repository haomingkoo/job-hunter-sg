# Job Hunter SG

AI-powered job aggregator, resume coach, and career toolkit for the Singapore job market.

Searches MyCareersFuture and Careers@Gov in one interface. Scores your resume, rewrites bullets with validation gates to prevent hallucination, and generates tailored cover letters. Semantic matching via RAG finds jobs keyword search would miss.

**[Try it live](https://job.kooexperience.com)** | **[Blog Post](https://kooexperience.com/blog/posts/job-hunter.html)** | **[Portfolio](https://kooexperience.com)**

![License](https://img.shields.io/badge/license-AGPL--3.0-blue)
![AI](https://img.shields.io/badge/AI-SEA--LION-purple)
![Tests](https://img.shields.io/badge/tests-320%2B-green)

## Screenshots

| | |
|---|---|
| ![Jobs Search](docs/screenshots/jobs-search.jpeg) | ![Upload Options](docs/screenshots/upload-options.jpeg) |
| **Job Search** — MCF + Careers@Gov with filters | **Upload** — PDF, paste, AI chat, or demo |
| ![Templates](docs/screenshots/templates.jpeg) | ![Bullet Feedback](docs/screenshots/bullet-feedback.jpeg) |
| **Templates** — 8 professional styles | **AI Feedback** — per-bullet coaching |
| ![AI Rewrite](docs/screenshots/ai-rewrite.jpeg) | ![Market Insights](docs/screenshots/market-insights.jpeg) |
| **AI Rewrite** — 3 options per bullet | **Market Insights** — sector & skill trends |
| ![Smart Match](docs/screenshots/smart-match.jpeg) | ![Export](docs/screenshots/export.jpeg) |
| **Smart Match** — RAG-powered job matching | **Export** — DOCX with final score |

---

## Features

### Job Search
- Aggregates MyCareersFuture (~12K jobs) and Careers@Gov (~3K jobs) via public APIs
- Admin-triggered crawl with full pagination; extensible `SOURCE_MAP` supports 5 additional scrapers
- Filter by seniority, job type, salary range, skills
- ATS skill tags extracted at scrape time (413 known skills, ~50ms/job)

### Resume Builder
- Upload PDF/DOCX or build from scratch with AI chat
- 8 professional templates (Classic, Modern, SG Professional, Compact, Executive, Creative, Technical, Minimal)
- Inline click-to-edit with drag-and-drop bullet reordering (Framer Motion)
- Add/delete sections, entries, bullets with one click
- Download as DOCX via python-docx

### AI Resume Coach (SEA-LION)
- ATS scoring (0-100) across Impact, Presentation, Competencies
- Per-bullet feedback with annotations (Solid Impact, Review, Verb Check)
- AI rewrite with 3 options per bullet (32B model, <2s)
- 7-stage tailoring pipeline for specific JDs (70B + 32B, 45-60s)
- 5 validation gates on every AI rewrite: fact preservation, AI phrase detection (84 patterns), keyword verbatim, length sanity, hallucination detection
- Injectable vs non-injectable keyword classification — AI can only add skills the user plausibly has
- Custom summary generation with user prompts

### AI Resume Chat Builder
- Conversational interface that builds your resume from scratch
- Coaches you to add metrics and quantified achievements
- Suggests trending skills from the job database
- Generates structured resume dropped directly into the editor

### Cover Letter Generator
- Generate from resume + job description
- Custom direction ("emphasize leadership", "keep it concise")
- Edit inline, copy, or download

### Smart Match (RAG)
- Semantic job matching using sentence-transformers/all-MiniLM-L6-v2 (384-dim)
- Hybrid scoring: keyword overlap + cosine similarity
- Suitability scores, skill gap analysis, bridge paths
- Pre-embedded jobs for instant matching

### Application Tracker
- Track applications: Applied, Interview, Offer
- Follow-up reminders
- Status tracking per job

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy + SQLite/PostgreSQL |
| Frontend | React 19 + Vite + Tailwind CSS + Framer Motion |
| AI | SEA-LION (AI Singapore) — 32B interactive, 70B reasoning |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Skills | SSG-WSG SkillsFuture Skills Framework API |
| Rate Limiting | In-memory token bucket, 5 API keys cycled (~45 req/min) |
| Auth | JWT + bcrypt, tier-based rate limiting |
| Deploy | Railway (Docker), persistent PostgreSQL |

---

## Quick Start

```bash
# Backend
cd backend
pip install -r requirements.txt
python main.py  # starts on :8000

# Frontend
cd frontend
npm install
npm run dev     # starts on :5173, proxies /api to :8000
```

---

## Testing

```bash
# Backend (222 tests)
cd backend && python -m pytest tests/ -q

# Frontend (98 tests)
cd frontend && npx vitest run
```

---

## Architecture

```
scrapers (MCF, CareersGov, +5 pluggable)
    ↓
jd_preparser.py (50ms/job → skills, exp, education)
    ↓
scraped_jobs table (parsed_jd JSON, ATS terms, JD summary)
    ↓
embedding_service.py (MiniLM-L6-v2, 384-dim vectors)

User uploads resume
    ↓
resume_structurer.py → sections/entries/bullets with IDs
    ↓
resume_scorer.py → 0-100 score (Impact/Presentation/Competencies)
    ↓
tailoring_pipeline.py (7 stages: Analyze → Strategize → Cleanup → Rewrite → Polish → Summarize → Validate)
    ↓
validation_gates.py (5 gates, revert on failure)
    ↓
DOCX export via python-docx

shared/resume-classification.json ← single source of truth for both backend + frontend
```

---

## API Highlights

60+ endpoints total. Key ones:

| Endpoint | Description |
|----------|-------------|
| `GET /api/jobs` | Browse cached jobs with filters |
| `GET /api/search?q=...` | Full-text job search |
| `POST /api/resume/score` | Score resume 0-100 |
| `POST /api/resume/upload` | Upload PDF/DOCX, extract text |
| `POST /api/resume/tailor` | Start 7-stage tailoring pipeline |
| `GET /api/resume/tailor/{id}/status` | Poll pipeline progress |
| `POST /api/ai/rewrite` | AI bullet rewrite (3 options) |
| `POST /api/ai/cover-letter` | Generate cover letter |
| `POST /api/ai/resume-chat` | Conversational resume builder |
| `GET /api/jobs/power-match` | Smart Match with RAG |
| `POST /api/admin/seed` | Trigger job crawl (admin) |

---

## Environment Variables

```bash
DATABASE_URL=sqlite:///./jobhunter.db
JWT_SECRET=your-secret
sealion_api=your-sealion-key          # supports sealion_api2 through sealion_api5
ALLOWED_EMAIL_DOMAINS=*               # or comma-separated domains
ALLOWED_ORIGINS=http://localhost:5173  # CORS
```

See `.env.example` for full list.

---

## License

[AGPL-3.0](LICENSE) — Free to use and modify. Must share changes if deployed as a service. Attribution required.

Built by [Haoming Koo](https://kooexperience.com).
