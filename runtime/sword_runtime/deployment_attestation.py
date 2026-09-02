"""Safe local attestation for the deployed Sword source and campaign checkout.

Railway executes Python from the immutable build image while the live campaign
checkout lives on the persistent volume.  Those are intentionally separate
storage tiers, but executable/game/dependency changes must never be mixed across
them.  This module compares the build source revision advertised by Railway with
local Git refs only; it performs no network access and exposes no credentials.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_EXECUTION_NEUTRAL_PREFIXES = (
    "state/",
    "docs/",
    "plugins/sword-and-banners/skill/",
    "tests/",
    "tools/",
    ".github/",
)
_EXECUTION_NEUTRAL_EXACT = frozenset({"README.md"})


class DeploymentCompatibilityError(RuntimeError):
    """The image source cannot safely execute the current repository image."""


def _git(root: Path, arguments: tuple[str, ...], *, allow_failure: bool = False) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if allow_failure:
            return None
        raise DeploymentCompatibilityError("deployment Git inspection unavailable") from exc
    if completed.returncode:
        if allow_failure:
            return None
        raise DeploymentCompatibilityError("deployment Git inspection failed")
    try:
        return completed.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        if allow_failure:
            return None
        raise DeploymentCompatibilityError("deployment Git output is invalid") from exc


def _object_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if _OBJECT_ID.fullmatch(value) else None


def _runtime_neutral_path(path: str) -> bool:
    return path in _EXECUTION_NEUTRAL_EXACT or any(path.startswith(prefix) for prefix in _EXECUTION_NEUTRAL_PREFIXES)


def _changed_paths(root: Path, older: str, newer: str) -> tuple[str, ...]:
    raw = _git(root, ("diff", "--no-renames", "--name-only", "-z", older, newer, "--"))
    assert isinstance(raw, str)
    # ``strip`` in _git is harmless for normal paths but a NUL-separated result
    # may still carry the final NUL. Empty records are discarded below.
    values = tuple(sorted({path for path in raw.split("\x00") if path}))
    if len(values) > 10000:
        raise DeploymentCompatibilityError("deployment diff exceeds bounded inspection")
    return values


def _is_ancestor(root: Path, older: str, newer: str) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    return None


def deployment_attestation(
    campaign_root: object,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a bounded, non-secret source/check-out compatibility record.

    ``RAILWAY_GIT_COMMIT_SHA`` identifies the immutable image source.  The
    persistent checkout may legitimately advance beyond it through campaign
    state transactions, Skill/docs/tests/tools changes, or CI metadata.  Any
    executable/runtime, game/rule, dependency, or deployment change requires a
    new image and is reported as ``deployment_required``.
    """
    root = Path(campaign_root).expanduser().resolve()
    source = os.environ if environ is None else environ
    image_source = _object_id(source.get("RAILWAY_GIT_COMMIT_SHA"))
    checkout_head = _object_id(_git(root, ("rev-parse", "HEAD"), allow_failure=True))
    remote = str(source.get("SWORD_GIT_REMOTE") or "origin")
    branch = str(source.get("SWORD_GIT_BRANCH") or "main")
    tracking_ref = f"refs/remotes/{remote}/{branch}"
    tracking_head = _object_id(_git(root, ("rev-parse", "--verify", tracking_ref), allow_failure=True))

    result: dict[str, Any] = {
        "platform": "railway" if image_source is not None else "unattested_environment",
        "image_source_commit": image_source,
        "checkout_commit": checkout_head,
        "tracking_commit": tracking_head,
        "source_sync_status": "unattested",
        "source_compatible": True,
        "deployment_required": False,
        "checkout_matches_tracking": bool(checkout_head and tracking_head and checkout_head == tracking_head),
        "incompatible_path_count": 0,
        "incompatible_paths": [],
    }
    deployment_id = source.get("RAILWAY_DEPLOYMENT_ID")
    if isinstance(deployment_id, str) and deployment_id.strip():
        result["deployment_id"] = deployment_id.strip()[:160]

    # Local development and tests need no Railway build identity. Production
    # startup is fail-closed only when Railway explicitly supplies one.
    if image_source is None:
        result["source_sync_status"] = "image_source_not_advertised"
        return result
    if checkout_head is None:
        result.update({
            "source_sync_status": "checkout_unverifiable",
            "source_compatible": False,
            "deployment_required": True,
        })
        return result

    # Prefer the fetched tracking head when it is available: after an old live
    # process discovers a newer main during transaction preflight, the local
    # checkout can still equal the image source while the remote-tracking ref
    # proves that a deploy-relevant revision is waiting.
    target_head = tracking_head or checkout_head
    if image_source == target_head:
        result["source_sync_status"] = "exact"
        return result

    ancestor = _is_ancestor(root, image_source, target_head)
    if ancestor is not True:
        result.update({
            "source_sync_status": "source_lineage_mismatch" if ancestor is False else "source_lineage_unverifiable",
            "source_compatible": False,
            "deployment_required": True,
        })
        return result

    try:
        paths = _changed_paths(root, image_source, target_head)
    except DeploymentCompatibilityError:
        result.update({
            "source_sync_status": "source_diff_unverifiable",
            "source_compatible": False,
            "deployment_required": True,
        })
        return result
    incompatible = [path for path in paths if not _runtime_neutral_path(path)]
    result["incompatible_path_count"] = len(incompatible)
    result["incompatible_paths"] = incompatible[:32]
    if incompatible:
        result.update({
            "source_sync_status": "deployment_source_behind",
            "source_compatible": False,
            "deployment_required": True,
        })
    else:
        result["source_sync_status"] = "checkout_ahead_runtime_neutral"
    return result


def assert_deployment_compatible(campaign_root: object, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Fail startup when Railway advertises an incompatible image/check-out pair."""
    attestation = deployment_attestation(campaign_root, environ)
    if attestation.get("source_compatible") is not True:
        raise DeploymentCompatibilityError(str(attestation.get("source_sync_status") or "deployment_source_incompatible"))
    return attestation


def public_deployment_health(campaign_root: object, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return a minimal non-secret health projection for unauthenticated probes."""
    attestation = deployment_attestation(campaign_root, environ)
    def short(value: object) -> str | None:
        return value[:12] if isinstance(value, str) and _OBJECT_ID.fullmatch(value) else None
    return {
        "status": "ok" if attestation.get("source_compatible") is True else "source_mismatch",
        "source_sync": attestation.get("source_sync_status"),
        "image_source": short(attestation.get("image_source_commit")),
        "checkout": short(attestation.get("checkout_commit")),
        "deployment_required": bool(attestation.get("deployment_required")),
    }


__all__ = [
    "DeploymentCompatibilityError",
    "assert_deployment_compatible",
    "deployment_attestation",
    "public_deployment_health",
]
