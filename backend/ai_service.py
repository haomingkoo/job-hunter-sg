"""
AI service — SEA-LION integration with rate throttling.

Uses the SEA-LION API (OpenAI-compatible) from AI Singapore.
Free tier: 10 requests per minute.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

import requests

log = logging.getLogger("jobhunter.ai")

# ── Rate limiter (token bucket, 10 req/min) ────────────────────────────────

class _RateLimiter:
    """Thread-safe token-bucket rate limiter."""

    def __init__(self, max_tokens: int = 10, refill_seconds: float = 60):
        self._max = max_tokens
        self._tokens = float(max_tokens)
        self._refill_rate = max_tokens / refill_seconds
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    @property
    def queue_position(self) -> int:
        """Approximate number of requests waiting."""
        with self._lock:
            return max(0, int(-self._tokens))

    @property
    def wait_seconds(self) -> float:
        """Estimated seconds until a token is available."""
        with self._lock:
            if self._tokens >= 1:
                return 0
            return max(0, (1 - self._tokens) / self._refill_rate)

    def acquire(self, timeout: float = 30) -> bool:
        """Block until a token is available or timeout."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self._max, self._tokens + elapsed * self._refill_rate)
                self._last_refill = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)


# ── SEA-LION Client ─────────────────────────────────────────────────────────

SEALION_BASE_URL = "https://api.sea-lion.ai/v1"
SEALION_MODEL = "aisingapore/Qwen-SEA-LION-v4-32B-IT"

# Available models (for reference):
# - aisingapore/Qwen-SEA-LION-v4-32B-IT  (best quality, 32B)
# - aisingapore/Gemma-SEA-LION-v4-27B-IT (27B, good alternative)
# - aisingapore/Llama-SEA-LION-v3.5-70B-R (70B reasoning, slower)
# - aisingapore/Llama-SEA-LION-v3-70B-IT  (70B instruct)
# - aisingapore/SEA-Guard (safety model)


def _load_api_keys() -> list[str]:
    """Load all SEA-LION API keys from environment (supports multiple)."""
    keys = []
    # Primary key
    k1 = os.environ.get("SEALION_API", os.environ.get("sealion_api", ""))
    if k1:
        keys.append(k1)
    # Additional keys (sealion_api2, sealion_api3, etc.)
    for i in range(2, 10):
        k = os.environ.get(f"SEALION_API{i}", os.environ.get(f"sealion_api{i}", ""))
        if k:
            keys.append(k)
    return keys


_api_keys = _load_api_keys()
_key_index = 0
_key_lock = threading.Lock()

# Rate limiter: 9 req/min per key, so N keys = 9*N req/min total
_limiter = _RateLimiter(
    max_tokens=max(1, 9 * len(_api_keys)),
    refill_seconds=60,
)

log.info(f"[AI] Loaded {len(_api_keys)} SEA-LION API key(s) → {9 * len(_api_keys)} req/min capacity")


def _get_api_key() -> str:
    """Round-robin through available API keys."""
    global _key_index
    if not _api_keys:
        return ""
    with _key_lock:
        key = _api_keys[_key_index % len(_api_keys)]
        _key_index += 1
        return key


# ── Failure tracking & alerting ─────────────────────────────────────────────

_failure_count = 0
_failure_lock = threading.Lock()
_last_alert_time = 0
_ALERT_THRESHOLD = 5          # Alert after 5 consecutive failures
_ALERT_COOLDOWN = 300         # Don't spam alerts — max once per 5 min
_ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "haomingkoo@gmail.com")


def _track_failure(error_type: str, detail: str) -> None:
    """Track failures and alert admin if things are broken."""
    global _failure_count, _last_alert_time
    with _failure_lock:
        _failure_count += 1
        if _failure_count >= _ALERT_THRESHOLD and (time.time() - _last_alert_time) > _ALERT_COOLDOWN:
            _last_alert_time = time.time()
            log.critical(
                f"[AI ALERT] {_failure_count} consecutive failures! "
                f"Last error: {error_type} ({detail}). "
                f"Admin: {_ADMIN_EMAIL}"
            )
            # TODO: Send actual email/Telegram alert here
            # For now this logs as CRITICAL which Railway/monitoring will catch


def _track_success() -> None:
    """Reset failure counter on success."""
    global _failure_count
    with _failure_lock:
        _failure_count = 0


def get_ai_health() -> dict:
    """Internal health status for monitoring."""
    return {
        "consecutive_failures": _failure_count,
        "is_healthy": _failure_count < _ALERT_THRESHOLD,
        "keys_loaded": len(_api_keys),
    }


