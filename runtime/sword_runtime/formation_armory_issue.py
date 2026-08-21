"""Aggregate, conserved House Tang outfitting and formation equipment service.

Issued equipment belongs to formations as complete role-appropriate sets.  The
House inventory stores only unissued aggregate set capacity.  Ammunition and
living mounts remain in their exact depot/mount authorities.  No monthly item
factory or obsolete weapon-variant reserve ledger exists here.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.geography import location_chain

_INVENTORY_PATH = "state/inv/inventories.json"
_OUTFITTING_RULES = "game/data/mechanics/outfitting.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_POPULATION_PATH = "state/population/tang-manor.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_ECONOMY_PATH = "state/economy/private/qin.json"


def _record(registry: MutableMapping[str, Any], record_id: str) -> MutableMapping[str, Any]:
    for row in registry.get("records", []):
        if isinstance(row, MutableMapping) and row.get("record_id") == record_id:
            facts = row.setdefault("facts", {})
            if not isinstance(facts, MutableMapping):
                raise ValueError(f"inventory record {record_id} has no mutable facts")
            return facts
    raise ValueError(f"inventory record {record_id} is unavailable")


def _formation_units(formation: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    units = formation.setdefault("equipment_units_by_role", {})
    if not isinstance(units, MutableMapping):
        raise ValueError("formation equipment unit ledger is invalid")
    return units


def _recompute_completeness(formation: MutableMapping[str, Any]) -> None:
    personnel = max(1, int(formation.get("personnel", 0)))
    total = sum(max(0, int(v)) for v in _formation_units(formation).values())
    formation["equipment_completeness"] = f"{min(1.0, total / personnel):.4f}"


def _replace_serviceable_shields(planner: Any, formation: MutableMapping[str, Any], item_key: str = "outfitting_role_set") -> int:
    """Restore missing serviceable shields from fresh complete sets or staged shields."""
    if item_key not in {"outfitting_role_set", "shield_standard"}:
        return 0
    units = _formation_units(formation)
    composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
    shields = formation.setdefault("shield_units_by_role", {})
    conditions = formation.setdefault("shield_condition_by_role", {})
    staging = formation.get("equipment_staging_by_item") if isinstance(formation.get("equipment_staging_by_item"), MutableMapping) else None
    replaced = 0
    for role in sorted(str(r) for r in composition):
        eligible = min(max(0, int(composition.get(role, 0))), max(0, int(units.get(role, 0))))
        current = max(0, int(shields.get(role, eligible)))
        if current >= eligible:
            continue
        missing = eligible - current
        if item_key == "shield_standard":
            available = max(0, int(staging.get(item_key, 0))) if staging is not None else 0
            delta = min(missing, available)
        else:
            delta = missing
        if delta <= 0:
            continue
        current_condition = max(0.0, min(100.0, float(conditions.get(role, 100.0))))
        after_units = current + delta
        shields[role] = after_units
        conditions[role] = round((current * current_condition + delta * 100.0) / max(1, after_units), 3)
        if item_key == "shield_standard" and staging is not None:
            remaining = max(0, int(staging.get(item_key, 0)) - delta)
            if remaining:
                staging[item_key] = remaining
            else:
                staging.pop(item_key, None)
        replaced += delta
    return replaced


def _replace_serviceable_armor_sets(planner: Any, formation: MutableMapping[str, Any]) -> int:
    """Restore missing armor sets, conserving staged body armor and helmets when present."""
    units = _formation_units(formation)
    composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
    armor = formation.setdefault("armor_units_by_role", {})
    conditions = formation.setdefault("armor_condition_by_role", {})
    staging = formation.get("equipment_staging_by_item") if isinstance(formation.get("equipment_staging_by_item"), MutableMapping) else None
    staged_mode = bool(staging is not None and ("armor_heavy" in staging or "helmet_standard" in staging))
    replaced = 0
    for role in sorted(str(r) for r in composition):
        eligible = min(max(0, int(composition.get(role, 0))), max(0, int(units.get(role, 0))))
        current = max(0, int(armor.get(role, eligible)))
        if current >= eligible:
            continue
        missing = eligible - current
        if staged_mode:
            available = min(max(0, int(staging.get("armor_heavy", 0))), max(0, int(staging.get("helmet_standard", 0))))
            delta = min(missing, available)
        else:
            delta = missing
        if delta <= 0:
            continue
        current_condition = max(0.0, min(100.0, float(conditions.get(role, 100.0))))
        after_units = current + delta
        armor[role] = after_units
        conditions[role] = round((current * current_condition + delta * 100.0) / max(1, after_units), 3)
        if staged_mode and staging is not None:
            for key in ("armor_heavy", "helmet_standard"):
                remaining = max(0, int(staging.get(key, 0)) - delta)
                if remaining:
                    staging[key] = remaining
                else:
                    staging.pop(key, None)
        replaced += delta
    return replaced


def _role_uses_crossbow(planner: Any, formation: Mapping[str, Any], role: str) -> bool:
    try:
        profile = planner._combat_role_profile(role)
    except Exception:
        return False
    return str(profile.get("loadout_id", "")).lower().find("crossbow") >= 0 or str(profile.get("primary_weapon", "")).lower().find("crossbow") >= 0


def _reserve_facts(planner: Any, *, mutable: bool = False):
    inv = copy.deepcopy(planner.read(_INVENTORY_PATH)) if mutable else planner.read(_INVENTORY_PATH)
    facts = _record(inv, "house_tang_outfitting_sets") if mutable else next(
        (row.get("facts", {}) for row in inv.get("records", []) if isinstance(row, Mapping) and row.get("record_id") == "house_tang_outfitting_sets"), {}
    )
    return inv, facts


def house_armory_reserve_available(planner: Any, item_key: str) -> int:
    _inv, facts = _reserve_facts(planner)
    aliases = {
        "outfitting_role_set": "standard_role_sets_reserve",
        "outfitting_crossbow_role_set": "crossbow_role_sets_reserve",
        "outfitting_mounted_harness_set": "mounted_harness_sets_reserve",
    }
    key = aliases.get(str(item_key))
    if key is None:
        return 0
    return max(0, int(facts.get(key, 0)))


def _repair_authorized(planner: Any, formation: Mapping[str, Any], actor_ref: str) -> None:
    if str(formation.get("administrative_owner", "")) != "house_tang":
        raise PermissionError("House Tang equipment service requires House Tang administrative ownership")
    if str(formation.get("command_authority", "")) != str(actor_ref):
        raise PermissionError("formation equipment service requires exact formation command authority")
    loc = str(formation.get("location_ref", ""))
    if "loc_tang_manor" not in location_chain(planner.read, loc):
        raise PermissionError("House Tang equipment service requires the formation to be physically inside Tang Manor")


def _qin_tang_region(planner: Any, economy: dict[str, Any]) -> dict[str, Any]:
    if hasattr(planner, "_ensure_local_economy_ledger"):
        planner._ensure_local_economy_ledger("qin", economy)
    regions = economy.get("local_regions", {}).get("regions", {}) if isinstance(economy.get("local_regions"), Mapping) else {}
    for ref in ("loc_tang_manor", "loc_qin_regional_01"):
        row = regions.get(ref) if isinstance(regions, Mapping) else None
        if isinstance(row, dict):
            return row
    raise ValueError("House Tang has no exact local private-economy procurement region")


def repair_house_formation_equipment(planner: Any, *, formation_ref: str, hours: int, actor_ref: str, at: str, categories: tuple[str, ...] = ("shield", "armor")) -> dict[str, Any]:
    if int(hours) <= 0:
        raise ValueError("repair hours must be positive")
    formation_path, raw = planner._load_formation(str(formation_ref))
    formation = copy.deepcopy(raw)
    _repair_authorized(planner, formation, actor_ref)
    rules = planner.read(_OUTFITTING_RULES).get("repair", {})
    minimum = float(rules.get("minimum_repairable_condition_pct", 5.0))
    selected = {str(x) for x in categories} & {"shield", "armor"}
    if not selected:
        raise ValueError("repair requires shield and/or armor category")
    composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
    units = _formation_units(formation)
    shield_units = formation.setdefault("shield_units_by_role", {})
    armor_units = formation.setdefault("armor_units_by_role", {})
    shield_cond = formation.setdefault("shield_condition_by_role", {})
    armor_cond = formation.setdefault("armor_condition_by_role", {})
    tasks: list[tuple[str, str, int, float]] = []
    for role in sorted(str(r) for r in composition):
        equipped = min(max(0, int(composition.get(role, 0))), max(0, int(units.get(role, 0))))
        if "shield" in selected:
            n = min(equipped, max(0, int(shield_units.get(role, equipped))))
            c = max(0.0, min(100.0, float(shield_cond.get(role, 100.0))))
            if n and minimum <= c < 100.0: tasks.append((role, "shield", n, c))
        if "armor" in selected:
            n = min(equipped, max(0, int(armor_units.get(role, equipped))))
            c = max(0.0, min(100.0, float(armor_cond.get(role, 100.0))))
            if n and minimum <= c < 100.0: tasks.append((role, "armor", n, c))
    equivalent = sum(n * (100.0-c) / 100.0 for _r,_k,n,c in tasks)
    if equivalent <= 1e-9:
        raise ValueError("formation has no surviving damaged shield/armor equipment eligible for repair")
    pop = planner.read(_POPULATION_PATH)
    workers = min(max(0, int(pop.get("strata", {}).get(str(rules.get("worker_stratum", "craft_and_industry")), 0))), max(1, int(rules.get("maximum_parallel_workers", 7000))))
    labor_need = equivalent * float(rules.get("worker_hours_per_equivalent_destroyed_set", 334.0))
    material_need = equivalent * float(rules.get("construction_material_units_per_equivalent_destroyed_set", 2.4))
    silver_need = equivalent * float(rules.get("silver_per_equivalent_destroyed_set", 11.1))
    economy = copy.deepcopy(planner.read(_ECONOMY_PATH)); region = _qin_tang_region(planner, economy)
    stock = region.setdefault("commodity_stock", {})
    material_available = max(0, int(stock.get("construction_material_units", 0)))
    treasury = copy.deepcopy(planner.read(_TREASURY_PATH)); silver_available = max(0, int(treasury.get("silver", 0)))
    fraction = min(1.0, workers * int(hours) / max(1e-9,labor_need), material_available / max(1e-9,material_need), silver_available / max(1e-9,silver_need))
    if fraction <= 1e-9: raise ValueError("House Tang lacks current labor, construction materials, or silver for equipment repair")
    material_used = min(material_available, int(math.ceil(material_need * fraction - 1e-9)))
    silver_used = min(silver_available, int(math.ceil(silver_need * fraction - 1e-9)))
    stock["construction_material_units"] = material_available - material_used
    treasury["silver"] = silver_available - silver_used
    region["cash_silver"] = max(0, int(region.get("cash_silver", 0))) + silver_used
    if hasattr(planner, "_record_private_realized_sale") and silver_used:
        planner._record_private_realized_sale(region, amount_silver=silver_used, at=at, kind="formation_equipment_repair", resource="construction_material_units", quantity=material_used)
    role_results: dict[str, dict[str, Any]] = {}
    for role,kind,n,c in tasks:
        after = c + (100.0-c)*fraction
        target = shield_cond if kind=="shield" else armor_cond
        target[role]=round(min(100.0,after),3)
        role_results.setdefault(role,{})[kind]={"units":n,"before_condition_pct":round(c,3),"after_condition_pct":target[role]}
    formation.setdefault("equipment_service_runtime", {})["last_repair"] = {"at":at,"hours":int(hours),"repair_fraction":round(fraction,8),"material_units":material_used,"silver":silver_used}
    if hasattr(planner, "_sync_local_economy_aggregate"): planner._sync_local_economy_aggregate(economy)
    planner.put(_ECONOMY_PATH,economy); planner.put(_TREASURY_PATH,treasury); planner.put(formation_path,formation)
    return {"formation_ref":formation_ref,"hours":int(hours),"categories":sorted(selected),"workers_available":workers,"worker_hours_used":round(labor_need*fraction,3),"repair_fraction":round(fraction,8),"construction_material_units_consumed":material_used,"silver_paid":silver_used,"role_results":role_results,"shield_units_by_role":copy.deepcopy(dict(shield_units)),"armor_units_by_role":copy.deepcopy(dict(armor_units)),"shield_condition_by_role":copy.deepcopy(dict(shield_cond)),"armor_condition_by_role":copy.deepcopy(dict(armor_cond))}


def issue_house_armory_to_formation(planner: Any, *, formation_ref: str, item_key: str, quantity: int, actor_ref: str, at: str) -> dict[str, Any]:
    quantity=max(0,int(quantity))
    if quantity<=0: raise ValueError("formation outfitting issue quantity must be positive")
    aliases={"outfitting_role_set":"standard_role_sets_reserve","outfitting_crossbow_role_set":"crossbow_role_sets_reserve","outfitting_mounted_harness_set":"mounted_harness_sets_reserve"}
    reserve_key=aliases.get(str(item_key))
    if reserve_key is None:
        raise ValueError("House Tang issues aggregate role-outfitting sets; exact obsolete item reserves are not an authority")
    formation_path, raw=planner._load_formation(str(formation_ref)); formation=copy.deepcopy(raw)
    _repair_authorized(planner,formation,actor_ref)
    inv,facts=_reserve_facts(planner,mutable=True); available=max(0,int(facts.get(reserve_key,0)))
    if available<quantity: raise ValueError(f"House Tang outfitting reserve lacks {item_key}: requested {quantity}, available {available}")
    facts[reserve_key]=available-quantity
    converted=0
    if item_key in {"outfitting_role_set","outfitting_crossbow_role_set"}:
        units=_formation_units(formation); composition=formation.get("composition",{}) if isinstance(formation.get("composition"),Mapping) else {}
        remaining=quantity
        for role in sorted(str(r) for r in composition):
            cross=_role_uses_crossbow(planner,formation,role)
            if (item_key=="outfitting_crossbow_role_set") != cross: continue
            target=max(0,int(composition.get(role,0))); current=max(0,int(units.get(role,0))); add=min(remaining,max(0,target-current))
            if add:
                units[role]=current+add; converted+=add; remaining-=add
        spare_key="crossbow_role_sets" if item_key=="outfitting_crossbow_role_set" else "standard_role_sets"
        spares=formation.setdefault("spare_outfitting_sets",{}); spares[spare_key]=max(0,int(spares.get(spare_key,0)))+remaining
        _replace_serviceable_shields(planner,formation,"outfitting_role_set"); _replace_serviceable_armor_sets(planner,formation); _recompute_completeness(formation)
    else:
        formation["spare_mounted_harness_sets"] = max(0,int(formation.get("spare_mounted_harness_sets",0)))+quantity
    formation.setdefault("equipment_service_runtime",{})["last_issue"]={"at":at,"kind":item_key,"quantity":quantity,"converted_to_active_role_sets":converted}
    planner.put(_INVENTORY_PATH,inv); planner.put(formation_path,formation)
    return {"formation_ref":formation_ref,"item_key":item_key,"quantity":quantity,"complete_loadout_units_converted":converted,"equipment_units_by_role":copy.deepcopy(dict(formation.get("equipment_units_by_role",{}))),"equipment_completeness":formation.get("equipment_completeness"),"spare_outfitting_sets":copy.deepcopy(dict(formation.get("spare_outfitting_sets",{}))),"spare_mounted_harness_sets":int(formation.get("spare_mounted_harness_sets",0))}


class FormationArmoryIssueMixin:
    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "formation_equipment_repair":
            started=self._world_time(); cats=payload.get("categories",["shield","armor"]); categories=tuple(str(x) for x in cats) if isinstance(cats,list) else ("shield","armor")
            result=repair_house_formation_equipment(self,formation_ref=str(payload.get("formation_ref","")),hours=int(payload.get("hours",1)),actor_ref=str(command.actor_id),at=str(started),categories=categories)
            world_time,metrics=self._advance_seconds(int(payload.get("hours",1))*3600); self._write_meta(command,str(world_time)); return self._result(world_time=str(world_time),**result,**metrics)
        if command.command_type != "equipment_issue" or not str(payload.get("target_ref","")).startswith("formation_"):
            return super()._dispatch(command,payload)
        result=issue_house_armory_to_formation(self,formation_ref=str(payload.get("target_ref","")),item_key=str(payload.get("item_key","")),quantity=int(payload.get("quantity",0)),actor_ref=str(command.actor_id),at=str(self._world_time()))
        self._write_meta(command,str(self._world_time())); return self._result(**result)

__all__=["FormationArmoryIssueMixin","house_armory_reserve_available","issue_house_armory_to_formation","repair_house_formation_equipment","_replace_serviceable_shields","_replace_serviceable_armor_sets"]
