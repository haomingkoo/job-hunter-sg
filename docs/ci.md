# CI and Local Gates

## GitHub Actions

- Backend: install dependencies, compile, run Ruff critical checks, run the scoped ty baseline, and run backend tests.
- Frontend: install dependencies, run Vitest, and build.
- Secrets: Gitleaks scans pushed history in CI.

## Pre-commit

Install once:

```bash
backend/.venv/bin/pre-commit install
```

Run manually:

```bash
backend/.venv/bin/pre-commit run --all-files
```

The hook is intentionally fast: file hygiene, no commits to `main`, Ruff critical checks, staged secret detection, backend compile, and the scoped ty baseline. Tests stay in CI.
