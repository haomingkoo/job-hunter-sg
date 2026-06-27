from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _Limiter:
    def acquire(self, timeout: float = 30) -> bool:
        return True


class _Response:
    def __init__(self, message: dict):
        self._message = message

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [{"message": self._message}],
            "usage": {"total_tokens": 12},
        }


def test_call_sealion_reads_standard_content(monkeypatch):
    import ai_service

    monkeypatch.setattr(ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(ai_service, "_limiter", _Limiter())
    monkeypatch.setattr(
        ai_service.requests,
        "post",
        lambda *args, **kwargs: _Response({"role": "assistant", "content": "Standard reply"}),
    )

    assert ai_service._call_sealion([{"role": "user", "content": "hello"}]) == "Standard reply"


def test_call_sealion_reads_sealion_reasoning_content(monkeypatch):
    import ai_service

    monkeypatch.setattr(ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(ai_service, "_limiter", _Limiter())
    monkeypatch.setattr(
        ai_service.requests,
        "post",
        lambda *args, **kwargs: _Response(
            {"role": "assistant", "reasoning_content": "SEA-LION reply"}
        ),
    )

    assert ai_service._call_sealion([{"role": "user", "content": "hello"}]) == "SEA-LION reply"


def test_pipeline_model_can_be_overridden(monkeypatch):
    import ai_service
    import config

    original = os.environ.get("SEALION_PIPELINE_MODEL")
    monkeypatch.setenv("SEALION_PIPELINE_MODEL", "test-pipeline-model")
    try:
        importlib.reload(config)
        reloaded = importlib.reload(ai_service)

        assert reloaded.SEALION_MODEL_PIPELINE_BULLETS == "test-pipeline-model"
        assert reloaded.SEALION_MODEL_REASONING == "test-pipeline-model"
    finally:
        if original is None:
            monkeypatch.delenv("SEALION_PIPELINE_MODEL", raising=False)
        else:
            monkeypatch.setenv("SEALION_PIPELINE_MODEL", original)
        importlib.reload(config)
        importlib.reload(ai_service)
