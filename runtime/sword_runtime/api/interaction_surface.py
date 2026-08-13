"""Player-safe interaction and live scene projection helpers.

This module deliberately does not own campaign truth. It validates caller-owned
interaction intent, translates it into a legacy attempt-only event for the
transaction engine, and builds bounded read projections exclusively from exact
current owners and already-triggered event-registry facts.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.commands import CommandEnvelope

INTERACTION_ACTIONS = frozenset({
    "present", "request", "petition", "report", "ask", "offer", "decline",
    "comply", "withdraw", "wait_for_reply", "proceed",
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


def _walk_forbidden(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).strip().lower() in FORBIDDEN_OUTCOME_KEYS:
                return True
            if _walk_forbidden(child):
                return True
    elif isinstance(value, list):
        return any(_walk_forbidden(item) for item in value)
    return False


def validate_interaction_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    keys = set(payload)
    if not keys <= INTERACTION_PAYLOAD_KEYS:
        raise ValueError("interaction_action contains unsupported caller fields")
    if _walk_forbidden(payload):
        raise ValueError("interaction_action may not supply world or NPC outcomes")
    target_ref = payload.get("target_ref")
    action = payload.get("action")
    if not isinstance(target_ref, str) or not target_ref or len(target_ref) > 160:
        raise ValueError("interaction_action requires one exact target_ref")
    if not isinstance(action, str) or action not in INTERACTION_ACTIONS:
        raise ValueError("interaction_action action is unsupported")
    process_ref = payload.get("process_ref")
    if process_ref is not None and (not isinstance(process_ref, str) or not process_ref or len(process_ref) > 160):
        raise ValueError("interaction_action process_ref is invalid")
    statement = payload.get("player_statement")
    if statement is not None and (not isinstance(statement, str) or not statement.strip() or len(statement) > 2000 or "\x00" in statement):
        raise ValueError("interaction_action player_statement is invalid")
    posture = payload.get("posture")
    if posture is not None and (not isinstance(posture, str) or not posture.strip() or len(posture) > 500 or "\x00" in posture):
        raise ValueError("interaction_action posture is invalid")
    formation_refs = payload.get("formation_refs", [])
    if not isinstance(formation_refs, list) or len(formation_refs) > 128:
        raise ValueError("interaction_action formation_refs is invalid")
    if any(not isinstance(ref, str) or not ref or len(ref) > 160 for ref in formation_refs):
        raise ValueError("interaction_action formation_refs is invalid")
    if len(set(formation_refs)) != len(formation_refs):
        raise ValueError("interaction_action formation_refs must be unique")
    return {
        "target_ref": target_ref,
        "action": action,
        "process_ref": process_ref,
        "player_statement": statement.strip() if isinstance(statement, str) else None,
        "formation_refs": list(formation_refs),
        "posture": posture.strip() if isinstance(posture, str) else None,
    }


def interaction_summary(actor_id: str, payload: Mapping[str, Any]) -> str:
    """Render only player-owned intent. Never render an external response."""
    record = validate_interaction_payload(payload)
    parts = [f"{actor_id} performs interaction action '{record['action']}' toward exact ref {record['target_ref']}."]
    if record["process_ref"]:
        parts.append(f"The declared process anchor is {record['process_ref']}.")
    if record["formation_refs"]:
        parts.append("The declared accompanying controlled formations are: " + ", ".join(record["formation_refs"]) + ".")
    if record["posture"]:
        parts.append("Player-declared posture: " + record["posture"])
    if record["player_statement"]:
        parts.append("Player-declared statement: " + record["player_statement"])
    parts.append("No NPC response, access, appointment, rank, vacancy, acceptance, permission, or other world outcome is established by this attempt record.")
    return " ".join(parts)


def translate_interaction_command(command: CommandEnvelope) -> CommandEnvelope:
    payload = validate_interaction_payload(command.payload)
    return CommandEnvelope(
        campaign_id=command.campaign_id,
        request_id=command.request_id,
        actor_id=command.actor_id,
        command_type="scene_consequence",
        expected_revision=command.expected_revision,
        submitted_at=command.submitted_at,
        payload={"summary": interaction_summary(command.actor_id, payload)},
        mode=command.mode,
    )


def triggered_interaction_handles(store, *, limit: int = HOT_INTERACTION_LIMIT) -> list[dict[str, Any]]:
    try:
        registry = store.read_json("state/event/events-messages-and-movement.json")
    except FileNotFoundError:
        return []
    causal = registry.get("causal_events", {}) if isinstance(registry, Mapping) else {}
    if not isinstance(causal, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for event_ref, raw in causal.items():
        if not isinstance(raw, Mapping) or raw.get("status") != "triggered":
            continue
        kind = str(raw.get("kind", ""))
        if kind not in {"institutional_response", "petition_response", "message", "audience_response"}:
            continue
        rows.append({
            "interaction_ref": str(raw.get("event_ref") or event_ref),
            "kind": kind,
            "status": "triggered",
            "triggered_at": raw.get("triggered_at"),
            "summary": raw.get("summary"),
            "provenance": raw.get("provenance"),
        })
    rows.sort(key=lambda item: (str(item.get("triggered_at") or ""), str(item["interaction_ref"])))
    return rows[-max(1, min(int(limit), 32)):]


def fresh_runtime_projection(context: Mapping[str, Any], handles: list[dict[str, Any]]) -> dict[str, Any]:
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
    return {
        "projection_status": "fresh_runtime_projection",
        "projection_provenance": "exact_current_owners_and_triggered_event_registry",
        "projected_at": campaign.get("world_time"),
        "projected_revision": campaign.get("revision"),
        "scene_id": f"runtime_projection_r{campaign.get('revision')}",
        "summary": "Current player-visible state reconstructed from authoritative owners after the authored scene projection became stale.",
        "location": location,
        "location_id": location,
        "physical_scene": {"controlled_formations_at_player_location": colocated},
        "observable_pressures": [item for item in current_handles],
        "player_observable_state": {
            "location": location,
            "health": player.get("health"),
            "fatigue": player.get("fatigue"),
        },
        "unresolved_decision": None,
        "known_clock_boundaries": [],
        "active_questions": [],
        "available_reports": [item for item in current_handles],
        "pending_information_paths": [],
        "recent_reveals": [item for item in current_handles],
        "unresolved_hooks": [],
    }


__all__ = [
    "HOT_FORMATION_LIMIT", "HOT_INFORMATION_LIMIT", "HOT_INTERACTION_LIMIT",
    "INTERACTION_ACTIONS", "INTERACTION_PAYLOAD_KEYS", "FORBIDDEN_OUTCOME_KEYS",
    "fresh_runtime_projection", "interaction_summary", "translate_interaction_command",
    "triggered_interaction_handles", "validate_interaction_payload",
]
