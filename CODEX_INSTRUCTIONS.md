# CODEX INSTRUCTIONS — Complete Fix Plan

## Context
Job Hunter SG is a Singapore job aggregator + AI resume coach. The backend is solid (30+ endpoints, all working). The frontend (App.jsx, 3915 lines) has multiple bugs and missing features. This document lists EVERY issue to fix, in priority order.

**Files**: `frontend/src/App.jsx` (primary), `backend/main.py`, `backend/ai_service.py`

**Rules**:
- No hidden fallbacks — if something fails, show error
- No hardcoded credentials
- No VMock, SEA-LION, or developer jargon in user-facing text
- All useState before conditional returns
- Every API call needs try/catch with user-visible error

---

## CRITICAL FIXES

### Fix 1: AI Rewrite shows empty "Suggested Rewrite" box
**Location**: App.jsx ~line 3114 and ~line 2269
**Problem**: Backend returns `{options: ["opt1", "opt2", "opt3"]}` but frontend reads `result.rewritten` (undefined).
**Fix**:
- Find `selectedRewrite.rewritten` and replace with `selectedRewrite.options`
- Show ALL 3 options as selectable cards:
```jsx
{selectedRewrite?.no_change ? (
  <div className="bg-emerald-50 p-3 rounded-xl text-emerald-700 text-sm">
    {selectedRewrite.message || "This bullet is already strong — no changes needed."}
  </div>
) : selectedRewrite?.options?.length > 0 ? (
  <div className="space-y-2">
    <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Pick a rewrite</div>
    {selectedRewrite.options.map((opt, idx) => (
      <div key={idx} className="rounded-xl border border-gray-200 bg-gray-50 p-3">
        <p className="text-sm text-gray-700 leading-relaxed">{opt}</p>
        <button onClick={() => acceptRewrite(selectedBullet, idx)}
          className="mt-2 bg-indigo-600 text-white px-3 py-1.5 rounded-lg text-xs">
          Accept Option {idx + 1}
        </button>
      </div>
    ))}
  </div>
) : null}
```
- Update `acceptRewrite(section)` → `acceptRewrite(section, optionIndex=0)`:
```javascript
const candidate = rewriteResults?.[section.id]?.options?.[optionIndex];
```
- Also find the line `const candidate = rewriteResults?.[section.id]?.rewritten;` and change to `.options?.[0]`

### Fix 2: Admin account creation is unreachable code
**Location**: backend/main.py ~line 301-318
**Problem**: Admin creation code ended up inside `_build_bridge_plan()` after a `return` statement — unreachable.
**Fix**: Move the admin creation try/except block into `on_startup()` function (after line 168), properly indented.

### Fix 3: "Finalize Score" doesn't re-score
**Location**: App.jsx — find the Finalize Score button's onClick handler
**Problem**: The button exists but doesn't call POST /api/resume/score with the current resumeText.
**Fix**: The handler should:
1. Set `scoring = true`
2. Call `POST /api/resume/score` with `{resume_text: resumeText, job_description: selectedJob?.description || ""}`
3. Update `scoreData` with the response
4. Set `scoring = false`
5. Show before/after if old score exists (e.g., "41 → 67")

### Fix 4: Re-score automatically after "AI Improve All"
**Location**: App.jsx — `handleAIFormat` function (~line 2209-2235)
**Problem**: After AI reformats the resume, score stays stale.
**Fix**: After `applyResumeText(data.formatted_resume, ...)`, trigger a re-score call.

---

## HIGH FIXES

### Fix 5: Resume preview must match DOCX output exactly
**Location**: App.jsx lines 1296-1324 (template styles) and line 3336 (page container)
**Problem**: Preview uses different font sizes, margins, and section header styles than the DOCX templates.
**Fix**: Make page container style TEMPLATE-SPECIFIC:
```javascript
const templatePageStyles = {
  classic: { fontFamily: 'Georgia, "Times New Roman", serif', fontSize: '11pt', padding: '25mm 25mm' },
  modern: { fontFamily: 'Calibri, "Segoe UI", sans-serif', fontSize: '10pt', padding: '15mm 15mm' },
  singapore: { fontFamily: 'Calibri, "Segoe UI", sans-serif', fontSize: '11pt', padding: '20mm 20mm' },
  compact: { fontFamily: 'Arial, Helvetica, sans-serif', fontSize: '10pt', padding: '13mm 13mm' },
};
```
Apply the selected template's page style to the container `style` prop.

