from __future__ import annotations

from sword_runtime.vitality import summarize_playability_vitality


class _Store:
    def __init__(self, event: dict):
        self.docs = {
            "state/meta.json": {"player_id": "char_tang_wei", "time": "245-BCE-12-25T20:22:48+08:00", "revision": 100},
            "state/runtime.json": {"hosts": {}, "pending_wake": None},
            "state/arc/kingdom-arcs.json": {"records": []},
            "state/event/events-messages-and-movement.json": {"causal_events": {event["event_ref"]: event}, "archived_event_count": 0},
            "state/information/index.json": {"claims": {}},
            "state/scene.json": {"world_time": None, "projection_revision": None, "narrative": {"available_reports": []}},
            "state/index/institutional-process-routing.json": {"processes": []},
        }

    def read_json(self, path: str):
        return self.docs[path]


def _activity(result: str) -> dict:
    return {
        "event_ref": "event_world_arc_test",
        "kind": "world_arc_activity",
        "status": "triggered",
        "visibility_class": "discoverable",
        "result": result,
    }


def test_discoverable_queued_work_is_intentionally_not_a_missing_report_route() -> None:
    summary = summarize_playability_vitality(_Store(_activity("work_queued")))
    assert summary["visible_arc_activities_without_delivery_route"] == 0
    assert summary["suppressed_nonmaterial_visible_arc_activities"] == 1
    assert "player_visible_world_arc_activity_without_delivery_route" not in summary["diagnostics"]


def test_reportable_material_activity_without_route_still_fails_vitality() -> None:
    summary = summarize_playability_vitality(_Store(_activity("material_action_settled")))
    assert summary["visible_arc_activities_without_delivery_route"] == 1
    assert summary["suppressed_nonmaterial_visible_arc_activities"] == 0
    assert "player_visible_world_arc_activity_without_delivery_route" in summary["diagnostics"]


def test_concretely_blocked_activity_remains_report_eligible() -> None:
    summary = summarize_playability_vitality(_Store(_activity("work_blocked")))
    assert summary["visible_arc_activities_without_delivery_route"] == 1
