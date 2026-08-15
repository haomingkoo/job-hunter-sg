"""Central tunable config: SEA-LION model tiers + operational knobs.

Named constants for product values; ``os.getenv(...)`` for operational knobs that
should be tunable in prod without a redeploy.

Model-tier rationale: FAST stays on the cheaper v4 instruct model for classic
interactive calls. AGENT/SMART use v4.5 Qwen, the current SEA-LION agentic line.
"""

from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None


def _positive_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {value}")
    return value


def _positive_float_env(name: str, default: float) -> float:
    value = _float_env(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {value}")
    return value


def _nonnegative_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value < 0:
        raise ValueError(f"{name} must be zero or greater, got {value}")
    return value


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


# FAST: interactive rewrites, JD summaries, default classic pipeline tier.
SEALION_FAST_MODEL: str = os.getenv(
    "SEALION_FAST_MODEL",
    "aisingapore/Qwen-SEA-LION-v4-32B-IT",  # pragma: allowlist secret
)
# Classic tailoring pipeline model. Defaults to FAST because v4.5 Qwen currently
# leaks reasoning text into strict JSON/prose prompts on this path.
SEALION_PIPELINE_MODEL: str = os.getenv("SEALION_PIPELINE_MODEL", SEALION_FAST_MODEL)
# AGENT: Resume Agent v2 orchestration and tool-calling loop.
SEALION_AGENT_MODEL: str = os.getenv("SEALION_AGENT_MODEL", "aisingapore/Qwen-SEA-LION-v4.5-27B-IT")
# The conversational tool loop runs on the AGENT tier, so the recruitment-team
# path stays on one model. It fell back to FAST on 2026-08-02, when v4.5-27B was
# unreachable; the endpoint serves it again. The 2026-06-26 eval rated v4-32B
# higher for tool loops, so COORDINATOR_MODEL exists to move this one back
# without moving the assessment path with it.
COORDINATOR_MODEL: str = os.getenv("COORDINATOR_MODEL", "").strip() or SEALION_AGENT_MODEL
# A reasoning tier thinks before it writes; with no floor the reply gets the rest.
RECRUITMENT_CONVERSATION_MAX_TOKENS: int = _int_env("RECRUITMENT_CONVERSATION_MAX_TOKENS", 8000)
RECRUITMENT_EDIT_EVIDENCE_MAX_TOKENS: int = _positive_int_env(
    "RECRUITMENT_EDIT_EVIDENCE_MAX_TOKENS",
    2000,
)
# SMART: deep-agent persona reviews (single-shot, no tools, latency-tolerant).
SEALION_SMART_MODEL: str = os.getenv("SEALION_SMART_MODEL", "aisingapore/Qwen-SEA-LION-v4.5-27B-IT")
# Models that must run in instruct/non-thinking mode for product-facing text and
# JSON calls. Qwen v4.5 otherwise returns reasoning_content instead of content.
SEALION_DISABLE_THINKING_MODELS: tuple[str, ...] = _csv_env(
    "SEALION_DISABLE_THINKING_MODELS",
    SEALION_AGENT_MODEL,
)
# SMART is a reasoning model — under a tight budget it spends all tokens "thinking"
# and returns empty. Floor its max_tokens at call sites that use it.
SMART_MIN_MAX_TOKENS: int = _int_env("SMART_MIN_MAX_TOKENS", 6000)

AGENT_MAX_TOOL_ITERATIONS: int = _positive_int_env("AGENT_MAX_TOOL_ITERATIONS", 20)
OPEN_AGENT_MAX_PROPOSED_EDITS: int = _positive_int_env("OPEN_AGENT_MAX_PROPOSED_EDITS", 8)
# Each ask_candidate call pauses the whole graph, and the guardrails only reject a
# materially identical repeat, so without a cap a run can keep asking and never
# reach synthesis, the judge, or a proposed edit.
OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS: int = _positive_int_env(
    "OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS",
    2,
)
# Durable LangGraph checkpoint store, so an ask_candidate pause survives a
# process restart and can be resumed from any worker, not just the one that
# hit the pause.
OPEN_AGENT_CHECKPOINT_DB_PATH: str = os.getenv("OPEN_AGENT_CHECKPOINT_DB_PATH", "open_agent_checkpoints.db")
# Separate from AGENT_MAX_TOOL_ITERATIONS so tuning a chat turn cannot starve an
# assessment. A LangGraph recursion_limit counts super-steps, not tool calls:
# measured at 5 steps plus 4 per call, so 45 buys ten tool calls.
COORDINATOR_MAX_TOOL_ITERATIONS: int = _positive_int_env("COORDINATOR_MAX_TOOL_ITERATIONS", 45)
AGENT_PERSONA_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "AGENT_PERSONA_VALIDATION_ATTEMPTS",
    2,
)
AGENT_JUDGE_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "AGENT_JUDGE_VALIDATION_ATTEMPTS",
    2,
)
AGENT_SMART_MAX_TOKENS: int = max(
    SMART_MIN_MAX_TOKENS,
    _int_env("AGENT_SMART_MAX_TOKENS", SMART_MIN_MAX_TOKENS),
)
AGENT_SEARCH_JOBS_LIMIT: int = _positive_int_env("AGENT_SEARCH_JOBS_LIMIT", 7)
AGENT_SEARCH_CANDIDATE_MULTIPLIER: int = _positive_int_env(
    "AGENT_SEARCH_CANDIDATE_MULTIPLIER",
    10,
)
RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS: int = _positive_int_env(
    "RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS",
    300,
)
RECRUITMENT_MODEL_TRANSPORT_RETRIES: int = _nonnegative_int_env(
    "RECRUITMENT_MODEL_TRANSPORT_RETRIES",
    2,
)
RECRUITMENT_WORKFLOW_RESUME_LIMIT: int = _positive_int_env(
    "RECRUITMENT_WORKFLOW_RESUME_LIMIT",
    1,
)
_RECRUITMENT_MAX_MODEL_INVOKE_SECONDS = (
    RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS * (RECRUITMENT_MODEL_TRANSPORT_RETRIES + 1)
)
RECRUITMENT_RUN_LEASE_SECONDS: int = _positive_int_env(
    "RECRUITMENT_RUN_LEASE_SECONDS",
    _RECRUITMENT_MAX_MODEL_INVOKE_SECONDS + 60,
)
if RECRUITMENT_RUN_LEASE_SECONDS <= _RECRUITMENT_MAX_MODEL_INVOKE_SECONDS:
    raise ValueError(
        "RECRUITMENT_RUN_LEASE_SECONDS must exceed the configured model timeout and retries "
        f"({_RECRUITMENT_MAX_MODEL_INVOKE_SECONDS}s), got {RECRUITMENT_RUN_LEASE_SECONDS}"
    )
RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS",
    2,
)
RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS: int = _int_env(
    "RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS",
    1,
)
if RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS not in {0, 1}:
    raise ValueError(
        "RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS must be zero or one, "
        f"got {RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS}"
    )
CANDIDATE_PROFILE_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "CANDIDATE_PROFILE_VALIDATION_ATTEMPTS",
    2,
)
CANDIDATE_PROFILE_REVIEW_ATTEMPTS: int = _positive_int_env(
    "CANDIDATE_PROFILE_REVIEW_ATTEMPTS",
    2,
)
RECRUITMENT_CONVERSATION_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "RECRUITMENT_CONVERSATION_VALIDATION_ATTEMPTS",
    2,
)
ROLE_DEFINITION_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "ROLE_DEFINITION_VALIDATION_ATTEMPTS",
    2,
)
ROLE_EVIDENCE_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "ROLE_EVIDENCE_VALIDATION_ATTEMPTS",
    12,
)
RECRUITMENT_PERSONA_PACK_VERSION: str = os.getenv(
    "RECRUITMENT_PERSONA_PACK_VERSION",
    "v1",
)
AGENT_MAX_CONCURRENT_RUNS_PER_USER: int = _positive_int_env("AGENT_MAX_CONCURRENT_RUNS_PER_USER", 1)
AGENT_MAX_ACTIVE_RUNS: int = _positive_int_env("AGENT_MAX_ACTIVE_RUNS", 4)
RECRUITMENT_STREAM_HEARTBEAT_SECONDS: float = _positive_float_env(
    "RECRUITMENT_STREAM_HEARTBEAT_SECONDS",
    15.0,
)
RECRUITMENT_MAX_CONCURRENT_SPECIALISTS: int = _positive_int_env(
    "RECRUITMENT_MAX_CONCURRENT_SPECIALISTS",
    AGENT_MAX_ACTIVE_RUNS,
)
AGENT_CHAT_HISTORY_LIMIT: int = _positive_int_env("AGENT_CHAT_HISTORY_LIMIT", 20)
AGENT_SESSION_TTL_SECONDS: int = _positive_int_env("AGENT_SESSION_TTL_SECONDS", 3600)
AGENT_MAX_SESSIONS: int = _positive_int_env("AGENT_MAX_SESSIONS", 200)
AGENT_MAX_DRAFT_CHARS: int = _positive_int_env("AGENT_MAX_DRAFT_CHARS", 50000)
AGENT_MAX_PROFILE_CONTEXT_CHARS: int = _positive_int_env("AGENT_MAX_PROFILE_CONTEXT_CHARS", 12000)
AGENT_MAX_SESSION_ID_CHARS: int = _positive_int_env("AGENT_MAX_SESSION_ID_CHARS", 200)
AGENT_MAX_MESSAGE_CHARS: int = _positive_int_env("AGENT_MAX_MESSAGE_CHARS", 10000)
AGENT_MAX_JOB_CONTEXT_CHARS: int = _positive_int_env("AGENT_MAX_JOB_CONTEXT_CHARS", 20000)
AGENT_MAX_SCORE_CONTEXT_CHARS: int = _positive_int_env("AGENT_MAX_SCORE_CONTEXT_CHARS", 10000)
AGENT_E2E_REQUEST_TIMEOUT_SECONDS: int = _positive_int_env("AGENT_E2E_REQUEST_TIMEOUT_SECONDS", 30)
AGENT_E2E_POLL_INTERVAL_SECONDS: int = _positive_int_env("AGENT_E2E_POLL_INTERVAL_SECONDS", 2)
AGENT_E2E_TERMINAL_TIMEOUT_SECONDS: int = _positive_int_env("AGENT_E2E_TERMINAL_TIMEOUT_SECONDS", 300)
if AGENT_MAX_ACTIVE_RUNS < AGENT_MAX_CONCURRENT_RUNS_PER_USER:
    raise ValueError("AGENT_MAX_ACTIVE_RUNS must be at least AGENT_MAX_CONCURRENT_RUNS_PER_USER")
