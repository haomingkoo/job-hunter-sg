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
- [ ] "AI Rewrite This Bullet" shows 3 options (not empty)
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
