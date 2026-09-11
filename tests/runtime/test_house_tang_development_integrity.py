from __future__ import annotations

import copy

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def test_training_host_normalizes_to_one_unified_house_tang_owner(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    now = runtime["world_time"]
    runtime["hosts"]["host_sword_manor"] = {
        "kind": "sword_manor", "owner_ref": "force_sword_manor", "recurrence_seconds": 2592000,
        "next_due": runtime["hosts"]["host_house_tang_training"]["next_due"], "resolved_through": now,
        "safe_through": now, "quiet_run_count": 0,
    }
    runtime["events"].append({"event_id":"event_old_sword_review","kind":"institution_review","priority":100,"target_host":"host_sword_manor","due_at":runtime["hosts"]["host_house_tang_training"]["next_due"]})
    planner._normalize_house_tang_training_host(runtime)
    assert "host_sword_manor" not in runtime["hosts"]
    host = runtime["hosts"]["host_house_tang_training"]
    assert host["kind"] == "house_tang_training"
    assert host["owner_ref"] == "force_house_tang"
    events = [row for row in runtime["events"] if isinstance(row, dict) and row.get("target_host") == "host_house_tang_training"]
    assert len(events) == 1


def test_monthly_house_training_preserves_two_species_headcount_and_population(campaign) -> None:
    planner = _planner(campaign)
    before = copy.deepcopy(planner.read("state/forces/house-tang.json"))
    qin_before = copy.deepcopy(planner.read("state/population/qin.json"))
    manor_before = copy.deepcopy(planner.read("state/population/tang-manor.json"))
    host = next(row for row in planner.read("state/runtime.json")["hosts"].values() if isinstance(row, dict) and row.get("kind") == "house_tang_training")
    planner._autonomy_house_tang_training(host, 1, str(host["next_due"]))
    after = planner.read("state/forces/house-tang.json")
    qin_after = planner.read("state/population/qin.json")
    manor_after = planner.read("state/population/tang-manor.json")
    assert after["headcount"] == before["headcount"] == 176060
    assert after["authorized_by_role"] == {"house_infantry": 164060, "house_cavalry": 12000}
    assert int(after.get("cohort_training_closes", 0)) == int(before.get("cohort_training_closes", 0)) + 1
    validate_cohort_ledger(after)
    assert qin_after["population_total"] == qin_before["population_total"]
    assert sum(qin_after["strata"].values()) == qin_after["population_total"]
    assert manor_after["population_total"] == manor_before["population_total"]
