# Maintainer Handbook Dry-run — 2026-08-15

This is a dated evidence record, not a current runbook. The current entry point
is the [maintainer handbook](README.md).

## Scope

The dry-run followed the new landing path from a branch rebased onto current
`main`, installed the documented dependencies into a newly created temporary
Python 3.12 environment, recreated frontend dependencies with `npm ci`, started
the application with an isolated SQLite database, and ran the validation
commands. The temporary environments, build output, and databases were removed
afterward. No production credential, token, private resume, or production data
was used.

## Corrections discovered during audit

| Previous claim or omission | Correction made |
|---|---|
| README claimed five additional pluggable scrapers. | Current `SOURCE_MAP` has two scheduled and two optional API adapters. |
| Deployment source table listed NodeFlair, Indeed, and JobStreet as scraped. | The source matrix marks them absent or authorization-blocked; only implemented paths are described as such. |
| “Nightly crawl” appeared next to the broader source list. | The handbook states that `--full` schedules only MyCareersFuture and Careers@Gov. |
| Setup used `pip`/`npm install` without a reproducible environment. | Setup now creates `.venv`, uses pinned CI tooling, and runs `npm ci --legacy-peer-deps`. |
| The test command omitted root `tests/`. | The documented command matches CI: `backend/tests tests`. |
| `.env.example` could be read as an auto-loaded file. | Setup explicitly says values must be exported or supplied by the process manager. |
| `ADMIN_API_KEY` was used by operational endpoints but absent from the environment reference. | Added it as a separate maintenance bearer key and distinguished it from account-admin credentials. |
| The current MCP guide still claimed absent HTML source adapters existed and used a repository-local absolute install path. | Linked the source matrix and changed setup to the root `.venv` convention. |
| Railway variable examples used unquoted angle-bracket placeholders that a shell treats as redirection. | Replaced them with copy-safe non-secret placeholder values. |
| Recruitment SQL rows were durable, but the separate LangGraph SQLite checkpoint default was undocumented and may be container-ephemeral. | Architecture and operations now separate durable records from restart-resumable execution and document `OPEN_AGENT_CHECKPOINT_DB_PATH`. |
| Upload parsing was attributed to `resume_structurer.py`, and classic tailoring was described as an accept-before-save flow. | Architecture now traces upload canonicalization through `resume_document.py`, classic tailoring's derived-version auto-save, and the recruitment team's separate explicit-accept flow. |
| The new Documents view and cover-letter persistence were absent from the architecture map. | The map now shows active resume versions plus the latest tracked-job cover letter stored in `TrackedJob.role_metadata`. |
| The freshness query called every non-hidden row visible. | It now mirrors the public posting-age and closing-date predicates and still requires an API acceptance check. |
| The deployment guide used `railway init` and `railway up` as the routine release path. | The release path is GitHub branch, PR, checks, merge, and exact-commit Railway GitHub deployment; direct local deploys are excluded. |
| CI docs omitted dependency audits, ty, frontend tests, and the docs gate. | The current gate list mirrors `.github/workflows/ci.yml`. |
| No operator path distinguished health, cron execution, fresh writes, deployment, and browser acceptance. | The operations runbook records them as separate receipts. |

## Dry-run receipt

| Check | Result |
|---|---|
| Fresh Python install | Passed in a disposable Python 3.12.12 environment using both requirements files and the documented test tools. |
| `python scripts/check_docs.py` | Passed: 27 Markdown files and 45 local links. |
| Documentation checker tests | 2 passed, including reference links, Markdown fragments, undefined references, and ignored hidden output. |
| Backend and checker compile | Passed. |
| Ruff 0.15.20 and scoped ty check | Passed. |
| Full Python suite | 1,021 passed, 4 skipped on Python 3.12.12. |
| `npm ci --legacy-peer-deps` | Passed from the committed lockfile. |
| Frontend suite | 109 passed. |
| Frontend production build | Passed; the existing large-chunk warning remains. |
| Frontend audit | Passed with zero known vulnerabilities. |
| Python audit | The normal requirements audit could not create its internal temporary environment because `ensurepip` aborted on this macOS managed-Python installation. The no-bootstrap audit of all directly pinned requirements found no known vulnerabilities; GitHub CI remains required for the normal transitive audit. |
| Local application smoke | Passed with an isolated SQLite database: direct and Vite-proxied `/api/health` returned database-connected status, and the Vite page returned the Job Hunter SG title. |

Production deployment and production-browser acceptance are deliberately
outside this local dry-run.
