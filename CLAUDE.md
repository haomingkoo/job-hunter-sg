# Job Hunter SG

Singapore job aggregator + AI resume coach with multi-user support.

## Architecture

- **Backend**: FastAPI + SQLAlchemy + SQLite (Postgres on Railway)
- **Frontend**: React + Vite + Tailwind CSS
- **Scraping**: requests + BeautifulSoup (MCF, CareersGov, NodeFlair, Indeed, JobStreet, Adzuna, Jooble)
- **Embeddings**: sentence-transformers/all-MiniLM-L6-v2 (384-dim) for semantic job matching (`embedding_service.py`)
- **AI**: SEA-LION API (OpenAI-compatible, by AI Singapore). Free tier, 10 req/min/key, 5 keys = 50 req/min.
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
```

## AI Models (SEA-LION)

| Model | Size | Used for | Constant |
|-------|------|----------|----------|
| `Qwen-SEA-LION-v4-32B-IT` | 32B (Qwen3 base) | Interactive single-bullet rewrites | `SEALION_MODEL` |
| `Llama-SEA-LION-v3.5-70B-R` | 70B (reasoning) | Full pipeline (strategy, rewrites, summary) | `SEALION_MODEL_REASONING` |

Both models are on the same free API at `https://api.sea-lion.ai/v1`. Same rate limits. 70B is slower but stronger. Use 32B only where instant response matters (interactive rewrite buttons).

## Resume Tailoring Pipeline

The core feature is a multi-pass AI pipeline that tailors a resume for a specific job. It runs as a background thread with progress polling.

### Pipeline stages

```
Stage 0: Local (200ms)   -- Parse resume into structured sections/bullets + load pre-parsed JD + baseline score
Stage 1: 70B   (~10s)    -- Strategic analysis: which bullets to prioritize, where to inject keywords
Stage 2: Local (50ms)    -- AI phrase cleanup (107 replacements, protected if phrase appears in JD)
Stage 3: 70B   (~15s)    -- Per-bullet rewrites (batched 4/call, validation-gated)
Stage 4: Local (50ms)    -- Section coherence: verb dedup with synonym map, tense consistency
Stage 5: 70B   (~12s)    -- Executive summary generation from polished content below
Stage 6: Local (50ms)    -- Validation gates (fact preservation, hallucination detection) + final score
```

### Intensity levels

- **`nudge`**: Stages 0, 2, 4, 6 only (local, no LLM, ~5s)
- **`keywords`**: Stages 0-4, 6 (+ AI rewrites, ~30s)
- **`full`**: All stages including summary generation (~45-60s)

### Backend files

| File | Purpose |
|------|---------|
| `jd_preparser.py` | Pre-parse JDs at scrape time: skills, experience years, education, responsibilities. Pure regex, ~50ms/job. |
| `resume_structurer.py` | Parse resume text into `{sections: [{key, entries: [{bullets: [{id, text, issues}]}]}]}`. Reuses `resume_scorer.py` logic. |
| `ai_phrases.py` | 107 AI-sounding phrase->replacement mappings. Phrases in the JD are protected. |
| `validation_gates.py` | 5 gates run on every AI rewrite: fact_preservation, ai_phrases, keyword_verbatim, length_sanity, hallucination. |
| `tailoring_pipeline.py` | 7-stage orchestrator. Runs in background thread. `PipelineState` tracks progress for polling. |
| `resume_scorer.py` | Scores resume 0-100 across Impact/Presentation/Competencies. Existing, not new. |
| `ai_service.py` | SEA-LION client with rate limiting, round-robin keys, progressive retry (`call_sealion_json`). |

### Shared config

- `shared/resume-classification.json` — Single source of truth for section heading synonyms, bullet markers, and classification rules. Used by both backend (`resume_structurer.py`) and frontend (`resumeHelpers.jsx`).

### Embedding service

- `embedding_service.py` — RAG semantic search using sentence-transformers/all-MiniLM-L6-v2 (384-dim, normalized). Lazy-loaded singleton model. Encodes job descriptions and resumes for cosine similarity matching.

### Tests

~218 tests across backend modules. Run with:
```bash
cd backend && python -m pytest tests/ -q
```

Key test files:
- `tests/test_resume_structurer_comprehensive.py` — comprehensive resume parsing tests
- `tests/test_resume_scorer.py` — scoring logic
- `tests/test_validation_gates.py` — AI rewrite validation
- `tests/test_jd_preparser.py` — JD parsing

Frontend tests via Vitest:
```bash
cd frontend && npx vitest run
```

### Key design decisions

