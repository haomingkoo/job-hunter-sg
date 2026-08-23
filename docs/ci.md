# CI and Local Gates

Run the dependency-free documentation check first:

```bash
python scripts/check_docs.py
```

## GitHub Actions

- Documentation: reject broken local Markdown links or an incomplete authoritative handbook index.
- Backend: install dependencies, run `pip-audit`, compile, run Ruff critical checks, run the scoped ty baseline, run both backend test roots, and build `Dockerfile.alerts`. A PostgreSQL service also exercises schema repair and the shared crawl lease on the production dialect.
- Frontend: install from the lockfile, run Vitest, run `npm audit --audit-level=high`, build, and then build the actual production `Dockerfile` without pushing it.
- Secrets: Gitleaks scans pushed history in CI.

## Pre-commit

Install once:

```bash
.venv/bin/pre-commit install
```

Run manually:

```bash
.venv/bin/pre-commit run --all-files
```

The hook is intentionally fast: file hygiene, no commits to `main`, Ruff critical checks, staged secret detection, backend compile, and the scoped ty baseline. Tests stay in CI.

Production enforcement, exact-commit acceptance, scheduled-service receipts,
and rollback are documented in [Production release](production-release.md).
