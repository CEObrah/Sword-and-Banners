import copy
import json

from sword_runtime.api.command_discovery import compact_play_context
from sword_runtime.api.gm_scene_context import build_gm_scene_context
from sword_runtime.api.interaction_surface import SCENE_ACTION_PREFIX, apply_scene_action_record
from sword_runtime.battle_command import _objective_posture
from sword_runtime.campaign_command_decision import _mission_order
from sword_runtime.operational_intent import operational_intent_contract
from sword_runtime.scene_sessions import (
    ACTIVE_SESSION_PATH,
    HISTORY_HEAD_PATH,
    record_attributed_speech,
    record_continuity_note,
    relevant_scene_continuity,
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


def test_legacy_contact_development_is_information_mission_not_general_attack():
    operation = {
        "campaign_phase": "contact_development",
        "campaign_commander_ref": "char_mou_gou",
        "campaign_participant_operation_refs": ["operation.main_body", "operation.reserve"],
        "objective": "Advance toward the enemy and develop contact before reporting.",
    }

    contract = operational_intent_contract(operation, None)

    assert contract["operational_intent"] == "develop_contact"
    assert contract["deliberate_battle_commitment_authorized"] is False
    assert contract["contact_is_not_synonymous_with_battle"] is True
    assert contract["independent_detachment"] is False
    assert contract["field_command_relationship"] == "campaign_subordinate_component"
    assert contract["campaign_commander_ref"] == "char_mou_gou"
    assert _objective_posture(operation) == "neutral"


def test_new_follow_on_contact_order_explicitly_preserves_parent_campaign_support():
    operation = {
        "location_ref": "loc_forward_camp",
        "institutional_owner_ref": "state_qin",
        "campaign_commander_ref": "char_mou_gou",
        "campaign_participant_operation_refs": ["operation.main_body", "operation.reserve"],
    }
    cycle = {
        "supreme_commander_ref": "char_mou_gou",
        "coordination_authority_ref": "char_mou_gou",
    }
    base_order = {
        "order_ref": "operational_order_base",
        "issuer_ref": "char_mou_gou",
        "mission_packet": {
            "strategic_target_ref": "loc_enemy_axis",
            "strategic_target_name": "enemy axis",
            "destination_ref": "loc_forward_camp",
            "destination_name": "forward camp",
        },
        "applies_to_formation_refs": ["formation.tang_wei.vanguard"],
        "excluded_non_state_formation_refs": [],
    }

    order = _mission_order(
        operation,
        cycle,
        base_order,
        at="244-BCE-09-30T06:00:00+08:00",
        information_refs=["information.scout_report"],
        request_refs=[],
        signature="contacttest",
    )
    packet = order["mission_packet"]

    assert packet["operational_intent"] == "develop_contact"
    assert packet["battle_commitment_authorized"] is False
    assert packet["independent_detachment"] is False
    assert "parent army" in packet["support_continuity_rule"]
    assert "general-attack" in order["objective"]
    assert "not contained" in order["follow_on_requirement"]


def test_literary_continuity_is_evidence_cited_soft_memory_and_survives_hot_history_churn():
    store = _Store()
    session = start_scene_session(
        store,
        session_ref="scene_session_memory",
        kind="conversation",
        location_ref="loc_tang_manor",
        participant_refs=["char_tang_wei", "char_mou_gou"],
        started_at="245-BCE-12-05T18:00:00+08:00",
        purpose="Discuss the campaign.",
    )
    speech = record_attributed_speech(
        store,
        surface_digest="memory-basis",
        at="245-BCE-12-05T18:01:00+08:00",
        speaker_ref="char_mou_gou",
        statement="Stay close enough that my center can still reach you.",
        speech_kind="advice",
        session_ref=session["session_ref"],
    )
    note = record_continuity_note(
        store,
        surface_digest="memory-note",
        at="245-BCE-12-05T18:02:00+08:00",
        summary="Mou Gou tends to express concern about Wei through practical command-distance warnings.",
        continuity_kind="relationship_expression",
        session_ref=session["session_ref"],
        subject_refs=["char_mou_gou"],
        basis_refs=[speech["speech_ref"]],
    )

    for index in range(70):
        record_attributed_speech(
            store,
            surface_digest=f"churn-{index}",
            at=f"245-BCE-12-05T18:{10 + index // 60:02d}:{index % 60:02d}+08:00",
            speaker_ref="char_tang_wei",
            statement=f"Routine line {index}",
            speech_kind="observation",
            session_ref=session["session_ref"],
        )

    recent = store.records[HISTORY_HEAD_PATH]["recent"]
    assert all(row.get("continuity_ref") != note["continuity_ref"] for row in recent)
    remembered = relevant_scene_continuity(
        store,
        subject_refs=["char_mou_gou"],
        location_ref="loc_tang_manor",
        limit=8,
    )
    remembered_note = next(row for row in remembered if row.get("continuity_ref") == note["continuity_ref"])
    assert remembered_note["truth_status"] == "derived_narrative_continuity"
    assert remembered_note["authority"] is False
    assert remembered_note["mechanical_consequence_authority"] is False


def test_gm_workspace_prioritizes_scene_and_compacts_private_character_mechanics():
    context = {
        "campaign": {"world_time": "245-BCE-12-05T18:00:00+08:00"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {
            "location": "loc_tang_manor",
            "scene_cast": {
                "present_people": [
                    {"person_id": "char_tang_wei", "name": "Tang Wei"},
                    {"person_id": "char_mou_gou", "name": "Mou Gou"},
                ]
            },
            "gm_private_director_context": {
                "present_people_context": {
                    "privacy": "gm_private_scene_bounded_omniscient_truth_not_player_knowledge",
                    "present_people": [{
                        "person_ref": "char_mou_gou",
                        "name": "Mou Gou",
                        "behavior_profile": {"register": "plainspoken"},
                        "character_truth": {
                            "life_status": "alive",
                            "health_status": "ready",
                            "authority": ["army_command"],
                            "attributes": {"Strength": 999},
                            "skills": {"Strategy": 999},
                            "hidden_goals": ["keep campaign coherent"],
                        },
                        "cognition": {"private_concern": "Wei overextends"},
                    }],
                    "relationship_edges": [],
                    "scene_pressure": {"private_signal": "messenger expected soon"},
                }
            },
        },
        "active_scene_session": {
            "session_ref": "scene_session_memory",
            "kind": "conversation",
            "location_ref": "loc_tang_manor",
            "participant_refs": ["char_tang_wei", "char_mou_gou"],
            "open_thread_refs": [],
        },
        "recent_scene_history": [{
            "speech_ref": "scene_speech_recent",
            "at": "245-BCE-12-05T18:01:00+08:00",
            "session_ref": "scene_session_memory",
            "speaker_ref": "char_mou_gou",
            "speech_kind": "question",
            "statement": "How far ahead do you intend to ride?",
            "truth_status": "attributed_statement",
        }],
        "recent_interaction_attempts": [{
            "event_id": "interaction_answer",
            "at": "245-BCE-12-05T18:02:00+08:00",
            "action": "speak",
            "target_ref": "char_mou_gou",
            "player_statement": "Close enough for your center to reach me.",
            "scene_session_ref": "scene_session_memory",
            "thread_status": "responded",
        }],
        "controlled_operations": [{
            "operation_ref": "operation.vanguard",
            "campaign_phase": "contact_development",
            "operational_intent_contract": {
                "operational_intent": "develop_contact",
                "deliberate_battle_commitment_authorized": False,
            },
        }],
        "commands": {"supported_command_types": []},
    }

    gm = build_gm_scene_context(context)
    assert gm["immediate_continuity"][-2]["statement"] == "How far ahead do you intend to ride?"
    assert gm["immediate_continuity"][-1]["player_statement"] == "Close enough for your center to reach me."
    assert gm["immediate_continuity"][-1]["beat_kind"] == "player_declared_action"
    assert gm["writer_contract"]["scene_direction_owner"] == "llm"
    assert gm["writer_contract"]["hard_consequence_owner"] == "runtime"
    assert gm["writer_contract"]["doctrine_source"].startswith("GM Skill")
    assert "present_people_are_active_agents_not_response_functions_or_speaking_queue" not in gm["writer_contract"]
    assert gm["hard_constraints"]["operational_intent_contracts"][0]["operational_intent"] == "develop_contact"
    mou_gou = next(row for row in gm["present_people"] if row.get("person_id") == "char_mou_gou")
    private = mou_gou["gm_private_direction"]
    assert "hidden_goals" in private["character_truth"]
    assert "attributes" not in private["character_truth"]
    assert "skills" not in private["character_truth"]
    director_people = gm["gm_private_scene_truth"]["director_context"]["present_people_context"]
    assert director_people["people_context_source"] == "present_people[].gm_private_direction"
    assert "present_people" not in director_people

    compact = compact_play_context(context)
    assert compact["gm_scene_context"]["purpose"] == "prioritized_writer_workspace_not_prose"
    assert compact["scene"]["gm_private_director_context"]["available_in_gm_scene_context"] is True
    compact_private_context = compact["gm_scene_context"]["gm_private_scene_truth"]["director_context"]["present_people_context"]
    compact_private = next(row for row in compact["gm_scene_context"]["present_people"] if row.get("person_id") == "char_mou_gou")["gm_private_direction"]
    assert compact_private_context["scene_pressure"]["private_signal"] == "messenger expected soon"
    assert compact_private_context["people_context_source"] == "present_people[].gm_private_direction"
    assert "attributes" not in compact_private["character_truth"]
    assert "skills" not in compact_private["character_truth"]


def test_scene_workspace_does_not_treat_sessionless_old_attempts_as_immediate_continuity() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00"},
        "player": {"location": "loc_wei_regional_02"},
        "scene": {"location": "loc_wei_regional_02", "scene_cast": {"present_people": []}},
        "active_scene_session": None,
        "recent_scene_history": [
            {
                "speech_ref": "old_scene_speech",
                "at": "244-BCE-09-29T18:14:00+08:00",
                "session_ref": "scene_session_already_closed",
                "speaker_ref": "char_mou_gou",
                "speech_kind": "statement",
                "statement": "Keep your banners where I can still reach them.",
                "truth_status": "attributed_statement",
            },
            {
                "fact_ref": "old_scene_fact",
                "at": "244-BCE-09-29T18:14:30+08:00",
                "session_ref": "scene_session_already_closed",
                "fact_kind": "visible_reaction",
                "summary": "Mou Gou folded the campaign map after the briefing.",
                "authority": False,
            },
        ],
        "recent_interaction_attempts": [
            {
                "event_id": "old_order",
                "at": "244-BCE-09-29T18:15:00+08:00",
                "action": "speak",
                "target_ref": "cmdgrp.tang_wei.field_army",
                "process_ref": "operation.vanguard",
                "player_statement": "Develop contact and report. Do not start a general battle.",
                "thread_status": "not_applicable",
            }
        ],
        "controlled_operations": [
            {
                "operation_ref": "operation.vanguard",
                "status": "active",
                "campaign_phase": "contact_development",
                "operational_intent_contract": {
                    "operational_intent": "develop_contact",
                    "deliberate_battle_commitment_authorized": False,
                    "contact_is_not_synonymous_with_battle": True,
                },
            }
        ],
    }

    gm = build_gm_scene_context(context)
    assert gm["immediate_continuity"] == []
    assert gm["recent_player_action_count"] == 0
    assert gm["practical_threads"][0]["operational_intent"]["operational_intent"] == "develop_contact"


def test_sessionless_populated_scene_explicitly_invites_llm_npc_initiative_without_scripted_prose() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00", "player_id": "char_tang_wei"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {
            "location": "loc_tang_manor",
            "scene_cast": {
                "present_people": [
                    {"person_id": "char_tang_wei", "name": "Tang Wei"},
                    {"person_id": "char_mou_gou", "name": "Mou Gou"},
                ]
            },
            "gm_private_director_context": {
                "present_people_context": {
                    "present_people": [{
                        "person_ref": "char_mou_gou",
                        "name": "Mou Gou",
                        "character_truth": {"life_status": "alive", "health_status": "ready"},
                        "cognition": {"private_concern": "Wei overextends"},
                    }],
                    "relationship_edges": [],
                }
            },
        },
        "active_scene_session": None,
        "recent_scene_history": [],
        "recent_interaction_attempts": [],
    }

    gm = build_gm_scene_context(context)
    direction = gm["scene_direction"]
    assert direction["llm_is_scene_director"] is True
    assert direction["continuation_mode"] == "present_people_may_initiate"
    assert direction["present_agent_refs"] == ["char_mou_gou"]
    assert direction["next_beat_requirement"] == "advance_grounded_scene_or_compress"
    assert direction["director_doctrine_source"].startswith("GM Skill")
    assert "directing_contract" not in direction
    assert gm["writer_contract"]["scene_direction_owner"] == "llm"
    assert gm["writer_contract"]["hard_consequence_owner"] == "runtime"
    assert gm["writer_contract"]["doctrine_source"].startswith("GM Skill")
    assert direction["director_doctrine_source"].startswith("GM Skill")
    assert "directing_contract" not in direction
    assert len(direction["director_protocol"]) >= 7
    assert "reject_draft_if" not in direction
    assert "directing_contract" not in direction
    assert direction["agents_with_private_direction_refs"] == ["char_mou_gou"]
    assert direction["beat_candidates"][0]["reason"] in {"private_direction_available", "present_agent"}
    assert direction["beat_candidate_rule"] == "causal_priority_hint_not_speaking_queue_or_script"
    assert len(json.dumps(direction, sort_keys=True)) < 5000


