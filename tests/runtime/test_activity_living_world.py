from copy import deepcopy

from sword_runtime.activity_living_world import ActivityCampaignEventPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_rates import verified_activity_hours_per_cycle


def test_activity_routing_uses_one_host_and_excludes_player(campaign):
    planner = ActivityCampaignEventPlanner(campaign)
    planner._reset()
    before = deepcopy(planner.read("state/runtime.json"))
    host_count = len(before["hosts"])
    already_routed = "host_named_person_activity" in before["hosts"]

    planner._ensure_activity_routes()
    after = planner.read("state/runtime.json")
    activity_host = after["hosts"]["host_named_person_activity"]

    assert len(after["hosts"]) == host_count + (0 if already_routed else 1)
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


def test_routed_activity_uses_canonical_hours_and_advances_named_person_attributes(campaign):
    planner = ActivityCampaignEventPlanner(campaign)
    planner._reset()
    planner._ensure_activity_routes()
    runtime = planner.read("state/runtime.json")
    activity_host = deepcopy(runtime["hosts"]["host_named_person_activity"])
    due = CampaignTime.parse(activity_host["next_due"])
    duan_before = deepcopy(planner.read("state/char/duan-jin.json"))
    contract = duan_before["activity_contract"]
    profiles = planner.read("game/data/mil/recruitment-cohort-profiles.json")
    expected_hours = int(
        verified_activity_hours_per_cycle(
            duan_before,
            contract,
            profiles,
            int(duan_before["autonomous_activity_state"]["cadence_seconds"]),
            fallback_hours=48.0,
        )
    )
    before_banks = deepcopy(duan_before.get("development_state", {}).get("attribute_edu_banks", {}))

    planner._settle_activity_host(activity_host, str(due))
    duan = planner.read("state/char/duan-jin.json")
    history = duan.get("autonomous_development_history", [])

    assert history
    assert history[-1]["hours"] == expected_hours
    assert history[-1]["verification_basis"] == "registered_deterministic_program_v1"
    assert history[-1]["planned_opportunity_hours_used"] is False
    assert any(row.get("attribute_development") for row in history[-1]["development"].get("development", []))
    after_banks = duan["development_state"]["attribute_edu_banks"]
    assert any(float(after_banks.get(key, 0.0)) > float(before_banks.get(key, 0.0)) for key in after_banks)
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




def test_base_annual_life_review_does_not_duplicate_routed_activity_training(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    person_host = deepcopy(runtime["hosts"]["host_person_duan_jin"])
    before = deepcopy(planner.read("state/char/duan-jin.json")).get("autonomous_development_history", [])

    planner._autonomy_person(person_host, 1, str(person_host["next_due"]))
    after = planner.read("state/char/duan-jin.json").get("autonomous_development_history", [])

    assert after == before

def test_short_chronology_steps_do_not_force_full_activity_route_rescan(campaign):
    planner = ActivityCampaignEventPlanner(campaign)
    planner._reset()
    runtime = planner.read("state/runtime.json")
    now = CampaignTime.parse(runtime["world_time"])

    assert planner._activity_route_scan_required(str(now.add_seconds(4 * 3600))) is False

    activity_due = min(
        CampaignTime.parse(event["due_at"])
        for event in runtime["events"]
        if event.get("kind") == "person_activity_review"
    )
    assert planner._activity_route_scan_required(str(activity_due)) is True


def test_activity_route_rescan_occurs_after_one_campaign_day_even_without_due_cycle(campaign):
    planner = ActivityCampaignEventPlanner(campaign)
    planner._reset()
    runtime = deepcopy(planner.read("state/runtime.json"))
    now = CampaignTime.parse(runtime["world_time"])
    runtime.setdefault("person_activity_routing", {})["last_route_scan_at"] = str(now.add_seconds(-86400))
    planner.put("state/runtime.json", runtime)

    assert planner._activity_route_scan_required(str(now.add_seconds(3600))) is True
