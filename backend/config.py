"""Central tunable config: SEA-LION model tiers + operational knobs.

Named constants for product values; ``os.getenv(...)`` for operational knobs that
should be tunable in prod without a redeploy. Foundation from the ponytail
magic-number audit (2026-06-26) — the highest-value cost/throughput levers land
here first; the broader named-constant sweep across scoring rubrics is a follow-up.

Model-tier rationale: FAST stays on the cheaper v4 instruct model for classic
interactive calls. AGENT/SMART use v4.5 Qwen, the current SEA-LION agentic line.
"""

from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    """Read an int from the environment."""
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


def _nonnegative_int_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value < 0:
        raise ValueError(f"{name} must be zero or greater, got {value}")
    return value


def _zero_or_one_env(name: str, default: int) -> int:
    value = _int_env(name, default)
    if value not in {0, 1}:
        raise ValueError(f"{name} must be zero or one, got {value}")
    return value


def _csv_env(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


# ── SEA-LION model tiers ──────────────────────────────────────────────────────
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
SMART_MIN_MAX_TOKENS: int = _int_env("SMART_MIN_MAX_TOKENS", 3000)

# ── Resume deep-agent v2 knobs ───────────────────────────────────────────────
AGENT_MAX_TOOL_ITERATIONS: int = _positive_int_env("AGENT_MAX_TOOL_ITERATIONS", 20)
OPEN_AGENT_MAX_PROPOSED_EDITS: int = _positive_int_env("OPEN_AGENT_MAX_PROPOSED_EDITS", 8)
AGENT_PERSONA_COUNT: int = _int_env("AGENT_PERSONA_COUNT", 5)
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
    0,
)
RECRUITMENT_SPECIALIST_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "RECRUITMENT_SPECIALIST_VALIDATION_ATTEMPTS",
    2,
)
RECRUITMENT_SPECIALIST_MAX_CONCURRENCY: int = _positive_int_env(
    "RECRUITMENT_SPECIALIST_MAX_CONCURRENCY",
    5,
)
RECRUITMENT_JUDGE_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "RECRUITMENT_JUDGE_VALIDATION_ATTEMPTS",
    2,
)
RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS",
    2,
)
RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS: int = _zero_or_one_env(
    "RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS",
    1,
)
CANDIDATE_PROFILE_VALIDATION_ATTEMPTS: int = _positive_int_env(
    "CANDIDATE_PROFILE_VALIDATION_ATTEMPTS",
    2,
)
CANDIDATE_PROFILE_EVALUATION_ATTEMPTS: int = _positive_int_env(
    "CANDIDATE_PROFILE_EVALUATION_ATTEMPTS",
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
    2,
)
RECRUITMENT_PERSONA_PACK_VERSION: str = os.getenv(
    "RECRUITMENT_PERSONA_PACK_VERSION",
    "v1",
)
AGENT_MAX_CONCURRENT_RUNS_PER_USER: int = _positive_int_env("AGENT_MAX_CONCURRENT_RUNS_PER_USER", 1)
AGENT_MAX_ACTIVE_RUNS: int = _positive_int_env("AGENT_MAX_ACTIVE_RUNS", 4)
AGENT_CHAT_HISTORY_LIMIT: int = _positive_int_env("AGENT_CHAT_HISTORY_LIMIT", 20)
AGENT_SESSION_TTL_SECONDS: int = _positive_int_env("AGENT_SESSION_TTL_SECONDS", 3600)
AGENT_MAX_SESSIONS: int = _positive_int_env("AGENT_MAX_SESSIONS", 200)
AGENT_MAX_DRAFT_CHARS: int = _positive_int_env("AGENT_MAX_DRAFT_CHARS", 50000)
AGENT_MAX_PROFILE_CONTEXT_CHARS: int = _positive_int_env("AGENT_MAX_PROFILE_CONTEXT_CHARS", 12000)
AGENT_PENDING_DIFFS_LIMIT: int = _int_env("AGENT_PENDING_DIFFS_LIMIT", 30)
AGENT_MAX_SESSION_ID_CHARS: int = _positive_int_env("AGENT_MAX_SESSION_ID_CHARS", 200)
AGENT_MAX_MESSAGE_CHARS: int = _positive_int_env("AGENT_MAX_MESSAGE_CHARS", 10000)
AGENT_MAX_JOB_CONTEXT_CHARS: int = _positive_int_env("AGENT_MAX_JOB_CONTEXT_CHARS", 20000)
AGENT_MAX_SCORE_CONTEXT_CHARS: int = _positive_int_env("AGENT_MAX_SCORE_CONTEXT_CHARS", 10000)
AGENT_E2E_REQUEST_TIMEOUT_SECONDS: int = _positive_int_env("AGENT_E2E_REQUEST_TIMEOUT_SECONDS", 30)
AGENT_E2E_POLL_INTERVAL_SECONDS: int = _positive_int_env("AGENT_E2E_POLL_INTERVAL_SECONDS", 2)
AGENT_E2E_TERMINAL_TIMEOUT_SECONDS: int = _positive_int_env("AGENT_E2E_TERMINAL_TIMEOUT_SECONDS", 300)
AGENT_SSE_HEARTBEAT_SECONDS: int = _positive_int_env("AGENT_SSE_HEARTBEAT_SECONDS", 15)
if AGENT_MAX_ACTIVE_RUNS < AGENT_MAX_CONCURRENT_RUNS_PER_USER:
    raise ValueError("AGENT_MAX_ACTIVE_RUNS must be at least AGENT_MAX_CONCURRENT_RUNS_PER_USER")
