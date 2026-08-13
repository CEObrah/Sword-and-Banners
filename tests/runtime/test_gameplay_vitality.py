from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sword_runtime.api.gameplay_vitality import (
    VitalityCampaignOperations,
    build_player_opportunities,
    build_scene_vitality,
    translate_continuation_command,
)
from sword_runtime.campaign_event_planner import _player_facing_event_wake
from sword_runtime.commands import CommandEnvelope
from sword_runtime.service_runtime import ProductionSwordRuntime


class _ProjectionStore:
    def __init__(self):
        self.docs = {
            "state/index/owner-index-gold.json": {
                "owners": {
                    "char_near": "state/char/near.json",
                    "char_far": "state/char/far.json",
                    "char_hidden": "state/char/hidden.json",
                }
            },
            "state/char/near.json": {"location": "loc_manor"},
            "state/char/far.json": {"location": "loc_kanyou"},
            "state/char/hidden.json": {"location": "loc_manor"},
        }

    def read_json(self, path):
        return self.docs[path]


class _WakePlanner:
    def __init__(self, event):
        self.event = event

    def owner_path(self, owner_ref):
        assert owner_ref == "events_messages_and_movement"
        return "state/event/events-messages-and-movement.json"

    def read(self, path):
        assert path == "state/event/events-messages-and-movement.json"
        return {"causal_events": {self.event["event_ref"]: self.event}}


def test_scene_vitality_uses_only_permitted_exact_people() -> None:
    context = {
        "campaign": {"player_id": "char_player"},
        "player": {"location": "loc_manor"},
        "scene": {},
        "permitted_person_ids": ["char_player", "char_near", "char_far"],
    }
    projected = build_scene_vitality(context, _ProjectionStore())
    cast = projected["scene_cast"]
    assert cast["present_people"] == []
    assert cast["nearby_people"] == ["char_near"]
    assert cast["referenced_people"] == ["char_far"]
    assert "char_hidden" not in cast["nearby_people"]
    assert projected["scene_vitality"]["ephemeral_motion_allowed"] is True


def test_opportunities_route_reports_and_suppress_addressed_handles() -> None:
    context = {
        "interaction_handles": [
            {"interaction_ref": "event_report", "kind": "world_arc_report", "summary": "report"},
            {"interaction_ref": "event_reply", "kind": "institutional_response", "summary": "reply"},
        ],
        "interaction_handles_count": 2,
        "recent_interaction_attempts": [{"target_ref": "event_reply", "process_ref": None}],
    }
    projected = build_player_opportunities(context)
    assert projected["opportunities_count"] == 1
    assert projected["opportunities"][0]["interaction_ref"] == "event_report"
    assert projected["opportunities"][0]["kind"] == "strategic_report"


def test_continuation_translation_is_deterministic_and_reuses_advance_time() -> None:
    command = CommandEnvelope(
        campaign_id="campaign",
        request_id="continue-once",
        actor_id="char_tang_wei",
        command_type="advance_until_event",
        expected_revision=9,
        submitted_at="245-BCE-12-05T06:22:48+08:00",
        payload={},
        mode="gameplay",
    )
    first = translate_continuation_command(command)
    second = translate_continuation_command(command)
    assert first.command_type == "advance_time"
    assert first.payload["hours"] == 720
    assert first.digest == second.digest


def test_player_facing_event_wake_ignores_noninteractive_calendar_boundary() -> None:
    interactive = {
        "event_ref": "event_message",
        "kind": "message",
        "status": "triggered",
        "triggered_at": "245-BCE-12-05T07:00:00+08:00",
        "summary": "A message arrives.",
    }
    wake = _player_facing_event_wake(
        _WakePlanner(interactive),
        owner_ref="events_messages_and_movement",
        event_ref="event_message",
        at=interactive["triggered_at"],
    )
    assert wake is not None
    assert wake["campaign_event_ref"] == "event_message"

    calendar = {
        "event_ref": "event_calendar",
        "kind": "calendar_boundary",
        "status": "triggered",
        "triggered_at": "245-BCE-12-05T07:00:00+08:00",
        "summary": "A known date boundary is reached.",
    }
    assert _player_facing_event_wake(
        _WakePlanner(calendar),
        owner_ref="events_messages_and_movement",
        event_ref="event_calendar",
        at=calendar["triggered_at"],
    ) is None


def test_advance_until_event_stops_on_new_player_facing_campaign_event(campaign: Path) -> None:
    meta = json.loads((campaign / "state/meta.json").read_text(encoding="utf-8"))
    work_path = campaign / "state/index/campaign-causal-work.json"
    work = {
        "authority": False,
        "purpose": "gameplay vitality regression",
        "targets": [
            {
                "work_ref": "event_vitality_message",
                "source_owner_ref": "events_messages_and_movement",
                "kind": "message",
                "due_at": meta["time"],
                "priority": 1,
                "status": "pending",
                "effect": {"summary": "A lawful player-facing message reaches Tang Wei."},
                "wake": False,
            }
        ],
    }
    work_path.write_text(json.dumps(work, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(campaign), "add", "state/index/campaign-causal-work.json"], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "-q", "-m", "test: add vitality event"], check=True)

    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-vitality")
    operations = VitalityCampaignOperations(runtime)
    context = operations.play_context()
    assert "advance_until_event" in context["commands"]["supported_command_types"]
    assert "scene_cast" in context
    assert "scene_vitality" in context
    assert "opportunities" in context

    command = CommandEnvelope(
        campaign_id=meta["campaign_id"],
        request_id="vitality.advance-until-event",
        actor_id=meta["player_id"],
        command_type="advance_until_event",
        expected_revision=meta["revision"],
        submitted_at=meta["time"],
        payload={"hours": 24},
        mode="gameplay",
    )
    receipt = operations.execute_command(command)
    assert receipt["surface_command_type"] == "advance_until_event"
    assert receipt["result"]["wake_required"] is True
    assert receipt["result"]["world_time"] == meta["time"]

    after = operations.play_context()
    assert after["pending_wake"]["campaign_event_ref"] == "event_vitality_message"
    refs = {item["interaction_ref"] for item in after["opportunities"]}
    assert "event_vitality_message" in refs
