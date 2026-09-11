from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import sword_runtime.branch_bootstrap as branch_bootstrap_module
from sword_runtime.bootstrap import BootstrapError, CheckoutSettings
from sword_runtime.branch_bootstrap import prepare_campaign_branch
from sword_runtime.deployment_attestation import deployment_attestation
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.remote import GitRemoteDurability

CAMPAIGN_ID = "sword-banner-tang-wei-main"
BASELINE_ID = "test-baseline-a"


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
            "player_id": "char_tang_wei",
            "revision": revision,
            "time": "test-time",
        },
        separators=(",", ":"),
    ) + "\n"


def state_digest(root: Path) -> str:
    state = root / "state"
    digest = hashlib.sha256()
    for path in sorted(
        (path for path in state.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(state).as_posix(),
    ):
        rel = path.relative_to(state).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def release_contract(root: Path, baseline_id: str = BASELINE_ID, revision: int = 1) -> str:
    return json.dumps(
        {
            "schema": "release-campaign-state-contract-1.0",
            "release_baseline_id": baseline_id,
            "campaign_id": CAMPAIGN_ID,
            "player_id": "char_tang_wei",
            "revision": revision,
            "world_time": "test-time",
            "state_tree_sha256": state_digest(root),
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
    (source / "runtime" / "contracts").mkdir(parents=True)
    (source / "runtime" / "contracts" / "release-campaign-state.json").write_text(
        release_contract(source), encoding="utf-8"
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
    assert branch == f"campaign-baselines/{CAMPAIGN_ID}/{BASELINE_ID}"
    assert git(checkout, "branch", "--show-current") == branch
    assert git(checkout, "rev-parse", "HEAD") == baseline
    assert git(remote, "rev-parse", f"refs/heads/{branch}") == baseline
    assert json.loads(
        (checkout / "state" / "meta.json").read_text(encoding="utf-8")
    )["revision"] == 1


def test_first_bootstrap_rejects_mismatched_release_baseline_digest_without_publishing_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    contract_path = source / "runtime/contracts/release-campaign-state.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["state_tree_sha256"] = "f" * 64
    contract_path.write_text(
        json.dumps(contract, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    git(source, "add", str(contract_path.relative_to(source)))
    git(source, "commit", "-qm", "break release baseline digest")
    bad_head = git(source, "rev-parse", "HEAD")
    git(source, "push", "-q", "origin", "main")
    configure_deployed_source(monkeypatch, bad_head)

    with pytest.raises(BootstrapError, match="source release baseline failed verification"):
        prepare_campaign_branch(settings)

    branch = f"campaign-baselines/{CAMPAIGN_ID}/{BASELINE_ID}"
    completed = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", "--verify", f"refs/heads/{branch}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert completed.returncode != 0
    assert git(settings.campaign_root, "branch", "--show-current") == "main"


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


def test_same_source_local_ahead_is_left_for_transaction_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    campaign_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")

    local_transaction_head = commit(
        checkout,
        "state/meta.json",
        meta(2),
        "locally committed transaction awaiting recovery",
    )

    assert prepare_campaign_branch(settings) == campaign_branch

    assert git(checkout, "rev-parse", "HEAD") == local_transaction_head
    assert git(remote, "rev-parse", f"refs/heads/{campaign_branch}") == baseline
    assert json.loads(
        (checkout / "state" / "meta.json").read_text(encoding="utf-8")
    )["revision"] == 2


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
    assert json.loads(
        (checkout / "state" / "meta.json").read_text(encoding="utf-8")
    )["revision"] == 2
    assert (
        checkout / "runtime" / "sword_runtime" / "engine.py"
    ).read_text(encoding="utf-8") == "VALUE = 2\n"


def test_split_checkout_remains_compatible_with_deployed_source_attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    campaign_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    commit(checkout, "state/meta.json", meta(2), "gameplay revision 2")
    git(checkout, "push", "-q", "origin", campaign_branch)

    source_head = commit(
        source,
        "runtime/sword_runtime/engine.py",
        "VALUE = 2\n",
        "new source release",
    )
    git(source, "push", "-q", "origin", "main")
    configure_deployed_source(monkeypatch, source_head)
    prepare_campaign_branch(settings)

    attestation = deployment_attestation(
        checkout,
        {
            "RAILWAY_GIT_COMMIT_SHA": source_head,
            "SWORD_GIT_REMOTE": "origin",
            "SWORD_GIT_BRANCH": campaign_branch,
            "SWORD_SOURCE_BRANCH": "main",
        },
    )

    assert attestation["source_compatible"] is True
    assert attestation["deployment_required"] is False
    assert attestation["source_sync_status"] == "checkout_ahead_runtime_neutral"
    assert attestation["incompatible_paths"] == []


def test_new_release_baseline_seeds_new_durability_branch_instead_of_reusing_old_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    old_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    old_state_head = commit(
        checkout,
        "state/meta.json",
        meta(2),
        "old baseline gameplay revision 2",
    )
    git(checkout, "push", "-q", "origin", old_branch)
    old_receipt = settings.runtime_root / "receipts" / "old-request.json"
    old_receipt.parent.mkdir(parents=True, exist_ok=True)
    old_receipt.write_text("retired receipt\n", encoding="utf-8")

    contract_path = source / "runtime" / "contracts" / "release-campaign-state.json"
    contract_path.write_text(release_contract(source, "test-baseline-b", revision=1), encoding="utf-8")
    git(source, "add", str(contract_path.relative_to(source)))
    git(source, "commit", "-qm", "declare replacement release baseline")
    source_head = git(source, "rev-parse", "HEAD")
    git(source, "push", "-q", "origin", "main")
    configure_deployed_source(monkeypatch, source_head)

    new_branch = prepare_campaign_branch(settings)

    assert new_branch == f"campaign-baselines/{CAMPAIGN_ID}/test-baseline-b"
    assert new_branch != old_branch
    assert git(checkout, "branch", "--show-current") == new_branch
    assert json.loads((checkout / "state/meta.json").read_text(encoding="utf-8"))["revision"] == 1
    assert git(remote, "rev-parse", f"refs/heads/{old_branch}") == old_state_head
    assert git(remote, "rev-parse", f"refs/heads/{new_branch}") == git(checkout, "rev-parse", "HEAD")
    assert not (settings.runtime_root / "receipts").exists()
    retired_receipts = list(
        (settings.runtime_root / "retired-release-baselines").glob(
            "*/receipts/old-request.json"
        )
    )
    assert len(retired_receipts) == 1
    assert retired_receipts[0].read_text(encoding="utf-8") == "retired receipt\n"


def test_legacy_campaign_branch_naming_migration_preserves_same_baseline_live_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    scoped_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    live_head = commit(
        checkout,
        "state/meta.json",
        meta(2),
        "live gameplay revision 2 before branch naming migration",
    )
    git(checkout, "push", "-q", "origin", scoped_branch)

    legacy_branch = f"campaign/{CAMPAIGN_ID}"
    # Model the actual pre-migration remote topology: the legacy ref exists and
    # the new baseline-scoped ref does not. Delete the scoped fixture ref before
    # publishing the legacy parent-style name because Git cannot store both
    # ``campaign/<id>`` and ``campaign/<id>/...`` simultaneously.
    git(remote, "update-ref", "-d", f"refs/heads/{scoped_branch}")
    git(checkout, "branch", "-m", legacy_branch)
    git(checkout, "push", "-q", "origin", f"HEAD:refs/heads/{legacy_branch}")
    receipt = settings.runtime_root / "receipts" / "same-lineage.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("preserve me\n", encoding="utf-8")

    migrated = prepare_campaign_branch(settings)

    assert migrated == scoped_branch
    assert git(checkout, "branch", "--show-current") == scoped_branch
    assert git(checkout, "rev-parse", "HEAD") == live_head
    assert git(remote, "rev-parse", f"refs/heads/{scoped_branch}") == live_head
    assert git(remote, "rev-parse", f"refs/heads/{legacy_branch}") == live_head
    assert json.loads((checkout / "state/meta.json").read_text(encoding="utf-8"))["revision"] == 2
    assert receipt.read_text(encoding="utf-8") == "preserve me\n"


def test_replacement_release_baseline_bad_digest_restores_old_live_branch_and_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    old_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    old_head = commit(checkout, "state/meta.json", meta(2), "old live revision 2")
    git(checkout, "push", "-q", "origin", old_branch)
    receipt = settings.runtime_root / "receipts" / "old-request.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("still live\n", encoding="utf-8")

    contract_path = source / "runtime/contracts/release-campaign-state.json"
    contract = json.loads(release_contract(source, "test-baseline-b", revision=1))
    contract["state_tree_sha256"] = "e" * 64
    contract_path.write_text(
        json.dumps(contract, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    git(source, "add", str(contract_path.relative_to(source)))
    git(source, "commit", "-qm", "declare invalid replacement baseline")
    source_head = git(source, "rev-parse", "HEAD")
    git(source, "push", "-q", "origin", "main")
    configure_deployed_source(monkeypatch, source_head)

    with pytest.raises(BootstrapError, match="source release baseline failed verification"):
        prepare_campaign_branch(settings)

    new_branch = f"campaign-baselines/{CAMPAIGN_ID}/test-baseline-b"
    assert git(checkout, "branch", "--show-current") == old_branch
    assert git(checkout, "rev-parse", "HEAD") == old_head
    assert json.loads((checkout / "state/meta.json").read_text(encoding="utf-8"))["revision"] == 2
    assert receipt.read_text(encoding="utf-8") == "still live\n"
    completed = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", "--verify", f"refs/heads/{new_branch}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert completed.returncode != 0


def test_release_baseline_recovery_retirement_failure_restores_old_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    old_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    old_head = commit(checkout, "state/meta.json", meta(2), "old baseline revision 2")
    git(checkout, "push", "-q", "origin", old_branch)

    contract_path = source / "runtime/contracts/release-campaign-state.json"
    contract_path.write_text(release_contract(source, "test-baseline-b", revision=1), encoding="utf-8")
    git(source, "add", str(contract_path.relative_to(source)))
    git(source, "commit", "-qm", "declare replacement baseline")
    source_head = git(source, "rev-parse", "HEAD")
    git(source, "push", "-q", "origin", "main")
    configure_deployed_source(monkeypatch, source_head)

    def fail_retirement(*_args: object, **_kwargs: object) -> None:
        raise BootstrapError("release baseline recovery-store retirement failed")

    monkeypatch.setattr(
        branch_bootstrap_module, "_retire_recovery_store", fail_retirement
    )
    with pytest.raises(BootstrapError, match="recovery-store retirement failed"):
        prepare_campaign_branch(settings)

    assert git(checkout, "branch", "--show-current") == old_branch
    assert git(checkout, "rev-parse", "HEAD") == old_head
    assert json.loads((checkout / "state/meta.json").read_text(encoding="utf-8"))["revision"] == 2
    new_branch = f"campaign-baselines/{CAMPAIGN_ID}/test-baseline-b"
    completed = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", "--verify", f"refs/heads/{new_branch}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert completed.returncode != 0


def test_existing_replacement_baseline_branch_overrides_stale_volume_and_retires_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    old_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    old_state_head = commit(
        checkout,
        "state/meta.json",
        meta(2),
        "old baseline gameplay revision 2",
    )
    git(checkout, "push", "-q", "origin", old_branch)
    old_receipt = settings.runtime_root / "receipts" / "old-request.json"
    old_receipt.parent.mkdir(parents=True, exist_ok=True)
    old_receipt.write_text("stale baseline receipt\n", encoding="utf-8")

    contract_path = source / "runtime/contracts/release-campaign-state.json"
    contract_path.write_text(release_contract(source, "test-baseline-b", revision=1), encoding="utf-8")
    git(source, "add", str(contract_path.relative_to(source)))
    git(source, "commit", "-qm", "declare replacement baseline branch")
    source_head = git(source, "rev-parse", "HEAD")
    git(source, "push", "-q", "origin", "main")
    new_branch = f"campaign-baselines/{CAMPAIGN_ID}/test-baseline-b"
    git(source, "push", "-q", "origin", f"{source_head}:refs/heads/{new_branch}")
    configure_deployed_source(monkeypatch, source_head)

    selected = prepare_campaign_branch(settings)

    assert selected == new_branch
    assert git(checkout, "branch", "--show-current") == new_branch
    assert json.loads((checkout / "state/meta.json").read_text(encoding="utf-8"))["revision"] == 1
    assert git(remote, "rev-parse", f"refs/heads/{old_branch}") == old_state_head
    assert not (settings.runtime_root / "receipts").exists()
    retired = list(
        (settings.runtime_root / "retired-release-baselines").glob(
            "*/receipts/old-request.json"
        )
    )
    assert len(retired) == 1
    assert retired[0].read_text(encoding="utf-8") == "stale baseline receipt\n"


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


def test_missing_remote_campaign_branch_is_restored_from_clean_persistent_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    campaign_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    campaign_head = commit(
        checkout,
        "state/meta.json",
        meta(2),
        "durable gameplay revision 2",
    )
    git(checkout, "push", "-q", "origin", campaign_branch)
    git(remote, "update-ref", "-d", f"refs/heads/{campaign_branch}")

    assert prepare_campaign_branch(settings) == campaign_branch

    assert git(checkout, "branch", "--show-current") == campaign_branch
    assert git(checkout, "rev-parse", "HEAD") == campaign_head
    assert git(remote, "rev-parse", f"refs/heads/{campaign_branch}") == campaign_head
    assert json.loads(
        (checkout / "state" / "meta.json").read_text(encoding="utf-8")
    )["revision"] == 2


def test_missing_remote_campaign_branch_stays_fail_closed_with_pending_wal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    campaign_branch = prepare_campaign_branch(settings)
    git(remote, "update-ref", "-d", f"refs/heads/{campaign_branch}")
    monkeypatch.setattr(
        "sword_runtime.branch_bootstrap._has_recoverable_wal",
        lambda _settings: True,
    )

    with pytest.raises(BootstrapError, match="transaction recovery is pending"):
        prepare_campaign_branch(settings)

    completed = subprocess.run(
        ["git", "-C", str(remote), "rev-parse", "--verify", f"refs/heads/{campaign_branch}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    assert completed.returncode != 0


def test_missing_remote_campaign_branch_rejects_unidentified_local_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source, remote, settings, baseline = source_remote_and_settings(tmp_path)
    configure_deployed_source(monkeypatch, baseline)
    campaign_branch = prepare_campaign_branch(settings)
    checkout = settings.campaign_root
    git(checkout, "config", "user.email", "runtime@example.invalid")
    git(checkout, "config", "user.name", "Runtime Test")
    commit(
        checkout,
        "state/meta.json",
        '{"schema":"meta","revision":2}\n',
        "corrupt local campaign identity",
    )
    git(remote, "update-ref", "-d", f"refs/heads/{campaign_branch}")

    with pytest.raises(BootstrapError, match="without local campaign identity"):
        prepare_campaign_branch(settings)
