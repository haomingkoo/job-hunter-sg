# Resume Agent MCP

This exposes Job Hunter SG's deterministic resume/job tools to MCP clients such
as Claude Desktop. The LLM acts as the agent brain; this repo supplies grounded
tools only.

## Install

```bash
cd /Users/koohaoming/dev/job-hunter-sg/backend
./.venv/bin/python -m pip install -r requirements.txt
```

## Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "job-hunter-sg": {
      "command": "/Users/koohaoming/dev/job-hunter-sg/backend/.venv/bin/python",
      "args": [
        "/Users/koohaoming/dev/job-hunter-sg/backend/mcp_server.py"
      ]
    }
  }
}
```

Restart Claude Desktop after editing the file.

## Tools

- `parse_resume`: sections, stats, and stable bullet IDs.
- `score_resume`: resume score, optionally blended with a DB job.
- `extract_skills`: ATS-style skill phrases.
- `compare_candidate_profile`: compare resume and LinkedIn/profile text for consistency gaps.
- `search_jobs`: semantic search over the internal jobs DB.
- `get_job`: fetch one DB job.
- `validate_bullet_edit`: run anti-fabrication gates for one rewrite.
- `propose_resume_diff`: validate a rewrite against a resume bullet ID.

## Try

Ask Claude:

```text
Use the job-hunter-sg MCP tools. Parse this resume, score it, search for
relevant Singapore data roles, then propose safe per-bullet diffs. Before you
show a rewrite, call validate_bullet_edit or propose_resume_diff.
```

For LinkedIn/profile review, paste the profile text and ask Claude to call
`compare_candidate_profile`. Profile-only details are questions or consistency
gaps, not resume claims to add.

The MCP server does not call SEA-LION or any other LLM. Claude/Gemini/Groq does
the reasoning; this repo owns parsing, ATS scoring, job search, and validation.