### Fix 6: Job cards should expand to show full description + skills analysis
**Location**: App.jsx — Jobs tab, ScraperTab component
**Problem**: Job cards only show title, company, location. No way to see the full JD or skills.
**Fix**: Make each job card expandable on click:
- Add `expandedJobId` state
- On click, toggle expansion
- Expanded view shows: full description, skills tags, "Required Skills Analysis" section
- MCF jobs have descriptions + skills in the DB already
- CareersGov jobs may not have descriptions — show "View full listing" link instead

### Fix 7: Missing keywords should link back to the JD context
**Location**: App.jsx — Resume tab, Relevant Terms / Missing section
**Problem**: Missing keywords are just red pills with no context. User doesn't know WHERE in the JD the keyword appears.
**Fix**: When user hovers/clicks a missing keyword, show the sentence from the JD that contains it. For example:
```
Missing: "collaborate"
From JD: "...collaborate with cross-functional teams to deliver..."
Suggestion: Add this to your teamwork bullet.
```
This requires passing the JD text to the frontend and doing a simple substring search around each keyword.

### Fix 8: Tracker tab messaging for free-tier users
**Location**: App.jsx ~line 1038
**Problem**: Shows "Application tracking requires an @aisg.sg account" even when user IS logged in (just on free tier).
**Fix**: Change to "Upgrade to AISG tier to track applications. Sign up with @aisg.sg to unlock."

---

## MEDIUM FIXES

### Fix 9: Power Match tab "not listed" fallback text
**Location**: App.jsx ~lines 803-805
**Fix**: Use `{item.job.location && <span>...</span>}` pattern instead of `|| "not listed"`

### Fix 10: Send `used_verbs` in AI rewrite request
**Location**: App.jsx — `handleBulletRewrite` function
**Fix**: Before calling API, collect first words of all other bullets:
```javascript
const usedVerbs = bulletSections
  .filter(s => s.id !== selectedBullet.id && s.type === "bullet")
  .map(s => s.text.split(/\s+/)[0]?.toLowerCase())
  .filter(Boolean)
  .join(", ");
// Add to request body: used_verbs: usedVerbs
```

### Fix 11: Pagination should use total pages from API
**Location**: App.jsx — Jobs tab pagination
**Fix**: Store `totalPages` from `data.pages` and show Next only when `page < totalPages`

### Fix 12: Certifications and education entries should not be annotated
**Location**: App.jsx — `annotateBullet` function
**Fix**: Check if text contains certification/education keywords and return neutral annotation.
The regex check `looksLikeCert` and `looksLikeEducation` may already be in the code — verify it's working.

---

## FEATURE ADDITIONS

### Feature 1: Job card expansion with JD + analytics
When clicking a job in the Jobs tab:
```
┌──────────────────────────────────────────────────────┐
│ Senior Engineer, HIG-HBM Product System & Eng.       │
│ MICRON SEMICONDUCTOR | North Coast Drive | $6K-$12K  │
│                                                      │
│ ▼ DESCRIPTION                                        │
│ Responsibilities: Reliability Test Program Coding... │
│                                                      │
│ ▼ TOP SKILLS REQUIRED (from this JD)                 │
│ [Reliability Testing] [Electronics] [Python] [C++]   │
│ [Problem Solving] [Semiconductor]                    │
│                                                      │
│ ▼ YOUR MATCH (if resume uploaded)                    │
│ 4/6 skills matched • 67% match                      │
│ Missing: [C++] [Reliability Testing]                 │
│                                                      │
│ [Generate Resume for This Job] [+ Track] [View]      │
└──────────────────────────────────────────────────────┘
```

### Feature 2: AI generates points to match the JD
When clicking "Generate Resume for This Job":
- Compare user's resume against this job's skills/description
- AI suggests which bullets to modify and what keywords to add
- Uses the existing POST /api/ai/integrate-keywords endpoint

### Feature 3: Keyword context from JD
When showing "Missing" keywords in the resume workspace:
- Each keyword should show the sentence from the JD that mentions it
- Helps user understand WHY the keyword matters for this specific role
- Simple implementation: find the keyword in JD text, extract surrounding sentence

---

## TESTING CHECKLIST

