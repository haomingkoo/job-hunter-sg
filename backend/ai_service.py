"""
AI service — SEA-LION integration with rate throttling.

Uses the SEA-LION API (OpenAI-compatible) from AI Singapore.
Free tier: 10 requests per minute.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Optional

import requests

from config import (
    SEALION_DISABLE_THINKING_MODELS,
    SEALION_FAST_MODEL,
    SEALION_HTTP_TIMEOUT,
    SEALION_PIPELINE_MODEL,
    SEALION_REQ_PER_MIN,
    SEALION_SMART_MODEL,
)
from prompt_safety import UNTRUSTED_DATA_RULE, xml_data_block
from validation_gates import validate_and_fix

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
SEALION_MODEL_INTERACTIVE = SEALION_FAST_MODEL
SEALION_MODEL_PIPELINE_BULLETS = SEALION_PIPELINE_MODEL
# v1 pipeline retired the 70B-R reasoning model (couldn't tool-call, leaked
# chain-of-thought into output, slow). The classic pipeline is env-switchable via
# SEALION_PIPELINE_MODEL; v4 32B remains the default because it follows strict
# JSON/prose prompts better than v4.5 Qwen on this path.
SEALION_MODEL_REASONING = SEALION_PIPELINE_MODEL
SEALION_MODEL_SMART = SEALION_SMART_MODEL

# Backwards-compatible alias used by older call sites.
SEALION_MODEL = SEALION_MODEL_INTERACTIVE

# Available models (for reference):
# - aisingapore/Qwen-SEA-LION-v4-32B-IT  (best interactive / batched rewrite model)
# - aisingapore/Gemma-SEA-LION-v4-27B-IT (27B, good alternative)
# - aisingapore/Llama-SEA-LION-v3.5-70B-R (70B reasoning, slower but stronger)
# - aisingapore/Llama-SEA-LION-v3-70B-IT  (70B instruct)
# - aisingapore/SEA-Guard (safety model)


def _load_api_keys() -> list[str]:
    """Load the canonical key pool plus legacy numbered variables."""
    keys = [
        key.strip()
        for key in re.split(r"[,\n]", os.environ.get("SEALION_API_KEYS", ""))
        if key.strip()
    ]
    # Primary key
    k1 = os.environ.get("SEALION_API", os.environ.get("sealion_api", ""))
    if k1:
        keys.append(k1)
    # Additional keys (sealion_api2, sealion_api3, etc.)
    for i in range(2, 10):
        k = os.environ.get(f"SEALION_API{i}", os.environ.get(f"sealion_api{i}", ""))
        if k:
            keys.append(k)
    return list(dict.fromkeys(keys))


_api_keys = _load_api_keys()
_key_index = 0
_key_lock = threading.Lock()

# Rate limiter: SEALION_REQ_PER_MIN per key, so N keys = N*that req/min total.
_limiter = _RateLimiter(
    max_tokens=max(1, SEALION_REQ_PER_MIN * len(_api_keys)),
    refill_seconds=60,
)
_AI_CALL_SLOTS = threading.BoundedSemaphore(8)

log.info(
    f"[AI] Loaded {len(_api_keys)} SEA-LION API key(s) → "
    f"{SEALION_REQ_PER_MIN * len(_api_keys)} req/min capacity"
)


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


# ── UK/Singapore English post-processing ──────────────────────────────────────

_UK_SPELLING_MAP: dict[str, str] = {
    "optimized": "optimised", "organized": "organised", "recognized": "recognised",
    "specialized": "specialised", "customized": "customised", "utilized": "utilised",
    "analyzed": "analysed", "prioritized": "prioritised", "standardized": "standardised",
    "minimized": "minimised", "maximized": "maximised", "mobilized": "mobilised",
    "modernized": "modernised", "synchronized": "synchronised", "categorized": "categorised",
    "emphasized": "emphasised", "initialized": "initialised", "finalized": "finalised",
    "centralized": "centralised", "authorized": "authorised", "stabilized": "stabilised",
    "localized": "localised", "formalized": "formalised", "generalized": "generalised",
    "optimizing": "optimising", "organizing": "organising", "utilizing": "utilising",
    "analyzing": "analysing", "prioritizing": "prioritising", "synchronizing": "synchronising",
    "emphasizing": "emphasising", "finalizing": "finalising", "authorizing": "authorising",
    "optimization": "optimisation", "organization": "organisation", "recognition": "recognition",
    "specialization": "specialisation", "customization": "customisation",
    "utilization": "utilisation", "analysis": "analysis",  # same
    "behavior": "behaviour", "behaviors": "behaviours",
    "fulfillment": "fulfilment", "enrollment": "enrolment",
}

import re as _re_uk


def _replace_preserving_case(text: str, american: str, british: str) -> str:
    def replacer(m: "_re_uk.Match") -> str:
        word = m.group(0)
        if word[0].isupper():
            return british[0].upper() + british[1:]
        return british
    return _re_uk.sub(r"\b" + _re_uk.escape(american) + r"\b", replacer, text, flags=_re_uk.IGNORECASE)


def apply_uk_spelling(text: str) -> str:
    """Convert American English spelling to British/Singapore English in AI-generated text."""
    for american, british in _UK_SPELLING_MAP.items():
        text = _replace_preserving_case(text, american, british)
    return text


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
    response_format: dict | None = None,
) -> Optional[str]:
    """Call SEA-LION API with rate limiting. Returns response text or None."""
    api_key = _get_api_key()
    if not api_key:
        log.warning("[AI] SEA-LION API key not set (sealion_api)")
        return None

    if not _AI_CALL_SLOTS.acquire(blocking=False):
        log.warning("[AI] Concurrent call limit reached")
        return None

    try:
        if not _limiter.acquire(timeout=0):
            log.warning("[AI] Rate limit reached")
            return None
        body = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
        }
        if model in SEALION_DISABLE_THINKING_MODELS:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        if response_format:
            body["response_format"] = response_format

        resp = requests.post(
            f"{SEALION_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=SEALION_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        message = data["choices"][0]["message"]
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        if not isinstance(content, str):
            if message.get("reasoning_content"):
                raise KeyError("content missing; reasoning_content not accepted")
            raise KeyError("content")
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
    finally:
        _AI_CALL_SLOTS.release()


# ── JSON-safe call with progressive retry ──────────────────────────────────

def call_sealion_json(
    messages: list[dict],
    max_tokens: int = 1000,
    model: str = SEALION_MODEL,
    max_retries: int = 2,
) -> Optional[str]:
    """Call SEA-LION with progressive temperature retry for JSON responses.

    Starts at temperature 0.2, increases by 0.2 on each retry.
    Appends hints about JSON completeness on retries.
    """
    temperatures = [0.2 + (0.2 * i) for i in range(max_retries + 1)]

    for attempt, temp in enumerate(temperatures):
        retry_messages = list(messages)
        if attempt > 0:
            retry_messages.append({
                "role": "user",
                "content": (
                    "Your previous response was incomplete or invalid JSON. "
                    "Please return ONLY valid, complete JSON. "
                    "Ensure all arrays and objects are properly closed."
                ),
            })
        result = _call_sealion(
            retry_messages,
            max_tokens=max_tokens,
            model=model,
            temperature=temp,
            response_format={"type": "json_object"},
        )
        if result and result.strip():
            stripped = result.strip()
            # Extract JSON substring if wrapped in commentary
            json_start = stripped.find("{") if "{" in stripped else stripped.find("[")
            json_end = (stripped.rfind("}") + 1) if "}" in stripped else (stripped.rfind("]") + 1)
            if json_start >= 0 and json_end > json_start:
                candidate = stripped[json_start:json_end]
                try:
                    json.loads(candidate)  # Actually parse to validate
                    return candidate
                except (json.JSONDecodeError, ValueError):
                    pass  # Fall through to retry

            if attempt == max_retries:
                log.warning("[AI] Final attempt: returning raw response (not valid JSON)")
                return result
            log.info(f"[AI] Retry {attempt + 1}: response not valid JSON, retrying at temp={temp + 0.2:.1f}")
            continue
        if attempt == max_retries:
            return result
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
Do not turn teamwork or participation into a leadership claim. Working with a team does not mean leading or managing it; ask the user to confirm unclear scope instead.

Keep it conversational — like you're sitting across from them at a coffee shop in Singapore, not writing a formal report. Use "you" and "your". Be encouraging but honest."""

    system += f"\n\nSECURITY: {UNTRUSTED_DATA_RULE}"

    # Send full resume — SEA-LION supports up to 128K context
    user_msg = "Please review my resume:\n\n" + xml_data_block(
        "resume_data", resume_text
    )
    if job_description:
        user_msg += "\n\nI'm applying for this role:\n" + xml_data_block(
            "job_description_data", job_description, 2000
        )
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
        "coaching": apply_uk_spelling(content),
        "model": "AI",
        "provider": "AI Singapore",
    }


