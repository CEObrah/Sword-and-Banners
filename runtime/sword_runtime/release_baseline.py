"""Release-baseline identity and state-tree verification for bootstrap.

A certified ``release_baseline_id`` may intentionally start a new campaign
lineage while an older live lineage still exists on the durability remote or
persistent volume.  Before a newly derived durability branch is published, the
source-owned contract must exactly describe the packaged ``state/`` tree.  This
keeps branch naming from becoming permission to seed an arbitrary or stale save.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CONTRACT_REL = Path("runtime/contracts/release-campaign-state.json")


def state_tree_sha256(root: Path) -> str:
    state = Path(root) / "state"
    digest = hashlib.sha256()
    files = sorted(
        (path for path in state.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(state).as_posix(),
    )
    for path in files:
        rel = path.relative_to(state).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_release_contract(root: Path) -> dict[str, Any]:
    value = json.loads((Path(root) / CONTRACT_REL).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("release campaign-state contract must be an object")
    return value


def verify_release_baseline_core(root: Path) -> list[str]:
    """Verify the generic source-owned campaign baseline contract.

    This deliberately checks only identity, chronology, and the complete state
    tree digest.  Game-specific acceptance still belongs to the maintained
    release verifier and playability tests.
    """
    errors: list[str] = []
    root = Path(root)
    try:
        contract = load_release_contract(root)
        meta = json.loads((root / "state/meta.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"release baseline inputs unreadable: {type(exc).__name__}: {exc}"]
    if not isinstance(meta, dict):
        return ["state/meta.json must be an object"]

    for actual_key, contract_key in (
        ("campaign_id", "campaign_id"),
        ("player_id", "player_id"),
        ("revision", "revision"),
        ("time", "world_time"),
    ):
        expected = contract.get(contract_key)
        actual = meta.get(actual_key)
        if actual != expected:
            errors.append(
                f"campaign baseline mismatch {actual_key}: expected {expected!r}, got {actual!r}"
            )

    expected_hash = contract.get("state_tree_sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        errors.append("release baseline state_tree_sha256 is invalid")
    else:
        actual_hash = state_tree_sha256(root)
        if actual_hash != expected_hash:
            errors.append(
                f"campaign state tree hash mismatch: expected {expected_hash}, got {actual_hash}"
            )

    baseline_id = contract.get("release_baseline_id")
    if not isinstance(baseline_id, str) or not baseline_id.strip():
        errors.append("release baseline id is missing")
    return errors


__all__ = [
    "CONTRACT_REL",
    "load_release_contract",
    "state_tree_sha256",
    "verify_release_baseline_core",
]
