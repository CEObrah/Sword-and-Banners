from __future__ import annotations

import copy
import json

from conftest import execute
from sword_runtime.anatomy import (
    anatomy_activity_factor,
    anatomy_function_factors,
    anatomy_function_profile,
    apply_irreversible_anatomy,
    apply_structural_injury_state,
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
    changed = apply_irreversible_anatomy(person, result, at="244-BCE-07-29T20:22:48+08:00", source_weapon="weapon_sword")
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


def test_one_destroyed_eye_is_monocular_while_two_destroyed_eyes_remove_visual_targeting():
    person = {}
    left = {"irreversible": True, "outcome": "eye_destroyed", "side": "left", "structure": "eye"}
    right = {"irreversible": True, "outcome": "eye_destroyed", "side": "right", "structure": "eye"}

    apply_irreversible_anatomy(person, left, at="244-BCE-01-01T00:00:00+08:00", source_weapon="weapon_test")
    one_eye = anatomy_function_factors(person)
    assert one_eye["left_eye_function"] == 0.0
    assert one_eye["right_eye_function"] == 1.0
    assert 0.40 <= one_eye["depth_perception_factor"] <= 0.50
    assert 0.60 <= one_eye["ranged_targeting_factor"] < 0.75
    assert one_eye["awareness_factor"] > 0.80

    apply_irreversible_anatomy(person, right, at="244-BCE-01-01T00:01:00+08:00", source_weapon="weapon_test")
    blind = anatomy_function_factors(person)
    assert blind["vision_factor"] == 0.0
    assert blind["visual_detection_factor"] == 0.0
    assert blind["depth_perception_factor"] == 0.0
    assert blind["ranged_targeting_factor"] == 0.0
    assert 0.30 <= blind["attack_factor"] <= 0.40
    assert 0.40 <= blind["awareness_factor"] <= 0.50


def test_health_recovery_heals_wound_but_never_regenerates_absent_hand(campaign):
    player_path = campaign / "state/player.json"
    player = json.loads(player_path.read_text())
    player["anatomy_state"] = {
        "rule": "Absent or destroyed anatomy is permanent.",
        "structures": {
            "right_wrist": {"status": "severed", "permanent": True, "reversible_by_normal_recovery": False},
            "right_hand": {"status": "absent", "permanent": True, "reversible_by_normal_recovery": False},
        },
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


def test_severed_achilles_is_permanent_and_burdens_gait_running_riding_and_labor():
    person = {}
    resolution = {
        "side": "left",
        "severity_index": 4,
        "damaged_structures": [
            {
                "structure": "achilles_tendon",
                "category": "tendon",
                "status": "severed",
                "severity_index": 4,
                "permanent_sequela": True,
            }
        ],
    }
    changed = apply_structural_injury_state(
        person, resolution, at="244-BCE-01-01T00:00:00+08:00", source_weapon="weapon_sword"
    )
    assert changed == ["left:achilles_tendon"]
    row = person["anatomy_state"]["structural_damage"]["left:achilles_tendon"]
    assert row["status"] == "severed"
    assert row["permanent_sequela"] is True
    assert row["reversible_by_ordinary_recovery"] is False

    f = anatomy_function_profile(person)
    assert f["left_leg_function"] == 0.10
    assert f["right_leg_function"] == 1.0
    assert f["running_factor"] < f["walking_factor"] < f["standing_factor"] < 0.60
    assert anatomy_activity_factor(person, "foot_travel") < 0.40
    assert anatomy_activity_factor(person, "running") < 0.30
    assert anatomy_activity_factor(person, "riding") < 0.60
    assert anatomy_activity_factor(person, "construction") < 0.75


def test_missing_arm_preserves_skill_but_denies_bilateral_body_functions():
    person = {"skills": {"Sword": 170, "Bow": 160}}
    apply_irreversible_anatomy(
        person,
        {"irreversible": True, "outcome": "complete_severance", "side": "right", "structure": "upper_arm"},
        at="244-BCE-01-01T00:00:00+08:00",
        source_weapon="weapon_glaive",
    )
    f = anatomy_function_profile(person)
    assert person["skills"]["Sword"] == 170
    assert person["skills"]["Bow"] == 160
    assert f["right_hand_function"] == 0.0
    assert f["left_hand_function"] == 1.0
    assert f["usable_hands"] == 1
    assert f["bilateral_hand_factor"] == 0.0
    assert anatomy_activity_factor(person, "bow") <= 0.02
    assert anatomy_activity_factor(person, "two_handed_weapon") <= 0.02
    assert 0.50 < anatomy_activity_factor(person, "sword") < 0.80
    assert anatomy_activity_factor(person, "lifting") < anatomy_activity_factor(person, "self_care")


def test_lower_body_permanent_disability_has_distinct_severity_ordering():
    healthy = anatomy_function_profile({})

    achilles = {}
    apply_structural_injury_state(
        achilles,
        {"side": "left", "severity_index": 4, "damaged_structures": [
            {"structure": "achilles_tendon", "category": "tendon", "status": "severed", "severity_index": 4, "permanent_sequela": True}
        ]},
        at="244-BCE-01-01T00:00:00+08:00", source_weapon="weapon_sword",
    )

    knee = {}
    apply_irreversible_anatomy(
        knee,
        {"irreversible": True, "outcome": "joint_destroyed", "side": "left", "structure": "knee"},
        at="244-BCE-01-01T00:00:00+08:00", source_weapon="weapon_glaive",
    )

    missing = {}
    apply_irreversible_anatomy(
        missing,
        {"irreversible": True, "outcome": "complete_severance", "side": "left", "structure": "thigh"},
        at="244-BCE-01-01T00:00:00+08:00", source_weapon="weapon_glaive",
    )

    a = anatomy_function_profile(achilles)
    k = anatomy_function_profile(knee)
    m = anatomy_function_profile(missing)
    for key in ("walking_factor", "running_factor", "standing_factor", "balance_factor", "climbing_factor", "riding_factor", "physical_labor_factor"):
        assert m[key] < k[key] < a[key] < healthy[key], key


def test_missing_leg_does_not_behave_like_a_normal_slow_walk():
    person = {}
    apply_irreversible_anatomy(
        person,
        {"irreversible": True, "outcome": "complete_severance", "side": "left", "structure": "thigh"},
        at="244-BCE-01-01T00:00:00+08:00",
        source_weapon="weapon_glaive",
    )
    f = anatomy_function_profile(person)
    assert f["left_leg_function"] == 0.0
    assert f["walking_factor"] <= 0.18
    assert f["running_factor"] <= 0.055
    assert f["standing_factor"] <= 0.28
    assert f["crawling_factor"] > f["running_factor"]
    assert anatomy_activity_factor(person, "running") < anatomy_activity_factor(person, "foot_travel")
