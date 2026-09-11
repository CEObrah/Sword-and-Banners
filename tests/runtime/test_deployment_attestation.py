from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sword_runtime.deployment_attestation import (
    DeploymentCompatibilityError,
    assert_deployment_compatible,
    deployment_attestation,
    public_deployment_health,
)


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "deployment@example.invalid")
    git(root, "config", "user.name", "Deployment Test")
    (root / "state").mkdir()
    (root / "runtime" / "sword_runtime").mkdir(parents=True)
    (root / "game").mkdir()
    (root / "state" / "meta.json").write_text('{"revision":1}\n', encoding="utf-8")
    (root / "runtime" / "sword_runtime" / "engine.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "game" / "rules.json").write_text('{}\n', encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    return root, git(root, "rev-parse", "HEAD")


def commit(root: Path, path: str, text: str, message: str) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(root, "add", path)
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


def railway_env(source_sha: str) -> dict[str, str]:
    return {
        "RAILWAY_GIT_COMMIT_SHA": source_sha,
        "RAILWAY_DEPLOYMENT_ID": "deployment-test",
        "SWORD_GIT_REMOTE": "origin",
        "SWORD_GIT_BRANCH": "main",
    }


def test_state_only_checkout_advance_is_safe_for_existing_image(tmp_path: Path) -> None:
    root, source_sha = repository(tmp_path)
    commit(root, "state/meta.json", '{"revision":2}\n', "gameplay state")

    result = deployment_attestation(root, railway_env(source_sha))

    assert result["source_compatible"] is True
    assert result["deployment_required"] is False
    assert result["source_sync_status"] == "checkout_ahead_runtime_neutral"
    assert result["incompatible_paths"] == []


def test_runtime_change_requires_new_deployment_and_fails_startup_guard(tmp_path: Path) -> None:
    root, source_sha = repository(tmp_path)
    commit(root, "runtime/sword_runtime/engine.py", "VALUE = 2\n", "runtime change")

    result = deployment_attestation(root, railway_env(source_sha))

    assert result["source_compatible"] is False
    assert result["deployment_required"] is True
    assert result["source_sync_status"] == "deployment_source_behind"
    assert result["incompatible_paths"] == ["runtime/sword_runtime/engine.py"]
    with pytest.raises(DeploymentCompatibilityError, match="deployment_source_behind"):
        assert_deployment_compatible(root, railway_env(source_sha))


def test_game_dependency_or_deployment_configuration_changes_are_not_neutral(tmp_path: Path) -> None:
    root, source_sha = repository(tmp_path)
    commit(root, "game/rules.json", '{"changed":true}\n', "game rule")
    commit(root, "requirements.txt", "example==1\n", "dependency")
    commit(root, "railway.toml", "[deploy]\n", "deployment config")

    result = deployment_attestation(root, railway_env(source_sha))

    assert result["deployment_required"] is True
    assert set(result["incompatible_paths"]) == {"game/rules.json", "requirements.txt", "railway.toml"}


def test_skill_docs_tests_and_ci_changes_do_not_force_runtime_image(tmp_path: Path) -> None:
    root, source_sha = repository(tmp_path)
    commit(root, "plugins/sword-and-banners/skill/sword-and-banners-game-master/SKILL.md", "skill\n", "skill")
    commit(root, "docs/note.md", "docs\n", "docs")
    commit(root, "tests/runtime/test_placeholder.py", "def test_ok(): assert True\n", "test")
    commit(root, ".github/workflows/check.yml", "name: test\n", "ci")

    result = deployment_attestation(root, railway_env(source_sha))

    assert result["source_compatible"] is True
    assert result["deployment_required"] is False


def test_unattested_local_environment_remains_developer_usable(tmp_path: Path) -> None:
    root, _source_sha = repository(tmp_path)

    result = assert_deployment_compatible(root, {})
    health = public_deployment_health(root, {})

    assert result["platform"] == "unattested_environment"
    assert result["source_compatible"] is True
    assert result["source_sync_status"] == "image_source_not_advertised"
    assert health["status"] == "ok"
    assert health["deployment_required"] is False


def test_public_health_exposes_only_bounded_source_fingerprint(tmp_path: Path) -> None:
    root, source_sha = repository(tmp_path)

    health = public_deployment_health(root, railway_env(source_sha))

    assert health == {
        "status": "ok",
        "source_sync": "exact",
        "image_source": source_sha[:12],
        "checkout": source_sha[:12],
        "deployment_required": False,
    }
