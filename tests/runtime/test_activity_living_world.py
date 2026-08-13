from copy import deepcopy

from sword_runtime.activity_living_world import ActivityCampaignEventPlanner
from sword_runtime.sim.calendar import CampaignTime


def test_activity_routing_uses_one_host_and_excludes_player(campaign):
    planner = ActivityCampaignEventPlanner(campaign)
    planner._reset()
    before = deepcopy(planner.read("state/runtime.json"))
    host_count = len(before["hosts"])

    planner._ensure_activity_routes()
    after = planner.read("state/runtime.json")
    activity_host = after["hosts"]["host_named_person_activity"]

    assert len(after["hosts"]) == host_count + 1
    assert activity_host["kind"] == "person_activity"
    assert "char_tang_wei" not in activity_host["routed_person_refs"]
    assert "char_tang_zhu" in activity_host["routed_person_refs"]
    assert "char_duan_jin" in activity_host["routed_person_refs"]
    assert after["hosts"]["host_person_duan_jin"]["activity_route"]["status"] == "routed"
    assert all(
        after["metrics"][key] == 0
        for key in ("global_person_scans", "global_faction_scans", "global_force_scans", "global_house_scans")
    )


def test_activity_routing_is_incremental_and_idempotent(campaign):
    planner = ActivityCampaignEventPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    runtime = deepcopy(planner.read("state/runtime.json"))
    initial_refs = set(runtime["hosts"]["host_named_person_activity"]["routed_person_refs"])

    planner._ensure_activity_routes()
    after = planner.read("state/runtime.json")
    refs = after["hosts"]["host_named_person_activity"]["routed_person_refs"]
    assert set(refs) == initial_refs
    assert len(refs) == len(set(refs))
    assert sum(1 for e in after["events"] if e["event_id"] == "event_host_named_person_activity_review") == 1


def test_routed_activity_uses_fixed_verified_cycles_not_planned_opportunity_text(campaign):
    planner = ActivityCampaignEventPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    runtime = planner.read("state/runtime.json")
    activity_host = deepcopy(runtime["hosts"]["host_named_person_activity"])
    due = CampaignTime.parse(activity_host["next_due"])

    planner._settle_activity_host(activity_host, str(due))
    duan = planner.read("state/char/duan-jin.json")
    history = duan.get("autonomous_development_history", [])

    assert history
    assert history[-1]["hours"] == 48
    assert history[-1]["verification_basis"] == "structured_causal_activity_cycle_v1"
    assert history[-1]["planned_opportunity_hours_used"] is False
    assert duan["autonomous_activity_state"]["completed_cycles"] >= 1


def test_annual_person_review_does_not_double_award_routed_training(campaign):
    planner = ActivityCampaignEventPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    runtime = planner.read("state/runtime.json")
    person_host = deepcopy(runtime["hosts"]["host_person_duan_jin"])
    before = deepcopy(planner.read("state/char/duan-jin.json")).get("autonomous_development_history", [])

    planner._autonomy_person(person_host, 1, str(person_host["next_due"]))
    after = planner.read("state/char/duan-jin.json").get("autonomous_development_history", [])

    assert after == before
