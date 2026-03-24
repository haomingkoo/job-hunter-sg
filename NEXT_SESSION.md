# Next Session — Priority Fixes

## Critical Issues (must fix)

### 1. PDF Parser Splits Bullets Across Lines
**Problem**: pdfplumber breaks lines based on PDF layout, not sentences. One bullet becomes 2-3 lines:
```
"Led multi-site manufacturing and quality transformation initiatives spanning 4"
"regions, aligning engineering, operations and supplier teams under a unified QMS"
"framework."
```
Should be one line.

**Fix**: After extraction, join lines that don't start with a bullet char, section header, or date pattern. Lines that start with lowercase or don't look like a new entry should be joined to the previous line.

### 2. Scorer Can't Detect Bullets Without Bullet Characters
**Problem**: PDF strips •, -, * characters. Scorer sees 0 bullets → scores 0/10 on Action Oriented and Specifics (20 points lost).

**Fix**: In `resume_scorer.py`, detect bullets by:
- Lines starting with action verbs (from the ACTION_VERBS set)
- Lines that follow a subheading (company/role/date line)
- Lines that are indented or part of a list pattern
- Not just lines starting with •, -, *

### 3. Finalize Score Button Doesn't Re-Score
**Problem**: Clicking "Finalize Score" doesn't trigger a new POST /api/resume/score call. The score stays stale.

**Fix**: In App.jsx, the Finalize Score handler needs to call the score API with the current resumeText.

### 4. Resume Preview Too Cramped
**Problem**: Text in the document preview is too dense — needs more line-height, paragraph spacing, and padding.

**Fix**: Increase padding on the page container from `p-6 sm:p-8` to `p-8 sm:p-12`. Increase line-height. Add more spacing between sections.

### 5. Batch Rewrite (One-Shot All Suggestions)
**Feature**: Instead of clicking rewrite per bullet, one AI call returns rewrite options for ALL flagged bullets at once. User picks Option A, B, or Keep Original for each.

**Backend**: New endpoint `POST /api/ai/batch-rewrite` that sends all bullets + job description, returns `{rewrites: [{original, options: [a, b], reason}]}`.

### 6. Overusage Score Too Harsh
**Problem**: Score shows "66 words used 3+ times" and scores 0/10. Technical resumes legitimately repeat domain terms (Python, quality, data). Threshold should be higher and domain/skill terms should be exempted.

### 7. AI Format Destroys Resume Structure
**Problem**: "AI Improve All" flattens job titles/subheadings into bullet points. "Senior Process & Equipment Engineer – Wet Process | Nov 2019 – Nov 2021" becomes a bullet instead of a subheading.

**Fix**: Update the AI Format system prompt in `main.py` to explicitly:
- Preserve section headers (EXPERIENCE, EDUCATION, SKILLS) as headers
- Preserve job title | company | date lines as subheadings (NOT bullets)
- Only format actual achievement/responsibility lines as bullets
- Never merge a job title with a bullet point
- Maintain the hierarchy: Section → Company → Role + Date → Bullets

### 8. Frontend Resume Preview Parser Needs Improvement
**Problem**: The `parseResumeToSections()` function doesn't distinguish job titles from bullets well enough. Lines with dates and `|` separators should be subheadings, not bullets.

**Fix**: Improve the parser to detect:
- Lines with date ranges (e.g., "Jan 2020 – Dec 2023") → subheading
- Lines with `|` or `—` separator → subheading
- Lines starting with `**text**` markdown bold → subheading
- ALL CAPS short lines → section heading

## Nice to Have

- Re-seed CareersGov with fixed scraper (location + posted date now captured)
- Job market analytics dashboard
- Cold start resume builder for users with no resume
- Email alerts for job matches
