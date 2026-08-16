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


def test_qin_border_detachment_is_four_real_two_thousand_units():
    cfg = _rules()["qin_border_detachment"]
    assert cfg["persistent_unit_slots"] == 4
    assert cfg["fighting_establishment_per_unit"] == 2000
    assert cfg["fighting_establishment_total"] == 8000
    assert cfg["unit_command_bodies_total"] == 8
    assert cfg["unit_commander_representation"] == "full_character"
    assert cfg["unit_deputy_representation"] == "person_lite"
    assert cfg["internal_commanders_per_unit"] == 26
    assert cfg["internal_commander_assignments_total"] == 104
    assert cfg["internal_deputy_billets_total"] == 0
    assert cfg["external_support_target_total"] == 112
    assert cfg["fully_staffed_attached_personnel"] == 8120
    assert len(cfg["formation_refs"]) == 4


def test_each_qin_unit_separates_fighting_strength_from_real_command_and_support():
    rules = _rules()
    for ref in rules["qin_border_detachment"]["formation_refs"]:
        formation = {
            "formation_ref": ref,
            "owner_force_ref": "force_state_qin",
            "personnel": 2000,
        }
        structure = build_formation_command_structure(formation, rules)

        assert structure["projection_kind"] == "formation_command_structure_v4"
        assert "schema" not in structure
        assert structure["fighting_establishment"] == 2000
        assert structure["persistent_unit_slots"] == 1
        assert structure["unit_command"]["commander_billets"] == 1
        assert structure["unit_command"]["deputy_billets"] == 1
        assert structure["unit_command"]["target_bodies"] == 2
        assert structure["unit_command"]["effective_billets_staffed"] == 0
        assert structure["unit_command"]["staffing_shortfall"] == 2
        assert _hierarchy(structure) == {1000: 2, 500: 4, 100: 20}
        assert structure["internal_commander_assignments"] == 26
        assert structure["internal_commanders_inside_fighting_establishment"] == 26
        assert all(row["representation"] == "person_lite" for row in structure["internal_hierarchy"])
        assert all(row["deputy_policy"] == "none" for row in structure["internal_hierarchy"])
        assert structure["external_support"]["targets_by_role"] == {
            "command_personnel": 8,
            "signal": 8,
            "logistics": 12,
        }
        assert structure["external_support"]["target_total"] == 28
        assert structure["external_support"]["allocated_total"] == 0
        assert structure["attached_personnel_target"] == 2030
        assert structure["attached_personnel_actual_from_force_allocations"] == 2000
        assert structure["staffing_status"] == "internal_leadership_only"

        profile = rules["formation_profiles"][ref]["external_unit_command"]
        assert profile["commander_representation"] == "full_character"
        assert profile["deputy_representation"] == "person_lite"


def test_qin_full_external_staffing_is_counted_only_when_allocated():
    formation = {
        "formation_ref": "formation_qin_border_line",
        "owner_force_ref": "force_state_qin",
        "personnel": 2000,
        "attached_unit_command_by_role": {"command_personnel": 2},
        "attached_support_by_role": {"command_personnel": 8, "signal": 8, "logistics": 12},
    }
    structure = build_formation_command_structure(formation, _rules())
    assert structure["unit_command"]["effective_billets_staffed"] == 2
    assert structure["unit_command"]["staffing_shortfall"] == 0
    assert structure["external_support"]["allocated_total"] == 28
    assert set(structure["external_support"]["shortfall_by_role"].values()) == {0}
    assert structure["attached_personnel_actual_from_force_allocations"] == 2030
    assert structure["staffing_status"] == "aggregate_unit_command"


