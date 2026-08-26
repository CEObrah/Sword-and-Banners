from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from sword_runtime.api.interaction_surface import triggered_interaction_handles
from sword_runtime.autonomy_routing import rotating_candidate_refs
from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.world_arcs import _initial_momentum, _schedule_report_route, settle_world_arc_review, sync_world_arc_routes


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


def _release_formation_from_active_operation(planner, formation_ref: str) -> None:
    """Free one exact fixture formation without changing manpower or authority."""
    index = planner.read("state/operations/index.json")
    for operation_path in index.get("operations", {}).values():
        if not isinstance(operation_path, str):
            continue
        operation = copy.deepcopy(planner.read(operation_path))
        if formation_ref not in operation.get("formation_refs", []):
            continue
        if str(operation.get("status", "")) not in {"active", "mobilizing", "advancing", "engaged", "occupied"}:
            continue
        operation["status"] = "completed"
        operation["completed_at"] = str(planner.read("state/runtime.json")["world_time"])
        planner.put(operation_path, operation)


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
    before = next(item for item in planner.read("state/arc/kingdom-arcs.json")["records"] if item.get("record_id") == arc_ref)
    before_runtime = before.get("runtime", {})
    before_reviews = int(before_runtime.get("review_count", 0))
    before_initiatives = int(before_runtime.get("initiative_count", 0))

    settle_world_arc_review(planner, host, now)

    arcs = planner.read("state/arc/kingdom-arcs.json")
    record = next(item for item in arcs["records"] if item.get("record_id") == arc_ref)
    runtime = record["runtime"]
    assert runtime["review_count"] == before_reviews + 1
    assert runtime["initiative_count"] in {before_initiatives, before_initiatives + 1}
    assert runtime["pressure_stage"] in {"contained", "developing", "material", "acute"}
    assert isinstance(runtime["driver_refs"], list)
    owner = planner.read("state/event/events-messages-and-movement.json")
    _validate_event_registry(Path(campaign), owner)
    if runtime["initiative_count"] > before_initiatives:
        event_ref = runtime["last_initiative_ref"]
        event = owner["causal_events"][event_ref]
        assert event["kind"] == "world_arc_activity"
        assert event["actor_ref"] in runtime["driver_refs"]
        assert event["basis_goal"]
        assert event["result"] in {"material_action_settled", "work_queued", "work_blocked", "intent_recorded"}
        assert event["provenance"]["kind"] == "world_arc_orchestration"
        assert "success roll" not in event["summary"].lower()
        assert event["visibility_class"] == "hidden"
        assert "opportunity_template" not in event

    # Arc orchestration may trigger a registered political/economic action, but it
    # may not directly fabricate military logistics or territorial outcomes.
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


def test_northern_steppe_arc_has_exact_non_zhao_driver(campaign):
    from sword_runtime.world_arcs import _resolve_driver_refs
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign)
    registry = planner.read('state/arc/kingdom-arcs.json')
    record = next(row for row in registry['records'] if row.get('record_id') == 'arc_northern_steppe_ganmon_pressure')
    drivers = _resolve_driver_refs(planner, record)
    assert 'state_zhao' in drivers
    assert 'polity_northern_steppe' in drivers



