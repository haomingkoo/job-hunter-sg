"""
AI service — SEA-LION integration with rate throttling.

Uses the SEA-LION API (OpenAI-compatible) from AI Singapore.
Free tier: 10 requests per minute.
"""

from __future__ import annotations

import json
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
_ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")


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
                f"Admin notification pending."
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
    AI-powered resume coaching.
    Returns structured, conversational coaching like a real career advisor.
    """
    system = """You are an expert career coach with 10+ years of experience helping job seekers in Singapore land roles at top companies and government agencies. You've reviewed thousands of resumes and know exactly what hiring managers and ATS systems look for.

Your coaching style:
- Warm but direct — like a mentor who genuinely wants them to succeed
- Reference SPECIFIC lines from their resume (quote them)
- Explain WHY something works or doesn't (not just what to change)
- Give concrete before/after examples for weak bullets
- Understand the Singapore job market (MCF, SkillsFuture credits, EP/SP considerations, statutory boards, GovTech, MNCs in SG)

Structure your review in this exact order:

1. **First Impression** (2-3 sentences)
   What a recruiter sees in the first 6 seconds. Is the headline/summary compelling? Does it pass the "so what" test?

2. **What's Working Well** (2-3 specific things)
   Call out their strongest bullets with exact quotes. Explain why these work. Build their confidence before the critique.

3. **Critical Improvements** (3-5 specific fixes)
   For each: quote the weak text → explain the problem → give a rewritten version.
   Focus on: weak action verbs, missing metrics, vague impact, buried results, filler words.

4. **Inconsistencies & Red Flags** (if any)
   Flag anything that doesn't add up — conflicting dates, different numbers for the same achievement (e.g. "$3M" in one place and "$2M" in another), gaps in employment that should be addressed, claims that seem inconsistent. Don't fix these silently — call them out so the user can clarify.

5. **Missing Elements** (1-3 things)
   What's not on the resume but should be? Skills gaps, missing sections, SG-specific items (residency status, SkillsFuture certs, language skills).

6. **Quick Wins** (2-3 easy fixes)
   Things they can fix in 5 minutes that will immediately improve their score.

PAGE LENGTH: The ideal resume is 1-2 pages. 3 pages is acceptable for senior professionals with 15+ years of experience. If the resume is over 3 pages, recommend what to trim. Don't be rigid about 1 page — 2 pages is perfectly fine for most candidates in Singapore.

IMPORTANT: Never alter factual information (names, emails, phone numbers, dates, company names, degrees, certifications). Only suggest improvements to wording, structure, and presentation. If something seems wrong, flag it for the user to fix — don't change it yourself.

Keep it conversational — like you're sitting across from them at a coffee shop in Singapore, not writing a formal report. Use "you" and "your". Be encouraging but honest."""

    # Send full resume — SEA-LION supports up to 128K context
    user_msg = f"Please review my resume:\n\n{resume_text}"
    if job_description:
        user_msg += f"\n\n---\nI'm applying for this role:\n{job_description[:2000]}"
        user_msg += "\n\nPlease focus on how I can tailor my resume for this specific job. What keywords am I missing? How should I reframe my experience?"
    else:
        user_msg += "\n\nI'm looking for roles in Singapore. Please give me a general review and help me make this stronger."

    content = _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=1500,  # Enough for detailed coaching on a 2-page resume
        temperature=0.7,
    )

    if not content:
        return None

    return {
        "coaching": content,
        "model": "AI",
        "provider": "AI Singapore",
    }


def rewrite_bullet(bullet: str, job_title: str = "", context: str = "") -> Optional[str]:
    """Rewrite a single resume bullet to be more impactful."""
    system = """You are a resume writing expert who has helped thousands of professionals in Singapore.

CRITICAL — DO NOT HALLUCINATE:
- NEVER invent company names, dates, metrics, or achievements that aren't in the original
- If the original says "$50M", keep it as "$50M" — do not change to "$60M"
- If there are no numbers, use placeholders like [X%] or [N] that the user fills in themselves
- Preserve all factual information exactly as-is

Rules for rewriting:
- Start with a STRONG action verb (Led, Spearheaded, Engineered, Drove, Optimized — not Managed, Helped, Worked on)
- Include measurable IMPACT (%, $, team size, time saved, users affected)
- Keep it to 1-2 lines max
- Make it ATS-friendly (use standard industry terms, not jargon)
- Return ONLY the rewritten bullet, nothing else. No explanation, no prefix, just the bullet."""

    user_msg = f"Rewrite this resume bullet:\n\"{bullet}\""
    if job_title:
        user_msg += f"\n\nThis is for a {job_title} role."
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


def prep_interview(resume_text: str, job_description: str) -> Optional[str]:
    """Generate interview prep based on resume + job description."""
    system = """You are an interview coach who has conducted 5,000+ interviews at Singapore companies.

Based on the candidate's resume and the job description, generate:

1. **Likely Interview Questions** (5-7 questions)
   Mix of behavioral (STAR format) and technical/role-specific.
   For each question, give a brief coaching tip on how to answer.

2. **Your STAR Stories** (3 stories)
   Pull from THEIR resume — identify their best achievements and frame them as STAR stories:
   - Situation: [context from their experience]
   - Task: [what they needed to do]
   - Action: [what they did — use their own bullet points]
   - Result: [the outcome/impact]

3. **Questions to Ask the Interviewer** (3 smart questions)
   Based on the job description, suggest questions that show genuine interest and research.

4. **Singapore-Specific Tips**
   Dress code norms for SG companies, common interview formats (panel vs 1:1), cultural expectations.

Be conversational and encouraging. Use "you" and "your"."""

    user_msg = f"My resume:\n{resume_text[:2000]}\n\n---\nJob I'm interviewing for:\n{job_description[:2000]}"

    content = _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=1000,
        temperature=0.7,
    )
    return content


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
    try:
        # Find JSON array in response
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except (json.JSONDecodeError, ValueError):
        pass

    return [{"rank": 1, "job_index": 0, "reason": content[:200]}]
