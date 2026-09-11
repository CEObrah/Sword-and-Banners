from __future__ import annotations

import copy

from sword_runtime.house_field_preparation_issue import _issue_material_reserve, _issue_spare_equipment


class _MemoryPlanner:
    def __init__(self) -> None:
        self.docs = {
            "game/data/world/locations.json": {"locations": [
                {"ref": "loc_tang_manor", "parent_ref": None},
                {"ref": "loc_tang_manor_garrison_yard", "parent_ref": "loc_tang_manor"},
            ]},
            "state/geography/dynamic.json": {"locations": [], "routes": []},
            "state/depots/house-tang.json": {"location_ref": "loc_tang_manor_garrison_yard", "stocks": {"grain_kg": 100000, "war_arrows": 100000}},
            "state/inv/inventories.json": {"records": [{"record_id": "house_tang_outfitting_sets", "facts": {"standard_role_sets_reserve": 100, "crossbow_role_sets_reserve": 0, "mounted_harness_sets_reserve": 100}}]},
            "game/data/loadouts.json": {"ids": ["loadout_test"], "path_template": "game/data/loadout-records/{loadout_id}.json"},
            "game/data/loadout-records/loadout_test.json": {"loadout": {"id": "loadout_test", "body_armor": "armor_heavy", "primary_melee_weapon": "weapon_spear", "ammunition_item": "ammo_arrow", "carried_ammunition": 36}},
            "state/formations/test.json": {"formation_ref": "formation_test", "administrative_owner": "house_tang", "command_authority": "char_tang_wei", "location_ref": "loc_tang_manor_garrison_yard", "personnel": 500, "mounts": {"horse": 500}, "composition": {"test_role": 500}, "equipment_units_by_role": {"test_role": 500}, "equipment_completeness": "1.0000", "registered_loadout_ref": "loadout_test", "logistics": {"war_arrows": 18000, "war_bolts": 0}},
        }

    def read(self, path):
        return copy.deepcopy(self.docs[path])

    def put(self, path, document):
        self.docs[path] = copy.deepcopy(document)

    def _load_formation(self, formation_ref):
        assert formation_ref == "formation_test"
        return "state/formations/test.json", self.read("state/formations/test.json")

    def _combat_role_profile(self, role):
        assert role == "test_role"
        return {"loadout_id": "loadout_test"}


def test_material_field_reserve_is_transferred_from_depot_to_formation() -> None:
    planner = _MemoryPlanner()
    result = _issue_material_reserve(planner, formation_ref="formation_test", arrow_loads_total=2, at="244-BCE-07-23T10:22:48+08:00")
    assert result["issued"] == {"war_arrows": 18000}
    formation = planner.docs["state/formations/test.json"]
    assert formation["logistics"]["war_arrows"] == 36000
    assert "food_kg" not in formation["logistics"]
    assert "fodder_kg" not in formation["logistics"]
    depot = planner.docs["state/depots/house-tang.json"]["stocks"]
    assert depot == {"grain_kg": 100000, "war_arrows": 82000}


def test_spare_issue_uses_aggregate_reserve_without_creating_item_variants() -> None:
    planner = _MemoryPlanner()
    result = _issue_spare_equipment(planner, formation_ref="formation_test", spare_basis_points=500, eligible_fields=("body_armor", "primary_melee_weapon"), at="244-BCE-07-23T10:22:48+08:00")
    assert result["desired_each"] == 25
    assert result["issued"]["outfitting_role_set"] == 25
    assert result["issued"]["outfitting_mounted_harness_set"] == 25
    assert result["shortfalls"] == {}
    formation = planner.docs["state/formations/test.json"]
    assert formation["spare_outfitting_sets"]["standard_role_sets"] == 25
    assert formation["spare_mounted_harness_sets"] == 25
    facts = planner.docs["state/inv/inventories.json"]["records"][0]["facts"]
    assert facts["standard_role_sets_reserve"] == 75
    assert facts["mounted_harness_sets_reserve"] == 75
    assert all("Tang Armor" not in key and "Cavalry Lance" not in key for key in facts)