WORKSPACE_AGENT_DRAFT_MIN_CHARS: int = _int_env("WORKSPACE_AGENT_DRAFT_MIN_CHARS", 50)
WORKSPACE_AGENT_DRAFT_LABEL_ROLE_CHARS: int = _int_env("WORKSPACE_AGENT_DRAFT_LABEL_ROLE_CHARS", 80)
WORKSPACE_SUBMITTED_ARTIFACT_TOKEN_BYTES: int = _int_env("WORKSPACE_SUBMITTED_ARTIFACT_TOKEN_BYTES", 12)
WORKSPACE_AGENT_REVIEW_DEFAULT_ROLES: tuple[str, ...] = _csv_env(
    "WORKSPACE_AGENT_REVIEW_DEFAULT_ROLES",
    "recruiter,hiring_manager,ats,skeptic,market_researcher",
)

# ── SEA-LION throughput / network knobs ───────────────────────────────────────
# Free tier is 10 req/min/key; default kept at 9 for headroom against 429s.
SEALION_REQ_PER_MIN: int = _int_env("SEALION_REQ_PER_MIN", 9)
SEALION_HTTP_TIMEOUT: int = _int_env("SEALION_HTTP_TIMEOUT", 60)  # seconds

# ── Database / scraper runtime knobs ─────────────────────────────────────────
DATABASE_POOL_SIZE: int = _int_env("DATABASE_POOL_SIZE", 5)
DATABASE_MAX_OVERFLOW: int = _int_env("DATABASE_MAX_OVERFLOW", 10)
DATABASE_POOL_TIMEOUT: int = _int_env("DATABASE_POOL_TIMEOUT", 30)
DATABASE_POOL_RECYCLE_SECONDS: int = _int_env("DATABASE_POOL_RECYCLE_SECONDS", 1800)
CAREERSGOV_CACHE_TTL_SECONDS: int = _int_env("CAREERSGOV_CACHE_TTL_SECONDS", 3600)
CAREERSGOV_HTTP_TIMEOUT_SECONDS: int = _int_env("CAREERSGOV_HTTP_TIMEOUT_SECONDS", 30)
JD_ENRICHMENT_MAX_WORKERS: int = _int_env("JD_ENRICHMENT_MAX_WORKERS", 3)
FAILED_SUMMARY_RETRY_SECONDS: int = _int_env("FAILED_SUMMARY_RETRY_SECONDS", 300)
ANALYTICS_FILTER_META_TTL_SECONDS: int = _int_env("ANALYTICS_FILTER_META_TTL_SECONDS", 300)
ANALYTICS_CACHE_TTL_SECONDS: int = _int_env("ANALYTICS_CACHE_TTL_SECONDS", 86400)
ANALYTICS_QUERY_CACHE_TTL_SECONDS: int = _int_env("ANALYTICS_QUERY_CACHE_TTL_SECONDS", 3600)
ANALYTICS_QUERY_CACHE_MAX: int = _int_env("ANALYTICS_QUERY_CACHE_MAX", 64)
ANALYTICS_MAX_ROWS: int = _int_env("ANALYTICS_MAX_ROWS", 12000)
ANALYTICS_YIELD_PER: int = _int_env("ANALYTICS_YIELD_PER", 500)

# ── Resume-tailoring pipeline token budgets (all on the FAST tier) ────────────
PIPELINE_STRATEGY_MAX_TOKENS: int = _int_env("PIPELINE_STRATEGY_MAX_TOKENS", 800)
PIPELINE_REWRITE_TOKENS_PER_BULLET: int = _int_env("PIPELINE_REWRITE_TOKENS_PER_BULLET", 150)
PIPELINE_SUMMARY_MAX_TOKENS: int = _int_env("PIPELINE_SUMMARY_MAX_TOKENS", 200)

# ── Resume validation gates ──────────────────────────────────────────────────
VALIDATION_REWRITE_MAX_EXPANSION_RATIO: float = _float_env(
    "VALIDATION_REWRITE_MAX_EXPANSION_RATIO",
    2.0,
)
