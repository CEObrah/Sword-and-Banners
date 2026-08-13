from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from sword_runtime.api.interaction_surface import triggered_interaction_handles
from sword_runtime.autonomy_routing import rotating_candidate_refs
from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.world_arcs import settle_world_arc_review, sync_world_arc_routes


def _active_arc_refs(planner):
    arcs = planner.read("state/arc/kingdom-arcs.json")
    return sorted(
        record["record_id"]
        for record in arcs.get("records", [])
        if isinstance(record, dict)
        and isinstance(record.get("record_id"), str)
        and record["record_id"].startswith("arc_")
        and isinstance(record.get("facts"), dict)
        and str(record["facts"].get("status", "")).lower().startswith("active")
    )


def _validate_event_registry(campaign: Path, owner: dict) -> None:
    schema = json.loads((campaign / "game/schemas/event-registry.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(owner)


def test_active_arcs_register_on_causal_frontier_without_player_action(campaign):
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    active = _active_arc_refs(planner)
    assert active

    sync_world_arc_routes(planner, runtime)
    routed = sorted(
        host["arc_ref"]
        for host in runtime["hosts"].values()
        if isinstance(host, dict) and host.get("kind") == "world_arc"
    )
    assert routed == active
    assert all(runtime["hosts"][host_id].get("next_due") is not None for host_id in runtime["hosts"] if runtime["hosts"][host_id].get("kind") == "world_arc")


def test_arc_review_creates_runtime_owned_initiative_from_saved_goals(campaign):
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner._reset()
    now = str(planner.read("state/runtime.json")["world_time"])
    arc_ref = "arc_qin_succession_crisis_245"
    host = {"kind": "world_arc", "owner_ref": "kingdom_arcs", "arc_ref": arc_ref}

    settle_world_arc_review(planner, host, now)

    arcs = planner.read("state/arc/kingdom-arcs.json")
    record = next(item for item in arcs["records"] if item.get("record_id") == arc_ref)
    runtime = record["runtime"]
    assert runtime["review_count"] == 1
    assert runtime["initiative_count"] in {0, 1}
    assert runtime["pressure_stage"] in {"contained", "developing", "material", "acute"}
    assert isinstance(runtime["driver_refs"], list)
    owner = planner.read("state/event/events-messages-and-movement.json")
    _validate_event_registry(Path(campaign), owner)
    if runtime["initiative_count"]:
        event_ref = runtime["last_initiative_ref"]
        event = owner["causal_events"][event_ref]
        assert event["kind"] == "world_arc_activity"
        assert event["actor_ref"] in runtime["driver_refs"]
        assert event["basis_goal"]
        assert event["result"] in {"gains_ground", "checked", "inconclusive"}
        assert event["visibility_class"] == "hidden"

    # Arc-level initiative resolution may not directly mutate material domain owners.
    assert not any(path.startswith("state/formations/") for path in planner._writes)
    assert not any(path.startswith("state/depots/") for path in planner._writes)
    assert not any(path.startswith("state/territory/") for path in planner._writes)


def test_event_registry_schema_accepts_world_arc_report_shape(campaign):
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner._reset()
    owner = copy.deepcopy(planner.read("state/event/events-messages-and-movement.json"))
    now = str(planner.read("state/runtime.json")["world_time"])
    owner.setdefault("causal_events", {})["event_schema_world_arc_report"] = {
        "event_ref": "event_schema_world_arc_report",
        "kind": "world_arc_report",
        "status": "triggered",
        "due_at": now,
        "triggered_at": now,
        "arc_ref": "arc_schema_test",
        "source_event_ref": "event_schema_world_arc_activity",
        "summary": "A lawfully propagated test report reaches Tang Wei.",
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": "loc_kanyou",
            "route": "direct staff report",
        },
        "provenance": {
            "kind": "world_arc_information_propagation",
            "exposure_roll": 12,
            "exposure_chance": 70,
        },
    }
    _validate_event_registry(Path(campaign), owner)


def test_world_arc_planning_is_deterministic_on_same_snapshot(campaign):
    first = CampaignEventPlayerGroupActionPlanner(campaign)
    second = CampaignEventPlayerGroupActionPlanner(campaign)
    first._reset(); second._reset()
    now = str(first.read("state/runtime.json")["world_time"])
    host = {"kind": "world_arc", "owner_ref": "kingdom_arcs", "arc_ref": "arc_qin_succession_crisis_245"}

    settle_world_arc_review(first, host, now)
    settle_world_arc_review(second, host, now)

    for path in (
        "state/arc/kingdom-arcs.json",
        "state/event/events-messages-and-movement.json",
        "state/runtime.json",
    ):
        assert first.read(path) == second.read(path)


def test_bounded_autonomy_window_rotates_across_all_exact_refs():
    refs = [f"formation_test_{index:02d}" for index in range(30)]
    first, cursor = rotating_candidate_refs(refs, 0, limit=24)
    second, _ = rotating_candidate_refs(refs, cursor, limit=24)
    assert len(first) == 24
    assert "formation_test_29" not in first
    assert "formation_test_29" in second
    assert set(first) | set(second) == set(refs)


def test_hidden_arc_activity_is_not_player_visible_but_delivered_report_is():
    class Store:
        def __init__(self, causal):
            self.causal = causal
        def read_json(self, path):
            assert path == "state/event/events-messages-and-movement.json"
            return {"causal_events": self.causal}

    causal = {
        "event_hidden": {
            "event_ref": "event_hidden",
            "kind": "world_arc_activity",
            "status": "triggered",
            "triggered_at": "245-BCE-12-05T07:00:00+08:00",
            "summary": "hidden arc detail",
        },
        "event_report": {
            "event_ref": "event_report",
            "kind": "world_arc_report",
            "status": "triggered",
            "triggered_at": "245-BCE-12-05T08:00:00+08:00",
            "summary": "lawfully delivered report",
            "arc_ref": "arc_test",
            "delivery": {"target_ref": "char_tang_wei", "location_ref": "loc_kanyou"},
        },
    }
    handles, count = triggered_interaction_handles(Store(causal), limit=8)
    assert count == 1
    assert [item["interaction_ref"] for item in handles] == ["event_report"]
    assert handles[0]["summary"] == "lawfully delivered report"
