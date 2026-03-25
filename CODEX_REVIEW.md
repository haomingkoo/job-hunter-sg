# Codex Review - Session 2 (2026-03-25)

## What was shipped (13+ commits to main)

### JD Enrichment Pipeline
- `jd_summary.py` - SEA-LION 32B summaries with LLM input sanitization
- `jd_analyzer.py` - Quality scoring (0-100), prompt injection detection, red flags (scam/discrimination/exploitative), content hash for duplicates
- `backfill_enrichment.py` - CLI script with `--preview-only`, `--refresh-preview`, `--summary-limit` flags
- Admin endpoints: `POST /api/admin/backfill`, `GET /api/admin/backfill/status`, `GET /api/admin/jd-analysis`
- 70K jobs backfilled with parsed_jd, job_terms_preview, _analysis (3 rounds)

### ATS Term Extraction (3 rounds of quality fixes)
- Filtered section headers ("what the role is"), responsibility phrases (>4 words), verb-leading phrases
- Added prose noun phrase extractor (capitalized terms, "such as" patterns, parenthetical abbreviations)
- Added "proficient in X" / "knowledge of X" requirement phrase extractor
- Before: 1-3 cues per CareersGov JD. After: 5-9 cues

### Performance
- 5 DB indexes (posted_at_sort, source, location, seniority, employment_type)
- CareersGov hydration moved to background thread pool
- Frontend waterfall reduced (4 auto-fetches to 1)
- Filter metadata cached 5 min

### Resume Versioning (NEW)
- `ResumeVersion` model: label, source, resume_text, structured JSON, linked job, score, is_master
- CRUD endpoints: GET/POST/PUT/DELETE /api/resume/versions
- Auto-save tailored resume as version when pipeline completes

### Bug Fixes
- Resume parser: bulleted job titles now recognized as entry headings
- Bounded thread pool (3 workers, 50 cap) with circuit breaker
- N+1 query fixes, pool shutdown, retry cooldown

## What Codex should verify/improve

### High Priority
1. **Frontend version picker** - Backend ready, needs UI in Resume tab (load/save/switch versions)
2. **Resume scorer** - Core Skills section labels scored as bullets (should skip non-experience sections)
3. **Regenerate Summary button** - Hover/click on Professional Summary to regenerate from bullets + JD
4. **crawl_all_jobs()** in seed_jobs.py skips enrichment (no preview/analysis at crawl time)
5. **JobOut schema** missing new columns (jd_summary, job_terms_preview) - single job endpoint drops them

### Medium Priority
6. **Template intelligence** - Reorder sections by seniority, prompt for missing sections
7. **Resume formatting** - Education layout wrapping, Certification alignment
8. **Tracker features** - Check if tracked job listing is still live (HTTP HEAD), show closed status
9. **Email reminders** - Send reminder emails for saved jobs with follow-up dates
10. **Data analytics page** - Top skills, top jobs, trends by domain (aggregate job_terms_preview)

### Low Priority
11. **Deduplicate shared functions** - `_job_term_labels`, `_normalize_skill_strings` in 3 files
12. **Experience years + education** on job card previews
13. **Resume DOCX/PDF parsing** - Handle more edge cases
14. **Add bullet between bullets** - Click-to-insert in Smart Editor
15. **Summary backfill** - Trigger overnight: `POST /api/admin/backfill {}` (5 keys, ~24h)

## Architecture Notes

### Backfill commands
```bash
# Preview only (no LLM, ~15 min for 70K):
POST /api/admin/backfill {"preview_only": true}

# Refresh all previews (after fixing extraction):
POST /api/admin/backfill {"preview_only": true, "refresh_preview": true}

# Full (preview + summaries, ~24h with 5 keys):
POST /api/admin/backfill {}

# Check status:
GET /api/admin/backfill/status

# View flagged JDs:
GET /api/admin/jd-analysis?flag_type=all
```

### Railway
- Project: victorious-rejoicing, Service: job-hunter-sg
- Cron: enthusiastic-gratitude (nightly, can add summary backfill)
- Push to main = auto-deploy (kills in-flight backfills, so don't push during backfill)
