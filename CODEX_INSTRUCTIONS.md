# CODEX INSTRUCTIONS — Priority Fix List

## Context
Job Hunter SG is a Singapore job aggregator + AI resume coach. Live at https://jobhunter.kooexperience.com. Public repo: https://github.com/haomingkoo/job-hunter-sg

**Stack**: FastAPI backend, React+Vite+Tailwind frontend (single file `App.jsx`), SQLite/Postgres, SEA-LION AI (OpenAI-compatible).

**New this session**: A 7-stage resume tailoring pipeline was built (see `backend/PIPELINE_README.md`). Backend is complete. Frontend integration is partial.

**Rules**:
- No hidden fallbacks. If something fails, show error or explain in pipeline_notes.
- No hardcoded credentials.
- No developer jargon in user-facing text (no "SEA-LION", "VMock", "32B").
- Test locally before pushing. Railway auto-deploys from main.

---

## CRITICAL FIXES (do these first)

### Fix 0: Mobile is completely broken (3 sub-issues)

**0a. Search returns 0 results on mobile**
Searching "Micron" on mobile shows "0 jobs matching Micron" but works fine on desktop. Debug the search flow on mobile — check if query param, filters, or request encoding differs. Test with Chrome DevTools mobile emulation.

**0b. Resume editor — AI feedback panel invisible on mobile**
On mobile, the left panel (score, bullet feedback, AI buttons) is behind the Edit/Feedback toggle. When tapping "Feedback", the scoring panel + AI rewrite options + action buttons must be fully visible and scrollable. Currently the AI buttons (Improve All, Run Full Tailor, AI Coach) may be below the fold or not rendering in the Feedback view at all.

**0c. Mobile editing zoom goes crazy**
Tapping a bullet to edit on mobile causes uncontrollable zoom and the editing area clips off-screen. Fix:
- Set `font-size: 16px` on ALL input, textarea, and contenteditable elements. iOS Safari zooms in on inputs with font-size < 16px.
- Add to `index.html`: `<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">`
- The editing input must be full-width on mobile, not clipped to a narrow column
- When the keyboard opens, the sticky bottom bar ("Score --" / "Download DOCX") must not overlap the editing area. Use `position: sticky` with proper bottom offset, or hide the bar when keyboard is open.

**Test all 3 on Chrome DevTools (iPhone 14 Pro, 393x852) and a real phone if possible.**

### Fix 1: Education entries lumped together
**Location**: `frontend/src/App.jsx` — `buildEducationPair()` function (~line 2081)
**Problem**: Two degrees (M.Sc. and B.Sc.) render as one merged block instead of separate entries.

The raw text from backend is correct:
```
Line 32: M.Sc., Smart Industries & Digital Transformation — NUS, 2022
Line 33: GPA: 4.85 / 5.00 | Graduate Certificates in IoT...
Line 34: B.Sc. (Hons, Distinction), Chemistry — NUS
Line 35: GPA: 4.46 / 5.00 | Exchange: Simon Fraser University
```

Lines 32+33 should be one education entry. Lines 34+35 should be a SEPARATE entry. Currently the parser merges all 4 lines into one block.

**Fix**: In `buildEducationPair`, when processing the "next" line and considering `canExtendEducationMeta` (line 2093), check if the third line starts a NEW degree (`RESUME_DEGREE_RE` match). If it does, do NOT merge — stop at `consumed=1` and let the next iteration create a new pair.

Add degree detection:
```javascript
const DEGREE_START_RE = /^(M\.?Sc|B\.?Sc|B\.?Eng|MBA|M\.?Eng|Ph\.?D|B\.?A|M\.?A|Diploma)/i;
```
If `third` matches this regex, set `canExtendEducationMeta = false`.

**Test**: Upload a resume with 2+ degrees. Each should render as a separate entry with its own GPA line.

### Fix 2: Section order wrong
**Location**: `frontend/src/App.jsx` — `reorderParsedSections()` function
**Problem**: "Additional Information" and "Languages" appear before "Professional Summary" in the preview. The backend returns sections in correct order (Summary first).

