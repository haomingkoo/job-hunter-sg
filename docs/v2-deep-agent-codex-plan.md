# Resume Deep Agent (v2) — Implementation Plan (for Codex)

> Self-contained build plan. Execute with **TDD discipline** (see §5). Everything you
> need is here; you should not need the originating chat.

## 0. Executor rules (read first)

- **Branch:** `feat/resume-deep-agent` (already created, off the config-model-tiering foundation). Commit in small TDD increments. Open a PR when done. **Do NOT merge** (Railway auto-deploys from `main`; merge is the user's call).
- **Additive only.** Do NOT change the existing tailoring pipeline, its endpoints, or the classic ResumeTab editor. v2 is a parallel feature behind a toggle. If a test for existing behavior breaks, you broke something — stop and fix.
- **TDD, vertical slices.** One test → minimal impl → next test. Never write all tests first. Mock the LLM/network in tests (see `~/.claude/skills/tdd/`). Tests assert behavior through public interfaces, not internals.
- **No magic numbers.** Every cap/threshold/token-budget lives in `backend/config.py` (named constant, env-overridable). This is a hard requirement from the project's magic-number audit.
- **No fabrication.** Every AI-proposed resume edit runs through `validation_gates` before it can be accepted. The agent must never invent metrics, employers, dates, or skills.
- **Reuse the model tiers** from `backend/config.py`: `SEALION_FAST_MODEL`, `SEALION_SMART_MODEL`, `SMART_MIN_MAX_TOKENS` (already exist).
- **Parse SMART output defensively** — it's a reasoning model: strip `<think>…</think>` / ```` ```json ```` fences / slice to outer braces before JSON-parsing (see §9; cf. existing commit 158d888). **Fairness + anti-fabrication guardrails live in the persona prompts** (see §9), kept in ONE shared place — do not duplicate prompt text.

## 1. What you're building

A chat-first **deep agent** that tailors a user's resume to a **specific target job** (or does general strengthening), using LangChain `deepagents`. The agent plans, calls tools (search the jobs DB, score the resume, etc.), delegates to **persona sub-agents** (recruiter, hiring manager, ATS, skeptic), and proposes **per-bullet edits the user accepts or rejects**. It streams progress to a new **v2 panel inside ResumeTab** (the classic editor stays untouched).

### Locked decisions
| Decision | Choice |
|----------|--------|
| Engine | `deepagents` (Python) + `langgraph`, on SEA-LION via `langchain-openai` `ChatOpenAI(base_url=...)` |
| Orchestrator + ALL tool-calling | `config.SEALION_FAST_MODEL` (v4-32B — the only reliable tool-caller; proven by spike) |
| Persona sub-agents | `config.SEALION_SMART_MODEL` (v4.5-27B) — **single-shot, NO tools**, `max_tokens >= SMART_MIN_MAX_TOKENS` |
| Interaction | Chat-first; main agent + persona sub-agents + a research step |
| Deliverable | A resume tailored to a target job (or general strengthening) |
| Edits | Per-bullet accept/reject diffs (structured, via `resume_structurer`) |
| Job context | Both: user picks a target job from the DB, OR general strengthening |
| Analysis/rewrites | The agent does its **own** analysis/rewrites (not the v1 pipeline). Still reuses data/grounding helpers — see §7 Q1. |
| Streaming | SSE |
| Thread state | In-memory (`langgraph` `MemorySaver`) for v2 |
| Frontend | "Classic / Agent v2" toggle inside ResumeTab; classic path unchanged |

### Hard facts from the model eval (do not relearn these)
- SEA-LION **FAST (v4-32B) tool-calls reliably**; the multi-step tool loop works (proven against the live API).
- **SMART (v4.5-27B) must never be given tools** — it won't emit tool calls within budget. Use it only for single-shot persona critiques, with `max_tokens >= 3000`, or it returns **empty**.
- `Llama-v3.5-70B-R` is retired (no tool support; leaks chain-of-thought).
- Rate limit: `config.SEALION_REQ_PER_MIN` per key × N keys. A full turn (plan + personas + research) can be 15–30 calls → cap and serialize (see §4 T10).

## 2. Architecture

```
backend/resume_agent/            # new package (keep files focused/small)
  __init__.py
  models.py        # ChatOpenAI factory bound to SEA-LION FAST / SMART + key pool
  tools.py         # thin, config-capped tools wrapping existing services
  personas.py      # deepagents subagent definitions (SMART)
  agent.py         # create_deep_agent(...) factory + run/stream helpers + state
backend/main.py                  # + 2 new endpoints (additive)
frontend/src/components/ResumeTab.jsx   # + v2 toggle + chat/diff panel (additive)
backend/config.py                # + new AGENT_* constants
```

- **Model factory** (`models.py`): returns `ChatOpenAI(base_url=ai_service.SEALION_BASE_URL, api_key=<key from ai_service pool>, model=config.SEALION_FAST_MODEL)` for the orchestrator, and a SMART instance (`temperature` low, `max_tokens=config.SMART_MIN_MAX_TOKENS`) for personas.
- **Tools** (`tools.py`), each a `@tool`, each capped by a `config.AGENT_*` constant:
  - `search_jobs(query, n)` → `embedding_service` semantic search over `scraped_jobs`.
  - `get_job(job_id)` → `parsed_jd` + `jd_summary`.
  - `score_resume(resume_text)` → `resume_scorer`.
  - `extract_skills(text)` → `skill_extractor`.
  - `propose_edit(bullet_id, rewrite)` → runs `validation_gates`; rejects fabricated metrics/skills; returns accepted/rejected + reason.
- **Personas** (`personas.py`): deepagents subagents on SMART — `recruiter`, `hiring_manager`, `ats`, `skeptic`, `market_researcher` (the last may call `search_jobs`/`market_insights` — but a subagent with tools needs FAST; if a persona needs tools, run it on FAST, not SMART).
- **Agent** (`agent.py`): `create_deep_agent(model=FAST, tools=[...], subagents=[...], system_prompt=...)`. Working resume + research notes held in the deepagents virtual FS / langgraph state, keyed by thread id. Per-bullet structure via `resume_structurer`.
- **Endpoints** (additive, in `main.py`):
  - `POST /api/resume/agent/chat` — `{session_id?, message, resume_text?, job_id?}` → **SSE** stream of tokens + tool/subagent events.
  - `GET /api/resume/agent/{session_id}/state` — current draft, plan/todos, persona findings, pending diffs.
  - Saving the final resume reuses the existing `POST /api/resume/versions`.
- **Config additions** (`config.py`): `AGENT_MAX_TOOL_ITERATIONS`, `AGENT_PERSONA_COUNT`, `AGENT_SMART_MAX_TOKENS` (= `SMART_MIN_MAX_TOKENS`), `AGENT_SEARCH_JOBS_LIMIT`, `AGENT_MAX_CONCURRENT_RUNS_PER_USER`, `AGENT_CHAT_HISTORY_LIMIT` — all `os.getenv`-overridable.

## 3. Dependencies
Add to `backend/requirements.txt` (pin versions): `deepagents`, `langgraph`, `langchain`, `langchain-openai`. ⚠️ Railway memory: this stack adds weight next to `sentence-transformers` — verify the container still boots within the memory tier; lazy-import the agent module so it doesn't load unless used.

## 4. Task list (ordered — each is one TDD vertical slice)

- **T1 — Model factory.** `resume_agent/models.py`: FAST + SMART `ChatOpenAI` instances bound to SEA-LION, using the existing key pool. (Smallest tracer bullet.)
- **T2 — First tool.** `search_jobs` in `tools.py`, capped at `config.AGENT_SEARCH_JOBS_LIMIT`, wrapping `embedding_service`.
- **T3 — Minimal agent.** `create_deep_agent(model=FAST, tools=[search_jobs])`; one turn; confirm it can call the tool and return a grounded reply.
- **T4 — Remaining tools.** `get_job`, `score_resume`, `extract_skills`, `propose_edit` (the last runs `validation_gates`).
- **T5 — Persona sub-agents.** Define personas; main agent delegates; each persona returns structured findings.
- **T6 — Per-bullet diff flow.** Map agent rewrites onto `resume_structurer` bullet IDs; produce accept/reject diffs; rejected fabrications never surface.
- **T7 — Chat endpoint (SSE).** `POST /api/resume/agent/chat`; in-memory thread via `MemorySaver`; streams tokens + tool/subagent events.
- **T8 — State endpoint.** `GET /api/resume/agent/{sid}/state`.
- **T9 — Frontend v2 toggle.** Classic/Agent toggle in ResumeTab; chat panel + plan/findings side panel + per-bullet accept/reject UI. Classic path untouched.
- **T10 — Guardrails.** `AGENT_MAX_TOOL_ITERATIONS` hard cap; one active run/user; serialize sub-agents; rate-limit throttle reusing `ai_service` limiter.

## 5. TDD test list (write in this order; one at a time; mock the LLM/network)

**Backend (`backend/tests/`, pytest; mock SEA-LION — never hit the network):**
1. `test_model_factory_builds_fast_and_smart_models` — FAST model id == `config.SEALION_FAST_MODEL`; SMART == `config.SEALION_SMART_MODEL` and `max_tokens >= SMART_MIN_MAX_TOKENS`.
2. `test_search_jobs_returns_results_capped_at_config_limit` — returns ≤ `AGENT_SEARCH_JOBS_LIMIT`; shape is stable.
3. `test_agent_calls_search_jobs_for_role_query` — with a stubbed FAST model that emits a `search_jobs` tool_call, the agent invokes the tool and feeds the result back.
4. `test_propose_edit_accepts_clean_rewrite` — a rewrite with no new facts passes the gates.
5. `test_propose_edit_rejects_fabricated_metric` — a rewrite introducing an unsupported number is rejected with a reason (integration with `validation_gates`).
6. `test_persona_subagent_uses_smart_model_and_no_tools` — persona config binds SMART, tool list empty.
7. `test_per_bullet_diff_preserves_bullet_ids` — diffs map 1:1 to `resume_structurer` bullet IDs; no orphan/dup IDs.
8. `test_general_mode_runs_without_target_job` — `job_id` omitted → still produces critique + edits (no crash, no fabricated job).
9. `test_tool_iteration_cap_stops_runaway_loop` — a model stub that always tool-calls halts at `AGENT_MAX_TOOL_ITERATIONS`.
10. `test_chat_endpoint_streams_token_and_tool_events` — SSE yields ordered events for a stubbed run.
11. `test_state_endpoint_returns_draft_todos_and_pending_diffs`.
12. `test_smart_persona_output_strips_think_tags` — a SMART response wrapped in `<think>…</think>` + ```` ```json ```` parses to clean structured output (reasoning-model defensive parse).
13. `test_fairness_counterfactual_name_school_swap` — swapping candidate name / school / location in the input leaves the proposed bullet edits unchanged (prompt-level fairness regression guard; a real eval the prior art lacks).
14. `test_existing_pipeline_endpoints_unchanged` — smoke that `/api/resume/tailor` + classic paths still import/respond (regression guard).

**Frontend (`frontend/src/.../__tests__`, vitest):**
15. `v2 toggle renders and does not affect the classic editor`.
16. `accepting a bullet diff applies it; rejecting discards it` (state-level).

Each test: integration-style, public interface, survives refactors. Use the project's existing test patterns. Mock external calls per `~/.claude/skills/tdd/mocking.md`.

## 6. Done criteria
- All new tests green; existing backend collection unchanged (234 tests collect, no new import errors); frontend vitest still ≥103 passing.
- Classic ResumeTab + tailoring pipeline visibly unchanged (no regressions).
- Manual smoke: open Agent v2, pick a DB job, the agent researches + critiques + proposes per-bullet diffs; accept some; save a resume version.
- Zero new magic numbers (all caps in `config.py`); zero fabricated facts (gates on every edit).

## 7. Open questions — confirm with the user before building if blocking
1. **"Fully independent" scope.** The agent owns its analysis/rewrites (not the v1 pipeline). Confirm it MAY still reuse data/grounding helpers — `embedding_service`, `resume_structurer` (parsing + bullet IDs), `validation_gates` (anti-fabrication) — rather than reimplementing parsing/validation from scratch. Recommendation: reuse those (DRY + safety); only the LLM analysis/rewrite logic is independent.
2. **Persona set** — recruiter / hiring_manager / ats / skeptic / market_researcher final, or adjust?
3. **Web research** — out of scope for v2 (internal jobs DB + market insights only)? Recommended: yes, out; add behind a flag later.

## 8. Risks (pre-validated)
- **Tool-calling on SEA-LION:** ✅ proven. FAST works; SMART must not get tools.
- **SMART empty-output trap:** always set `max_tokens >= SMART_MIN_MAX_TOKENS` for SMART calls.
- **Rate/cost:** cap personas, serialize sub-agents, one run/user, reuse the `ai_service` throttle.
- **Railway memory:** lazy-import the agent; verify boot.

## 9. Prior art — `interviewstreet/hiring-agent` (HackerRank), studied
It's a deterministic resume→**score** *screening* pipeline (employer side), NOT a
deepagents/tool-calling agent — no agent loop, no personas, no JD-matching, no
eval harness. So its *orchestration* is a floor, not a model. Steal these patterns:

**ADOPT**
- **Defensive JSON parsing for SMART output**: strip ```` ```json ```` fences, strip
  `<think>…</think>` / reasoning preamble, slice to outer braces. SMART (v4.5) is a
  reasoning model — required (cf. existing commit 158d888). Ref: their
  `llm_utils.extract_json_from_response`.
- **Per-section extraction** (narrow prompt + per-section Pydantic schema) over one
  mega-prompt — higher fidelity on mid-size models. Reuse `resume_structurer`.
- **Triple-enforce any numeric the agent emits**: prompt anchor → Pydantic validator
  → Python clamp. Models drift; never trust the LLM alone.
- **Compute facts in code; use the LLM only for fuzzy judgment; always a deterministic
  fallback** — apply to the jobs-DB research step (filter/rank in code, personas
  interpret). Ref: their GitHub top-7 selection + "fall back to first 7".
- **Fairness guardrail in persona prompts**: explicit deny-list (don't score/penalize
  on name, gender, demographics, school/university, GPA, location) + allow-list
  (skills, project complexity, impact). Important for an AISG-adjacent product.
- **Anti-fabrication in the prompt too** (not only post-hoc gates): "keep only what's
  in the source; never invent URLs/metrics/skills," with DO/DON'T examples.
- **Rubric anchored to concrete signals**, not vague adjectives — makes per-bullet
  edit rationales credible.

**AVOID**
- Their single-shot, persona-less, JD-blind scoring + zero eval — those gaps are
  exactly our value. Keep multi-persona + JD-aware tailoring + the §5 test list.
- Don't duplicate guardrail prompt text across files (theirs drifts) — keep the
  fairness/anti-fabrication block in ONE shared partial/constant (extend the
  `shared/resume-classification.json` habit).

deepagents API: `create_deep_agent(model=, tools=, subagents=, system_prompt=)` (verified current).
Clone available at `/tmp/hiring-agent-study`.
