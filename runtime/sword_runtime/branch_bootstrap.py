"""Prepare a dedicated campaign durability branch before normal Railway bootstrap.

The immutable Railway image is built from the source branch (normally ``main``),
while gameplay transactions append to a branch whose head is not moved by
ordinary source releases. This wrapper establishes that split on the persistent
checkout, merges exactly the deployed source revision into the campaign branch,
and then delegates to :mod:`sword_runtime.bootstrap` with ``SWORD_GIT_BRANCH``
pointed at the campaign branch.

The split preserves the existing transaction invariants: campaign writes still
use one exact non-force remote branch, WAL recovery, idempotency receipts, and a
single-writer lock. Source releases simply stop being part of that branch's
preflight condition until a new image performs the controlled source merge.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess

from sword_runtime import bootstrap as legacy_bootstrap
from sword_runtime.bootstrap import BootstrapError, CheckoutSettings
from sword_runtime.release_baseline import verify_release_baseline_core
from sword_runtime.tx.errors import WalError
from sword_runtime.tx.wal import WriteAheadLog

_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _git_env(settings: CheckoutSettings) -> dict[str, str]:
    return dict(legacy_bootstrap._askpass_environment(settings))


def _run(
    settings: CheckoutSettings,
    *arguments: str,
    allow_failure: bool = False,
) -> str | None:
    completed = subprocess.run(
        [settings.git_binary, "-C", str(settings.campaign_root), *arguments],
        env=_git_env(settings),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if completed.returncode:
        if allow_failure:
            return None
        raise BootstrapError("campaign-branch Git operation failed")
    return completed.stdout.strip()


def _ensure_repository(settings: CheckoutSettings) -> None:
    """Create the initial source checkout without reconciling a split checkout."""
    git_directory = settings.campaign_root / ".git"
    if git_directory.is_dir():
        configured_url = _run(settings, "remote", "get-url", settings.remote)
        if configured_url != settings.git_url:
            raise BootstrapError("configured Git remote URL differs from SWORD_GIT_URL")
        legacy_bootstrap._assert_clean(settings)
        return
    # On a fresh volume the legacy bootstrap is exactly the desired source clone.
    legacy_bootstrap.ensure_checkout(settings)


def _remote_branch_exists(settings: CheckoutSettings, branch: str) -> bool:
    completed = subprocess.run(
        [
            settings.git_binary,
            "-C",
            str(settings.campaign_root),
            "ls-remote",
            "--exit-code",
            "--heads",
            settings.remote,
            f"refs/heads/{branch}",
        ],
        env=_git_env(settings),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 2:
        return False
    raise BootstrapError("campaign-branch remote inspection failed")


def _fetch_branch(settings: CheckoutSettings, branch: str) -> str:
    remote_ref = f"refs/remotes/{settings.remote}/{branch}"
    _run(
        settings,
        "fetch",
        "--no-tags",
        settings.remote,
        f"refs/heads/{branch}:{remote_ref}",
    )
    value = _run(settings, "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    assert isinstance(value, str)
    return value


def _current_branch(settings: CheckoutSettings) -> str:
    value = _run(settings, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not isinstance(value, str) or not value:
        raise BootstrapError("persistent campaign checkout must be on a named branch")
    return value


def _head(settings: CheckoutSettings) -> str:
    value = _run(settings, "rev-parse", "HEAD")
    assert isinstance(value, str)
    return value


def _release_baseline(settings: CheckoutSettings, commit: str) -> tuple[str, str] | None:
    """Return ``(baseline_id, campaign_id)`` from one committed release contract.

    The release contract is source-owned, so it is safe to use as the durability
    lineage selector before the mutable campaign branch is chosen. A malformed
    contract fails closed instead of silently falling back to the legacy
    campaign-only branch name.
    """
    raw = legacy_bootstrap._commit_text(
        settings, commit, "runtime/contracts/release-campaign-state.json"
    )
    if raw is None:
        return None
    try:
        contract = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BootstrapError("release campaign-state contract is invalid JSON") from exc
    if not isinstance(contract, dict):
        raise BootstrapError("release campaign-state contract must be an object")
    baseline_id = contract.get("release_baseline_id")
    campaign_id = contract.get("campaign_id")
    if not isinstance(baseline_id, str) or not baseline_id:
        raise BootstrapError("release campaign-state contract has no baseline id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise BootstrapError("release campaign-state contract has no campaign id")
    baseline_id = legacy_bootstrap._safe_ref(baseline_id, "release baseline id")
    campaign_id = legacy_bootstrap._safe_ref(campaign_id, "release campaign id")
    return baseline_id, campaign_id


def _baseline_campaign_branch(campaign_id: str, baseline_id: str) -> str:
    """Return the non-conflicting ref namespace for certified baselines.

    Keep this outside ``campaign/<id>`` because Git cannot simultaneously store
    a legacy ``campaign/<id>`` ref and child refs beneath that same path.
    """
    return legacy_bootstrap._safe_ref(
        f"campaign-baselines/{campaign_id}/{baseline_id}",
        "baseline-scoped campaign branch",
    )


def _campaign_branch_name(settings: CheckoutSettings, source_commit: str) -> str:
    explicit = os.environ.get("SWORD_CAMPAIGN_BRANCH")
    if explicit:
        branch = legacy_bootstrap._safe_ref(explicit, "SWORD_CAMPAIGN_BRANCH")
    else:
        identity = legacy_bootstrap._campaign_identity_revision(settings, source_commit)
        if identity is None:
            raise BootstrapError(
                "cannot derive campaign durability branch without source state/meta.json identity"
            )
        release = _release_baseline(settings, source_commit)
        if release is None:
            # Legacy repositories without a release contract keep their historic
            # branch name. Current certified releases always have a contract.
            branch_name = f"campaign/{identity[0]}"
        else:
            baseline_id, contract_campaign_id = release
            if contract_campaign_id != identity[0]:
                raise BootstrapError(
                    "release campaign-state contract campaign id disagrees with source state"
                )
            branch_name = _baseline_campaign_branch(identity[0], baseline_id)
        branch = legacy_bootstrap._safe_ref(branch_name, "derived campaign branch")
    if branch == settings.branch:
        raise BootstrapError("campaign durability branch must differ from source branch")
    return branch


def _deployed_source_commit(settings: CheckoutSettings, source_head: str) -> str:
    advertised = os.environ.get("RAILWAY_GIT_COMMIT_SHA")
    if advertised is None:
        return source_head
    advertised = advertised.strip().lower()
    if not _OBJECT_ID.fullmatch(advertised):
        raise BootstrapError("RAILWAY_GIT_COMMIT_SHA is not a valid source commit")
    if _run(
        settings,
        "cat-file",
        "-e",
        f"{advertised}^{{commit}}",
        allow_failure=True,
    ) is None:
        raise BootstrapError("deployed source commit is unavailable in persistent Git history")
    if not legacy_bootstrap._is_ancestor(settings, advertised, source_head):
        raise BootstrapError("deployed source commit is not on the configured source branch")
    return advertised


def _source_changes_campaign_authority(
    settings: CheckoutSettings,
    campaign_head: str,
    source_commit: str,
) -> bool:
    merge_base = _run(settings, "merge-base", campaign_head, source_commit)
    if not isinstance(merge_base, str) or not merge_base:
        raise BootstrapError("source and campaign branches have no common Git ancestor")
    return bool(
        legacy_bootstrap._changed_campaign_authority_paths(
            settings,
            merge_base,
            source_commit,
        )
    )


def _merge_deployed_source(
    settings: CheckoutSettings,
    source_commit: str,
) -> None:
    """Merge source into campaign history without allowing source-owned state edits."""
    before = _head(settings)
    if legacy_bootstrap._is_ancestor(settings, source_commit, before):
        return
    if _source_changes_campaign_authority(settings, before, source_commit):
        raise BootstrapError(
            "source branch changes campaign authority; use an explicit campaign migration instead"
        )

    completed = subprocess.run(
        [
            settings.git_binary,
            "-C",
            str(settings.campaign_root),
            "-c",
            "commit.gpgSign=false",
            "-c",
            "user.name=Sword Bootstrap",
            "-c",
            "user.email=bootstrap@invalid",
            "merge",
            "--no-ff",
            "--no-edit",
            source_commit,
        ],
        env=_git_env(settings),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode:
        subprocess.run(
            [settings.git_binary, "-C", str(settings.campaign_root), "merge", "--abort"],
            env=_git_env(settings),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        raise BootstrapError(
            "deployed source could not be merged into campaign durability history"
        )
    after = _head(settings)
    if not legacy_bootstrap._campaign_authority_matches(settings, before, after):
        _run(settings, "reset", "--hard", before)
        raise BootstrapError("source merge changed campaign authority")
    legacy_bootstrap._assert_clean(settings)


def _adopt_remote_campaign(
    settings: CheckoutSettings,
    campaign_branch: str,
    remote_head: str,
) -> bool:
    """Align with remote campaign history and report recoverable local-ahead state.

    ``True`` means the local campaign branch is a strict descendant of its remote.
    That can be legitimate crash evidence from a transaction committed locally but
    not yet pushed. The bootstrap wrapper must leave it untouched for the existing
    WAL/receipt coordinator instead of publishing it directly.
    """
    current_branch = _current_branch(settings)
    local_head = _head(settings)
    if current_branch != campaign_branch:
        local_identity = legacy_bootstrap._campaign_identity_revision(settings, local_head)
        remote_identity = legacy_bootstrap._campaign_identity_revision(settings, remote_head)
        local_release = _release_baseline(settings, local_head)
        remote_release = _release_baseline(settings, remote_head)
        release_lineage_change = (
            os.environ.get("SWORD_CAMPAIGN_BRANCH") is None
            and current_branch != settings.branch
            and remote_release is not None
            and remote_identity is not None
            and local_identity is not None
            and local_identity[0] == remote_identity[0] == remote_release[1]
            and (local_release is None or local_release[0] != remote_release[0])
            and campaign_branch
            == _baseline_campaign_branch(remote_identity[0], remote_release[0])
        )
        if release_lineage_change:
            if _has_recoverable_wal(settings):
                raise BootstrapError(
                    "release baseline changed while transaction recovery is pending"
                )
            old_branch = current_branch
            old_head = local_head
            _run(settings, "checkout", "-B", campaign_branch, remote_head)
            legacy_bootstrap._assert_clean(settings)
            try:
                _retire_recovery_store(
                    settings,
                    retired_head=old_head,
                    new_baseline_id=remote_release[0],
                )
            except BootstrapError:
                _run(settings, "checkout", "-B", old_branch, old_head)
                legacy_bootstrap._assert_clean(settings)
                raise
            return False
        if local_identity is not None and remote_identity is not None:
            if local_identity[0] != remote_identity[0]:
                raise BootstrapError(
                    "local and remote campaign branches refer to different campaign IDs"
                )
            if local_identity[1] > remote_identity[1]:
                raise BootstrapError(
                    "local checkout has newer campaign authority than durability branch"
                )
            if (
                local_identity[1] == remote_identity[1]
                and not legacy_bootstrap._campaign_authority_matches(
                    settings,
                    local_head,
                    remote_head,
                )
            ):
                raise BootstrapError("local checkout conflicts with campaign durability branch")
        _run(settings, "checkout", "-B", campaign_branch, remote_head)
        local_head = remote_head

    if local_head == remote_head:
        return False
    if legacy_bootstrap._is_ancestor(settings, local_head, remote_head):
        remote_ref = f"refs/remotes/{settings.remote}/{campaign_branch}"
        _run(settings, "merge", "--ff-only", remote_ref)
        return False
    if legacy_bootstrap._is_ancestor(settings, remote_head, local_head):
        return True
    raise BootstrapError("local and remote campaign durability histories diverged")


def _has_recoverable_wal(settings: CheckoutSettings) -> bool:
    """Return whether transaction recovery owns unpublished local campaign state."""
    try:
        return bool(WriteAheadLog(settings.runtime_root / "wal").recoverable_records())
    except (OSError, TypeError, ValueError, WalError) as exc:
        raise BootstrapError("campaign recovery WAL could not be inspected safely") from exc


def _retire_recovery_store(
    settings: CheckoutSettings,
    *,
    retired_head: str,
    new_baseline_id: str,
) -> None:
    """Move non-recoverable WAL/receipts out of a replacement baseline.

    Request receipts and completed WAL records belong to the retired campaign
    lineage. Reusing them after an intentional baseline reset can resurrect old
    idempotency decisions even when the Git state was reset correctly.
    """
    sources = [settings.runtime_root / name for name in ("wal", "receipts") if (settings.runtime_root / name).exists()]
    if not sources:
        return
    token = hashlib.sha256(
        f"{retired_head}:{new_baseline_id}".encode("utf-8")
    ).hexdigest()[:20]
    archive_root = settings.runtime_root / "retired-release-baselines"
    try:
        archive_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BootstrapError("release baseline recovery archive could not be created") from exc
    archive = None
    for index in range(1, 1001):
        candidate = archive_root / (token if index == 1 else f"{token}-{index}")
        try:
            candidate.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        except OSError as exc:
            raise BootstrapError("release baseline recovery archive could not be created") from exc
        archive = candidate
        break
    if archive is None:
        raise BootstrapError("release baseline recovery archive namespace exhausted")
    moved: list[tuple[object, object]] = []
    try:
        for source in sources:
            target = archive / source.name
            source.rename(target)
            moved.append((source, target))
    except OSError as exc:
        for source, target in reversed(moved):
            try:
                target.rename(source)
            except OSError:
                pass
        try:
            archive.rmdir()
        except OSError:
            pass
        raise BootstrapError("release baseline recovery-store retirement failed") from exc


def _restore_missing_remote_campaign(
    settings: CheckoutSettings,
    campaign_branch: str,
    source_commit: str,
) -> None:
    """Republish a lost durability ref only from an unambiguous committed checkout.

    A persistent volume can outlive accidental deletion or replacement of the
    remote campaign ref. When that happens, the clean local campaign branch is
    still useful authority, but only if transaction recovery has no pending WAL
    evidence. A pending WAL may represent a local commit awaiting its exact
    durability transition, so bootstrap must leave that case fail-closed for the
    transaction coordinator instead of publishing it out of band.
    """
    current_branch = _current_branch(settings)
    if current_branch == settings.branch:
        _run(settings, "checkout", "-b", campaign_branch, source_commit)
        if _release_baseline(settings, source_commit) is not None:
            baseline_errors = verify_release_baseline_core(settings.campaign_root)
            if baseline_errors:
                _run(settings, "checkout", settings.branch)
                legacy_bootstrap._assert_clean(settings)
                raise BootstrapError(
                    "source release baseline failed verification: "
                    + "; ".join(baseline_errors[:4])
                )
        return
    if current_branch != campaign_branch:
        # A changed release_baseline_id intentionally creates a new durability
        # lineage. Preserve the old branch/ref, but seed the new branch from the
        # exact deployed source baseline instead of resurrecting the previous
        # campaign state. Pending WAL evidence blocks this reset.
        if os.environ.get("SWORD_CAMPAIGN_BRANCH") is not None:
            raise BootstrapError(
                "explicit campaign durability branch is missing while checkout is on an unexpected branch"
            )
        release = _release_baseline(settings, source_commit)
        if release is None:
            raise BootstrapError(
                "campaign durability branch is missing while checkout is on an unexpected branch"
            )
        old_head = _head(settings)
        new_baseline_id, campaign_id = release
        local_release = _release_baseline(settings, old_head)
        legacy_branch = legacy_bootstrap._safe_ref(
            f"campaign/{campaign_id}", "legacy campaign branch"
        )
        if current_branch == legacy_branch:
            if local_release is None:
                raise BootstrapError(
                    "legacy campaign branch has no certified release baseline; explicit migration is required"
                )
            if local_release[1] != campaign_id:
                raise BootstrapError(
                    "legacy campaign branch release contract changes campaign identity"
                )
            if local_release[0] == new_baseline_id:
                if _has_recoverable_wal(settings):
                    raise BootstrapError(
                        "campaign branch naming migration blocked by transaction recovery"
                    )
                # This is only a durability-ref naming migration. Preserve the
                # exact live campaign head and its same-lineage receipts.
                _run(settings, "checkout", "-B", campaign_branch, old_head)
                legacy_bootstrap._assert_clean(settings)
                return
        if _has_recoverable_wal(settings):
            raise BootstrapError(
                "release baseline changed while transaction recovery is pending"
            )
        _run(settings, "checkout", "-B", campaign_branch, source_commit)
        legacy_bootstrap._assert_clean(settings)
        baseline_errors = verify_release_baseline_core(settings.campaign_root)
        if baseline_errors:
            _run(settings, "checkout", "-B", current_branch, old_head)
            legacy_bootstrap._assert_clean(settings)
            raise BootstrapError(
                "source release baseline failed verification: "
                + "; ".join(baseline_errors[:4])
            )
        try:
            _retire_recovery_store(
                settings,
                retired_head=old_head,
                new_baseline_id=new_baseline_id,
            )
        except BootstrapError:
            _run(settings, "checkout", "-B", current_branch, old_head)
            legacy_bootstrap._assert_clean(settings)
            raise
        return

    local_head = _head(settings)
    local_identity = legacy_bootstrap._campaign_identity_revision(settings, local_head)
    if local_identity is None:
        raise BootstrapError(
            "missing campaign durability branch cannot be restored without local campaign identity"
        )
    explicit = os.environ.get("SWORD_CAMPAIGN_BRANCH")
    if explicit is None:
        expected_branch = _campaign_branch_name(settings, source_commit)
        if campaign_branch != expected_branch:
            raise BootstrapError(
                "local campaign identity does not match missing durability branch"
            )
    if _has_recoverable_wal(settings):
        raise BootstrapError(
            "campaign durability branch is missing while transaction recovery is pending"
        )

    _run(
        settings,
        "push",
        "--no-force",
        settings.remote,
        f"HEAD:refs/heads/{campaign_branch}",
    )
    restored_head = _fetch_branch(settings, campaign_branch)
    if restored_head != local_head:
        raise BootstrapError("restored campaign durability branch did not converge")


def prepare_campaign_branch(settings: CheckoutSettings) -> str:
    """Return the exact branch that will own gameplay transaction durability."""
    settings.runtime_root.mkdir(parents=True, exist_ok=True)
    _ensure_repository(settings)
    legacy_bootstrap._assert_clean(settings)

    source_head = _fetch_branch(settings, settings.branch)
    source_commit = _deployed_source_commit(settings, source_head)
    campaign_branch = _campaign_branch_name(settings, source_commit)
    local_ahead = False

    if _remote_branch_exists(settings, campaign_branch):
        remote_campaign_head = _fetch_branch(settings, campaign_branch)
        local_ahead = _adopt_remote_campaign(
            settings,
            campaign_branch,
            remote_campaign_head,
        )
    else:
        _restore_missing_remote_campaign(settings, campaign_branch, source_commit)
        # When the checkout began on the source branch, the new local campaign
        # branch still needs its first remote durability publication. When the
        # checkout already held the campaign branch, the helper published and
        # verified the preserved local authority directly.
        if not _remote_branch_exists(settings, campaign_branch):
            _merge_deployed_source(settings, source_commit)
            _run(
                settings,
                "push",
                "--no-force",
                settings.remote,
                f"HEAD:refs/heads/{campaign_branch}",
            )

    if local_ahead:
        # A same-source restart may have a transaction commit that exists locally
        # but not remotely because the process died between commit and push. Let the
        # established coordinator inspect WAL + trailers and finish or reject it.
        # Never make a source-merge commit or direct push on top of that evidence.
        if not legacy_bootstrap._is_ancestor(settings, source_commit, _head(settings)):
            raise BootstrapError(
                "pending local campaign transaction must recover before a newer source deployment can reconcile"
            )
        legacy_bootstrap._assert_clean(settings)
        return campaign_branch

    _merge_deployed_source(settings, source_commit)
    local_head = _head(settings)
    remote_campaign_head = _fetch_branch(settings, campaign_branch)
    if local_head != remote_campaign_head:
        # At this point local-ahead transaction evidence was excluded above, so the
        # only legitimate local descendant is the source-reconciliation merge made
        # by this wrapper. Publish it non-force from the exact fetched campaign head.
        if not legacy_bootstrap._is_ancestor(settings, remote_campaign_head, local_head):
            raise BootstrapError(
                "source reconciliation no longer descends from campaign durability head"
            )
        _run(settings, "push", settings.remote, f"HEAD:refs/heads/{campaign_branch}")
        remote_campaign_head = _fetch_branch(settings, campaign_branch)
        if _head(settings) != remote_campaign_head:
            raise BootstrapError("campaign durability push did not converge")

    legacy_bootstrap._assert_clean(settings)
    return campaign_branch


def main() -> int:
    source_settings = CheckoutSettings.from_env()
    source_branch = source_settings.branch
    campaign_branch = prepare_campaign_branch(source_settings)

    # The normal bootstrap and production transaction coordinator now see only
    # the campaign durability branch. Keep the source branch separately available
    # for diagnostics; it is intentionally not part of transaction synchronization.
    os.environ["SWORD_SOURCE_BRANCH"] = source_branch
    os.environ["SWORD_CAMPAIGN_BRANCH"] = campaign_branch
    os.environ["SWORD_GIT_BRANCH"] = campaign_branch
    return legacy_bootstrap.main()


if __name__ == "__main__":
    raise SystemExit(main())
