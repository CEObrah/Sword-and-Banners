from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sword_runtime.cohort_personnel import release_external_formation_allocations, validate_cohort_ledger
from sword_runtime.combat_capability import CombatCapabilityMixin
from sword_runtime.warfare_depth import build_formation_command_structure, build_mercenary_command_structure


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _rules() -> dict:
    return json.loads((_root() / "game/data/mechanics/warfare-organization.json").read_text())


def _hierarchy(structure: dict) -> dict[int, int]:
    return {int(row["scale"]): int(row["count"]) for row in structure["internal_hierarchy"]}


def test_static_warfare_rules_do_not_snapshot_current_tang_wei_campaign_organization():
    rules = _rules()
    assert "qin_border_detachment" not in rules
    assert "tang_wei_house_contingent" not in rules

def test_four_arm_2100_unit_uses_one_top_commander_and_subordinate_echelons():
    formation = {
        "formation_ref": "formation_test_four_arm_2100",
        "owner_force_ref": "force_state_qin",
        "personnel": 2100,
        "authorized_strength": 2100,
        "formation_class": "unit",
        "commander_ref": "char_test_commander",
        "composition": {"line_infantry": 1500, "archer": 300, "light_cavalry": 200, "heavy_cavalry": 100},
    }
    structure = build_formation_command_structure(formation, _rules())
    assert structure["fighting_establishment"] == 2100
    assert structure["unit_command"]["commander_billets"] == 1
    assert structure["unit_command"]["target_bodies"] == 1
    assert structure["unit_command"]["effective_billets_staffed"] == 1
    assert structure["unit_command"]["named_commander_ref"] == "char_test_commander"
    assert _hierarchy(structure) == {1000: 2, 500: 4, 100: 21}
    assert structure["attached_personnel_target"] == 2101

def test_unit_top_command_counts_only_the_saved_commander():
    formation = {
        "formation_ref": "formation_test_unit_command",
        "owner_force_ref": "force_state_qin",
        "personnel": 2000,
        "authorized_strength": 2000,
        "formation_class": "unit",
        "commander_ref": "char_test_commander",
    }
    structure = build_formation_command_structure(formation, _rules())
    assert structure["unit_command"]["target_bodies"] == 1
    assert structure["unit_command"]["effective_billets_staffed"] == 1
    assert structure["unit_command"]["staffing_shortfall"] == 0

def test_current_red_lance_leaf_has_one_external_top_commander():
    formation = json.loads((_root() / "state/formations/red-lance-a.json").read_text())
    structure = build_formation_command_structure(formation, _rules())
    assert structure["fighting_establishment"] == 500
    assert structure["unit_command"]["named_commander_ref"] == formation["commander_ref"] == "char_duan_jin"
    assert [(r["scale"], r["count"], r["representation"]) for r in structure["internal_hierarchy"]] == [(100, 5, "aggregate")]

def test_generic_state_army_uses_same_hierarchy_without_materializing_officers():
    formation = {
        "formation_ref": "formation_state_generic_8000",
        "owner_force_ref": "force_state_zhao",
        "personnel": 8000,
    }
    structure = build_formation_command_structure(formation, _rules())

    assert _hierarchy(structure) == {1000: 8, 500: 16, 100: 80}
    assert structure["internal_commander_assignments"] == 104
    assert structure["authorized_strength"] == 8000
    assert structure["unit_command"]["representation"] == "aggregate"
    assert all(row["representation"] == "aggregate" for row in structure["internal_hierarchy"])
    assert "representation_policy" not in structure
    assert structure["staffing_status"] == "internal_leadership_only"


def test_1200_current_strength_is_a_lawful_100_man_increment_establishment():
    formation = {
        "formation_ref": "formation_house_example",
        "owner_force_ref": "force_house_example",
        "personnel": 1200,
    }
    structure = build_formation_command_structure(formation, _rules())
    assert structure["formation_class"] == "unit"
    assert structure["authorized_strength"] == 1200
    assert _hierarchy(structure) == {500: 2, 100: 12}
    assert all(row["representation"] == "aggregate" for row in structure["internal_hierarchy"])