WORKSPACE_AGENT_DRAFT_MIN_CHARS: int = _int_env("WORKSPACE_AGENT_DRAFT_MIN_CHARS", 50)
WORKSPACE_AGENT_DRAFT_LABEL_ROLE_CHARS: int = _int_env("WORKSPACE_AGENT_DRAFT_LABEL_ROLE_CHARS", 80)
WORKSPACE_SUBMITTED_ARTIFACT_TOKEN_BYTES: int = _int_env("WORKSPACE_SUBMITTED_ARTIFACT_TOKEN_BYTES", 12)
WORKSPACE_AGENT_REVIEW_DEFAULT_ROLES: tuple[str, ...] = _csv_env(
    "WORKSPACE_AGENT_REVIEW_DEFAULT_ROLES",
    "recruiter,hiring_manager,ats,skeptic,market_researcher",
)
RECRUITMENT_RETENTION_NOTICE: dict[str, str] = {
    "live_data": "Deleted immediately from the live application database.",
    "backups": "Infrastructure backups follow the provider retention policy and may expire later.",
    "telemetry": "Trace and semantic-evaluation deletion is requested at the same time; provider-side removal may not be immediate.",
}

# Conservative per-key request budget; override only to match provider limits.
SEALION_REQ_PER_MIN: int = _int_env("SEALION_REQ_PER_MIN", 9)
SEALION_HTTP_TIMEOUT: int = _int_env("SEALION_HTTP_TIMEOUT", 60)  # seconds

