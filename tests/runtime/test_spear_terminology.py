from __future__ import annotations

from sword_runtime.static_records import normalize_spear_loadout


def test_legacy_saved_loadout_normalizes_lance_metadata_without_state_write():
    """Legacy NPC/player equipment metadata reads as spear without mutating saves."""
    legacy = {
        "primary_melee_weapon": "weapon_spear",
        "shield_state_with_lance": "ready_offhand",
    }
    normalized = normalize_spear_loadout(legacy)
    assert normalized["primary_melee_weapon"] == "weapon_spear"
    assert normalized["shield_state_with_spear"] == "ready_offhand"
    assert "shield_state_with_lance" not in normalized
    assert legacy["shield_state_with_lance"] == "ready_offhand"
