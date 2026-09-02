from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sword_runtime.tx.errors import RemoteDivergenceError
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.remote import GitRemoteDurability


def _run(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _commit(repo: Path, path: str, content: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _run(repo, "add", "--", path)
    _run(repo, "commit", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


def _seed_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    publisher = tmp_path / "publisher"
    worker = tmp_path / "worker"
    remote.mkdir()
    publisher.mkdir()
    _run(remote, "init", "--bare")
    _run(publisher, "init")
    _run(publisher, "checkout", "-b", "main")
    _run(publisher, "config", "user.name", "Sword Test")
    _run(publisher, "config", "user.email", "sword-test@invalid")
    _commit(publisher, "state/meta.json", '{"revision": 1}\n', "seed campaign")
    _run(publisher, "remote", "add", "origin", str(remote))
    _run(publisher, "push", "-u", "origin", "main")
    completed = subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(worker)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return remote, publisher, worker


def test_preflight_fast_forwards_runtime_neutral_remote_descendant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SWORD_GIT_TOKEN", raising=False)
    _, publisher, worker = _seed_pair(tmp_path)
    original_state = (worker / "state/meta.json").read_text(encoding="utf-8")
    neutral_path = (
        "plugins/sword-and-banners/skill/sword-and-banners-game-master/"
        "references/narration.md"
    )
    remote_head = _commit(publisher, neutral_path, "updated prose\n", "update skill")
    _run(publisher, "push", "origin", "main")

    durability = GitRemoteDurability(GitStager(worker), "origin", "main")
    snapshot = durability.verify_synchronized()

    assert snapshot.local_head == remote_head
    assert snapshot.remote_head == remote_head
    assert _run(worker, "rev-parse", "HEAD") == remote_head
    assert (worker / neutral_path).read_text(encoding="utf-8") == "updated prose\n"
    assert (worker / "state/meta.json").read_text(encoding="utf-8") == original_state


def test_preflight_fast_forwards_descendant_with_no_net_tree_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SWORD_GIT_TOKEN", raising=False)
    _, publisher, worker = _seed_pair(tmp_path)
    local_head = _run(worker, "rev-parse", "HEAD")
    original_state = (worker / "state/meta.json").read_text(encoding="utf-8")

    _commit(publisher, "state/meta.json", '{"revision": 2}\n', "accidental state edit")
    remote_head = _commit(publisher, "state/meta.json", original_state, "revert accidental state edit")
    _run(publisher, "push", "origin", "main")

    assert _run(publisher, "diff", "--name-only", local_head, remote_head) == ""

    durability = GitRemoteDurability(GitStager(worker), "origin", "main")
    snapshot = durability.verify_synchronized()

    assert snapshot.local_head == remote_head
    assert snapshot.remote_head == remote_head
    assert _run(worker, "rev-parse", "HEAD") == remote_head
    assert (worker / "state/meta.json").read_text(encoding="utf-8") == original_state


def test_preflight_refuses_remote_descendant_that_changes_campaign_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SWORD_GIT_TOKEN", raising=False)
    _, publisher, worker = _seed_pair(tmp_path)
    local_head = _run(worker, "rev-parse", "HEAD")
    _commit(publisher, "state/meta.json", '{"revision": 2}\n', "external state change")
    _run(publisher, "push", "origin", "main")

    durability = GitRemoteDurability(GitStager(worker), "origin", "main")
    with pytest.raises(RemoteDivergenceError):
        durability.verify_synchronized()

    assert _run(worker, "rev-parse", "HEAD") == local_head
    assert (worker / "state/meta.json").read_text(encoding="utf-8") == '{"revision": 1}\n'
