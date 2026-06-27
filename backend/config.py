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
    """Read an int from the environment, falling back to ``default`` if unset/invalid."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ── SEA-LION model tiers ──────────────────────────────────────────────────────
# FAST: interactive rewrites, JD summaries, default classic pipeline tier.
SEALION_FAST_MODEL: str = os.getenv(
    "SEALION_FAST_MODEL", "aisingapore/Qwen-SEA-LION-v4-32B-IT"
)
# Classic tailoring pipeline model. Defaults to FAST because v4.5 Qwen currently
# leaks reasoning text into strict JSON/prose prompts on this path.
SEALION_PIPELINE_MODEL: str = os.getenv("SEALION_PIPELINE_MODEL", SEALION_FAST_MODEL)
# AGENT: Resume Agent v2 orchestration and tool-calling loop.
SEALION_AGENT_MODEL: str = os.getenv(
    "SEALION_AGENT_MODEL", "aisingapore/Qwen-SEA-LION-v4.5-27B-IT"
)
# SMART: deep-agent persona reviews (single-shot, no tools, latency-tolerant).
SEALION_SMART_MODEL: str = os.getenv(
    "SEALION_SMART_MODEL", "aisingapore/Qwen-SEA-LION-v4.5-27B-IT"
)
# SMART is a reasoning model — under a tight budget it spends all tokens "thinking"
# and returns empty. Floor its max_tokens at call sites that use it.
SMART_MIN_MAX_TOKENS: int = 3000

# ── Resume deep-agent v2 knobs ───────────────────────────────────────────────
AGENT_MAX_TOOL_ITERATIONS: int = _int_env("AGENT_MAX_TOOL_ITERATIONS", 8)
AGENT_PERSONA_COUNT: int = _int_env("AGENT_PERSONA_COUNT", 5)
AGENT_SMART_MAX_TOKENS: int = max(
    SMART_MIN_MAX_TOKENS,
    _int_env("AGENT_SMART_MAX_TOKENS", SMART_MIN_MAX_TOKENS),
)
AGENT_SEARCH_JOBS_LIMIT: int = _int_env("AGENT_SEARCH_JOBS_LIMIT", 7)
AGENT_MAX_CONCURRENT_RUNS_PER_USER: int = _int_env(
    "AGENT_MAX_CONCURRENT_RUNS_PER_USER", 1
)
AGENT_CHAT_HISTORY_LIMIT: int = _int_env("AGENT_CHAT_HISTORY_LIMIT", 20)

# ── SEA-LION throughput / network knobs ───────────────────────────────────────
# Free tier is 10 req/min/key; default kept at 9 for headroom against 429s.
SEALION_REQ_PER_MIN: int = _int_env("SEALION_REQ_PER_MIN", 9)
SEALION_HTTP_TIMEOUT: int = _int_env("SEALION_HTTP_TIMEOUT", 60)  # seconds

# ── Resume-tailoring pipeline token budgets (all on the FAST tier) ────────────
PIPELINE_STRATEGY_MAX_TOKENS: int = _int_env("PIPELINE_STRATEGY_MAX_TOKENS", 800)
PIPELINE_REWRITE_TOKENS_PER_BULLET: int = _int_env(
    "PIPELINE_REWRITE_TOKENS_PER_BULLET", 150
)
PIPELINE_SUMMARY_MAX_TOKENS: int = _int_env("PIPELINE_SUMMARY_MAX_TOKENS", 200)
