"""Conserved House Tang armory issue to exact formations.

Exact items leave House reserves and enter a formation staging ledger. When the
formation declares a registered loadout, complete staged sets are converted into
abstract equipment units for its actual troop role. No parallel formation-specific issue path is required.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.house_tang_production import (
    _available as _production_available,
    _consume as _production_consume,
    _credit_private_cash as _production_credit_private_cash,
    _reconcile_private_aggregate as _production_reconcile_private_aggregate,
    _regions as _production_regions,
    _worker_count as _production_worker_count,
)

_INVENTORY_PATH = "state/inv/inventories.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_LOADOUT_INDEX_PATH = "game/data/loadouts.json"
_PRODUCTION_RULES_PATH = "game/data/mechanics/house-tang-production.json"
_POPULATION_PATH = "state/population/tang-manor.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_ECONOMY_PATH = "state/economy/private/qin.json"

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


def _loadout_items(planner: Any, formation: Mapping[str, Any], role: str | None = None) -> tuple[str, ...]:
    by_role = formation.get("registered_loadouts_by_role", {})
    loadout_id = by_role.get(role) if isinstance(by_role, Mapping) and isinstance(role, str) else None
    loadout_id = loadout_id or formation.get("equipment_loadout_id") or formation.get("registered_loadout_ref")
    # Formation combat derives ordinary troop equipment from the canonical combat
    # role profile when no formation-local loadout override exists.  Armory repair
    # and issue must follow the same route or a role can physically fight with a
    # shield while the workshop is unable to discover that shield.
    if (not isinstance(loadout_id, str) or not loadout_id) and isinstance(role, str):
        try:
            profile = planner._combat_role_profile(role)
            candidate = profile.get("loadout_id") if isinstance(profile, Mapping) else None
            if isinstance(candidate, str) and candidate:
                loadout_id = candidate
        except (AttributeError, KeyError, ValueError, FileNotFoundError):
            pass
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
    """Convert exact staged items into complete loadout units role-by-role.

    A formation is allowed to contain several troop roles. Shared staged items are
    consumed deterministically by role order and never collapsed into the largest
    component.
    """
    composition = formation.get("composition", {})
    if not isinstance(composition, Mapping) or not composition:
        return 0
    staging = formation.setdefault("equipment_staging_by_item", {})
    if not isinstance(staging, MutableMapping):
        raise ValueError("formation equipment staging ledger is invalid")
    units = _formation_units(formation)
    converted = 0
    for role in sorted(str(k) for k, v in composition.items() if int(v) > 0):
        target = max(0, int(composition.get(role, 0)))
        current = max(0, int(units.get(role, 0)))
        deficit = max(0, target - current)
        if deficit <= 0:
            continue
        required = _loadout_items(planner, formation, role)
        if not required or any(max(0, int(staging.get(item, 0))) <= 0 for item in required):
            continue
        possible = min(max(0, int(staging.get(item, 0))) for item in required)
        complete = min(possible, deficit)
        if complete <= 0:
            continue
        for item in required:
            remain = max(0, int(staging.get(item, 0)) - complete)
            if remain:
                staging[item] = remain
            else:
                staging.pop(item, None)
        units[role] = current + complete
        shield_items=[]
        for item in required:
            try:
                record=planner._item_record(str(item))
            except Exception:
                record={}
            if isinstance(record, Mapping) and str(record.get("schema", "")) == "shield":
                shield_items.append(str(item))
        if shield_items:
            shield_units=formation.setdefault("shield_units_by_role", {})
            if not isinstance(shield_units, MutableMapping):
                raise ValueError("formation shield unit ledger is invalid")
            existing=max(0,min(current,int(shield_units.get(role,current) or 0)))
            added=max(0,min(complete,target-existing))
            shield_units[role]=min(target,existing+added)
            if added>0:
                shield_condition=formation.setdefault("shield_condition_by_role", {})
                if not isinstance(shield_condition, MutableMapping):
                    raise ValueError("formation shield condition ledger is invalid")
                prior_condition=max(0.0,min(100.0,float(shield_condition.get(role,100.0) or 0.0))) if existing>0 else 100.0
                shield_condition[role]=round((prior_condition*existing+100.0*added)/max(1,existing+added),3)
        protective=[]
        for item in required:
            try:
                record=planner._item_record(str(item))
            except Exception:
                record={}
            if isinstance(record, Mapping) and str(record.get("schema", "")) in {"human_armor","helmet"}:
                protective.append(str(item))
        if protective:
            armor_units=formation.setdefault("armor_units_by_role", {})
            if not isinstance(armor_units, MutableMapping):
                raise ValueError("formation armor unit ledger is invalid")
            existing=max(0,min(current,int(armor_units.get(role,current) or 0)))
            added=max(0,min(complete,target-existing))
            armor_units[role]=min(target,existing+added)
            if added>0:
                armor_condition=formation.setdefault("armor_condition_by_role", {})
                if not isinstance(armor_condition, MutableMapping):
                    raise ValueError("formation armor condition ledger is invalid")
                prior_condition=max(0.0,min(100.0,float(armor_condition.get(role,100.0) or 0.0))) if existing>0 else 100.0
                armor_condition[role]=round((prior_condition*existing+100.0*added)/max(1,existing+added),3)
        converted += complete
    _recompute_completeness(formation)
    return converted



def _replace_serviceable_shields(planner: Any, formation: MutableMapping[str, Any], item_key: str) -> int:
    """Consume staged shields to replace missing physical formation shields.

    A destroyed shield does not erase the rest of that soldier's loadout.  The
    complete-set equipment ledger therefore remains separate from the exact
    serviceable shield count.  Replacement shields can refill that count without
    requiring an entire armor/weapon set to be reissued.
    """
    try:
        item = planner._item_record(str(item_key))
    except Exception:
        return 0
    if not isinstance(item, Mapping) or str(item.get("schema", "")) != "shield":
        return 0
    staging = formation.setdefault("equipment_staging_by_item", {})
    if not isinstance(staging, MutableMapping):
        raise ValueError("formation equipment staging ledger is invalid")
    available = max(0, int(staging.get(str(item_key), 0)))
    if available <= 0:
        return 0
    composition = formation.get("composition", {})
    if not isinstance(composition, Mapping):
        return 0
    equipped = _formation_units(formation)
    shield_units = formation.setdefault("shield_units_by_role", {})
    if not isinstance(shield_units, MutableMapping):
        raise ValueError("formation shield unit ledger is invalid")
    replaced = 0
    for role in sorted(str(k) for k, v in composition.items() if int(v) > 0):
        if available <= 0:
            break
        required = _loadout_items(planner, formation, role)
        if str(item_key) not in required:
            continue
        role_personnel = max(0, int(composition.get(role, 0)))
        role_equipped = min(role_personnel, max(0, int(equipped.get(role, 0))))
        if role_equipped <= 0:
            continue
        # Existing formations predate the explicit shield ledger.  In that case
        # complete loadout units establish the initial physical shield count.
        current = max(0, min(role_equipped, int(shield_units.get(role, role_equipped) or 0)))
        deficit = max(0, role_equipped - current)
        take = min(deficit, available)
        if take <= 0:
            shield_units.setdefault(role, current)
            continue
        shield_units[role] = current + take
        shield_condition = formation.setdefault("shield_condition_by_role", {})
        if not isinstance(shield_condition, MutableMapping):
            raise ValueError("formation shield condition ledger is invalid")
        prior_condition=max(0.0,min(100.0,float(shield_condition.get(role,100.0) or 0.0))) if current>0 else 100.0
        shield_condition[role]=round((prior_condition*current+100.0*take)/max(1,current+take),3)
        available -= take
        replaced += take
    if available:
        staging[str(item_key)] = available
    else:
        staging.pop(str(item_key), None)
    return replaced

def _replace_serviceable_armor_sets(planner: Any, formation: MutableMapping[str, Any]) -> int:
    """Consume staged body-armor/helmet components to replace lost protective sets.

    Protective-set quantity is separate from the complete weapon/loadout ledger.
    A replacement set is restored only when every protective component registered
    by that role's loadout is physically present in formation staging.
    """
    staging=formation.setdefault("equipment_staging_by_item", {})
    if not isinstance(staging,MutableMapping):
        raise ValueError("formation equipment staging ledger is invalid")
    composition=formation.get("composition", {})
    if not isinstance(composition,Mapping): return 0
    equipped=_formation_units(formation)
    armor_units=formation.setdefault("armor_units_by_role", {})
    if not isinstance(armor_units,MutableMapping):
        raise ValueError("formation armor unit ledger is invalid")
    replaced=0
    for role in sorted(str(k) for k,v in composition.items() if int(v)>0):
        role_personnel=max(0,int(composition.get(role,0))); role_equipped=min(role_personnel,max(0,int(equipped.get(role,0))))
        if role_equipped<=0: continue
        protective=[]
        for item in _loadout_items(planner,formation,role):
            try: record=planner._item_record(str(item))
            except Exception: record={}
            if isinstance(record,Mapping) and str(record.get("schema","")) in {"human_armor","helmet"}: protective.append(str(item))
        if not protective: continue
        current=max(0,min(role_equipped,int(armor_units.get(role,role_equipped) or 0)))
        deficit=max(0,role_equipped-current)
        if deficit<=0:
            armor_units.setdefault(role,current); continue
        possible=min(max(0,int(staging.get(item,0))) for item in protective) if protective else 0
        take=min(deficit,possible)
        if take<=0: continue
        for item in protective:
            remain=max(0,int(staging.get(item,0))-take)
            if remain: staging[item]=remain
            else: staging.pop(item,None)
        armor_units[role]=current+take
        armor_condition=formation.setdefault("armor_condition_by_role", {})
        if not isinstance(armor_condition,MutableMapping):
            raise ValueError("formation armor condition ledger is invalid")
        prior=max(0.0,min(100.0,float(armor_condition.get(role,100.0) or 0.0))) if current>0 else 100.0
        armor_condition[role]=round((prior*current+100.0*take)/max(1,current+take),3)
        replaced+=take
    return replaced


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


def _repair_authorized(planner: Any, formation: Mapping[str, Any], actor_ref: str) -> None:
    if str(formation.get("command_authority", "")) != str(actor_ref):
        raise PermissionError("formation equipment repair requires exact formation command authority")
    if not str(formation.get("location_ref", "")).startswith("loc_tang_manor_"):
        raise PermissionError("House Tang equipment repair requires the formation to be at Tang Manor")
    house = planner.read(_HOUSE_PATH)
    programs = house.get("administrative_programs", {}) if isinstance(house, Mapping) else {}
    prep = programs.get("wei_field_preparation", {}) if isinstance(programs, Mapping) else {}
    if not isinstance(prep, Mapping) or str(prep.get("principal_ref", "")) != str(actor_ref):
        raise PermissionError("House equipment repair requires persisted House field-preparation authorization")


def _production_recipe_by_item(planner: Any, item_key: str) -> Mapping[str, Any] | None:
    counter = _ARMORY_COUNTERS.get(str(item_key))
    if counter is None:
        return None
    reserve_key = counter[1]
    rules = planner.read(_PRODUCTION_RULES_PATH)
    for row in rules.get("items", []) if isinstance(rules, Mapping) else []:
        if isinstance(row, Mapping) and str(row.get("reserve_key", "")) == reserve_key:
            return row
    return None


def repair_house_formation_equipment(
    planner: Any,
    *,
    formation_ref: str,
    hours: int,
    actor_ref: str,
    at: str,
    categories: tuple[str, ...] = ("shield", "armor"),
) -> dict[str, Any]:
    """Repair surviving House formation shields/armor through exact production inputs.

    Destroyed or missing units are deliberately excluded.  They require separate
    armory issue from exact unissued reserve.  Repair work consumes real Tang
    forge-worker hours, nearby private construction materials, and House silver;
    those worker-hours are also deducted from the next monthly manufacture close.
    """
    hours = int(hours)
    if hours <= 0:
        raise ValueError("formation equipment repair hours must be positive")
    selected = tuple(sorted({str(x) for x in categories if str(x) in {"shield", "armor"}}))
    if not selected:
        raise ValueError("formation equipment repair requires shield and/or armor category")
    formation_path, formation0 = planner._load_formation(str(formation_ref))
    formation = copy.deepcopy(formation0)
    _repair_authorized(planner, formation, actor_ref)

    rules = planner.read(_PRODUCTION_RULES_PATH)
    repair_rules = rules.get("military_equipment_repair", {}) if isinstance(rules, Mapping) else {}
    labor_fraction = max(0.01, min(1.0, float(repair_rules.get("labor_fraction_of_new_manufacture", 0.35) or 0.35)))
    material_fraction = max(0.0, min(1.0, float(repair_rules.get("material_fraction_of_new_manufacture", 0.30) or 0.30)))
    silver_fraction = max(0.0, min(1.0, float(repair_rules.get("silver_fraction_of_new_manufacture", 0.30) or 0.30)))
    minimum_condition = max(0.0, min(100.0, float(repair_rules.get("minimum_repairable_condition_pct", 5) or 5)))
    cycle_hours = max(1.0, float(rules.get("cycle_seconds", 2592000) or 2592000) / 3600.0)
    population = planner.read(_POPULATION_PATH)
    workers = _production_worker_count(population, rules, "forge_and_armory_workers")
    if workers <= 0:
        raise ValueError("House Tang has no available forge-and-armory workforce")
    worker_hour_budget = float(workers) * float(hours)

    composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
    shield_units = formation.setdefault("shield_units_by_role", {})
    armor_units = formation.setdefault("armor_units_by_role", {})
    shield_conditions = formation.setdefault("shield_condition_by_role", {})
    armor_conditions = formation.setdefault("armor_condition_by_role", {})
    if not all(isinstance(x, MutableMapping) for x in (shield_units, armor_units, shield_conditions, armor_conditions)):
        raise ValueError("formation equipment repair ledgers are invalid")

    tasks: list[dict[str, Any]] = []
    for role in sorted(str(k) for k, v in composition.items() if int(v) > 0):
        required = _loadout_items(planner, formation, role)
        if not required:
            continue
        if "shield" in selected:
            shield_items = []
            for item_id in required:
                try:
                    item = planner._item_record(str(item_id))
                except Exception:
                    item = {}
                if isinstance(item, Mapping) and str(item.get("schema", "")) == "shield":
                    shield_items.append(str(item_id))
            units = max(0, min(int(composition.get(role, 0)), int(shield_units.get(role, 0) or 0)))
            condition = max(0.0, min(100.0, float(shield_conditions.get(role, 100.0) or 0.0)))
            if units > 0 and condition >= minimum_condition and condition < 100.0:
                for item_id in shield_items:
                    tasks.append({"role": role, "category": "shield", "item_id": item_id, "units": units, "condition": condition})
        if "armor" in selected:
            protective = []
            for item_id in required:
                try:
                    item = planner._item_record(str(item_id))
                except Exception:
                    item = {}
                if isinstance(item, Mapping) and str(item.get("schema", "")) in {"human_armor", "helmet"}:
                    protective.append(str(item_id))
            units = max(0, min(int(composition.get(role, 0)), int(armor_units.get(role, 0) or 0)))
            condition = max(0.0, min(100.0, float(armor_conditions.get(role, 100.0) or 0.0)))
            if units > 0 and condition >= minimum_condition and condition < 100.0:
                for item_id in protective:
                    tasks.append({"role": role, "category": "armor", "item_id": item_id, "units": units, "condition": condition})

    quoted: list[dict[str, Any]] = []
    total_worker_hours = total_material = total_silver = 0.0
    for task in tasks:
        recipe = _production_recipe_by_item(planner, str(task["item_id"]))
        if not isinstance(recipe, Mapping):
            continue
        rate = max(1e-9, float(recipe.get("units_per_worker_month", 0.0) or 0.0))
        batch = max(1, int(recipe.get("batch_size", 1) or 1))
        material_per_unit = max(0.0, float(recipe.get("material_units_per_batch", 0) or 0)) / batch
        silver_per_unit = max(0.0, float(recipe.get("silver_per_batch", 0) or 0)) / batch
        deficit_fraction = max(0.0, (100.0 - float(task["condition"])) / 100.0)
        equivalent_units = max(0.0, float(task["units"]) * deficit_fraction)
        worker_hours = equivalent_units * (cycle_hours / rate) * labor_fraction
        material = equivalent_units * material_per_unit * material_fraction
        silver = equivalent_units * silver_per_unit * silver_fraction
        row = dict(task)
        row.update({"equivalent_new_units": equivalent_units, "worker_hours": worker_hours, "material_units": material, "silver": silver})
        quoted.append(row)
        total_worker_hours += worker_hours
        total_material += material
        total_silver += silver

    if total_worker_hours <= 1e-9:
        raise ValueError("formation has no serviceable damaged shield/armor equipment eligible for repair")

    economy = copy.deepcopy(planner.read(_ECONOMY_PATH))
    treasury = copy.deepcopy(planner.read(_TREASURY_PATH))
    region_refs = [str(value) for value in rules.get("procurement_regions", []) if isinstance(value, str)]
    regions = _production_regions(economy, region_refs)
    material_available = _production_available(regions, "construction_material_units")
    silver_available = max(0, int(treasury.get("silver", 0)))
    repair_fraction = min(1.0, worker_hour_budget / total_worker_hours)
    if total_material > 1e-9:
        repair_fraction = min(repair_fraction, material_available / total_material)
    if total_silver > 1e-9:
        repair_fraction = min(repair_fraction, silver_available / total_silver)
    repair_fraction = max(0.0, min(1.0, repair_fraction))
    if repair_fraction <= 1e-9:
        raise ValueError("House Tang lacks current labor, construction materials, or silver for equipment repair")

    material_used = min(material_available, max(0, int(math.ceil(total_material * repair_fraction - 1e-9))))
    silver_used = min(silver_available, max(0, int(math.ceil(total_silver * repair_fraction - 1e-9))))
    if material_used and _production_consume(regions, "construction_material_units", material_used) != material_used:
        raise ValueError("House Tang repair material conservation failed")
    treasury["silver"] = silver_available - silver_used
    _production_credit_private_cash(regions, silver_used)
    _production_reconcile_private_aggregate(economy)

    role_results: dict[str, dict[str, Any]] = {}
    for role in sorted(str(k) for k, v in composition.items() if int(v) > 0):
        row: dict[str, Any] = {}
        if "shield" in selected and int(shield_units.get(role, 0) or 0) > 0:
            before = max(0.0, min(100.0, float(shield_conditions.get(role, 100.0) or 0.0)))
            if minimum_condition <= before < 100.0:
                after = before + (100.0 - before) * repair_fraction
                shield_conditions[role] = round(min(100.0, after), 3)
                row["shield"] = {"units": int(shield_units.get(role, 0)), "before_condition_pct": round(before, 3), "after_condition_pct": round(float(shield_conditions[role]), 3)}
        if "armor" in selected and int(armor_units.get(role, 0) or 0) > 0:
            before = max(0.0, min(100.0, float(armor_conditions.get(role, 100.0) or 0.0)))
            if minimum_condition <= before < 100.0:
                after = before + (100.0 - before) * repair_fraction
                armor_conditions[role] = round(min(100.0, after), 3)
                row["armor"] = {"units": int(armor_units.get(role, 0)), "before_condition_pct": round(before, 3), "after_condition_pct": round(float(armor_conditions[role]), 3)}
        if row:
            role_results[role] = row

    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    runtime = house.setdefault("administrative_programs", {}).setdefault("house_equipment_production", {})
    worker_hours_used = total_worker_hours * repair_fraction
    runtime["repair_worker_hours_pending"] = round(max(0.0, float(runtime.get("repair_worker_hours_pending", 0.0) or 0.0)) + worker_hours_used, 3)
    history = runtime.setdefault("repair_history", [])
    history.append({
        "at": at,
        "formation_ref": str(formation_ref),
        "calendar_hours": hours,
        "worker_hours_used": round(worker_hours_used, 3),
        "repair_fraction_of_total_damage": round(repair_fraction, 8),
        "construction_material_units_consumed": material_used,
        "silver_paid": silver_used,
        "categories": list(selected),
        "role_results": copy.deepcopy(role_results),
        "rule": "surviving_equipment_repair_competes_with_house_manufacture_labor_and_consumes_exact_private_materials_plus_house_silver",
    })
    runtime["repair_history"] = history[-48:]
    formation.setdefault("equipment_issue_history", []).append({
        "at": at,
        "kind": "house_workshop_repair",
        "hours": hours,
        "worker_hours_used": round(worker_hours_used, 3),
        "construction_material_units_consumed": material_used,
        "silver_paid": silver_used,
        "repair_fraction": round(repair_fraction, 8),
        "categories": list(selected),
    })
    formation["equipment_issue_history"] = formation["equipment_issue_history"][-32:]

    planner.put(_ECONOMY_PATH, economy)
    planner.put(_TREASURY_PATH, treasury)
    planner.put(_HOUSE_PATH, house)
    planner.put(formation_path, formation)
    return {
        "formation_ref": str(formation_ref),
        "hours": hours,
        "categories": list(selected),
        "workers_available": workers,
        "worker_hours_used": round(worker_hours_used, 3),
        "repair_fraction": round(repair_fraction, 8),
        "construction_material_units_consumed": material_used,
        "silver_paid": silver_used,
        "role_results": role_results,
        "shield_units_by_role": copy.deepcopy(dict(shield_units)),
        "armor_units_by_role": copy.deepcopy(dict(armor_units)),
        "shield_condition_by_role": copy.deepcopy(dict(shield_conditions)),
        "armor_condition_by_role": copy.deepcopy(dict(armor_conditions)),
    }


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
    shield_units_replaced = _replace_serviceable_shields(planner, formation, str(item_key))
    armor_units_replaced = _replace_serviceable_armor_sets(planner, formation)
    converted = _convert_complete_sets(planner, formation)
    _recompute_completeness(formation)
    formation.setdefault("equipment_issue_history", []).append({
        "at": at,
        "kind": "house_armory_issue",
        "item_key": str(item_key),
        "quantity": quantity,
        "source_ref": "equipment_inventories",
        "complete_loadout_units_converted": converted,
        "shield_units_replaced": shield_units_replaced,
        "armor_units_replaced": armor_units_replaced,
    })
    formation["equipment_issue_history"] = formation["equipment_issue_history"][-32:]
    planner.put(_INVENTORY_PATH, registry)
    planner.put(formation_path, formation)
    return {
        "formation_ref": str(formation_ref),
        "item_key": str(item_key),
        "quantity": quantity,
        "complete_loadout_units_converted": converted,
        "shield_units_replaced": shield_units_replaced,
        "armor_units_replaced": armor_units_replaced,
        "shield_units_by_role": copy.deepcopy(dict(formation.get("shield_units_by_role", {}))),
        "armor_units_by_role": copy.deepcopy(dict(formation.get("armor_units_by_role", {}))),
        "equipment_units_by_role": copy.deepcopy(dict(formation.get("equipment_units_by_role", {}))),
        "equipment_completeness": formation.get("equipment_completeness"),
        "equipment_staging_by_item": copy.deepcopy(dict(formation.get("equipment_staging_by_item", {}))),
    }


class FormationArmoryIssueMixin:
    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "formation_equipment_repair":
            started = self._world_time()
            categories_raw = payload.get("categories", ["shield", "armor"])
            categories = tuple(str(x) for x in categories_raw) if isinstance(categories_raw, list) else ("shield", "armor")
            result = repair_house_formation_equipment(
                self,
                formation_ref=str(payload.get("formation_ref", "")),
                hours=int(payload.get("hours", 1)),
                actor_ref=str(command.actor_id),
                at=str(started),
                categories=categories,
            )
            world_time, metrics = self._advance_seconds(int(payload.get("hours", 1)) * 3600)
            self._write_meta(command, str(world_time))
            return self._result(world_time=str(world_time), **result, **metrics)
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
    "repair_house_formation_equipment",
]
