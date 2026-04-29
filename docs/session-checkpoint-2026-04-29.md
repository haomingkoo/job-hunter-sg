# Session Checkpoint - 2026-04-29

## Current State

- Branch: `main`
- Latest pushed commit: `e28e379 polish app copy and account layout`
- Previous commit before this session's push: `d64fba2 fix: clean noisy analytics and bridge gaps`
- Build checked: `npm run build` in `frontend/`
- Frontend tests checked: `npm test` in `frontend/` (`103` tests passed)

## What Changed This Session

This session focused on making the app feel lighter, clearer, and less internal/technical in user-facing copy.

### Account Page

File: `frontend/src/components/AccountTab.jsx`

- Added internal account subviews:
  - `Overview`
  - `Plans & Privacy`
  - `Admin` for admin users only
- Moved admin metrics out of the default account page.
- Moved plan comparison and legal/privacy into `Plans & Privacy`.
- Kept profile, usage, quick actions, alerts, and contact in `Overview`.
- Changed admin metrics loading so it only runs when the `Admin` subview is opened.
- Fixed usage limit display:
  - Before: `/ Unlimited limit`
  - After: `Unlimited`
- Simplified account copy:
  - `Manage your account, usage, saved work, and support requests.`
  - became `Manage your account, saved work, alerts, and support.`

### Market Insights

File: `frontend/src/components/AnalyticsTab.jsx`

- Replaced the confusing headline metric:
  - Before: `Official SSIC 7%`
  - After: `Industry mapped`
- New `Industry mapped` value combines official SSIC matches and inferred industry mappings.
- Kept SSIC transparency in helper copy instead of making it a primary KPI.
- Simplified market labels:
  - `Unique ATS terms` -> `Skill terms`
  - `ATS read` -> `Skill signal`
  - `Drill Down` -> `Explore Market`
  - `ATS Hard Skills` -> `Hard Skills`
  - `Over-Indexed Skills` -> `Standout Skills`
  - `Over-indexing recently` -> `Rising recently`

### Job Cards

File: `frontend/src/components/ScraperTab.jsx`

- Replaced internal/AI-heavy job card copy:
  - `AI Summary` -> `Job Summary`
  - `Original Description` -> `Full Description`
  - `Source Tags & Skill Cues` -> `Skills Found`
  - `parsed JD cues` -> `job terms`
  - `practical ATS cues` -> `reliable skill terms`
- Simplified skill extraction loading and empty states.

### Interview Prep Card

File: `frontend/src/components/InterviewPrep.jsx`

- Made the interview prep card smaller and visually quieter on expanded job cards.
- Reduced padding, icon size, loading state height, and empty-state footprint.
- Changed copy:
  - `Prep for Interview` -> `Interview prep`
  - `Build your story bank to see prep suggestions here` -> `Add a few stories to get interview prompts for this role.`
  - `Go to Story Bank` -> `Add stories`

### Resume Editor

Files:

- `frontend/src/components/ResumeTab.jsx`
- `frontend/src/lib/resumeConstants.js`

Removed user-facing NUS/internal wording and made labels more product-like:

- `Reference Cues` -> `Resume Guide`
- `NUS benchmark signals` -> `Recommended targets`
- `Benchmark Snapshot` -> `Resume Targets`
- `Relevant Terms` -> `Job Terms`
- `Open Improvements` -> `Suggested Fixes`
- `Improvement Queue` -> `Next Fixes`
- `Full Tailor Run` -> `Tailor Resume`
- `JD Alignment Snapshot` -> `Job Match`
- `AI ready` -> `Assistant ready`
- `AI Summary` -> `Rewrite Summary`
- `NUS-ready` -> `SG-ready`
- `Final score pending` -> `Draft edited`

Also changed keyword guidance to discourage stuffing:

- Before: `Click to insert`
- After: `Use naturally`

## Files Changed In Pushed Commit

- `frontend/src/components/AccountTab.jsx`
- `frontend/src/components/AnalyticsTab.jsx`
- `frontend/src/components/InterviewPrep.jsx`
- `frontend/src/components/ResumeTab.jsx`
- `frontend/src/components/ScraperTab.jsx`
- `frontend/src/lib/resumeConstants.js`

## Codebase Map

### App Entry And Routing

- `frontend/src/App.jsx`
  - Main tab routing and app-level state.
  - Wires tabs like Jobs, Resume, Stories, Applications, Market Insights, Smart Match, Account.
