# Job Hunter SG

AI-powered job search, resume tailoring, and career tools for Singapore.

Browse 72,000+ jobs from MyCareersFuture and CareersGov. Build, score, and tailor your resume with AI. Generate cover letters. Match semantically with RAG.

**[Try it live](https://job.kooexperience.com)** | **[Portfolio](https://kooexperience.com)**

![License](https://img.shields.io/badge/license-AGPL--3.0-blue)
![Jobs](https://img.shields.io/badge/jobs-72%2C000%2B-green)
![AI](https://img.shields.io/badge/AI-SEA--LION-purple)

## Screenshots

| | |
|---|---|
| ![Jobs Search](docs/screenshots/jobs-search.jpeg) | ![Upload Options](docs/screenshots/upload-options.jpeg) |
| **Job Search** — 72K+ listings with filters | **Upload** — PDF, paste, AI chat, or demo |
| ![Templates](docs/screenshots/templates.jpeg) | ![Bullet Feedback](docs/screenshots/bullet-feedback.jpeg) |
| **Templates** — 8 professional styles | **AI Feedback** — per-bullet coaching |
| ![AI Rewrite](docs/screenshots/ai-rewrite.jpeg) | ![Market Insights](docs/screenshots/market-insights.jpeg) |
| **AI Rewrite** — 3 options per bullet | **Market Insights** — sector & skill trends |
| ![Smart Match](docs/screenshots/smart-match.jpeg) | ![Export](docs/screenshots/export.jpeg) |
| **Smart Match** — RAG-powered job matching | **Export** — DOCX/PDF with final score |

---

## Features

### Job Search
- Aggregates from MyCareersFuture and CareersGov
- 72,000+ listings refreshed nightly
- Filter by seniority, job type, salary, skills
- ATS skill tags on every listing

### Resume Builder
- Upload PDF/DOCX or build from scratch with AI chat
- 8 professional templates (Classic, Modern, SG Pro, Compact, Executive, Creative, Technical, Minimal)
- Inline click-to-edit with drag-and-drop bullet reordering
- Add/delete sections, entries, bullets with one click
- Download as DOCX

### AI Resume Coach (SEA-LION)
- ATS scoring (0-100) across Impact, Presentation, Competencies
- Per-bullet feedback with annotations (Solid Impact, Review, Verb Check)
- AI rewrite with 3 options per bullet
- Full 7-stage tailoring pipeline for specific job descriptions
- Custom summary generation with user prompts
- Template-aware section detection

### AI Resume Chat Builder
- ChatGPT-like conversation that builds your resume from scratch
- Coaches you to add metrics and quantified achievements
- Suggests trending skills from the job database
- Generates structured resume dropped into the editor

### Cover Letter Generator
- Generate from resume + job description
- Custom direction ("emphasize leadership", "keep it concise")
- Edit inline, copy, or download

### Smart Match (RAG)
- Semantic job matching using sentence-transformers embeddings
- Hybrid scoring: keyword overlap + cosine similarity
- Suitability scores, gap analysis, bridge paths
- Pre-embedded 72K jobs for instant matching

### Application Tracker
- Track applications: Applied, Interview, Offer
- Follow-up reminders
- Status tracking per job

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy + SQLite/Postgres |
| Frontend | React 19 + Vite + Tailwind CSS |
| AI | SEA-LION (AI Singapore) — 32B + 70B models |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Deploy | Railway (Docker) |
| Auth | JWT + bcrypt |

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
# Backend (143 tests)
cd backend && python -m pytest tests/test_resume_structurer_comprehensive.py -v

# Frontend (98 tests)
cd frontend && npm test
```

---

## Architecture

```
shared/resume-classification.json  <- Single source of truth
    |                    |
backend/                 frontend/src/lib/
resume_structurer.py     resumeHelpers.jsx
resume_scorer.py         resumeConstants.js
ai_service.py            ResumeTab.jsx
embedding_service.py     ScraperTab.jsx
    |                        |
AI pipeline, scoring     Visual preview, editing
```

---

## API Highlights

| Endpoint | Description |
|----------|-------------|
| `GET /api/jobs` | Browse cached jobs |
| `POST /api/resume/score` | Score resume (0-100) |
| `POST /api/resume/upload` | Upload PDF/DOCX |
| `POST /api/ai/rewrite` | AI bullet rewrite (3 options) |
| `POST /api/ai/cover-letter` | Generate cover letter |
| `POST /api/ai/resume-chat` | AI chat resume builder |
| `GET /api/jobs/power-match` | Smart Match with RAG |
| `POST /api/resume/tailor` | 7-stage tailoring pipeline |

---

## Environment Variables

```bash
DATABASE_URL=sqlite:///./jobhunter.db
JWT_SECRET=your-secret
sealion_api=your-sealion-key
ALLOWED_EMAIL_DOMAINS=*  # or comma-separated domains
```

See `.env.example` for full list.

---

## License

[AGPL-3.0](LICENSE) — Free to use and modify. Must share changes if deployed as a service. Attribution required.

Built by [Haoming Koo](https://kooexperience.com).
