from __future__ import annotations

import copy
from pathlib import Path

from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.scheduler_frontier import (
    RECONCILE_EVENT_ID,
    RECONCILE_HOST_ID,
    RECONCILE_SECONDS,
    mark_scheduler_dirty,
    record_reconciliation,
    runtime_route_integrity,
)
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign: Path) -> ProductionCampaignPlanner:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    return planner


def test_small_advance_moves_world_and_causal_frontier_together_without_full_reconcile(campaign: Path) -> None:
    planner = _planner(campaign)
    before = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(before["world_time"]))
    revision = int(before["scheduler"]["registry_revision"])
    last_reconciled = str(before["scheduler"]["last_reconciled_at"])

    planner._active_command_type = "advance_time"
    planner._advance_runtime(str(current.add_hours(1)))
    after = planner.read("state/runtime.json")

    assert after["world_time"] == str(current.add_hours(1))
    assert after["scheduler"]["causal_settled_through"] == after["world_time"]
    assert int(after["scheduler"]["registry_revision"]) == revision
    assert after["scheduler"]["last_reconciled_at"] == last_reconciled


def test_dirty_scheduler_repairs_missing_dynamic_route_before_even_a_short_advance(campaign: Path) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    target_owner = "faction_qin_noble_patrons"
    target_host = next(
        host_id for host_id, host in runtime["hosts"].items()
        if host.get("kind") == "faction" and host.get("owner_ref") == target_owner
    )
    runtime["hosts"].pop(target_host)
    runtime["events"] = [row for row in runtime["events"] if row.get("target_host") != target_host]
    mark_scheduler_dirty(runtime, "test_missing_faction_route")
    planner.put("state/runtime.json", runtime)

    planner._active_command_type = "advance_time"
    planner._advance_runtime(str(current.add_hours(1)))
    repaired = planner.read("state/runtime.json")

    assert any(
        host.get("kind") == "faction" and host.get("owner_ref") == target_owner
        for host in repaired["hosts"].values()
    )
    assert repaired["scheduler"]["dirty"] is False
    assert repaired["scheduler"]["causal_settled_through"] == repaired["world_time"]
    assert runtime_route_integrity(repaired)["complete"] is True


def test_long_skip_runs_periodic_reconciliation_inside_the_same_chronological_heap(campaign: Path) -> None:
    class CountingPlanner(ProductionCampaignPlanner):
        def __init__(self, root: object) -> None:
            super().__init__(root)
            self.reconciled_at: list[str] = []

        def _reconcile_all_scheduler_domains(self, at: str):
            self.reconciled_at.append(at)
            runtime = copy.deepcopy(self.read("state/runtime.json"))
            coverage = runtime_route_integrity(runtime)
            record_reconciliation(runtime, at, coverage=coverage)
            self.put("state/runtime.json", runtime)
            return coverage

    planner = CountingPlanner(campaign)
    planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    # Isolate the scheduler-control host so this test proves chronology rather
    # than depending on any campaign-specific NPC outcome.
    host = copy.deepcopy(runtime["hosts"][RECONCILE_HOST_ID])
    event = next(copy.deepcopy(row) for row in runtime["events"] if row.get("event_id") == RECONCILE_EVENT_ID)
    first_reconcile = current.add_seconds(RECONCILE_SECONDS)
    host["resolved_through"] = str(current)
    host["next_due"] = str(first_reconcile)
    host["safe_through"] = str(first_reconcile.add_seconds(-1))
    event["due_at"] = str(first_reconcile)
    runtime["hosts"] = {RECONCILE_HOST_ID: host}
    runtime["events"] = [event]
    runtime["scheduler"]["dirty"] = False
    runtime["scheduler"]["next_safety_reconcile_at"] = str(first_reconcile)
    planner.put("state/runtime.json", runtime)

    target = current.add_seconds(15 * 86400)
    planner._active_command_type = "advance_time"
    result = planner._advance_runtime(str(target))
    after = planner.read("state/runtime.json")

    assert planner.reconciled_at == [
        str(current.add_seconds(RECONCILE_SECONDS)),
        str(current.add_seconds(RECONCILE_SECONDS * 2)),
    ]
    assert result["causal_settled_through"] == str(target)
    assert after["scheduler"]["causal_settled_through"] == str(target)
    assert after["world_time"] == str(target)


