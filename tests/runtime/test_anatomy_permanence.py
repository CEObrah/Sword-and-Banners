from __future__ import annotations

import copy
import json

from conftest import execute
from sword_runtime.anatomy import (
    anatomy_function_factors,
    apply_irreversible_anatomy,
    resolve_anatomical_contact,
)


def test_clean_cut_can_establish_exact_permanent_wrist_severance():
    result = resolve_anatomical_contact(
        zone="forearms_hands",
        mode="cut",
        impact_index=110.0,
        channel_protection=30.0,
        contact_grade="clean",
        declared_intent="cut through the right wrist to disable the weapon hand",
        seed=7,
    )
    assert result["irreversible"] is True
    assert result["outcome"] == "complete_severance"
    assert result["structure"] == "wrist"
    assert result["required_impact_index"] == 91.5

    person = {"owner_id": "char_test", "health_status": "injured"}
    changed = apply_irreversible_anatomy(person, result, at="244-BCE-07-29T20:22:48+08:00", source_weapon="weapon_sword_one_hand")
    assert changed == ["right_wrist", "right_hand"]
    anatomy = person["anatomy_state"]["structures"]
    assert anatomy["right_wrist"]["status"] == "severed"
    assert anatomy["right_hand"]["status"] == "absent"
    assert anatomy["right_hand"]["reversible_by_normal_recovery"] is False


def test_glancing_or_insufficient_cut_does_not_invent_amputation():
    weak = resolve_anatomical_contact(
        zone="forearms_hands",
        mode="cut",
        impact_index=70.0,
        channel_protection=30.0,
        contact_grade="clean",
        declared_intent="right wrist",
        seed=1,
    )
    glancing = resolve_anatomical_contact(
        zone="forearms_hands",
        mode="cut",
        impact_index=140.0,
        channel_protection=30.0,
        contact_grade="glancing",
        declared_intent="right wrist",
        seed=1,
    )
    assert weak["irreversible"] is False
    assert glancing["irreversible"] is False


def test_permanent_anatomy_changes_future_combat_function():
    person = {}
    result = {
        "irreversible": True,
        "outcome": "complete_severance",
        "side": "left",
        "structure": "lower_leg",
    }
    apply_irreversible_anatomy(person, result, at="244-BCE-07-29T20:22:48+08:00", source_weapon="weapon_glaive")
    factors = anatomy_function_factors(person)
    assert factors["movement_factor"] < 0.30
    assert person["anatomy_state"]["structures"]["left_foot"]["status"] == "absent"


def test_health_recovery_heals_wound_but_never_regenerates_absent_hand(campaign):
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    player["anatomy_state"] = {
        "rule": "Absent or destroyed anatomy is permanent.",
        "structures": {
            "right_wrist": {"status": "severed", "permanent": True, "reversible_by_normal_recovery": False},
            "right_hand": {"status": "absent", "permanent": True, "reversible_by_normal_recovery": False},
        },
        "permanent_impairments": [],
    }
    player["injury_state"] = {
        "label": "critical cut wound to right wrist",
        "severity": "critical",
        "minimum_recovery_hours": 8,
        "recovered_hours": 0,
        "active": True,
        "permanent_anatomy": True,
        "anatomical_outcome": "complete_severance",
    }
    if isinstance(player.get("health"), dict):
        player["health"]["status"] = "injured"
    else:
        player["health_status"] = "injured"
    player_path.write_text(json.dumps(player, indent=2, sort_keys=True) + "\n")

    # Commit the fixture mutation because production commands are Git-backed.
    import subprocess
    subprocess.run(["git", "-C", str(campaign), "add", "state/player.json"], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test permanent anatomy fixture"], check=True)

    execute(campaign, "health_recovery", {"hours": 8}, request_id="permanent-anatomy-recovery")
    after = json.loads(player_path.read_text())
    assert after["injury_state"]["active"] is False
    assert after["injury_state"]["healed_with_permanent_sequelae"] is True
    assert after["anatomy_state"]["structures"]["right_hand"]["status"] == "absent"
    assert after["anatomy_state"]["structures"]["right_wrist"]["status"] == "severed"