def test_scene_director_preserves_explicit_player_decision_without_freezing_reversible_npc_reaction() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00", "player_id": "char_tang_wei"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {
            "location": "loc_tang_manor",
            "scene_cast": {
                "present_people": [
                    {"person_id": "char_tang_wei", "name": "Tang Wei"},
                    {"person_id": "char_mou_gou", "name": "Mou Gou"},
                ]
            },
        },
        "unresolved_decision": {"decision_ref": "decision.command_offer", "kind": "qin_field_command_offer"},
        "active_scene_session": None,
        "recent_scene_history": [],
        "recent_interaction_attempts": [],
    }
    gm = build_gm_scene_context(context)
    direction = gm["scene_direction"]
    assert direction["protected_player_decision_pending"] is True
    assert direction["continuation_mode"] == "preserve_player_decision_and_allow_reversible_reaction"
    assert direction["present_agent_refs"] == ["char_mou_gou"]
    assert direction["director_doctrine_source"].startswith("GM Skill")
    assert "directing_contract" not in direction


def test_scene_director_does_not_promote_remote_open_attempt_into_local_human_thread() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00", "player_id": "char_tang_wei"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {
            "location": "loc_tang_manor",
            "scene_cast": {"present_people": [{"person_id": "char_tang_wei", "name": "Tang Wei"}]},
        },
        "active_scene_session": None,
        "recent_scene_history": [],
        "recent_interaction_attempts": [{
            "event_id": "attempt.remote",
            "action": "ask",
            "target_ref": "char_remote_officer",
            "player_statement": "Send me your report.",
            "thread_status": "open",
            "scene_session_ref": "scene_session_old",
        }],
    }
    gm = build_gm_scene_context(context)
    assert gm["human_threads"] == []
    assert gm["scene_direction"]["open_human_thread_count"] == 0
    assert gm["scene_direction"]["open_human_target_refs"] == []