def test_scheduler_frontier_never_runs_ahead_of_an_interrupt(campaign: Path) -> None:
    class InterruptPlanner(ProductionCampaignPlanner):
        def _settle_operational_battlefields(self, start: CampaignTime, end: CampaignTime):
            if end <= start:
                return {"player_interrupt": False, "delivered_reports": [], "reviews": []}
            reached = start.add_hours(6) if end > start.add_hours(6) else end
            return {
                "player_interrupt": True,
                "reached_time": str(reached),
                "delivered_reports": [{
                    "report_id": "report_test_frontier",
                    "operation_ref": "operation_test_frontier",
                    "battlefield_ref": "battlefield_test_frontier",
                    "sector_ref": "sector_test_frontier",
                    "level": "contact",
                }],
                "reviews": [],
            }

    planner = InterruptPlanner(campaign)
    planner._reset()
    # Normalize the live campaign's one-time entry-authority lifecycle before
    # isolating scheduler hosts. This test measures the battlefield frontier,
    # not the current campaign fixture's follow-on order handoff.
    planner._reconcile_campaign_entry_authority()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    # Isolate scheduler activity beyond this window so the assertion measures
    # the battlefield interruption frontier itself rather than a campaign-host
    # fixture that happens to wake sooner.
    far_due = current.add_seconds(100 * 86400)
    reconcile_host = copy.deepcopy(runtime["hosts"][RECONCILE_HOST_ID])
    reconcile_event = next(copy.deepcopy(row) for row in runtime["events"] if row.get("event_id") == RECONCILE_EVENT_ID)
    reconcile_host["resolved_through"] = str(current)
    reconcile_host["next_due"] = str(far_due)
    reconcile_host["safe_through"] = str(far_due.add_seconds(-1))
    reconcile_event["due_at"] = str(far_due)
    runtime["hosts"] = {RECONCILE_HOST_ID: reconcile_host}
    runtime["events"] = [reconcile_event]
    runtime["scheduler"]["next_safety_reconcile_at"] = str(far_due)
    runtime["scheduler"]["dirty"] = False
    planner.put("state/runtime.json", runtime)

    planner._active_command_type = "advance_time"
    result = planner._advance_runtime(str(current.add_hours(48)))
    after = planner.read("state/runtime.json")

    assert result["interrupted"] is True
    assert after["world_time"] == str(current.add_hours(6))
    assert after["scheduler"]["causal_settled_through"] == after["world_time"]
    assert CampaignTime.parse(after["world_time"]) < current.add_hours(48)


def test_long_advance_requeues_recreated_one_shot_with_same_event_id(campaign: Path) -> None:
    """A stable action may retire and recreate its one-shot route in one skip.

    Queue identity must include the due generation, not only event_id, otherwise
    the second incarnation is silently skipped and becomes overdue later.
    """
    class RecreatedRoutePlanner(ProductionCampaignPlanner):
        def __init__(self, root: object) -> None:
            super().__init__(root)
            self.one_shot_runs: list[str] = []

        def _run_due_host(self, host, due_text: str) -> None:
            kind = host.get("kind")
            if kind == "queue_generation_trigger":
                runtime = copy.deepcopy(self.read("state/runtime.json"))
                due = CampaignTime.parse(due_text).add_hours(1)
                runtime["hosts"]["host_reused_one_shot"] = {
                    "kind": "queue_generation_once",
                    "owner_ref": "test_reused_action",
                    "event_id": "event_reused_one_shot",
                    "recurrence_seconds": 0,
                    "resolved_through": due_text,
                    "next_due": str(due),
                    "safe_through": str(due.add_seconds(-1)),
                }
                runtime["events"].append({
                    "event_id": "event_reused_one_shot",
                    "kind": "queue_generation_once",
                    "priority": 50,
                    "target_host": "host_reused_one_shot",
                    "due_at": str(due),
                })
                self.put("state/runtime.json", runtime)
                self._pending_wake_created = None
                return
            if kind == "queue_generation_once":
                self.one_shot_runs.append(due_text)
                self._pending_wake_created = None
                return
            super()._run_due_host(host, due_text)

    planner = RecreatedRoutePlanner(campaign)
    planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    first = current.add_hours(1)
    runtime["hosts"] = {
        "host_queue_generation_trigger": {
            "kind": "queue_generation_trigger",
            "owner_ref": "test_queue_generation",
            "event_id": "event_queue_generation_trigger",
            "recurrence_seconds": 2 * 3600,
            "resolved_through": str(current),
            "next_due": str(first),
            "safe_through": str(first.add_seconds(-1)),
        }
    }
    runtime["events"] = [{
        "event_id": "event_queue_generation_trigger",
        "kind": "queue_generation_trigger",
        "priority": 40,
        "target_host": "host_queue_generation_trigger",
        "due_at": str(first),
    }]
    runtime["scheduler"]["dirty"] = False
    runtime["scheduler"]["last_reconciled_at"] = str(current)
    runtime["scheduler"]["next_safety_reconcile_at"] = str(current.add_seconds(7 * 86400))
    runtime["scheduler"]["causal_settled_through"] = str(current)
    planner.put("state/runtime.json", runtime)

    planner._active_command_type = "advance_time"
    target = current.add_hours(4).add_seconds(1800)
    planner._advance_runtime(str(target))

    assert planner.one_shot_runs == [str(current.add_hours(2)), str(current.add_hours(4))]
    after = planner.read("state/runtime.json")
    assert "host_reused_one_shot" not in after["hosts"]
    assert not any(row.get("event_id") == "event_reused_one_shot" for row in after["events"])
    assert after["scheduler"]["causal_settled_through"] == str(target)