**Fix**: The template ordering logic in `reorderParsedSections` is overriding the natural document order. Either:
1. Fix the template section order to put `summary` first, OR
2. Keep sections in their original document order unless the template explicitly specifies otherwise

**Test**: Upload resume. Sections should appear in this order: Contact → Summary → Core Skills → Experience → Education → Certifications → Additional Info → Languages.

### Fix 3: Empty sections still render
**Location**: `frontend/src/App.jsx` — resume document renderer
**Problem**: "ADDITIONAL INFORMATION" shows as a heading with no content below it.

**Fix**: In the render loop, skip sections that have:
- Type "heading" followed immediately by another heading or spacer
- No bullets, paragraphs, or subheadings between this heading and the next

**Test**: Upload resume with an empty section heading. It should not appear in the preview.

### Fix 4: Specifics score — show WHICH bullets lack metrics
**Location**: `frontend/src/App.jsx` — Specifics feedback panel
**Problem**: Shows "8/22 bullets contain metrics/numbers" but doesn't tell the user WHICH 14 bullets are missing metrics. The data is available in the annotations (bullets with "Good Start" badge have no metrics, "Solid Impact" have metrics).

**Fix**: Under the Specifics score, add a list of the bullets that are missing metrics:
```
Bullets missing quantification:
• "Managed a cross-site team of 6..." — already has team size, but no outcome metric
• "Partnered with process integration..." — add a %, $, or scale number
• "Standardized documentation..." — what was the result? How many docs? Time saved?
```

For each bullet missing metrics, show the first 60 chars + a hint about what metric to add.

---

## HIGH PRIORITY

### Fix 5: "Run Full Tailor" progress UI
**Location**: `frontend/src/App.jsx` — tailoring section
**Problem**: The pipeline starts but the progress UI is minimal. Users need to see which of the 7 stages is active.

The backend returns from `GET /api/resume/tailor/{session_id}/status`:
```json
{
  "stage": "bullet_rewrite",
  "stage_number": 3,
  "total_stages": 7,
  "progress": {"completed": 8, "total": 20},
  "message": "Rewriting bullets 8 of 20...",
  "complete": false
}
```

**Fix**: Show a step progress bar with 7 stages:
```
[✓ Analyze] [✓ Strategy] [✓ Cleanup] [● Rewriting 8/20] [ Polish] [ Summary] [ Validate]
```
Each stage gets a label. Active stage shows progress. Completed stages get a checkmark.

### Fix 6: Pipeline result — accept/reject per change
**Location**: `frontend/src/App.jsx`
**Problem**: When the pipeline completes, the result contains `changes[]` with `original` and `tailored` per bullet, but there's no diff view or accept/reject UI.

**Endpoints available**:
- `POST /api/resume/tailor/{session_id}/feedback` — `{bullet_id, action: "accept"|"reject"|"edit", edited_text}`
- `POST /api/resume/tailor/{session_id}/apply` — applies only accepted changes

**Fix**: After pipeline completes, show each change as a card:
```
ORIGINAL: "Responsible for managing stakeholder relationships across APAC"
TAILORED: "Directed stakeholder engagement across 4 APAC regions, aligning engineering and operations teams"
[✓ Accept] [✗ Reject] [✎ Edit]
```

Then an "Apply Accepted Changes" button that calls `/apply`.

### Fix 7: ATS gap report UI
**Location**: `frontend/src/App.jsx`
**Problem**: Pipeline returns `ats_gaps[]` showing remaining missing skills with suggested placement, but no UI displays this.

Each gap looks like:
```json
{
  "skill": "kubernetes",
  "required": true,
  "suggested_section": "skills",
  "suggested_entry_id": null,
  "action": "No existing bullets relate to 'kubernetes'. Add to Skills if you have it, or skip.",
  "needs_user_input": true
}
```

**Fix**: After pipeline results, show an "ATS Gaps" section:
```
REMAINING GAPS (3 skills still missing)

[REQUIRED] kubernetes
  → Add to Skills if you have this experience, or skip
  [Add to Skills] [Skip — I don't have this]

[PREFERRED] real-time streaming
  → Your AI Singapore role mentions NLP pipeline — could be relevant
  [Add to bullet] [Add to Skills] [Skip]
```

