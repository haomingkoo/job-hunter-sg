from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_model_factory_builds_fast_and_smart_models(monkeypatch):
    import config
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    fast = agent_models.create_fast_model()
    smart = agent_models.create_smart_model()

    assert fast.model_name == config.SEALION_FAST_MODEL
    assert smart.model_name == config.SEALION_SMART_MODEL
    assert smart.max_tokens >= config.SMART_MIN_MAX_TOKENS