def test_weekly_scheduler_safety_does_not_rescan_all_people_until_deep_safety_boundary(campaign: Path) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    routing = runtime.setdefault("person_activity_routing", {})
    routing["last_route_scan_at"] = str(current)
    runtime["scheduler"]["dirty"] = False

    assert planner._activity_route_reconcile_required(runtime, str(current.add_seconds(7 * 86400))) is False
    assert planner._activity_route_reconcile_required(runtime, str(current.add_seconds(29 * 86400))) is False
    assert planner._activity_route_reconcile_required(runtime, str(current.add_seconds(30 * 86400))) is True

    runtime["scheduler"]["dirty"] = True
    assert planner._activity_route_reconcile_required(runtime, str(current.add_hours(1))) is True


def test_base_engine_time_advance_keeps_frontier_synced_and_marks_production_reconcile_dirty(campaign: Path) -> None:
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    runtime["scheduler"]["dirty"] = False
    runtime["scheduler"]["dirty_reasons"] = []
    planner.put("state/runtime.json", runtime)

    target = current.add_hours(1)
    planner._advance_runtime(str(target))
    after = planner.read("state/runtime.json")

    assert after["world_time"] == str(target)
    assert after["scheduler"]["causal_settled_through"] == str(target)
    assert after["scheduler"]["dirty"] is True
    assert "base_engine_advance_requires_production_reconcile" in after["scheduler"]["dirty_reasons"]


def test_retiring_one_shot_can_append_child_route_without_losing_it(campaign: Path) -> None:
    """A one-shot callback may append its successor while retiring itself.

    Event removal must not hide the appended route merely because the final event
    list length matches the pre-callback length after the parent is removed.
    """
    class ParentChildPlanner(ProductionCampaignPlanner):
        def __init__(self, root: object) -> None:
            super().__init__(root)
            self.child_runs: list[str] = []

        def _run_due_host(self, host, due_text: str) -> None:
            kind = str(host.get("kind", ""))
            if kind == "test_parent_once":
                runtime = copy.deepcopy(self.read("state/runtime.json"))
                child_due = CampaignTime.parse(due_text).add_hours(1)
                runtime["hosts"]["host_test_child_once"] = {
                    "kind": "test_child_once",
                    "owner_ref": "test_parent_child",
                    "event_id": "event_test_child_once",
                    "recurrence_seconds": 0,
                    "resolved_through": due_text,
                    "next_due": str(child_due),
                    "safe_through": str(child_due.add_seconds(-1)),
                }
                runtime["events"].append({
                    "event_id": "event_test_child_once",
                    "kind": "test_child_once",
                    "priority": 51,
                    "target_host": "host_test_child_once",
                    "due_at": str(child_due),
                })
                self.put("state/runtime.json", runtime)
                self._pending_wake_created = None
                return
            if kind == "test_child_once":
                self.child_runs.append(due_text)
                self._pending_wake_created = None
                return
            super()._run_due_host(host, due_text)

    planner = ParentChildPlanner(campaign)
    planner._reset()
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    current = CampaignTime.parse(str(runtime["world_time"]))
    parent_due = current.add_hours(1)
    runtime["hosts"] = {
        "host_test_parent_once": {
            "kind": "test_parent_once",
            "owner_ref": "test_parent_child",
            "event_id": "event_test_parent_once",
            "recurrence_seconds": 0,
            "resolved_through": str(current),
            "next_due": str(parent_due),
            "safe_through": str(parent_due.add_seconds(-1)),
        }
    }
    runtime["events"] = [{
        "event_id": "event_test_parent_once",
        "kind": "test_parent_once",
        "priority": 50,
        "target_host": "host_test_parent_once",
        "due_at": str(parent_due),
    }]
    runtime["scheduler"]["dirty"] = False
    runtime["scheduler"]["last_reconciled_at"] = str(current)
    runtime["scheduler"]["next_safety_reconcile_at"] = str(current.add_seconds(7 * 86400))
    runtime["scheduler"]["causal_settled_through"] = str(current)
    planner.put("state/runtime.json", runtime)

    planner._active_command_type = "advance_time"
    target = current.add_hours(3)
    planner._advance_runtime(str(target))

    assert planner.child_runs == [str(current.add_hours(2))]
    after = planner.read("state/runtime.json")
    assert "host_test_parent_once" not in after["hosts"]
    assert "host_test_child_once" not in after["hosts"]
    assert not any(
        row.get("event_id") in {"event_test_parent_once", "event_test_child_once"}
        for row in after["events"]
    )
    assert after["scheduler"]["causal_settled_through"] == str(target)


