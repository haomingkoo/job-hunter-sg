# REVIEW RESULTS — Resume Tailoring Pipeline

## Summary

- Review date: 2026-03-24
- Reviewer: Codex
- Scope: `CODEX_REVIEW.md` Phases 1-6
- Total issues found: `1`
- Critical: `0`
- Medium: `1`
- Low: `0`

## What I Ran

### Phase 1: Imports

Verified all requested imports in `backend/`:

- `jd_preparser.preparse_job_description`
- `resume_structurer.structure_resume`, `get_all_bullets`, `flatten_to_text`
- `ai_phrases.clean_ai_phrases`, `AI_PHRASE_REPLACEMENTS`
- `validation_gates.run_all_gates`, `validate_and_fix`
- `tailoring_pipeline.run_pipeline`, `get_pipeline_state`, `STAGES`
- `models.ScrapedJob`, `TailoredResume`

Result: all imports passed cleanly.

### Phase 2: Validation gates safety net

Added [test_validation_gates.py](/Users/koohaoming/dev/job-hunter-sg/backend/test_validation_gates.py) with 13 gate-focused tests covering:

- fact preservation
- AI phrase replacement and JD protection
- keyword verbatim matching
- length sanity
- hallucination detection
- `validate_and_fix()` revert / auto-fix behavior

Run:

```bash
cd backend && python3 -m pytest test_validation_gates.py -v
```

Result: `13 passed`

### Phase 3: Integration checks

Verified:

- `preparse_job_description("")` returns an empty structured object with timestamp
- real DB JD parsing works against an existing `ScrapedJob`
- `structure_resume()` preserves contact info, sections, bullets, and round-trips via `flatten_to_text()`
- `run_pipeline(..., intensity="nudge")` completes end-to-end

Added [tests/test_tailoring_pipeline_review.py](/Users/koohaoming/dev/job-hunter-sg/backend/tests/test_tailoring_pipeline_review.py) with review-focused integration checks.

### Phase 4: Error-path audit

Explicitly tested / verified:

- Stage 1 strategy fallback marks pipeline as degraded
- Stage 3 invalid JSON rewrite batches do not crash and keep originals
- validation-gate failures do not create bullet changes
- empty JD parsing does not crash
- no-bullet resumes skip Stage 3 cleanly
- concurrent pipelines keep separate results

### Phase 5: Specific bug checklist

Verified:

- `_stage_6_validate()` signature includes `parsed_jd` and `state`
- `skill_match.after` comes from real post-tailor re-scan
- `call_sealion_json()` really parses JSON inside the retry loop
- Stage 3 uses `call_sealion_json()`, not raw `_call_sealion()`
- `_cleanup_expired_pipelines()` runs via `get_pipeline_state()`
- FastAPI app uses lifespan and has no startup handlers
- `auth.py` generates an ephemeral JWT secret in local dev instead of using a hardcoded fallback

## Issue Found

### 1. Summary-stage degradation was still silent

- Severity: Medium
- File: [tailoring_pipeline.py](/Users/koohaoming/dev/job-hunter-sg/backend/tailoring_pipeline.py#L687)
- Description:
  If Stage 5 summary generation returned `None` or unusable content, the pipeline silently kept the current summary state. The user could only infer this from logs, which violated the “no hidden fallbacks” rule in the review doc.
- Fix applied:
  - Stage 5 now returns `_degraded` and `_degraded_reason` when summary polishing is unavailable or unusable in [tailoring_pipeline.py](/Users/koohaoming/dev/job-hunter-sg/backend/tailoring_pipeline.py#L687)
  - `_execute_pipeline()` now appends an explicit `summary_fallback` pipeline note in [tailoring_pipeline.py](/Users/koohaoming/dev/job-hunter-sg/backend/tailoring_pipeline.py#L1005)
- Test added:
  - [tests/test_tailoring_pipeline_review.py#L176](/Users/koohaoming/dev/job-hunter-sg/backend/tests/test_tailoring_pipeline_review.py#L176)

## Test Results

Combined review suite:

```bash
cd backend && python3 -m pytest tests/test_features.py test_validation_gates.py tests/test_tailoring_pipeline_review.py -q
```

Result: `67 passed in 26.40s`

## Remaining Concerns

- No additional reliability bugs were found in the reviewed phases after the summary-stage fix.
- The pipeline still relies on local heuristics for some resume structure and ATS gap placement. That is acceptable for now, but it remains an area to watch as more resume formats are supported.
- This review did not change architecture or add product features; it focused on explicit failure handling, validation coverage, and bug-proofing the existing pipeline.
