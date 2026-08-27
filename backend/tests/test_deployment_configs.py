from __future__ import annotations

import json
import tomllib
from pathlib import Path

from embedding_service import EMBEDDING_MODEL_NAME, EMBEDDING_MODEL_REVISION


ROOT = Path(__file__).resolve().parents[2]


def test_legacy_railway_config_paths_are_empty_compatibility_stubs():
    for filename in ("railway.toml", "railway.seed.toml", "railway.alerts.toml"):
        assert tomllib.loads((ROOT / filename).read_text()) == {}


def test_web_service_keeps_process_local_workflows_on_one_worker_and_replica():
    infrastructure = (ROOT / ".railway" / "railway.ts").read_text()

    assert 'start: "python main.py"' in infrastructure
    assert 'healthcheck: "/api/health"' in infrastructure
    assert 'replicas: { "asia-southeast1-eqsg3a": 1 }' in infrastructure


def test_scheduled_alert_image_runs_as_non_root():
    dockerfile = (ROOT / "Dockerfile.alerts").read_text()

    assert "useradd --create-home --uid 10001 --user-group appuser" in dockerfile
    assert "COPY --chown=appuser:appuser backend/ ." in dockerfile
    assert "USER appuser" in dockerfile


def test_full_crawl_service_runs_the_versioned_cli_to_completion():
    dockerfile = (ROOT / "Dockerfile.crawler").read_text()
    infrastructure = (ROOT / ".railway" / "railway.ts").read_text()

    assert (
        'CMD ["/bin/sh", "-c", "python seed_jobs.py --full && '
        'python backfill_embeddings.py"]'
    ) in dockerfile
    assert "USER appuser" in dockerfile
    assert "ENV HF_HUB_OFFLINE=1" in dockerfile
    assert "TRANSFORMERS_OFFLINE=1" in dockerfile
    assert 'dockerfilePath: "Dockerfile.crawler"' in infrastructure
    assert 'cronSchedule: "0 22 * * *"' in infrastructure


def test_images_and_ranking_gate_pin_the_runtime_embedding_model():
    expected = f"SentenceTransformer('{EMBEDDING_MODEL_NAME}', revision='{EMBEDDING_MODEL_REVISION}')"
    assert expected in (ROOT / "Dockerfile").read_text()
    assert expected in (ROOT / "Dockerfile.crawler").read_text()

    manifest = json.loads((ROOT / "backend/evals/job-ranking-v1.json").read_text())
    assert manifest["model"] == EMBEDDING_MODEL_NAME
    assert manifest["model_revision"] == EMBEDDING_MODEL_REVISION