def test_scene_director_uses_physically_projected_active_scene_threads() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00", "player_id": "char_tang_wei"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {
            "location": "loc_tang_manor",
            "scene_cast": {
                "present_people": [
                    {"person_id": "char_tang_wei", "name": "Tang Wei"},
                    {"person_id": "char_mou_gou", "name": "Mou Gou"},
                ]
            },
            "active_threads": [{
                "event_id": "attempt.local",
                "action": "ask",
                "target_ref": "char_mou_gou",
                "player_statement": "What do you think?",
                "thread_status": "open",
                "scene_session_ref": "scene_session_current",
            }],
        },
        "active_scene_session": {
            "session_ref": "scene_session_current",
            "kind": "conversation",
            "participant_refs": ["char_tang_wei", "char_mou_gou"],
            "open_thread_refs": ["attempt.local"],
        },
        "recent_scene_history": [],
        "recent_interaction_attempts": [],
    }
    gm = build_gm_scene_context(context)
    assert gm["scene_direction"]["open_human_target_refs"] == ["char_mou_gou"]
    assert gm["scene_direction"]["open_human_thread_count"] == 1


def test_scene_direction_exposes_llm_owned_scene_lifecycle_affordance() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00", "player_id": "char_tang_wei"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {
            "location": "loc_tang_manor",
            "scene_cast": {"present_people": [
                {"person_id": "char_tang_wei", "name": "Tang Wei"},
                {"person_id": "char_mou_gou", "name": "Mou Gou"},
            ]},
        },
        "active_scene_session": None,
        "recent_scene_history": [],
        "recent_interaction_attempts": [],
    }
    direction = build_gm_scene_context(context)["scene_direction"]
    lifecycle = direction["scene_lifecycle"]
    assert lifecycle["formal_session_active"] is False
    assert lifecycle["open_affordance"] is True
    assert lifecycle["candidate_participant_refs"] == ["char_tang_wei", "char_mou_gou"]
    assert lifecycle["persistence_route_source"] == "GM Skill scene lifecycle contract"
    assert "rules" not in lifecycle
    assert direction["director_doctrine_source"].startswith("GM Skill")
    assert len(direction["director_protocol"]) == 7
    assert "decide_scene_lifecycle_from_lived_pressure" in direction["director_protocol"]


