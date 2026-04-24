# Changelog

Notable changes to Job Hunter SG are tracked here.

## 2026-04-25

### Added
- Jobs now store source posting IDs, openings, and company SSIC metadata fields for official industry classification.
- Market Insights now reports ACRA SSIC coverage and distinguishes official industry sectors from inferred fallbacks.
- Added `backfill_company_ssic.py` to populate company SSIC metadata from official ACRA data.gov.sg datasets on explicit runs.
- Market Insights now exposes a visible Drill Down panel near the top so source, sector, and title filters are easier to discover.
- Market Insights now includes source drilldowns for Careers@Gov/MyCareersFuture, clickable company/department rankings, and directional market movers based on recent versus older dated postings.
- Story Bank generation now shows an indeterminate progress bar and rotating status text while resume-based stories are being extracted.
- Account now includes quick actions, AI request usage, and cleaner unlimited-limit display.
- Smart Match now shows the exact stored resume snapshot, word count, update time, and snapshot hash used for matching.

### Changed
- Job deduplication is now source-aware: official posting IDs or canonical source URLs are used before title/company fallback, preserving distinct postings with the same title and employer.
- Sector inference now uses title plus extracted skill signals and adds Singapore-market categories such as Built Environment, Food & Hospitality, Beauty & Wellness, Customer Service, and Public Sector.
- Market Insights sector filters now use stored precomputed sectors only; unclassified rows are labelled explicitly instead of being re-guessed during requests.
- Market Insights labels inferred sectors and unique ATS terms more explicitly to avoid implying ground-truth industry data.
- Salary insights now show advertised floor plus midpoint where the posting exposes a range, so low-looking medians are clearly labelled.
- Seniority mix is sorted by market share instead of fixed career-stage order.
- Smart Match no longer guesses resume skills from capitalised words when the trusted skill corpus finds no match.
- Resume parsing keeps wrapped bullet continuations attached to the original bullet and avoids turning short line-wrap fragments into fake job headings.

### Fixed
- Certification lines such as `Full Stack Development with AI (NUS x Emeritus, 2025)` now render as full credential text instead of being split into fake title/date pairs.
- All eight resume DOCX templates are covered by export tests.
- Filtered Market Insights no longer caches empty over-indexing output before the market baseline cache is ready.
- Power Match no longer pads candidate pools with newest jobs when too few skill-filtered roles are found.
- The legacy jobs recommendation endpoint now uses the trusted skill extractor instead of capitalised-word matching.
- Bullet rewrite now withholds suggestions when validation gates cannot produce a safe rewrite instead of showing raw AI output.

## 2026-04-24

### Added
- Resume uploads now return parse-quality diagnostics and show a non-blocking warning when extracted text looks incomplete, flattened, or space-damaged.
- Admin metrics now include privacy-safe resume parse-quality aggregates without storing raw resume content in usage logs.
- Smart Match now includes a "Close the Gap" panel that recommends official MySkillsFuture courses for repeated missing skills.
- SkillsFuture course recommendations rank by relevance, course rating, career impact, and response count.
- Market Insights now surfaces ATS hard skills, over-indexed skills, hiring freshness, seniority mix, and salary coverage.
- Smart Match includes a short explanation of resume source, fit signals, thresholds, and human-review limits.
- Search visibility assets were added for crawlers and AI assistants: `robots.txt`, `sitemap.xml`, `llms.txt`, canonical metadata, Open Graph, Twitter Card, and JSON-LD.
- GitHub Actions now runs backend quality, frontend build, and Gitleaks secret scanning on `main` and pull requests.

### Changed
- Power Match snapshots are persisted by resume hash and job corpus marker so repeat visits return quickly.
- Job filters and market insights use precomputed fields to reduce repeated parsing and database work.
- Market skill names are normalized so aliases like `Aws`, `Excel`, and `Microsoft Excel` do not fragment the analytics.
- Smart Match course lookup caches the official MySkillsFuture XLSX and degrades gracefully if data.gov.sg is rate-limited.

### Fixed
- Power Match no longer performs long synchronous embedding work on the HTTP path, reducing Cloudflare 524 timeout risk.
- API error handling now avoids showing raw Cloudflare HTML in the app.
- Login password fields include the correct autocomplete hint.

### Security
- CI secret scanning is enabled with Gitleaks.
- Pre-commit hooks cover private-key detection, large-file checks, Ruff critical checks, and backend compile checks.
