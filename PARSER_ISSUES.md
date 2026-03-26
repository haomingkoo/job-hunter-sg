# Resume Parser Issues — Comprehensive Fix Needed

## Context

The resume document preview in the Resume tab renders uploaded resumes with
multiple visual issues. The text extraction from PDF/DOCX is clean, but the
**frontend parser** (`frontend/src/lib/resumeHelpers.jsx`, function
`parseResumeToSections`) misclassifies lines, creating a messy display.

## Root Cause

The frontend parser processes text **line by line**. When PDF extraction
produces line breaks mid-sentence (word wrapping), each fragment becomes a
separate parsed section. This causes:

1. Bold first part + light continuation (falsely detected as "lead paragraph")
2. Bullets without markers (continuation text rendered as paragraph)
3. Short orphaned lines ("Tableau, Python" on its own row)

## Specific Issues (with examples from real resumes)

### Issue 1: Bullet continuation lines become separate paragraphs

**Input text:**
```
• Led Hub-like innovation strategy via Micron's Accelerator Program,
aligning 6 global teams and vendors to scale pilot deployments.
```

**Current parse:** Two sections — bullet + paragraph (bold/light split)
**Expected:** One bullet with full text

### Issue 2: Summary paragraph split into bold lead + light continuation

**Input text:**
```
Strategic transformation leader with 7+ years of experience driving innovation,
cross-border collaboration, and economic impact through digital manufacturing, AI,
and business process optimization.
```

**Current parse:** Bold first line + light continuation lines
**Expected:** One continuous paragraph

### Issue 3: Standalone years not merged with position entry

**Input text:**
```
Manager, Engineering Strategy & Systems
2022
2025
```

**Current parse:** Three separate subheading entries
**Expected:** One entry: "Manager, Engineering Strategy & Systems | 2022 – 2025"

### Issue 4: Section heading split from its modifier

**Input text:**
```
CERTIFICATIONS
& Career Development
```

**Current parse:** "CERTIFICATIONS" heading + "& Career Development" paragraph
**Expected:** One heading: "CERTIFICATIONS & Career Development"

### Issue 5: Bullet marker on separate line from bullet text

**Input text:**
```
•
Business & Economic Analysis: Industry sensing, KPI tracking
```

**Current parse:** Empty bullet + separate paragraph
**Expected:** One bullet: "Business & Economic Analysis: ..."

### Issue 6: Core Skills bullets wrapped across lines

**Input text:**
```
• Strategic Development & Execution: Innovation roadmaps, digital adoption,
hub strategy enablement
```

**Current parse:** Bullet (bold) + paragraph (light "hub strategy enablement")
**Expected:** One bullet with full text

## What Needs to Change

### Option A: Pre-process text before parsing (RECOMMENDED)

Add a `joinWrappedLines(text)` function that runs BEFORE `parseResumeToSections`.
This function should:

1. Join lines where the next line starts with lowercase (clear continuation)
2. Join lines where the next line is short and doesn't look like a new entry
3. Merge "•\n" (bullet marker on its own) with the next line
4. Merge "HEADING\n& modifier" patterns
5. NOT merge lines that start new semantic blocks (bullets, headings, dates, entries)

The backend already has this: `resume_parser.py:_join_broken_lines()` (line 87).
The frontend needs its own equivalent, OR the backend should always return
pre-joined text.

### Option B: Post-process parsed output

After `parseResumeToSections` returns its array, run a merge pass that:
1. Finds paragraph items that follow bullets and merges them
2. Finds consecutive paragraphs in the same section and merges them
3. Detects standalone date items and merges with previous entry

Note: `mergeParsedParagraphRuns` already exists (line 838) but only merges
consecutive paragraphs, not paragraph-after-bullet.

## Files to Modify

- `frontend/src/lib/resumeHelpers.jsx` — main parser logic
- `frontend/src/lib/resumeConstants.js` — heading/bullet patterns

## Test Data

13 curated resume text fixtures in `tests/fixtures/resumes_curated/*.txt`
Run tests: `cd frontend && npx vitest run`

## Acceptance Criteria

Upload `/Users/koohaoming/Documents/Resumes/Haoming_Koo_EDB_Hub_Strategy_Formatted.pdf`
and verify:

1. Professional Summary is ONE continuous paragraph (no bold/light split)
2. ALL bullets render with bullet markers and full text on same block
3. Position entries show: Title, Company | Location | Dates on 1-2 lines max
4. Core Skills bullets are complete (no orphaned "hub strategy enablement")
5. "CERTIFICATIONS & Career Development" is one heading
6. Education entries render as clean cards with degree, university, dates
