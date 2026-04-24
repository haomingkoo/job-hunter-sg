# Changelog

Notable changes to Job Hunter SG are tracked here.

## 2026-04-24

### Added
- Resume uploads now return parse-quality diagnostics and show a non-blocking warning when extracted text looks incomplete, flattened, or space-damaged.
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
