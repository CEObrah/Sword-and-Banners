from __future__ import annotations

import copy
import json
from pathlib import Path

from sword_runtime.warfare_depth import build_formation_command_structure, build_mercenary_command_structure


def _rules() -> dict:
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / "game/data/mechanics/warfare-organization.json").read_text())


def _hierarchy(structure: dict) -> dict[int, int]:
    return {int(row["scale"]): int(row["count"]) for row in structure["internal_hierarchy"]}


def test_qin_border_line_separates_fighting_strength_from_command_and_support():
    formation = {
        "formation_ref": "formation_qin_border_line",
        "owner_force_ref": "force_state_qin",
        "personnel": 8000,
    }
    structure = build_formation_command_structure(formation, _rules())

    assert structure["projection_kind"] == "formation_command_structure_v3"
    assert "schema" not in structure
    assert structure["fighting_establishment"] == 8000
    assert structure["persistent_unit_slots"] == 1
    assert structure["unit_command"]["commander_billets"] == 1
    assert structure["unit_command"]["deputy_billets"] == 1
    assert _hierarchy(structure) == {2000: 4, 1000: 8, 500: 16, 100: 80}
    assert structure["internal_commander_assignments"] == 108
    assert structure["internal_commanders_inside_fighting_establishment"] == 108
    assert structure["external_support"]["targets_by_role"] == {
        "command_personnel": 32,
        "signal": 32,
        "logistics": 48,
    }
    assert structure["external_support"]["target_total"] == 112
    assert structure["external_support"]["allocated_total"] == 0
    assert structure["attached_personnel_target"] == 8114


def test_gbg_command_nodes_align_to_fifteen_conserved_two_hundred_cohorts():
    formation = {
        "formation_ref": "formation_tang_wei_great_bow_guard_first",
        "owner_force_ref": "force_tang_wei_personal",
        "personnel": 3000,
    }
    structure = build_formation_command_structure(formation, _rules())

    assert structure["fighting_establishment"] == 3000
    assert structure["persistent_unit_slots"] == 1
    assert _hierarchy(structure) == {1000: 3, 200: 15}
    assert structure["internal_commander_assignments"] == 18
    assert all(bool(row["inside_fighting_establishment"]) for row in structure["internal_hierarchy"])


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
        "schema": "mercenary",
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
    assert structure["projection_kind"] == "mercenary_command_structure_v1"
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


def test_high_potential_representation_requires_saved_evidence_not_billet_status():
    policy = _rules()["officer_representation_policy"]
    assert policy["default_representation"] == "aggregate"
    assert "saved_high_potential_evidence" in policy["person_lite_triggers"]
    assert "never inferred from holding a billet" in policy["high_potential_evidence_rule"]
    assert "reclassifies one already conserved body" in policy["materialization_rule"]
