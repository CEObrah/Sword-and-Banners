#!/usr/bin/env python3
"""Bind a Sword & Banners release candidate to its intended campaign snapshot."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_REL = Path("runtime/contracts/release-campaign-state.json")


def state_tree_sha256(root: Path) -> str:
    state = root / "state"
    digest = hashlib.sha256()
    files = sorted((p for p in state.rglob("*") if p.is_file()), key=lambda p: p.relative_to(state).as_posix())
    for path in files:
        rel = path.relative_to(state).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def verify_release_state(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        contract: dict[str, Any] = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"release campaign state contract unreadable: {exc}"]
    try:
        meta: dict[str, Any] = json.loads((root / "state/meta.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"state/meta.json unreadable: {exc}"]

    expected = {
        "campaign_id": contract.get("campaign_id"),
        "player_id": contract.get("player_id"),
        "revision": contract.get("revision"),
        "time": contract.get("world_time"),
    }
    actual = {
        "campaign_id": meta.get("campaign_id"),
        "player_id": meta.get("player_id"),
        "revision": meta.get("revision"),
        "time": meta.get("time"),
    }
    for key in expected:
        if actual[key] != expected[key]:
            errors.append(f"campaign baseline mismatch {key}: expected {expected[key]!r}, got {actual[key]!r}")

    expected_hash = str(contract.get("state_tree_sha256") or "")
    actual_hash = state_tree_sha256(root)
    if actual_hash != expected_hash:
        errors.append(f"campaign state tree hash mismatch: expected {expected_hash}, got {actual_hash}")
    return errors


def main() -> int:
    errors = verify_release_state(ROOT)
    if errors:
        print("RELEASE CAMPAIGN STATE FAILED")
        for error in errors:
            print(" -", error)
        return 1
    contract = json.loads((ROOT / CONTRACT_REL).read_text(encoding="utf-8"))
    print(
        "RELEASE CAMPAIGN STATE OK:",
        contract["release_baseline_id"],
        f"revision={contract['revision']}",
        f"state_sha256={contract['state_tree_sha256']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
