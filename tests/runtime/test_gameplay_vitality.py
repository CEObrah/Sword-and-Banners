from __future__ import annotations

from sword_runtime.api.gameplay_vitality import (
    build_player_opportunities,
    build_scene_vitality,
    translate_continuation_command,
)
from sword_runtime.commands import CommandEnvelope


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


def test_continuation_rejects_ambiguous_or_invalid_horizons() -> None:
    base = {
        "campaign_id": "campaign",
        "request_id": "continue-invalid",
        "actor_id": "char_tang_wei",
        "command_type": "advance_until_event",
        "expected_revision": 9,
        "submitted_at": "245-BCE-12-05T06:22:48+08:00",
        "mode": "gameplay",
    }
    for payload in (
        {"hours": 1, "target_time": "245-BCE-12-06T06:22:48+08:00"},
        {"hours": 0},
        {"hours": True},
        {"unexpected": 1},
    ):
        command = CommandEnvelope(payload=payload, **base)
        try:
            translate_continuation_command(command)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid continuation payload accepted: {payload!r}")
