from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_web_service_keeps_process_local_workflows_on_one_worker_and_replica():
    config = tomllib.loads((ROOT / "railway.toml").read_text())

    assert config["deploy"]["startCommand"] == "python main.py"
    regions = config["deploy"]["multiRegionConfig"]
    assert regions == {"asia-southeast1-eqsg3a": {"numReplicas": 1}}


def test_scheduled_alert_image_runs_as_non_root():
    dockerfile = (ROOT / "Dockerfile.alerts").read_text()

    assert "useradd --create-home --uid 10001 --user-group appuser" in dockerfile
    assert "COPY --chown=appuser:appuser backend/ ." in dockerfile
    assert "USER appuser" in dockerfile


def test_full_crawl_service_runs_the_versioned_cli_to_completion():
    config = tomllib.loads((ROOT / "railway.seed.toml").read_text())

    assert config["build"] == {
        "builder": "dockerfile",
        "dockerfilePath": "Dockerfile",
    }
    assert config["deploy"] == {
        "startCommand": "python seed_jobs.py --full",
        "cronSchedule": "0 22 * * *",
        "restartPolicyType": "never",
    }
