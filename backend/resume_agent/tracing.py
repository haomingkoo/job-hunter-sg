"""Redacted first-party spans for resume-agent model and tool calls."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


log = logging.getLogger("jobhunter.resume_agent")


class ToolSpanRecorder(BaseCallbackHandler):
    """Record model/tool performance without prompts, outputs, or secrets."""

    def __init__(
        self,
        worker: str = "orchestrator",
        *,
        trace_id: str = "",
        attempt: int | None = None,
    ) -> None:
        self.worker = worker
        self.trace_id = trace_id
        self.attempt = attempt
        self.phase = "orchestrator"
        self.spans: list[dict] = []
        self.source_job_ids: set[int] = set()
        self._active_tools: dict[str, tuple[int, float]] = {}
        self._active_models: dict[str, tuple[int, float]] = {}

    def set_phase(self, phase: str) -> None:
        self.phase = phase

    def _base_span(self, kind: str, name: str) -> dict:
        return {
            "kind": kind,
            "trace_id": self.trace_id,
            "worker": self.worker,
            "attempt": self.attempt,
            "phase": self.phase,
            "name": name,
            "status": "running",
            "duration_ms": None,
            "input_keys": [],
            "result": {},
        }

    def on_tool_start(self, serialized, _input_str, *, run_id, inputs=None, **kwargs) -> None:
        name = str((serialized or {}).get("name") or kwargs.get("name") or "tool")
        span = self._base_span("tool", name)
        span["input_keys"] = (
            sorted(str(key) for key in inputs) if isinstance(inputs, dict) else []
        )
        self.spans.append(span)
        self._active_tools[str(run_id)] = (len(self.spans) - 1, time.perf_counter())

    def on_tool_end(self, output, *, run_id, **_kwargs) -> None:
        self._finish_tool(run_id, "success", output)

    def on_tool_error(self, error, *, run_id, **_kwargs) -> None:
        self._finish_tool(run_id, "error", {"error": type(error).__name__})

    def on_chat_model_start(self, serialized, _messages, *, run_id, **kwargs) -> None:
        self._start_model(serialized, run_id, kwargs)

    def on_llm_start(self, serialized, _prompts, *, run_id, **kwargs) -> None:
        self._start_model(serialized, run_id, kwargs)

    def on_llm_end(self, response, *, run_id, **_kwargs) -> None:
        self._finish_model(run_id, "success", response)

    def on_llm_error(self, error, *, run_id, **_kwargs) -> None:
        self._finish_model(run_id, "error", error)

    def _start_model(self, serialized, run_id, kwargs: dict) -> None:
        key = str(run_id)
        if key in self._active_models:
            return
        params = kwargs.get("invocation_params") or {}
        name = str(
            params.get("model_name")
            or params.get("model")
            or (serialized or {}).get("name")
            or "language_model"
        )
        self.spans.append(self._base_span("llm", name))
        self._active_models[key] = (len(self.spans) - 1, time.perf_counter())

    def _finish_tool(self, run_id, status: str, output: Any) -> None:
        active = self._active_tools.pop(str(run_id), None)
        if not active:
            return
        index, started_at = active
        span = self.spans[index]
        span["status"] = status
        span["duration_ms"] = round((time.perf_counter() - started_at) * 1000)
        value = self._payload(output)
        if isinstance(value, dict) and isinstance(value.get("query"), str):
            span["attempted_query"] = value["query"]
        self._collect_job_ids(value)
        span["result"] = self._tool_summary(value)
        self._log_span(span)

    def _finish_model(self, run_id, status: str, response: Any) -> None:
        active = self._active_models.pop(str(run_id), None)
        if not active:
            return
        index, started_at = active
        span = self.spans[index]
        span["status"] = status
        span["duration_ms"] = round((time.perf_counter() - started_at) * 1000)
        span["result"] = self._model_summary(response)
        self._log_span(span)

    @staticmethod
    def _log_span(span: dict) -> None:
        log.info("resume_agent_span %s", json.dumps(span, separators=(",", ":")))

    @staticmethod
    def _payload(output: Any) -> Any:
        value = getattr(output, "content", output)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def _collect_job_ids(self, value: Any) -> None:
        if not isinstance(value, dict):
            return
        jobs = value.get("results")
        if not isinstance(jobs, list):
            job = value.get("job")
            jobs = [job] if isinstance(job, dict) else []
        for job in jobs:
            if isinstance(job, dict) and isinstance(job.get("id"), int):
                self.source_job_ids.add(job["id"])

    @staticmethod
    def _tool_summary(value: Any) -> dict:
        if isinstance(value, list):
            return {"count": len(value)}
        if not isinstance(value, dict):
            return {}
        summary = {
            key: value[key]
            for key in (
                "ok",
                "accepted",
                "overall_score",
                "matched",
                "total",
                "count",
                "found",
                "query_executed",
                "result_count",
                "retryable",
            )
            if isinstance(value.get(key), (bool, int, float))
        }
        if isinstance(value.get("failure_type"), str):
            summary["failure_type"] = value["failure_type"]
        error = value.get("error")
        if isinstance(error, dict) and error.get("code"):
            summary["error_code"] = str(error["code"])
        return summary

    @staticmethod
    def _model_summary(response: Any) -> dict:
        llm_output = getattr(response, "llm_output", None) or {}
        usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
        summary: dict[str, Any] = {}
        for source, target in (
            ("prompt_tokens", "input_tokens"),
            ("input_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
            ("output_tokens", "output_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            if isinstance(usage.get(source), int):
                summary[target] = usage[source]
        model = llm_output.get("model_name") or llm_output.get("model")
        if isinstance(model, str):
            summary["model"] = model
        return summary

    _summarize = _tool_summary
