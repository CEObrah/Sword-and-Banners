"""Player-safe House Tang readiness projection from exact current owners."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from sword_runtime.api.operations import OperationError

_HOUSE_PATH="state/houses/house_tang.json"
_TREASURY_PATH="state/treasury/treasury-house-tang.json"
_DEPOT_PATH="state/depots/house-tang.json"
_INVENTORY_PATH="state/inv/inventories.json"
_OUTFITTING_RULES_PATH="game/data/mechanics/outfitting.json"
_META_PATH="state/meta.json"

def _mapping(value: object)->dict[str,Any]: return dict(value) if isinstance(value,Mapping) else {}

def _outfitting_facts(inventory: Mapping[str,Any])->dict[str,Any]:
    for row in inventory.get("records",[]) if isinstance(inventory.get("records"),list) else []:
        if isinstance(row,Mapping) and row.get("record_id")=="house_tang_outfitting_sets" and isinstance(row.get("facts"),Mapping): return dict(row["facts"])
    return {}

def house_readiness_snapshot(operations: Any)->dict[str,Any]:
    player_id=operations._player_actor(); store=operations.store
    meta=store.read_json(_META_PATH); house=store.read_json(_HOUSE_PATH)
    lineage=house.get("lineage_cohort",{}) if isinstance(house,Mapping) else {}
    if player_id not in (lineage.get("exact_member_refs",[]) if isinstance(lineage,Mapping) else []): raise OperationError(403,"house_readiness_not_authorized")
    treasury=store.read_json(_TREASURY_PATH); depot=store.read_json(_DEPOT_PATH); inventory=store.read_json(_INVENTORY_PATH); outfitting=store.read_json(_OUTFITTING_RULES_PATH)
    estate_support=house.get("estate_support",{}) if isinstance(house,Mapping) else {}
    return {
      "house_ref":"house_tang","visibility":"house_principal_readiness",
      "as_of":{"campaign_id":meta.get("campaign_id"),"revision":meta.get("revision"),"world_time":meta.get("time")},
      "treasury":{"silver":treasury.get("silver"),"stable_monthly_flows":_mapping(treasury.get("stable_monthly_flows")),"monthly_flow_components":_mapping(treasury.get("monthly_flow_components")),"siege_endurance":_mapping(treasury.get("siege_endurance"))},
      "strategic_stores":{"depot_ref":depot.get("depot_ref",depot.get("owner_id")),"stocks":_mapping(depot.get("stocks")),"storage_capacity":_mapping(depot.get("storage_capacity")),"garrison_support_targets":_mapping(depot.get("garrison_support_targets")),"current_shortfalls":_mapping(depot.get("current_shortfalls")),"mounts":_mapping(depot.get("mounts"))},
      "armory_and_remount_reserves":{"aggregate_outfitting_sets":_outfitting_facts(inventory),"outfitting_rule":outfitting.get("principle"),"ammunition_owner_ref":"depot_house_tang","mount_owner_ref":"depot_house_tang"},
      "estate_support":{k:estate_support.get(k) for k in ("food_monthly_output_kg","fodder_monthly_output_kg","supported_fighting_personnel","supported_resident_military","resident_house_mounts","house_mounts","strategic_autarky") if estate_support.get(k) is not None},
      "readiness_interpretation":{"garrison":"Use current home force condition and depot support. Home readiness does not prove campaign endurance.","emergency_mobilization":"Requires troops, complete role-outfitting sets, immediate stores, mounts and transport from exact current owners.","expeditionary":"Requires operation-specific force, route, duration, transport and retained home-defense burden; no blanket expedition-ready claim is inferred."},
      "accounting_rules":["Formations own issued equipment; the inventory holds only aggregate unissued complete-set capacity.","Ammunition and living horses are exact physical depot/mount stocks and are never duplicated in the armory projection.","New outfitting and repairs require real labor, material, silver and elapsed work; there is no monthly item-factory tick.","This read never commits House resources."],
      "source_owners":[_TREASURY_PATH,_DEPOT_PATH,_INVENTORY_PATH,_HOUSE_PATH,_OUTFITTING_RULES_PATH]
    }

__all__=["house_readiness_snapshot"]
