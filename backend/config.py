"""Central tunable config: SEA-LION model tiers + operational knobs.

Named constants for product values; ``os.getenv(...)`` for operational knobs that
should be tunable in prod without a redeploy. Foundation from the ponytail
magic-number audit (2026-06-26) — the highest-value cost/throughput levers land
here first; the broader named-constant sweep across scoring rubrics is a follow-up.

Model-tier rationale: empirical SEA-LION eval (2026-06-26). FAST is the only model
that reliably tool-calls and is fast + clean; SMART is the agent-tuned reasoning
model with the sharpest critiques but it is slow and needs a generous token budget.
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
# FAST: tool-calling agent loop, interactive rewrites, JD summaries, v1 pipeline.
SEALION_FAST_MODEL: str = os.getenv(
    "SEALION_FAST_MODEL", "aisingapore/Qwen-SEA-LION-v4-32B-IT"
)
# SMART: deep-agent persona reviews (single-shot, no tools, latency-tolerant).
SEALION_SMART_MODEL: str = os.getenv(
    "SEALION_SMART_MODEL", "aisingapore/Qwen-SEA-LION-v4.5-27B-IT"
)
# SMART is a reasoning model — under a tight budget it spends all tokens "thinking"
# and returns empty. Floor its max_tokens at call sites that use it.
SMART_MIN_MAX_TOKENS: int = 3000

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