def test_mercenary_company_carves_command_and_support_from_existing_total_headcount():
    company = {
        "schema": "mercenary-company",
        "owner_id": "merc.major.03",
        "headcount": 2600,
        "troop_pools": [
            {"role": "cavalry", "troop_type": "cavalry", "count": 1560},
            {"role": "light_infantry", "troop_type": "light_infantry", "specialty": "reconnaissance", "count": 390},
            {"role": "dismounted_line", "troop_type": "line_infantry", "count": 338},
            {"role": "support", "troop_type": "support_staff", "count": 312},
        ],
    }
    before = copy.deepcopy(company)
    structure = build_mercenary_command_structure(company, _rules())
    by_scale = {int(row["scale"]): row for row in structure["internal_hierarchy"]}

    assert company == before
    assert structure["projection_kind"] == "mercenary_command_structure"
    assert "schema" not in structure
    assert structure["company_headcount"] == 2600
    assert structure["troop_pool_headcount"] == 2600
    assert structure["fighting_establishment"] == 2288
    assert structure["existing_non_fighting_personnel"] == 312
    assert structure["attached_personnel_target"] == 2600
    assert structure["attached_personnel_delta"] == 0
    assert structure["unit_command"]["inside_total_headcount"] is True
    assert structure["unit_command"]["representation"] == "aggregate"
    assert _hierarchy(structure) == {1000: 3, 500: 5, 100: 23}
    assert by_scale[1000]["full_elements"] == 2
    assert by_scale[1000]["partial_tail_personnel"] == 288
    assert by_scale[500]["full_elements"] == 4
    assert by_scale[500]["partial_tail_personnel"] == 288
    assert by_scale[100]["full_elements"] == 22
    assert by_scale[100]["partial_tail_personnel"] == 88
    assert structure["internal_commander_assignments"] == 31
    assert all(row["representation"] == "aggregate" for row in structure["internal_hierarchy"])
    assert "routine_support_functions" not in structure


def test_external_personnel_are_first_class_force_conservation_not_phantom_bodies():
    force = {
        "headcount": 20,
        "available_by_role": {"signal": 15},
        "available_by_location": {"loc_a": {"signal": 15}},
        "allocated_to_formations": {},
        "materialized_people": {},
        "materialized_assignments": {},
        "external_personnel_allocations": {"formation_x": {"signal": 5}},
        "cohort_ledger": {
            "cohorts": {
                "cohort_signal": {
                    "role": "signal",
                    "reserve_by_location": {"loc_a": 15},
                    "allocated_by_formation": {},
                    "allocated_external_by_formation": {"formation_x": 5},
                }
            }
        },
    }
    validate_cohort_ledger(force)
    broken = copy.deepcopy(force)
    broken["external_personnel_allocations"]["formation_x"]["signal"] = 4
    with pytest.raises(ValueError, match="external personnel allocation mismatch"):
        validate_cohort_ledger(broken)


def test_external_personnel_release_returns_exact_bodies_to_force_and_cohort_reserve():
    force = {
        "headcount": 20,
        "available_by_role": {"signal": 15},
        "available_by_location": {"loc_a": {"signal": 15}},
        "allocated_to_formations": {},
        "materialized_people": {},
        "materialized_assignments": {},
        "external_personnel_allocations": {"formation_x": {"signal": 5}},
        "cohort_ledger": {
            "cohorts": {
                "cohort_signal": {
                    "role": "signal",
                    "reserve_by_location": {"loc_a": 15},
                    "allocated_by_formation": {},
                    "allocated_external_by_formation": {"formation_x": 5},
                }
            }
        },
    }

    released = release_external_formation_allocations(
        force, formation_ref="formation_x", location_ref="loc_a"
    )

    assert released == {"signal": 5}
    assert force["external_personnel_allocations"] == {}
    assert force["available_by_role"] == {"signal": 20}
    assert force["available_by_location"] == {"loc_a": {"signal": 20}}
    cohort = force["cohort_ledger"]["cohorts"]["cohort_signal"]
    assert cohort["reserve_by_location"] == {"loc_a": 20}
    assert cohort["allocated_external_by_formation"] == {}
    validate_cohort_ledger(force)


def test_house_tang_mercenaries_have_role_specific_quarterly_training_rules():
    cfg = _rules()["mercenary_training"]
    assert cfg["review_kind"] == "quarterly_autonomy"
    assert set(cfg["hours_per_review_by_status"]) >= {"available", "contracted", "deployed"}
    assert "contracted_defense" not in cfg["hours_per_review_by_status"]
    assert "house_tang_contracted_defense_overrides" not in cfg
    assert cfg["doctrine_familiarity_gain_per_review"] > 0
    tokens = {token for row in cfg["focus_profiles"] for token in row["tokens"]}
    assert {"countermining", "artillery", "heavy_infantry", "signal", "logistics"}.issubset(tokens)
    assert "diminishing-return training" in cfg["rule"]


