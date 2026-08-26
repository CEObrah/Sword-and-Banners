from __future__ import annotations

import json
from pathlib import Path


def _walk_keys(value, *, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if "lance" in key_text.casefold():
                yield child_path
            yield from _walk_keys(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keys(child, path=f"{path}[{index}]")


def test_persisted_json_has_no_mechanical_lance_keys(campaign):
    """Lance is not an equipment semantic; Red Lance remains a proper name value.

    Scan persisted/static JSON keys rather than string values so organization IDs,
    display names, and historical proper names remain untouched while stale fields
    such as shield_state_with_lance cannot silently survive on NPCs or troop data.
    """
    problems: list[str] = []
    for root_name in ("game", "state"):
        root = campaign / root_name
        for path in sorted(root.rglob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for key_path in _walk_keys(document):
                problems.append(f"{path.relative_to(campaign)}:{key_path}")
    assert not problems, "mechanical lance keys remain; use spear semantics:\n" + "\n".join(problems)