def test_gbg_command_tree_is_three_six_thirty_while_cohorts_remain_fifteen_by_two_hundred():
    formation = {
        "formation_ref": "formation_tang_wei_great_bow_guard_first",
        "owner_force_ref": "force_tang_wei_personal",
        "personnel": 3000,
    }
    rules = _rules()
    structure = build_formation_command_structure(formation, rules)

    assert structure["fighting_establishment"] == 3000
    assert structure["persistent_unit_slots"] == 1
    assert _hierarchy(structure) == {1000: 3, 500: 6, 100: 30}
    assert structure["internal_commander_assignments"] == 39
    assert all(bool(row["inside_fighting_establishment"]) for row in structure["internal_hierarchy"])
    assert all(row["representation"] == "person_lite" for row in structure["internal_hierarchy"])
    assert all(row["deputy_policy"] == "none" for row in structure["internal_hierarchy"])
    assert structure["external_support"]["target_total"] == 42
    assert structure["attached_personnel_target"] == 3044

    profile = rules["formation_profiles"]["formation_tang_wei_great_bow_guard_first"]
    assert profile["external_unit_command"]["commander_representation"] == "full_character"
    assert profile["external_unit_command"]["deputy_representation"] == "person_lite"
    alignment = profile["cohort_alignment"]
    assert alignment["cohort_size"] == 200
    assert alignment["cohort_count"] == 15
    assert alignment["cohorts_per_1000_command"] == 5
    assert alignment["purpose"] == "recruitment_and_manpower_provenance_not_tactical_command_level"
    assert rules["great_bow_guard"]["internal_commander_assignments"] == 39
    assert rules["great_bow_guard"]["internal_deputy_billets"] == 0


def test_tang_champions_are_separate_unit_and_preserve_named_command():
    rules = _rules()
    contingent = rules["tang_wei_house_contingent"]
    assert contingent["persistent_unit_slots"] == 2
    assert contingent["fighting_establishment_total"] == 3100
    assert set(contingent["formation_refs"]) == {
        "formation_tang_wei_great_bow_guard_first",
        "formation_tang_champions_first",
    }

    formation = {
        "formation_ref": "formation_tang_champions_first",
        "owner_force_ref": "force_house_tang",
        "personnel": 100,
        "commander_ref": "char_duan_jin",
        "deputy_ref": "char_shen_rui",
    }
    structure = build_formation_command_structure(formation, rules)
    assert structure["fighting_establishment"] == 100
    assert structure["persistent_unit_slots"] == 1
    assert structure["internal_commander_assignments"] == 0
    assert structure["unit_command"]["named_commander_ref"] == "char_duan_jin"
    assert structure["unit_command"]["named_deputy_ref"] == "char_shen_rui"
    assert structure["unit_command"]["effective_billets_staffed"] == 2
    assert structure["staffing_status"] == "named_unit_command"


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


def test_incapacitated_gbg_unit_commander_yields_to_healthy_deputy_without_minting_replacement():
    class Harness(CombatCapabilityMixin):
        def read(self, path: str):
            if path == "game/data/mechanics/warfare-organization.json":
                return _rules()
            raise AssertionError(path)

    formation = {
        "personnel": 3000,
        "training_progress": 70,
        "cohesion": 70,
        "command_structure": {
            "internal_hierarchy": [
                {"scale": 1000, "count": 3},
                {"scale": 500, "count": 6},
                {"scale": 100, "count": 30},
            ],
            "unit_command": {"target_bodies": 2, "effective_billets_staffed": 2},
            "external_support": {"target_total": 42, "allocated_total": 0},
        },
    }
    named = [
        {"role": "commander", "command_score": 0, "command_available": False},
        {"role": "deputy", "command_score": 90, "command_available": True},
    ]
    result = Harness()._combat_command_effects(formation, named)
    assert result["continuity_mode"] == "acting_deputy"
    assert result["acting_command_score"] == pytest.approx(73.8)
    assert result["support"] == 1.0


def test_high_potential_representation_requires_saved_evidence_not_billet_status():
    policy = _rules()["officer_representation_policy"]
    assert policy["default_representation"] == "aggregate"
    assert "saved_high_potential_evidence" in policy["person_lite_triggers"]
    assert "never inferred from holding a billet" in policy["high_potential_evidence_rule"]
    assert "reclassifies one already conserved body" in policy["materialization_rule"]


def test_gbg_program_does_not_automatically_draw_sword_manor_officers():
    programs = json.loads((_root() / "game/data/mechanics/house-tang-programs.json").read_text())
    gbg = programs["great_bow_guard"]
    officers = programs["sword_manor_officer_cadre"]
    assert gbg["fighting_establishment_max"] == 3000
    assert gbg["conserved_recruitment_cohorts"] == 15
    assert gbg["preferred_recruitment_cohort_size"] == 200
    assert gbg["automatic_sword_manor_secondments"] == 0
    assert gbg["internal_command_candidate_source"] == "accepted_great_bow_guard_recruits"
    assert officers["authorized_officer_target"] == 50
    assert officers["great_bow_guard_default_secondment_target"] == 0
