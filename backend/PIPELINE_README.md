# Resume Tailoring Pipeline

A multi-pass AI pipeline that transforms a raw resume into a version tailored for a specific job description. Built for the Singapore job market.

## How it works

```
User uploads resume + clicks "Tailor for This Job"
                    |
                    v
    +---------------------------------+
    |  Stage 0: ANALYZE (local)       |  ~200ms
    |  - Parse resume into structured |
    |    sections/entries/bullets      |
    |  - Load pre-parsed JD (from DB) |
    |  - Score baseline (0-100)       |
    |  - Compute skill gaps           |
    |    (matched/missing/injectable) |
    +---------------------------------+
                    |
                    v
    +---------------------------------+
    |  Stage 1: STRATEGIZE (70B LLM)  |  ~10s
    |  - Which bullets to rewrite?    |
    |  - Where to inject keywords?    |
    |  - What story for the summary?  |
    +---------------------------------+
                    |
                    v
    +---------------------------------+
    |  Stage 2: CLEANUP (local)       |  ~50ms
    |  - Replace 107 AI-sounding      |
    |    phrases ("spearheaded"->     |
    |    "led") unless JD uses them   |
    +---------------------------------+
                    |
                    v
    +---------------------------------+
    |  Stage 3: REWRITE (70B LLM)     |  ~15s
    |  - Rewrite priority bullets     |
    |    (batched 4/call)             |
    |  - Each bullet gets:            |
    |    - Entry context (company/    |
    |      role/date)                 |
    |    - Sibling bullets (avoid     |
    |      duplication)               |
    |    - Keywords to inject         |
    |    - Specific issues to fix     |
    |  - Every rewrite validated by   |
    |    5 gates before acceptance    |
    +---------------------------------+
                    |
                    v
    +---------------------------------+
    |  Stage 4: POLISH (local)        |  ~50ms
    |  - Verb dedup within entries    |
    |    ("Led"x2 -> "Led" + "Dir-   |
    |    ected")                      |
    |  - Skills section reordered     |
    |    (JD-matched skills to top)   |
    +---------------------------------+
                    |
                    v
    +---------------------------------+
    |  Stage 5: SUMMARY (70B LLM)     |  ~12s
    |  - Generate executive summary   |
    |    from polished bullets below  |
    |  - Uses strategy direction      |
    |  - Reads actual JD job title    |
    +---------------------------------+
                    |
                    v
    +---------------------------------+
    |  Stage 6: VALIDATE (local)      |  ~50ms
    |  - Re-score tailored resume     |
    |  - Real skill match re-scan     |
    |  - Build ATS gap report         |
    |    (what's still missing +      |
    |     WHERE to add it)            |
    +---------------------------------+
                    |
                    v
    User reviews changes (accept/reject/edit each one)
                    |
                    v
    Apply accepted changes -> Download DOCX
```

## Files

| File | Lines | Purpose |
|------|-------|---------|
| `tailoring_pipeline.py` | ~1050 | Main orchestrator. 7 stages, background threading, progress tracking. |
| `jd_preparser.py` | ~470 | Pre-parse JDs at scrape time. Pure regex, ~50ms/job, no LLM. |
| `resume_structurer.py` | ~630 | Parse resume text into structured sections/entries/bullets with IDs. |
| `ai_phrases.py` | ~190 | 107 AI-sounding phrase replacements. JD-protected. |
| `validation_gates.py` | ~280 | 5 validation gates on every AI rewrite. |

## The Skill Pipeline

### Where skills come from

```
JOB DESCRIPTION
     |
     +-- At scrape time (jd_preparser.py, ~50ms, no LLM):
     |   |
     |   +-- skill_extractor.py: 200+ known multi-word phrases
     |   |   ("machine learning", "project management", "cross-functional collaboration")
     |   |
     |   +-- SINGLE_WORD_TECH: 70+ single-word terms
     |   |   (python, sql, docker, kubernetes, aws, pytorch, etc.)
     |   |
     |   +-- Job's own skill tags from source API
     |   |   (MCF provides structured skill arrays per job)
     |   |
     |   +-- Classified into:
     |       - required_skills (before "preferred"/"nice to have" markers)
     |       - preferred_skills (after those markers)
     |       - single_word_skills (tech terms found anywhere)
     |       - competency_signals (analytical, leadership, teamwork, etc.)
     |       - experience_years ("5+", "3-5", etc.)
     |       - education_level ("bachelor", "master", etc.)
     |
     +-- Stored in ScrapedJob.parsed_jd (JSON column)
         Ready INSTANTLY when user clicks "Tailor"
```

### How skills flow through the pipeline

