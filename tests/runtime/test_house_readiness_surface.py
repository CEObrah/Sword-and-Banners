from __future__ import annotations

import copy

from sword_runtime.api.house_readiness import house_readiness_snapshot
from sword_runtime.api.stable_operations import StableCampaignOperations
from sword_runtime.service_runtime import ProductionSwordRuntime


def _outfitting_facts(inventory: dict) -> dict:
    for record in inventory.get("records", []):
        if record.get("record_id") == "house_tang_outfitting_sets":
            return dict(record.get("facts", {}))
    return {}


def test_house_readiness_is_exact_read_only_projection(campaign):
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-house-readiness")
    operations = StableCampaignOperations(runtime)
    source_paths = (
        "state/meta.json",
        "state/houses/house_tang.json",
        "state/treasury/treasury-house-tang.json",
        "state/depots/house-tang.json",
        "state/inv/inventories.json",
        "state/mounts/house-tang.json",
        "game/data/mechanics/outfitting.json",
    )
    before = {path: copy.deepcopy(runtime.store.read_json(path)) for path in source_paths}
    result = house_readiness_snapshot(operations)
    assert result["visibility"] == "house_principal_readiness"
    assert result["as_of"]["revision"] == before["state/meta.json"]["revision"]
    assert result["as_of"]["world_time"] == before["state/meta.json"]["time"]
    assert result["treasury"]["silver"] == before["state/treasury/treasury-house-tang.json"]["silver"]
    assert result["strategic_stores"]["stocks"] == before["state/depots/house-tang.json"]["stocks"]
    facts = _outfitting_facts(before["state/inv/inventories.json"])
    assert result["armory_and_remount_reserves"]["aggregate_outfitting_sets"] == facts
    assert facts["standard_role_sets_reserve"] >= 0
    assert facts["crossbow_role_sets_reserve"] >= 0
    assert facts["mounted_harness_sets_reserve"] >= 0
    assert result["armory_and_remount_reserves"]["ammunition_owner_ref"] == "depot_house_tang"
    assert result["armory_and_remount_reserves"]["mount_owner_ref"] == "mount_pool_force_house_tang"
    assert before["state/mounts/house-tang.json"]["owner_id"] == "mount_pool_force_house_tang"
    assert "monthly item-factory" in " ".join(result["accounting_rules"])
    after = {path: runtime.store.read_json(path) for path in source_paths}
    assert after == before


def test_house_readiness_does_not_double_count_ammunition_or_mounts(campaign):
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-house-readiness-stocks")
    operations = StableCampaignOperations(runtime)
    result = house_readiness_snapshot(operations)
    depot = runtime.store.read_json("state/depots/house-tang.json")
    facts = result["armory_and_remount_reserves"]["aggregate_outfitting_sets"]
    assert result["strategic_stores"]["stocks"] == depot.get("stocks", {})
    assert facts["ammunition_owner_ref"] == "depot_house_tang"
    assert facts["mount_stock_owner_ref"] == "mount_pool_force_house_tang"
    assert "war_arrows" not in facts and "horse" not in facts
