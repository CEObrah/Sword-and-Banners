#!/usr/bin/env python3
"""Synchronize the runtime/Skill compatibility fingerprint.

The fingerprint binds the Skill to runtime source, MCP contracts, game content,
schemas and dependency declarations. Token markers are normalized before hashing.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master"
SKILL_ENTRY = SKILL_ROOT / "SKILL.md"
RUNTIME_CONTRACT = ROOT / "runtime/sword_runtime/gm_skill_contract.py"
SKILL_MARKER = re.compile(r"(?m)^GM_SKILL_CONTRACT_TOKEN: [0-9a-f]{64}$")
RUNTIME_MARKER = re.compile(r'(?m)^GM_SKILL_CONTRACT_TOKEN = "[0-9a-f]{64}"$')
def skill_tree_token() -> str:
    # Retain the helper name for existing release callers.
    sys.path.insert(0, str(ROOT / 'runtime'))
    from sword_runtime.release_identity import release_fingerprints
    return release_fingerprints(ROOT)['release_contract_sha256']


def _current_values() -> tuple[str, str]:
    skill_text = SKILL_ENTRY.read_text(encoding="utf-8")
    runtime_text = RUNTIME_CONTRACT.read_text(encoding="utf-8")
    skill_match = SKILL_MARKER.search(skill_text)
    runtime_match = RUNTIME_MARKER.search(runtime_text)
    if skill_match is None or runtime_match is None:
        raise RuntimeError("GM skill contract markers are missing")
    return skill_match.group(0).split(": ", 1)[1], runtime_match.group(0).split('"', 2)[1]


def synchronize(*, check: bool) -> str:
    token = skill_tree_token()
    current_skill, current_runtime = _current_values()
    if check:
        if current_skill != token or current_runtime != token:
            raise RuntimeError(
                "GM Skill contract is stale; run tools/sync_gm_skill_contract.py"
            )
        return token

    skill_text = SKILL_ENTRY.read_text(encoding="utf-8")
    runtime_text = RUNTIME_CONTRACT.read_text(encoding="utf-8")
    skill_text, skill_count = SKILL_MARKER.subn(
        f"GM_SKILL_CONTRACT_TOKEN: {token}", skill_text
    )
    runtime_text, runtime_count = RUNTIME_MARKER.subn(
        f'GM_SKILL_CONTRACT_TOKEN = "{token}"', runtime_text
    )
    if skill_count != 1 or runtime_count != 1:
        raise RuntimeError("GM Skill contract markers are not unique")
    SKILL_ENTRY.write_text(skill_text, encoding="utf-8")
    RUNTIME_CONTRACT.write_text(runtime_text, encoding="utf-8")
    return token


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        token = synchronize(check=args.check)
    except RuntimeError as exc:
        print(f"GM SKILL CONTRACT FAILED: {exc}")
        return 1
    print(f"GM SKILL CONTRACT {'OK' if args.check else 'SYNCED'}: {token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
