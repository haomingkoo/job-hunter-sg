from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from recruitment_team.model_transport_observer import (
    ModelTransportObserver,
    bind_transport_collector,
    collect_transport_metrics,
    create_observed_agent_model,
    current_transport_metrics,
    observe_transport_request,
    transport_role,
)
from recruitment_team.telemetry import RecordedTelemetry
from recruitment_team.execution_metrics import merge_execution_event


def _completion() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-observed",
            "object": "chat.completion",
            "created": 1,
            "model": "observed-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def _model(monkeypatch, client: httpx.Client, observer: ModelTransportObserver, *, retries: int):
    import ai_service
    import openai._base_client as openai_base_client
    from resume_agent.models import create_agent_model

    monkeypatch.setattr(openai_base_client.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ai_service, "SEALION_BASE_URL", "https://secret-provider.example/v1")
    monkeypatch.setattr(ai_service, "_get_api_key", lambda: "secret-api-key")
    monkeypatch.setattr(ai_service._limiter, "acquire", lambda **_kwargs: True)
    return create_agent_model(
        model="observed-model",
        max_retries=retries,
        http_client=client,
        callbacks=[observer],
    )


def test_observer_counts_a_successful_sdk_retry_without_recording_payloads(monkeypatch):
    responses = iter([httpx.Response(500), _completion()])
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: next(responses)),
        event_hooks={"request": [observe_transport_request]},
    )
    telemetry = RecordedTelemetry()
    observer = ModelTransportObserver(telemetry)
    try:
        response = _model(monkeypatch, client, observer, retries=1).invoke("private resume text")
    finally:
        client.close()

    assert response.content == "ok"
    span = telemetry.spans[-1]
    assert span.name == "model_transport"
    latency_ms = float(span.attributes.pop("latency_ms"))
    assert latency_ms > 0
    assert span.attributes == {
        "transport_attempt_count": 2,
        "transport_retry_count": 1,
        "outcome": "success",
        "role": "unclassified",
        "model": "observed-model",
        "input_tokens": 1,
        "output_tokens": 1,
        "token_usage_available": True,
    }
    serialized = json.dumps(span.attributes)
    assert "secret-provider" not in serialized
    assert "secret-api-key" not in serialized
    assert "private resume" not in serialized


def test_observer_counts_exhausted_connection_retries_with_safe_error_type(monkeypatch):
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sensitive network detail", request=request)

    client = httpx.Client(
        transport=httpx.MockTransport(fail),
        event_hooks={"request": [observe_transport_request]},
    )
    telemetry = RecordedTelemetry()
    observer = ModelTransportObserver(telemetry)
    try:
        with pytest.raises(Exception):
            _model(monkeypatch, client, observer, retries=2).invoke("private resume text")
    finally:
        client.close()

    span = telemetry.spans[-1]
    latency_ms = float(span.attributes.pop("latency_ms"))
    assert latency_ms > 0
    assert span.attributes == {
        "transport_attempt_count": 3,
        "transport_retry_count": 2,
        "outcome": "error",
        "error_type": "APIConnectionError",
        "role": "unclassified",
        "model": "observed-model",
        "input_tokens": 0,
        "output_tokens": 0,
        "token_usage_available": False,
    }
    assert span.status == "error"
    assert span.error_type == "APIConnectionError"
    assert "sensitive network detail" not in json.dumps(span.attributes)


def test_shared_observed_model_factory_counts_a_retry_for_its_stage(monkeypatch):
    import ai_service
    import openai._base_client as openai_base_client
    import recruitment_team.model_transport_observer as transport_observer

    responses = iter([httpx.Response(500), _completion()])
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: next(responses)),
        event_hooks={"request": [observe_transport_request]},
    )
    monkeypatch.setattr(openai_base_client.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ai_service, "SEALION_BASE_URL", "https://secret-provider.example/v1")
    monkeypatch.setattr(ai_service, "_get_api_key", lambda: "secret-api-key")
    monkeypatch.setattr(ai_service._limiter, "acquire", lambda **_kwargs: True)
    monkeypatch.setattr(transport_observer, "_SHARED_HTTP_CLIENT", client)
    telemetry = RecordedTelemetry()
    try:
        response = create_observed_agent_model(
            telemetry,
            role="candidate_profile",
            model="observed-model",
            max_retries=1,
        ).invoke("private resume text")
    finally:
        client.close()

    assert response.content == "ok"
    latency_ms = float(telemetry.spans[-1].attributes.pop("latency_ms"))
    assert latency_ms > 0
    assert telemetry.spans[-1].attributes == {
        "transport_attempt_count": 2,
        "transport_retry_count": 1,
        "outcome": "success",
        "role": "candidate_profile",
        "model": "observed-model",
        "input_tokens": 1,
        "output_tokens": 1,
        "token_usage_available": True,
    }


