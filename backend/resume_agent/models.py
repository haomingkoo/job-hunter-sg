"""SEA-LION ChatOpenAI factories for the Resume Deep Agent."""

from __future__ import annotations

import ai_service
import config


def create_fast_model(temperature: float = 0.0):
    """Return the FAST model used by the orchestrator and tool-calling loop."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=ai_service.SEALION_BASE_URL,
        api_key=ai_service._get_api_key(),
        model=config.SEALION_FAST_MODEL,
        temperature=temperature,
    )


def create_smart_model(temperature: float = 0.0):
    """Return the SMART model used for single-shot persona critique."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=ai_service.SEALION_BASE_URL,
        api_key=ai_service._get_api_key(),
        model=config.SEALION_SMART_MODEL,
        temperature=temperature,
        max_tokens=config.AGENT_SMART_MAX_TOKENS,
    )
