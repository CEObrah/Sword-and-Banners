"""Player-safe interaction and live scene projection helpers.

This module deliberately does not own campaign truth. It validates caller-owned
interaction intent, translates it into an internal attempt-only event for the
transaction engine, and builds bounded read projections exclusively from exact
current owners and already-triggered event-registry facts.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.commands import CommandEnvelope
from sword_runtime.causal_event_store import (
    causal_event_kind_count_from_reader,
    get_causal_event_from_reader,
    iter_causal_events_newest,
)

from sword_runtime.scene_sessions import (
    INTERACTION_CLOSED_HISTORY_LIMIT, SCENE_FACT_KINDS, SESSION_KINDS, SPEECH_KINDS, active_scene_session, attach_open_thread,
    close_active_scene, record_attributed_speech, record_scene_fact, start_scene_session, touch_active_scene,
)

INTERACTION_ACTIONS = frozenset({
    "present", "request", "petition", "report", "ask", "offer", "decline",
    "comply", "withdraw", "proceed", "seek_contact", "speak",
})
RESPONSE_BEARING_ACTIONS = frozenset({"ask", "request", "petition", "offer", "present", "report", "speak"})
INTERACTION_PAYLOAD_KEYS = frozenset({
    "target_ref", "action", "process_ref", "player_statement",
    "formation_refs", "posture", "topic", "scopes", "expects_response",
})
FORBIDDEN_OUTCOME_KEYS = frozenset({
    "outcome", "response", "result", "npc_response", "world_effect",
    "authoritative_summary", "summary", "decision", "reaction", "acceptance",
    "appointment", "rank", "vacancy", "access_granted", "permission_granted",
})
HOT_INFORMATION_LIMIT = 16
HOT_FORMATION_LIMIT = 12
HOT_INTERACTION_LIMIT = 8
HOT_ATTEMPT_LIMIT = 8
HOT_ACTIVE_THREAD_LIMIT = 16
INTERACTION_ATTEMPT_LEDGER_LIMIT = INTERACTION_CLOSED_HISTORY_LIMIT
INTERACTION_ATTEMPT_LEDGER_PATH = "state/index/interaction-attempts.json"
INTERACTION_ATTEMPT_PREFIX = "sword-interaction-attempt.v1 "
SCENE_ACTION_PREFIX = "sword-scene-action.v1 "
SCENE_SESSION_ACTIONS = frozenset({"open", "close", "record_speech", "record_fact"})
SCENE_ACTION_PAYLOAD_KEYS = frozenset({
    "action", "kind", "participant_refs", "process_ref", "purpose", "agenda",
    "session_ref", "close_reason", "speaker_ref", "statement", "speech_kind",
    "basis_refs", "resolves_thread_ref", "resolves_question_ref",
    "fact_kind", "description", "actor_ref", "improvised_prop",
})
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_PERSON_OWNER_SCHEMAS = frozenset({"sab_character", "person-lite", "sword-materialized-person"})


def _expects_response(action: str, explicit: object) -> bool:
    """Use semantic defaults, but honor an explicit no-response/final-line intent."""
    if isinstance(explicit, bool):
        return explicit
    return action in RESPONSE_BEARING_ACTIONS
_TRIGGERED_INTERACTION_KINDS = frozenset({
    "institutional_response", "petition_response", "message", "audience_response",
    "world_arc_report",
    "campaign_command_council", "campaign_command_superior_order", "campaign_command_after_action_review",
    "campaign_command_dawn_briefing", "campaign_command_evening_sitrep",
})

# Live play needs a compact machine-readable boundary between durable world
# truth and ordinary reversible scene flow. Narrative procedure belongs in the
# GM Skill; the runtime only advertises the current authority boundary.
SCENE_LOCAL_NARRATION_CONTRACT = {
    "mode": "presentation_only_reversible",
    "reversible_local_continuation": True,
    "persistent_consequences_require_runtime": True,
    "interaction_attempt_establishes_external_outcome": False,
    "runtime_records_are_source_material_not_dialogue_scripts": True,
    "ai_authors_human_performance": True,
    "subjective_scene_latitude": (
        "The GM may author momentary nonbinding reactions, tone, hesitation, humor, irritation, warmth, silence, and ordinary opinions "
        "when consistent with established role, relationship, prior behavior, and pressure. These are scene performance, not hidden factual motives or durable state."
    ),
}


def _walk_forbidden(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).strip().lower() in FORBIDDEN_OUTCOME_KEYS:
                return True
            if _walk_forbidden(child):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_walk_forbidden(item) for item in value)
    return False


def _require_safe_ref(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise ValueError(f"interaction_action {field} is invalid")
    return value


def _optional_text(value: object, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character in value for character in ("\x00", "\r", "\n"))
    ):
        raise ValueError(f"interaction_action {field} is invalid")
    return value.strip()


def validate_interaction_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    keys = set(payload)
    if not keys <= INTERACTION_PAYLOAD_KEYS:
        raise ValueError("interaction_action contains unsupported caller fields")
    if _walk_forbidden(payload):
        raise ValueError("interaction_action may not supply world or NPC outcomes")
    target_ref = _require_safe_ref(payload.get("target_ref"), "target_ref")
    action = payload.get("action")
    if not isinstance(action, str) or action not in INTERACTION_ACTIONS:
        raise ValueError("interaction_action action is unsupported")
    process_ref = payload.get("process_ref")
    if process_ref is not None:
        process_ref = _require_safe_ref(process_ref, "process_ref")
    statement = _optional_text(payload.get("player_statement"), "player_statement", 2000)
    posture = _optional_text(payload.get("posture"), "posture", 500)
    topic = _optional_text(payload.get("topic"), "topic", 240)
    scope_values = payload.get("scopes", ())
    if (
        not isinstance(scope_values, Sequence)
        or isinstance(scope_values, (str, bytes, bytearray))
        or len(scope_values) > 32
    ):
        raise ValueError("interaction_action scopes is invalid")
    scopes = [_require_safe_ref(ref, "scopes") for ref in scope_values]
    if len(set(scopes)) != len(scopes):
        raise ValueError("interaction_action scopes must be unique")
    formation_values = payload.get("formation_refs", ())
    if (
        not isinstance(formation_values, Sequence)
        or isinstance(formation_values, (str, bytes, bytearray))
        or len(formation_values) > 128
    ):
        raise ValueError("interaction_action formation_refs is invalid")
    formation_refs = [_require_safe_ref(ref, "formation_refs") for ref in formation_values]
    if len(set(formation_refs)) != len(formation_refs):
        raise ValueError("interaction_action formation_refs must be unique")
    expects_response = payload.get("expects_response")
    if expects_response is not None and not isinstance(expects_response, bool):
        raise ValueError("interaction_action expects_response is invalid")
    return {
        "target_ref": target_ref,
        "action": action,
        "process_ref": process_ref,
        "player_statement": statement,
        "formation_refs": formation_refs,
        "posture": posture,
        "topic": topic,
        "scopes": scopes,
        "expects_response": bool(expects_response) if expects_response is not None else None,
    }



_IMPROVISED_PROP_FORMS = frozenset({"small_rigid", "short_rigid", "long_rigid", "heavy_rigid", "sharp_fragment"})
_IMPROVISED_PROP_MATERIALS = frozenset({"wood", "bamboo", "ceramic", "stone", "metal", "bone"})
_IMPROVISED_PROP_CONDITIONS = frozenset({"intact", "worn", "cracked", "broken_piece"})


def _validate_improvised_prop(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) - {"form", "material", "condition"}:
        raise ValueError("scene_session_action improvised_prop is invalid")
    form = value.get("form")
    material = value.get("material")
    condition = value.get("condition", "intact")
    if form not in _IMPROVISED_PROP_FORMS:
        raise ValueError("scene_session_action improvised_prop form is unsupported")
    if material not in _IMPROVISED_PROP_MATERIALS:
        raise ValueError("scene_session_action improvised_prop material is unsupported")
    if condition not in _IMPROVISED_PROP_CONDITIONS:
        raise ValueError("scene_session_action improvised_prop condition is unsupported")
    return {"kind": "mundane_improvised_prop", "form": str(form), "material": str(material), "condition": str(condition)}


def validate_scene_action_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not set(payload) <= SCENE_ACTION_PAYLOAD_KEYS:
        raise ValueError("scene_session_action contains unsupported caller fields")
    if _walk_forbidden(payload):
        raise ValueError("scene_session_action may not supply mechanical world outcomes")
    action = payload.get("action")
    if not isinstance(action, str) or action not in SCENE_SESSION_ACTIONS:
        raise ValueError("scene_session_action action is unsupported")
    if action == "open":
        kind = payload.get("kind")
        if not isinstance(kind, str) or kind not in SESSION_KINDS:
            raise ValueError("scene_session_action kind is unsupported")
        participants = payload.get("participant_refs")
        if not isinstance(participants, Sequence) or isinstance(participants, (str, bytes, bytearray)):
            raise ValueError("scene_session_action participant_refs is invalid")
        refs = [_require_safe_ref(ref, "participant_refs") for ref in participants]
        if not refs or len(refs) > 128 or len(set(refs)) != len(refs):
            raise ValueError("scene_session_action participant_refs is invalid")
        process_ref = payload.get("process_ref")
        if process_ref is not None:
            process_ref = _require_safe_ref(process_ref, "process_ref")
        purpose = _optional_text(payload.get("purpose"), "purpose", 1000)
        agenda = payload.get("agenda", [])
        if not isinstance(agenda, Sequence) or isinstance(agenda, (str, bytes, bytearray)) or len(agenda) > 32:
            raise ValueError("scene_session_action agenda is invalid")
        agenda_rows = [_optional_text(item, "agenda", 500) for item in agenda]
        if any(item is None for item in agenda_rows):
            raise ValueError("scene_session_action agenda is invalid")
        return {"action": action, "kind": kind, "participant_refs": refs, "process_ref": process_ref, "purpose": purpose, "agenda": agenda_rows}
    session_ref = _require_safe_ref(payload.get("session_ref"), "session_ref")
    if action == "close":
        reason = payload.get("close_reason", "completed")
        if reason not in {"completed", "player_left", "hard_interruption", "skipped_to_conclusion", "cancelled"}:
            raise ValueError("scene_session_action close_reason is unsupported")
        return {"action": action, "session_ref": session_ref, "close_reason": reason}
    if action == "record_fact":
        actor_ref = _require_safe_ref(payload.get("actor_ref"), "actor_ref")
        fact_kind = payload.get("fact_kind")
        if not isinstance(fact_kind, str) or fact_kind not in SCENE_FACT_KINDS:
            raise ValueError("scene_session_action fact_kind is unsupported")
        description = _optional_text(payload.get("description"), "description", 1500)
        if description is None:
            raise ValueError("scene_session_action description is required")
        participant_values = payload.get("participant_refs", [])
        if not isinstance(participant_values, Sequence) or isinstance(participant_values, (str, bytes, bytearray)) or len(participant_values) > 32:
            raise ValueError("scene_session_action participant_refs is invalid")
        participant_refs = [_require_safe_ref(ref, "participant_refs") for ref in participant_values]
        if len(set(participant_refs)) != len(participant_refs):
            raise ValueError("scene_session_action participant_refs must be unique")
        basis_values = payload.get("basis_refs", [])
        if not isinstance(basis_values, Sequence) or isinstance(basis_values, (str, bytes, bytearray)) or len(basis_values) > 32:
            raise ValueError("scene_session_action basis_refs is invalid")
        basis_refs = [_require_safe_ref(ref, "basis_refs") for ref in basis_values]
        if len(set(basis_refs)) != len(basis_refs):
            raise ValueError("scene_session_action basis_refs must be unique")
        improvised_prop = _validate_improvised_prop(payload.get("improvised_prop"))
        if improvised_prop is not None and fact_kind != "object_state":
            raise ValueError("scene_session_action improvised_prop requires object_state fact_kind")
        return {
            "action": action, "session_ref": session_ref, "actor_ref": actor_ref,
            "fact_kind": fact_kind, "description": description, "participant_refs": participant_refs,
            "basis_refs": basis_refs, "improvised_prop": improvised_prop,
        }
    speaker_ref = _require_safe_ref(payload.get("speaker_ref"), "speaker_ref")
    statement = _optional_text(payload.get("statement"), "statement", 2500)
    if statement is None:
        raise ValueError("scene_session_action statement is required")
    speech_kind = payload.get("speech_kind")
    if not isinstance(speech_kind, str) or speech_kind not in SPEECH_KINDS:
        raise ValueError("scene_session_action speech_kind is unsupported")
    basis_values = payload.get("basis_refs", [])
    if not isinstance(basis_values, Sequence) or isinstance(basis_values, (str, bytes, bytearray)) or len(basis_values) > 32:
        raise ValueError("scene_session_action basis_refs is invalid")
    basis_refs = [_require_safe_ref(ref, "basis_refs") for ref in basis_values]
    if len(set(basis_refs)) != len(basis_refs):
        raise ValueError("scene_session_action basis_refs must be unique")
    thread_ref = payload.get("resolves_thread_ref")
    if thread_ref is not None:
        thread_ref = _require_safe_ref(thread_ref, "resolves_thread_ref")
    question_ref = payload.get("resolves_question_ref")
    if question_ref is not None:
        question_ref = _require_safe_ref(question_ref, "resolves_question_ref")
    if thread_ref is not None and question_ref is not None and thread_ref != question_ref:
        raise ValueError("scene_session_action thread/question resolution refs disagree")
    thread_ref = thread_ref or question_ref
    return {
        "action": action, "session_ref": session_ref, "speaker_ref": speaker_ref,
        "statement": statement, "speech_kind": speech_kind, "basis_refs": basis_refs,
        "resolves_thread_ref": thread_ref,
        "resolves_question_ref": question_ref,
    }


def scene_action_summary(command: CommandEnvelope, payload: Mapping[str, Any]) -> str:
    record = validate_scene_action_payload(payload)
    event = {
        "schema": "sword-scene-action.v1",
        "surface_digest": command.semantic_digest,
        "actor_id": command.actor_id,
        **record,
    }
    summary = SCENE_ACTION_PREFIX + json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(summary) > 4000:
        raise ValueError("scene_session_action serialized record exceeds bounded transport")
    return summary


def parse_scene_action_summary(summary: object) -> dict[str, Any] | None:
    if not isinstance(summary, str) or not summary.startswith(SCENE_ACTION_PREFIX):
        return None
    try:
        record = json.loads(summary[len(SCENE_ACTION_PREFIX):])
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict) or record.get("schema") != "sword-scene-action.v1":
        return None
    return record


def translate_scene_action_command(command: CommandEnvelope) -> CommandEnvelope:
    summary = scene_action_summary(command, command.payload)
    return CommandEnvelope(
        campaign_id=command.campaign_id,
        request_id=command.request_id,
        actor_id=command.actor_id,
        command_type="scene_consequence",
        expected_revision=command.expected_revision,
        submitted_at=command.submitted_at,
        payload={"summary": summary},
        mode=command.mode,
    )

def interaction_attempt_summary(command: CommandEnvelope, payload: Mapping[str, Any]) -> str:
    """Encode a typed, attempt-only record with the original surface digest."""
    record = validate_interaction_payload(payload)
    attempt = {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": command.semantic_digest,
        "actor_id": command.actor_id,
        "target_ref": record["target_ref"],
        "action": record["action"],
        "process_ref": record["process_ref"],
        "player_statement": record["player_statement"],
        "formation_refs": record["formation_refs"],
        "posture": record["posture"],
        "topic": record["topic"],
        "scopes": record["scopes"],
        "expects_response": record["expects_response"],
        "world_response_status": "not_established_by_attempt",
        "world_response_status_scope": "hard_consequence_only",
        "ordinary_scene_response_rule": "co_located_or_authorized_scene_may_respond_reversibly_without_bespoke_mechanic",
    }
    summary = INTERACTION_ATTEMPT_PREFIX + json.dumps(
        attempt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(summary) > 4000:
        raise ValueError("interaction_action serialized attempt exceeds bounded history record")
    return summary


def parse_interaction_attempt_summary(summary: object) -> dict[str, Any] | None:
    if not isinstance(summary, str) or not summary.startswith(INTERACTION_ATTEMPT_PREFIX):
        return None
    try:
        record = json.loads(summary[len(INTERACTION_ATTEMPT_PREFIX):])
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict) or record.get("schema") != "sword-interaction-attempt.v1":
        return None
    if record.get("world_response_status") != "not_established_by_attempt":
        return None
    return record


def interaction_attempt_record_ref(attempt: Mapping[str, Any]) -> str:
    digest = str(attempt.get("surface_digest", ""))
    token = digest[:24]
    if not token:
        raise ValueError("interaction attempt lacks surface digest identity")
    return f"interaction_attempt_{token}"


def interaction_attempt_ref(attempt: Mapping[str, Any]) -> str:
    """Return the gameplay-causal identity of an interaction attempt.

    Transaction request IDs are recovery/idempotency metadata and must never be
    copied into campaign state.  The typed interaction event has its own stable
    identity derived from the command surface digest; persisted ledger rows also
    carry that identity directly as ``event_id``.
    """
    event_id = attempt.get("event_id")
    if isinstance(event_id, str) and event_id:
        return event_id
    return interaction_attempt_record_ref(attempt)



def _normalized_attempt_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(raw)
    row.setdefault("scene_session_ref", None)
    row.setdefault("topic", None)
    row.setdefault("scopes", [])
    action = str(row.get("action"))
    has_statement = isinstance(row.get("player_statement"), str) and bool(row.get("player_statement"))
    expects_response = _expects_response(action, row.get("expects_response"))
    belongs_to_scene = isinstance(row.get("scene_session_ref"), str) and bool(row.get("scene_session_ref"))
    row.setdefault("expects_response", expects_response if has_statement else False)
    row.setdefault("thread_kind", "question" if action == "ask" else ("conversation" if expects_response and has_statement else None))
    row.setdefault("thread_status", "open" if expects_response and has_statement and belongs_to_scene else "not_applicable")
    row.setdefault("world_response_status_scope", "hard_consequence_only")
    row.setdefault("ordinary_scene_response_rule", "co_located_or_authorized_scene_may_respond_reversibly_without_bespoke_mechanic")
    row.setdefault("resolved_at", None)
    row.setdefault("response_ref", None)
    return row


def record_interaction_attempt(store, summary: object, *, at: str) -> str | None:
    """Persist one typed attempt in bounded routing state, never semantic history."""
    attempt = parse_interaction_attempt_summary(summary)
    if attempt is None:
        return None
    ref = interaction_attempt_record_ref(attempt)
    ledger = _read_optional_json(store, INTERACTION_ATTEMPT_LEDGER_PATH)
    if not isinstance(ledger, Mapping):
        ledger = {
            "schema": "sword-interaction-attempt-ledger",
            "authority": False,
            "purpose": "bounded routing ledger for player-authored interaction attempts; never world outcome authority",
            "total_recorded": 0,
            "attempts": [],
        }
    else:
        ledger = dict(ledger)
    raw_rows = ledger.get("attempts", [])
    rows = [_normalized_attempt_row(row) for row in raw_rows if isinstance(row, Mapping)] if isinstance(raw_rows, list) else []
    if any(str(row.get("event_id", "")) == ref for row in rows):
        return ref
    persisted_attempt = {key: value for key, value in attempt.items() if key != "schema"}
    session = active_scene_session(store)
    target_ref = str(attempt.get("target_ref", ""))
    action = str(attempt.get("action"))
    has_statement = isinstance(attempt.get("player_statement"), str) and bool(attempt.get("player_statement"))
    expects_response = _expects_response(action, attempt.get("expects_response"))

    # Do not require a separate scene-open command before an ordinary human
    # request/question can persist as a live conversation. The interaction
    # surface has already validated the exact co-located target. When no scene
    # exists, establish one authority:false conversation in this same semantic
    # transaction. This reduces command choreography without weakening hard
    # consequence authority.
    if session is None and has_statement and expects_response:
        target_path = person_owner_path(store, target_ref)
        actor_ref = str(attempt.get("actor_id") or "")
        if actor_ref and target_path is not None:
            player = _read_optional_json(store, "state/player.json")
            target = _read_optional_json(store, target_path)
            location = None
            target_location = None
            if isinstance(player, Mapping):
                location = player.get("location") or player.get("current_location") or player.get("location_ref")
            if isinstance(target, Mapping):
                target_location = target.get("current_location") or target.get("location_ref") or target.get("location")
            # A known or remotely addressable person is not automatically in
            # the room. Only co-located exact people receive an implicit live
            # conversation session; remote petitions/messages remain ordinary
            # routed attempts until their delivery mechanics establish contact.
            if isinstance(location, str) and location and target_location == location:
                session = start_scene_session(
                    store,
                    session_ref=f"scene_session_{str(attempt.get('surface_digest') or '')[:24]}",
                    kind="conversation",
                    location_ref=location,
                    participant_refs=[actor_ref, target_ref],
                    started_at=at,
                    process_ref=attempt.get("process_ref") if isinstance(attempt.get("process_ref"), str) else None,
                    purpose=str(attempt.get("topic") or "ongoing conversation")[:1000],
                )

    # A live conversation is not a frozen cast list. If Wei addresses another
    # persistent person who is physically co-located at the same exact scene,
    # admit that person to the reversible session in this same semantic action
    # so a natural response can remain a durable thread. Remote message/channel
    # targets never enter a face-to-face session through this path.
    if isinstance(session, Mapping) and has_statement and expects_response:
        actor_ref = str(attempt.get("actor_id") or "")
        target_path = person_owner_path(store, target_ref)
        participants = [str(x) for x in session.get("participant_refs", []) if isinstance(x, str)]
        if actor_ref in participants and target_ref not in participants and target_path is not None:
            player = _read_optional_json(store, "state/player.json")
            target = _read_optional_json(store, target_path)
            location = None
            target_location = None
            if isinstance(player, Mapping):
                location = player.get("location") or player.get("current_location") or player.get("location_ref")
            if isinstance(target, Mapping):
                target_location = target.get("current_location") or target.get("location_ref") or target.get("location")
            if isinstance(location, str) and location and target_location == location and session.get("location_ref") == location:
                session = dict(session)
                session["participant_refs"] = participants + [target_ref]
                session["last_updated_at"] = at
                store.put("state/index/active-scene-session.json", session)

    session_participants = set(str(x) for x in session.get("participant_refs", []) if isinstance(x, str)) if isinstance(session, Mapping) else set()
    session_ref = str(session.get("session_ref")) if isinstance(session, Mapping) and target_ref in session_participants else None
    is_question = action == "ask" and has_statement
    is_thread = expects_response and has_statement and session_ref is not None
    rows.append({
        "event_id": ref, "at": at, **persisted_attempt,
        "scene_session_ref": session_ref,
        "expects_response": expects_response if has_statement else False,
        "thread_kind": "question" if is_question else ("conversation" if is_thread else None),
        "thread_status": "open" if is_thread else "not_applicable",
        "resolved_at": None,
        "response_ref": None,
    })
    # Keep every genuinely unresolved thread plus only a bounded recent window
    # of resolved/non-thread attempts. The hot-routing bound must never silently
    # erase a live question merely because unrelated interactions occurred.
    open_rows = [row for row in rows if row.get("thread_status") == "open"]
    closed_rows = [row for row in rows if row.get("thread_status") != "open"]
    ledger["attempts"] = open_rows + closed_rows[-INTERACTION_ATTEMPT_LEDGER_LIMIT:]
    ledger["total_recorded"] = int(ledger.get("total_recorded", 0)) + 1
    store.put(INTERACTION_ATTEMPT_LEDGER_PATH, ledger)
    if session_ref is not None:
        touch_active_scene(store, at=at, session_ref=session_ref)
    if is_thread:
        attach_open_thread(store, ref, at=at, is_question=is_question)
    return ref



def mark_interaction_thread_resolved(store: Any, thread_ref: str, *, at: str, response_ref: str) -> bool:
    ledger = _read_optional_json(store, INTERACTION_ATTEMPT_LEDGER_PATH)
    if not isinstance(ledger, Mapping):
        return False
    out = dict(ledger)
    raw_rows = out.get("attempts", [])
    if not isinstance(raw_rows, list):
        return False
    changed = False
    rows = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            continue
        row = _normalized_attempt_row(raw)
        if str(row.get("event_id")) == thread_ref and row.get("thread_status") == "open":
            row["thread_status"] = "answered" if row.get("thread_kind") == "question" else "responded"
            row["resolved_at"] = at
            row["response_ref"] = response_ref
            changed = True
        rows.append(row)
    if changed:
        out["attempts"] = rows
        store.put(INTERACTION_ATTEMPT_LEDGER_PATH, out)
    return changed


def mark_interaction_question_resolved(store: Any, question_ref: str, *, at: str, response_ref: str) -> bool:
    return mark_interaction_thread_resolved(store, question_ref, at=at, response_ref=response_ref)


def apply_scene_action_record(store: Any, summary: object, *, at: str) -> dict[str, Any] | None:
    record = parse_scene_action_summary(summary)
    if record is None:
        return None
    action = str(record.get("action"))
    if action == "open":
        player = _read_optional_json(store, "state/player.json")
        location = player.get("location") if isinstance(player, Mapping) else None
        if not isinstance(location, str) or not location:
            raise ValueError("scene session requires the player's exact current location")
        digest = str(record.get("surface_digest") or "")[:24]
        session = start_scene_session(
            store,
            session_ref=f"scene_session_{digest}",
            kind=str(record.get("kind")),
            location_ref=location,
            participant_refs=[str(x) for x in record.get("participant_refs", []) if isinstance(x, str)],
            started_at=at,
            process_ref=record.get("process_ref") if isinstance(record.get("process_ref"), str) else None,
            purpose=record.get("purpose") if isinstance(record.get("purpose"), str) else None,
            agenda=[str(x) for x in record.get("agenda", []) if isinstance(x, str)],
        )
        return {"record_kind": "scene_session_open", "session_ref": session.get("session_ref")}
    session = active_scene_session(store)
    if session is None or str(session.get("session_ref")) != str(record.get("session_ref")):
        raise ValueError("scene action does not match active session")
    if action == "close":
        session_ref = str(session.get("session_ref"))
        lifecycle = close_active_scene(store, at=at, reason=str(record.get("close_reason"))) or {}
        return {
            "record_kind": "scene_session_close",
            "session_ref": session_ref,
            "abandoned_question_count": int(lifecycle.get("abandoned_question_count", 0) or 0),
        }
    if action == "record_fact":
        fact = record_scene_fact(
            store,
            surface_digest=str(record.get("surface_digest") or ""),
            at=at,
            actor_ref=str(record.get("actor_ref")),
            summary=str(record.get("description")),
            fact_kind=str(record.get("fact_kind")),
            session_ref=str(record.get("session_ref")),
            participant_refs=[str(x) for x in record.get("participant_refs", []) if isinstance(x, str)],
            basis_refs=[str(x) for x in record.get("basis_refs", []) if isinstance(x, str)],
            improvised_prop=record.get("improvised_prop") if isinstance(record.get("improvised_prop"), Mapping) else None,
        )
        return {
            "record_kind": "reversible_scene_fact",
            "fact_ref": fact.get("fact_ref"),
            "session_ref": fact.get("session_ref"),
            "mechanical_consequence_authority": False,
        }
    speech = record_attributed_speech(
        store,
        surface_digest=str(record.get("surface_digest") or ""),
        at=at,
        speaker_ref=str(record.get("speaker_ref")),
        statement=str(record.get("statement")),
        speech_kind=str(record.get("speech_kind")),
        session_ref=str(record.get("session_ref")),
        basis_refs=[str(x) for x in record.get("basis_refs", []) if isinstance(x, str)],
        resolves_thread_ref=record.get("resolves_thread_ref") if isinstance(record.get("resolves_thread_ref"), str) else None,
        resolves_question_ref=record.get("resolves_question_ref") if isinstance(record.get("resolves_question_ref"), str) else None,
    )
    thread_ref = speech.get("resolves_thread_ref")
    if isinstance(thread_ref, str):
        mark_interaction_thread_resolved(store, thread_ref, at=at, response_ref=str(speech.get("speech_ref")))
    return {"record_kind": "attributed_scene_speech", "speech_ref": speech.get("speech_ref"), "session_ref": speech.get("session_ref")}

def translate_interaction_command(command: CommandEnvelope) -> CommandEnvelope:
    summary = interaction_attempt_summary(command, command.payload)
    return CommandEnvelope(
        campaign_id=command.campaign_id,
        request_id=command.request_id,
        actor_id=command.actor_id,
        command_type="scene_consequence",
        expected_revision=command.expected_revision,
        submitted_at=command.submitted_at,
        payload={"summary": summary},
        mode=command.mode,
    )


def _format_triggered_interaction(event_ref: str, raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping) or raw.get("status") != "triggered":
        return None
    kind = str(raw.get("kind", ""))
    if kind not in _TRIGGERED_INTERACTION_KINDS:
        return None
    # Message/response events are player-facing handles only when they were
    # actually delivered to Tang Wei.  The causal registry can contain other
    # actors' correspondence; mere existence in that owner must never grant Wei
    # knowledge of it or a remote reply channel to its sender.
    if kind in {"message", "audience_response", "institutional_response", "petition_response"}:
        target_ref = raw.get("target_ref")
        if target_ref != "char_tang_wei":
            return None
    record = {
        "interaction_ref": str(raw.get("event_ref") or event_ref),
        "kind": kind,
        "status": "triggered",
        "triggered_at": raw.get("triggered_at"),
        "summary": raw.get("summary"),
        "provenance": raw.get("provenance"),
    }
    for key in ("arc_ref", "source_event_ref", "delivery", "operation_ref", "campaign_command_cycle_ref", "campaign_command_context", "present_person_refs"):
        if key in raw:
            record[key] = raw.get(key)
    return record


def _triggered_interaction_rows(store, *, scan_limit: int | None = None) -> list[dict[str, Any]]:
    """Discover player-facing triggered events across hot and archived storage.

    The newest-first causal iterator reads only as many deterministic archive
    segments as needed for the requested page.  An unread report cannot vanish
    merely because unrelated newer causal traffic pushed it out of the hot head.
    """
    rows: list[dict[str, Any]] = []
    for event_ref, raw in iter_causal_events_newest(store, kinds=_TRIGGERED_INTERACTION_KINDS):
        record = _format_triggered_interaction(str(event_ref), raw)
        if record is not None:
            rows.append(record)
            if scan_limit is not None and len(rows) >= max(0, int(scan_limit)):
                break
    return rows


def triggered_interaction_handles(store, *, limit: int = HOT_INTERACTION_LIMIT) -> tuple[list[dict[str, Any]], int]:
    bounded = max(1, min(int(limit), 32))
    rows = _triggered_interaction_rows(store, scan_limit=bounded)
    total = causal_event_kind_count_from_reader(store, _TRIGGERED_INTERACTION_KINDS)
    # Iterator order is newest-first; public handles retain chronological order.
    return list(reversed(rows)), total


def triggered_interaction_page(store, *, cursor: str | None = None, limit: int = 20) -> dict[str, Any]:
    if cursor is None:
        offset = 0
    elif isinstance(cursor, str) and cursor.isdigit() and len(cursor) <= 12:
        offset = int(cursor)
    else:
        raise ValueError("interaction page cursor is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 64:
        raise ValueError("interaction page limit is invalid")
    total = causal_event_kind_count_from_reader(store, _TRIGGERED_INTERACTION_KINDS)
    rows = _triggered_interaction_rows(store, scan_limit=offset + limit)
    page = rows[offset:offset + limit]
    next_offset = offset + len(page)
    return {
        "cursor": cursor,
        "count": total,
        "returned": len(page),
        "truncated": next_offset < total,
        "next_cursor": str(next_offset) if next_offset < total else None,
        "interaction_handles": page,
    }


def triggered_interaction_record(store, interaction_ref: str) -> dict[str, Any] | None:
    raw = get_causal_event_from_reader(store, interaction_ref)
    return _format_triggered_interaction(interaction_ref, raw)


def _read_optional_json(store, path: str) -> Any:
    if hasattr(store, "read_optional"):
        return store.read_optional(path)
    if hasattr(store, "read_json"):
        try:
            return store.read_json(path)
        except FileNotFoundError:
            return None
    raise TypeError("interaction reader does not support JSON reads")


def person_owner_path(store, person_ref: str) -> str | None:
    """Resolve a persistent person without relying on an ID naming convention."""
    owner_index = _read_optional_json(store, "state/index/owner-index.json")
    owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
    path = owners.get(person_ref) if isinstance(owners, Mapping) else None
    if not isinstance(path, str):
        return None
    if path == "state/player.json" or path.startswith("state/char/"):
        return path
    if not path.startswith("state/person/"):
        return None
    record = _read_optional_json(store, path)
    if not isinstance(record, Mapping) or str(record.get("schema", "")) not in _PERSON_OWNER_SCHEMAS:
        return None
    return path


def recent_interaction_attempts(
    store,
    actor_id: str,
    *,
    limit: int = HOT_ATTEMPT_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """Read recent typed attempts from the bounded routing ledger."""
    rows_by_ref: dict[str, dict[str, Any]] = {}
    ledger = _read_optional_json(store, INTERACTION_ATTEMPT_LEDGER_PATH)
    if isinstance(ledger, Mapping):
        raw_rows = ledger.get("attempts", [])
        if isinstance(raw_rows, list):
            for row in raw_rows:
                if not isinstance(row, Mapping) or row.get("actor_id") != actor_id:
                    continue
                ref = str(row.get("event_id", "")) or interaction_attempt_record_ref(row)
                rows_by_ref[ref] = _normalized_attempt_row(row)
    rows = sorted(rows_by_ref.values(), key=lambda row: (str(row.get("at", "")), str(row.get("event_id", ""))))
    bounded = max(1, min(int(limit), INTERACTION_ATTEMPT_LEDGER_LIMIT))
    total = max(len(rows), int(ledger.get("total_recorded", 0)) if isinstance(ledger, Mapping) else 0)
    return rows[-bounded:], total


def active_scene_interaction_attempts(
    store,
    actor_id: str,
    session: Mapping[str, Any] | None,
    *,
    limit: int = HOT_ACTIVE_THREAD_LIMIT,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Read the newest unresolved attempts named by the active scene owner.

    The generic recent-attempt window is intentionally tiny and may contain
    unrelated interactions.  Live conversation continuity must instead route
    through the session's exact open-thread refs, otherwise a still-unanswered
    request can disappear merely because later attempts filled the hot window.
    """
    if not isinstance(session, Mapping):
        return [], 0, False
    session_ref = session.get("session_ref")
    if not isinstance(session_ref, str) or not session_ref:
        return [], 0, False
    present_targets = {
        str(ref) for ref in session.get("participant_refs", [])
        if isinstance(ref, str) and ref
    }
    raw_refs = session.get("open_thread_refs", session.get("open_question_refs", []))
    refs = [str(ref) for ref in raw_refs if isinstance(ref, str) and ref]
    if not refs:
        return [], 0, False

    ledger = _read_optional_json(store, INTERACTION_ATTEMPT_LEDGER_PATH)
    rows_by_ref: dict[str, dict[str, Any]] = {}
    if isinstance(ledger, Mapping):
        raw_rows = ledger.get("attempts", [])
        if isinstance(raw_rows, list):
            wanted = set(refs)
            for raw in raw_rows:
                if not isinstance(raw, Mapping) or raw.get("actor_id") != actor_id:
                    continue
                ref = str(raw.get("event_id", "")) or interaction_attempt_record_ref(raw)
                if ref not in wanted:
                    continue
                row = _normalized_attempt_row(raw)
                if row.get("thread_status", "open") != "open" or row.get("scene_session_ref") != session_ref:
                    continue
                # The durable session may retain a departed participant so an
                # unanswered request can resume if that person returns.  The
                # hot scene surface, however, must expose only threads whose
                # exact target is physically present in the fresh projected
                # session.  Otherwise the GM can accidentally answer for a
                # person who has already left the room.
                if present_targets and str(row.get("target_ref") or "") not in present_targets:
                    continue
                rows_by_ref[ref] = row

    active_refs = [ref for ref in refs if ref in rows_by_ref]
    total = len(active_refs)
    bounded = max(1, min(int(limit), HOT_ACTIVE_THREAD_LIMIT))
    # Session refs are append ordered.  Project newest first so the most recent
    # unresolved conversational move is always the first item the GM sees.
    selected_refs = list(reversed(active_refs))[:bounded]
    rows = [rows_by_ref[ref] for ref in selected_refs if ref in rows_by_ref]
    truncated = total > len(selected_refs)
    return rows, total, truncated