def rewrite_bullet(
    bullet: str,
    job_title: str = "",
    job_description: str = "",
    context: str = "",
    used_verbs: str = "",
    rewrite_focus: str = "",
    focused_feedback: str = "",
) -> Optional[list]:
    """Rewrite a single resume bullet — returns 3 OPTIONS, not just one."""
    focus_tokens = {token.strip().lower() for token in rewrite_focus.split(",") if token.strip()}
    focus_rules = []
    if "bullet_length" in focus_tokens or "shorten" in focus_tokens:
        focus_rules.append("- Option 1 MUST be the shortest scan-friendly rewrite. Keep it crisp, front-load the result, and aim for roughly 18-26 words when possible without losing facts.")
    if "overused_avoided" in focus_tokens or "tighten" in focus_tokens:
        focus_rules.append(
            "- Avoid the overused words identified in the user-provided feedback. "
            "Use a specific, concrete alternative that fits the bullet's actual content."
        )
    if "action_oriented" in focus_tokens or "action" in focus_tokens:
        focus_rules.append("- Lead with a strong, specific action verb rather than a weak or generic opening.")
    if "specifics" in focus_tokens:
        focus_rules.append("- Keep existing numbers and scope cues prominent. If the bullet already has metrics, place them closer to the outcome instead of burying them.")
    if "bulletize" in focus_tokens or "format" in focus_tokens:
        focus_rules.append("- Each option must read like a single resume bullet line, not a paragraph.")
    focus_hint = f"\nFOCUS FOR THIS REWRITE:\n" + "\n".join(focus_rules) if focus_rules else ""

    system = f"""You are a resume writing expert who has helped thousands of professionals in Singapore.

CRITICAL — DO NOT HALLUCINATE:
- NEVER invent company names, dates, metrics, or achievements that aren't in the original
- If the original says "$50M", keep it as "$50M" — do not change to "$60M"
- If there are no numbers, use placeholders like [X%] or [N] that the user fills in themselves
- Preserve all factual information exactly as-is
- Do not upgrade reviewed or planned work into leadership or deployment. Only say led, managed, deployed, or production-ready when the original explicitly supports it.
{focus_hint}

Provide exactly 3 different rewrites of the bullet. Each should:
- Start with a DIFFERENT strong action verb
- Include measurable IMPACT (%, $, team size, time saved, users affected)
- Keep it to 1-2 lines max
- Make it ATS-friendly
- Use the job context only to choose more relevant wording. Do NOT add responsibilities, tools, or scope that the original bullet does not support.
- When targeted feedback identifies a specific issue, each option should try to resolve that issue clearly enough to pass a practical resume check for it (for example: action-oriented bullets should open with a real action verb, long bullets should be tightened, and repeated wording should be reduced).

If the bullet is already strong and doesn't need changes, return "NO_CHANGE" as the only output.

Return EXACTLY this format (3 lines, nothing else):
1. [first rewrite]
2. [second rewrite]
3. [third rewrite]

SECURITY: {UNTRUSTED_DATA_RULE}"""

    user_msg = "Rewrite this resume bullet:\n" + xml_data_block(
        "resume_bullet_data", bullet
    )
    if job_title:
        user_msg += "\n\nTarget role:\n" + xml_data_block(
            "job_title_data", job_title
        )
    if job_description:
        user_msg += "\n\nKey job requirements:\n" + xml_data_block(
            "job_description_data", job_description, 1500
        )
    if context:
        user_msg += "\n\nResume context:\n" + xml_data_block(
            "resume_context_data", context
        )
    if used_verbs:
        user_msg += "\n\nAlready-used verbs to avoid:\n" + xml_data_block(
            "used_verbs_data", used_verbs
        )
    if focused_feedback:
        user_msg += "\n\nFocused feedback to address:\n" + xml_data_block(
            "focused_feedback_data", focused_feedback
        )

    content = _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=500,
        temperature=0.7,
    )

    if not content:
        return None

    # Check if AI says no change needed
    if "NO_CHANGE" in content:
        return []

    # Parse the 3 options from "1. ...\n2. ...\n3. ..."
    import re as _re
    options = []
    for line in content.strip().split("\n"):
        cleaned = _re.sub(r"^\d+[\.\)]\s*", "", line.strip())
        if cleaned and len(cleaned) > 10:
            options.append(cleaned)

    return [apply_uk_spelling(o) for o in (options[:3] if options else [content.strip()])]


