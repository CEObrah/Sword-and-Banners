from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sword_runtime.bootstrap import CheckoutSettings, ensure_checkout

CAMPAIGN_ID = "sword-banner-tang-wei-main"


def git(root: Path, *args: str) -> str:
    cp = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert cp.returncode == 0, cp.stderr
    return cp.stdout.strip()


def meta(revision: int) -> str:
    return json.dumps(
        {"schema": "meta", "campaign_id": CAMPAIGN_ID, "revision": revision},
        separators=(",", ":"),
    ) + "\n"


def make_repo(tmp_path: Path) -> tuple[Path, Path, CheckoutSettings]:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    git(source, "config", "user.email", "source@example.invalid")
    git(source, "config", "user.name", "Source Test")
    (source / "state").mkdir()
    (source / "runtime" / "sword_runtime").mkdir(parents=True)
    (source / "state" / "meta.json").write_text(meta(1), encoding="utf-8")
    (source / "runtime" / "sword_runtime" / "engine.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(source, "add", ".")
    git(source, "commit", "-qm", "revision-1 baseline")

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(remote)], check=True)
    git(source, "remote", "add", "origin", str(remote))

    settings = CheckoutSettings(
        campaign_root=tmp_path / "volume" / "campaign",
        runtime_root=tmp_path / "volume" / "runtime",
        git_url=str(remote),
        branch="main",
    )
    return source, remote, settings


def test_single_main_preserves_state_commit_across_source_release(tmp_path: Path) -> None:
    source, _remote, settings = make_repo(tmp_path)
    checkout = ensure_checkout(settings)
    assert git(checkout, "branch", "--show-current") == "main"

    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    (checkout / "state" / "meta.json").write_text(meta(2), encoding="utf-8")
    git(checkout, "add", "state/meta.json")
    git(checkout, "commit", "-qm", "runtime gameplay revision 2")
    git(checkout, "push", "-q", "origin", "main")

    git(source, "pull", "-q", "--ff-only", "origin", "main")
    (source / "runtime" / "sword_runtime" / "engine.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(source, "add", "runtime/sword_runtime/engine.py")
    git(source, "commit", "-qm", "source release after gameplay")
    source_head = git(source, "rev-parse", "HEAD")
    git(source, "push", "-q", "origin", "main")

    ensure_checkout(settings)
    assert git(checkout, "branch", "--show-current") == "main"
    assert git(checkout, "rev-parse", "HEAD") == source_head
    saved = json.loads((checkout / "state" / "meta.json").read_text(encoding="utf-8"))
    assert saved["revision"] == 2
    assert (checkout / "runtime" / "sword_runtime" / "engine.py").read_text(encoding="utf-8") == "VALUE = 2\n"
