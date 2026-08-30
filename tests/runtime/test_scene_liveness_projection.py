from __future__ import annotations

from sword_runtime.api.interaction_surface import fresh_runtime_projection
from sword_runtime.api.stable_operations import (
    _campaign_command_present_refs,
    _compact_interaction_attempts,
    _project_active_session_presence,
)


class _PresenceStore:
    def __init__(self):
        self.rows = {
            "state/index/owner-index.json": {"owners": {
                "char_stays": "state/char/stays.json",
                "char_left": "state/char/left.json",
            }},
            "state/char/stays.json": {"current_location": "loc_hall"},
            "state/char/left.json": {"current_location": "loc_road"},
        }

    def read_json(self, path):
        if path not in self.rows:
            raise FileNotFoundError(path)
        return self.rows[path]


def test_open_war_council_attendees_remain_present_after_start_instant():
    handles = [{
        "interaction_ref": "event_council",
        "kind": "campaign_command_council",
        "triggered_at": "244-BCE-09-17T18:22:48+08:00",
        "campaign_command_cycle_ref": "cycle_qin",
        "delivery": {"location_ref": "loc_kanyou"},
        "present_person_refs": ["char_mou_gou", "char_shou_hei_kun"],
    }]
    runtime = {
        "hosts": {
            "host_return": {
                "kind": "campaign_command_council_return",
                "cycle_ref": "cycle_qin",
                "next_due": "244-BCE-09-17T22:22:48+08:00",
            }
        }
    }

    active_session = {
        "session_ref": "scene_session_council",
        "status": "active",
        "kind": "war_council",
        "process_ref": "cycle_qin",
    }
    assert _campaign_command_present_refs(
        handles,
        current_time="244-BCE-09-17T19:22:48+08:00",
        player_location="loc_kanyou",
        runtime=runtime,
        active_session=active_session,
    ) == {"char_mou_gou", "char_shou_hei_kun"}

    runtime["hosts"] = {}
    assert _campaign_command_present_refs(
        handles,
        current_time="244-BCE-09-17T22:22:48+08:00",
        player_location="loc_kanyou",
        runtime=runtime,
        active_session=active_session,
    ) == set()


def test_one_departed_attendee_does_not_erase_remaining_live_conversation():
    session = {
        "session_ref": "scene_session_test",
        "status": "active",
        "kind": "council",
        "location_ref": "loc_hall",
        "participant_refs": ["char_tang_wei", "char_stays", "char_left"],
        "open_thread_refs": ["thread_1"],
    }
    projected = _project_active_session_presence(
        _PresenceStore(), session, player_id="char_tang_wei", player_location="loc_hall"
    )
    assert projected is not None
    assert projected["participant_refs"] == ["char_tang_wei", "char_stays"]
    assert projected["physically_absent_participant_refs"] == ["char_left"]
    assert projected["open_thread_refs"] == ["thread_1"]


def test_one_on_one_scene_disappears_when_only_other_participant_left():
    session = {
        "session_ref": "scene_session_test",
        "status": "active",
        "kind": "conversation",
        "location_ref": "loc_hall",
        "participant_refs": ["char_tang_wei", "char_left"],
    }
    assert _project_active_session_presence(
        _PresenceStore(), session, player_id="char_tang_wei", player_location="loc_hall"
    ) is None


def test_interaction_compaction_keeps_player_authored_question_and_posture_only():
    compact = _compact_interaction_attempts([{
        "event_id": "interaction_attempt_test",
        "at": "244-BCE-09-17T18:22:48+08:00",
        "action": "ask",
        "target_ref": "char_mou_gou",
        "player_statement": "What is your intended opening plan?",
        "posture": "Ask directly during the council.",
        "world_response_status": "not_established_by_attempt",
    }])
    assert compact == [{
        "event_id": "interaction_attempt_test",
        "at": "244-BCE-09-17T18:22:48+08:00",
        "action": "ask",
        "target_ref": "char_mou_gou",
        "player_statement": "What is your intended opening plan?",
        "posture": "Ask directly during the council.",
    }]


def test_fresh_projection_exposes_pending_player_question_for_reversible_reply():
    context = {
        "campaign": {
            "world_time": "244-BCE-09-17T19:22:48+08:00",
            "revision": 5,
        },
        "player": {
            "location": "loc_kanyou",
            "health": "healthy",
            "fatigue": 3,
        },
        "controlled_formations": [],
    }
    attempts = [{
        "event_id": "interaction_attempt_test",
        "at": "244-BCE-09-17T18:22:48+08:00",
        "action": "ask",
        "target_ref": "char_mou_gou",
        "player_statement": "What is your intended opening plan?",
        "scene_session_ref": "scene_session_council",
        "thread_status": "open",
    }]
    context["active_scene_session"] = {
        "session_ref": "scene_session_council",
        "status": "active",
        "kind": "war_council",
        "process_ref": "cycle_qin",
    }

    projection = fresh_runtime_projection(context, [], attempts)

    assert projection["active_questions"] == [{
        "event_id": "interaction_attempt_test",
        "at": "244-BCE-09-17T18:22:48+08:00",
        "target_ref": "char_mou_gou",
        "player_statement": "What is your intended opening plan?",
        "scene_session_ref": "scene_session_council",
    }]