def test_scene_direction_marks_close_risk_for_live_thread_and_player_decision() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00", "player_id": "char_tang_wei"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {
            "location": "loc_tang_manor",
            "scene_cast": {"present_people": [
                {"person_id": "char_tang_wei", "name": "Tang Wei"},
                {"person_id": "char_mou_gou", "name": "Mou Gou"},
            ]},
            "active_threads": [{
                "event_id": "attempt.local",
                "action": "ask",
                "target_ref": "char_mou_gou",
                "scene_session_ref": "scene_session_current",
                "thread_status": "open",
            }],
        },
        "unresolved_decision": {"decision_ref": "decision.command_offer"},
        "active_scene_session": {
            "session_ref": "scene_session_current",
            "kind": "conversation",
            "participant_refs": ["char_tang_wei", "char_mou_gou"],
            "open_thread_refs": ["attempt.local"],
        },
        "recent_scene_history": [],
        "recent_interaction_attempts": [],
    }
    lifecycle = build_gm_scene_context(context)["scene_direction"]["scene_lifecycle"]
    assert lifecycle["formal_session_active"] is True
    assert lifecycle["close_affordance"] is True
    assert set(lifecycle["close_risks"]) == {"open_human_threads", "protected_player_decision"}


def test_scene_direction_does_not_offer_people_session_during_active_conflict() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00", "player_id": "char_tang_wei"},
        "player": {"person_id": "char_tang_wei", "location": "loc_field"},
        "scene": {
            "location": "loc_field",
            "scene_cast": {"present_people": [
                {"person_id": "char_tang_wei", "name": "Tang Wei"},
                {"person_id": "char_mou_gou", "name": "Mou Gou"},
            ]},
            "personal_combat": {"combat_ref": "combat.1", "status": "active"},
        },
        "active_scene_session": None,
        "recent_scene_history": [],
        "recent_interaction_attempts": [],
    }
    lifecycle = build_gm_scene_context(context)["scene_direction"]["scene_lifecycle"]
    assert lifecycle["contested_process_active"] is True
    assert lifecycle["open_affordance"] is False


