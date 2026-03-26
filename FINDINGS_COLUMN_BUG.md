# Resume Preview Two-Column Bug: Findings + Fix

Date: 2026-03-26  
Branch: `feat/jd-summary-cache`

## Symptom
In the Resume tab document preview, long paragraphs (especially in `PROFESSIONAL SUMMARY`) render in two columns instead of full-width single-column text. This happens across templates.

## Root Cause
Even though no explicit `column-count` or column CSS existed in Tailwind or template styles, the preview container could still inherit or be affected by a column context (browser quirks, injected styles, or dependency side effects). Once a column context exists, long paragraphs flow left-to-right in columns.

We found one inline style that hinted at a column context:
- `columnSpan: "all"` in `heading_paragraph` blocks in `frontend/src/components/ResumeTab.jsx`, which only makes sense when a parent is in a column layout.

## Fix Applied
To make the preview immune to any column layout, we explicitly reset column properties on the page and body styles returned by `buildResumeTemplateStyles()`:

File: `frontend/src/lib/resumeHelpers.jsx`
- Added the following to `pageStyle`:
  - `columnCount: 1`
  - `columnWidth: "auto"`
  - `columnGap: "normal"`
  - `columnFill: "auto"`
- Added the following to `bodyStyle`:
  - `display: "block"`
  - `width: "100%"`
  - `maxWidth: "100%"`
  - `columnCount: 1`
  - `columnWidth: "auto"`
  - `columnGap: "normal"`

This forces a single-column flow regardless of any injected or inherited column styles.

## Related CSS Build Fix
`npm run build` failed due to CSS import order:
```
@import must precede all other statements
```
Fixed by moving the Google Fonts `@import` to the top of `frontend/src/index.css`.

## Verification
- `npm run build` now passes.
- The resume preview should render summary paragraphs as full-width single-column text across all templates.

## Notes for Buddy Check
- If the two-column bug persists in production, it’s likely stale assets. The new build outputs:
  - `dist/assets/index-CkcR1baf.js`
  - `dist/assets/index-CNDwT1Ep.css`