def active_scene_thread_page(store, *, cursor: str | None = None, limit: int = HOT_ACTIVE_THREAD_LIMIT) -> dict[str, Any]:
    """Page every unresolved player-authored thread in the exact active scene.

    The ordinary play-context window intentionally shows only the newest live
    threads.  When that window truncates, this progressive read recovers older
    unresolved requests/questions/proposals from the authoritative active
    session plus the attempt ledger without turning either projection into
    world-outcome authority.
    """
    try:
        offset = 0 if cursor in (None, "") else int(str(cursor))
    except ValueError as exc:
        raise ValueError("scene thread cursor is invalid") from exc
    if offset < 0 or isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 64:
        raise ValueError("scene thread page is invalid")
    session = active_scene_session(store)
    if not isinstance(session, Mapping):
        raise ValueError("no active scene session")
    session_ref = str(session.get("session_ref") or "")
    refs = [
        str(ref) for ref in session.get("open_thread_refs", session.get("open_question_refs", []))
        if isinstance(ref, str) and ref
    ]
    page_refs = refs[offset:offset + limit]
    ledger = _read_optional_json(store, INTERACTION_ATTEMPT_LEDGER_PATH)
    rows_by_ref: dict[str, dict[str, Any]] = {}
    if isinstance(ledger, Mapping):
        raw_rows = ledger.get("attempts", [])
        if isinstance(raw_rows, list):
            wanted = set(page_refs)
            for raw in raw_rows:
                if not isinstance(raw, Mapping):
                    continue
                ref = str(raw.get("event_id", "")) or interaction_attempt_record_ref(raw)
                if ref not in wanted:
                    continue
                row = _normalized_attempt_row(raw)
                if row.get("thread_status", "open") == "open" and row.get("scene_session_ref") == session_ref:
                    rows_by_ref[ref] = row
    threads = [rows_by_ref[ref] for ref in page_refs if ref in rows_by_ref]
    next_offset = offset + len(page_refs)
    return {
        "session_ref": session_ref,
        "cursor": str(offset),
        "count": len(refs),
        "returned": len(threads),
        "truncated": next_offset < len(refs),
        "next_cursor": str(next_offset) if next_offset < len(refs) else None,
        "threads": threads,
        "authority": False,
        "mechanical_consequence_authority": False,
    }


