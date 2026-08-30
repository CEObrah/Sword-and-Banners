from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_sword_manor_and_bastions_are_not_parallel_force_owners() -> None:
    owners = _read("state/index/owner-index.json")["owners"]
    retired = {
        "force_sword_manor", "force_bastion_iron_wall", "force_bastion_red_thunder",
        "force_bastion_white_blade", "force_bastion_stone_spear",
        "force_house_guardian_cavalry", "force_house_guards",
    }
    assert not (retired & set(owners))


def test_inner_walls_survives_as_physical_geography_not_separate_manpower() -> None:
    locations = json.dumps(_read("game/data/world/locations.json"))
    assert "loc_tang_inner_walls" in locations
    assert "Sword Manor" not in locations
    owners = _read("state/index/owner-index.json")["owners"]
    assert "force_sword_manor" not in owners


def test_house_home_defense_has_exact_three_layer_command_tree() -> None:
    root = _read("state/cmd/command-groups/cmdgrp.house_tang.field_army.json")
    assert root["commander_ref"] == "char_tang_zhu"
    assert root["units"] == [
        {"kind": "nested_army", "ref": "cmdgrp.house_tang.outer_wall"},
        {"kind": "nested_army", "ref": "cmdgrp.house_tang.inner_walls"},
        {"kind": "nested_army", "ref": "cmdgrp.house_tang.inner_citadel"},
    ]


def test_home_layer_formations_are_all_owned_by_unified_house_force() -> None:
    for group_ref in ("cmdgrp.house_tang.outer_wall", "cmdgrp.house_tang.inner_walls", "cmdgrp.house_tang.inner_citadel"):
        group = _read(f"state/cmd/command-groups/{group_ref}.json")
        assert group["units"]
        for unit in group["units"]:
            assert unit["kind"] == "formation"
            rel = _read("state/index/owner-index.json")["owners"][unit["ref"]]
            formation = _read(rel)
            assert formation["owner_force_ref"] == "force_house_tang"
