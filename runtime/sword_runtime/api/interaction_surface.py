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
from sword_runtime.history_store import recent_history_events
from sword_runtime.causal_event_store import (
    causal_event_kind_count_from_reader,
    get_causal_event_from_reader,
    iter_causal_events_newest,
)

INTERACTION_ACTIONS = frozenset({
    "present", "request", "petition", "report", "ask", "offer", "decline",
    "comply", "withdraw", "proceed", "seek_contact",
})
INTERACTION_PAYLOAD_KEYS = frozenset({
    "target_ref", "action", "process_ref", "player_statement",
    "formation_refs", "posture",
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
INTERACTION_ATTEMPT_PREFIX = "sword-interaction-attempt.v1 "
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_TRIGGERED_INTERACTION_KINDS = frozenset({
    "institutional_response", "petition_response", "message", "audience_response",
    "world_arc_report",
})

# Live play needs a clear boundary between durable world truth and ordinary
# reversible scene flow. An attempt-only interaction record correctly prevents
# caller prose from becoming rank, access, consent, appointment, information,
# or another persistent NPC/world outcome. It must not, however, turn every
# greeting, follow-up question, examiner prompt, gesture, or procedural exchange
# inside an already-established interaction into a transaction boundary.
SCENE_LOCAL_NARRATION_CONTRACT = {
    "mode": "presentation_only_reversible",
    "rule": (
        "Within an already-established live interaction or institutional process, "
        "the GM may continue ordinary scene-local NPC behavior and dialogue without "
        "a gameplay write when the beat is reversible and does not establish persistent campaign truth."
    ),
    "allowed_examples": [
        "routine acknowledgements, objections, clarifying questions, and follow-up questions",
        "examiner prompts and ordinary nonbinding reactions during an already-established review",
        "brief procedural directions within access that is already established",
        "gestures, seating, pauses, unnamed attendants, and short movement inside the established scene",
    ],
    "persistent_boundary_examples": [
        "new access, permission, acceptance, refusal, or final institutional judgment",
        "rank, office, appointment, vacancy, command authority, troop custody, or deployment authority",
        "relationship or reputation change",
        "a new information claim whose truth must persist beyond the scene",
        "money, equipment, injury, death, formation, logistics, territory, or elapsed mechanical time",
        "a promise, contract, obligation, or other durable consequence",
    ],
    "interaction_attempt_rule": (
        "world_response_status:not_established_by_attempt blocks persistent NPC/world outcomes; "
        "it does not require the GM to stop before reversible scene-local dialogue or questions."
    ),
    "continuation_rule": (
        "Do not stop a live scene merely because the latest interaction_action is attempt-only when "
        "the next beat is ordinary reversible continuation. Stop and require runtime authority only "
        "when carrying a persistent consequence forward."
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
    return {
        "target_ref": target_ref,
        "action": action,
        "process_ref": process_ref,
        "player_statement": statement,
        "formation_refs": formation_refs,
        "posture": posture,
    }


def interaction_attempt_summary(command: CommandEnvelope, payload: Mapping[str, Any]) -> str:
    """Encode a typed, attempt-only record with the original surface digest."""
    record = validate_interaction_payload(payload)
    attempt = {
        "schema": "sword-interaction-attempt.v1",
        "surface_digest": command.digest,
        "request_id": command.request_id,
        "actor_id": command.actor_id,
        "target_ref": record["target_ref"],
        "action": record["action"],
        "process_ref": record["process_ref"],
        "player_statement": record["player_statement"],
        "formation_refs": record["formation_refs"],
        "posture": record["posture"],
        "world_response_status": "not_established_by_attempt",
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
    record = {
        "interaction_ref": str(raw.get("event_ref") or event_ref),
        "kind": kind,
        "status": "triggered",
        "triggered_at": raw.get("triggered_at"),
        "summary": raw.get("summary"),
        "provenance": raw.get("provenance"),
    }
    for key in ("arc_ref", "source_event_ref", "delivery"):
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


def recent_interaction_attempts(
    store,
    actor_id: str,
    *,
    limit: int = HOT_ATTEMPT_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    try:
        events = recent_history_events(store, 512)
    except FileNotFoundError:
        return [], 0
    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        attempt = parse_interaction_attempt_summary(event.get("summary"))
        if attempt is None or attempt.get("actor_id") != actor_id:
            continue
        rows.append({
            "event_id": event.get("event_id"),
            "at": event.get("at"),
            **attempt,
        })
    bounded = max(1, min(int(limit), 32))
    return rows[-bounded:], len(rows)


def _dedupe_handles(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ref: dict[str, dict[str, Any]] = {}
    for item in values:
        ref = str(item.get("interaction_ref", ""))
        if ref:
            by_ref[ref] = item
    return list(by_ref.values())


def fresh_runtime_projection(
    context: Mapping[str, Any],
    handles: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    campaign = context["campaign"]
    player = context["player"]
    location = player.get("location")
    colocated = [
        {
            "formation_ref": item.get("formation_ref"),
            "name": item.get("name"),
            "personnel": item.get("personnel"),
            "commander_ref": item.get("commander_ref"),
            "mobilized": item.get("mobilized"),
        }
        for item in context.get("controlled_formations", [])
        if item.get("location_ref") == location
    ]
    current_handles = [item for item in handles if item.get("triggered_at") == campaign.get("world_time")]
    recent_world_reports = [item for item in handles if item.get("kind") == "world_arc_report"][-3:]
    pressures = _dedupe_handles(current_handles + recent_world_reports)
    return {
        "projection_status": "fresh_runtime_projection",
        "projection_provenance": "exact_current_owners_triggered_events_and_typed_player_attempts",
        "projected_at": campaign.get("world_time"),
        "projected_revision": campaign.get("revision"),
        "scene_id": f"runtime_projection_r{campaign.get('revision')}",
        "summary": "Current player-visible state reconstructed from authoritative owners after the authored scene projection became stale.",
        "location": location,
        "location_id": location,
        "physical_scene": {"controlled_formations_at_player_location": colocated},
        "observable_pressures": pressures,
        "player_observable_state": {
            "location": location,
            "health": player.get("health"),
            "fatigue": player.get("fatigue"),
        },
        "scene_local_narration_contract": SCENE_LOCAL_NARRATION_CONTRACT,
        "unresolved_decision": None,
        "known_clock_boundaries": [],
        "active_questions": [],
        "available_reports": [
            {key: item.get(key) for key in ("interaction_ref", "kind", "triggered_at", "summary") if item.get(key) is not None}
            for item in handles
        ],
        "pending_information_paths": [],
        "recent_reveals": [
            {key: item.get(key) for key in ("interaction_ref", "kind", "triggered_at", "summary") if item.get(key) is not None}
            for item in pressures
        ],
        "recent_player_actions": [
            {key: item.get(key) for key in ("event_id", "at", "request_id", "action", "target_ref", "process_ref") if item.get(key) is not None}
            for item in attempts
        ],
        "unresolved_hooks": recent_world_reports,
    }


__all__ = [
    "HOT_ATTEMPT_LIMIT", "HOT_FORMATION_LIMIT", "HOT_INFORMATION_LIMIT", "HOT_INTERACTION_LIMIT",
    "INTERACTION_ACTIONS", "INTERACTION_PAYLOAD_KEYS", "FORBIDDEN_OUTCOME_KEYS",
    "SCENE_LOCAL_NARRATION_CONTRACT",
    "fresh_runtime_projection", "interaction_attempt_summary", "parse_interaction_attempt_summary",
    "recent_interaction_attempts", "translate_interaction_command", "triggered_interaction_handles",
    "triggered_interaction_page", "triggered_interaction_record", "validate_interaction_payload",
]