After all fixes, verify:
- [ ] Upload resume PDF → text appears, name parsed, score calculated
- [ ] Score shows bullet count > 0 (not "0/0 bullets")
- [ ] "AI Improve All" reformats resume AND re-scores
- [ ] "AI Rewrite This Bullet" shows 3 options (not empty) — uses 32B model (fast, interactive)
- [ ] Accepting a rewrite updates the resume text
- [ ] "Finalize Score" triggers a fresh score
- [ ] Certifications not flagged as "Review Opening"
- [ ] Resume preview matches DOCX template (font, margins, spacing)
- [ ] Download DOCX produces a real file
- [ ] Job cards expand to show full description
- [ ] Missing keywords show JD context
- [ ] Pagination shows correct total and pages
- [ ] No "not listed" fallback text anywhere
- [ ] All buttons have loading states
- [ ] All API calls have error handling
- [ ] No console errors in browser dev tools

### Pipeline-specific tests (new backend):
- [ ] `POST /api/resume/tailor` with `{resume_text, job_id, intensity: "full"}` returns `session_id`
- [ ] `GET /api/resume/tailor/{session_id}/status` returns progress stages correctly
- [ ] `GET /api/resume/tailor/{session_id}/result` returns tailored resume + REAL before/after skill match (re-scanned, not estimated)
- [ ] `POST /api/resume/tailor/{session_id}/feedback` with `{bullet_id, action: "accept"}` marks change
- [ ] `POST /api/resume/tailor/{session_id}/apply` applies only accepted changes, returns final text + score
- [ ] `GET /api/jobs/{job_id}/parsed` returns pre-parsed JD with required_skills, preferred_skills
- [ ] Pipeline runs all 7 stages without crashing. If AI calls fail, `pipeline_notes` explains what degraded (no hidden fallbacks).
- [ ] Validation gates reject hallucinated metrics (test: add fake "$5M" to a bullet that had no numbers)
- [ ] AI phrase cleanup replaces "spearheaded" with "led" (unless JD uses "spearheaded")
- [ ] Verb dedup: if two bullets in same job entry start with "Led", second gets replaced with synonym
- [ ] `ats_gaps` in result shows remaining missing skills with suggested section + entry for each
- [ ] Skills section gets reordered: JD-matched skills moved to top
- [ ] `skill_match.after` is an actual re-scan of tailored text, not an estimate
- [ ] Stage 3 uses JSON output format (`{"rewrites": [...]}`) with numbered-line fallback

---

## NEW: Resume Tailoring Pipeline (backend complete, needs frontend)

### Why we built this

Our old approach was broken. We were sending the entire resume + JD in a single LLM call and asking it to review every bullet, diagnose issues, rewrite them, AND integrate keywords -- all at once, capped at 3000 tokens. Even a strong model produces mediocre results when you cram 5 tasks into one call.

We studied Resume-Matcher (26K stars, similar FastAPI stack) and found they use a **multi-pass pipeline**: separate focused calls for keyword extraction, bullet rewriting, keyword injection, AI phrase cleanup, and hallucination detection. Each call does ONE thing well.

Our new pipeline applies the same principle:
- **Structured data model**: Resume is parsed into sections/entries/bullets with IDs (not a flat string). Every AI call knows exactly what section and entry it's working in.
- **Focused calls**: One call for strategy (which bullets to prioritize), separate calls for per-bullet rewrites (batched 4 at a time), one call for executive summary.
- **Local validation**: 5 gates check every AI rewrite -- fact preservation, hallucination detection, AI phrase cleanup, length sanity, keyword verification. No LLM cost for these.
- **Pre-parsed JDs**: Job descriptions are analyzed at scrape time (regex, ~50ms, no LLM). When a user clicks "Tailor", skill gaps are instant -- no waiting for JD analysis.
- **70B reasoning model**: The API gives us `Llama-SEA-LION-v3.5-70B-R` (70B reasoning) at the same rate limit and cost as the 32B. Pipeline uses 70B since it runs in background. Single-bullet interactive rewrites use 32B for speed.

### Architecture
A 7-stage pipeline that transforms a raw resume into a JD-tailored version. Runs as a background thread with progress polling.

**New backend files** (do NOT modify these, they are tested and working):
- `jd_preparser.py` — pre-parses JDs at scrape time (runs on every new job, ~50ms, no LLM)
- `resume_structurer.py` — parses resume into structured sections/entries/bullets
- `ai_phrases.py` — 107 AI-sounding phrase replacements with JD protection
- `validation_gates.py` — 5 validation gates (fact preservation, hallucination detection, etc.)
- `tailoring_pipeline.py` — 7-stage orchestrator

