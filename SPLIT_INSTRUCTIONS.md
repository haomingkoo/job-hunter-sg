# SPLIT INSTRUCTIONS — Claude (Backend) + Codex (Frontend)

## FOR CODEX — Frontend ONLY (App.jsx)

### CRITICAL BUG: Section headers treated as bullets
The `parseResumeToSections()` function doesn't detect these as HEADINGS:
- `**Professional Summary**` (markdown bold)
- `**Core Skills**`
- `**Professional Experience**`
- `**Micron Technology** — Singapore / Japan / Taiwan / USA` (company name)
- `**Manager, Strategic Operations & Transformation** | Aug 2022 – Jan 2025` (job title with date)

FIX the parser to detect:
1. Lines wrapped in `**text**` → strip the `**` and treat as HEADING or SUBHEADING
2. Lines with dates (MMM YYYY – MMM YYYY, or YYYY – YYYY, or YYYY – Present) → SUBHEADING
3. Lines with `|` or `—` separators → SUBHEADING
4. ALL CAPS lines (PROFESSIONAL EXPERIENCE, EDUCATION, etc) → HEADING
5. Known section words (experience, education, skills, certifications, summary) → HEADING

Headings should render as: bold, uppercase, letter-spacing, bottom border, NO bullet dot, NO annotation
Subheadings should render as: bold text left + date right, NO bullet dot, NO annotation

Only ACTUAL bullet content (achievement lines starting with action verbs) should get bullet dots and annotations.

### CRITICAL BUG: AI Rewrite shows empty box
Backend returns `{options: ["opt1", "opt2", "opt3"]}` not `{rewritten: "string"}`.
Fix ALL references to `.rewritten` → use `.options` array.
Show 3 option cards. Handle `{no_change: true}`.

### CRITICAL BUG: Finalize Score doesn't work
The button must call `POST /api/resume/score` with current resumeText + selectedJob?.description.
Update scoreData with response. Show loading state.

### Resume preview formatting
- Name: 18pt bold centered
- Contact: 9pt centered, pipe-separated
- Section headers: bold uppercase with bottom border, NOT treated as bullets
- Job titles: bold, date right-aligned
- Company: normal weight, separate line
- Bullets: visible • character, indented
- Text: justified, 11pt body
- Template-specific styling must actually apply

### Search should split query words (AND logic)
"micron i4" should match jobs containing BOTH "micron" AND "i4".
Currently searches for literal "micron i4" substring.
FIX: split query into words, match all words independently.
(This could also be a backend fix — coordinate with Claude)

### JD panel on Resume tab
When selectedJob exists:
- Show job title + company + description at top
- Show required skills as pills
- "Back to Jobs" link
- Pass job_description to score API

### After download: next steps card
- "Search matching jobs" → switch to Jobs tab
- "Track this application" → open tracker

### Keyword display
Backend returns matched/missing as objects `{skill, resume_context}` / `{skill, jd_context}`.
Extract `.skill` for display text. Show context on hover/click.

---

## FOR CLAUDE — Backend ONLY (backend/*.py)

### Fix search to support multi-word queries
In `main.py`, the `/api/jobs` endpoint uses `ILIKE %query%`.
Change to split query into words and require ALL words match:
```python
if q:
    words = [w.strip() for w in q.split() if w.strip()]
    for word in words:
        pattern = f"%{word}%"
        query = query.filter(
            (ScrapedJob.title.ilike(pattern))
            | (ScrapedJob.company.ilike(pattern))
            | (ScrapedJob.description.ilike(pattern))
        )
```

### Fix AI Improve All — targeted approach
Change the `/api/resume/format` prompt to:
- Score first, identify weak bullets
- Only rewrite weak ones
- Preserve ALL structure (headers, titles, dates)
- Leave strong bullets untouched

### Fix AI Format output
The AI is wrapping section headers in `**markdown bold**` which the frontend parser doesn't understand.
Update the prompt to output PLAIN TEXT with ALL CAPS headers, not markdown:
```
PROFESSIONAL EXPERIENCE
Micron Technology — Singapore
Manager, Strategic Operations | Aug 2022 – Jan 2025
• Led cross-functional...
```
NOT:
```
**Professional Experience**
**Micron Technology** — Singapore
**Manager, Strategic Operations** | Aug 2022 – Jan 2025
```

### CareersGov enrichment
The enrich_careersgov.py script is ready. Run it to fetch full JDs for CareersGov jobs.

### Crawl status
Full crawl running — 23K+ jobs. When done, commit the DB.

---

## COORDINATION RULES
- Codex: ONLY edit `frontend/src/App.jsx`
- Claude: ONLY edit `backend/*.py`
- No one touches the other's files
- Commit independently, merge at the end

---

## ADDITIONAL ISSUES FOUND

### Classic template should show Education FIRST
The "Classic" template description says "Education first" but the preview shows sections in the order they appear in the text. When "Classic" is selected, the frontend should REORDER sections: Summary → Education → Experience → Skills → Certifications.

Each template has a section_order defined in backend/resume_templates.py:
- classic: summary, education, experience, skills, certifications
- modern: summary, experience, projects, skills, education
- singapore: personal, summary, education, experience, activities, skills
- compact: summary, experience, skills, education, certifications

The frontend parseResumeToSections should respect this ordering when rendering.

### **text** markdown not stripped
The AI Format returns section headers as `**Professional Experience**` with markdown bold markers. The frontend parser must:
1. Detect `**text**` patterns
2. Strip the `**` markers
3. Treat the inner text as a HEADING (not a bullet)

Regex: `/^\*\*(.+)\*\*$/` → extract group 1 as heading text

### "Additional Information" section header treated as bullet
`*Additional Information**` shows with a bullet dot and "Review Bullet" annotation. Same fix — detect as heading.
