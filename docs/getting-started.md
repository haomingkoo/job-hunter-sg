# Fresh-clone Setup

Use Python 3.12 and Node.js 24 to match CI. Node.js 20 is sufficient for the
production Docker build. The commands below assume a Unix-like shell and start
from the repository root.

## 1. Install dependencies

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  -r backend/requirements.txt \
  -r backend/requirements-test.txt \
  pip-audit pytest pre-commit ruff==0.15.20 ty==0.0.56

cd frontend
npm ci --legacy-peer-deps
cd ..
```

The Python install includes the local embedding model stack and can be large.
Linux hosts also need the Pango/Cairo packages listed in the root
[Dockerfile](../Dockerfile) for PDF rendering.

## 2. Start the backend

No external database is required for local development. If `DATABASE_URL` is
unset, SQLAlchemy creates `backend/jobhunter.db` and applies the repository's
lightweight additive migrations at startup.

```bash
.venv/bin/python backend/main.py
```

Confirm the API and database path are usable:

```bash
curl --fail http://localhost:8000/api/health
```

The expected response includes `"status":"ok"` and `"db":"connected"`.

For authenticated local flows, export local-only values before starting the
backend:

```bash
export JWT_SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_EMAIL=admin@example.test
export ADMIN_PASSWORD=local-only-change-me
```

`.env.example` is a reference, not an automatically loaded dotenv file. Export
values in the shell or configure them in the process manager. Never commit the
generated secret or a real account password.

## 3. Start the frontend

In a second shell:

```bash
cd frontend
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to
`http://localhost:8000`. Set `VITE_API_URL` only when the backend is elsewhere.

Public job browsing and non-AI screens work without third-party credentials.
These capabilities need additional services:

| Capability | Requirement |
|---|---|
| Production persistence | PostgreSQL through `DATABASE_URL` |
| Password signup/reset email | SMTP variables in `.env.example` |
| SEA-LION generation | One or more `sealion_api*` keys |
| Seed/enrichment maintenance endpoints | Separate `ADMIN_API_KEY` bearer secret |
| Adzuna or Jooble search | The source-specific API key |
| SkillsFuture enrichment | SSG client credentials |
| External MCP endpoint | `MCP_API_KEY` |
| Cloudflare Access mode | Access team domain and audience |

See the [source matrix](sources.md) before enabling job sources.

## 4. Run checks

The shortest repository-wide sanity pass is:

```bash
.venv/bin/python scripts/check_docs.py
.venv/bin/python -m compileall -q backend
.venv/bin/ruff check backend tests
.venv/bin/ty check
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests tests -q

cd frontend
npm test -- --run
npm run build
npm audit --audit-level=high
```

Run `.venv/bin/pip-audit -r backend/requirements.txt` when dependencies change.
The authoritative CI sequence is documented in [CI and local gates](ci.md).

## Common setup failures

- `ModuleNotFoundError` from backend imports: run the command from the repository
  root exactly as shown, including `PYTHONPATH=backend` for tests.
- Signup returns an email-service error: configure SMTP or use the local admin
  bootstrap; signup intentionally fails closed without delivery.
- The frontend shows API failures: verify port 8000 and the health endpoint
  before changing CORS.
- PDF rendering fails: install the native libraries from the Dockerfile. DOCX
  export does not prove the PDF path is healthy.
- A model downloads on first use: the Docker image preloads MiniLM, but a fresh
  local environment may fetch it when semantic matching first runs.
