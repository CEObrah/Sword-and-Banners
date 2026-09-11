import copy

from sword_runtime.api.interaction_surface import (
    active_scene_interaction_attempts,
    active_scene_thread_page,
    apply_scene_action_record,
    fresh_runtime_projection,
    interaction_attempt_summary,
    recent_interaction_attempts,
    record_interaction_attempt,
    scene_action_summary,
    validate_scene_action_payload,
)
from sword_runtime.commands import CommandEnvelope
from sword_runtime.scene_sessions import (
    ACTIVE_SESSION_PATH,
    HISTORY_HEAD_PATH,
    INTERACTION_LEDGER_PATH,
    active_scene_session,
    abandon_session_threads,
    attach_open_question,
    close_active_scene,
    record_attributed_speech,
    record_scene_fact,
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


def test_response_bearing_request_is_generic_open_thread_and_can_be_resolved_by_attributed_speech():
    store = _Store({"state/player.json": {"location": "loc_kanyou_command_hall"}})
    session = _open_council(store)
    request = _command(
        "interaction_action",
        {
            "target_ref": "char_mou_gou",
            "action": "request",
            "player_statement": "Give my army the forward duty.",
            "topic": "campaign_command:vanguard_assignment",
        },
        "request-forward-duty",
    )
    thread_ref = record_interaction_attempt(
        store, interaction_attempt_summary(request, request.payload), at=request.submitted_at
    )
    active = active_scene_session(store)
    assert thread_ref in active["open_thread_refs"]
    assert thread_ref not in active["open_question_refs"]
    row = store.records[INTERACTION_LEDGER_PATH]["attempts"][-1]
    assert row["thread_kind"] == "conversation"
    assert row["thread_status"] == "open"

    response = _command(
        "scene_session_action",
        {
            "action": "record_speech",
            "session_ref": session["session_ref"],
            "speaker_ref": "char_mou_gou",
            "statement": "I heard you. I have not assigned the forward duty yet.",
            "speech_kind": "nonbinding_response",
            "basis_refs": ["campaign_command_cycle_qin"],
            "resolves_thread_ref": thread_ref,
        },
        "respond-forward-duty",
    )
    result = apply_scene_action_record(store, scene_action_summary(response, response.payload), at=response.submitted_at)
    resolved = store.records[INTERACTION_LEDGER_PATH]["attempts"][-1]
    assert resolved["thread_status"] == "responded"
    assert resolved["response_ref"] == result["speech_ref"]


def test_active_scene_threads_survive_generic_recent_attempt_window_eviction():
    session_ref = "scene_session_live"
    old_thread = {
        "event_id": "thread_old",
        "actor_id": "char_tang_wei",
        "at": "245-BCE-12-05T19:00:00+08:00",
        "action": "request",
        "target_ref": "char_mou_gou",
        "player_statement": "Keep this request open while we discuss the rest.",
        "scene_session_ref": session_ref,
        "thread_kind": "conversation",
        "thread_status": "open",
    }
    later = [
        {
            "event_id": f"later_{index:02d}",
            "actor_id": "char_tang_wei",
            "at": f"245-BCE-12-05T19:{index + 1:02d}:00+08:00",
            "action": "decline",
            "target_ref": "char_mou_gou",
            "scene_session_ref": session_ref,
            "thread_status": "not_applicable",
        }
        for index in range(9)
    ]
    store = _Store({
        INTERACTION_LEDGER_PATH: {
            "schema": "sword-interaction-attempt-ledger",
            "authority": False,
            "total_recorded": 10,
            "attempts": [old_thread, *later],
        }
    })
    session = {
        "session_ref": session_ref,
        "open_thread_refs": ["thread_old"],
        "open_thread_count": 1,
    }

    recent, _ = recent_interaction_attempts(store, "char_tang_wei")
    assert "thread_old" not in {row["event_id"] for row in recent}

    active, total, truncated = active_scene_interaction_attempts(
        store, "char_tang_wei", session
    )
    assert [row["event_id"] for row in active] == ["thread_old"]
    assert total == 1
    assert truncated is False


def test_departed_participant_thread_remains_durable_but_is_not_hot_answerable():
    session_ref = "scene_session_live"
    store = _Store({
        INTERACTION_LEDGER_PATH: {
            "schema": "sword-interaction-attempt-ledger",
            "authority": False,
            "total_recorded": 2,
            "attempts": [
                {
                    "event_id": "thread_stays",
                    "actor_id": "char_tang_wei",
                    "at": "245-BCE-12-05T19:01:00+08:00",
                    "action": "ask",
                    "target_ref": "char_stays",
                    "player_statement": "What do you think?",
                    "scene_session_ref": session_ref,
                    "thread_status": "open",
                },
                {
                    "event_id": "thread_left",
                    "actor_id": "char_tang_wei",
                    "at": "245-BCE-12-05T19:02:00+08:00",
                    "action": "request",
                    "target_ref": "char_left",
                    "player_statement": "Bring the ledger back.",
                    "scene_session_ref": session_ref,
                    "thread_status": "open",
                },
            ],
        }
    })
    projected_session = {
        "session_ref": session_ref,
        "participant_refs": ["char_tang_wei", "char_stays"],
        "physically_absent_participant_refs": ["char_left"],
        "open_thread_refs": ["thread_stays", "thread_left"],
        "open_thread_count": 2,
    }

    active, total, truncated = active_scene_interaction_attempts(
        store, "char_tang_wei", projected_session
    )

    assert [row["event_id"] for row in active] == ["thread_stays"]
    assert total == 1
    assert truncated is False
    assert projected_session["open_thread_refs"] == ["thread_stays", "thread_left"]


def test_fresh_projection_prioritizes_newest_open_threads_and_reports_truncation():
    context = {
        "campaign": {"world_time": "245-BCE-12-05T19:22:00+08:00", "revision": 7},
        "player": {"location": "loc_kanyou_command_hall", "health": {}, "fatigue": {}},
        "controlled_formations": [],
        "active_scene_session": {
            "session_ref": "scene_session_live",
            "open_thread_count": 20,
        },
    }
    attempts = [
        {
            "event_id": f"thread_{index:02d}",
            "at": f"245-BCE-12-05T19:{index:02d}:00+08:00",
            "action": "request",
            "player_statement": f"Request {index}",
            "scene_session_ref": "scene_session_live",
            "thread_status": "open",
        }
        for index in range(20)
    ]

    projection = fresh_runtime_projection(context, [], attempts)

    assert len(projection["active_threads"]) == 16
    assert projection["active_threads"][0]["event_id"] == "thread_19"
    assert projection["active_threads"][-1]["event_id"] == "thread_04"
    assert projection["active_thread_count"] == 20
    assert projection["active_threads_truncated"] is True


def test_active_scene_thread_page_recovers_older_threads_hidden_by_hot_window():
    session_ref = "scene_session_long_council"
    refs = [f"thread_{index:02d}" for index in range(20)]
    attempts = [
        {
            "event_id": ref,
            "actor_id": "char_tang_wei",
            "at": f"245-BCE-12-05T19:{index:02d}:00+08:00",
            "action": "request",
            "target_ref": "char_mou_gou",
            "player_statement": f"Request {index}",
            "scene_session_ref": session_ref,
            "thread_status": "open",
            "thread_kind": "conversation",
        }
        for index, ref in enumerate(refs)
    ]
    store = _Store({
        ACTIVE_SESSION_PATH: {
            "schema": "sword-scene-session",
            "session_ref": session_ref,
            "status": "active",
            "open_thread_refs": refs,
        },
        INTERACTION_LEDGER_PATH: {
            "schema": "sword-interaction-attempt-ledger",
            "authority": False,
            "total_recorded": len(attempts),
            "attempts": attempts,
        },
    })

    first = active_scene_thread_page(store)
    assert first["count"] == 20
    assert [row["event_id"] for row in first["threads"]] == refs[:16]
    assert first["truncated"] is True
    assert first["next_cursor"] == "16"
    second = active_scene_thread_page(store, cursor=first["next_cursor"])
    assert [row["event_id"] for row in second["threads"]] == refs[16:]
    assert second["truncated"] is False


def test_fresh_projection_exposes_generic_threads_and_question_compatibility_subset():
    context = {
        "campaign": {"world_time": "245-BCE-12-05T19:22:00+08:00", "revision": 7},
        "player": {"location": "loc_kanyou_command_hall", "health": {}, "fatigue": {}},
        "controlled_formations": [],
        "active_scene_session": {"session_ref": "scene_session_live"},
    }
    attempts = [
        {"event_id": "request_1", "action": "request", "player_statement": "Let me lead.", "scene_session_ref": "scene_session_live", "thread_status": "open"},
        {"event_id": "ask_1", "action": "ask", "player_statement": "Why?", "scene_session_ref": "scene_session_live", "thread_status": "open"},
    ]
    projection = fresh_runtime_projection(context, [], attempts)
    assert [row["event_id"] for row in projection["active_threads"]] == ["request_1", "ask_1"]
    assert [row["event_id"] for row in projection["active_questions"]] == ["ask_1"]


def test_response_bearing_person_interaction_auto_opens_lightweight_conversation_session():
    store = _Store({
        "state/player.json": {"location": "loc_kanyou_command_hall"},
        "state/index/owner-index.json": {
            "owners": {"char_mou_gou": "state/char/mou-gou.json"}
        },
        "state/char/mou-gou.json": {"current_location": "loc_kanyou_command_hall"},
    })
    request = _command(
        "interaction_action",
        {
            "target_ref": "char_mou_gou",
            "action": "request",
            "player_statement": "Can my army take the forward duty?",
            "topic": "campaign_command:vanguard_assignment",
        },
        "auto-open-forward-duty",
    )

    thread_ref = record_interaction_attempt(
        store, interaction_attempt_summary(request, request.payload), at=request.submitted_at
    )

    session = active_scene_session(store)
    assert session is not None
    assert session["kind"] == "conversation"
    assert session["participant_refs"] == ["char_tang_wei", "char_mou_gou"]
    assert thread_ref in session["open_thread_refs"]
    row = store.records[INTERACTION_LEDGER_PATH]["attempts"][-1]
    assert row["scene_session_ref"] == session["session_ref"]
    assert row["thread_status"] == "open"


def test_response_bearing_remote_interaction_does_not_fake_face_to_face_session():
    store = _Store({
        "state/player.json": {"location": "loc_kanyou_command_hall"},
        "state/index/owner-index.json": {
            "owners": {"char_mou_gou": "state/char/mou-gou.json"}
        },
        "state/char/mou-gou.json": {"current_location": "loc_frontier_headquarters"},
    })
    request = _command(
        "interaction_action",
        {
            "target_ref": "char_mou_gou",
            "action": "request",
            "player_statement": "Send me your decision when you have it.",
            "topic": "campaign_command:remote_request",
        },
        "remote-request-no-session",
    )

    thread_ref = record_interaction_attempt(
        store, interaction_attempt_summary(request, request.payload), at=request.submitted_at
    )

    assert thread_ref is not None
    assert active_scene_session(store) is None
    row = store.records[INTERACTION_LEDGER_PATH]["attempts"][-1]
    assert row["scene_session_ref"] is None
    assert row["thread_status"] == "not_applicable"



def test_salient_reversible_scene_fact_persists_without_mechanical_authority():
    store = _Store({"state/player.json": {"location": "loc_kanyou_command_hall"}})
    session = _open_council(store)
    established = _command(
        "scene_session_action",
        {
            "action": "record_fact",
            "session_ref": session["session_ref"],
            "actor_ref": "char_tang_wei",
            "fact_kind": "object_state",
            "description": "A bronze bowl is already on the council table within Tang Wei's reach.",
            "participant_refs": ["char_mou_gou"],
            "basis_refs": [],
            "improvised_prop": {"form": "small_rigid", "material": "metal", "condition": "intact"},
        },
        "establish-bowl-scene-fact",
    )
    established_result = apply_scene_action_record(
        store, scene_action_summary(established, established.payload), at=established.submitted_at
    )
    action = _command(
        "scene_session_action",
        {
            "action": "record_fact",
            "session_ref": session["session_ref"],
            "actor_ref": "char_tang_wei",
            "fact_kind": "object_state",
            "description": "Tang Wei lifts the already-established bronze bowl and sets it on Mou Gou's head.",
            "participant_refs": ["char_mou_gou"],
            "basis_refs": [established_result["fact_ref"]],
            "improvised_prop": {"form": "small_rigid", "material": "metal", "condition": "intact"},
        },
        "record-bowl-scene-fact",
    )

    result = apply_scene_action_record(
        store, scene_action_summary(action, action.payload), at=action.submitted_at
    )

    assert result["record_kind"] == "reversible_scene_fact"
    row = store.records[HISTORY_HEAD_PATH]["recent"][-1]
    assert row["fact_ref"] == result["fact_ref"]
    assert row["fact_kind"] == "object_state"
    assert row["truth_status"] == "observed_reversible_scene_fact"
    assert row["scope"] == "scene_local_history_only"
    assert row["authority"] is False
    assert row["mechanical_consequence_authority"] is False
    assert row["basis_refs"] == [established_result["fact_ref"]]
    assert row["source_object_fact_ref"] == established_result["fact_ref"]
    assert row["improvised_prop"] == {
        "kind": "mundane_improvised_prop",
        "form": "small_rigid",
        "material": "metal",
        "condition": "intact",
    }
    assert active_scene_session(store)["session_ref"] == session["session_ref"]


def test_improvised_prop_classification_is_bounded_and_object_state_only():
    store = _Store({"state/player.json": {"location": "loc_kanyou_command_hall"}})
    session = _open_council(store)
    base = {
        "action": "record_fact",
        "session_ref": session["session_ref"],
        "actor_ref": "char_tang_wei",
        "description": "Tang Wei has the already-established bowl in hand.",
        "participant_refs": [],
        "basis_refs": [],
        "improvised_prop": {"form": "small_rigid", "material": "metal", "condition": "intact"},
    }
    import pytest
    with pytest.raises(ValueError, match="requires object_state"):
        validate_scene_action_payload({**base, "fact_kind": "local_action"})
    with pytest.raises(ValueError, match="unsupported caller fields"):
        validate_scene_action_payload({**base, "fact_kind": "object_state", "mass_kg": 12.0})
    with pytest.raises(ValueError, match="improvised_prop is invalid"):
        validate_scene_action_payload({**base, "fact_kind": "object_state", "improvised_prop": {**base["improvised_prop"], "damage": 999}})
    source = record_scene_fact(
        store,
        surface_digest="descriptor-only-prop",
        at="245-BCE-12-05T19:00:01+08:00",
        actor_ref="char_tang_wei",
        summary="A ceramic cup is visibly present on the table.",
        fact_kind="object_state",
        session_ref=session["session_ref"],
        improvised_prop={"kind": "mundane_improvised_prop", "form": "small_rigid", "material": "ceramic", "condition": "intact"},
    )
    assert source["basis_refs"] == []
    assert "source_object_fact_ref" not in source
    with pytest.raises(ValueError, match="does not match prior object_state descriptor"):
        record_scene_fact(
            store,
            surface_digest="swapped-prop-classification",
            at="245-BCE-12-05T19:00:02+08:00",
            actor_ref="char_tang_wei",
            summary="Tang Wei claims the established cup is now a heavy metal bar.",
            fact_kind="object_state",
            session_ref=session["session_ref"],
            basis_refs=[source["fact_ref"]],
            improvised_prop={"kind": "mundane_improvised_prop", "form": "heavy_rigid", "material": "metal", "condition": "intact"},
        )


def test_targeted_speak_defaults_to_live_conversational_thread():
    store = _Store({
        "state/player.json": {"location": "loc_kanyou_command_hall"},
        "state/index/owner-index.json": {"owners": {"char_mou_gou": "state/char/mou-gou.json"}},
        "state/char/mou-gou.json": {"current_location": "loc_kanyou_command_hall"},
    })
    speak = _command(
        "interaction_action",
        {
            "target_ref": "char_mou_gou",
            "action": "speak",
            "player_statement": "You knew I wanted the forward duty before this council began.",
            "topic": "accusation",
        },
        "speak-thread-default",
    )
    thread_ref = record_interaction_attempt(
        store, interaction_attempt_summary(speak, speak.payload), at=speak.submitted_at
    )
    active = active_scene_session(store)
    row = store.records[INTERACTION_LEDGER_PATH]["attempts"][-1]
    assert row["expects_response"] is True
    assert row["thread_status"] == "open"
    assert row["thread_kind"] == "conversation"
    assert thread_ref in active["open_thread_refs"]


def test_scene_history_basis_refs_must_belong_to_active_session_scope():
    store = _Store()
    session = _open_council(store)
    with __import__("pytest").raises(ValueError, match="basis_ref is not visible"):
        record_attributed_speech(
            store,
            surface_digest="digest-speech-hidden-basis",
            at="245-BCE-12-05T19:23:00+08:00",
            speaker_ref="char_mou_gou",
            statement="I have considered it.",
            speech_kind="nonbinding_response",
            session_ref=session["session_ref"],
            basis_refs=["secret_owner_that_is_not_in_the_scene"],
        )
    with __import__("pytest").raises(ValueError, match="basis_ref is not visible"):
        record_scene_fact(
            store,
            surface_digest="digest-fact-hidden-basis",
            at="245-BCE-12-05T19:24:00+08:00",
            actor_ref="char_tang_wei",
            summary="Wei shifts the established cup nearer the map.",
            fact_kind="object_state",
            session_ref=session["session_ref"],
            participant_refs=["char_mou_gou"],
            basis_refs=["secret_owner_that_is_not_in_the_scene"],
        )


def test_explicit_no_response_suppresses_default_speak_thread():
    store = _Store({
        "state/player.json": {"location": "loc_kanyou_command_hall"},
        "state/index/owner-index.json": {"owners": {"char_mou_gou": "state/char/mou-gou.json"}},
        "state/char/mou-gou.json": {"current_location": "loc_kanyou_command_hall"},
    })
    speak = _command(
        "interaction_action",
        {"target_ref": "char_mou_gou", "action": "speak", "player_statement": "Enough. We're done here.", "expects_response": False},
        "speak-no-thread",
    )
    record_interaction_attempt(store, interaction_attempt_summary(speak, speak.payload), at=speak.submitted_at)
    assert active_scene_session(store) is None
    row = store.records[INTERACTION_LEDGER_PATH]["attempts"][-1]
    assert row["expects_response"] is False
    assert row["thread_status"] == "not_applicable"


def test_legacy_thread_normalization_honors_explicit_no_response():
    store = _Store()
    session = _open_council(store)
    store.records[INTERACTION_LEDGER_PATH] = {
        "attempts": [{
            "attempt_ref": "attempt:legacy-final-statement",
            "scene_session_ref": session["session_ref"],
            "target_ref": "char_mou_gou",
            "action": "speak",
            "player_statement": "Enough. We're done here.",
            "expects_response": False,
        }]
    }
    abandoned = abandon_session_threads(store, session["session_ref"], at="245-BCE-12-05T19:25:00+08:00")
    assert abandoned == 0
    row = store.records[INTERACTION_LEDGER_PATH]["attempts"][-1]
    assert row["expects_response"] is False
    assert row["thread_status"] == "not_applicable"
    assert row["resolved_at"] is None
