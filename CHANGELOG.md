# Changelog

All notable changes to Job Hunter SG will be documented in this file.

## [Unreleased]

### Added
- Unified Resume workspace (upload, score, AI review, edit, download in one tab)
- PDF/DOCX resume upload with auto-parsing
- 100-point resume scoring (Impact / Presentation / Competencies)
- AI resume coaching via Singapore AI (session-based, unlimited rewrites per session)
- AI bullet rewriting with anti-hallucination guardrails
- 4 ATS-friendly DOCX templates (Classic, Modern, Singapore Pro, Compact)
- DOCX resume download
- Job search across MCF, CareersGov, Adzuna, Jooble
- SSG Skills Framework integration (OAuth2)
- Application tracker with follow-up reminders
- User memory (AI remembers your background across sessions)
- Pre-cached job database (17,000+ SG jobs via full crawl)
- Cookie + IP anonymous rate limiting
- Cloudflare Access support for @aisg.sg OTP login
- Privacy notice (rendered HTML page)
- Encouragement messages for job seekers
- Configurable tier limits via environment variables

### Security
- JWT auth with production crash guard
- API key masking in responses
- Login rate limiting (5 attempts / 15 min)
- Input sanitization (HTML, URL, resume text)
- CSV injection protection
- No hardcoded credentials anywhere
- CORS wildcard blocked in production
- OpenAPI docs disabled in production
- PII removed from logs

### Infrastructure
- SQLite (local) / PostgreSQL (Railway) with auto-migration
- Full crawl script (seed_jobs.py --full)
- Health check with DB connectivity test
- Docker support for both backend and frontend
- 4 SEA-LION API keys with round-robin rate limiting (36 req/min)
