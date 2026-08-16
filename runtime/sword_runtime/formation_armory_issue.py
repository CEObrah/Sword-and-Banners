"""Conserved House Tang armory issue to exact formations.

The baseline equipment surface transfers exact-person manifests.  Formation equipment
is deliberately abstracted as complete loadout units, so House armory stock needs a
staging step: each exact item leaves the institutional reserve and is allocated to
one formation; only a complete registered role loadout is converted into formation
``equipment_units_by_role``.  Partial kits never inflate equipment completeness.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

_INVENTORY_PATH = "state/inv/inventories.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_PROGRAM_RULES_PATH = "game/data/mechanics/house-tang-programs.json"

# Exact existing conservation counters in state/inv/inventories.json.
_ARMORY_COUNTERS: dict[str, tuple[str, str, str]] = {
    "armor_tang": ("tang_restricted_equipment", "Tang Armor unissued reserve", "Tang Armor issued"),
    "helmet_tang": ("tang_restricted_equipment", "Tang Helmet unissued reserve", "Tang Helmet issued"),
    "shield_tang": ("tang_restricted_equipment", "Tang Shield unissued reserve", "Tang Shield issued"),
    "weapon_bow_great_war": ("bows", "Great War Bow armory reserve", "Great War Bow active issued"),
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


def _gbg_loadout(planner: Any) -> tuple[str, ...]:
    rules = planner.read(_PROGRAM_RULES_PATH)
    great = rules.get("great_bow_guard", {}) if isinstance(rules, Mapping) else {}
    raw = great.get("fighter_loadout", []) if isinstance(great, Mapping) else []
    values = tuple(str(value) for value in raw if isinstance(value, str) and value)
    if not values:
        raise ValueError("Great Bow Guard registered fighter loadout is unavailable")
    return values


def _formation_units(formation: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    units = formation.setdefault("equipment_units_by_role", {})
    if not isinstance(units, MutableMapping):
        raise ValueError("formation equipment unit ledger is invalid")
    return units


def _recompute_completeness(formation: MutableMapping[str, Any]) -> None:
    personnel = max(1, int(formation.get("personnel", 0)))
    units = _formation_units(formation)
    total = sum(max(0, int(value)) for value in units.values())
    formation["equipment_completeness"] = f"{min(1.0, total / personnel):.4f}"


def _convert_complete_gbg_sets(planner: Any, formation: MutableMapping[str, Any]) -> int:
    composition = formation.get("composition", {})
    if not isinstance(composition, Mapping) or int(composition.get("great_bow_guard", 0)) <= 0:
        return 0
    staging = formation.setdefault("equipment_staging_by_item", {})
    if not isinstance(staging, MutableMapping):
        raise ValueError("formation equipment staging ledger is invalid")
    loadout = _gbg_loadout(planner)
    if any(item not in staging for item in loadout):
        return 0
    possible = min(max(0, int(staging.get(item, 0))) for item in loadout)
    units = _formation_units(formation)
    current = max(0, int(units.get("great_bow_guard", 0)))
    headroom = max(0, int(composition.get("great_bow_guard", 0)) - current)
    complete = min(possible, headroom)
    if complete <= 0:
        return 0
    for item in loadout:
        remaining = max(0, int(staging.get(item, 0)) - complete)
        if remaining:
            staging[item] = remaining
        else:
            staging.pop(item, None)
    units["great_bow_guard"] = current + complete
    _recompute_completeness(formation)
    return complete


def issue_house_armory_to_formation(
    planner: Any,
    *,
    formation_ref: str,
    item_key: str,
    quantity: int,
    actor_ref: str,
    at: str,
) -> dict[str, Any]:
    """Move exact House reserve stock into one formation's equipment staging.

    This function performs no procurement.  If an item has no registered House
    reserve counter, the shortage remains real and the issue fails closed.
    """
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
    location = str(formation.get("location_ref", ""))
    if not location.startswith("loc_tang_manor_"):
        raise PermissionError("House Tang armory issue requires the formation to be at Tang Manor")

    # House stock use was explicitly authorized by the persisted field-preparation
    # request.  Formation command alone is not treated as House treasury authority.
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
        raise ValueError(f"House Tang armory reserve lacks {item_key}: requested {quantity}, available {reserve}")
    facts[reserve_key] = reserve - quantity
    facts[issued_key] = max(0, int(facts.get(issued_key, 0))) + quantity

    staging = formation.setdefault("equipment_staging_by_item", {})
    if not isinstance(staging, MutableMapping):
        raise ValueError("formation equipment staging ledger is invalid")
    staging[str(item_key)] = max(0, int(staging.get(str(item_key), 0))) + quantity
    converted = _convert_complete_gbg_sets(planner, formation)
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
    """Extend equipment_issue to House-authorized exact formations."""

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type != "equipment_issue":
            return super()._dispatch(command, payload)
        target_ref = str(payload.get("target_ref", ""))
        if not target_ref.startswith("formation_"):
            return super()._dispatch(command, payload)
        result = issue_house_armory_to_formation(
            self,
            formation_ref=target_ref,
            item_key=str(payload.get("item_key", "")),
            quantity=int(payload.get("quantity", 0)),
            actor_ref=str(command.actor_id),
            at=str(self._world_time()),
        )
        self._write_meta(command, str(self._world_time()))
        return self._result(**result)


__all__ = ["FormationArmoryIssueMixin", "issue_house_armory_to_formation"]
