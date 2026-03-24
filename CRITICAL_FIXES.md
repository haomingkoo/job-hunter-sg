# CRITICAL FIXES — Must Do Before Deploy

## The Core Problem
The resume preview doesn't match the actual PDF/DOCX output. Users see one thing on screen and get a different thing when they download. This destroys trust.

## Fix 1: Frontend — Rewrite display handles new API format
**File**: `frontend/src/App.jsx`
**What**: Backend returns `{options: ["option1", "option2", "option3"]}` but frontend reads `result.rewritten` (old format).
**Fix**: Find all references to `.rewritten` and update to handle `options` array. Show 3 clickable cards — user picks one.
**Lines**: 2269, 3114

## Fix 2: Frontend — Resume preview must match DOCX exactly
**File**: `frontend/src/App.jsx`
**What**: The preview uses different fonts, spacing, colors than the DOCX templates.
**Fix**: Read `backend/resume_templates.py` and match EXACTLY:
- Classic: Georgia 11pt, 1" margins, section headers = ALL CAPS with bottom border
- Modern: Calibri 10pt, 0.6" margins, section headers = left indigo border
- SG Pro: Calibri 11pt, 0.8" margins, section headers = bottom border + bold
- Compact: Arial 10pt, 0.5" margins, bold headers only
- Body text: same pt size as DOCX
- Bullet character: use `•` (U+2022) not tiny CSS dots
- Section headers should match the color/style of the template

## Fix 3: Frontend — Finalize Score button must call the API
**File**: `frontend/src/App.jsx`
**What**: "Finalize Score" button doesn't re-score. Score stays at 41 even after AI improvements.
**Fix**: onClick should call `POST /api/resume/score` with current `resumeText` and update `scoreData`.

## Fix 4: Frontend — Certifications still flagged
**File**: `frontend/src/App.jsx`
**What**: Education/certification entries show "Review Opening" annotation.
**Fix**: The cert detection regex was added but may not be in the deployed version. Verify `looksLikeCert` and `looksLikeEducation` checks are present in `annotateBullet()`.

## Fix 5: Backend — Rewrite returns empty for good bullets
**File**: `backend/ai_service.py`
**What**: If the AI returns `NO_CHANGE`, the frontend shows an empty "Suggested Rewrite" box.
**Fix**: Frontend should check for `result.no_change === true` and show "This bullet is already strong — no changes needed" instead of an empty box.

## State
- Backend: 40 commits, all Python files pass syntax check
- Frontend: 3,915 lines, builds clean with Vite
- Database: 17,450 jobs cached
- 5 SEA-LION API keys (45 req/min)
- All AI rate limits lifted for testing
- Git: everything committed and pushed to github.com:haomingkoo/job-hunter-sg.git
