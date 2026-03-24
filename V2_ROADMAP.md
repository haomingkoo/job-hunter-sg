# V2 Roadmap — Job Hunter SG

## Features to Build

### 1. Personalized Job Filters Based on Resume
When a signed-in user uploads their resume, auto-extract skills and preferences.
Show "Jobs For You" section filtered by their resume skills.
Let users customize: target roles, salary range, location, seniority level.
Store preferences in UserMemory.

### 2. Cold Start Resume Builder
For users who have NO resume yet (fresh grads, career changers):
- Ask them a few questions: What's your background? What role are you targeting?
- AI generates bullet points based on their answers
- Uses SSG Skills Framework to suggest relevant skills for the target role
- Guided flow: Summary → Experience → Education → Skills

### 3. NUS Templates as Ground Truth
Store the NUS career centre templates, guidelines, and action verbs as reference data.
- `backend/templates/nus/NUS Guidelines.pdf` — formatting rules
- `backend/templates/nus/List of Action Verbs for your Resume.pdf` — verb reference
- `backend/templates/nus/OJS 1.docx` — official template
Use these to validate our template output matches university standards.
Could also integrate NUS CFG links as resources for users.

### 4. RAG (Retrieval Augmented Generation)
Potential use cases:
- **Resume advice RAG**: Index resume best practices from Harvard, NUS, MIT guides.
  When AI coaches a resume, retrieve relevant advice passages for context.
- **Job matching RAG**: Embed job descriptions + resume text, use vector similarity
  for smarter matching than keyword search. SEA-LION Embedding (600M) is ideal.
- **Skills gap RAG**: Index SSG Skills Framework data. When a user targets a role,
  retrieve the exact skills/competencies required and compare against their resume.
- **Interview prep RAG**: Index common interview questions by role/industry.

Best approach: Use SEA-LION Embedding model for vectors, store in pgvector on Railway.

### 5. Job Market Analytics
Use the 17,450+ cached jobs to generate insights:
- Most in-demand skills (by frequency across all job postings)
- Salary distribution by role (from MCF data which includes salary ranges)
- Top hiring companies this month
- Role demand trends over time (needs timestamps from scraping)
- Skills gap analysis: "Your resume vs market demand"

Needs:
- Timestamps on scraped_jobs (scraped_at field exists)
- Aggregation endpoints: GET /api/analytics/skills, /api/analytics/salaries
- A simple dashboard tab in the frontend
- Weekly/monthly comparisons once we have enough historical data

### 6. Email Alerts
For signed-in users:
- Weekly digest of new jobs matching their saved keywords/resume skills
- Follow-up reminders for tracked applications
- Application status change notifications
Needs: Resend integration (free 100 emails/day)

### 7. Cloudflare Access OTP Login
Replace password auth with Cloudflare Access email OTP for @aisg.sg users.
Backend already supports Cf-Access-Authenticated-User-Email header.
Just needs Cloudflare dashboard configuration on deployment.

## Ground Rules
- No hidden fallbacks — if data is missing, say so explicitly
- No hardcoded credentials — everything via env vars
- No hallucination in AI features — flag uncertainties, don't fake
- Privacy first — users control their data, can delete anytime