**Model selection**:
- Single bullet rewrite (`/api/ai/rewrite`): **32B Qwen** (fast, interactive, user is watching)
- Full pipeline (`/api/resume/tailor`): **70B Llama reasoning** (background, user sees progress bar)

**New endpoints**:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `POST /api/resume/tailor` | Start pipeline | `{resume_text, job_id, intensity}` -> `{session_id}` |
| `GET /api/resume/tailor/{session_id}/status` | Poll progress | Returns stage number, progress %, message |
| `GET /api/resume/tailor/{session_id}/result` | Get result | Returns full result + `ats_gaps` + real `skill_match` |
| `POST /api/resume/tailor/{session_id}/feedback` | Accept/reject | `{bullet_id, action: "accept"|"reject"|"edit", edited_text}` |
| `POST /api/resume/tailor/{session_id}/apply` | Apply changes | Applies accepted changes only, returns final text + score |
| `GET /api/jobs/{job_id}/parsed` | Get parsed JD | Returns pre-parsed skills/requirements |

**`intensity` levels**:
- `"nudge"` — local fixes only (AI phrase cleanup, verb dedup). No LLM calls. ~5 seconds.
- `"keywords"` — nudge + keyword injection + bullet rewrites. ~30 seconds.
- `"full"` — everything + executive summary generation. ~45-60 seconds.

