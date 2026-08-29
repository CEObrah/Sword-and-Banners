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

import os
import re
import subprocess

from sword_runtime import bootstrap as legacy_bootstrap
from sword_runtime.bootstrap import BootstrapError, CheckoutSettings

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


def _campaign_branch_name(settings: CheckoutSettings, fallback_commit: str) -> str:
    explicit = os.environ.get("SWORD_CAMPAIGN_BRANCH")
    if explicit:
        branch = legacy_bootstrap._safe_ref(explicit, "SWORD_CAMPAIGN_BRANCH")
    else:
        identity = legacy_bootstrap._campaign_identity_revision(settings, _head(settings))
        if identity is None:
            identity = legacy_bootstrap._campaign_identity_revision(settings, fallback_commit)
        if identity is None:
            raise BootstrapError(
                "cannot derive campaign durability branch without state/meta.json identity"
            )
        branch = legacy_bootstrap._safe_ref(
            f"campaign/{identity[0]}",
            "derived campaign branch",
        )
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
        current_branch = _current_branch(settings)
        if current_branch != settings.branch:
            raise BootstrapError(
                "campaign durability branch is missing while checkout is not on source branch"
            )
        # Start the durability lineage from the current committed campaign checkout
        # so no live state is discarded. All later routing uses exact refs rather
        # than Git's implicit branch-upstream configuration.
        _run(settings, "checkout", "-b", campaign_branch)
        _merge_deployed_source(settings, source_commit)
        _run(
            settings,
            "push",
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