def test_scene_open_implicitly_keeps_tang_wei_in_persisted_participants() -> None:
    store = _Store({
        "state/player.json": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
    })
    event = {
        "schema": "sword-scene-action.v1",
        "surface_digest": "abc123",
        "actor_id": "char_tang_wei",
        "action": "open",
        "kind": "conversation",
        "participant_refs": ["char_mou_gou"],
        "process_ref": None,
        "purpose": "Talk through the immediate issue",
        "agenda": [],
    }
    summary = SCENE_ACTION_PREFIX + json.dumps(event, sort_keys=True, separators=(",", ":"))
    result = apply_scene_action_record(store, summary, at="244-BCE-10-04T06:00:00+08:00")
    assert result["record_kind"] == "scene_session_open"
    session = store.records[ACTIVE_SESSION_PATH]
    assert session["participant_refs"] == ["char_tang_wei", "char_mou_gou"]


def test_scene_director_reconciles_formal_session_when_other_participant_is_physically_absent() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {
            "location": "loc_tang_manor",
            "scene_cast": {"present_people": [{"person_id": "char_tang_wei", "name": "Tang Wei"}]},
        },
        "active_scene_session": {
            "session_ref": "scene_session_departed",
            "kind": "conversation",
            "location_ref": "loc_tang_manor",
            "participant_refs": ["char_tang_wei"],
            "participant_count": 1,
            "durable_participant_count": 2,
            "physically_absent_participant_refs": ["char_mou_gou"],
            "physically_absent_participant_count": 1,
            "physical_scene_viable": False,
            "lifecycle_reconciliation_recommended": True,
            "open_thread_refs": ["interaction_old_question"],
        },
        "recent_scene_history": [],
        "recent_interaction_attempts": [],
        "controlled_operations": [],
        "commands": {"supported_command_types": []},
    }

    gm = build_gm_scene_context(context)
    direction = gm["scene_direction"]
    lifecycle = direction["scene_lifecycle"]
    assert direction["continuation_mode"] == "reconcile_stale_formal_session_then_transition"
    assert direction["open_human_thread_count"] == 0
    assert gm["human_threads"] == []
    assert lifecycle["formal_session_presence_viable"] is False
    assert lifecycle["formal_session_absent_participant_refs"] == ["char_mou_gou"]
    assert lifecycle["lifecycle_reconciliation_recommended"] is True


