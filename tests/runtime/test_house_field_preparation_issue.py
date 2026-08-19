from __future__ import annotations

import copy

from sword_runtime.house_field_preparation_issue import (
    _issue_material_reserve,
    _issue_spare_equipment,
)


class _MemoryPlanner:
    def __init__(self) -> None:
        self.docs = {
            "state/depots/house-tang.json": {
                "location_ref": "loc_tang_manor_garrison_yard",
                "stocks": {
                    "grain_kg": 100000,
                    "fodder_kg": 100000,
                    "war_arrows": 100000,
                },
            },
            "state/houses/house_tang.json": {
                "administrative_programs": {
                    "wei_field_preparation": {"principal_ref": "char_tang_wei"}
                }
            },
            "state/inv/inventories.json": {
                "records": [
                    {
                        "record_id": "tang_restricted_equipment",
                        "facts": {
                            "Tang Armor unissued reserve": 100,
                            "Tang Armor issued": 0,
                            "Long Spear unissued reserve": 0,
                            "Long Spear issued": 0,
                        },
                    }
                ]
            },
            "game/data/loadouts.json": {
                "ids": ["loadout_test"],
                "path_template": "game/data/loadout-records/{loadout_id}.json",
            },
            "game/data/loadout-records/loadout_test.json": {
                "loadout": {
                    "id": "loadout_test",
                    "body_armor": "armor_tang",
                    "primary_melee_weapon": "weapon_spear_long",
                    "ammunition_item": "ammo_arrow_war",
                    "carried_ammunition": 36,
                }
            },
            "state/formations/test.json": {
                "formation_ref": "formation_test",
                "administrative_owner": "house_tang",
                "command_authority": "char_tang_wei",
                "location_ref": "loc_tang_manor_garrison_yard",
                "personnel": 500,
                "mounts": {"horse_tang_heavy_war": 500},
                "composition": {"test_role": 500},
                "equipment_units_by_role": {"test_role": 500},
                "equipment_completeness": "1.0000",
                "registered_loadout_ref": "loadout_test",
                "logistics": {
                    "food_kg": 0,
                    "fodder_kg": 0,
                    "war_arrows": 18000,
                    "war_bolts": 0,
                },
            },
        }

    def read(self, path):
        return copy.deepcopy(self.docs[path])

    def put(self, path, document):
        self.docs[path] = copy.deepcopy(document)

    def _load_formation(self, formation_ref):
        assert formation_ref == "formation_test"
        return "state/formations/test.json", self.read("state/formations/test.json")


def test_material_field_reserve_is_transferred_from_depot_to_formation() -> None:
    planner = _MemoryPlanner()
    result = _issue_material_reserve(
        planner,
        formation_ref="formation_test",
        reserve_days=7,
        arrow_loads_total=2,
        at="244-BCE-07-23T10:22:48+08:00",
    )

    assert result["issued"] == {
        "food_kg": 2800,
        "fodder_kg": 14000,
        "war_arrows": 18000,
    }
    formation = planner.docs["state/formations/test.json"]
    assert formation["logistics"]["food_kg"] == 2800
    assert formation["logistics"]["fodder_kg"] == 14000
    assert formation["logistics"]["war_arrows"] == 36000
    depot = planner.docs["state/depots/house-tang.json"]["stocks"]
    assert depot["grain_kg"] == 97200
    assert depot["fodder_kg"] == 86000
    assert depot["war_arrows"] == 82000


def test_spare_issue_uses_exact_reserve_and_records_real_shortfall() -> None:
    planner = _MemoryPlanner()
    result = _issue_spare_equipment(
        planner,
        formation_ref="formation_test",
        spare_basis_points=500,
        eligible_fields=("body_armor", "primary_melee_weapon"),
        at="244-BCE-07-23T10:22:48+08:00",
    )

    assert result["desired_each"] == 25
    assert result["issued"]["armor_tang"] == 25
    assert result["issued"]["weapon_spear_long"] == 0
    assert result["shortfalls"] == {"weapon_spear_long": 25}
    formation = planner.docs["state/formations/test.json"]
    assert formation["equipment_staging_by_item"]["armor_tang"] == 25
    inventory = planner.docs["state/inv/inventories.json"]["records"][0]["facts"]
    assert inventory["Tang Armor unissued reserve"] == 75
    assert inventory["Tang Armor issued"] == 25
