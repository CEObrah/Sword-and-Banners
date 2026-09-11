from __future__ import annotations

import re
import runpy
import subprocess
import sys

import pytest
from pathlib import Path
from sword_runtime.gm_skill_contract import (
    GM_SKILL_CONTRACT_TOKEN,
    verified_delivery_integrity,
    verify_gm_skill_contract_token,
)
from sword_runtime.deployment_attestation import DeploymentCompatibilityError, assert_deployment_compatible
from tools.verify_release_state import verify_release_state

ROOT = Path(__file__).resolve().parents[2]



def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return completed.stdout.strip()


def _deployment_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    (root / "state").mkdir(parents=True)
    (root / "runtime" / "sword_runtime").mkdir(parents=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Sword Playability")
    (root / "state/meta.json").write_text('{"revision":1}\n', encoding="utf-8")
    (root / "runtime/sword_runtime/engine.py").write_text("BUILD = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")
    return root, _git(root, "rev-parse", "HEAD")


def test_packaged_skill_fingerprint_is_synchronized():
    completed = subprocess.run(
        [sys.executable, "tools/sync_gm_skill_contract.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_get_play_context_fails_closed_for_missing_or_stale_skill_token():
    assert verify_gm_skill_contract_token(None) is False
    assert verify_gm_skill_contract_token("f" * 64) is False
    assert verify_gm_skill_contract_token(GM_SKILL_CONTRACT_TOKEN) is True
    integrity = verified_delivery_integrity()
    assert integrity["gm_skill_contract_verified"] is True
    assert "gm_skill_contract_token" not in repr(integrity)

    # Actual exported schemas and transport calls are exercised in
    # tests/runtime/test_mcp_live_boundary.py with the pinned service SDK.


def test_deployment_docs_cannot_drift_from_railway_start_command_again():
    railway = (ROOT / "railway.toml").read_text(encoding="utf-8")
    match = re.search(r'^startCommand = "([^"]+)"$', railway, flags=re.MULTILINE)
    assert match is not None
    command = match.group(1)
    assert command == "PYTHONPATH=/app/runtime python -m sword_runtime.branch_bootstrap"

    for rel in ("docs/RUNTIME_SERVICE_DEPLOYMENT.md", "docs/RAILWAY_IAC_MIGRATION.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert command in text
        assert "python -m sword_runtime.bootstrap` start command" not in text


def test_release_candidate_still_matches_its_pinned_campaign_baseline():
    assert verify_release_state(ROOT) == []


def test_app_entrypoint_calls_deployment_guard_before_runtime_recovery():
    source = (ROOT / "runtime/sword_runtime/api/app.py").read_text(encoding="utf-8")
    guard = source.index("assert_deployment_compatible(campaign_root)")
    recovery = source.index("app = create_app(campaign_root, token, Path(runtime_root), recover=True)")
    assert guard < recovery


def test_changed_path_router_sends_deployment_runbooks_to_delivery_regressions():
    policy = runpy.run_path(str(ROOT / "tools/test_changed.py"))
    selected = set(policy["select"]([
        "docs/RUNTIME_SERVICE_DEPLOYMENT.md",
        "docs/RAILWAY_IAC_MIGRATION.md",
    ]))
    assert "tests/playability/test_delivery_chain_contract.py" in selected
    assert "tests/runtime/test_deployment_attestation.py" in selected


def test_resumable_release_evidence_is_invalidated_by_deployment_runbook_changes():
    policy = runpy.run_path(str(ROOT / "tools/run_release_suite.py"))
    certified = set(policy["CERTIFIED_TOP_LEVEL_FILES"])
    assert "docs/RUNTIME_SERVICE_DEPLOYMENT.md" in certified
    assert "docs/RAILWAY_IAC_MIGRATION.md" in certified


def test_changed_path_router_covers_release_lineage_owners():
    policy = runpy.run_path(str(ROOT / "tools/test_changed.py"))
    for changed in (
        "runtime/sword_runtime/branch_bootstrap.py",
        "runtime/contracts/release-campaign-state.json",
    ):
        selected = set(policy["select"]([changed]))
        assert "tests/runtime/test_branch_bootstrap.py" in selected
        assert "tests/playability/test_delivery_chain_contract.py" in selected


def test_release_runner_discovers_playability_and_runs_mutation_audit():
    source = (ROOT / "tools/run_release_suite.py").read_text(encoding="utf-8")
    assert 'ROOT / "tests/playability"' in source
    assert '"tests/playability"' in source
    assert "_run_mutation_audit()" in source



def test_production_deployment_guard_rejects_stale_runtime_image(tmp_path: Path):
    root, source_sha = _deployment_repo(tmp_path)
    (root / "runtime/sword_runtime/engine.py").write_text("BUILD = 2\n", encoding="utf-8")
    _git(root, "add", "runtime/sword_runtime/engine.py")
    _git(root, "commit", "-m", "source ahead")
    env = {
        "RAILWAY_GIT_COMMIT_SHA": source_sha,
        "SWORD_GIT_REMOTE": "origin",
        "SWORD_GIT_BRANCH": "main",
    }
    with pytest.raises(DeploymentCompatibilityError, match="deployment_source_behind"):
        assert_deployment_compatible(root, env)
    assert assert_deployment_compatible(root, {})["source_compatible"] is True


def test_split_campaign_branch_still_tracks_original_source_branch_for_stale_image_detection(tmp_path: Path):
    root, source_sha = _deployment_repo(tmp_path)
    _git(root, "branch", "campaign/test", source_sha)
    _git(root, "checkout", "campaign/test")
    (root / "state/meta.json").write_text('{"revision":2}\n', encoding="utf-8")
    _git(root, "add", "state/meta.json")
    _git(root, "commit", "-m", "campaign state")
    campaign_head = _git(root, "rev-parse", "HEAD")

    _git(root, "checkout", "main")
    (root / "runtime/sword_runtime/engine.py").write_text("BUILD = 2\n", encoding="utf-8")
    _git(root, "add", "runtime/sword_runtime/engine.py")
    _git(root, "commit", "-m", "new source runtime")
    source_head = _git(root, "rev-parse", "HEAD")

    # Model branch_bootstrap's fetched remote refs, then leave the persistent
    # checkout on the durability branch exactly as production does before the
    # ASGI startup guard runs.
    _git(root, "update-ref", "refs/remotes/origin/main", source_head)
    _git(root, "update-ref", "refs/remotes/origin/campaign/test", campaign_head)
    _git(root, "checkout", "campaign/test")

    env = {
        "RAILWAY_GIT_COMMIT_SHA": source_sha,
        "SWORD_GIT_REMOTE": "origin",
        "SWORD_GIT_BRANCH": "campaign/test",
        "SWORD_SOURCE_BRANCH": "main",
    }
    with pytest.raises(DeploymentCompatibilityError, match="deployment_source_behind"):
        assert_deployment_compatible(root, env)