def _call_sealion(
    messages: list[dict],
    max_tokens: int = 500,
    model: str = SEALION_MODEL,
    temperature: float = 0.7,
) -> Optional[str]:
    """Call SEA-LION API with rate limiting. Returns response text or None."""
    api_key = _get_api_key()
    if not api_key:
        log.warning("[AI] SEA-LION API key not set (sealion_api)")
        return None

    if not _limiter.acquire(timeout=30):
        log.warning("[AI] Rate limit — could not acquire token in 30s")
        return None

    try:
        resp = requests.post(
            f"{SEALION_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_completion_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        log.info(
            f"[AI] SEA-LION response: {usage.get('total_tokens', '?')} tokens"
        )
        _track_success()
        return content
    except requests.exceptions.RequestException as e:
        err_type = type(e).__name__
        err_status = getattr(getattr(e, "response", None), "status_code", "N/A")
        log.warning(f"[AI] SEA-LION request failed: {err_type} (status={err_status})")
        _track_failure(err_type, err_status)
        return None
    except (KeyError, IndexError) as e:
        log.warning(f"[AI] SEA-LION parse error: {type(e).__name__}: {e}")
        _track_failure("ParseError", str(e)[:50])
        return None


# ── Status ──────────────────────────────────────────────────────────────────

def get_ai_status() -> dict:
    """Return current AI service status for display to users."""
    wait = _limiter.wait_seconds
    capacity = _limiter._max
    available = max(0, int(_limiter._tokens)) if hasattr(_limiter, '_tokens') else capacity

    # Check if service is down (consecutive failures)
    if _failure_count >= _ALERT_THRESHOLD:
        return {
            "status": "down",
            "message": "AI service is temporarily unavailable. We've been notified and are working on it.",
            "wait_seconds": -1,
        }

    if available > capacity * 0.5:
        status_text = "ready"
        message = "AI is ready — results in ~15 seconds"
    elif available > 0:
        status_text = "busy"
        message = f"AI is busy — estimated wait ~{int(wait + 15)} seconds"
    else:
        status_text = "queued"
        message = f"High demand — estimated wait ~{int(wait + 15)} seconds"

    return {
        "status": status_text,
        "message": message,
        "wait_seconds": round(wait, 1),
    }


# ── Public AI Features ──────────────────────────────────────────────────────

def coach_resume(resume_text: str, job_description: str = "") -> Optional[dict]:
    """
    AI-powered resume coaching using SEA-LION.
    Returns conversational feedback with per-bullet suggestions.
    """
    system = (
        "You are an expert Singapore career coach with 10+ years experience "
        "reviewing resumes for tech, PM, and engineering roles in Singapore. "
        "You understand the SG job market (MCF, SkillsFuture, EP/SP visas, "
        "statutory boards, GovTech, FAANG-SEA). "
        "Give specific, actionable feedback. Reference exact text from the resume. "
        "Be encouraging but honest. Use a conversational tone — not bullet points."
    )

    user_msg = f"Review this resume and give coaching feedback:\n\n{resume_text[:3000]}"
    if job_description:
        user_msg += f"\n\n---\nTarget job description:\n{job_description[:2000]}"
        user_msg += "\n\nFocus on how to tailor this resume for this specific role."

    content = _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=800,
        temperature=0.7,
    )

    if not content:
        return None

    return {
        "coaching": content,
        "model": SEALION_MODEL,
        "provider": "AI",
    }


def rewrite_bullet(bullet: str, job_title: str = "", context: str = "") -> Optional[str]:
    """Rewrite a single resume bullet to be more impactful."""
    system = (
        "You are a resume writing expert. Rewrite the given resume bullet to be "
        "more impactful. Use strong action verbs, add quantification where possible, "
        "and make the result-oriented. Return ONLY the rewritten bullet, nothing else."
    )

    user_msg = f"Rewrite this resume bullet:\n\"{bullet}\""
    if job_title:
        user_msg += f"\n\nTarget role: {job_title}"
    if context:
        user_msg += f"\nContext: {context}"

    return _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=200,
        temperature=0.7,
    )


def match_resume_to_jobs(resume_text: str, jobs: list[dict], top_n: int = 5) -> Optional[list[dict]]:
    """
    Use AI to rank jobs by fit with the resume.
    Returns top_n jobs with match reasoning.
    """
    # Build a compact job summary
    job_summaries = []
    for i, j in enumerate(jobs[:20]):
        job_summaries.append(
            f"[{i+1}] {j.get('title', '')} @ {j.get('company', '')} "
            f"| Skills: {', '.join(j.get('skills', [])[:5])}"
        )

    system = (
        "You are a job matching expert. Given a resume and a list of jobs, "
        "rank the top 5 best matches. For each, explain WHY it's a good fit "
        "in 1 sentence. Return as JSON array: [{\"rank\": 1, \"job_index\": N, \"reason\": \"...\"}]"
    )

    user_msg = (
        f"Resume (summary):\n{resume_text[:1500]}\n\n"
        f"Available jobs:\n" + "\n".join(job_summaries)
    )

    content = _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=400,
        temperature=0.3,
    )

    if not content:
        return None

    # Try to parse JSON from response
    import json
    try:
        # Find JSON array in response
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except (json.JSONDecodeError, ValueError):
        pass

    return [{"rank": 1, "job_index": 0, "reason": content[:200]}]
