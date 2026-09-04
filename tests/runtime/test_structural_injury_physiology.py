from __future__ import annotations

import copy
import json
from pathlib import Path

from sword_runtime.anatomy import anatomy_function_factors, apply_structural_injury_state, resolve_structural_injury
from sword_runtime.personal_combat import (
    active_injury_rows,
    advance_injury_physiology,
    injury_physiology_snapshot,
    recover_injury_physiology,
    sync_injury_record,
)


ROOT = Path(__file__).resolve().parents[2]


def _mechanics():
    return json.loads((ROOT / "game/data/mechanics/injury.json").read_text())


def _fighter() -> dict:
    return {
        "attributes": {
            "Toughness": 100,
            "Composure": 100,
            "Endurance": 100,
            "Coordination": 100,
        },
        "injuries": [],
        "physiology_state": {
            "blood_loss_units": 0.0,
            "respiratory_failure_equivalent_seconds": 0.0,
        },
    }


def test_structural_injury_is_deterministic_and_structure_specific():
    args = dict(
        zone="forearms_hands",
        structure="wrist",
        side="right",
        mode="cut",
        severity="serious",
        impact_index=80.0,
        penetration_index=70.0,
        contact_grade="clean",
        seed=0,
    )
    first = resolve_structural_injury(**args)
    second = resolve_structural_injury(**args)
    assert first == second
    assert len(first["damaged_structures"]) == 2
    assert {row["category"] for row in first["damaged_structures"]} == {"joint", "tendon"}
    assert first["functional_effects"]["attack_factor"] < 0.5
    assert first["functional_effects"]["parry_factor"] < 0.5


def test_eye_trauma_has_immediate_visual_function_effects_before_destruction():
    result = resolve_structural_injury(
        zone="head", structure="eye", side="right", mode="blunt",
        severity="serious", impact_index=70.0, penetration_index=15.0,
        contact_grade="clean", seed=4,
    )
    assert result["damaged_structures"][0]["category"] == "eye"
    assert result["functional_effects"]["vision_factor"] <= 0.18
    assert result["functional_effects"]["ranged_targeting_factor"] <= 0.20

    person = {}
    apply_structural_injury_state(person, result, at="244-BCE-01-01T00:00:00+08:00", source_weapon="weapon_test")
    factors = anatomy_function_factors(person)
    assert factors["right_eye_function"] <= 0.18
    assert 0.45 < factors["ranged_targeting_factor"] < 0.70


def test_thoracic_thrust_can_create_exact_respiratory_compromise():
    result = resolve_structural_injury(
        zone="upper_torso",
        structure="upper_torso",
        side="midline",
        mode="thrust",
        severity="serious",
        impact_index=100.0,
        penetration_index=100.0,
        contact_grade="clean",
        seed=6,
    )
    assert any(row["category"] == "lung" for row in result["damaged_structures"])
    assert result["respiratory_compromise"] == 58.0


def test_primary_injury_mirror_does_not_double_count_bleeding_after_reload():
    fighter = _fighter()
    wound = {
        "injury_id": "combat:test:1",
        "label": "serious cut wound to wrist",
        "severity": "serious",
        "severity_index": 3,
        "body_zone": "forearms_hands",
        "contact_structure": "wrist",
        "mechanism": "cut",
        "bleeding": {"rate_units_per_minute": 20.0, "controlled": False},
        "pain": 55.0,
        "active": True,
    }
    fighter["injuries"] = [copy.deepcopy(wound)]
    fighter["injury_state"] = copy.deepcopy(wound)
    assert len(active_injury_rows(fighter)) == 1
    assert injury_physiology_snapshot(fighter)["bleeding"] == 20.0


def test_blood_loss_advances_by_actual_seconds_and_can_cause_shock_incapacitation():
    fighter = _fighter()
    wound = {
        "injury_id": "combat:test:2",
        "label": "serious cut wound to forearm",
        "severity": "serious",
        "severity_index": 3,
        "body_zone": "forearms_hands",
        "contact_structure": "forearm",
        "mechanism": "cut",
        "bleeding": {"rate_units_per_minute": 30.0, "controlled": False},
        "pain": 55.0,
        "active": True,
    }
    fighter["injuries"] = [wound]
    after_30s = advance_injury_physiology(fighter, _mechanics(), elapsed_seconds=30.0)
    assert after_30s["blood"] == 15.0
    assert after_30s["state"] == "incapacitated"
    assert fighter["physiology_state"]["consciousness"] == "unconscious"


def test_controlled_bleeding_stops_further_blood_loss_but_not_existing_loss():
    fighter = _fighter()
    wound = {
        "injury_id": "combat:test:3",
        "label": "moderate cut wound",
        "severity": "moderate",
        "severity_index": 2,
        "body_zone": "upper_arms",
        "mechanism": "cut",
        "bleeding": {"rate_units_per_minute": 6.0, "controlled": False},
        "pain": 30.0,
        "active": True,
    }
    fighter["injuries"] = [wound]
    advance_injury_physiology(fighter, _mechanics(), elapsed_seconds=60.0)
    assert fighter["physiology_state"]["blood_loss_units"] == 6.0
    wound["bleeding"]["controlled"] = True
    advance_injury_physiology(fighter, _mechanics(), elapsed_seconds=120.0)
    assert fighter["physiology_state"]["blood_loss_units"] == 6.0