def test_every_current_active_arc_first_review_reports_truthful_domain_status(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    active = _active_arc_refs(ProductionCampaignPlanner(campaign))
    assert active
    results = {}
    for arc_ref in active:
        planner = ProductionCampaignPlanner(campaign)
        planner._reset()
        arcs_before = planner.read("state/arc/kingdom-arcs.json")
        before_record = next(item for item in arcs_before["records"] if item.get("record_id") == arc_ref)
        before_momentum = int(before_record.get("runtime", {}).get("pressure_momentum", _initial_momentum(before_record)))
        now = str(planner.read("state/runtime.json")["world_time"])
        settle_world_arc_review(planner, {"kind": "world_arc", "owner_ref": "kingdom_arcs", "arc_ref": arc_ref}, now)
        arcs = planner.read("state/arc/kingdom-arcs.json")
        record = next(item for item in arcs["records"] if item.get("record_id") == arc_ref)
        event_ref = record["runtime"].get("last_initiative_ref")
        assert event_ref, f"{arc_ref} produced no initiative"
        event = planner.read("state/event/events-messages-and-movement.json")["causal_events"][event_ref]
        result = event["result"]
        assert result in {"material_action_settled", "work_queued", "work_blocked", "intent_recorded"}
        assert result != "work_executed"
        after_momentum = int(record["runtime"]["pressure_momentum"])
        if result == "material_action_settled":
            assert after_momentum == min(6, before_momentum + 1)
            assert "settled" in event["summary"].lower() or "material" in event["summary"].lower()
            evidence = event["provenance"].get("material_evidence")
            assert isinstance(evidence, dict) and evidence, (arc_ref, event)
        elif result == "work_blocked":
            assert after_momentum == max(0, before_momentum - 1)
        else:
            assert after_momentum == before_momentum
        results[arc_ref] = (event["actor_ref"], result)

    # The Hyou review currently has no lawful material downstream action.  It must
    # remain queued rather than falsely advancing the strategic arc.
    assert results["arc_shin_hyou_departure"][1] == "work_queued"
    # A current snapshot is allowed to have every actor materially committed
    # elsewhere. The synthetic priority tests below prove the material-operation
    # path without requiring the live campaign to keep an idle formation.


def test_world_arc_cannot_claim_material_execution_without_domain_evidence(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    arc_ref = "arc_qin_succession_crisis_245"
    arcs_before = planner.read("state/arc/kingdom-arcs.json")
    before_record = next(item for item in arcs_before["records"] if item.get("record_id") == arc_ref)
    before_momentum = int(before_record.get("runtime", {}).get("pressure_momentum", _initial_momentum(before_record)))
    planner._world_arc_domain_action = lambda actor_ref, target_ref, goal, at, arc_ref: {
        "status": "material_action_settled",
        "action": "fake_dead_priority",
        "action_ref": "dead_priority_record",
    }
    now = str(planner.read("state/runtime.json")["world_time"])
    for _ in range(4):
        settle_world_arc_review(planner, {"kind": "world_arc", "owner_ref": "kingdom_arcs", "arc_ref": arc_ref}, now)
    arcs = planner.read("state/arc/kingdom-arcs.json")
    record = next(item for item in arcs["records"] if item.get("record_id") == arc_ref)
    event_ref = record["runtime"]["last_initiative_ref"]
    event = planner.read("state/event/events-messages-and-movement.json")["causal_events"][event_ref]
    assert event["result"] == "work_queued"
    assert int(record["runtime"]["pressure_momentum"]) == before_momentum
    assert "material_evidence" not in event["provenance"]


def test_state_and_house_arc_preparation_never_counts_as_strategic_progress(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    cases = (
        ("arc_qin_succession_crisis_245", "house_ou_family", "house", "char_sei_kyou", "test house preparation without strategic progress"),
        ("arc_ryo_fui_northern_wei_campaign", "state_qin", "state", "state_wei", "test state preparation without strategic progress"),
    )
    for arc_ref, owner_ref, domain, target_ref, goal in cases:
        planner = ProductionCampaignPlanner(campaign)
        planner._reset()
        now = str(planner.read("state/runtime.json")["world_time"])
        arc_before = next(item for item in planner.read("state/arc/kingdom-arcs.json")["records"] if item.get("record_id") == arc_ref)
        momentum_before = int(arc_before.get("runtime", {}).get("pressure_momentum", _initial_momentum(arc_before)))

        if domain == "house":
            result = planner._world_arc_house_action(owner_ref, target_ref, goal, now, arc_ref)
        else:
            result = planner._world_arc_state_action(owner_ref, target_ref, goal, now, arc_ref)
        assert result["status"] == "work_queued"
        action_ref = result["action_ref"]

        arc_after = next(item for item in planner.read("state/arc/kingdom-arcs.json")["records"] if item.get("record_id") == arc_ref)
        assert int(arc_after.get("runtime", {}).get("pressure_momentum", _initial_momentum(arc_after))) == momentum_before

        owner_path = planner.owner_path(owner_ref) if domain == "house" else f"state/states/{owner_ref.removeprefix('state_')}.json"
        owner = planner.read(owner_path)
        queue = [row for row in owner.get("world_arc_priorities", []) if isinstance(row, dict) and row.get("action_ref") == action_ref]
        assert len(queue) == 1
        first_spend = int(queue[0].get("coordination_spent_silver", 0))
        assert first_spend > 0

        if domain == "house":
            repeated = planner._world_arc_house_action(owner_ref, target_ref, goal, now, arc_ref)
        else:
            repeated = planner._world_arc_state_action(owner_ref, target_ref, goal, now, arc_ref)
        assert repeated["status"] == "work_queued"
        assert repeated["action_ref"] == action_ref
        owner2 = planner.read(owner_path)
        queue2 = [row for row in owner2.get("world_arc_priorities", []) if isinstance(row, dict) and row.get("action_ref") == action_ref]
        assert len(queue2) == 1
        assert int(queue2[0].get("coordination_spent_silver", 0)) == first_spend


def test_world_arc_reports_get_independent_delivery_hosts_per_source_event(campaign):
    planner = CampaignEventPlayerGroupActionPlanner(campaign)
    planner._reset()
    now = str(planner.read("state/runtime.json")["world_time"])
    kwargs = dict(arc_ref="arc_qin_succession_crisis_245", at=now, route="court report", origin_state="qin", pressure_stage="material", visibility="discoverable")
    _schedule_report_route(planner, source_event_ref="event_arc_source_old", **kwargs)
    _schedule_report_route(planner, source_event_ref="event_arc_source_new", **kwargs)
    runtime = planner.read("state/runtime.json")
    hosts = [row for row in runtime["hosts"].values() if isinstance(row, dict) and row.get("kind") == "world_arc_report" and row.get("arc_ref") == "arc_qin_succession_crisis_245"]
    source_refs = {row.get("source_event_ref") for row in hosts}
    assert {"event_arc_source_old", "event_arc_source_new"}.issubset(source_refs)
    assert len({row["host_id"] for row in hosts if row.get("source_event_ref") in source_refs}) >= 2


def test_delivered_one_shot_world_arc_report_scheduler_route_is_garbage_collected(campaign):
    from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    for event in runtime.get("events", []):
        if isinstance(event, dict): event["suspended"] = True
    planner.put("state/runtime.json", runtime)
    now = str(runtime["world_time"])
    _path, owner = read_causal_event_owner(planner)
    source_ref = "event_world_arc_gc_source"
    owner.setdefault("causal_events", {})[source_ref] = {
        "event_ref": source_ref, "kind": "world_arc_activity", "status": "triggered",
        "due_at": now, "triggered_at": now, "arc_ref": "arc_qin_succession_crisis_245",
        "actor_ref": "house_shou_bun_kun_household", "initiative_kind": "political_initiative",
        "basis_goal": "protect the loyal network", "result": "material_action_settled",
        "pressure_stage": "material", "visibility_class": "direct", "summary": "Material loyalist coordination settled.",
        "provenance": {
            "kind": "world_arc_orchestration",
            "arc_owner_ref": "kingdom_arcs",
            "review_count": 1,
            "domain_status": "material_action_settled",
            "domain_action_ref": "house_gc_action",
            "material_evidence": {
                "kind": "exact_operation_created",
                "operation_ref": "operation_test_gc",
                "formation_ref": "formation_test_gc",
                "formation_status_before": "ready",
                "formation_status_after": "mobilized",
                "evidence_stage": "domain_action",
            },
        },
    }
    write_causal_event_owner(planner, owner)
    _schedule_report_route(planner, arc_ref="arc_qin_succession_crisis_245", source_event_ref=source_ref, at=now, route="direct family report", origin_state="qin", pressure_stage="material", visibility="direct")
    scheduled = planner.read("state/runtime.json")
    host_id = next(hid for hid, h in scheduled["hosts"].items() if isinstance(h, dict) and h.get("source_event_ref") == source_ref)
    event_id = scheduled["hosts"][host_id]["event_id"]
    due = scheduled["hosts"][host_id]["next_due"]
    planner._active_command_type = "advance_time"
    planner._advance_runtime(due)
    after = planner.read("state/runtime.json")
    assert host_id not in after["hosts"]
    assert event_id not in {row.get("event_id") for row in after.get("events", []) if isinstance(row, dict)}
    report = read_causal_event_owner(planner)[1]["causal_events"][source_ref + ".report"]
    assert report["delivery"]["target_ref"] == "char_tang_wei"


def test_world_arc_sync_prunes_unreferenced_terminal_report_routes(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["hosts"]["host_world_arc_report_old_terminal"] = {
        "host_id": "host_world_arc_report_old_terminal", "kind": "world_arc_report", "owner_ref": "kingdom_arcs",
        "event_id": "event_world_arc_report_old_terminal", "next_due": None, "resolved_through": runtime["world_time"],
        "safe_through": runtime["world_time"], "recurrence_seconds": 0,
    }
    runtime["events"].append({"event_id": "event_world_arc_report_old_terminal", "kind": "world_arc_report_delivery", "priority": 75, "target_host": "host_world_arc_report_old_terminal", "due_at": runtime["world_time"], "suspended": True})
    sync_world_arc_routes(planner, runtime)
    assert "host_world_arc_report_old_terminal" not in runtime["hosts"]
    assert all(row.get("target_host") != "host_world_arc_report_old_terminal" for row in runtime["events"] if isinstance(row, dict))


def test_queued_person_arc_work_does_not_compound_momentum_or_duplicate_attempts(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    arc_ref = "arc_shin_hyou_departure"
    arcs = planner.read("state/arc/kingdom-arcs.json")
    record = next(item for item in arcs["records"] if item.get("record_id") == arc_ref)
    baseline = int(record.get("runtime", {}).get("pressure_momentum", _initial_momentum(record)))
    # Exercise the exact queued personal bridge directly twice, then confirm the
    # unresolved initiative is one durable queue entry rather than fictional work.
    now = str(planner.read("state/runtime.json")["world_time"])
    first = planner._world_arc_person_action("char_shin", None, "depart into service under hidden political pressure", now, arc_ref)
    second = planner._world_arc_person_action("char_shin", None, "depart into service under hidden political pressure", now, arc_ref)
    assert first["status"] == second["status"] == "work_queued"
    person = planner.read(planner.owner_path("char_shin"))
    attempts = [row for row in list(person.get("runtime", {}).get("autonomous_priorities", {}).values()) if row.get("arc_ref") == arc_ref and row.get("status") == "queued"]
    matching = [row for row in attempts if row.get("action_ref") == first["action_ref"]]
    assert len(matching) == 1
    assert matching[0]["action_ref"] == first["action_ref"] == second["action_ref"]
    # Merely queueing exact-person intent does not mutate the arc's pressure owner.
    after = planner.read("state/arc/kingdom-arcs.json")
    after_record = next(item for item in after["records"] if item.get("record_id") == arc_ref)
    assert int(after_record.get("runtime", {}).get("pressure_momentum", _initial_momentum(after_record))) == baseline


def test_queued_person_priority_is_consumed_by_actor_host_before_arc_observes_it(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    now = str(planner.read("state/runtime.json")["world_time"])
    arc_ref = "arc_shin_hyou_departure"
    queued = planner._world_arc_person_action("char_shin", "char_kyoukai", "seize the first lawful opportunity to enter service", now, arc_ref)
    assert queued["status"] == "work_queued"
    runtime = planner.read("state/runtime.json")
    host = next(h for h in runtime["hosts"].values() if isinstance(h, dict) and h.get("kind") == "world_arc_priority" and h.get("action_ref") == queued["action_ref"])
    planner._settle_world_arc_priority_host(copy.deepcopy(host), host["next_due"])
    person = planner.read(planner.owner_path("char_shin"))
    row = person["runtime"]["autonomous_priorities"][queued["action_ref"]]
    assert row["status"] == "commitment_settled"
    assert row["evidence_stage"] == "commitment"
    assert row["material_evidence"]["kind"] == "exact_person_commitment"
    assert row["material_evidence"]["history_event_ref"].startswith("autonomous_domain_")
    observed = planner._world_arc_domain_action("char_shin", "char_kyoukai", row["goal"], host["next_due"], arc_ref)
    assert observed["status"] == "work_queued"
    assert observed["evidence_stage"] == "commitment"
    assert observed["material_evidence"]["history_event_ref"] == row["material_evidence"]["history_event_ref"]


def test_house_world_arc_priority_materializes_real_nonplayer_operation(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    now = str(planner.read("state/runtime.json")["world_time"])
    arc_ref = "arc_qin_succession_crisis_245"
    house_ref = "house_shou_bun_kun_household"
    _release_formation_from_active_operation(planner, "formation_house_shou_bun_kun_household_01")
    queued = planner._world_arc_house_action(house_ref, "char_sei_kyou", "protect Ei Sei and preserve the loyal network", now, arc_ref)
    assert queued["status"] == "work_queued"
    runtime = planner.read("state/runtime.json")
    host = next(h for h in runtime["hosts"].values() if isinstance(h, dict) and h.get("kind") == "world_arc_priority" and h.get("action_ref") == queued["action_ref"])
    planner._settle_world_arc_priority_host(copy.deepcopy(host), host["next_due"])
    house = planner.read(planner.owner_path(house_ref))
    row = next(x for x in house["world_arc_priorities"] if x.get("action_ref") == queued["action_ref"])
    assert row["status"] == "material_settled"
    evidence = row["material_evidence"]
    assert evidence["kind"] == "exact_operation_created"
    operation = planner.read(planner.owner_path(evidence["operation_ref"]))
    assert operation["administrative_authority"] == house_ref
    assert operation["formation_refs"] == [evidence["formation_ref"]]
    formation = planner.read(planner.owner_path(evidence["formation_ref"]))
    assert formation.get("command_authority") != planner.PLAYER_ACTOR
    assert formation.get("commander_ref") != planner.PLAYER_ACTOR


def test_world_arc_priority_scheduler_route_is_one_shot_and_arc_observes_completed_work(campaign):
    from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    # Suspend unrelated work so advancing exactly to the priority due time is bounded.
    for event in runtime.get("events", []):
        if isinstance(event, dict): event["suspended"] = True
    planner.put("state/runtime.json", runtime)
    now = str(runtime["world_time"])
    _release_formation_from_active_operation(planner, "formation_qin_mobile_reserve")
    test_arc_ref = "test_world_arc_priority_scheduler_material"
    queued = planner._world_arc_state_action("state_qin", "state_wei", "protect core territory and maintain military readiness", now, test_arc_ref)
    scheduled = copy.deepcopy(planner.read("state/runtime.json"))
    host_id, host = next((hid, h) for hid, h in scheduled["hosts"].items() if isinstance(h, dict) and h.get("kind") == "world_arc_priority" and h.get("action_ref") == queued["action_ref"])
    event_id = host["event_id"]
    # Active world-arc routes are intentionally resumed by route reconciliation.
    # Keep unrelated active arcs outside this bounded advancement window rather
    # than pretending they are dormant via a transient suspended flag.
    from sword_runtime.sim.calendar import CampaignTime
    deferred_due = str(CampaignTime.parse(str(host["next_due"])).add_seconds(86400))
    for event in scheduled.get("events", []):
        if not isinstance(event, dict) or event.get("event_id") == event_id:
            continue
        target_host = event.get("target_host")
        route_host = scheduled.get("hosts", {}).get(target_host) if isinstance(target_host, str) else None
        if isinstance(route_host, dict) and route_host.get("kind") == "world_arc":
            route_host["next_due"] = deferred_due
            route_host["safe_through"] = str(CampaignTime.parse(deferred_due).add_seconds(-1))
            event["due_at"] = deferred_due
        else:
            event["suspended"] = True
    planner.put("state/runtime.json", scheduled)
    host = scheduled["hosts"][host_id]
    planner._active_command_type = "advance_time"
    planner._advance_runtime(host["next_due"])
    after = planner.read("state/runtime.json")
    assert host_id not in after["hosts"]
    assert event_id not in {row.get("event_id") for row in after.get("events", []) if isinstance(row, dict)}
    state = planner.read("state/states/qin.json")
    priority = next(x for x in state["world_arc_priorities"] if x.get("action_ref") == queued["action_ref"])
    assert priority["status"] == "material_settled"
    observed = planner._world_arc_completed_priority("state_qin", test_arc_ref)
    assert observed is not None and observed["status"] == "material_action_settled"
    assert observed["material_evidence"]["history_event_ref"].startswith("autonomous_domain_")


def test_protected_canon_pressure_anchors_activate_by_year_without_forcing_outcomes(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    baseline = copy.deepcopy(planner.read("state/runtime.json"))
    arcs = planner.read("state/arc/kingdom-arcs.json")
    sanyou = next(row for row in arcs["records"] if row.get("record_id") == "arc_sanyou_campaign_pressure")
    coalition = next(row for row in arcs["records"] if row.get("record_id") == "arc_coalition_invasion_pressure")
    assert sanyou["facts"]["status"] == "dormant protected"
    assert coalition["facts"]["status"] == "dormant protected"

    # Merely syncing in 244 BCE must not pull future pressure forward.
    sync_world_arc_routes(planner, baseline)
    still = planner.read("state/arc/kingdom-arcs.json")
    assert next(row for row in still["records"] if row.get("record_id") == "arc_sanyou_campaign_pressure")["facts"]["status"] == "dormant protected"
    assert next(row for row in still["records"] if row.get("record_id") == "arc_coalition_invasion_pressure")["facts"]["status"] == "dormant protected"

    # The source gives a campaign year rather than an exact historical day. When
    # play first reaches 241 BCE, both due anchors enter decision space, but sync
    # itself creates no treaty, mobilization, battle, casualty, or territory result.
    future = copy.deepcopy(baseline)
    future["world_time"] = "241-BCE-01-01T00:00:00+08:00"
    writes_before = set(planner._writes)
    sync_world_arc_routes(planner, future)
    after = planner.read("state/arc/kingdom-arcs.json")
    sanyou_after = next(row for row in after["records"] if row.get("record_id") == "arc_sanyou_campaign_pressure")
    coalition_after = next(row for row in after["records"] if row.get("record_id") == "arc_coalition_invasion_pressure")
    assert sanyou_after["facts"]["status"].startswith("active")
    assert coalition_after["facts"]["status"].startswith("active")
    assert coalition_after["runtime"]["anchor_activated_at"].startswith("241-BCE-")
    assert coalition_after["runtime"]["eligible_actor_refs"] == ["state_chu", "state_han", "state_qi", "state_wei", "state_yan", "state_zhao"]
    assert any(isinstance(host, dict) and host.get("arc_ref") == "arc_coalition_invasion_pressure" for host in future["hosts"].values())
    new_writes = set(planner._writes) - writes_before
    assert not any(path.startswith("state/operations/") for path in new_writes)
    assert not any(path.startswith("state/formations/") for path in new_writes)
    assert not any(path.startswith("state/politics/treaties") for path in new_writes)

    for state_ref in coalition_after["runtime"]["eligible_actor_refs"]:
        state = planner.read(planner.owner_path(state_ref))
        threat = state["known_threats"]["protected_arc:arc_coalition_invasion_pressure"]
        assert threat["source_ref"] == "state_qin"
        assert threat["severity"] >= 70
        assert state_ref not in threat["coordination_candidate_refs"]
        assert len(threat["coordination_candidate_refs"]) >= 4


def test_protected_coalition_pressure_uses_existing_sovereign_diplomacy(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime["world_time"] = "241-BCE-01-01T00:00:00+08:00"
    sync_world_arc_routes(planner, runtime)

    proposal = planner._generate_npc_diplomatic_initiative("state_zhao", runtime["world_time"])
    assert proposal is not None
    assert proposal["kind"] == "coalition"
    assert proposal["direction"] == "mutual"
    assert proposal["terms"]["coalition_target_ref"] == "state_qin"
    assert proposal["target_ref"] in {"state_chu", "state_han", "state_qi", "state_wei", "state_yan"}
    assert proposal["status"] == "in_transit"
    # A protected pressure creates a real diplomatic question, not instant consent.
    assert "treaty_ref" not in proposal


def test_qin_world_arc_retasks_player_commanded_state_detachment_instead_of_ignoring_it(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    now = str(planner.read("state/runtime.json")["world_time"])
    op_ref = "operation_arc_131572c4e8a2892bbc"
    op_path = planner.read("state/operations/index.json")["operations"][op_ref]
    operation = copy.deepcopy(planner.read(op_path))
    refs = sorted(["formation_high_guard_qin_a", "formation_high_guard_qin_b"] + [f"formation_black_banner_0{i}{suffix}" for i in range(1, 5) for suffix in ("a", "b")])
    operation.update({
        "status": "active",
        "kind": "assigned_qin_field_detachment_operation",
        "objective": "maintain military readiness",
        "objective_refs": ["arc_ryo_fui_northern_wei_campaign", "state_wei"],
        "formation_refs": refs,
        "administrative_authority": "char_tang_wei",
        "administrative_authorities": ["char_tang_wei"],
        "assignment_authority_ref": "char_tang_wei",
        "institutional_owner_ref": "state_qin",
        "source_force_ref": "force_state_qin",
        "command_group_ref": "cmdgrp.tang_wei.field_army",
        "autonomous": False,
    })
    planner.put(op_path, operation)

    evidence = planner._priority_operation_evidence(
        actor_ref="state_qin",
        action_ref="action_test_qin_orders_wei_into_war",
        arc_ref="arc_ryo_fui_northern_wei_campaign",
        goal="open offensive operations against northern Wei",
        target_ref="state_wei",
        at=now,
        force_refs=["force_state_qin"],
        kind="state_world_arc_operation",
    )

    assert evidence is not None
    assert evidence["kind"] == "player_command_operational_order_issued"
    assert evidence["operation_ref"] == op_ref
    assert evidence["formation_refs"] == refs
    assert evidence["movement_committed"] is False
    assert evidence["tactical_decision_committed"] is False
    after = planner.read(op_path)
    assert after["order_status"] == "awaiting_commander_execution"
    assert after["last_operational_order_ref"] == evidence["order_ref"]
    order = after["operational_orders"][-1]
    assert order["applies_to_formation_refs"] == refs
    assert order["excluded_non_state_formation_refs"] == []
    assert order["issuer_ref"] == "state_qin"
    assert "northern Wei" in order["objective"] or "offensive" in order["objective"]
    for ref in refs:
        formation = planner.read(planner.owner_path(ref))
        assert formation["owner_force_ref"] == "force_state_qin"
        assert formation["command_authority"] == "char_tang_wei"


def test_state_operational_order_never_commandeers_house_tang_formations(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    now = str(planner.read("state/runtime.json")["world_time"])
    op_ref = "operation_arc_131572c4e8a2892bbc"
    op_path = planner.read("state/operations/index.json")["operations"][op_ref]
    operation = copy.deepcopy(planner.read(op_path))
    qin_refs = sorted(["formation_high_guard_qin_a", "formation_high_guard_qin_b"] + [f"formation_black_banner_0{i}{suffix}" for i in range(1, 5) for suffix in ("a", "b")])
    house_refs = ["formation_red_lance_a", "formation_high_guard_infantry_01a"]
    operation.update({
        "status": "active",
        "objective": "maintain military readiness",
        "objective_refs": ["arc_ryo_fui_northern_wei_campaign", "state_wei"],
        "formation_refs": qin_refs + house_refs,
        "administrative_authority": "char_tang_wei",
        "administrative_authorities": ["char_tang_wei"],
        "assignment_authority_ref": "char_tang_wei",
        "institutional_owner_ref": "state_qin",
        "source_force_ref": "force_state_qin",
        "command_group_ref": "cmdgrp.tang_wei.field_army",
        "autonomous": False,
    })
    planner.put(op_path, operation)

    evidence = planner._priority_operation_evidence(
        actor_ref="state_qin",
        action_ref="action_test_qin_order_excludes_house",
        arc_ref="arc_ryo_fui_northern_wei_campaign",
        goal="join the northern Wei campaign",
        target_ref="state_wei",
        at=now,
        force_refs=["force_state_qin"],
        kind="state_world_arc_operation",
    )
    assert evidence is not None
    assert evidence["formation_refs"] == qin_refs
    assert evidence["excluded_non_state_formation_refs"] == sorted(house_refs)
    order = planner.read(op_path)["operational_orders"][-1]
    assert order["applies_to_formation_refs"] == qin_refs
    assert order["excluded_non_state_formation_refs"] == sorted(house_refs)
