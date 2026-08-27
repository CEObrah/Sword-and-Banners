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
INTERACTION_ATTEMPT_LEDGER_LIMIT = 128
INTERACTION_ATTEMPT_LEDGER_PATH = "state/index/interaction-attempts.json"
INTERACTION_ATTEMPT_PREFIX = "sword-interaction-attempt.v1 "
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
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
        "surface_digest": command.semantic_digest,
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
    rows = [dict(row) for row in raw_rows if isinstance(row, Mapping)] if isinstance(raw_rows, list) else []
    if any(str(row.get("event_id", "")) == ref for row in rows):
        return ref
    persisted_attempt = {key: value for key, value in attempt.items() if key != "schema"}
    rows.append({"event_id": ref, "at": at, **persisted_attempt})
    ledger["attempts"] = rows[-INTERACTION_ATTEMPT_LEDGER_LIMIT:]
    ledger["total_recorded"] = max(int(ledger.get("total_recorded", 0)), len(rows))
    store.put(INTERACTION_ATTEMPT_LEDGER_PATH, ledger)
    return ref


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
                rows_by_ref[ref] = dict(row)
    rows = sorted(rows_by_ref.values(), key=lambda row: (str(row.get("at", "")), str(row.get("event_id", ""))))
    bounded = max(1, min(int(limit), INTERACTION_ATTEMPT_LEDGER_LIMIT))
    total = max(len(rows), int(ledger.get("total_recorded", 0)) if isinstance(ledger, Mapping) else 0)
    return rows[-bounded:], total


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
        "active_questions": [],
        "pending_information_paths": [],
    }


__all__ = [
    "HOT_ATTEMPT_LIMIT", "HOT_FORMATION_LIMIT", "HOT_INFORMATION_LIMIT", "HOT_INTERACTION_LIMIT",
    "INTERACTION_ACTIONS", "INTERACTION_PAYLOAD_KEYS", "FORBIDDEN_OUTCOME_KEYS",
    "SCENE_LOCAL_NARRATION_CONTRACT",
    "fresh_runtime_projection", "interaction_attempt_ref", "interaction_attempt_summary", "parse_interaction_attempt_summary",
    "recent_interaction_attempts", "record_interaction_attempt", "translate_interaction_command", "triggered_interaction_handles",
    "triggered_interaction_page", "triggered_interaction_record", "validate_interaction_payload",
]
