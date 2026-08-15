from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from sword_runtime.downtime import DowntimeAdvanceMixin
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


class _BoundaryBase:
    def __init__(self) -> None:
        self.docs = {
            "state/runtime.json": {
                "world_time": "245-BCE-12-07T12:05:48+08:00",
                "hosts": {
                    "host_hidden": {"next_due": "245-BCE-12-07T14:05:48+08:00"},
                    "host_report": {"next_due": "245-BCE-12-07T18:22:48+08:00"},
                },
                "events": [
                    {
                        "event_id": "event_hidden",
                        "target_host": "host_hidden",
                        "due_at": "245-BCE-12-07T14:05:48+08:00",
                    },
                    {
                        "event_id": "event_report",
                        "target_host": "host_report",
                        "due_at": "245-BCE-12-07T18:22:48+08:00",
                    },
                ],
            },
            "state/event/events-messages-and-movement.json": {"causal_events": {}},
        }

    def read(self, path: str):
        return self.docs[path]

    def _advance_runtime(self, target_text: str):
        target = CampaignTime.parse(target_text)
        runtime = self.docs["state/runtime.json"]
        runtime["world_time"] = str(target)
        if str(target) == "245-BCE-12-07T14:05:48+08:00":
            runtime["hosts"]["host_hidden"]["next_due"] = "245-BCE-12-08T14:05:48+08:00"
            runtime["events"][0]["due_at"] = "245-BCE-12-08T14:05:48+08:00"
        if str(target) == "245-BCE-12-07T18:22:48+08:00":
            runtime["hosts"]["host_report"]["next_due"] = None
            self.docs["state/event/events-messages-and-movement.json"]["causal_events"]["report_1"] = {
                "kind": "world_arc_report",
                "status": "triggered",
                "triggered_at": str(target),
            }
        return {
            "hosts_woken": 1,
            "events_processed": 1,
            "battlefield_reports": [],
            "battlefield_reviews": 0,
        }


class _BoundaryPlanner(DowntimeAdvanceMixin, _BoundaryBase):
    pass


def test_stop_on_player_event_halts_at_first_new_report():
    planner = _BoundaryPlanner()
    planner._downtime_stop_on_player_event = True
    result = planner._advance_runtime("245-BCE-12-14T12:05:48+08:00")

    assert planner.read("state/runtime.json")["world_time"] == "245-BCE-12-07T18:22:48+08:00"
    assert result["interrupted"] is True
    assert result["wake_required"] is False
    assert result["interrupt_reason"] == "player_facing_event"
    assert result["player_facing_event_refs"] == ["report_1"]


def test_event_bounded_outer_dispatch_commits_actual_reached_time(campaign, monkeypatch):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    meta = planner.read("state/meta.json")
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    reached = start.add_hours(3)

    def fake_advance(_target_text: str):
        runtime = deepcopy(planner.read("state/runtime.json"))
        runtime["world_time"] = str(reached)
        planner.put("state/runtime.json", runtime)
        return {
            "hosts_woken": 1,
            "events_processed": 1,
            "battlefield_reports": [],
            "battlefield_reviews": 0,
            "interrupted": True,
            "interrupt_reason": "player_facing_event",
        }

    monkeypatch.setattr(planner, "_advance_runtime", fake_advance)
    command = SimpleNamespace(expected_revision=int(meta["revision"]), request_id="test-event-bounded-outer")
    result = planner._dispatch_event_bounded_advance(
        command,
        {"hours": 24, "stop_on_player_event": True},
    )

    assert result["world_time"] == str(reached)
    assert result["requested_time"] == str(start.add_hours(24))
    assert result["interrupted"] is True
    assert planner.read("state/meta.json")["time"] == str(reached)
    assert planner.read("state/meta.json")["revision"] == int(meta["revision"]) + 1


def test_player_standing_plan_settles_only_configured_rate(campaign):
    player_path = Path(campaign) / "state/player.json"
    player = json.loads(player_path.read_text())
    player.setdefault("activity_contract", {})["verified_hours_per_7d"] = 42
    player_path.write_text(json.dumps(player, sort_keys=True, separators=(",", ":")) + "\n")

    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    end = start.add_hours(8)
    before = deepcopy(planner.read("state/player.json"))
    result = planner._settle_player_training(start, end, "test-standing-player")
    after = planner.read("state/player.json")

    assert result["status"] == "settled"
    assert result["settled_hours"] == 2
    assert after["development_state"]["settled_training_hours"] == int(before.get("development_state", {}).get("settled_training_hours", 0)) + 2
    assert after["training_history"][-1]["mode"] == "standing_downtime"


def test_controlled_formation_downtime_uses_house_training_regimen(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    end = start.add_hours(8)
    _path, before = planner._load_formation("formation_tang_champions_first")
    before_hours = int(before.get("verified_training_hours") or 0)

    result = planner._settle_formation_training(
        "formation_tang_champions_first",
        start,
        end,
        "test-standing-champions",
    )
    _path, after = planner._load_formation("formation_tang_champions_first")

    assert result["status"] == "settled"
    assert result["settled_hours"] == 2
    assert int(after.get("verified_training_hours") or 0) == before_hours + 2
    assert int(after.get("training_progress") or 0) >= 1


def test_household_person_downtime_accrues_without_authoring_skill_result(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    end = start.add_hours(8)
    _path, before = planner._exact_person("char_tang_ling", active=False)
    before_skills = deepcopy(before["skills"])

    result = planner._accrue_household_person_activity(
        "char_tang_ling",
        start,
        end,
        "test-standing-ling",
    )
    _path, after = planner._exact_person("char_tang_ling", active=False)

    assert result["status"] == "accrued_under_autonomous_contract"
    assert result["verified_activity_hours_in_current_cycle"] > 0
    assert result["skill_settlement_deferred_to_activity_host"] is True
    assert after["skills"] == before_skills
