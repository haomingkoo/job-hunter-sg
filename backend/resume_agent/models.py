"""SEA-LION ChatOpenAI factories for the Resume Deep Agent."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from typing import Any

import ai_service
import config
from langchain_core.rate_limiters import BaseRateLimiter
from pydantic import SecretStr


class _SeaLionRateLimiter(BaseRateLimiter):
    def __init__(self) -> None:
        # One ChatOpenAI instance captures one API key. Pace that key instead
        # of borrowing the aggregate token bucket used by direct calls that
        # rotate keys on every request.
        self._limiter = ai_service._RateLimiter(
            max_tokens=1,
            refill_seconds=60 / max(1, config.SEALION_REQ_PER_MIN),
        )

    def acquire(self, *, blocking: bool = True) -> bool:
        timeout = config.SEALION_HTTP_TIMEOUT if blocking else 0
        return self._limiter.acquire(timeout=timeout)

    async def aacquire(self, *, blocking: bool = True) -> bool:
        return await asyncio.to_thread(self.acquire, blocking=blocking)


_key_rate_limiters: dict[bytes, _SeaLionRateLimiter] = {}
_key_rate_limiters_lock = threading.Lock()


def _rate_limiter_for(api_key: str) -> _SeaLionRateLimiter:
    key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).digest()
    with _key_rate_limiters_lock:
        return _key_rate_limiters.setdefault(key_fingerprint, _SeaLionRateLimiter())


class ResumeAgentConfigurationError(RuntimeError):
    """Raised when the agent cannot be configured from the current environment."""


def _api_key() -> str:
    key = ai_service._get_api_key()
    if not key:
        raise ResumeAgentConfigurationError(
            "Agent v2 needs SEALION_API_KEYS or SEALION_API configured before it can run."
        )
    return key


def _model_kwargs(model: str) -> dict:
    if model in config.SEALION_DISABLE_THINKING_MODELS:
        return {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
    return {}


def create_agent_model(
    temperature: float = 0.0,
    *,
    timeout: int | None = None,
    max_retries: int = 0,
    model: str | None = None,
    max_completion_tokens: int | None = None,
    http_client: Any | None = None,
    callbacks: list[Any] | None = None,
):
    """Return the agentic model used by the orchestrator and tool-calling loop."""
    from langchain_openai import ChatOpenAI

    resolved_model = model or config.SEALION_AGENT_MODEL
    completion_budget: dict[str, Any] = (
        {"max_completion_tokens": max_completion_tokens}
        if max_completion_tokens is not None
        else {}
    )
    api_key = _api_key()
    return ChatOpenAI(
        base_url=ai_service.SEALION_BASE_URL,
        api_key=SecretStr(api_key),
        model=resolved_model,
        temperature=temperature,
        timeout=config.SEALION_HTTP_TIMEOUT if timeout is None else timeout,
        max_retries=max_retries,
        rate_limiter=_rate_limiter_for(api_key),
        http_client=http_client,
        callbacks=callbacks,
        **completion_budget,
        **_model_kwargs(resolved_model),
    )


def create_smart_model(temperature: float = 0.0):
    """Return the SMART model used for single-shot persona critique."""
    from langchain_openai import ChatOpenAI

    api_key = _api_key()
    return ChatOpenAI(
        base_url=ai_service.SEALION_BASE_URL,
        api_key=SecretStr(api_key),
        model=config.SEALION_SMART_MODEL,
        temperature=temperature,
        max_completion_tokens=config.AGENT_SMART_MAX_TOKENS,
        timeout=config.SEALION_HTTP_TIMEOUT,
        max_retries=0,
        rate_limiter=_rate_limiter_for(api_key),
        **_model_kwargs(config.SEALION_SMART_MODEL),
    )
