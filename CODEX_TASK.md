# Codex Task: Validate & Fix Resume Parser

## Overview

The resume parser has two implementations (frontend JS + backend Python) that
share a classification config (`shared/resume-classification.json`). Both need
to correctly parse ANY resume format uploaded by users. Currently there are
rendering issues where bullets split across lines, headings get fragmented,
and dates don't merge with position entries.

## Resume Database for Testing

We have 13 curated resume text fixtures extracted from real PDFs/DOCX files:

```
tests/fixtures/resumes_curated/
├── Haoming_Koo_Apple_BusinessProcessReengineeringManager_Resume.txt
├── Haoming_Koo_CAG_CommercialStrategyAnalytics_Resume.txt
├── Haoming_Koo_CapGemini_ProgramManager_328506_Resume.txt
├── Haoming_Koo_DBS_VP_DataScientist_Chapter_Resume.txt
├── Haoming_Koo_Dyson_Resume.txt
├── Haoming_Koo_Emerald.txt
├── Haoming_Koo_Generic_Resume.txt
├── Haoming_Koo_Govt_Resume.txt
├── Haoming_Koo_HTX_LeadEngineer_Resume.txt
├── Haoming_Koo_KLA_TPM_Resume.txt
├── Haoming_Koo_Meta_TPM_Final_Updated.txt
├── Haoming_Koo_Mondelez.txt
└── Haoming_Koo_TikTok_DataProductManager_Resume.txt
```

To add more fixtures, run:
```bash
cd backend && python scripts/extract_resume_fixtures.py
```

132 additional resume PDFs are available in `~/Documents/Resumes/`.

## How to Run Tests

```bash
# Backend parser tests (143 tests)
cd backend && python -m pytest tests/test_resume_structurer_comprehensive.py -v

# Frontend parser tests (90 tests)
cd frontend && npx vitest run

# Frontend build check
cd frontend && npx vite build
```

## What to Validate

### For EACH fixture file, run BOTH parsers and check:

#### Backend (`backend/resume_structurer.py` → `structure_resume()`)
```python
import sys; sys.path.insert(0, '.')
from resume_structurer import structure_resume
text = open('../tests/fixtures/resumes_curated/FILENAME.txt').read()
result = structure_resume(text)
# Check:
# - result['contact']['name'] == 'Haoming Koo'
# - result['sections'] has experience, education sections
# - Each experience entry has correct company, title, date_range
# - Bullets are under the correct entry (not orphaned)
# - No garbage section keys like 'dns.' or 'hbm.'
# - stats['total_bullets'] is reasonable (10-30 for a 2-page resume)
```

#### Frontend (`frontend/src/lib/resumeHelpers.jsx` → `parseResumeToSections()`)
Write a Node.js script or vitest test that:
```javascript
import { parseResumeToSections } from './resumeHelpers.jsx';
const text = fs.readFileSync('../../tests/fixtures/resumes_curated/FILENAME.txt', 'utf-8');
const sections = parseResumeToSections(text, []);
// Check:
// - Every bullet (type=bullet) has non-empty text
// - No bullet marker • appears as its own section (text should be merged)
// - Headings have correct sectionKey (not empty string)
// - No more than 2 consecutive spacers (no huge gaps)
// - Paragraphs are not fragments (minimum ~20 chars unless it's a date)
// - Position subheadings have dates (variant=dated, not just variant=company)
```

### Cross-parser consistency
For each fixture, compare:
- Backend section keys vs frontend section keys (should match)
- Backend bullet count vs frontend bullet count (should be close)
- Backend entry count vs frontend subheading count (should correspond)

## Known Issues (see PARSER_ISSUES.md for details)

1. **Bullet marker on own line** — `•\n text` should be `• text`
2. **Continuation lines as paragraphs** — wrapped text becomes bold/light split
3. **Standalone dates** — `2022\n2025` should merge as `2022 – 2025`
4. **Split headings** — `CERTIFICATIONS\n& Career Development` should be one heading
5. **False entries from pipes in bullets** — `6 | 9 engineers` is not a heading
6. **Garbage ALL-CAPS headings** — `HBM.` or `DNS.` are not section headings

## Priority Fixes Needed

### High Priority
- Bullets must ALWAYS render with their full text (no splitting)
- Section headings must be detected correctly
- Position entries must group company + title + dates

### Medium Priority
- Cross-parser consistency (both agree on section types)
- Education cards render cleanly (degree, university, dates)
- Skills section renders as proper list, not fragmented paragraphs

### Low Priority
- Contact header editable
- Continuation line merging for very long paragraphs

## Architecture

```
shared/resume-classification.json     ← Single source of truth for headings/keys
    ↓                    ↓
backend/                 frontend/src/lib/
shared_classification.py resumeConstants.js (imports JSON)
resume_structurer.py     resumeHelpers.jsx
    ↓                        ↓
AI pipeline, scoring     Visual preview, inline editing
```

## Files to Focus On

| File | What it does |
|------|-------------|
| `frontend/src/lib/resumeHelpers.jsx` | Frontend parser — `parseResumeToSections()` is the main function. Pre-processing at top, line-by-line parsing, then post-processing chain |
| `frontend/src/lib/resumeConstants.js` | Heading sets, bullet regex, section labels — imports from shared config |
| `backend/resume_structurer.py` | Backend parser — `structure_resume()`, `_build_entries()`, `_is_entry_heading()` |
| `backend/resume_scorer.py` | Scoring engine — uses `STANDARD_SECTIONS`, `_section_key()` |
| `shared/resume-classification.json` | 68 headings, 68 key mappings, 30 title patterns, 9 bullet markers |
| `tests/fixtures/resumes_curated/*.txt` | Test data — 13 real resumes |
| `backend/tests/test_resume_structurer_comprehensive.py` | Backend test suite |
| `frontend/src/lib/__tests__/resumeHelpers.test.js` | Frontend test suite |

## Acceptance Criteria

Upload any of the 13 fixture resumes and verify the document preview shows:
- Clean section headings (no fragments, no garbage)
- Bullets with full text (no bold/light splits, no orphaned lines)
- Position entries grouped properly (title + company + dates)
- Education as clean cards
- Skills as a proper list
- No huge empty gaps between sections
