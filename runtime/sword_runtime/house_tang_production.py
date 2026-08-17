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

_RULES_PATH = "game/data/mechanics/house-tang-production.json"
_POPULATION_PATH = "state/population/tang-manor.json"
_INVENTORY_PATH = "state/inv/inventories.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_ECONOMY_PATH = "state/economy/private/qin.json"
_HOUSE_PATH = "state/houses/house_tang.json"


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
        workers = _worker_count(population, rules, str(row.get("workforce", "")))
        share = max(0, min(10000, int(row.get("work_share_basis_points", 0))))
        rate = max(0.0, float(row.get("units_per_worker_month", 0.0)))
        labor_units = max(0, int(math.floor(workers * rate * share / 10000.0 + 1e-9)))
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
    runtime["schema"] = "house-equipment-production-runtime.v1"
    runtime["last_close"] = at
    runtime["forge_and_armory_workers"] = _worker_count(population, rules, "forge_and_armory_workers")
    runtime["stable_remount_and_carriage_workers"] = _worker_count(population, rules, "stable_remount_and_carriage_workers")
    runtime["reserve_targets"] = copy.deepcopy(dict(targets))
    runtime["last_output"] = copy.deepcopy(produced)
    runtime["last_material_units_consumed"] = material_units
    runtime["last_horses_acquired"] = horses
    runtime["last_silver_paid"] = silver
    history = runtime.setdefault("history", [])
    history.append({
        "at": at,
        "produced": copy.deepcopy(produced),
        "construction_material_units_consumed": material_units,
        "private_horses_acquired": horses,
        "silver_paid": silver,
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


class HouseTangEquipmentProductionMixin:
    """Run House armory production after each ordinary Sword Manor monthly close."""

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        if host.get("kind") == "sword_manor":
            settle_house_tang_equipment_production(self, due_text)


__all__ = ["HouseTangEquipmentProductionMixin", "settle_house_tang_equipment_production"]