def test_major_vessel_contact_creates_exact_source_bleeding_not_generic_only():
    found = None
    for seed in range(64):
        result = resolve_structural_injury(
            zone="forearms_hands", structure="wrist", side="right", mode="cut",
            severity="serious", impact_index=90.0, penetration_index=90.0,
            contact_grade="clean", seed=seed,
        )
        if any(row["category"] == "major_vessel" for row in result["damaged_structures"]):
            found = result
            break
    assert found is not None
    assert found["major_vessel_damage"] is True
    assert found["bleeding_units_per_minute"] >= 38.0
    assert any(row["category"] == "major_vessel" for row in found["bleeding_sources"])


def test_critical_knee_blunt_damage_can_destroy_load_bearing_structure_and_mobility():
    result = resolve_structural_injury(
        zone="lower_legs_feet", structure="knee", side="left", mode="blunt",
        severity="critical", impact_index=180.0, penetration_index=10.0,
        contact_grade="exceptional", seed=3,
    )
    assert any(row["category"] in {"bone", "joint"} for row in result["damaged_structures"])
    assert result["functional_effects"]["movement_factor"] <= 0.06


def test_permanent_exact_substructure_sequela_survives_wound_record_resolution():
    person = {}
    resolution = {
        "side": "right",
        "external_structure": "wrist",
        "severity_index": 4,
        "damaged_structures": [
            {"structure": "flexor_tendons", "category": "tendon", "status": "severed", "severity_index": 4, "permanent_sequela": True},
        ],
    }
    changed = apply_structural_injury_state(person, resolution, at="244-BCE-01-01T00:00:00+08:00", source_weapon="weapon_test")
    assert changed == ["right:flexor_tendons"]
    factors = anatomy_function_factors(person)
    assert factors["right_hand_function"] <= 0.10
    assert 0.50 < factors["attack_factor"] < 0.80
    assert person["anatomy_state"]["structural_damage"]["right:flexor_tendons"]["permanent_sequela"] is True


def test_multiple_wounds_add_bleeding_shock_and_compound_respiratory_loss():
    fighter = _fighter()
    wound_a = {
        "injury_id": "combat:multi:a", "severity": "moderate", "severity_index": 2,
        "bleeding": {"rate_units_per_minute": 4.0, "controlled": False}, "pain": 30.0,
        "respiratory_compromise": 20.0, "active": True,
    }
    wound_b = {
        "injury_id": "combat:multi:b", "severity": "serious", "severity_index": 3,
        "bleeding": {"rate_units_per_minute": 10.0, "controlled": False}, "pain": 55.0,
        "respiratory_compromise": 30.0, "active": True,
    }
    fighter["injuries"] = [wound_a, wound_b]
    snapshot = injury_physiology_snapshot(fighter)
    assert snapshot["bleeding"] == 14.0
    assert snapshot["severity_sum"] == 5.0
    assert round(snapshot["respiratory"], 6) == 44.0
    assert snapshot["shock"] > 3 * 18.0 + 14.0


def test_compensated_respiratory_loss_does_not_accumulate_failure_but_uncompensated_does():
    fighter = _fighter()
    wound = {
        "injury_id": "combat:resp", "severity": "moderate", "severity_index": 2,
        "bleeding": {"rate_units_per_minute": 0.0, "controlled": True}, "pain": 20.0,
        "respiratory_compromise": 30.0, "active": True,
    }
    fighter["injuries"] = [wound]
    advance_injury_physiology(fighter, _mechanics(), elapsed_seconds=120.0)
    assert fighter["physiology_state"]["respiratory_failure_equivalent_seconds"] == 0.0
    wound["respiratory_compromise"] = 70.0
    advance_injury_physiology(fighter, _mechanics(), elapsed_seconds=60.0)
    assert fighter["physiology_state"]["respiratory_failure_equivalent_seconds"] > 30.0


def test_stable_recovery_restores_blood_volume_without_reopening_wound():
    fighter = _fighter()
    wound = {
        "injury_id": "combat:recovery", "severity": "moderate", "severity_index": 2,
        "bleeding": {"rate_units_per_minute": 0.0, "controlled": True}, "pain": 15.0,
        "respiratory_compromise": 0.0, "active": True,
    }
    fighter["injuries"] = [copy.deepcopy(wound)]
    fighter["injury_state"] = copy.deepcopy(wound)
    fighter["physiology_state"]["blood_loss_units"] = 20.0
    fighter["physiology_state"]["respiratory_failure_equivalent_seconds"] = 30.0
    after = recover_injury_physiology(fighter, _mechanics(), elapsed_hours=5.0)
    assert after["blood"] == 10.0
    assert fighter["physiology_state"]["respiratory_failure_equivalent_seconds"] == 0.0
    assert active_injury_rows(fighter)[0]["active"] is True


def test_sync_injury_record_updates_mirror_and_ledger_together():
    fighter = _fighter()
    wound = {
        "injury_id": "combat:sync", "severity": "serious", "severity_index": 3,
        "bleeding": {"rate_units_per_minute": 20.0, "controlled": False}, "active": True,
    }
    fighter["injuries"] = [copy.deepcopy(wound)]
    fighter["injury_state"] = copy.deepcopy(wound)
    wound["bleeding"]["controlled"] = True
    wound["bleeding"]["rate_units_per_minute"] = 0.0
    sync_injury_record(fighter, wound)
    assert fighter["injury_state"]["bleeding"]["controlled"] is True
    assert fighter["injuries"][0]["bleeding"]["controlled"] is True
    assert injury_physiology_snapshot(fighter)["bleeding"] == 0.0
