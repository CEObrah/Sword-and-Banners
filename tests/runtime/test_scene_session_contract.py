import copy

from sword_runtime.api.interaction_surface import (
    apply_scene_action_record,
    fresh_runtime_projection,
    interaction_attempt_summary,
    record_interaction_attempt,
    scene_action_summary,
)
from sword_runtime.commands import CommandEnvelope
from sword_runtime.scene_sessions import (
    ACTIVE_SESSION_PATH,
    HISTORY_HEAD_PATH,
    INTERACTION_LEDGER_PATH,
    active_scene_session,
    attach_open_question,
    close_active_scene,
    start_scene_session,
)


class _Store:
    def __init__(self, records=None):
        self.records = copy.deepcopy(records or {})

    def read_optional(self, path):
        value = self.records.get(path)
        return copy.deepcopy(value) if value is not None else None

    def read(self, path):
        if path not in self.records:
            raise FileNotFoundError(path)
        return copy.deepcopy(self.records[path])

    def put(self, path, value):
        self.records[path] = copy.deepcopy(value)


def _command(command_type, payload, request_id):
    return CommandEnvelope(
        campaign_id="campaign",
        request_id=request_id,
        actor_id="char_tang_wei",
        command_type=command_type,
        expected_revision=7,
        submitted_at="245-BCE-12-05T19:22:00+08:00",
        payload=payload,
        mode="gameplay",
    )


def _open_council(store):
    return start_scene_session(
        store,
        session_ref="scene_session_council",
        kind="war_council",
        location_ref="loc_kanyou_command_hall",
        participant_refs=["char_tang_wei", "char_mou_gou"],
        started_at="245-BCE-12-05T18:22:00+08:00",
        process_ref="campaign_command_cycle_qin",
        purpose="Set Qin campaign command and entry authority.",
        agenda=["hierarchy", "intelligence", "entry authority"],
        soft_end_at="245-BCE-12-05T22:22:00+08:00",
    )


def test_question_answer_lifecycle_and_attributed_speech_are_non_mechanical():
    store = _Store({"state/player.json": {"location": "loc_kanyou_command_hall"}})
    session = _open_council(store)

    ask = _command(
        "interaction_action",
        {
            "target_ref": "char_mou_gou",
            "action": "ask",
            "player_statement": "What changes when entry authority arrives?",
            "topic": "entry_authority",
            "scopes": ["entry_authority", "assigned_role"],
        },
        "ask-entry-authority",
    )
    question_ref = record_interaction_attempt(
        store, interaction_attempt_summary(ask, ask.payload), at=ask.submitted_at
    )
    assert question_ref is not None
    assert question_ref in active_scene_session(store)["open_question_refs"]
    ledger_row = store.records[INTERACTION_LEDGER_PATH]["attempts"][0]
    assert ledger_row["thread_status"] == "open"
    assert ledger_row["scene_session_ref"] == session["session_ref"]

    answer = _command(
        "scene_session_action",
        {
            "action": "record_speech",
            "session_ref": session["session_ref"],
            "speaker_ref": "char_mou_gou",
            "statement": "Until that authority changes, your force stays concentrated and reports rather than crossing.",
            "speech_kind": "clarification",
            "basis_refs": ["campaign_command_cycle_qin"],
            "resolves_question_ref": question_ref,
        },
        "answer-entry-authority",
    )
    result = apply_scene_action_record(
        store, scene_action_summary(answer, answer.payload), at=answer.submitted_at
    )

    assert result["record_kind"] == "attributed_scene_speech"
    assert question_ref not in active_scene_session(store)["open_question_refs"]
    answered = store.records[INTERACTION_LEDGER_PATH]["attempts"][0]
    assert answered["thread_status"] == "answered"
    assert answered["response_ref"] == result["speech_ref"]
    recent = store.records[HISTORY_HEAD_PATH]["recent"][-1]
    assert recent["speech_ref"] == result["speech_ref"]
    assert recent["truth_status"] == "attributed_statement"
    assert recent["authority"] is False
    assert recent["mechanical_consequence_authority"] is False


def test_closing_scene_abandons_open_question_instead_of_leaving_recent_ask_active():
    store = _Store()
    session = _open_council(store)
    question_ref = "interaction_attempt_unanswered"
    attach_open_question(store, question_ref, at="245-BCE-12-05T19:00:00+08:00")
    store.put(
        INTERACTION_LEDGER_PATH,
        {
            "schema": "sword-interaction-attempt-ledger",
            "authority": False,
            "total_recorded": 1,
            "attempts": [
                {
                    "event_id": question_ref,
                    "action": "ask",
                    "player_statement": "What is my reserve role?",
                    "scene_session_ref": session["session_ref"],
                    "thread_status": "open",
                    "resolved_at": None,
                    "response_ref": None,
                }
            ],
        },
    )

    lifecycle = close_active_scene(
        store, at="245-BCE-12-05T20:00:00+08:00", reason="player_left"
    )

    assert lifecycle["abandoned_question_count"] == 1
    assert store.records[ACTIVE_SESSION_PATH]["status"] == "closed"
    row = store.records[INTERACTION_LEDGER_PATH]["attempts"][0]
    assert row["thread_status"] == "abandoned_with_scene_close"
    assert row["response_ref"] is None


def test_no_active_scene_means_no_active_questions_projection():
    attempts = [
        {
            "event_id": "interaction_attempt_old_open",
            "at": "245-BCE-12-05T19:22:00+08:00",
            "target_ref": "char_mou_gou",
            "action": "ask",
            "player_statement": "What is my role?",
            "scene_session_ref": "scene_session_old",
            "thread_status": "open",
        }
    ]
    context = {
        "campaign": {"world_time": "245-BCE-12-05T19:22:00+08:00", "revision": 7},
        "player": {"location": "loc_kanyou_command_hall", "health": {}, "fatigue": {}},
        "controlled_formations": [],
        "active_scene_session": None,
    }

    projection = fresh_runtime_projection(context, [], attempts)

    assert projection["active_questions"] == []


def test_scene_close_rebounds_abandoned_threads_into_bounded_hot_routing_history():
    store = _Store()
    session = _open_council(store)
    rows = []
    question_refs = []
    for index in range(140):
        ref = f"interaction_attempt_q_{index:03d}"
        question_refs.append(ref)
        rows.append(
            {
                "event_id": ref,
                "action": "ask",
                "player_statement": f"Question {index}?",
                "scene_session_ref": session["session_ref"],
                "thread_status": "open",
                "resolved_at": None,
                "response_ref": None,
            }
        )
    store.records[ACTIVE_SESSION_PATH]["open_question_refs"] = question_refs
    store.put(
        INTERACTION_LEDGER_PATH,
        {
            "schema": "sword-interaction-attempt-ledger",
            "authority": False,
            "total_recorded": len(rows),
            "attempts": rows,
        },
    )

    lifecycle = close_active_scene(
        store, at="245-BCE-12-05T20:00:00+08:00", reason="completed"
    )

    assert lifecycle["abandoned_question_count"] == 140
    bounded = store.records[INTERACTION_LEDGER_PATH]["attempts"]
    assert len(bounded) == 128
    assert all(row["thread_status"] == "abandoned_with_scene_close" for row in bounded)