def test_bounded_long_horizon_windows_match_single_heap_and_remain_atomic(campaign: Path) -> None:
    """Internal scheduler windows are working-memory boundaries, not commits."""
    class WindowPlanner(ProductionCampaignPlanner):
        def __init__(self, root: object) -> None:
            super().__init__(root)
            self.tick_runs: list[str] = []
            self.post_calls = 0

        def _prepare_scheduler_for_advance(self, target_text: str) -> None:
            del target_text

        def _post_advance_domain_hooks(self, metrics):
            self.post_calls += 1
            return dict(metrics)

        def _run_due_host(self, host, due_text: str) -> None:
            if str(host.get("kind", "")) == "test_daily_tick":
                self.tick_runs.append(due_text)
                self._pending_wake_created = None
                return
            super()._run_due_host(host, due_text)

    def configure(planner: WindowPlanner) -> tuple[CampaignTime, CampaignTime, str]:
        planner._reset()
        runtime = copy.deepcopy(planner.read("state/runtime.json"))
        original_disk_time = str(planner.store.read_json("state/runtime.json")["world_time"])
        current = CampaignTime.parse(str(runtime["world_time"]))
        first = current.add_seconds(86400)
        target = current.add_seconds(65 * 86400)
        runtime["hosts"] = {
            "host_test_daily_tick": {
                "kind": "test_daily_tick",
                "owner_ref": "test_daily_tick",
                "event_id": "event_test_daily_tick",
                "recurrence_seconds": 86400,
                "resolved_through": str(current),
                "next_due": str(first),
                "safe_through": str(first.add_seconds(-1)),
            }
        }
        runtime["events"] = [{
            "event_id": "event_test_daily_tick",
            "kind": "test_daily_tick",
            "priority": 50,
            "target_host": "host_test_daily_tick",
            "due_at": str(first),
        }]
        runtime["scheduler"]["dirty"] = False
        runtime["scheduler"]["last_reconciled_at"] = str(current)
        runtime["scheduler"]["next_safety_reconcile_at"] = str(target.add_seconds(86400))
        runtime["scheduler"]["causal_settled_through"] = str(current)
        planner.put("state/runtime.json", runtime)
        planner._active_command_type = "advance_time"
        return current, target, original_disk_time

    direct = WindowPlanner(campaign)
    _current, target, original_disk_time = configure(direct)
    direct_metrics = direct._advance_causal_runtime(str(target))

    windowed = WindowPlanner(campaign)
    _current2, target2, original_disk_time2 = configure(windowed)
    assert str(target2) == str(target)
    windowed_metrics = windowed._advance_runtime(str(target2))

    assert direct.tick_runs == windowed.tick_runs
    assert len(windowed.tick_runs) == 65
    assert direct.read("state/runtime.json") == windowed.read("state/runtime.json")
    assert int(direct_metrics["events_processed"]) == int(windowed_metrics["events_processed"])
    assert int(direct_metrics["hosts_woken"]) == int(windowed_metrics["hosts_woken"])
    assert windowed.post_calls == 1
    assert windowed.read("state/runtime.json")["world_time"] == str(target2)
    assert windowed.read("state/runtime.json")["scheduler"]["causal_settled_through"] == str(target2)
    # No internal window persisted anything. The repository still exposes the
    # pre-command snapshot until the outer transaction coordinator commits.
    assert original_disk_time2 == original_disk_time
    assert str(windowed.store.read_json("state/runtime.json")["world_time"]) == original_disk_time


def test_regional_state_institutions_have_authoritative_owner_routes(campaign):
    import json
    owners = json.loads((campaign / "state/index/owner-index.json").read_text(encoding="utf-8"))["owners"]
    for state in ("qin", "zhao", "chu", "wei", "han", "yan", "qi"):
        rel = f"state/institutions/regional-{state}.json"
        records = json.loads((campaign / rel).read_text(encoding="utf-8"))["records"]
        for ref in records:
            assert owners.get(ref) == f"{rel}#/records/{ref}"
