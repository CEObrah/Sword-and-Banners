from __future__ import annotations

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.sim.calendar import CampaignTime


def test_new_world_arc_routes_start_after_one_normal_interval():
    current = "245-BCE-12-05T06:22:48+08:00"
    recurrence = 48 * 3600
    first_due = str(CampaignTime.parse(current).add_seconds(recurrence))
    runtime = {
        "world_time": current,
        "hosts": {
            "host_existing": {
                "kind": "world_arc",
                "next_due": current,
                "recurrence_seconds": recurrence,
            },
            "host_new": {
                "kind": "world_arc",
                "next_due": current,
                "recurrence_seconds": recurrence,
            },
        },
        "events": [
            {"event_id": "event_existing", "target_host": "host_existing", "due_at": current},
            {"event_id": "event_new", "target_host": "host_new", "due_at": current},
        ],
    }

    CampaignEventPlayerGroupActionPlanner._defer_new_world_arc_routes(runtime, {"host_existing"})

    assert runtime["hosts"]["host_existing"]["next_due"] == current
    assert runtime["events"][0]["due_at"] == current
    assert runtime["hosts"]["host_new"]["resolved_through"] == current
    assert runtime["hosts"]["host_new"]["next_due"] == first_due
    assert runtime["events"][1]["due_at"] == first_due


def test_campaign_event_ack_cleanup_is_narrow():
    runtime = {"acknowledged_wake": {"kind": "campaign_event", "event_id": "event_review"}}
    CampaignEventPlayerGroupActionPlanner._clear_completed_campaign_event_ack(runtime)
    assert "acknowledged_wake" not in runtime

    unrelated = {"kind": "interstate_contact", "event_id": "event_contact"}
    runtime = {"acknowledged_wake": dict(unrelated)}
    CampaignEventPlayerGroupActionPlanner._clear_completed_campaign_event_ack(runtime)
    assert runtime["acknowledged_wake"] == unrelated