### Frontend work needed
1. **"Tailor for This Job" button** on job cards (expanded view) and in the Resume tab when a job is selected
2. **Progress UI**: poll `/status` every 2-3s, show stage name + progress bar. 7 stages with labels.
3. **Result display**: show before/after diff per bullet, accept/reject/edit controls per change
4. **Accept/reject flow**: each change shows original vs tailored. User clicks Accept, Reject, or Edit. Uses `POST /feedback` endpoint.
5. **"Apply Changes" button**: calls `POST /apply` endpoint, only applies accepted changes. Shows final score.
6. **ATS Gap Report**: after pipeline completes, show `ats_gaps` from result:
   - Each missing skill shows: name, required/preferred badge, suggested section + entry
   - If `needs_user_input: true`, show input: "Do you have experience with [skill]? Describe briefly."
   - Actions: [Add to bullet] [Add to Skills only] [Skip - I don't have this]
7. **Score comparison**: show skill match before/after (real re-scanned numbers) AND resume score before/after
8. **Loading states**: clear loading during pipeline. Show active stage name. No hidden spinners.
9. **Pipeline notes**: if `result.degraded` is true, show `pipeline_notes` explaining what degraded. No hidden fallbacks.

### DB changes
- `ScrapedJob` has new `parsed_jd` JSON column (auto-populated at scrape time)
- `TailoredResume` table for session tracking (not yet used by frontend)

---

## CODE REVIEW REQUEST FOR CODEX

Codex: you are the second pair of eyes. The new pipeline files were written in one session and need a thorough review. Please check ALL of the following:

### 1. Import + runtime verification
For each new backend file, verify it actually imports and runs without error:
```bash
cd backend
python3 -c "from jd_preparser import preparse_job_description; print('jd_preparser OK')"
python3 -c "from resume_structurer import structure_resume, get_all_bullets, flatten_to_text; print('structurer OK')"
python3 -c "from ai_phrases import clean_ai_phrases; print('ai_phrases OK')"
python3 -c "from validation_gates import run_all_gates, validate_and_fix; print('gates OK')"
python3 -c "from tailoring_pipeline import run_pipeline, get_pipeline_state; print('pipeline OK')"
```

### 2. Database migration
The `ScrapedJob` model now has a `parsed_jd` column and there's a new `TailoredResume` table. Verify:
- SQLite creates these on `init_db()` (SQLAlchemy `create_all`)
- Existing data is not lost
- The `parsed_jd` column is nullable (old jobs can have NULL)

### 3. Endpoint contract verification
Test each new endpoint returns the documented response shape:
- `POST /api/resume/tailor` - returns `{session_id, status, estimated_seconds}`
- `GET /api/resume/tailor/{id}/status` - returns `{stage, stage_number, total_stages, progress, message, complete}`
- `GET /api/resume/tailor/{id}/result` - returns `{tailored_text, changes[], skill_match{before, after, matched_after, missing_after}, score{before, after}, ats_gaps[]}`
- `POST /api/resume/tailor/{id}/feedback` - returns `{bullet_id, action, accepted, rejected, pending}`
- `POST /api/resume/tailor/{id}/apply` - returns `{tailored_text, applied, rejected, skipped_pending, score_after}`
- `GET /api/jobs/{id}/parsed` - returns `{job_id, title, company, parsed_jd, has_parsed_jd}`

### 4. Error path verification
Confirm NO hidden fallbacks. Every error path should either:
- Return an explicit HTTP error with a clear message, OR
- Add to `pipeline_notes` explaining what degraded and why

Check specifically:
- What happens if the LLM returns empty/null for Stage 1 strategy?
- What happens if Stage 3 JSON parsing fails AND the numbered-line fallback also fails?
- What happens if `_stage_6_validate` receives a structured resume with zero sections?
- What happens if `parsed_jd` is None when `_execute_pipeline` runs?

### 5. Validation gate edge cases
Test these with unit tests:
- `gate_fact_preservation`: original has "$3M", tailored changes to "$3.5M" - should FAIL
- `gate_fact_preservation`: original has "12 engineers", tailored has "12 engineers" - should PASS
- `gate_hallucination`: tailored adds "Kubernetes, Docker, Terraform" when original had none - should FAIL
- `gate_ai_phrases`: tailored says "spearheaded", JD also says "spearheaded" - should be PROTECTED (not replaced)
- `gate_length_sanity`: 45-word rewrite of a 20-word original - should FAIL (>1.8x)

### 6. Concurrency check
The pipeline uses `threading.Thread`. Verify:
- `_active_pipelines` dict access is thread-safe (uses `_pipelines_lock`)
- `PipelineState` updates are thread-safe (uses `self._lock`)
- Rate limiter handles concurrent pipeline threads (multiple threads calling `_call_sealion`)

### 7. Memory / cleanup
- `_active_pipelines` has a TTL cleanup. Verify `_cleanup_expired_pipelines()` is actually called somewhere (it may need to be wired into lifespan or a periodic task).
- Each pipeline result stores full resume text. With many concurrent users, check memory isn't unbounded.

### 8. Known issues to fix if found
- `_cleanup_expired_pipelines` is now called on every `get_pipeline_state()` read. Verify it works.
- `auth.py` now generates ephemeral JWT keys in local dev (not a hardcoded fallback). Verify tokens work during a dev session.
- `main.py` uses `lifespan` instead of deprecated `on_event("startup")`. Verify startup still works correctly.

---

## FULL REVIEW SPEC

**See `CODEX_REVIEW.md` for the complete 6-phase review checklist.**

Codex: when you pick up this project, run the review FIRST before doing any feature work. The pipeline was built in one session and needs a reliability audit. The review spec has test cases to write, error paths to trace, and specific bugs to check for. Write results to `REVIEW_RESULTS.md`.

---

## ADDITIONAL FEATURE: Smart Keyword Integration

### The Flow
1. JD skills are extracted as MULTI-WORD phrases (not single words)
   - "project management" not "project" + "management"  
   - "cross-functional collaboration" not "cross" + "functional" + "collaboration"
   - "semiconductor manufacturing" not "semiconductor" + "manufacturing"

2. When showing "Missing" keywords in the resume workspace:
   - Each keyword shows the sentence FROM THE JD where it appears
   - User clicks a missing keyword
   - AI generates 3 sentence options that:
     a) Keep the keyword as EXACT MATCH (verbatim, not paraphrased)
     b) Fit naturally into the user's existing resume style
     c) Reference their actual experience (not hallucinated)

3. User picks an option → it inserts into their resume at the right place

### Backend Endpoint (already exists)
`POST /api/ai/integrate-keywords` — accepts resume_text + missing_keywords + job_title

### Frontend Implementation
- In the "Missing" keywords section, make each pill CLICKABLE
- On click, show:
  1. JD context: the sentence containing this keyword
  2. "AI Suggest" button → calls /api/ai/integrate-keywords for this keyword
  3. 3 rewrite options with the keyword in BOLD
  4. Accept → inserts into resume text

### Multi-Word Phrase Extraction
The keyword extraction currently splits on single words. Need to extract phrases:
- Use the job's `skills` array from the database (MCF provides these as phrases)
- For JD text: extract noun phrases (2-3 word combinations) not just individual words
- Common multi-word skills: "machine learning", "data analysis", "project management", etc.
- Maintain a skills dictionary of known multi-word terms

