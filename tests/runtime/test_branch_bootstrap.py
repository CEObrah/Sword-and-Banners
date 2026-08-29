from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sword_runtime.bootstrap import BootstrapError, CheckoutSettings
from sword_runtime.branch_bootstrap import prepare_campaign_branch
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.remote import GitRemoteDurability

CAMPAIGN_ID = "sword-banner-tang-wei-main"


def git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def commit(root: Path, path: str, text: str, message: str) -> str:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(root, "add", "--", path)
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


def meta(revision: int) -> str:
    return json.dumps(
        {
            "schema": "meta",
            "campaign_id": CAMPAIGN_ID,
            "revision": revision,
        },
        separators=(",", ":"),
    ) + "\n"


def source_remote_and_settings(tmp_path: Path) -> tuple[Path, Path, CheckoutSettings, str]:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    git(source, "config", "user.email", "source@example.invalid")
    git(source, "config", "user.name", "Source Test")
    (source / "state").mkdir()
    (source / "runtime" / "sword_runtime").mkdir(parents=True)
    (source / "state" / "meta.json").write_text(meta(1), encoding="utf-8")
    (source / "runtime" / "sword_runtime" / "engine.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    git(source, "add", ".")
    git(source, "commit", "-qm", "baseline")
    baseline = git(source, "rev-parse", "HEAD")

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(source), str(remote)],
        check=True,
    )
    git(source, "remote", "add", "origin", str(remote))

    settings = CheckoutSettings(
        campaign_root=tmp_path / "volume" / "campaign",
        runtime_root=tmp_path / "volume" / "runtime",
        git_url=str(remote),
        branch="main",
    )
    return source, remote, settings, baseline


def configure_deployed_source(monkeypatch: pytest.MonkeyPatch, sha: str) -> None:
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", sha)
    monkeypatch.delenv("SWORD_CAMPAIGN_BRANCH", raising=False)
    monkeypatch.delenv("SWORD_GIT_TOKEN", raising=False)


def test_first_bootstrap_creates_dedicated_campaign_durability_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)

    branch = prepare_campaign_branch(settings)

    checkout = settings.campaign_root
    assert branch == f"campaign/{CAMPAIGN_ID}"
    assert git(checkout, "branch", "--show-current") == branch
    assert git(checkout, "rev-parse", "HEAD") == baseline
    assert (
        git(remote, "rev-parse", f"refs/heads/{branch}")
        == baseline
    )
    assert json.loads((checkout / "state" / "meta.json").read_text(encoding="utf-8"))["revision"] == 1


def test_source_branch_advance_does_not_break_existing_campaign_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    campaign_branch = prepare_campaign_branch(settings)
    campaign_head = git(settings.campaign_root, "rev-parse", "HEAD")

    commit(
        source,
        "runtime/sword_runtime/engine.py",
        "VALUE = 2\n",
        "new source release",
    )
    git(source, "push", "-q", "origin", "main")

    durability = GitRemoteDurability(
        GitStager(settings.campaign_root),
        "origin",
        campaign_branch,
    )
    snapshot = durability.verify_synchronized()

    assert snapshot.local_head == campaign_head
    assert snapshot.remote_head == campaign_head
    assert git(settings.campaign_root, "rev-parse", "HEAD") == campaign_head


def test_new_deployment_merges_source_without_rewriting_campaign_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    campaign_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    campaign_state_head = commit(
        checkout,
        "state/meta.json",
        meta(2),
        "gameplay revision 2",
    )
    git(checkout, "push", "-q", "origin", campaign_branch)

    source_head = commit(
        source,
        "runtime/sword_runtime/engine.py",
        "VALUE = 2\n",
        "new source release",
    )
    git(source, "push", "-q", "origin", "main")
    configure_deployed_source(monkeypatch, source_head)

    assert prepare_campaign_branch(settings) == campaign_branch

    merged_head = git(checkout, "rev-parse", "HEAD")
    assert merged_head != campaign_state_head
    assert git(checkout, "merge-base", "--is-ancestor", source_head, merged_head) == ""
    assert json.loads((checkout / "state" / "meta.json").read_text(encoding="utf-8"))["revision"] == 2
    assert (checkout / "runtime" / "sword_runtime" / "engine.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def test_source_side_campaign_state_edit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    prepare_campaign_branch(settings)

    bad_source = commit(source, "state/meta.json", meta(2), "invalid source-side state edit")
    git(source, "push", "-q", "origin", "main")
    configure_deployed_source(monkeypatch, bad_source)

    with pytest.raises(BootstrapError, match="source branch changes campaign authority"):
        prepare_campaign_branch(settings)

    assert json.loads(
        (settings.campaign_root / "state" / "meta.json").read_text(encoding="utf-8")
    )["revision"] == 1
