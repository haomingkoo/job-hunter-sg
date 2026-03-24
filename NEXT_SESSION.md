# Next Session - Priority Issues

## Critical (deploy-breaking)

### FIXED: 405 on /api/resume/tailor
Static mount was before pipeline routes. Moved to end of file. Deployed.

## High Priority (UX bugs visible to users)

### 1. Education entries lumped together
Two degrees (M.Sc. and B.Sc.) render as one block instead of separate entries.
The frontend `parseResumeToSections` function doesn't detect "B.Sc." as a new entry within the Education section.
**Fix**: In `parseResumeToSections`, detect lines starting with degree abbreviations (M.Sc., B.Sc., B.Eng, MBA, etc.) as new subheadings within education sections.

### 2. Section order wrong in preview
"Additional Information" and "Languages" appear before "Professional Summary".
The backend parses correctly (line 3 = Professional Summary, line 40 = Additional Information).
**Fix**: Frontend template ordering is overriding the natural order. Check `RESUME_TEMPLATE_SECTION_ORDER` and `templateOrder` in `parseResumeToSections`.

### 3. Empty sections still render
"ADDITIONAL INFORMATION" shows as a heading with no content below it.
**Fix**: Skip rendering sections that have no entries and no content.

### 4. ATS gap integration UI
The pipeline returns `ats_gaps` with suggested placement per missing skill, but there's no frontend UI to:
- Show each missing skill with its suggested section/entry
- Let user click to add it (either to a bullet or skills section)
- Get AI-generated sentence suggestions for integration
**Design**: Each missing skill pill should be clickable. On click, show: suggested entry, AI-generated bullet incorporating the keyword, accept/skip buttons.

### 5. Summary optimization button
Stage 5 of the pipeline generates a new summary, but there's no standalone "Optimize Summary" button.
Users should be able to click on the Professional Summary section and get AI to rewrite it based on the bullets below + the target JD.

### 6. Filter dropdowns need backend data
The `filter_meta` is now returned from `/api/jobs` but frontend may not be consuming it yet for employment type dropdown. Also the employment_type data for 66K MCF jobs is empty until next crawl.

## Medium Priority

### 7. Overused word rewrites still use the same words
Fixed: now passes the specific overused words to the rewrite prompt. Needs verification.

### 8. Sort default should be "Newest"
Was changed in the feature branch but may have been overwritten by Codex changes. Verify.

### 9. Cover letter generation
Not built yet. Natural extension of the pipeline (resume + JD + strategy = cover letter).

## For Codex

Run `CODEX_REVIEW.md` - it has 6 mechanical tasks (import check, unit tests, pipeline test, error path audit, live API check, write results). Do not just read - RUN.
