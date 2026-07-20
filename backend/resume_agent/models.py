"""SEA-LION ChatOpenAI factories for the Resume Deep Agent."""

from __future__ import annotations

import asyncio

import ai_service
import config
from langchain_core.rate_limiters import BaseRateLimiter
from pydantic import SecretStr


class _SeaLionRateLimiter(BaseRateLimiter):
    def acquire(self, *, blocking: bool = True) -> bool:
        timeout = config.SEALION_HTTP_TIMEOUT if blocking else 0
        return ai_service._limiter.acquire(timeout=timeout)

    async def aacquire(self, *, blocking: bool = True) -> bool:
        return await asyncio.to_thread(self.acquire, blocking=blocking)


_rate_limiter = _SeaLionRateLimiter()


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
):
    """Return the agentic model used by the orchestrator and tool-calling loop."""
    from langchain_openai import ChatOpenAI

    resolved_model = model or config.SEALION_AGENT_MODEL
    completion_budget = {"max_completion_tokens": max_completion_tokens} if max_completion_tokens is not None else {}
    return ChatOpenAI(
        base_url=ai_service.SEALION_BASE_URL,
        api_key=SecretStr(_api_key()),
        model=resolved_model,
        temperature=temperature,
        timeout=config.SEALION_HTTP_TIMEOUT if timeout is None else timeout,
        max_retries=max_retries,
        rate_limiter=_rate_limiter,
        **completion_budget,
        **_model_kwargs(resolved_model),
    )


create_fast_model = create_agent_model


def create_smart_model(temperature: float = 0.0):
    """Return the SMART model used for single-shot persona critique."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=ai_service.SEALION_BASE_URL,
        api_key=SecretStr(_api_key()),
        model=config.SEALION_SMART_MODEL,
        temperature=temperature,
        max_completion_tokens=config.AGENT_SMART_MAX_TOKENS,
        timeout=config.SEALION_HTTP_TIMEOUT,
        max_retries=0,
        rate_limiter=_rate_limiter,
        **_model_kwargs(config.SEALION_SMART_MODEL),
    )