1. **Pre-parse JDs at scrape time** -- `parsed_jd` JSON column on `ScrapedJob`. When user clicks "Tailor", skill gap analysis is instant.
2. **Structured resume model** -- Resume is parsed into sections/entries/bullets with IDs, not kept as flat text. Enables surgical edits.
3. **Validation gates on every rewrite** -- Facts (numbers, dates) must be preserved. Hallucinated terms rejected. AI phrases auto-replaced. Reverts to original if critical gate fails.
4. **Injectable vs non-injectable keywords** -- Only inject keywords the user plausibly has experience with. Never fabricate skills.
5. **70B for pipeline, 32B for interactive** -- Background pipeline uses stronger model since user sees progress bar. Single-bullet rewrite uses faster model since user is watching.

## API Endpoints

### Core
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

### Resume AI
| Endpoint | Auth | Description |
|----------|------|-------------|
| POST /api/resume/score | Optional | Score resume (0-100) |
| POST /api/resume/upload | Optional | Upload PDF/DOCX, extract text |
| POST /api/resume/download | Optional | Generate DOCX from text + template |
| POST /api/ai/coach | Optional | AI coaching review (starts session) |
| POST /api/ai/rewrite | Optional | Rewrite single bullet (32B, 3 options) |
| POST /api/ai/review-all | Optional | Review all bullets at once |
| POST /api/ai/integrate-keywords | Optional | Suggest keyword integration |

### Tailoring Pipeline
| Endpoint | Auth | Description |
|----------|------|-------------|
| POST /api/resume/tailor | Optional | Start pipeline: `{resume_text, job_id, intensity}` -> `{session_id}` |
| GET /api/resume/tailor/{session_id}/status | No | Poll progress: stage, progress %, message |
| GET /api/resume/tailor/{session_id}/result | Optional | Get result + auto-save version if logged in |
| GET /api/jobs/{job_id}/parsed | No | Get pre-parsed JD: skills, requirements, experience level |

### Resume Versions
| Endpoint | Auth | Description |
|----------|------|-------------|
| GET /api/resume/versions | Yes | List all saved resume versions |
| POST /api/resume/versions | Yes | Save new version: `{label, resume_text, job_id?, is_master?}` |
| GET /api/resume/versions/{id} | Yes | Load a specific version (full text + metadata) |
| PUT /api/resume/versions/{id} | Yes | Update label, text, or master status |
| DELETE /api/resume/versions/{id} | Yes | Soft-delete a version |

### JD Enrichment (Admin)
| Endpoint | Auth | Description |
|----------|------|-------------|
| POST /api/admin/backfill | Admin | Trigger JD enrichment: `{preview_only?, refresh_preview?, summary_limit?}` |
| GET /api/admin/backfill/status | Admin | Coverage stats + live backfill progress/ETA |
| GET /api/admin/jd-analysis | Admin | Flagged JDs, quality scores, duplicates: `?flag_type=injection\|red_flag\|duplicates` |

## Database

### Tables
- `users` -- accounts with email, password hash, tier
- `scraped_jobs` -- cached jobs from all sources
  - `parsed_jd` JSON -- pre-parsed skills, experience, education, responsibilities, `_analysis` (quality score, red flags, content hash)
  - `job_terms_preview` JSON -- cached 8 ATS skill labels for fast list rendering
  - `jd_summary` -- AI-generated 2-4 sentence summary (SEA-LION 32B)
  - `jd_summary_status` -- generating/model_name/unavailable/failed
- `tracked_jobs` -- user's application tracker
- `user_memories` -- persistent AI coaching memory per user
- `tailored_resumes` -- pipeline session tracking (structured resume snapshots, changes, scores)
- `resume_versions` -- saved resume versions with labels, linked jobs, scores, master flag
- `usage_logs` -- rate limiting and analytics

### Backend files (enrichment & search)
| File | Purpose |
|------|---------|
| `jd_summary.py` | LLM summary generation via SEA-LION 32B |
| `jd_analyzer.py` | Quality scoring, red flags, injection detection, duplicate hashing |
| `backfill_enrichment.py` | CLI + admin endpoint for batch enrichment of all jobs |
| `embedding_service.py` | RAG embeddings for semantic job-resume matching (MiniLM-L6-v2) |

## Environment Variables

- `DATABASE_URL` -- DB connection string (default: sqlite:///./jobhunter.db)
- `JWT_SECRET` -- Secret for JWT tokens
- `PORT` -- Server port (default: 8000)
- `ALLOWED_ORIGINS` -- CORS origins (default: *)
- `sealion_api` through `sealion_api5` -- SEA-LION API keys (supports multiple for higher throughput)
- `ALLOWED_EMAIL_DOMAINS` -- Restrict signups (default: aisg.sg)

## Security

- All scraped data is sanitized (HTML stripped) before storage and display
- JWT auth with bcrypt password hashing
- Rate limiting by tier
- No raw HTML rendering in frontend
- Validation gates prevent AI from fabricating metrics or skills
- API keys loaded from env vars, never logged or echoed
