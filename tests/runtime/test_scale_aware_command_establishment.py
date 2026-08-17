from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.combat_capability import CombatCapabilityMixin
from sword_runtime.warfare_depth import build_formation_command_structure, build_mercenary_command_structure


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _rules() -> dict:
    return json.loads((_root() / "game/data/mechanics/warfare-organization.json").read_text())


def _hierarchy(structure: dict) -> dict[int, int]:
    return {int(row["scale"]): int(row["count"]) for row in structure["internal_hierarchy"]}


def test_qin_border_detachment_is_one_conserved_eight_thousand_formation_with_four_command_cells():
    cfg = _rules()["qin_border_detachment"]
    assert cfg["fighting_establishment_total"] == 8000
    assert cfg["internal_unit_cells"] == 4
    assert cfg["fighting_establishment_per_unit_cell"] == 2000
    assert cfg["unit_command_external_to_fighting_strength"] is True
    assert cfg["automatic_person_lite_internal_commanders_total"] == 24
    assert cfg["aggregate_100_man_commanders_total"] == 80
    assert cfg["state_owner"] == "state_qin"



def test_qin_designated_formation_preserves_four_unit_cells_and_100_man_aggregate_commands():
    rules = _rules()
    formation = json.loads((_root() / "state/formations/qin-border-line.json").read_text())
    structure = build_formation_command_structure(formation, rules)
    assert structure["fighting_establishment"] == 8000
    assert structure["unit_command"]["commander_billets"] == 4
    assert structure["unit_command"]["deputy_billets"] == 4
    assert structure["unit_command"]["effective_billets_staffed"] == 8
    assert len(structure["unit_command_cells"]) == 4
    assert [(r["scale"], r["count"], r["representation"]) for r in structure["internal_hierarchy"]] == [
        (1000, 8, "person_lite"), (500, 16, "person_lite"), (100, 80, "aggregate")
    ]
    assert structure["external_support"]["target_total"] == 112
    assert structure["attached_personnel_target"] == 8120



def test_qin_designated_external_unit_command_is_counted_from_saved_cell_commanders():
    rules = _rules()
    formation = json.loads((_root() / "state/formations/qin-border-line.json").read_text())
    structure = build_formation_command_structure(formation, rules)
    assert structure["unit_command"]["target_bodies"] == 8
    assert structure["unit_command"]["effective_billets_staffed"] == 8
    assert structure["unit_command"]["staffing_shortfall"] == 0





def test_tang_wei_house_contingent_preserves_guard_and_named_champion_command():
    rules = _rules()
    contingent = rules["tang_wei_house_contingent"]
    assert contingent["persistent_unit_slots"] == 2
    assert contingent["fighting_establishment_total"] == 3500
    assert set(contingent["formation_refs"]) == {"formation_tang_wei_house_guard_first", "formation_tang_champions_first"}
    formation = json.loads((_root() / "state/formations/tang-champions-first.json").read_text())
    structure = build_formation_command_structure(formation, rules)
    assert structure["fighting_establishment"] == 500
    assert structure["unit_command"]["named_commander_ref"] == "char_duan_jin"
    assert structure["unit_command"]["named_deputy_ref"] == "char_shen_rui"
    assert [(r["scale"],r["count"],r["representation"]) for r in structure["internal_hierarchy"]] == [(100,5,"aggregate")]



def test_generic_state_army_uses_same_hierarchy_without_materializing_officers():
    formation = {
        "formation_ref": "formation_state_generic_8000",
        "owner_force_ref": "force_state_zhao",
        "personnel": 8000,
    }
    structure = build_formation_command_structure(formation, _rules())

    assert _hierarchy(structure) == {2000: 4, 1000: 8, 500: 16, 100: 80}
    assert structure["internal_commander_assignments"] == 108
    assert structure["unit_command"]["representation"] == "aggregate"
    assert all(row["representation"] == "aggregate" for row in structure["internal_hierarchy"])
    assert structure["representation_policy"].startswith("aggregate_by_default")
    assert structure["staffing_status"] == "internal_leadership_only"


def test_house_army_uses_universal_projection_and_partial_command_tails():
    formation = {
        "formation_ref": "formation_house_example",
        "owner_force_ref": "force_house_example",
        "personnel": 1200,
    }
    structure = build_formation_command_structure(formation, _rules())
    by_scale = {int(row["scale"]): row for row in structure["internal_hierarchy"]}

    assert _hierarchy(structure) == {1000: 2, 500: 3, 100: 12}
    assert by_scale[1000]["full_elements"] == 1
    assert by_scale[1000]["partial_tail_personnel"] == 200
    assert by_scale[500]["full_elements"] == 2
    assert by_scale[500]["partial_tail_personnel"] == 200
    assert all(row["representation"] == "aggregate" for row in structure["internal_hierarchy"])


