"""House Tang armory, bowyer and remount replenishment.

This is a replenishment system, not a stock mint.  Monthly output is limited by
exact Tang Manor workers, registered work allocation, nearby private-economy
materials or horse stock, House cash and explicit reserve targets.  The private
economy receives the House payment and loses the physical inputs in the same
transaction.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.geography import location_chain

_RULES_PATH = "game/data/mechanics/house-tang-production.json"
_POPULATION_PATH = "state/population/tang-manor.json"
_INVENTORY_PATH = "state/inv/inventories.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_ECONOMY_PATH = "state/economy/private/qin.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_DEPOT_PATH = "state/depots/house-tang.json"
_INFRASTRUCTURE_PATH = "state/infrastructure/settlements.json"
_HOUSE_FORCE_PATHS = (
    "state/forces/house-tang.json",
    "state/forces/sword-manor.json",
    "state/forces/bastion-iron-rampart.json",
    "state/forces/bastion-red-crane.json",
    "state/forces/bastion-white-lantern.json",
    "state/forces/bastion-deep-earth.json",
)


def _facts(inventory: MutableMapping[str, Any], record_id: str) -> MutableMapping[str, Any]:
    for row in inventory.get("records", []):
        if isinstance(row, MutableMapping) and row.get("record_id") == record_id:
            value = row.setdefault("facts", {})
            if isinstance(value, MutableMapping):
                return value
    raise ValueError(f"House Tang production missing inventory record {record_id}")


def _regions(economy: MutableMapping[str, Any], refs: list[str]) -> list[MutableMapping[str, Any]]:
    local = economy.get("local_regions", {})
    rows = local.get("regions", {}) if isinstance(local, Mapping) else {}
    result: list[MutableMapping[str, Any]] = []
    for ref in refs:
        row = rows.get(ref) if isinstance(rows, Mapping) else None
        if isinstance(row, MutableMapping):
            result.append(row)
    if not result:
        raise ValueError("House Tang production has no exact nearby private-economy procurement region")
    return result


def _available(regions: list[Mapping[str, Any]], key: str) -> int:
    return sum(max(0, int(row.get("commodity_stock", {}).get(key, 0))) for row in regions)


def _consume(regions: list[MutableMapping[str, Any]], key: str, amount: int) -> int:
    remaining = max(0, int(amount))
    used = 0
    for row in regions:
        if remaining <= 0:
            break
        stock = row.setdefault("commodity_stock", {})
        available = max(0, int(stock.get(key, 0)))
        take = min(available, remaining)
        if take:
            stock[key] = available - take
            remaining -= take
            used += take
    return used


def _credit_private_cash(regions: list[MutableMapping[str, Any]], amount: int) -> None:
    value = max(0, int(amount))
    if value:
        regions[0]["cash_silver"] = int(regions[0].get("cash_silver", 0)) + value


def _reconcile_private_aggregate(economy: MutableMapping[str, Any]) -> None:
    local = economy.get("local_regions", {})
    rows = local.get("regions", {}) if isinstance(local, Mapping) else {}
    if not isinstance(rows, Mapping) or not rows:
        return
    economy["cash_silver"] = sum(int(row.get("cash_silver", 0)) for row in rows.values() if isinstance(row, Mapping))
    commodity: dict[str, int] = {}
    finished: dict[str, int] = {}
    for row in rows.values():
        if not isinstance(row, Mapping):
            continue
        for key, raw in (row.get("commodity_stock", {}) or {}).items():
            commodity[str(key)] = commodity.get(str(key), 0) + max(0, int(raw))
        for key, raw in (row.get("finished_goods", {}) or {}).items():
            finished[str(key)] = finished.get(str(key), 0) + max(0, int(raw))
    economy["commodity_stock"] = commodity
    economy["finished_goods"] = finished


def _worker_count(population: Mapping[str, Any], rules: Mapping[str, Any], worker_key: str) -> int:
    workforce = rules.get("workforce", {}) if isinstance(rules.get("workforce"), Mapping) else {}
    raw = workforce.get(worker_key, worker_key)
    # The production registry may either name the population stratum or state
    # the installed workforce capacity directly. Numeric capacity still draws
    # from the same-named Tang Manor population stratum; it is not a stratum ID.
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        stratum = worker_key
        cap = max(0, int(raw))
    else:
        stratum = str(raw)
        cap = None
    strata = population.get("strata", {}) if isinstance(population.get("strata"), Mapping) else {}
    current = max(0, int(strata.get(stratum, 0)))
    return min(current, cap) if cap is not None else current



def _inside_tang_manor(planner: Any, location_ref: str) -> bool:
    if not location_ref:
        return False
    try:
        return "loc_tang_manor" in location_chain(planner.read, str(location_ref))
    except (ValueError, KeyError, FileNotFoundError):
        return str(location_ref).startswith("loc_tang_manor")


def _resident_house_military(planner: Any) -> int:
    """Count conserved House military bodies physically resident inside Tang Manor.

    Allocated formations and unallocated force reserves are mutually exclusive
    partitions of the same force bodies.  This helper counts each once and does
    not assume the full authorized establishment remains at home during campaign.
    """
    owner_index = planner.read("state/index/owner-index.json").get("owners", {})
    total = 0
    for force_path in _HOUSE_FORCE_PATHS:
        force = planner.read_optional(force_path)
        if not isinstance(force, Mapping):
            continue
        for location_ref, pool in (force.get("available_by_location", {}) or {}).items():
            if isinstance(pool, Mapping) and _inside_tang_manor(planner, str(location_ref)):
                total += sum(max(0, int(value)) for value in pool.values())
        for formation_ref in (force.get("allocated_to_formations", {}) or {}):
            route = owner_index.get(str(formation_ref)) if isinstance(owner_index, Mapping) else None
            if not isinstance(route, str):
                continue
            formation = planner.read_optional(route)
            if isinstance(formation, Mapping) and _inside_tang_manor(planner, str(formation.get("location_ref", ""))):
                total += max(0, int(formation.get("personnel", 0)))
    return total


def _resident_house_mounts(planner: Any, inventory: Mapping[str, Any]) -> int:
    owner_index = planner.read("state/index/owner-index.json").get("owners", {})
    assigned = 0
    for force_path in _HOUSE_FORCE_PATHS:
        force = planner.read_optional(force_path)
        if not isinstance(force, Mapping):
            continue
        for formation_ref in (force.get("allocated_to_formations", {}) or {}):
            route = owner_index.get(str(formation_ref)) if isinstance(owner_index, Mapping) else None
            if not isinstance(route, str):
                continue
            formation = planner.read_optional(route)
            if isinstance(formation, Mapping) and _inside_tang_manor(planner, str(formation.get("location_ref", ""))):
                assigned += sum(max(0, int(value)) for value in (formation.get("mounts", {}) or {}).values())
    reserve = 0
    for row in inventory.get("records", []) if isinstance(inventory.get("records"), list) else []:
        if isinstance(row, Mapping) and row.get("record_id") == "mounts":
            reserve = max(0, int((row.get("facts", {}) or {}).get("Tang Heavy Warhorse reserve", 0)))
            break
    return assigned + reserve


def settle_house_tang_estate_autarky(planner: Any, at: str) -> dict[str, Any] | None:
    """Settle one average month of enclosed Tang Manor food/fodder production.

    The estate does not import survival stock.  Production is derived from the
    exact master-plan land budget and current productive-asset condition, stock is
    capped by physical storage, and consumption follows the bodies/mounts actually
    resident inside Tang Manor at the close.
    """
    rules = planner.read(_RULES_PATH)
    agriculture = rules.get("estate_agriculture", {}) if isinstance(rules, Mapping) else {}
    siege = rules.get("siege_logistics", {}) if isinstance(rules, Mapping) else {}
    if not isinstance(agriculture, Mapping) or not isinstance(siege, Mapping):
        return None
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    runtime = house.setdefault("administrative_programs", {}).setdefault("estate_autarky", {})
    if runtime.get("last_close") == at:
        return None
    population = planner.read(_POPULATION_PATH)
    civilians = max(0, int(population.get("population_total", 0)))
    military = _resident_house_military(planner)
    inventory = planner.read(_INVENTORY_PATH)
    mounts = _resident_house_mounts(planner, inventory)
    infrastructure = planner.read(_INFRASTRUCTURE_PATH)
    site = (infrastructure.get("sites", {}) or {}).get("loc_tang_manor", {}) if isinstance(infrastructure, Mapping) else {}
    assets = site.get("productive_assets", {}) if isinstance(site, Mapping) else {}
    site_condition = max(0.0, min(1.0, float(site.get("condition", 1.0)))) if isinstance(site, Mapping) else 1.0
    food_condition = min(
        site_condition,
        max(0.0, min(1.0, float((assets or {}).get("staple_agriculture_condition", 1.0)))),
        max(0.0, min(1.0, float((assets or {}).get("waterworks_condition", 1.0)))),
    )
    fodder_condition = min(
        site_condition,
        max(0.0, min(1.0, float((assets or {}).get("fodder_agriculture_condition", 1.0)))),
        max(0.0, min(1.0, float((assets or {}).get("waterworks_condition", 1.0)))),
    )
    storage_condition = min(
        site_condition,
        max(0.0, min(1.0, float((assets or {}).get("storage_network_condition", 1.0)))),
    )
    food_output = max(0, int(round(float(agriculture.get("average_usable_food_output_kg_per_month", 0)) * food_condition)))
    fodder_output = max(0, int(round(float(agriculture.get("average_harvested_fodder_output_kg_per_month", 0)) * fodder_condition)))
    food_need = max(0, int(round((civilians * float(agriculture.get("civilian_staple_ration_kg_per_day", 0.68)) + military * float(agriculture.get("military_staple_ration_kg_per_day", 0.90))) * 365.0 / 12.0)))
    fodder_need = max(0, int(round(mounts * float(agriculture.get("resident_mount_fodder_kg_per_day", 4.0)) * 365.0 / 12.0)))
    depot = copy.deepcopy(planner.read(_DEPOT_PATH))
    stocks = depot.setdefault("stocks", {})
    capacity = depot.setdefault("storage_capacity", {})
    grain_cap = max(0, int(round(float(capacity.get("grain_kg", siege.get("grain_storage_capacity_kg", 0))) * storage_condition)))
    fodder_cap = max(0, int(round(float(capacity.get("fodder_kg", siege.get("fodder_storage_capacity_kg", 0))) * storage_condition)))
    before_food = max(0, int(stocks.get("grain_kg", 0))); before_fodder = max(0, int(stocks.get("fodder_kg", 0)))
    food_after_output = min(grain_cap, before_food + food_output)
    fodder_after_output = min(fodder_cap, before_fodder + fodder_output)
    food_spilled = max(0, before_food + food_output - food_after_output)
    fodder_spilled = max(0, before_fodder + fodder_output - fodder_after_output)
    food_consumed = min(food_need, food_after_output); fodder_consumed = min(fodder_need, fodder_after_output)
    stocks["grain_kg"] = food_after_output - food_consumed
    stocks["fodder_kg"] = fodder_after_output - fodder_consumed
    food_shortfall = max(0, food_need - food_consumed); fodder_shortfall = max(0, fodder_need - fodder_consumed)
    runtime.clear()
    runtime.update({
        "last_close": at,
        "civilian_residents": civilians,
        "resident_military_bodies": military,
        "resident_house_mounts": mounts,
        "food_output_kg": food_output,
        "food_consumed_kg": food_consumed,
        "food_shortfall_kg": food_shortfall,
        "fodder_output_kg": fodder_output,
        "fodder_consumed_kg": fodder_consumed,
        "fodder_shortfall_kg": fodder_shortfall,
        "grain_stock_kg": int(stocks["grain_kg"]),
        "fodder_stock_kg": int(stocks["fodder_kg"]),
        "grain_storage_capacity_kg": grain_cap,
        "fodder_storage_capacity_kg": fodder_cap,
        "unstored_food_surplus_kg": food_spilled,
        "unstored_fodder_surplus_kg": fodder_spilled,
        "productive_condition": {"food": round(food_condition, 4), "fodder": round(fodder_condition, 4), "storage": round(storage_condition, 4)},
        "rule": "Finite enclosed production and storage. Blockade does not stop undamaged internal production; shortages require real stock/production damage or demand exceeding capacity.",
    })
    support = house.setdefault("estate_support", {})
    support.update({
        "food_monthly_output_kg": food_output,
        "fodder_monthly_output_kg": fodder_output,
        "strategic_food_reserve_kg": int(stocks["grain_kg"]),
        "strategic_fodder_reserve_kg": int(stocks["fodder_kg"]),
        "supported_resident_military": military,
        "resident_house_mounts": mounts,
        "strategic_autarky": True,
    })
    planner.put(_DEPOT_PATH, depot)
    planner.put(_HOUSE_PATH, house)
    return copy.deepcopy(runtime)

def settle_house_tang_equipment_production(planner: Any, at: str) -> dict[str, Any] | None:
    rules = planner.read(_RULES_PATH)
    population = planner.read(_POPULATION_PATH)
    inventory = copy.deepcopy(planner.read(_INVENTORY_PATH))
    treasury = copy.deepcopy(planner.read(_TREASURY_PATH))
    economy = copy.deepcopy(planner.read(_ECONOMY_PATH))
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    programs = house.setdefault("administrative_programs", {})
    runtime = programs.setdefault("house_equipment_production", {})
    if runtime.get("last_close") == at:
        return None

    region_refs = [str(value) for value in rules.get("procurement_regions", []) if isinstance(value, str)]
    regions = _regions(economy, region_refs)
    targets = rules.get("reserve_targets", {}) if isinstance(rules.get("reserve_targets"), Mapping) else {}
    produced: dict[str, int] = {}
    material_units = 0
    horses = 0
    silver = 0
    # Immediate formation repairs draw on the same conserved forge-worker month
    # that feeds reserve production.  Pending repair worker-hours therefore
    # reduce this close's available forge labor instead of allowing the same
    # craftsmen to manufacture and repair simultaneously for free.
    forge_workers = _worker_count(population, rules, "forge_and_armory_workers")
    cycle_hours = max(1.0, float(rules.get("cycle_seconds", 2592000)) / 3600.0)
    pending_repair_worker_hours = max(0.0, float(runtime.get("repair_worker_hours_pending", 0.0) or 0.0))
    forge_capacity_hours = max(1.0, forge_workers * cycle_hours)
    forge_labor_fraction = max(0.0, min(1.0, 1.0 - pending_repair_worker_hours / forge_capacity_hours))

    for row in rules.get("items", []):
        if not isinstance(row, Mapping):
            continue
        record_id = str(row.get("record_id", ""))
        reserve_key = str(row.get("reserve_key", ""))
        total_key = str(row.get("total_key", ""))
        if not record_id or not reserve_key or reserve_key not in targets:
            continue
        facts = _facts(inventory, record_id)
        current = max(0, int(facts.get(reserve_key, 0)))
        shortage = max(0, int(targets[reserve_key]) - current)
        if shortage <= 0:
            continue
        workforce_key = str(row.get("workforce", ""))
        workers = _worker_count(population, rules, workforce_key)
        share = max(0, min(10000, int(row.get("work_share_basis_points", 0))))
        rate = max(0.0, float(row.get("units_per_worker_month", 0.0)))
        labor_fraction = forge_labor_fraction if workforce_key == "forge_and_armory_workers" else 1.0
        labor_units = max(0, int(math.floor(workers * labor_fraction * rate * share / 10000.0 + 1e-9)))
        batch = max(1, int(row.get("batch_size", 1)))
        material_per = max(0, int(row.get("material_units_per_batch", 0)))
        silver_per = max(0, int(row.get("silver_per_batch", 0)))
        batches = min(shortage // batch, labor_units // batch)
        if material_per:
            batches = min(batches, _available(regions, "construction_material_units") // material_per)
        if silver_per:
            batches = min(batches, max(0, int(treasury.get("silver", 0))) // silver_per)
        if batches <= 0:
            continue
        units = batches * batch
        material_need = batches * material_per
        silver_need = batches * silver_per
        if material_need and _consume(regions, "construction_material_units", material_need) != material_need:
            raise ValueError("House Tang production material conservation failed")
        treasury["silver"] = int(treasury.get("silver", 0)) - silver_need
        _credit_private_cash(regions, silver_need)
        facts[reserve_key] = current + units
        if total_key:
            facts[total_key] = max(0, int(facts.get(total_key, current))) + units
        produced[reserve_key] = produced.get(reserve_key, 0) + units
        material_units += material_need
        silver += silver_need

    for row in rules.get("remounts", []):
        if not isinstance(row, Mapping):
            continue
        reserve_key = str(row.get("reserve_key", ""))
        if reserve_key not in targets:
            continue
        facts = _facts(inventory, str(row.get("record_id", "mounts")))
        current = max(0, int(facts.get(reserve_key, 0)))
        shortage = max(0, int(targets[reserve_key]) - current)
        if shortage <= 0:
            continue
        workers = _worker_count(population, rules, str(row.get("workforce", "")))
        share = max(0, min(10000, int(row.get("work_share_basis_points", 0))))
        rate = max(0.0, float(row.get("units_per_worker_month", 0.0)))
        capacity = max(0, int(math.floor(workers * rate * share / 10000.0 + 1e-9)))
        horse_per = max(1, int(row.get("private_horse_stock_per_mount", 1)))
        silver_per = max(0, int(row.get("silver_per_mount", 0)))
        units = min(shortage, capacity, _available(regions, "horse_stock") // horse_per)
        if silver_per:
            units = min(units, max(0, int(treasury.get("silver", 0))) // silver_per)
        if units <= 0:
            continue
        horse_need = units * horse_per
        silver_need = units * silver_per
        if _consume(regions, "horse_stock", horse_need) != horse_need:
            raise ValueError("House Tang remount conservation failed")
        treasury["silver"] = int(treasury.get("silver", 0)) - silver_need
        _credit_private_cash(regions, silver_need)
        facts[reserve_key] = current + units
        total_key = str(row.get("total_key", ""))
        if total_key:
            facts[total_key] = max(0, int(facts.get(total_key, current))) + units
        produced[reserve_key] = produced.get(reserve_key, 0) + units
        horses += horse_need
        silver += silver_need

    _reconcile_private_aggregate(economy)
    runtime["schema"] = "house-equipment-production-runtime"
    runtime["last_close"] = at
    runtime["forge_and_armory_workers"] = _worker_count(population, rules, "forge_and_armory_workers")
    runtime["stable_remount_and_carriage_workers"] = _worker_count(population, rules, "stable_remount_and_carriage_workers")
    runtime["reserve_targets"] = copy.deepcopy(dict(targets))
    runtime["last_output"] = copy.deepcopy(produced)
    runtime["last_material_units_consumed"] = material_units
    runtime["last_horses_acquired"] = horses
    runtime["last_silver_paid"] = silver
    runtime["last_repair_worker_hours_deducted"] = round(pending_repair_worker_hours, 3)
    runtime["repair_worker_hours_pending"] = 0.0
    history = runtime.setdefault("history", [])
    history.append({
        "at": at,
        "produced": copy.deepcopy(produced),
        "construction_material_units_consumed": material_units,
        "private_horses_acquired": horses,
        "silver_paid": silver,
        "repair_worker_hours_deducted": round(pending_repair_worker_hours, 3),
        "forge_labor_fraction_available_after_repairs": round(forge_labor_fraction, 6),
        "rule": "resource_bounded_monthly_replenishment_to_registered_reserve_targets",
    })
    runtime["history"] = history[-24:]
    programs["house_equipment_production"] = runtime
    planner.put(_INVENTORY_PATH, inventory)
    planner.put(_TREASURY_PATH, treasury)
    planner.put(_ECONOMY_PATH, economy)
    planner.put(_HOUSE_PATH, house)
    return {
        "at": at,
        "produced": produced,
        "material_units_consumed": material_units,
        "horses_acquired": horses,
        "silver_paid": silver,
    }


def settle_house_tang_fortress_support_production(planner: Any, at: str) -> dict[str, Any] | None:
    """Replenish finite fortress-support stock from Tang Manor's exact internal industry.

    The Manor master plan already establishes forestry, mines/quarries, medicinal
    crops, carriage works and construction labor.  This close converts only that
    saved resident labor plus House silver into bounded physical stock.  It never
    draws Qin state inventory and it never fills above the depot's exact capacity.
    """
    rules = planner.read(_RULES_PATH)
    policy = rules.get("fortress_support_industry", {}) if isinstance(rules, Mapping) else {}
    outputs = policy.get("outputs", {}) if isinstance(policy, Mapping) else {}
    if not isinstance(outputs, Mapping) or not outputs:
        return None
    population = planner.read(_POPULATION_PATH)
    treasury = copy.deepcopy(planner.read(_TREASURY_PATH))
    depot = copy.deepcopy(planner.read(_DEPOT_PATH))
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    runtime = house.setdefault("administrative_programs", {}).setdefault("fortress_support_production", {})
    if runtime.get("last_close") == at:
        return None
    stocks = depot.setdefault("stocks", {})
    capacity = depot.setdefault("storage_capacity", {})
    produced: dict[str, int] = {}
    silver_spent = 0
    for key, cfg in outputs.items():
        if not isinstance(cfg, Mapping):
            continue
        cap = max(0, int(capacity.get(str(key), 0)))
        current = max(0, int(stocks.get(str(key), 0)))
        shortage = max(0, cap - current)
        if shortage <= 0:
            continue
        workers = _worker_count(population, rules, str(cfg.get("workforce", "")))
        share = max(0, min(10000, int(cfg.get("work_share_basis_points", 0))))
        rate = max(0.0, float(cfg.get("units_per_worker_month", 0.0)))
        possible = max(0, int(math.floor(workers * rate * share / 10000.0 + 1e-9)))
        unit_cost = max(0, int(cfg.get("silver_per_unit", 0)))
        if unit_cost:
            possible = min(possible, max(0, int(treasury.get("silver", 0))) // unit_cost)
        qty = min(shortage, possible)
        if qty <= 0:
            continue
        stocks[str(key)] = current + qty
        cost = qty * unit_cost
        treasury["silver"] = max(0, int(treasury.get("silver", 0)) - cost)
        silver_spent += cost
        produced[str(key)] = qty
    runtime.update({
        "last_close": at,
        "last_output": copy.deepcopy(produced),
        "last_silver_spent": silver_spent,
        "resource_basis_ref": str(policy.get("resource_basis_ref", "")),
        "rule": str(policy.get("rule", "")),
    })
    hist = runtime.setdefault("history", [])
    hist.append({"at": at, "produced": copy.deepcopy(produced), "silver_spent": silver_spent})
    runtime["history"] = hist[-24:]
    planner.put(_DEPOT_PATH, depot)
    planner.put(_TREASURY_PATH, treasury)
    planner.put(_HOUSE_PATH, house)
    return {"at": at, "produced": produced, "silver_spent": silver_spent}


class HouseTangEquipmentProductionMixin:
    """Run House armory production after each ordinary Sword Manor monthly close."""

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        if host.get("kind") == "sword_manor":
            settle_house_tang_estate_autarky(self, due_text)
            settle_house_tang_equipment_production(self, due_text)
            settle_house_tang_fortress_support_production(self, due_text)


__all__ = ["HouseTangEquipmentProductionMixin", "settle_house_tang_estate_autarky", "settle_house_tang_equipment_production", "settle_house_tang_fortress_support_production"]
