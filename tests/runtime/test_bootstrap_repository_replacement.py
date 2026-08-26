from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sword_runtime.bootstrap import BootstrapError, CheckoutSettings, ensure_checkout

CAMPAIGN_ID = "sword-banner-tang-wei-main"


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root)] + list(arguments),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def meta(revision: int, *, note: str | None = None, compact: bool = True) -> str:
    payload = {"schema": "meta", "campaign_id": CAMPAIGN_ID, "revision": revision}
    if note is not None:
        payload["note"] = note
    if compact:
        return json.dumps(payload, separators=(",", ":")) + "\n"
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def source_and_remote(tmp_path: Path, revision: int = 0) -> tuple[Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    git(source, "config", "user.email", "bootstrap@example.invalid")
    git(source, "config", "user.name", "Bootstrap Test")
    (source / "state").mkdir()
    (source / "state" / "meta.json").write_text(meta(revision), encoding="utf-8")
    (source / "README.md").write_text("baseline\n", encoding="utf-8")
    git(source, "add", "state/meta.json", "README.md")
    git(source, "commit", "-qm", "baseline")

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(remote)], check=True)
    git(source, "remote", "add", "origin", str(remote))
    return source, remote


def settings(tmp_path: Path, remote: Path) -> CheckoutSettings:
    return CheckoutSettings(
        campaign_root=tmp_path / "volume" / "campaign",
        runtime_root=tmp_path / "volume" / "runtime",
        git_url=str(remote),
        branch="main",
    )


def replace_remote_history(source: Path, revision: int, *, note: str | None = None, compact: bool = True) -> str:
    git(source, "checkout", "--orphan", "replacement")
    git(source, "rm", "-rf", ".")
    (source / "state").mkdir()
    (source / "state" / "meta.json").write_text(meta(revision, note=note, compact=compact), encoding="utf-8")
    (source / "README.md").write_text("replacement\n", encoding="utf-8")
    git(source, "add", "state/meta.json", "README.md")
    git(source, "commit", "-qm", "replacement root")
    git(source, "branch", "-M", "main")
    git(source, "push", "-q", "--force", "origin", "main")
    return git(source, "rev-parse", "HEAD")


def test_same_head_dirty_checkout_is_rejected(tmp_path: Path) -> None:
    source, remote = source_and_remote(tmp_path, revision=2)
    configured = settings(tmp_path, remote)
    checkout = ensure_checkout(configured)

    assert git(checkout, "rev-parse", "HEAD") == git(source, "rev-parse", "HEAD")
    (checkout / "state" / "meta.json").write_text(
        meta(2, note="uncommitted persistent override"),
        encoding="utf-8",
    )

    with pytest.raises(BootstrapError, match="persistent campaign checkout is dirty"):
        ensure_checkout(configured)


def test_rehomes_replaced_history_when_state_json_is_semantically_identical(tmp_path: Path) -> None:
    source, remote = source_and_remote(tmp_path)
    configured = settings(tmp_path, remote)
    checkout = ensure_checkout(configured)

    remote_head = replace_remote_history(source, 0, compact=False)

    assert ensure_checkout(configured) == checkout
    assert git(checkout, "rev-parse", "HEAD") == remote_head


def test_rehomes_replaced_history_when_remote_same_campaign_revision_is_newer(tmp_path: Path) -> None:
    source, remote = source_and_remote(tmp_path, revision=3)
    configured = settings(tmp_path, remote)
    checkout = ensure_checkout(configured)

    remote_head = replace_remote_history(source, 4, note="legitimate newer campaign truth")

    assert ensure_checkout(configured) == checkout
    assert git(checkout, "rev-parse", "HEAD") == remote_head
    assert json.loads((checkout / "state" / "meta.json").read_text(encoding="utf-8"))["revision"] == 4


def test_replaced_history_refuses_to_discard_newer_local_campaign_revision(tmp_path: Path) -> None:
    source, remote = source_and_remote(tmp_path, revision=4)
    configured = settings(tmp_path, remote)
    checkout = ensure_checkout(configured)
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    (checkout / "state" / "meta.json").write_text(meta(5, note="unpushed gameplay"), encoding="utf-8")
    git(checkout, "add", "state/meta.json")
    git(checkout, "commit", "-qm", "local gameplay")

    replace_remote_history(source, 4, note="rewritten source")

    with pytest.raises(BootstrapError, match="local campaign revision 5 is newer"):
        ensure_checkout(configured)


def test_replaced_history_refuses_same_revision_conflicting_campaign_truth(tmp_path: Path) -> None:
    source, remote = source_and_remote(tmp_path, revision=0)
    configured = settings(tmp_path, remote)
    checkout = ensure_checkout(configured)

    replace_remote_history(source, 0, note="different baseline truth")

    with pytest.raises(BootstrapError, match="conflict at revision 0"):
        ensure_checkout(configured)