```
Stage 0: Compare resume vs parsed_jd
         -> matched_skills: ["python", "data analysis"]  (user has these)
         -> missing_skills: ["kubernetes", "data pipeline"]  (JD wants, user lacks)
         -> injectable: ["data pipeline"]  (user has adjacent experience - mentions "ETL")
         -> non_injectable: ["kubernetes"]  (user has zero DevOps context - don't fabricate)

Stage 1: Strategy decides WHERE to inject
         -> "data pipeline" goes in bullet exp-1-b3 (already discusses building ETL flows)
         -> "kubernetes" is NOT injected (non-injectable)

Stage 3: Bullet rewrite for exp-1-b3:
         System: "Rewrite this bullet. Inject 'data pipeline'. Keep all original facts."
         Original: "Built ETL flows processing 10M events daily"
         Rewritten: "Built scalable data pipeline processing 10M events daily using Python and Airflow"
         -> Validated by 5 gates before acceptance

Stage 6: Re-scan tailored text for actual matches
         -> matched: 3/5 (was 2/5)
         -> still missing: ["kubernetes"] (honestly reported, not fabricated)
         -> ATS gap report: "kubernetes - no existing bullets relate to this.
            Add to Skills if you have it, or skip."
```

## Validation Gates

Every AI-generated rewrite passes through 5 local checks (no LLM cost):

| Gate | What it checks | On failure |
|------|---------------|------------|
| **Fact Preservation** | Numbers ($3M, 25%, 12 engineers) must match original | **REVERT** to original |
| **AI Phrases** | "Spearheaded", "cutting-edge", etc. | Auto-replace with simpler words |
| **Keyword Verbatim** | Injected keywords must appear exactly | Flag as missing |
| **Length Sanity** | Max 40 words, max 1.8x original length | **REVERT** to original |
| **Hallucination** | Max 3 new domain terms not in original or injectable set | **REVERT** to original |

Critical failures (fact preservation, hallucination, length) automatically revert to the original text. The user never sees a corrupted bullet.

## Intensity Levels

| Level | Stages | LLM calls | Time | Use when |
|-------|--------|-----------|------|----------|
| `nudge` | 0, 2, 4, 6 | 0 | ~5s | Quick cleanup, free |
| `keywords` | 0-4, 6 | 2 | ~30s | Inject keywords + fix bullets |
| `full` | 0-6 | 3 | ~60s | Complete tailoring + summary |

## API Endpoints

```
POST /api/resume/tailor
  Body: {resume_text, job_id, intensity: "nudge"|"keywords"|"full"}
  Returns: {session_id, status: "started", estimated_seconds}

GET /api/resume/tailor/{session_id}/status
  Returns: {stage, stage_number, total_stages, progress, message, complete}
  Poll every 2-3 seconds.

GET /api/resume/tailor/{session_id}/result
  Returns: {
    tailored_text,
    changes: [{bullet_id, type, original, tailored, gate_results, user_status}],
    skill_match: {before, after, matched_after, missing_after, injectable, non_injectable},
    score: {before, after},
    ats_gaps: [{skill, required, suggested_section, suggested_entry_id, action, needs_user_input}],
    pipeline_notes: [{type, message}],  // if anything degraded
    degraded: bool,
  }

POST /api/resume/tailor/{session_id}/feedback
  Body: {bullet_id, action: "accept"|"reject"|"edit", edited_text}
  User reviews each change individually.

POST /api/resume/tailor/{session_id}/apply
  Applies only accepted changes to the original text.
  Returns: {tailored_text, applied, rejected, skipped_pending, score_after}

GET /api/jobs/{job_id}/parsed
  Returns pre-parsed JD data (instant, no LLM).
```

## Model Selection

| Model | Size | Used for | Why |
|-------|------|----------|-----|
| `Llama-SEA-LION-v3.5-70B-R` | 70B reasoning | Pipeline (stages 1, 3, 5) | Background process, user sees progress bar, quality matters more than speed |
| `Qwen-SEA-LION-v4-32B-IT` | 32B | Interactive single-bullet rewrite (`/api/ai/rewrite`) | User is watching, needs instant response |

Both models are on the same free SEA-LION API. Same rate limits. 70B is slower but stronger for multi-step reasoning.

## What makes this different from Resume-Matcher

| Aspect | Resume-Matcher | This pipeline |
|--------|---------------|---------------|
| JD analysis timing | Per-session (LLM call) | Pre-parsed at scrape time (free, instant) |
| Model cost | GPT-4/Claude (paid) | SEA-LION 70B (free) |
| Validation gates | 4 gates | 5 gates (+ keyword verbatim) |
| AI phrase blacklist | 60+ | 107 |
| Executive summary | Not a dedicated pass | Synthesized from polished bullets |
| Skill honesty | Injectable vs non-injectable split | Same + ATS gap report showing WHERE to add |
| Market focus | Generic | Singapore (MCF, SkillsFuture, statutory boards) |

## No Hidden Fallbacks

If something fails:
- LLM returns nothing? `pipeline_notes` explains what degraded.
- Validation gate rejects a rewrite? Original bullet kept, user sees it unchanged.
- All gates fail? User gets their original resume back with a clear message.
- Rate limit hit? Pipeline waits, progress bar shows "Waiting for AI capacity."

Every failure is visible. Nothing is silently swallowed.