def test_scene_director_prioritizes_active_session_people_over_general_site_cast() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {
            "location": "loc_tang_manor",
            "scene_cast": {
                "present_people": [
                    {"person_id": "char_tang_wei", "name": "Tang Wei"},
                    {"person_id": "char_bystander", "name": "Bystander"},
                    {"person_id": "char_mou_gou", "name": "Mou Gou", "role": "general"},
                ]
            },
        },
        "active_scene_session": {
            "session_ref": "scene_session_command",
            "kind": "conversation",
            "location_ref": "loc_tang_manor",
            "participant_refs": ["char_tang_wei", "char_mou_gou"],
            "participant_count": 2,
            "physical_scene_viable": True,
            "open_thread_refs": [],
        },
        "recent_scene_history": [],
        "recent_interaction_attempts": [],
        "controlled_operations": [],
        "commands": {"supported_command_types": []},
    }

    gm = build_gm_scene_context(context)
    direction = gm["scene_direction"]
    candidates = direction["beat_candidates"]
    assert direction["continuation_mode"] == "active_scene_continue_or_transition_by_lived_pressure"
    assert candidates[0] == {"person_ref": "char_mou_gou", "reason": "active_formal_session"}


def test_compact_play_context_keeps_scene_lifecycle_but_not_opaque_open_thread_refs() -> None:
    context = {
        "campaign": {"world_time": "244-BCE-10-04T06:00:00+08:00"},
        "player": {"person_id": "char_tang_wei", "location": "loc_tang_manor"},
        "scene": {"location": "loc_tang_manor", "scene_cast": {"present_people": []}},
        "active_scene_session": {
            "session_ref": "scene_session_compact",
            "kind": "conversation",
            "status": "active",
            "location_ref": "loc_tang_manor",
            "participant_refs": ["char_tang_wei"],
            "physically_absent_participant_refs": ["char_mou_gou"],
            "physical_scene_viable": False,
            "open_thread_refs": [f"thread_{i}" for i in range(20)],
        },
        "recent_scene_history": [],
        "recent_interaction_attempts": [],
        "controlled_operations": [],
        "commands": {"supported_command_types": []},
    }

    compact = compact_play_context(context)
    session = compact["active_scene_session"]
    assert session["open_thread_count"] == 20
    assert "open_thread_refs" not in session
    assert session["physically_absent_participant_refs"] == ["char_mou_gou"]
    assert session["physical_scene_viable"] is False