def _dedupe_handles(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ref: dict[str, dict[str, Any]] = {}
    for item in values:
        ref = str(item.get("interaction_ref", ""))
        if ref:
            by_ref[ref] = item
    return list(by_ref.values())


def _scene_handle_refs(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return identity/timing pointers for facts already carried in top-level handles.

    Fresh runtime scenes and ``interaction_handles`` are delivered in the same
    play-context response. Repeating each report's full summary inside several
    scene buckets materially bloats every turn without adding authority. Scene
    buckets therefore point at the exact visible handle; the top-level handle
    remains the bounded player-facing summary source and exact inspection/paging
    remains available when more detail is needed.
    """
    return [
        {
            key: item.get(key)
            for key in ("interaction_ref", "kind", "triggered_at")
            if item.get(key) is not None
        }
        for item in values
    ]


def fresh_runtime_projection(
    context: Mapping[str, Any],
    handles: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    campaign = context["campaign"]
    player = context["player"]
    location = player.get("location")
    colocated_refs = [
        str(item.get("formation_ref"))
        for item in context.get("controlled_formations", [])
        if item.get("location_ref") == location and isinstance(item.get("formation_ref"), str)
    ]
    current_handles = [item for item in handles if item.get("triggered_at") == campaign.get("world_time")]
    recent_world_reports = [item for item in handles if item.get("kind") == "world_arc_report"][-3:]
    pressures = _dedupe_handles(current_handles + recent_world_reports)
    active_session = context.get("active_scene_session") if isinstance(context.get("active_scene_session"), Mapping) else None
    active_session_ref = active_session.get("session_ref") if isinstance(active_session, Mapping) else None
    active_thread_rows = sorted(
        (
            item for item in attempts
            if item.get("thread_status", "open") == "open"
            and active_session_ref is not None
            and item.get("scene_session_ref") == active_session_ref
            and isinstance(item.get("player_statement"), str) and item.get("player_statement")
        ),
        key=lambda item: (str(item.get("at", "")), str(item.get("event_id", ""))),
        reverse=True,
    )[:HOT_ACTIVE_THREAD_LIMIT]
    active_threads = [
        {
            key: item.get(key)
            for key in ("event_id", "at", "action", "target_ref", "player_statement", "posture", "topic", "scopes", "scene_session_ref")
            if item.get(key) not in (None, "", [])
        }
        for item in active_thread_rows
    ]
    declared_thread_count = active_session.get("open_thread_count") if isinstance(active_session, Mapping) else None
    active_thread_count = (
        int(declared_thread_count)
        if isinstance(declared_thread_count, int) and not isinstance(declared_thread_count, bool) and declared_thread_count >= 0
        else len(active_thread_rows)
    )
    active_questions = [
        {
            key: item.get(key)
            for key in ("event_id", "at", "target_ref", "player_statement", "posture", "topic", "scopes", "scene_session_ref")
            if item.get(key) not in (None, "", [])
        }
        for item in active_threads
        if item.get("action") == "ask"
    ]
    return {
        "projection_status": "fresh_runtime_projection",
        "projection_provenance": "exact_current_owners_triggered_events_and_typed_player_attempts",
        "projected_at": campaign.get("world_time"),
        "projected_revision": campaign.get("revision"),
        "scene_id": f"runtime_projection_r{campaign.get('revision')}",
        "summary": "Current player-visible state reconstructed from authoritative owners after the authored scene projection became stale.",
        "location": location,
        "location_id": location,
        # Exact formation summaries already exist once in the top-level bounded
        # controlled_formations window. The scene needs only co-location refs.
        "physical_scene": {"controlled_formation_refs_at_player_location": colocated_refs},
        "observable_pressures": _scene_handle_refs(pressures),
        "player_observable_state": {
            "location": location,
            "health": player.get("health"),
            "fatigue": player.get("fatigue"),
        },
        "scene_local_narration_contract": SCENE_LOCAL_NARRATION_CONTRACT,
        "unresolved_decision": None,
        "known_clock_boundaries": [],
        "active_threads": active_threads,
        "active_thread_count": active_thread_count,
        "active_threads_truncated": active_thread_count > len(active_threads),
        "active_questions": active_questions,
        "pending_information_paths": [],
    }


__all__ = [
    "HOT_ACTIVE_THREAD_LIMIT", "HOT_ATTEMPT_LIMIT", "HOT_FORMATION_LIMIT", "HOT_INFORMATION_LIMIT", "HOT_INTERACTION_LIMIT",
    "active_scene_thread_page",
    "INTERACTION_ACTIONS", "INTERACTION_PAYLOAD_KEYS", "FORBIDDEN_OUTCOME_KEYS",
    "SCENE_LOCAL_NARRATION_CONTRACT",
    "SCENE_ACTION_PAYLOAD_KEYS", "SCENE_SESSION_ACTIONS",
    "abandon_session_questions", "apply_scene_action_record", "fresh_runtime_projection",
    "interaction_attempt_ref", "interaction_attempt_summary", "mark_interaction_question_resolved",
    "active_scene_interaction_attempts", "parse_interaction_attempt_summary", "parse_scene_action_summary", "recent_interaction_attempts",
    "record_interaction_attempt", "scene_action_summary", "translate_interaction_command",
    "translate_scene_action_command", "triggered_interaction_handles", "triggered_interaction_page",
    "triggered_interaction_record", "validate_interaction_payload", "validate_scene_action_payload",
    "person_owner_path",
]
