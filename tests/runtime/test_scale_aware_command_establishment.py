from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.warfare_depth import build_formation_command_structure


def _rules() -> dict:
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / "game/data/mechanics/warfare-organization.json").read_text())


def test_qin_border_line_separates_fighting_strength_from_command_and_support():
    formation = {
        "formation_ref": "formation_qin_border_line",
        "owner_force_ref": "force_state_qin",
        "personnel": 8000,
    }
    structure = build_formation_command_structure(formation, _rules())
    hierarchy = {int(row["scale"]): int(row["count"]) for row in structure["internal_hierarchy"]}

    assert structure["fighting_establishment"] == 8000
    assert structure["persistent_unit_slots"] == 1
    assert structure["unit_command"]["commander_billets"] == 1
    assert structure["unit_command"]["deputy_billets"] == 1
    assert hierarchy == {2000: 4, 1000: 8, 500: 16, 100: 80}
    assert structure["internal_commander_assignments"] == 108
    assert structure["internal_commanders_inside_fighting_establishment"] == 108
    assert structure["external_support"]["targets_by_role"] == {
        "command_personnel": 32,
        "signal": 32,
        "logistics": 48,
    }
    assert structure["external_support"]["target_total"] == 112
    assert structure["attached_personnel_target"] == 8114


def test_gbg_command_nodes_align_to_fifteen_conserved_two_hundred_cohorts():
    formation = {
        "formation_ref": "formation_tang_wei_great_bow_guard_first",
        "owner_force_ref": "force_tang_wei_personal",
        "personnel": 3000,
    }
    structure = build_formation_command_structure(formation, _rules())
    hierarchy = {int(row["scale"]): int(row["count"]) for row in structure["internal_hierarchy"]}

    assert structure["fighting_establishment"] == 3000
    assert structure["persistent_unit_slots"] == 1
    assert hierarchy == {1000: 3, 200: 15}
    assert structure["internal_commander_assignments"] == 18
    assert all(bool(row["inside_fighting_establishment"]) for row in structure["internal_hierarchy"])