- `frontend/src/components/Nav.jsx`
  - Top navigation tabs.

### Jobs Experience

- `frontend/src/components/ScraperTab.jsx`
  - Main Jobs tab.
  - Search/filter UI, job cards, expanded job details, job actions.
  - Mounts `InterviewPrep`.
  - Good first file for copy/layout issues on job cards.
- `frontend/src/components/InterviewPrep.jsx`
  - Interview prep module shown inside expanded job cards.
  - Uses `/api/stories/suggest/:jobId`.
- `frontend/src/components/JobCardSkeleton.jsx`
  - Loading skeleton for job cards.

### Resume Experience

- `frontend/src/components/ResumeTab.jsx`
  - Large resume editor workspace.
  - Handles upload/setup, scoring panels, improvement queue, inline editor, templates, tailoring, export.
  - Most resume UI copy lives here.
- `frontend/src/lib/resumeConstants.js`
  - Resume templates, benchmark constants, shared labels.
- `frontend/src/lib/resumeHelpers.jsx`
  - Resume parsing/rendering helpers.
- `frontend/src/lib/__tests__/resumeHelpers.test.js`
  - Frontend resume helper tests.

### Story Bank And Interview Prep

- `frontend/src/components/StoriesTab.jsx`
  - Story bank creation, editing, and generation UI.
- `frontend/src/lib/storyConstants.js`
  - Story tags and constants.
- `frontend/src/components/InterviewPrep.jsx`
  - Pulls story suggestions into job cards.

### Market Insights

- `frontend/src/components/AnalyticsTab.jsx`
  - Market Insights dashboard.
  - Industry/sector drilldowns, skill demand, salary, seniority, market movers.
- Backend API source is in `backend/main.py` around the analytics endpoint.
- Related backend helpers:
  - `backend/company_taxonomy.py`
  - `backend/skills_taxonomy.py`
  - `backend/ats_terms.py`
  - `backend/backfill_company_ssic.py`

### Account, Alerts, Legal

- `frontend/src/components/AccountTab.jsx`
  - Account overview, usage, quick actions, job alerts, plan/privacy, admin metrics, contact.
- `backend/job_alerts.py`
  - Job alert logic.
- `backend/send_job_alerts.py`
  - Alert sender.
- `backend/legal_pages.py`
  - Terms/privacy content endpoints.

### Smart Match

- `frontend/src/components/PowerTab.jsx`
  - Smart Match and course recommendation UI.
- Backend helpers:
  - `backend/embedding_service.py`
  - `backend/skillsfuture_courses.py`
  - `backend/ai_service.py`

### Tracker And Reminders

- `frontend/src/components/TrackerTab.jsx`
  - Application tracker.
- `frontend/src/components/RemindersTab.jsx`
  - Follow-up reminders.

### Backend Core

- `backend/main.py`
  - Main FastAPI app and API routes.
- `backend/models.py`
  - Data models.
- `backend/database.py`
  - Database access.
- `backend/job_store.py`
  - Job persistence/querying.
- `backend/scraper.py`
  - Job scraping.
- `backend/job_precompute.py`
  - Precompute pipeline.
- `backend/jd_preparser.py`
  - Job description preprocessing.
- `backend/jd_summary.py`
  - Job summary logic.

### Resume Backend

- `backend/resume_parser.py`
  - Resume extraction/parsing.
- `backend/resume_scorer.py`
  - Resume scoring.
- `backend/resume_structurer.py`
  - Resume structure normalization.
- `backend/resume_templates.py`
  - Resume template rendering.
- `backend/tailoring_pipeline.py`
  - Full tailoring pipeline.
- `backend/validation_gates.py`
  - Tailoring/rewrite validation gates.

### Tests

- Frontend:
  - `cd frontend && npm test`
  - Main current suite: `frontend/src/lib/__tests__/resumeHelpers.test.js`
- Backend/top-level:
  - `pytest`
  - Relevant tests live in `tests/` and `backend/tests/`.

## Good Next Steps

- Review Account page visually at desktop and mobile widths, especially the new internal account subnav.
- Consider a broader copy system pass for repeated terms:
  - prefer `Job terms` over `ATS terms` in user UI
  - prefer `Skill terms` over `cues`
  - prefer `Assistant` over `AI` for status labels
- Consider splitting `ResumeTab.jsx` later. It is very large and owns many concerns.
- Consider moving admin metrics into a dedicated top-level admin route if the admin area keeps growing.