DATABASE_POOL_SIZE: int = _int_env("DATABASE_POOL_SIZE", 5)
DATABASE_MAX_OVERFLOW: int = _int_env("DATABASE_MAX_OVERFLOW", 10)
DATABASE_POOL_TIMEOUT: int = _int_env("DATABASE_POOL_TIMEOUT", 30)
DATABASE_POOL_RECYCLE_SECONDS: int = _int_env("DATABASE_POOL_RECYCLE_SECONDS", 1800)
CAREERSGOV_CACHE_TTL_SECONDS: int = _int_env("CAREERSGOV_CACHE_TTL_SECONDS", 3600)
CAREERSGOV_HTTP_TIMEOUT_SECONDS: int = _int_env("CAREERSGOV_HTTP_TIMEOUT_SECONDS", 30)
ANALYTICS_FILTER_META_TTL_SECONDS: int = _int_env("ANALYTICS_FILTER_META_TTL_SECONDS", 300)
ANALYTICS_CACHE_TTL_SECONDS: int = _int_env("ANALYTICS_CACHE_TTL_SECONDS", 86400)
ANALYTICS_QUERY_CACHE_TTL_SECONDS: int = _int_env("ANALYTICS_QUERY_CACHE_TTL_SECONDS", 3600)
ANALYTICS_QUERY_CACHE_MAX: int = _int_env("ANALYTICS_QUERY_CACHE_MAX", 64)
ANALYTICS_MAX_ROWS: int = _int_env("ANALYTICS_MAX_ROWS", 12000)
# Default job feed is chronological, which rewards whoever reposts most often.
# Cap how many postings one company contributes so a handful of high-volume
# employers cannot own the browse feed.
JOBS_MAX_PER_COMPANY: int = _positive_int_env("JOBS_MAX_PER_COMPANY", 3)
# A company counts as a promotional poster when at least this share of its
# postings carry the tells. Deliberately a ratio, not a count: measured on the
# 16,390-row corpus, a count rule taints RECRUIT EXPRESS, a real agency with 608
# postings of which only 2% are flagged. At 50% every company caught is an
# MLM-style outfit, and 89 of their quiet postings get caught with them.
COMPANY_PROMOTIONAL_MIN_POSTS: int = _positive_int_env("COMPANY_PROMOTIONAL_MIN_POSTS", 5)
COMPANY_PROMOTIONAL_RATIO: float = _float_env("COMPANY_PROMOTIONAL_RATIO", 0.5)
ANALYTICS_YIELD_PER: int = _int_env("ANALYTICS_YIELD_PER", 500)

PIPELINE_STRATEGY_MAX_TOKENS: int = _int_env("PIPELINE_STRATEGY_MAX_TOKENS", 800)
PIPELINE_REWRITE_TOKENS_PER_BULLET: int = _int_env("PIPELINE_REWRITE_TOKENS_PER_BULLET", 150)
PIPELINE_SUMMARY_MAX_TOKENS: int = _int_env("PIPELINE_SUMMARY_MAX_TOKENS", 200)

VALIDATION_REWRITE_MAX_EXPANSION_RATIO: float = _float_env(
    "VALIDATION_REWRITE_MAX_EXPANSION_RATIO",
    2.0,
)
