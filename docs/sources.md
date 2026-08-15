# Job Source Status

This matrix was audited against the current code and deployment configuration
on 2026-08-15 and must be updated whenever a source adapter or Railway schedule
changes. “Implemented” does not mean “enabled in production”; credentials and a
successful deployment receipt still matter.

| Source | Status | Scheduled full crawl | Access path | Activation requirement |
|---|---|---:|---|---|
| MyCareersFuture | Active | Yes | Public JSON endpoint used by `MyCareersFutureScraper` | Monitor upstream compatibility and completed-crawl health. |
| Careers@Gov | Active | Yes | OpenGovSG pre-parsed public JSON used by `CareersGovScraper` | Monitor upstream freshness and completed-crawl health. |
| Adzuna | Optional | No | Official API adapter in `JobAggregator` | Set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`; invoke keyword seed/admin search explicitly. |
| Jooble | Optional | No | Official API adapter in `JobAggregator` | Set `JOOBLE_API_KEY`; invoke keyword seed/admin search explicitly. |
| LinkedIn | Planned; authorization-blocked | No | No adapter on this branch | Written partner/API authorization and approved payload contract; tracked in issue #220. |
| JobStreet / SEEK | Planned; authorization-blocked | No | No adapter on this branch | Written SEEK authorization and approved payload contract; tracked in issue #226. |
| NodeFlair | Disabled / absent | No | No current adapter | New source review and an authorized, reliable integration. |
| Indeed Singapore | Disabled / absent | No | No current adapter | New source review and an authorized, reliable integration. |

The production cron runs `python seed_jobs.py --full`; that path crawls only
MyCareersFuture and Careers@Gov. The non-full CLI and admin `/api/search` path
can call optional adapters. `/api/sources` reports implemented `SOURCE_MAP`
entries, not the scheduled or credential-ready production set.

## Adding or activating a source

A source is not “active” until all of the following are true:

1. Access is authorized and its terms, rate limits, and data-retention rules are
   recorded in the implementing issue.
2. The adapter maps stable source identity, canonical URL, posting/scrape dates,
   title, employer, location, and description into the existing `Job` contract.
3. Fixture-backed tests cover malformed/empty payloads, pagination, duplicate
   identity, partial failure, and source-specific dates without live calls.
4. Incomplete crawls cannot retire healthy cached rows.
5. The source composes with the existing sanitize, precompute, upsert, API
   source filter, analytics, and UI paths.
6. A production receipt proves fresh rows and honest failure reporting.

Do not add browser automation, login-wall workarounds, CAPTCHA handling,
rotating identities, or undocumented endpoints as a shortcut. Keep an adapter
disabled when authorization or reliability evidence is missing.
