"""Player-safe House Tang military readiness projection.

This module composes existing authoritative owners without creating a second
writable readiness state.  It is intentionally read-only: physical strategic
stores remain owned by the House depot, cash and stable flows by the treasury,
reserve equipment by the inventory registry, and realized replenishment by the
House production runtime.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.api.operations import OperationError

_HOUSE_PATH = "state/houses/house_tang.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_DEPOT_PATH = "state/depots/house-tang.json"
_INVENTORY_PATH = "state/inv/inventories.json"
_PRODUCTION_RULES_PATH = "game/data/mechanics/house-tang-production.json"
_META_PATH = "state/meta.json"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _inventory_facts(inventory: Mapping[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    records = inventory.get("records", [])
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, Mapping):
            continue
        row = record.get("facts")
        if not isinstance(row, Mapping):
            continue
        for key, value in row.items():
            facts[str(key)] = value
    return facts


def house_readiness_snapshot(operations: Any) -> dict[str, Any]:
    """Return an exact, bounded readiness ledger for an authorized House principal.

    The projection deliberately does not declare an operation expedition-ready.
    Expeditionary sufficiency depends on the force, route, duration, transport,
    and retained home-defense burden selected for that operation.
    """
    player_id = operations._player_actor()
    store = operations.store
    meta = store.read_json(_META_PATH)
    house = store.read_json(_HOUSE_PATH)

    lineage = house.get("lineage_cohort", {}) if isinstance(house, Mapping) else {}
    members = lineage.get("exact_member_refs", []) if isinstance(lineage, Mapping) else []
    if player_id not in members:
        raise OperationError(403, "house_readiness_not_authorized")

    treasury = store.read_json(_TREASURY_PATH)
    depot = store.read_json(_DEPOT_PATH)
    inventory = store.read_json(_INVENTORY_PATH)
    production_rules = store.read_json(_PRODUCTION_RULES_PATH)

    targets = production_rules.get("reserve_targets", {}) if isinstance(production_rules, Mapping) else {}
    targets = targets if isinstance(targets, Mapping) else {}
    facts = _inventory_facts(inventory)
    current_vs_targets: dict[str, dict[str, int]] = {}
    for raw_key, raw_target in sorted(targets.items(), key=lambda row: str(row[0])):
        key = str(raw_key)
        try:
            target = max(0, int(raw_target))
            current = max(0, int(facts.get(key, 0)))
        except (TypeError, ValueError):
            continue
        current_vs_targets[key] = {
            "current": current,
            "target": target,
            "shortfall": max(0, target - current),
        }

    programs = house.get("administrative_programs", {}) if isinstance(house, Mapping) else {}
    production = programs.get("house_equipment_production", {}) if isinstance(programs, Mapping) else {}
    production = production if isinstance(production, Mapping) else {}
    estate_support = house.get("estate_support", {}) if isinstance(house, Mapping) else {}
    estate_support = estate_support if isinstance(estate_support, Mapping) else {}

    treasury_view = {
        "silver": treasury.get("silver") if isinstance(treasury, Mapping) else None,
        "stable_monthly_flows": _mapping(treasury.get("stable_monthly_flows")) if isinstance(treasury, Mapping) else {},
        "monthly_flow_components": _mapping(treasury.get("monthly_flow_components")) if isinstance(treasury, Mapping) else {},
        "siege_endurance": _mapping(treasury.get("siege_endurance")) if isinstance(treasury, Mapping) else {},
    }
    strategic_stores = {
        "depot_ref": depot.get("depot_ref", depot.get("owner_id")) if isinstance(depot, Mapping) else None,
        "stocks": _mapping(depot.get("stocks")) if isinstance(depot, Mapping) else {},
        "storage_capacity": _mapping(depot.get("storage_capacity")) if isinstance(depot, Mapping) else {},
        "garrison_support_targets": _mapping(depot.get("garrison_support_targets")) if isinstance(depot, Mapping) else {},
        "current_shortfalls": _mapping(depot.get("current_shortfalls")) if isinstance(depot, Mapping) else {},
        "mounts": _mapping(depot.get("mounts")) if isinstance(depot, Mapping) else {},
    }
    production_view = {
        "current_vs_targets": current_vs_targets,
        "last_resource_bounded_monthly_close": production.get("last_close"),
        "last_resource_bounded_monthly_output": _mapping(production.get("last_output")),
        "forge_and_armory_workers": production.get("forge_and_armory_workers"),
        "stable_remount_and_carriage_workers": production.get("stable_remount_and_carriage_workers"),
        "last_material_units_consumed": production.get("last_material_units_consumed"),
        "last_horses_acquired": production.get("last_horses_acquired"),
        "last_silver_paid": production.get("last_silver_paid"),
    }
    estate_view = {
        key: estate_support.get(key)
        for key in (
            "food_monthly_output_kg",
            "fodder_monthly_output_kg",
            "supported_fighting_personnel",
            "supported_resident_military",
            "resident_house_mounts",
            "house_mounts",
            "strategic_autarky",
        )
        if estate_support.get(key) is not None
    }

    return {
        "house_ref": "house_tang",
        "visibility": "house_principal_readiness",
        "as_of": {
            "campaign_id": meta.get("campaign_id") if isinstance(meta, Mapping) else None,
            "revision": meta.get("revision") if isinstance(meta, Mapping) else None,
            "world_time": meta.get("time") if isinstance(meta, Mapping) else None,
        },
        "treasury": treasury_view,
        "strategic_stores": strategic_stores,
        "armory_and_remount_reserves": production_view,
        "estate_support": estate_view,
        "readiness_interpretation": {
            "garrison": "Use current home force condition and depot support. Home readiness does not prove campaign endurance.",
            "emergency_mobilization": "Requires troops, equipment, immediate stores, mounts and transport to be mustered from exact current owners.",
            "expeditionary": "Requires operation-specific force, route, duration, transport and retained home-defense burden; no blanket expedition-ready claim is inferred by this read.",
        },
        "accounting_rules": [
            "Depot stocks are the current physical House strategic stores exposed by this projection.",
            "Inventory missile strategic-reserve entries mirror depot ammunition and must never be added to depot stocks as separate physical supply.",
            "Last resource-bounded monthly output is an observed settled close, not a guaranteed future rate; future output remains constrained by reserve shortage, labor, material or horse stock and House silver.",
            "This read does not spend, reserve, move, issue or otherwise commit House resources.",
        ],
        "source_owners": [
            _TREASURY_PATH,
            _DEPOT_PATH,
            _INVENTORY_PATH,
            _HOUSE_PATH,
            _PRODUCTION_RULES_PATH,
        ],
    }


__all__ = ["house_readiness_snapshot"]
