from __future__ import annotations

import json
import re

from sword_runtime.static_records import normalize_spear_loadout


_LANCE_TOKEN = re.compile(r"(?:^|[._-])lance(?:$|[._-])", re.IGNORECASE)


def _mechanical_lance_key(key: str) -> bool:
    normalized = key.casefold()
    if "red_lance" in normalized:
        return False
    return bool(_LANCE_TOKEN.search(normalized))


def _walk_keys(value, *, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _mechanical_lance_key(key_text):
                yield child_path
            yield from _walk_keys(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keys(child, path=f"{path}[{index}]")


def test_canonical_game_json_has_no_mechanical_lance_keys(campaign):
    """New canonical game data uses spear keys; Red Lance proper-name IDs remain valid."""
    problems: list[str] = []
    root = campaign / "game"
    for file_path in sorted(root.rglob("*.json")):
        document = json.loads(file_path.read_text(encoding="utf-8"))
        for object_path in _walk_keys(document):
            problems.append(f"{file_path.relative_to(campaign)}:{object_path}")
    assert not problems, "canonical mechanical lance keys remain; use spear semantics:\n" + "\n".join(problems)


def test_legacy_saved_loadout_normalizes_lance_metadata_without_state_write():
    legacy = {
        "primary_melee_weapon": "weapon_spear",
        "shield_state_with_lance": "ready_offhand",
    }
    normalized = normalize_spear_loadout(legacy)
    assert normalized["primary_melee_weapon"] == "weapon_spear"
    assert normalized["shield_state_with_spear"] == "ready_offhand"
    assert "shield_state_with_lance" not in normalized
    assert legacy["shield_state_with_lance"] == "ready_offhand"
