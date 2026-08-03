"""Run the Candidate Evidence Profile against one local resume PDF."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from recruitment_team.candidate_profile import (  # noqa: E402
    CandidateProfileCheckpointStore,
    CandidateProfileTransportError,
    CandidateProfileValidationError,
    LangChainCandidateProfilerFactory,
    candidate_profile_execution_policy,
)
from recruitment_team.execution_metrics import merge_execution_event  # noqa: E402
from recruitment_team.telemetry import RecordedTelemetry  # noqa: E402
from resume_document import create_resume_document  # noqa: E402
from resume_parser import parse_resume_isolated  # noqa: E402


def _output_path(resume_path: Path, requested: str) -> Path:
    if requested:
        return Path(requested).expanduser().resolve()
    return resume_path.with_suffix(".candidate-profile.json")


class JsonCandidateProfileCheckpointStore(CandidateProfileCheckpointStore):
    """Local, explicit checkpoint file for resumable real-resume canaries."""

    def __init__(self, path: Path | None, execution_policy: dict):
        self.path = path
        self.execution_policy = execution_policy
        self._memory: dict | None = None

    def _read(self, checkpoint_id: str) -> dict:
        if self.path is None and self._memory is not None:
            payload = self._memory
        elif self.path is None or not self.path.exists():
            return {
                "checkpoint_id": checkpoint_id,
                "execution_policy": self.execution_policy,
                "scopes": {},
                "retry_feedback": {},
                "execution_metrics": {},
            }
        else:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        stored_id = payload.get("checkpoint_id")
        if stored_id != checkpoint_id:
            raise ValueError(
                "Candidate profile checkpoint identity does not match this resume, prompt, and model configuration"
            )
        if payload.get("execution_policy") != self.execution_policy:
            raise ValueError("Candidate profile checkpoint execution policy does not match")
        scopes = payload.get("scopes")
        if not isinstance(scopes, dict):
            raise ValueError("Candidate profile checkpoint scopes must be an object")
        if not isinstance(payload.get("retry_feedback", {}), dict):
            raise ValueError("Candidate profile checkpoint retry feedback must be an object")
        if not isinstance(payload.get("execution_metrics", {}), dict):
            raise ValueError("Candidate profile checkpoint execution metrics must be an object")
        return payload

    def _write(self, document: dict) -> None:
        if self.path is None:
            self._memory = document
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def load(self, checkpoint_id: str) -> dict[str, dict]:
        return dict(self._read(checkpoint_id)["scopes"])

    def save(self, checkpoint_id: str, scope_id: str, payload: dict) -> None:
        document = self._read(checkpoint_id)
        scopes = dict(document["scopes"])
        scopes[scope_id] = payload
        document["scopes"] = scopes
        self._write(document)

    def load_retry_feedback(self, checkpoint_id: str, scope_id: str) -> dict | None:
        value = self._read(checkpoint_id).get("retry_feedback", {}).get(scope_id)
        return dict(value) if isinstance(value, dict) else None

    def save_retry_feedback(
        self,
        checkpoint_id: str,
        scope_id: str,
        feedback: dict,
    ) -> None:
        document = self._read(checkpoint_id)
        retry_feedback = dict(document.get("retry_feedback") or {})
        retry_feedback[scope_id] = feedback
        document["retry_feedback"] = retry_feedback
        self._write(document)

    def clear_retry_feedback(self, checkpoint_id: str, scope_id: str) -> None:
        document = self._read(checkpoint_id)
        retry_feedback = dict(document.get("retry_feedback") or {})
        if scope_id not in retry_feedback:
            return
        retry_feedback.pop(scope_id)
        document["retry_feedback"] = retry_feedback
        self._write(document)

    def record_execution_event(self, checkpoint_id: str, event: dict) -> None:
        document = self._read(checkpoint_id)
        document["execution_metrics"] = merge_execution_event(
            document.get("execution_metrics"),
            {**event, "logical_run_id": checkpoint_id},
        )
        self._write(document)

    def execution_metrics(self, checkpoint_id: str) -> dict:
        return dict(self._read(checkpoint_id).get("execution_metrics") or {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-pdf", required=True, help="Local resume PDF to profile.")
    parser.add_argument("--output", default="", help="Path for the complete JSON report.")
    parser.add_argument(
        "--checkpoint",
        default="",
        help="Explicit local JSON checkpoint path. Omit to disable checkpoint reuse.",
    )
    args = parser.parse_args(argv)

    resume_path = Path(args.resume_pdf).expanduser().resolve()
    output_path = _output_path(resume_path, args.output)
    checkpoint_path = Path(args.checkpoint).expanduser().resolve() if args.checkpoint else None
    if checkpoint_path == output_path:
        parser.error("--checkpoint and --output must be different paths")
    execution_policy = candidate_profile_execution_policy()
    checkpoint_store = JsonCandidateProfileCheckpointStore(checkpoint_path, execution_policy)
    telemetry = RecordedTelemetry()
    report = {
        "status": "failed",
        "resume_pdf": str(resume_path),
        "parse_report": None,
        "execution_policy": {**execution_policy, "checkpoint_enabled": checkpoint_path is not None},
        "run": None,
        "profile": None,
        "evaluation": None,
        "error": None,
        "spans": [],
        "checkpoint": {
            "path": str(checkpoint_path) if checkpoint_path is not None else None,
            "completed_scope_ids": [],
        },
    }

    try:
        parsed = parse_resume_isolated(
            resume_path.name,
            "application/pdf",
            resume_path.read_bytes(),
        )
        parsed_document = parsed["document"]
        document = create_resume_document(
            str(parsed["text"]),
            source_format=str(parsed["file_type"]),
            filename=resume_path.name,
            source_sha256=str((parsed_document.get("source") or {}).get("sha256") or "") or None,
            warnings=list(parsed_document.get("warnings") or []),
        )
        report["parse_report"] = {
            "filename": parsed["filename"],
            "file_type": parsed["file_type"],
            "word_count": parsed["word_count"],
            "line_count": parsed["line_count"],
            "page_estimate": parsed["page_estimate"],
            "parse_quality": parsed["parse_quality"],
            "content_warnings": parsed["content_warnings"],
            "document_block_count": len(document["blocks"]),
        }
        run = LangChainCandidateProfilerFactory(telemetry=telemetry).create(
            checkpoint_store
        ).profile(document)
        report["status"] = "completed"
        report["run"] = {
            "model_name": run.model_name,
            "attempt_count": run.attempt_count,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "validation_codes": list(run.validation_codes),
            "scope_count": run.scope_count,
            "model_call_count": run.model_call_count,
            "checkpoint_hit_count": run.checkpoint_hit_count,
            "checkpoint_id": run.checkpoint_id,
        }
        report["profile"] = asdict(run.profile)
        report["evaluation"] = run.evaluation
    except CandidateProfileValidationError as error:
        failure_code = "information_absent" if error.validation_code == "profile:empty" else "semantic_fixable"
        report["error"] = {
            "type": type(error).__name__,
            "message": str(error),
            "failure_type": "validation",
            "failure_code": failure_code,
            "retryable": False,
            "validation_code": error.validation_code,
            "rejected_submission": error.rejected_submission,
            "attempt_count": error.attempt_count,
            "model_name": error.model_name,
            "input_tokens": error.input_tokens,
            "output_tokens": error.output_tokens,
            "validation_codes": list(error.validation_codes),
            "checkpoint_id": error.checkpoint_id,
            "completed_scope_ids": list(error.completed_scope_ids),
        }
    except CandidateProfileTransportError as error:
        report["error"] = {
            "type": type(error).__name__,
            "message": str(error),
            "failure_type": "transient",
            "failure_code": error.failure_code,
            "retryable": False,
            "cause_type": error.cause_type,
            "failed_scope_id": error.scope_id,
            "attempt": error.attempt,
            "completed_scope_ids": list(error.completed_scope_ids),
            "checkpoint_id": error.checkpoint_id,
            "model_call_count": error.model_call_count,
            "input_tokens": error.input_tokens,
            "output_tokens": error.output_tokens,
            "recovery": "Resume with the same explicit checkpoint path.",
        }
    except Exception as error:
        report["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    finally:
        report["spans"] = [asdict(span) for span in telemetry.spans]
        if checkpoint_path is not None and checkpoint_path.exists():
            checkpoint_document = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            report["checkpoint"]["completed_scope_ids"] = sorted((checkpoint_document.get("scopes") or {}).keys())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(output_path),
                "fields": len((report["profile"] or {}).get("fields") or []),
                "spans": len(report["spans"]),
            },
            separators=(",", ":"),
        )
    )
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
