# Resume Agent MCP

This exposes Job Hunter SG's deterministic resume/job tools to MCP clients. The
LLM acts as the agent brain; this repo supplies grounded tools only.

## Hosted Railway MCP

The production FastAPI app mounts the Streamable HTTP MCP endpoint at:

```text
https://job.kooexperience.com/mcp
```

On Railway it uses the same production `DATABASE_URL` as the website API, so job
tools read from the Railway jobs DB. The endpoint is disabled unless
`MCP_API_KEY` is configured. Clients must send `Authorization: Bearer <key>`;
requests are rate-limited before any MCP work runs.

The hosted tools are read-only, but the endpoint is not public. Keep private
resume parsing, scoring, and rewrite validation on the local stdio MCP.

The website and account-based RAG flow do not require MCP. Publish the hosted
endpoint to a directory only if there is a real external client and that
directory can supply the bearer key without exposing it.

## Install

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

## Client setup

Add an stdio server entry to your MCP client's configuration:

```json
{
  "mcpServers": {
    "job-hunter-sg": {
      "command": "<repo>/.venv/bin/python",
      "args": [
        "<repo>/backend/mcp_server.py"
      ]
    }
  }
}
```

Restart the client after editing its configuration.

By default, the MCP and local API both use `backend/jobhunter.db`, independent
of the directory they are launched from. Set `DATABASE_URL` explicitly only to
use another database.

## Tools

Hosted `/mcp` tools:

- `jobhunter.source_stats`: public job counts and freshness by source.
- `jobhunter.latest_jobs`: fetch the latest public jobs.
- `jobhunter.latest_careersgov_jobs`: fetch latest public Careers@Gov jobs.
- `jobhunter.latest_mycareersfuture_jobs`: fetch latest public MyCareersFuture jobs.
- `jobhunter.search_jobs`: semantic search over public jobs.
- `jobhunter.get_job`: fetch one public job.
- `jobhunter.ats_precompute_status`: check parsed JD, term preview, and embedding readiness.
- `jobhunter.recommend_skillsfuture_courses`: recommend official MySkillsFuture courses for skill gaps.

Local stdio-only tools:

- `parse_resume`: sections, stats, and stable bullet IDs.
- `score_resume`: resume score, optionally blended with a DB job.
- `extract_skills`: ATS-style skill phrases.
- `compare_candidate_profile`: compare resume and LinkedIn/profile text for consistency gaps.
- `jobhunter.match_resume_to_jobs`: rank public jobs against pasted resume text without storing it.
- `search_jobs`: semantic search over the internal jobs DB.
- `get_job`: fetch one DB job.
- `validate_bullet_edit`: run anti-fabrication gates for one rewrite.
- `propose_resume_diff`: validate a rewrite against a resume bullet ID.

## Job Ingestion

The website and MCP both read `scraped_jobs`. New jobs should enter through the
protected seed path, not through MCP:

- Manual refresh: call `POST /api/admin/seed` with `Authorization: Bearer $ADMIN_API_KEY`.
- Full crawl cron: deploy `railway.seed.toml`, which runs `python seed_jobs.py --full`.
- Extra API sources: set `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, and/or `JOOBLE_API_KEY`,
  then run `python seed_jobs.py --sources adzuna,jooble --limit 50`.
- The current source status and authorization requirements are maintained in
  the [job source matrix](sources.md). NodeFlair, Indeed SG, LinkedIn, and
  JobStreet are not implemented sources on this branch.

## Try

Ask the MCP client:

```text
Use the job-hunter-sg MCP tools. Parse this resume, score it, search for
relevant Singapore data roles, then propose safe per-bullet diffs. Before you
show a rewrite, call validate_bullet_edit or propose_resume_diff.
```

For a public jobs-only first pass, ask:

```text
Use the jobhunter.latest_jobs MCP tool and show me the newest Singapore roles.
```

For ATS matching against public jobs, paste a resume and ask:

```text
Use jobhunter.ats_precompute_status first. Then call jobhunter.match_resume_to_jobs
with my pasted resume, show the strongest matches, missing ATS terms, and suggest
SkillsFuture courses for the recurring gaps.
```

For LinkedIn/profile review, paste the profile text and ask the client to call
`compare_candidate_profile`. Profile-only details are questions or consistency
gaps, not resume claims to add.

`jobhunter.match_resume_to_jobs` does not read stored resumes or private
applications. It uses the pasted text for that tool call, public job rows,
precomputed `parsed_jd` / `job_terms_preview` where available, and embedding
similarity for candidate selection.

The MCP server does not call SEA-LION or another model. The client-side model does
the reasoning; this repo owns parsing, ATS scoring, job search, and validation.