def test_default_recruitment_models_share_the_observed_factory(monkeypatch):
    import recruitment_team.candidate_profile as candidate_profile
    import recruitment_team.coordinator.model as coordinator_model
    import recruitment_team.resume_edit_evidence as resume_edit_evidence
    import recruitment_team.role_evidence_assessor as role_evidence
    import recruitment_team.role_success as role_success

    roles: list[str] = []

    class BindableModel:
        def bind_tools(self, *_args, **_kwargs):
            return self

    sentinel = BindableModel()

    def observed(_telemetry, *, role, **_kwargs):
        roles.append(role)
        return sentinel

    modules = (
        candidate_profile,
        coordinator_model,
        resume_edit_evidence,
        role_evidence,
        role_success,
    )
    for module in modules:
        monkeypatch.setattr(module, "create_observed_agent_model", observed)

    telemetry = RecordedTelemetry()
    candidate_profile.LangChainCandidateProfiler(telemetry=telemetry)
    coordinator_model.DeepAgentConversationModel(telemetry=telemetry)._build_model()
    resume_edit_evidence.LangChainResumeEditEvidenceValidator(
        telemetry=telemetry
    )._bound_model()
    role_evidence.LangChainRoleEvidenceAssessor(telemetry=telemetry)
    role_success.LangChainRoleDefinitionGenerator(telemetry=telemetry)

    assert roles == [
        "candidate_profile",
        "coordinator",
        "resume_edit_evidence",
        "role_evidence",
        "role_definition",
    ]


def test_candidate_profile_execution_event_persists_physical_transport_totals():
    metrics = merge_execution_event(
        {},
        {
            "event": "model_attempt",
            "status": "success",
            "transport_call_count": 1,
            "transport_attempt_count": 3,
            "transport_retry_count": 2,
            "transport_error_count": 0,
            "transport_by_role": {
                "candidate_profile": {
                    "call_count": 1,
                    "attempt_count": 3,
                    "retry_count": 2,
                    "error_count": 0,
                }
            },
        },
    )

    assert metrics["transport_attempt_count"] == 3
    assert metrics["transport_retry_count"] == 2
    assert metrics["transport_by_role"]["candidate_profile"]["attempt_count"] == 3


def test_default_target_runner_injects_one_observer_and_the_request_telemetry(monkeypatch):
    import resume_agent.models
    from recruitment_team.http_routes import get_target_assessment_runner

    captured = {}
    sentinel_model = object()

    def fake_create_agent_model(**kwargs):
        captured.update(kwargs)
        return sentinel_model

    monkeypatch.setattr(resume_agent.models, "create_agent_model", fake_create_agent_model)
    telemetry = RecordedTelemetry()

    runner = get_target_assessment_runner(telemetry)
    model = runner._model_factory()

    assert model is sentinel_model
    assert runner._telemetry is telemetry
    assert len(captured["callbacks"]) == 1
    assert isinstance(captured["callbacks"][0], ModelTransportObserver)
    assert captured["callbacks"][0]._telemetry is telemetry
    assert captured["http_client"] is not None