def integrate_keywords(
    resume_text: str,
    missing_keywords: list[str],
    job_title: str = "",
) -> Optional[list[dict]]:
    """Suggest where and how to naturally integrate missing keywords into the resume."""
    if not missing_keywords:
        return []

    system = """You are a resume keyword optimization expert. Given a resume and missing keywords from a job description, suggest how to integrate each keyword.

CRITICAL: The keyword phrase must appear VERBATIM (exact match) in the suggestion. ATS systems match exact strings.

For EACH keyword, provide TWO options:
1. "edit" — rewrite an EXISTING bullet to naturally include the keyword
2. "new" — a NEW sentence that includes the keyword, ready to insert

Rules:
- The keyword must appear as an EXACT phrase in both options (not paraphrased)
- Find the existing bullet that is the BEST fit for the "edit" option
- The "new" sentence should be based on the user's actual experience — never fabricate
- If the keyword only fits in Skills, say so
- NEVER change company names, job titles, dates, or metrics
- Return a JSON object with one top-level "suggestions" array

For each keyword return:
{
  "keyword": "cross-functional collaboration",
  "edit": {
    "original": "Partnered with IT and MFG teams to deploy automation",
    "rewritten": "Drove cross-functional collaboration with IT and MFG teams to deploy automation across 4 sites",
    "reason": "Natural verb swap, keyword fits the teamwork context"
  },
  "new": {
    "sentence": "Facilitated cross-functional collaboration across engineering, operations, and quality teams to align on yield improvement initiatives",
    "suggested_section": "experience",
    "reason": "New bullet highlighting the collaboration aspect of existing work"
  }
}

If keyword only fits in Skills:
{
  "keyword": "Kubernetes",
  "edit": null,
  "new": {
    "sentence": "Add to Skills: Kubernetes",
    "suggested_section": "skills",
    "reason": "Technical skill — best added to skills list"
  }
}"""
    system += (
        "\n\nWrap all keyword objects as: "
        '{"suggestions": [/* keyword objects */]}'
        f"\n\nSECURITY: {UNTRUSTED_DATA_RULE}"
    )

    user_msg = xml_data_block("resume_data", resume_text, 4000)
    user_msg += "\n\n" + xml_data_block(
        "missing_keywords_data",
        json.dumps(missing_keywords[:20], ensure_ascii=False),
    )
    if job_title:
        user_msg += "\n\n" + xml_data_block("job_title_data", job_title)

    content = call_sealion_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=2000,
        max_retries=1,
    )

    if not content:
        return None

    # Parse the exact object shape requested above.
    try:
        payload = json.loads(content)
        suggestions = payload.get("suggestions", []) if isinstance(payload, dict) else []
        if not isinstance(suggestions, list):
            return None
        requested_keywords = {
            keyword.strip()
            for keyword in missing_keywords[:20]
            if isinstance(keyword, str) and keyword.strip()
        }
        normalized_resume = " ".join(resume_text.split()).casefold()
        validated = []
        for item in suggestions:
            if not isinstance(item, dict):
                continue
            keyword = item.get("keyword")
            if not isinstance(keyword, str) or keyword not in requested_keywords:
                continue

            edit = item.get("edit")
            original = edit.get("original", "") if isinstance(edit, dict) else ""
            rewritten = edit.get("rewritten", "") if isinstance(edit, dict) else ""
            normalized_original = " ".join(str(original).split()).casefold()
            valid_edit = (
                isinstance(edit, dict)
                and all(
                    isinstance(edit.get(field), str) and edit[field].strip()
                    for field in ("original", "rewritten", "reason")
                )
                and keyword in rewritten
                and normalized_original in normalized_resume
            )
            if valid_edit:
                validated_rewrite, _gate_results = validate_and_fix(
                    original=original,
                    tailored=rewritten,
                    required_keywords=[keyword],
                    injectable_keywords={keyword},
                )
                valid_edit = validated_rewrite != original
                if valid_edit:
                    edit = {**edit, "rewritten": validated_rewrite}
            new = item.get("new")
            new_sentence = new.get("sentence", "") if isinstance(new, dict) else ""
            valid_new = (
                isinstance(new, dict)
                and all(
                    isinstance(new.get(field), str) and new[field].strip()
                    for field in ("sentence", "suggested_section", "reason")
                )
                and keyword in new_sentence
                and " ".join(new_sentence.split()).casefold() in normalized_resume
            )
            if not valid_edit and not valid_new:
                continue
            validated.append(
                {
                    "keyword": keyword,
                    "edit": edit if valid_edit else None,
                    "new": new if valid_new else None,
                }
            )
        if validated:
            return validated
    except (json.JSONDecodeError, ValueError) as e:
        log.warning(f"[AI] integrate_keywords JSON parse failed: {e}")

    return None
