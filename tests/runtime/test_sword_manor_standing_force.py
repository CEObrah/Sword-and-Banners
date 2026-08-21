from __future__ import annotations

import json
from pathlib import Path

from conftest import execute_production_internal
from sword_runtime.warfare_depth import build_formation_command_structure


def _read(root: Path, rel: str):
    return json.loads((Path(root) / rel).read_text())


def test_sword_manor_is_permanent_force_not_mobilization_pool(campaign):
    force = _read(campaign, "state/forces/sword-manor.json")
    assert force["owner_id"] == "force_sword_manor"
    assert force["kind"] == "house_military_force"
    assert force["headcount"] == 30060
    assert sum(force["available_by_role"].values()) == 0
    allocated=sum(v["personnel"] for v in force["allocated_to_formations"].values())
    external=sum(sum(int(n) for n in roles.values()) for roles in force.get("external_personnel_allocations", {}).values())
    assert allocated + external == force["headcount"]
    assert len(force["materialized_assignments"]) == 89
    assert len(force["standing_formation_refs"]) == 7

    owners = _read(campaign, "state/index/owner-index.json")["owners"]
    formations = [_read(campaign, owners[ref]) for ref in force["standing_formation_refs"]]
    assert sum(f["personnel"] for f in formations) == allocated
    assert sorted(f["personnel"] for f in formations) == sorted([1498, 3498, 4998, 5013, 5013, 5013, 5013])
    assert sum(len(f.get("embedded_person_refs", [])) for f in formations) == 89
    assert all(f["owner_force_ref"] == "force_sword_manor" for f in formations)
    assert all(f["mobilized"] is True for f in formations)
    assert all(f["status"] == "home_ready" for f in formations)
    rules = _read(campaign, "game/data/mechanics/warfare-organization.json")
    command_structures = [build_formation_command_structure(f, rules) for f in formations]
    assert all("command_accounting" not in f for f in formations)
    assert all(c["unit_command"]["outside_fighting_establishment"] is True for c in command_structures)
    assert all(c["unit_command"]["allocated_aggregate_bodies"] == 2 for c in command_structures)
    trainee = [f for f in formations if "trainee" in f["composition"]]
    assert sum(f["equipment_units_by_role"].get("trainee", 0) for f in trainee) == 19940


def test_house_tang_field_army_nests_sword_manor_bastions_and_house_branches(campaign):
    field = _read(campaign, "state/cmd/command-groups/cmdgrp.house_tang.field_army.json")
    assert field["commander_ref"] == "char_tang_zhu"
    assert field["deputy_ref"] == "char_tang_ling"
    assert field["context"] == "field_army"
    assert field["display_name"] == "House Tang Grand Field Army Command"
    assert field["role_assignments"] == {
        "outer_perimeter_defense": "cmdgrp.house_tang.bastions",
        "city_interior_defense": "cmdgrp.sword_manor.field",
        "inner_citadel_guard": "cmdgrp.house_tang.house_guard",
        "mobile_inner_reserve": "cmdgrp.house_tang.guardian_cavalry",
        "decisive_elite_reserve": "cmdgrp.house_tang.champions",
    }
    assert any(order["order_ref"] == "house_tang_unified_command" for order in field["standing_orders"])
    assert any(order["order_ref"] == "house_tang_layered_home_defense" for order in field["standing_orders"])
    assert any(order["order_ref"] == "house_tang_reassignment_and_preservation" for order in field["standing_orders"])
    assert [row["ref"] for row in field["units"] if row["kind"] == "nested_army"] == [
        "cmdgrp.sword_manor.field",
        "cmdgrp.house_tang.bastions",
        "cmdgrp.house_tang.house_guard",
        "cmdgrp.house_tang.guardian_cavalry",
        "cmdgrp.house_tang.champions",
    ]
    sword = _read(campaign, "state/cmd/command-groups/cmdgrp.sword_manor.field.json")
    assert sword["commander_ref"] == "char_wei_jian"
    assert sword["deputy_ref"] == "char_ren_qiao"
    assert sword["parent_command_group_ref"] == field["id"]
    assert len([row["ref"] for row in sword["units"] if row["kind"] == "nested_army"]) == 4
    bastions = _read(campaign, "state/cmd/command-groups/cmdgrp.house_tang.bastions.json")
    assert bastions["parent_command_group_ref"] == field["id"]
    assert "cmdgrp.house_tang.bastions" in [row["ref"] for row in field["units"] if row["kind"] == "nested_army"]
    assert [row["ref"] for row in bastions["units"] if row["kind"] == "nested_army"] == [
        "cmdgrp.bastion.iron_wall",
        "cmdgrp.bastion.red_thunder",
        "cmdgrp.bastion.white_blade",
        "cmdgrp.bastion.stone_spear",
    ]


def test_wei_field_army_can_attach_as_one_intact_recursive_unit(campaign):
    parent = "cmdgrp.house_tang.field_army"
    child = "cmdgrp.tang_wei.field_army"
    child_before = _read(campaign, "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    direct_units = list([row for row in child_before["units"] if row["kind"] == "formation"])
    nested = list([row for row in child_before["units"] if row["kind"] == "nested_army"])
    execute_production_internal(campaign, "command_group_action", {"action":"attach_command_group","command_group_ref":parent,"subordinate_group_ref":child})
    attached = _read(campaign, "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    pdoc = _read(campaign, "state/cmd/command-groups/cmdgrp.house_tang.field_army.json")
    assert attached["parent_command_group_ref"] == parent
    assert child in [row["ref"] for row in pdoc["units"] if row["kind"] == "nested_army"]
    assert [row for row in attached["units"] if row["kind"] == "formation"] == direct_units
    assert [row for row in attached["units"] if row["kind"] == "nested_army"] == nested
    execute_production_internal(campaign, "command_group_action", {"action":"detach_command_group","command_group_ref":parent,"subordinate_group_ref":child})
    detached = _read(campaign, "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    assert detached["parent_command_group_ref"] is None
    assert [row for row in detached["units"] if row["kind"] == "formation"] == direct_units
    assert [row for row in detached["units"] if row["kind"] == "nested_army"] == nested


def test_wei_has_no_first_sword_or_house_top_field_command_authority(campaign):
    player = _read(campaign, "state/player.json")
    auth = _read(campaign, "state/authority/char-tang-wei.json")
    assert "First Sword" not in player["authority"]
    assert "House Tang Field Commander" not in player["authority"]
    roles = auth["roles"]
    assert all(r.get("authority_ref") != "force_sword_manor" for r in roles)
    assert all(r.get("role") != "First Sword" for r in roles)
    assert any(r.get("authority_ref") == "cmdgrp.tang_wei.field_army" and r.get("role") == "Tang Wei Field Army Commander" for r in roles)