def test_mercenary_company_carves_command_and_support_from_existing_total_headcount():
    company = {
        "schema": "mercenary-company",
        "owner_id": "merc.major.03",
        "headcount": 2600,
        "troop_pools": [
            {"role": "cavalry", "troop_type": "cavalry", "count": 1560},
            {"role": "mounted_scouts", "troop_type": "mounted_scout", "count": 390},
            {"role": "dismounted_line", "troop_type": "line_infantry", "count": 338},
            {"role": "support", "troop_type": "support_staff", "count": 312},
        ],
    }
    before = copy.deepcopy(company)
    structure = build_mercenary_command_structure(company, _rules())
    by_scale = {int(row["scale"]): row for row in structure["internal_hierarchy"]}

    assert company == before
    assert structure["projection_kind"] == "mercenary_command_structure_v2"
    assert "schema" not in structure
    assert structure["company_headcount"] == 2600
    assert structure["troop_pool_headcount"] == 2600
    assert structure["fighting_establishment"] == 2288
    assert structure["existing_non_fighting_personnel"] == 312
    assert structure["attached_personnel_target"] == 2600
    assert structure["attached_personnel_delta"] == 0
    assert structure["unit_command"]["inside_total_headcount"] is True
    assert structure["unit_command"]["representation"] == "aggregate"
    assert _hierarchy(structure) == {2000: 2, 1000: 3, 500: 5, 100: 23}
    assert by_scale[2000]["full_elements"] == 1
    assert by_scale[2000]["partial_tail_personnel"] == 288
    assert by_scale[1000]["full_elements"] == 2
    assert by_scale[1000]["partial_tail_personnel"] == 288
    assert by_scale[500]["full_elements"] == 4
    assert by_scale[500]["partial_tail_personnel"] == 288
    assert by_scale[100]["full_elements"] == 22
    assert by_scale[100]["partial_tail_personnel"] == 88
    assert structure["internal_commander_assignments"] == 33
    assert all(row["representation"] == "aggregate" for row in structure["internal_hierarchy"])
    assert structure["support"]["staffing_shortfall"] == 0


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


def test_house_tang_mercenaries_have_role_specific_quarterly_training_rules():
    cfg = _rules()["mercenary_training"]
    assert cfg["review_kind"] == "quarterly_autonomy"
    assert cfg["hours_per_review_by_status"]["contracted_defense"] > 0
    assert cfg["doctrine_familiarity_gain_per_review"] > 0
    tokens = {token for row in cfg["focus_profiles"] for token in row["tokens"]}
    assert {"countermining", "artillery", "heavy_infantry", "signal", "logistics"}.issubset(tokens)
    assert "diminishing-return training" in cfg["rule"]


def test_command_combat_effects_are_scale_bounded_and_actual_support_gated():
    class Harness(CombatCapabilityMixin):
        def read(self, path: str):
            if path == "game/data/mechanics/warfare-organization.json":
                return _rules()
            raise AssertionError(path)

    formation = {
        "personnel": 8000,
        "training_progress": 80,
        "cohesion": 80,
        "command_structure": {
            "internal_hierarchy": [{"scale": 2000, "count": 4}, {"scale": 1000, "count": 8}, {"scale": 100, "count": 80}],
            "unit_command": {"target_bodies": 2, "effective_billets_staffed": 2},
            "external_support": {"target_total": 112, "allocated_total": 112},
        },
    }
    named = [
        {"role": "commander", "command_score": 100, "command_available": True},
        {"role": "deputy", "command_score": 90, "command_available": True},
    ]
    full = Harness()._combat_command_effects(formation, named)
    assert 1.0 < full["combined_factor"] <= _rules()["command_effect_scales"]["combined_cap"]
    assert full["local"] > 1.0
    assert full["maneuver"] > 1.0
    assert full["operational"] > 1.0
    assert full["unit"] > 1.0
    assert full["support"] > 1.0

    no_support = copy.deepcopy(formation)
    no_support["command_structure"]["external_support"]["allocated_total"] = 0
    missing = Harness()._combat_command_effects(no_support, named)
    assert missing["support"] == 1.0




def test_high_potential_representation_requires_saved_evidence_not_billet_status():
    policy = _rules()["officer_representation_policy"]
    assert policy["default_representation"] == "aggregate"
    assert "saved_high_potential_evidence" in policy["person_lite_triggers"]
    assert "never inferred from holding a billet" in policy["high_potential_evidence_rule"]
    assert "reclassifies one already conserved body" in policy["materialization_rule"]