def test_command_combat_effects_are_scale_bounded_without_support_headcount_multiplier():
    class Harness(CombatCapabilityMixin):
        def read(self, path: str):
            if path == "game/data/mechanics/warfare-organization.json":
                return _rules()
            raise AssertionError(path)

    formation = {
        "personnel": 8000,
        "authorized_strength": 8000,
        "formation_class": "unit",
        "training_progress": 80,
        "cohesion": 80,
        "commander_ref": "char_test_commander",
    }
    named = [
        {"role": "commander", "command_score": 100, "command_available": True},
        {"role": "staff", "command_score": 90, "command_available": True},
    ]
    effects = Harness()._combat_command_effects(formation, named)
    assert 1.0 < effects["combined_factor"] <= _rules()["command_effect_scales"]["combined_cap"]
    assert effects["local"] > 1.0
    assert effects["maneuver"] > 1.0
    assert effects["operational"] > 1.0
    assert effects["unit"] > 1.0
    assert "support" not in effects




def test_high_potential_representation_requires_saved_evidence_not_billet_status():
    policy = _rules()["officer_representation_policy"]
    assert policy["default_representation"] == "aggregate"
    assert "saved_high_potential_evidence" in policy["person_lite_triggers"]
    assert "never inferred from holding a billet" in policy["high_potential_evidence_rule"]
    assert "reclassifies one already conserved body" in policy["materialization_rule"]




def test_casualties_do_not_auto_derank_surviving_internal_command_echelons():
    rules = _rules()
    formation = {
        "formation_ref": "formation_shattered_veteran_unit",
        "owner_force_ref": "force_state_qin",
        "personnel": 480,
        "commander_ref": "char_external_commander",
        "command_structure": {
            "internal_hierarchy": [
                {"scale": 1000, "count": 5, "representation": "person_lite", "inside_fighting_establishment": True},
                {"scale": 500, "count": 10, "representation": "person_lite", "inside_fighting_establishment": True},
                {"scale": 100, "count": 50, "representation": "aggregate", "inside_fighting_establishment": True},
            ]
        },
    }
    structure = build_formation_command_structure(formation, rules)
    assert _hierarchy(structure) == {1000: 5, 500: 10, 100: 50}
    assert structure["fighting_establishment"] == 480
    assert structure["formation_class"] == "unit"
    assert structure["authorized_strength"] == 5000
    # Nominal echelon size is durable establishment, not a live headcount clamp.
    assert structure["internal_hierarchy"][0]["full_elements"] == 0
    assert structure["internal_hierarchy"][0]["partial_tail_personnel"] == 480


def test_unit_top_echelon_is_never_repeated_as_internal_command():
    rules = _rules()
    cases = {
        500: {500: 0, 1000: 0, 100: 5},
        1000: {1000: 0, 500: 2, 100: 10},
        1500: {1000: 0, 500: 3, 100: 15},
        2000: {1000: 2, 500: 4, 100: 20},
        2100: {1000: 2, 500: 4, 100: 21},
    }
    for strength, expected in cases.items():
        formation = {
            "formation_ref": f"formation_test_{strength}",
            "owner_force_ref": "force_test",
            "personnel": strength,
            "authorized_strength": strength,
            "formation_class": "unit",
            "commander_ref": "char_test_commander",
        }
        structure = build_formation_command_structure(formation, rules)
        hierarchy = _hierarchy(structure)
        assert all(scale < strength for scale in hierarchy)
        for scale, count in expected.items():
            assert hierarchy.get(scale, 0) == count
        assert structure["unit_command"]["named_commander_ref"] == "char_test_commander"


def test_current_saved_formations_have_no_same_echelon_active_internal_billet():
    from sword_runtime.unit_establishment import authorized_strength_for, formation_class_for

    for formation_path in sorted((_root() / "state/formations").glob("*.json")):
        formation = json.loads(formation_path.read_text())
        current = int(formation.get("personnel", 0) or 0)
        klass = formation_class_for(formation, personnel=current, explicit=formation.get("formation_class"))
        authorized = authorized_strength_for(formation, personnel=current, formation_class=klass)
        structure = build_formation_command_structure(formation, _rules())
        assert all(int(row["scale"]) < authorized for row in structure["internal_hierarchy"]), formation_path.name

        assert "command_structure" not in formation
        active = structure.get("officer_cadre", {}).get("active_billets", {})
        if not isinstance(active, dict):
            continue
        for rank, count in active.items():
            if int(count or 0) <= 0:
                continue
            try:
                scale = int(str(rank).split("_", 1)[0])
            except ValueError:
                continue
            assert scale < authorized, (formation_path.name, rank, authorized)
