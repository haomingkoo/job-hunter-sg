import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.resolve_production_release import resolve_release_sha


ENVIRONMENT = "victorious-rejoicing / production"
NEW = "65441d85588bdd3e69bdccd283bd756c07294e17"  # pragma: allowlist secret (Git commit SHA)
OLD = "1082c5be74d736d120373ac5da7f36074741cd4c"  # pragma: allowlist secret (Git commit SHA)
OLDER = "31e28c06cf185b40cea0ab5d3243a46ece236ccc"  # pragma: allowlist secret (Git commit SHA)
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve_production_release.py"

# The three newest production deployments on 2026-11-14, as GitHub returns them.
# On 2026-11-12 Railway posted `success` on the OLD deployment while NEW went live.
RECORDED_DEPLOYMENTS = [
    {"sha": NEW, "environment": ENVIRONMENT, "created_at": "2026-11-11T20:48:22Z"},
    {"sha": OLD, "environment": ENVIRONMENT, "created_at": "2026-10-30T18:34:31Z"},
    {"sha": OLDER, "environment": ENVIRONMENT, "created_at": "2026-10-30T16:52:06Z"},
]


def test_a_status_on_a_superseded_deployment_resolves_to_the_newest_release():
    assert resolve_release_sha(RECORDED_DEPLOYMENTS, ENVIRONMENT) == NEW


def test_resolution_uses_creation_time_not_response_order():
    shuffled = [RECORDED_DEPLOYMENTS[1], RECORDED_DEPLOYMENTS[2], RECORDED_DEPLOYMENTS[0]]

    assert resolve_release_sha(shuffled, ENVIRONMENT) == NEW


def test_deployments_from_another_environment_are_not_the_release():
    staging_newer = {
        "sha": "c" * 40,
        "environment": "victorious-rejoicing / staging",
        "created_at": "2026-11-13T00:00:00Z",
    }

    assert resolve_release_sha([staging_newer, *RECORDED_DEPLOYMENTS], ENVIRONMENT) == NEW


def test_no_production_deployment_fails_instead_of_guessing():
    with pytest.raises(RuntimeError, match="no deployments"):
        resolve_release_sha([], ENVIRONMENT)


def test_a_malformed_release_sha_fails():
    broken = [{"sha": "65441d8", "environment": ENVIRONMENT, "created_at": "2026-11-11T20:48:22Z"}]

    with pytest.raises(RuntimeError, match="full lowercase Git SHA"):
        resolve_release_sha(broken, ENVIRONMENT)


def test_cli_reads_github_api_json_and_prints_only_the_sha():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), ENVIRONMENT],
        input=json.dumps(RECORDED_DEPLOYMENTS),
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout == f"{NEW}\n"
