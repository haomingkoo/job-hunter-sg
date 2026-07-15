"""Redacted tool traces shared by resume agents and reviewer workers."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


log = logging.getLogger("jobhunter.resume_agent")


class ToolSpanRecorder(BaseCallbackHandler):
    """Keep safe tool timing, status, and internal job citation data."""

    def __init__(self, worker: str = "orchestrator") -> None:
        self.worker = worker
        self.spans: list[dict] = []
        self.source_job_ids: set[int] = set()
        self._active: dict[str, tuple[int, float]] = {}

    def on_tool_start(self, serialized, _input_str, *, run_id, inputs=None, **kwargs) -> None:
        name = str((serialized or {}).get("name") or kwargs.get("name") or "tool")
        span = {
            "worker": self.worker,
            "name": name,
            "status": "running",
            "duration_ms": None,
            "input_keys": sorted(str(key) for key in inputs) if isinstance(inputs, dict) else [],
            "result": {},
        }
        self.spans.append(span)
        self._active[str(run_id)] = (len(self.spans) - 1, time.perf_counter())

    def on_tool_end(self, output, *, run_id, **_kwargs) -> None:
        self._finish(run_id, "success", output)

    def on_tool_error(self, error, *, run_id, **_kwargs) -> None:
        self._finish(run_id, "error", {"error": type(error).__name__})

    def _finish(self, run_id, status: str, output: Any) -> None:
        active = self._active.pop(str(run_id), None)
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
        span["result"] = self._summarize(value)
        log.info(
            "resume agent tool span worker=%s name=%s status=%s duration_ms=%s",
            self.worker,
            span["name"],
            status,
            span["duration_ms"],
        )

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
    def _summarize(value: Any) -> dict:
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
