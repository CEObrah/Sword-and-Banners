"""Conserved House Tang armory issue to exact formations.

Exact items leave House reserves and enter a formation staging ledger. When the
formation declares a registered loadout, complete staged sets are converted into
abstract equipment units for its actual troop role. No formation-specific legacy
paths are required.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

_INVENTORY_PATH = "state/inv/inventories.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_LOADOUT_INDEX_PATH = "game/data/loadouts.json"

_ARMORY_COUNTERS: dict[str, tuple[str, str, str]] = {
    "armor_tang": ("tang_restricted_equipment", "Tang Armor unissued reserve", "Tang Armor issued"),
    "helmet_tang": ("tang_restricted_equipment", "Tang Helmet unissued reserve", "Tang Helmet issued"),
    "shield_tang": ("tang_restricted_equipment", "Tang Shield unissued reserve", "Tang Shield issued"),
    "weapon_bow_great_war": ("bows", "Great War Bow armory reserve", "Great War Bow active issued"),
    "weapon_bow_heavy_war": ("bows", "Heavy War Bow armory reserve", "Heavy War Bow active issued"),
    "weapon_bow_composite": ("bows", "Composite Bow armory reserve", "Composite Bow active issued"),
    "weapon_spear_long": ("tang_restricted_equipment", "Long Spear unissued reserve", "Long Spear issued"),
    "weapon_lance_cavalry": ("tang_restricted_equipment", "Cavalry Lance unissued reserve", "Cavalry Lance issued"),
    "weapon_sword_one_hand_long": ("tang_restricted_equipment", "One-Handed Long Sword unissued reserve", "One-Handed Long Sword issued"),
    "horse_armor_tang": ("tang_restricted_equipment", "Tang Horse Armor reserve", "Tang Horse Armor issued"),
    "tack_tang": ("tang_restricted_equipment", "Tang Tack reserve", "Tang Tack issued"),
    "horse_tang_heavy_war": ("mounts", "Tang Heavy Warhorse reserve", "Tang Heavy Warhorse assigned"),
}


def _record(registry: MutableMapping[str, Any], record_id: str) -> MutableMapping[str, Any]:
    for row in registry.get("records", []):
        if isinstance(row, MutableMapping) and row.get("record_id") == record_id:
            facts = row.get("facts")
            if not isinstance(facts, MutableMapping):
                raise ValueError(f"armory record {record_id} has no mutable facts")
            return facts
    raise ValueError(f"armory record {record_id} is unavailable")


def _formation_units(formation: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    units = formation.setdefault("equipment_units_by_role", {})
    if not isinstance(units, MutableMapping):
        raise ValueError("formation equipment unit ledger is invalid")
    return units


def _recompute_completeness(formation: MutableMapping[str, Any]) -> None:
    personnel = max(1, int(formation.get("personnel", 0)))
    total = sum(max(0, int(v)) for v in _formation_units(formation).values())
    formation["equipment_completeness"] = f"{min(1.0, total / personnel):.4f}"


def _loadout_items(planner: Any, formation: Mapping[str, Any]) -> tuple[str, ...]:
    loadout_id = formation.get("equipment_loadout_id") or formation.get("registered_loadout_ref")
    if not isinstance(loadout_id, str) or not loadout_id:
        return ()
    index = planner.read(_LOADOUT_INDEX_PATH)
    rel = None
    records = index.get("records") if isinstance(index, Mapping) else None
    if isinstance(records, Mapping):
        rel = records.get(loadout_id)
    if not isinstance(rel, str):
        ids = index.get("ids", []) if isinstance(index, Mapping) else []
        template = index.get("path_template") if isinstance(index, Mapping) else None
        if loadout_id in ids and isinstance(template, str):
            rel = template.format(loadout_id=loadout_id)
    if not isinstance(rel, str):
        return ()
    doc = planner.read(rel)
    loadout = doc.get("loadout", {}) if isinstance(doc, Mapping) else {}
    if not isinstance(loadout, Mapping):
        return ()
    keys = (
        "body_armor",
        "helmet",
        "ranged_weapon",
        "primary_melee_weapon",
        "shield",
        "sidearm",
        "mount",
        "tack",
        "horse_armor",
    )
    return tuple(str(loadout[k]) for k in keys if isinstance(loadout.get(k), str) and loadout.get(k))


def _convert_complete_sets(planner: Any, formation: MutableMapping[str, Any]) -> int:
    composition = formation.get("composition", {})
    if not isinstance(composition, Mapping) or not composition:
        return 0
    role = max(composition, key=lambda k: int(composition.get(k, 0)))
    target = max(0, int(composition.get(role, 0)))
    staging = formation.setdefault("equipment_staging_by_item", {})
    if not isinstance(staging, MutableMapping):
        raise ValueError("formation equipment staging ledger is invalid")
    required = _loadout_items(planner, formation)
    if not required or any(item not in staging for item in required):
        return 0
    units = _formation_units(formation)
    current = max(0, int(units.get(role, 0)))
    possible = min(max(0, int(staging.get(item, 0))) for item in required)
    complete = min(possible, max(0, target - current))
    if complete <= 0:
        return 0
    for item in required:
        remain = max(0, int(staging.get(item, 0)) - complete)
        if remain:
            staging[item] = remain
        else:
            staging.pop(item, None)
    units[role] = current + complete
    _recompute_completeness(formation)
    return complete


def house_armory_reserve_available(planner: Any, item_key: str) -> int:
    counter = _ARMORY_COUNTERS.get(str(item_key))
    if counter is None:
        return 0
    record_id, reserve_key, _issued_key = counter
    registry = planner.read(_INVENTORY_PATH)
    for row in registry.get("records", []):
        if isinstance(row, Mapping) and row.get("record_id") == record_id:
            facts = row.get("facts") if isinstance(row.get("facts"), Mapping) else {}
            return max(0, int(facts.get(reserve_key, 0)))
    return 0


def issue_house_armory_to_formation(
    planner: Any,
    *,
    formation_ref: str,
    item_key: str,
    quantity: int,
    actor_ref: str,
    at: str,
) -> dict[str, Any]:
    quantity = int(quantity)
    if quantity <= 0:
        raise ValueError("formation armory issue quantity must be positive")
    counter = _ARMORY_COUNTERS.get(str(item_key))
    if counter is None:
        raise ValueError("House Tang has no exact armory reserve counter for this item")
    formation_path, formation0 = planner._load_formation(str(formation_ref))
    formation = copy.deepcopy(formation0)
    if str(formation.get("command_authority", "")) != str(actor_ref):
        raise PermissionError("formation armory issue requires exact formation command authority")
    if not str(formation.get("location_ref", "")).startswith("loc_tang_manor_"):
        raise PermissionError("House Tang armory issue requires the formation to be at Tang Manor")
    house = planner.read(_HOUSE_PATH)
    programs = house.get("administrative_programs", {}) if isinstance(house, Mapping) else {}
    prep = programs.get("wei_field_preparation", {}) if isinstance(programs, Mapping) else {}
    if not isinstance(prep, Mapping) or str(prep.get("principal_ref", "")) != str(actor_ref):
        raise PermissionError("House armory issue requires a persisted House field-preparation authorization")

    registry = copy.deepcopy(planner.read(_INVENTORY_PATH))
    record_id, reserve_key, issued_key = counter
    facts = _record(registry, record_id)
    reserve = max(0, int(facts.get(reserve_key, 0)))
    if reserve < quantity:
        raise ValueError(
            f"House Tang armory reserve lacks {item_key}: requested {quantity}, available {reserve}"
        )
    facts[reserve_key] = reserve - quantity
    facts[issued_key] = max(0, int(facts.get(issued_key, 0))) + quantity
    staging = formation.setdefault("equipment_staging_by_item", {})
    if not isinstance(staging, MutableMapping):
        raise ValueError("formation equipment staging ledger is invalid")
    staging[str(item_key)] = max(0, int(staging.get(str(item_key), 0))) + quantity
    converted = _convert_complete_sets(planner, formation)
    _recompute_completeness(formation)
    formation.setdefault("equipment_issue_history", []).append({
        "at": at,
        "kind": "house_armory_issue",
        "item_key": str(item_key),
        "quantity": quantity,
        "source_ref": "equipment_inventories",
        "complete_loadout_units_converted": converted,
    })
    formation["equipment_issue_history"] = formation["equipment_issue_history"][-32:]
    planner.put(_INVENTORY_PATH, registry)
    planner.put(formation_path, formation)
    return {
        "formation_ref": str(formation_ref),
        "item_key": str(item_key),
        "quantity": quantity,
        "complete_loadout_units_converted": converted,
        "equipment_units_by_role": copy.deepcopy(dict(formation.get("equipment_units_by_role", {}))),
        "equipment_completeness": formation.get("equipment_completeness"),
        "equipment_staging_by_item": copy.deepcopy(dict(formation.get("equipment_staging_by_item", {}))),
    }


class FormationArmoryIssueMixin:
    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type != "equipment_issue" or not str(payload.get("target_ref", "")).startswith("formation_"):
            return super()._dispatch(command, payload)
        result = issue_house_armory_to_formation(
            self,
            formation_ref=str(payload.get("target_ref", "")),
            item_key=str(payload.get("item_key", "")),
            quantity=int(payload.get("quantity", 0)),
            actor_ref=str(command.actor_id),
            at=str(self._world_time()),
        )
        self._write_meta(command, str(self._world_time()))
        return self._result(**result)


__all__ = [
    "FormationArmoryIssueMixin",
    "house_armory_reserve_available",
    "issue_house_armory_to_formation",
]
