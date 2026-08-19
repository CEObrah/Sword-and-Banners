from __future__ import annotations

import copy

from sword_runtime.api.house_readiness import house_readiness_snapshot
from sword_runtime.api.stable_operations import StableCampaignOperations
from sword_runtime.service_runtime import ProductionSwordRuntime


def _inventory_facts(inventory: dict) -> dict:
    facts = {}
    for record in inventory.get("records", []):
        if isinstance(record, dict) and isinstance(record.get("facts"), dict):
            facts.update(record["facts"])
    return facts


def test_house_readiness_is_exact_read_only_projection(campaign):
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-house-readiness")
    operations = StableCampaignOperations(runtime)

    source_paths = (
        "state/meta.json",
        "state/houses/house_tang.json",
        "state/treasury/treasury-house-tang.json",
        "state/depots/house-tang.json",
        "state/inv/inventories.json",
        "game/data/mechanics/house-tang-production.json",
    )
    before = {path: copy.deepcopy(runtime.store.read_json(path)) for path in source_paths}

    result = house_readiness_snapshot(operations)

    assert result["visibility"] == "house_principal_readiness"
    assert result["as_of"]["revision"] == before["state/meta.json"]["revision"]
    assert result["as_of"]["world_time"] == before["state/meta.json"]["time"]
    assert result["treasury"]["silver"] == before["state/treasury/treasury-house-tang.json"].get("silver")
    assert result["strategic_stores"]["stocks"] == before["state/depots/house-tang.json"].get("stocks", {})

    house = before["state/houses/house_tang.json"]
    production = house.get("administrative_programs", {}).get("house_equipment_production", {})
    assert result["armory_and_remount_reserves"]["last_resource_bounded_monthly_output"] == production.get("last_output", {})

    rules = before["game/data/mechanics/house-tang-production.json"]
    inventory_facts = _inventory_facts(before["state/inv/inventories.json"])
    for key, target in rules.get("reserve_targets", {}).items():
        projected = result["armory_and_remount_reserves"]["current_vs_targets"][key]
        current = max(0, int(inventory_facts.get(key, 0)))
        assert projected == {
            "current": current,
            "target": max(0, int(target)),
            "shortfall": max(0, int(target) - current),
        }

    after = {path: runtime.store.read_json(path) for path in source_paths}
    assert after == before


def test_house_readiness_does_not_double_count_mirrored_missile_reserve(campaign):
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-house-readiness-missiles")
    operations = StableCampaignOperations(runtime)
    result = house_readiness_snapshot(operations)

    depot_stocks = runtime.store.read_json("state/depots/house-tang.json").get("stocks", {})
    assert result["strategic_stores"]["stocks"] == depot_stocks
    assert any("must never be added" in rule for rule in result["accounting_rules"])