def test_transport_metrics_are_durable_role_aware_and_concurrency_isolated():
    telemetry = RecordedTelemetry()
    observer = ModelTransportObserver(telemetry, role="specialist")
    results: dict[int, dict] = {}

    def record(worker: int, attempts: int) -> None:
        with collect_transport_metrics():
            run_id = uuid4()
            observer.on_chat_model_start({}, [], run_id=run_id)
            for _ in range(attempts):
                observe_transport_request(httpx.Request("POST", "https://unused.invalid"))
            observer.on_llm_end(object(), run_id=run_id)
            results[worker] = current_transport_metrics()

    threads = [
        threading.Thread(target=record, args=(1, 2)),
        threading.Thread(target=record, args=(2, 3)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results[1]["transport_call_count"] == 1
    assert results[1]["transport_attempt_count"] == 2
    assert results[1]["transport_retry_count"] == 1
    assert results[1]["transport_error_count"] == 0
    assert results[1]["transport_input_tokens"] == 0
    assert results[1]["transport_output_tokens"] == 0
    assert results[1]["transport_token_usage_available"] is False
    assert results[1]["transport_latency_ms"] >= 0
    assert results[1]["transport_models"] == []
    assert results[1]["transport_observations"][0]["observation_id"]
    assert (
        results[1]["transport_observations"][0]["observation_id"]
        != results[2]["transport_observations"][0]["observation_id"]
    )
    assert results[1]["transport_by_role"]["specialist"] == {
        "call_count": 1,
        "attempt_count": 2,
        "retry_count": 1,
        "error_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "token_usage_available": False,
        "latency_ms": results[1]["transport_by_role"]["specialist"]["latency_ms"],
        "models": [],
    }
    assert results[2]["transport_attempt_count"] == 3
    assert results[2]["transport_retry_count"] == 2


def test_run_owned_model_binding_routes_precompiled_subagent_threads():
    telemetry = RecordedTelemetry()
    observer = ModelTransportObserver(telemetry, role="coordinator")
    model = SimpleNamespace(callbacks=[observer])

    with collect_transport_metrics() as collector:
        with bind_transport_collector(model, collector):
            def record_specialist() -> None:
                run_id = uuid4()
                observer.on_chat_model_start(
                    {},
                    [],
                    run_id=run_id,
                    tags=["transport_role:specialist:recruiter"],
                )
                observe_transport_request(httpx.Request("POST", "https://unused.invalid"))
                observer.on_llm_end(object(), run_id=run_id)

            thread = threading.Thread(target=record_specialist)
            thread.start()
            thread.join()
        summary = current_transport_metrics()

    assert summary["transport_by_role"]["specialist:recruiter"]["call_count"] == 1


def test_code_owned_stage_overrides_factory_role_in_durable_metrics():
    telemetry = RecordedTelemetry()
    observer = ModelTransportObserver(telemetry, role="quality_judge")
    with collect_transport_metrics():
        with transport_role("target_assessment_rejudge"):
            run_id = uuid4()
            observer.on_chat_model_start({}, [], run_id=run_id)
            observe_transport_request(httpx.Request("POST", "https://unused.invalid"))
            observer.on_llm_end(object(), run_id=run_id)
        summary = current_transport_metrics()

    role_metrics = summary["transport_by_role"]["target_assessment_rejudge"]
    assert role_metrics == {
        "call_count": 1,
        "attempt_count": 1,
        "retry_count": 0,
        "error_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "token_usage_available": False,
        "latency_ms": role_metrics["latency_ms"],
        "models": [],
    }
    assert telemetry.spans[-1].attributes["role"] == "target_assessment_rejudge"


def test_resume_edit_validator_call_emits_content_free_semantic_attempt():
    telemetry = RecordedTelemetry()
    observer = ModelTransportObserver(telemetry, role="resume_edit_evidence")
    run_id = uuid4()
    message = SimpleNamespace(
        usage_metadata={"input_tokens": 41, "output_tokens": 7},
        response_metadata={"model_name": "evidence-model"},
    )
    response = SimpleNamespace(
        generations=[[SimpleNamespace(message=message)]],
        llm_output={},
    )

    with collect_transport_metrics():
        observer.on_chat_model_start({}, [], run_id=run_id)
        observe_transport_request(httpx.Request("POST", "https://unused.invalid"))
        observer.on_llm_end(response, run_id=run_id)
        summary = current_transport_metrics()

    assert summary["nested_model_attempts"] == [{
        "attempt_id": f"resume_edit_evidence:{run_id}",
        "stage": "resume_edit_evidence",
        "team_member": "resume_edit_evidence",
        "model": "evidence-model",
        "input_tokens": 41,
        "output_tokens": 7,
        "token_usage_available": True,
        "latency_ms": summary["nested_model_attempts"][0]["latency_ms"],
        "attempt_count": 1,
        "status": "success",
    }]
    assert summary["transport_input_tokens"] == 41
    assert summary["transport_output_tokens"] == 7
    assert summary["transport_token_usage_available"] is True
    assert summary["transport_models"] == ["evidence-model"]
    assert summary["transport_by_role"]["resume_edit_evidence"]["models"] == [
        "evidence-model"
    ]
    assert "private" not in json.dumps(summary)


def test_terminal_exception_carries_only_safe_transport_totals():
    telemetry = RecordedTelemetry()
    observer = ModelTransportObserver(telemetry, role="coordinator")

    with pytest.raises(RuntimeError) as caught:
        with collect_transport_metrics():
            run_id = uuid4()
            observer.on_chat_model_start({}, [], run_id=run_id)
            for _ in range(3):
                observe_transport_request(httpx.Request("POST", "https://secret.invalid"))
            observer.on_llm_error(RuntimeError("private provider response"), run_id=run_id)
            raise RuntimeError("private provider response")

    metrics = caught.value.recruitment_transport_metrics
    assert metrics["transport_attempt_count"] == 3
    assert metrics["transport_retry_count"] == 2
    assert metrics["transport_error_count"] == 1
    serialized = json.dumps(metrics)
    assert "secret.invalid" not in serialized
    assert "private provider response" not in serialized