### Fix 8: Add Section / Add Bullet
**Location**: `frontend/src/App.jsx` — resume editor
**Problem**: Template coverage says "consider adding Projects" but there's no way to add a new section. The "+ Add Bullet Below" button exists for existing sections, but there's no "+ Add Section".

**Fix**: Add a "+ Add Section" button at the bottom of the resume preview. On click, show options:
- Projects
- Volunteer / Activities
- Awards / Honors
- Custom section (user types name)

When selected, insert the heading + one empty bullet into the resume text and re-render.

---

## MEDIUM PRIORITY

### Fix 9: Sort default to Newest
**Location**: `frontend/src/App.jsx` — ScraperTab sort
**Problem**: Default sort shows "Sort: Relevance" but there's no "Newest" option. Jobs should default to newest first.

**Fix**: Add "Sort: Newest" option (already present as "newest" in some code paths). Make it the default. Backend already returns by `id DESC` which is roughly newest first.

### Fix 10: Filter dropdowns from all jobs
**Location**: `frontend/src/App.jsx` — ScraperTab filters
**Problem**: Location/source/employment dropdowns were built from current 20 results. Backend now returns `filter_meta` on page 1 responses.

**Fix**: Use `data.filter_meta.sources`, `data.filter_meta.employment_types`, and `data.filter_meta.locations` from the `/api/jobs` response to populate dropdowns. Only fall back to current-page values if `filter_meta` is missing.

### Fix 11: Summary optimization button
**Problem**: No way to click on the Professional Summary and get AI to rewrite it.
**Fix**: When user clicks the Professional Summary section, show an "Optimize Summary" button in the left panel. On click, call the pipeline in "full" mode (which includes Stage 5 summary generation), or add a dedicated summary-only endpoint.

---

## BACKEND FILES (do NOT modify)
These were built and tested this session. Do not change unless a bug is found during review:
- `backend/jd_preparser.py`
- `backend/resume_structurer.py`
- `backend/ai_phrases.py`
- `backend/validation_gates.py`
- `backend/tailoring_pipeline.py`

## BACKEND CHANGES ALREADY MADE (for reference)
- `backend/main.py` — 6 new pipeline endpoints, lifespan (replaced deprecated on_event), validated rewrite options
- `backend/ai_service.py` — 70B model constants, progressive JSON retry, validated rewrites
- `backend/auth.py` — ephemeral JWT key in dev (no hardcoded fallback)
- `backend/models.py` — parsed_jd column on ScrapedJob, TailoredResume table
- `backend/seed_jobs.py` — auto pre-parse JD on scrape
- `backend/scraper.py` — MCF employment_type extraction from plural field
- `backend/resume_scorer.py` — word count range widened to 400-900

## REVIEW CHECKLIST
Before pushing any changes, also run `CODEX_REVIEW.md` — it has 6 mechanical test tasks for the pipeline reliability.

## TESTING
After all fixes, verify on https://jobhunter.kooexperience.com:
- [ ] Upload resume PDF/DOCX — sections render in correct order
- [ ] Education shows as separate entries (M.Sc. and B.Sc. not merged)
- [ ] Empty sections (like "Additional Information" with no content) are hidden
- [ ] Specifics score panel shows which bullets lack metrics
- [ ] "Run Full Tailor" completes without 405 error
- [ ] Pipeline progress shows 7 stages with active indicator
- [ ] Pipeline result shows accept/reject per change
- [ ] ATS gaps shown with actionable suggestions
- [ ] "+ Add Section" button works at bottom of resume
- [ ] Sort defaults to Newest
- [ ] Filter dropdowns show all sources/locations/employment types from DB
- [ ] AI rewrite options pass validation (no more picking an option that fails the same check)
- [ ] Score recalculates correctly after edits (Specifics count matches annotations)
- [ ] No console errors, no white screens, no hidden fallbacks
