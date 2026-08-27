"""Campaign-wide command rhythm above Tang Wei's nested field army.

This module connects existing campaign operations, exact commanders, battlefield
reports, operational orders, military supply, and chronology into a first-class
headquarters cycle.  It owns no troops, casualties, territory, battle outcomes,
or hidden intelligence.  Its exact cycle owner records only command-conference
attendance, delivered superior orders, routine upward reports, and daily briefing
snapshots derived from the existing authoritative owners.

The command chain is deliberately two-way:

    state / named supreme commander
        -> campaign order / mission
        -> Tang Wei field command
        -> Tang Wei's nested command groups and formations

and routine reports flow back upward without silently choosing Wei's tactics.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.battle_command import _command_group_for_formation
from sword_runtime.campaign_briefing import (
    build_campaign_dossier,
    campaign_arc_ref,
    safe_campaign_context,
)
from sword_runtime.court_presence import court_profile, court_session_projection
from sword_runtime.causal_event_store import (
    get_causal_event,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.environment import next_sunrise_after, next_sunset_after
from sword_runtime.military_supply import evaluate_military_supply
from sword_runtime.history_store import iter_history_events, write_history_index
from sword_runtime.sim.calendar import CampaignTime

_PLAYER_REF = "char_tang_wei"
_RUNTIME_PATH = "state/runtime.json"
_OWNER_INDEX = "state/index/owner-index.json"
_OPERATION_INDEX = "state/operations/index.json"
_MECHANICS_PATH = "game/data/mechanics/campaign-command.json"
_ACTIVE_OPERATION_STATUSES = {"active", "mobilizing", "advancing", "engaged", "occupied"}
_COUNCIL_PRIORITY = 38
_SUPERIOR_ORDER_PRIORITY = 39
_AFTER_ACTION_PRIORITY = 40
_DAWN_PRIORITY = 41
_EVENING_PRIORITY = 42
_RETURN_PRIORITY = 43


class _ReadAdapter:
    """Normalize planner-style and repository-store reads for projections."""

    def __init__(self, source: Any):
        self.source = source
        self.PLAYER_ACTOR = getattr(source, "PLAYER_ACTOR", _PLAYER_REF)

    def read(self, path: str) -> Any:
        if hasattr(self.source, "read"):
            return self.source.read(path)
        return self.source.read_json(path)

    def read_optional(self, path: str) -> Any:
        if hasattr(self.source, "read_optional"):
            return self.source.read_optional(path)
        try:
            return self.read(path)
        except (FileNotFoundError, KeyError, OSError, ValueError):
            return None

    def owner_path(self, ref: str) -> str:
        if hasattr(self.source, "owner_path"):
            return self.source.owner_path(ref)
        index = self.read(_OWNER_INDEX)
        owners = index.get("owners") if isinstance(index, Mapping) else None
        path = owners.get(ref) if isinstance(owners, Mapping) else None
        if not isinstance(path, str) or not path:
            raise KeyError(ref)
        return path


def _reader(source: Any) -> Any:
    if hasattr(source, "read") and hasattr(source, "owner_path"):
        return source
    return _ReadAdapter(source)


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def _mechanics(planner: Any) -> Mapping[str, Any]:
    raw = planner.read(_MECHANICS_PATH)
    section = raw.get("campaign_command_cycle") if isinstance(raw, Mapping) else None
    if not isinstance(section, Mapping):
        raise ValueError("campaign command mechanics are missing")
    return section


def _operation_path(planner: Any, operation_ref: str) -> str | None:
    index = planner.read(_OPERATION_INDEX)
    rows = index.get("operations") if isinstance(index, Mapping) else None
    path = rows.get(operation_ref) if isinstance(rows, Mapping) else None
    return str(path) if isinstance(path, str) and path else None


def _load_operation(planner: Any, operation_ref: str) -> tuple[str, dict[str, Any]]:
    path = _operation_path(planner, operation_ref)
    if path is None:
        raise ValueError(f"unknown operation: {operation_ref}")
    raw = planner.read(path)
    if not isinstance(raw, Mapping):
        raise ValueError(f"invalid operation owner: {operation_ref}")
    return path, copy.deepcopy(dict(raw))


def _latest_order(operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    ref = str(operation.get("last_operational_order_ref", ""))
    rows = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        if ref and str(row.get("order_ref", "")) != ref:
            continue
        return row
    return None


def _player_operation_refs(planner: Any) -> list[str]:
    player = planner.read("state/player.json")
    career = player.get("career_state", {}) if isinstance(player, Mapping) else {}
    appointments = career.get("appointments", []) if isinstance(career, Mapping) else []
    refs: list[str] = []
    for row in appointments if isinstance(appointments, list) else []:
        if not isinstance(row, Mapping) or row.get("status") != "active":
            continue
        if row.get("kind") != "qin_field_command" and row.get("kind") != "state_field_command":
            continue
        ref = row.get("operation_ref")
        if isinstance(ref, str) and ref:
            refs.append(ref)
    if refs:
        return list(dict.fromkeys(refs))

    # Older appointments may omit operation_ref.  Follow the exact active context
    # of the player's root field command rather than scanning arbitrary operations.
    try:
        group = planner.read("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    except (FileNotFoundError, KeyError, ValueError):
        return []
    ref = group.get("active_context_ref") if isinstance(group, Mapping) else None
    return [str(ref)] if isinstance(ref, str) and ref else []


def _cycle_ref(operation_ref: str) -> str:
    return f"campaign_command_cycle.{_digest('cycle', operation_ref)}"


def _cycle_path(cycle_ref: str) -> str:
    return f"state/operations/{cycle_ref}.json"


def _read_cycle(planner: Any, operation_ref: str) -> tuple[str, dict[str, Any]] | None:
    ref = _cycle_ref(operation_ref)
    try:
        path = planner.owner_path(ref)
    except (KeyError, FileNotFoundError, ValueError):
        return None
    raw = planner.read_optional(path)
    if not isinstance(raw, Mapping):
        return None
    return path, copy.deepcopy(dict(raw))


def _put_cycle(planner: Any, cycle: Mapping[str, Any]) -> str:
    cycle_ref = str(cycle.get("cycle_ref") or cycle.get("owner_id") or "")
    if not cycle_ref:
        raise ValueError("campaign command cycle lacks cycle_ref")
    path = _cycle_path(cycle_ref)
    index = copy.deepcopy(planner.read(_OWNER_INDEX))
    owners = index.setdefault("owners", {})
    existing = owners.get(cycle_ref)
    if existing is not None and existing != path:
        raise ValueError("campaign command cycle owner route changed")
    owners[cycle_ref] = path
    planner.put(_OWNER_INDEX, index)
    planner.put(path, copy.deepcopy(dict(cycle)))
    return path


def _person(planner: Any, ref: str | None) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(ref, str) or not ref.startswith("char_"):
        return None
    try:
        path = planner.owner_path(ref)
    except (KeyError, FileNotFoundError, ValueError):
        return None
    row = planner.read_optional(path)
    if not isinstance(row, Mapping):
        return None
    return path, copy.deepcopy(dict(row))


def _person_name(planner: Any, ref: str | None) -> str:
    person = _person(planner, ref)
    if person is None:
        return str(ref or "institutional command")
    return str(person[1].get("name") or ref)


def _person_location(planner: Any, ref: str) -> str | None:
    person = _person(planner, ref)
    if person is None:
        return None
    row = person[1]
    if hasattr(planner, "_person_location"):
        value = planner._person_location(row)
        return str(value) if isinstance(value, str) and value else None
    value = row.get("current_location") or row.get("location_ref")
    return str(value) if isinstance(value, str) and value else None


def _set_person_location(planner: Any, ref: str, destination: str) -> bool:
    person = _person(planner, ref)
    if person is None:
        return False
    path, row = person
    if hasattr(planner, "_set_person_location"):
        planner._set_person_location(row, destination)
    elif "current_location" in row:
        row["current_location"] = destination
    else:
        row["location_ref"] = destination
    planner.put(path, row)
    return True


def _operation_commander_refs(planner: Any, operation: Mapping[str, Any], *, include_nested: bool) -> list[str]:
    refs: list[str] = []
    root_ref = operation.get("command_group_ref")
    if isinstance(root_ref, str) and root_ref:
        try:
            group = planner.read(f"state/cmd/command-groups/{root_ref}.json")
        except (FileNotFoundError, KeyError, ValueError):
            group = None
        if isinstance(group, Mapping) and isinstance(group.get("commander_ref"), str):
            refs.append(str(group["commander_ref"]))
    if include_nested:
        for formation_ref in operation.get("formation_refs", []) if isinstance(operation.get("formation_refs"), list) else []:
            if not isinstance(formation_ref, str):
                continue
            group = _command_group_for_formation(planner, formation_ref)
            if isinstance(group, Mapping) and isinstance(group.get("commander_ref"), str):
                refs.append(str(group["commander_ref"]))
                continue
            try:
                formation = planner.read(planner.owner_path(formation_ref))
            except (FileNotFoundError, KeyError, ValueError):
                continue
            commander = formation.get("commander_ref") if isinstance(formation, Mapping) else None
            if isinstance(commander, str) and commander.startswith("char_"):
                refs.append(commander)
    return list(dict.fromkeys(refs))


def _campaign_participants(planner: Any, operation: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    operation_refs = [
        str(ref) for ref in operation.get("campaign_participant_operation_refs", [])
        if isinstance(ref, str) and ref
    ]
    commanders: list[str] = []
    # Tang Wei represents his own field army at the campaign council.  Do not
    # explode his nested hierarchy into peer campaign commanders.
    own_root = operation.get("command_group_ref")
    if isinstance(own_root, str) and own_root:
        try:
            group = planner.read(f"state/cmd/command-groups/{own_root}.json")
        except (FileNotFoundError, KeyError, ValueError):
            group = None
        if isinstance(group, Mapping) and isinstance(group.get("commander_ref"), str):
            commanders.append(str(group["commander_ref"]))
    if _PLAYER_REF not in commanders:
        commanders.insert(0, _PLAYER_REF)

    for ref in operation_refs:
        path = _operation_path(planner, ref)
        row = planner.read_optional(path) if isinstance(path, str) else None
        if not isinstance(row, Mapping) or str(row.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
            continue
        commanders.extend(_operation_commander_refs(planner, row, include_nested=True))
    return operation_refs, list(dict.fromkeys(commanders))


def _coordination_authority(operation: Mapping[str, Any]) -> str:
    explicit = operation.get("coordination_authority_ref")
    if isinstance(explicit, str) and explicit:
        return explicit
    order = _latest_order(operation)
    packet = order.get("mission_packet") if isinstance(order, Mapping) and isinstance(order.get("mission_packet"), Mapping) else None
    value = packet.get("coordination_authority_ref") if isinstance(packet, Mapping) else None
    if isinstance(value, str) and value:
        return value
    owner = operation.get("institutional_owner_ref") or operation.get("administrative_authority")
    return str(owner or "institutional_command")


def _council_forum(planner: Any, operation: Mapping[str, Any], *, default_venue_ref: str) -> dict[str, Any]:
    mechanics = _mechanics(planner)
    forums = mechanics.get("formal_council_forums") if isinstance(mechanics.get("formal_council_forums"), Mapping) else {}
    state_ref = operation.get("institutional_owner_ref") or operation.get("administrative_authority")
    row = forums.get(state_ref) if isinstance(forums, Mapping) and isinstance(state_ref, str) else None
    if not isinstance(row, Mapping):
        return {"forum_kind": "military_headquarters", "venue_ref": default_venue_ref, "court_state_ref": None}
    configured_venue = row.get("venue_ref")
    # A royal-court conference is only selected while the player's exact operation
    # is physically staged at that capital. Once the field army has departed, the
    # daily command cycle follows the player's real HQ rather than dragging court
    # presence into the field.
    if not isinstance(configured_venue, str) or configured_venue != default_venue_ref:
        return {"forum_kind": "military_headquarters", "venue_ref": default_venue_ref, "court_state_ref": None}
    return {
        "forum_kind": str(row.get("forum_kind") or "royal_court"),
        "venue_ref": configured_venue,
        "court_state_ref": row.get("court_state_ref") or state_ref,
        "attendance_rule": row.get("attendance_rule"),
    }


def _supreme_commander(operation: Mapping[str, Any]) -> str | None:
    for key in ("campaign_commander_ref", "supreme_commander_ref"):
        value = operation.get(key)
        if isinstance(value, str) and value.startswith("char_"):
            return value
    return None


def _formal_rank_value(planner: Any, person: Mapping[str, Any]) -> int:
    try:
        rules = planner.read("game/data/mechanics/military-career.json")
    except (FileNotFoundError, KeyError, ValueError):
        return 0
    order = rules.get("formal_rank_order") if isinstance(rules, Mapping) else None
    grade = (person.get("military_rank") or {}).get("grade") if isinstance(person.get("military_rank"), Mapping) else None
    value = order.get(grade) if isinstance(order, Mapping) and isinstance(grade, str) else None
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _current_command_span(person: Mapping[str, Any]) -> int:
    career = person.get("career_state") if isinstance(person.get("career_state"), Mapping) else {}
    value = career.get("current_command_span")
    return max(0, int(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _appoint_supreme_commander_if_needed(
    planner: Any,
    *,
    operation_ref: str,
    cycle: dict[str, Any],
    present_person_refs: list[str],
    at: str,
) -> dict[str, Any] | None:
    """Let the lawful Qin campaign authority appoint a missing supreme commander.

    This is an NPC/institutional decision, not player agency.  Selection uses only
    durable service facts the state itself owns: formal military rank first, then
    current lawful command span, then a stable reference tie-break.  It never uses
    hidden future history, battle outcomes, private motives, or troop ownership.
    """
    existing = cycle.get("supreme_commander_ref")
    if isinstance(existing, str) and existing.startswith("char_"):
        return None
    participant_refs = {
        str(ref) for ref in cycle.get("participant_commander_refs", [])
        if isinstance(ref, str) and ref.startswith("char_")
    }
    candidates: list[tuple[int, int, str, dict[str, Any]]] = []
    for ref in present_person_refs:
        if ref not in participant_refs:
            continue
        person_row = _person(planner, ref)
        if person_row is None:
            continue
        person = person_row[1]
        rank_value = _formal_rank_value(planner, person)
        if rank_value <= 0:
            continue
        candidates.append((rank_value, _current_command_span(person), ref, person))
    if not candidates:
        return None
    # Stable tie-break deliberately favors lexical ref only after rank/span are
    # equal; no hidden random or future-history preference enters the appointment.
    candidates.sort(key=lambda row: (-row[0], -row[1], row[2]))
    rank_value, command_span, selected_ref, selected_person = candidates[0]
    coordination = str(cycle.get("coordination_authority_ref") or "institutional_command")

    op_path, operation = _load_operation(planner, operation_ref)
    operation["campaign_commander_ref"] = selected_ref
    operation["coordination_authority_ref"] = coordination
    operation["campaign_command_assignment"] = {
        "commander_ref": selected_ref,
        "appointed_at": at,
        "appointing_authority_ref": coordination,
        "basis": "formal_rank_then_current_command_span",
        "formal_rank_value": rank_value,
        "current_command_span": command_span,
        "rule": "Campaign command is an operational authority assignment only; it does not transfer formation ownership, manpower, durable rank, or sovereign authority.",
    }
    current_ref = str(operation.get("last_operational_order_ref", ""))
    orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    for row in reversed(orders):
        if not isinstance(row, dict):
            continue
        if current_ref and str(row.get("order_ref", "")) != current_ref:
            continue
        row["superior_commander_ref"] = selected_ref
        row["coordination_authority_ref"] = coordination
        row["command_chain_assigned_at"] = at
        break
    planner.put(op_path, operation)

    for participant_ref in cycle.get("participant_operation_refs", []) if isinstance(cycle.get("participant_operation_refs"), list) else []:
        if not isinstance(participant_ref, str):
            continue
        try:
            participant_path, participant = _load_operation(planner, participant_ref)
        except ValueError:
            continue
        if str(participant.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
            continue
        participant["campaign_commander_ref"] = selected_ref
        participant["coordination_authority_ref"] = coordination
        participant["campaign_command_assignment"] = copy.deepcopy(operation["campaign_command_assignment"])
        planner.put(participant_path, participant)

    cycle["supreme_commander_ref"] = selected_ref
    cycle["superior_command_ref"] = selected_ref
    appointment = copy.deepcopy(operation["campaign_command_assignment"])
    appointment["commander_name"] = str(selected_person.get("name") or selected_ref)

    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    event_id = f"campaign_supreme_command_{_digest('appointment', operation_ref + '|' + selected_ref + '|' + at)}"
    events = history.setdefault("events", [])
    if not any(isinstance(row, Mapping) and row.get("event_id") == event_id for row in events):
        events.append({
            "event_id": event_id,
            "kind": "campaign_supreme_commander_appointed",
            "at": at,
            "operation_ref": operation_ref,
            "campaign_arc_ref": cycle.get("campaign_arc_ref"),
            "commander_ref": selected_ref,
            "appointing_authority_ref": coordination,
            "formal_rank_value": rank_value,
            "current_command_span": command_span,
            "authority_rule": "Operational campaign command does not transfer troop ownership or sovereign authority.",
        })
        write_history_index(planner, history)
    return appointment


def _build_travel_obligations(planner: Any, commander_refs: list[str], *, venue_ref: str, at: str) -> list[dict[str, Any]]:
    current = CampaignTime.parse(at)
    rows: list[dict[str, Any]] = []
    for ref in commander_refs:
        if ref == _PLAYER_REF:
            continue
        origin = _person_location(planner, ref)
        if not isinstance(origin, str) or not origin:
            rows.append({"person_ref": ref, "origin_ref": None, "venue_ref": venue_ref, "status": "unrouted_location_unknown", "travel_hours": None})
            continue
        if origin == venue_ref:
            rows.append({"person_ref": ref, "origin_ref": origin, "venue_ref": venue_ref, "status": "already_present", "travel_hours": 0, "due_at": at})
            continue
        try:
            hours = max(1, int(planner._route_travel_hours(origin, venue_ref, modes=("horse", "foot"))))
        except (ValueError, KeyError, FileNotFoundError):
            rows.append({"person_ref": ref, "origin_ref": origin, "venue_ref": venue_ref, "status": "route_unavailable", "travel_hours": None})
            continue
        rows.append({
            "person_ref": ref,
            "origin_ref": origin,
            "venue_ref": venue_ref,
            "status": "summoned_in_transit",
            "travel_hours": hours,
            "due_at": str(current.add_seconds(hours * 3600)),
        })
    return rows


def _council_due(at: str, obligations: list[Mapping[str, Any]], *, notice_hours: int) -> str:
    current = CampaignTime.parse(at)
    due = current.add_seconds(max(1, notice_hours) * 3600)
    for row in obligations:
        due_text = row.get("due_at") if isinstance(row, Mapping) else None
        if isinstance(due_text, str):
            candidate = CampaignTime.parse(due_text)
            if candidate > due:
                due = candidate
    return str(due)


def _ensure_cycle(planner: Any, operation_ref: str, *, at: str) -> dict[str, Any] | None:
    path, operation = _load_operation(planner, operation_ref)
    if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
        return None
    arc_ref = campaign_arc_ref(operation)
    participant_refs, commander_refs = _campaign_participants(planner, operation)
    existing = _read_cycle(planner, operation_ref)
    venue_ref = str(operation.get("location_ref") or "")
    if not venue_ref:
        player = planner.read("state/player.json")
        venue_ref = str(player.get("location", "")) if isinstance(player, Mapping) else ""
    if not venue_ref:
        return None
    forum = _council_forum(planner, operation, default_venue_ref=venue_ref)
    venue_ref = str(forum.get("venue_ref") or venue_ref)
    mechanics = _mechanics(planner)
    notice_hours = max(1, int(mechanics.get("minimum_war_council_notice_hours", 1) or 1))
    supreme = _supreme_commander(operation)
    coordination = _coordination_authority(operation)

    if existing is None:
        obligations = _build_travel_obligations(planner, commander_refs, venue_ref=venue_ref, at=at)
        cycle = {
            "schema": "generic-object",
            "authority": True,
            "owner_id": _cycle_ref(operation_ref),
            "cycle_ref": _cycle_ref(operation_ref),
            "kind": "campaign_command_cycle",
            "operation_ref": operation_ref,
            "campaign_arc_ref": arc_ref,
            "state_ref": operation.get("institutional_owner_ref") or operation.get("administrative_authority"),
            "coordination_authority_ref": coordination,
            "supreme_commander_ref": supreme,
            "superior_command_ref": supreme or coordination,
            "venue_ref": venue_ref,
            "forum_kind": forum.get("forum_kind"),
            "court_state_ref": forum.get("court_state_ref"),
            "forum_attendance_rule": forum.get("attendance_rule"),
            "participant_operation_refs": participant_refs,
            "participant_commander_refs": commander_refs,
            "status": "war_council_assembling",
            "war_council": {
                "status": "summoned",
                "summoned_at": at,
                "scheduled_at": _council_due(at, obligations, notice_hours=notice_hours),
                "travel_obligations": obligations,
                "present_person_refs": [],
                "absent_person_refs": [],
            },
            "daily_cycle": {
                "status": "pending_war_council",
                "last_dawn_at": None,
                "last_evening_at": None,
                "morning_snapshot": None,
            },
            "upward_reports": [],
            "delivered_superior_order_refs": [],
            "reviewed_battlefield_after_action_refs": [],
            "after_action_reviews": [],
            "created_at": at,
            "updated_at": at,
        }
        _put_cycle(planner, cycle)
    else:
        cycle_path, cycle = existing
        changed = False
        refreshes = {
            "campaign_arc_ref": arc_ref,
            "coordination_authority_ref": coordination,
            "supreme_commander_ref": supreme,
            "superior_command_ref": supreme or coordination,
            "venue_ref": venue_ref,
            "forum_kind": forum.get("forum_kind"),
            "court_state_ref": forum.get("court_state_ref"),
            "forum_attendance_rule": forum.get("attendance_rule"),
            "participant_operation_refs": participant_refs,
            "participant_commander_refs": commander_refs,
        }
        for key, value in refreshes.items():
            if cycle.get(key) != value:
                cycle[key] = copy.deepcopy(value); changed = True
        if changed:
            cycle["updated_at"] = at
            planner.put(cycle_path, cycle)

    if operation.get("campaign_command_cycle_ref") != _cycle_ref(operation_ref):
        operation["campaign_command_cycle_ref"] = _cycle_ref(operation_ref)
        if "coordination_authority_ref" not in operation:
            operation["coordination_authority_ref"] = coordination
        planner.put(path, operation)
    return cycle


def _host_ids(cycle_ref: str, phase: str, instance_ref: str | None = None) -> tuple[str, str]:
    identity = phase if not instance_ref else f"{phase}|{instance_ref}"
    token = _digest("host", cycle_ref + "|" + identity)
    return f"host_campaign_command_{phase}_{token}", f"event_campaign_command_{phase}_{token}"


def _register_host(
    runtime: dict[str, Any], *, cycle_ref: str, operation_ref: str, phase: str,
    due_at: str, priority: int, recurrence_seconds: int = 0,
    instance_ref: str | None = None,
) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = _host_ids(cycle_ref, phase, instance_ref)
    if host_id not in hosts:
        due = CampaignTime.parse(due_at)
        hosts[host_id] = {
            "host_id": host_id,
            "kind": f"campaign_command_{phase}",
            "owner_ref": cycle_ref,
            "cycle_ref": cycle_ref,
            "operation_ref": operation_ref,
            "phase_instance_ref": instance_ref,
            "recurrence_seconds": max(0, int(recurrence_seconds)),
            "next_due": due_at,
            "resolved_through": str(due.add_seconds(-1)),
            "safe_through": str(due.add_seconds(-1)),
        }
    if not any(isinstance(row, Mapping) and row.get("event_id") == event_id for row in events):
        events.append({
            "event_id": event_id,
            "kind": f"campaign_command_{phase}",
            "priority": priority,
            "target_host": host_id,
            "due_at": due_at,
        })


def _retire_recurring_phase_host(runtime: dict[str, Any], *, cycle_ref: str, phase: str) -> None:
    """Remove one deterministic recurring headquarters phase from the live causal queue."""
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = _host_ids(cycle_ref, phase)
    hosts.pop(host_id, None)
    events[:] = [
        row for row in events
        if not (
            isinstance(row, Mapping)
            and (row.get("event_id") == event_id or row.get("target_host") == host_id)
        )
    ]


def _daily_cycle_enabled(operation: Mapping[str, Any], mechanics: Mapping[str, Any]) -> bool:
    """Return whether this operation is in a field phase that merits twice-daily HQ cadence.

    Formal councils and immediate superior orders remain available before field entry.
    The recurring dawn/evening loop begins only once the campaign leaves staging and
    becomes an active field operation.  This avoids manufacturing hundreds of empty
    headquarters events during a long political or entry-authority wait.
    """
    if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
        return False
    phase = str(operation.get("campaign_phase") or operation.get("order_status") or "")
    suppressed = {
        str(value) for value in mechanics.get("daily_cycle_suppressed_phases", [])
        if isinstance(value, str) and value
    }
    return phase not in suppressed


def _not_before(now: CampaignTime, candidate_text: str | None) -> str:
    if not isinstance(candidate_text, str) or not candidate_text:
        return str(now)
    candidate = CampaignTime.parse(candidate_text)
    return str(candidate if candidate >= now else now)


def _after_action_key(after_action: Mapping[str, Any]) -> str | None:
    battlefield_ref = after_action.get("battlefield_ref")
    reviewed_at = after_action.get("reviewed_at")
    if not isinstance(battlefield_ref, str) or not battlefield_ref or not isinstance(reviewed_at, str) or not reviewed_at:
        return None
    return f"{battlefield_ref}|{reviewed_at}"


def _operation_after_actions(operation: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    battlefields = operation.get("battlefields") if isinstance(operation.get("battlefields"), Mapping) else {}
    for battlefield_ref, battlefield in sorted(battlefields.items()):
        if not isinstance(battlefield_ref, str) or not isinstance(battlefield, Mapping):
            continue
        after_action = battlefield.get("after_action")
        if not isinstance(after_action, Mapping):
            continue
        row = copy.deepcopy(dict(after_action))
        row.setdefault("battlefield_ref", battlefield_ref)
        if _after_action_key(row) is not None:
            rows.append(row)
    latest = operation.get("last_battlefield_after_action")
    if isinstance(latest, Mapping):
        row = copy.deepcopy(dict(latest))
        key = _after_action_key(row)
        if key is not None and all(_after_action_key(existing) != key for existing in rows):
            rows.append(row)
    return rows


def sync_campaign_command_cycle(planner: Any, runtime: dict[str, Any]) -> None:
    current_text = str(runtime.get("world_time", ""))
    if not current_text:
        raise ValueError("runtime world time is missing")
    current = CampaignTime.parse(current_text)
    mechanics = _mechanics(planner)
    day_seconds = max(3600, int(mechanics.get("daily_cycle_seconds", 86400) or 86400))
    for operation_ref in _player_operation_refs(planner):
        cycle = _ensure_cycle(planner, operation_ref, at=current_text)
        if not isinstance(cycle, Mapping):
            continue
        cycle_ref = str(cycle["cycle_ref"])
        council = cycle.get("war_council") if isinstance(cycle.get("war_council"), Mapping) else {}
        council_status = str(council.get("status", ""))
        if council_status in {"summoned", "assembling"}:
            due = str(council.get("scheduled_at") or current_text)
            _register_host(
                runtime, cycle_ref=cycle_ref, operation_ref=operation_ref,
                phase="council", due_at=due, priority=_COUNCIL_PRIORITY,
            )
            continue
        if council_status != "held":
            continue

        _op_path, operation = _load_operation(planner, operation_ref)
        delivered_orders = {
            str(ref) for ref in cycle.get("delivered_superior_order_refs", [])
            if isinstance(ref, str) and ref
        }
        current_order = _latest_order(operation)
        if isinstance(current_order, Mapping):
            order_ref = current_order.get("order_ref")
            if isinstance(order_ref, str) and order_ref and order_ref not in delivered_orders:
                delay_minutes = max(0, int(mechanics.get("superior_order_delivery_delay_minutes", 15) or 0))
                issued_at = current_order.get("issued_at")
                due_text = str(current)
                if isinstance(issued_at, str) and issued_at:
                    due_text = str(CampaignTime.parse(issued_at).add_seconds(delay_minutes * 60))
                _register_host(
                    runtime, cycle_ref=cycle_ref, operation_ref=operation_ref,
                    phase="superior_order", due_at=_not_before(current, due_text),
                    priority=_SUPERIOR_ORDER_PRIORITY, instance_ref=order_ref,
                )

        reviewed = {
            str(ref) for ref in cycle.get("reviewed_battlefield_after_action_refs", [])
            if isinstance(ref, str) and ref
        }
        review_delay = max(0, int(mechanics.get("after_action_review_delay_minutes", 60) or 0))
        for after_action in _operation_after_actions(operation):
            review_key = _after_action_key(after_action)
            if review_key is None or review_key in reviewed:
                continue
            reviewed_at = str(after_action.get("reviewed_at"))
            due_text = str(CampaignTime.parse(reviewed_at).add_seconds(review_delay * 60))
            _register_host(
                runtime, cycle_ref=cycle_ref, operation_ref=operation_ref,
                phase="after_action", due_at=_not_before(current, due_text),
                priority=_AFTER_ACTION_PRIORITY, instance_ref=review_key,
            )

        if not _daily_cycle_enabled(operation, mechanics):
            _retire_recurring_phase_host(runtime, cycle_ref=cycle_ref, phase="dawn")
            _retire_recurring_phase_host(runtime, cycle_ref=cycle_ref, phase="evening")
            if isinstance(cycle, dict):
                daily = cycle.setdefault("daily_cycle", {})
                if not isinstance(daily, dict):
                    daily = {}; cycle["daily_cycle"] = daily
                daily["status"] = "paused_until_field_operations"
                daily["paused_campaign_phase"] = str(operation.get("campaign_phase") or operation.get("order_status") or "")
                cycle["updated_at"] = current_text
                planner.put(_cycle_path(cycle_ref), cycle)
            continue

        if isinstance(cycle, dict):
            daily = cycle.setdefault("daily_cycle", {})
            if not isinstance(daily, dict):
                daily = {}; cycle["daily_cycle"] = daily
            if daily.get("status") == "paused_until_field_operations":
                daily["status"] = "scheduled"
                daily.pop("paused_campaign_phase", None)
                cycle["updated_at"] = current_text
                planner.put(_cycle_path(cycle_ref), cycle)

        dawn = next_sunrise_after(current)
        dusk = next_sunset_after(current)
        _register_host(
            runtime, cycle_ref=cycle_ref, operation_ref=operation_ref,
            phase="dawn", due_at=str(dawn), priority=_DAWN_PRIORITY,
            recurrence_seconds=day_seconds,
        )
        _register_host(
            runtime, cycle_ref=cycle_ref, operation_ref=operation_ref,
            phase="evening", due_at=str(dusk), priority=_EVENING_PRIORITY,
            recurrence_seconds=day_seconds,
        )


def _write_event(
    planner: Any, *, event_ref: str, kind: str, summary: str, at: str,
    cycle: Mapping[str, Any], present_person_refs: list[str], command_context: Mapping[str, Any],
    location_ref: str | None = None,
) -> str:
    existing = get_causal_event(planner, event_ref)
    if isinstance(existing, Mapping):
        return event_ref
    _path, owner = read_causal_event_owner(planner)
    event = {
        "event_ref": event_ref,
        "kind": kind,
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": cycle.get("superior_command_ref") or cycle.get("coordination_authority_ref"),
        "target_ref": _PLAYER_REF,
        "process_kind": "campaign_command_cycle",
        "process_stage": kind,
        "summary": summary[:4000],
        "operation_ref": cycle.get("operation_ref"),
        "campaign_command_cycle_ref": cycle.get("cycle_ref"),
        "campaign_command_context": copy.deepcopy(dict(command_context)),
        "present_person_refs": sorted(set(present_person_refs)),
        "delivery": {
            "target_ref": _PLAYER_REF,
            "location_ref": location_ref or cycle.get("venue_ref"),
            "route": "campaign headquarters command channel",
        },
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": cycle.get("cycle_ref"),
            "work_ref": event_ref,
            "late_catch_up": False,
        },
    }
    owner["causal_events"][event_ref] = event
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return event_ref


def _directive_state_owned_refs(planner: Any, operation: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    state_ref = str(operation.get("institutional_owner_ref") or "")
    expected_force = f"force_{state_ref}" if state_ref.startswith("state_") else ""
    state_owned: list[str] = []
    excluded: list[str] = []
    for ref in operation.get("formation_refs", []) if isinstance(operation.get("formation_refs"), list) else []:
        if not isinstance(ref, str):
            continue
        try:
            formation = planner.read(planner.owner_path(ref))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        owner_force = str(formation.get("owner_force_ref", "")) if isinstance(formation, Mapping) else ""
        if expected_force and owner_force == expected_force:
            state_owned.append(ref)
        else:
            excluded.append(ref)
    return sorted(state_owned), sorted(excluded)


def _directive_semantics(operation: Mapping[str, Any]) -> tuple[str, str]:
    phase = str(operation.get("campaign_phase") or operation.get("order_status") or "")
    order = _latest_order(operation)
    order_status = str(order.get("status", "")) if isinstance(order, Mapping) else ""
    if phase == "awaiting_entry_authority" or order_status == "staged_awaiting_entry_authority":
        return (
            "hold_staging_and_report",
            "Maintain the current lawful concentration, readiness, security, reconnaissance and command reporting. Do not cross into hostile territory until Qin issues exact war or entry authority.",
        )
    after_action = operation.get("last_battlefield_after_action")
    if isinstance(after_action, Mapping):
        return (
            "reform_account_and_report",
            "Reform the field command under the standing operation, account for losses, condition, ammunition and supply, maintain security, and report before the next committed maneuver unless an urgent superior order intervenes.",
        )
    if isinstance(order, Mapping) and str(order.get("actionability_status", "")) not in {"completed", ""}:
        return (
            "execute_lawful_operational_order",
            "Execute the current lawful operational mission within Tang Wei's field-command authority, preserve command reporting, and escalate any material change or authority conflict to supreme command.",
        )
    return (
        "maintain_readiness_and_report",
        "Maintain the field command in readiness under the current campaign objective and report material changes while awaiting a lawful follow-on operational instruction.",
    )


def _ensure_supreme_directive(
    planner: Any, *, operation_ref: str, cycle: Mapping[str, Any], at: str
) -> dict[str, Any] | None:
    commander_ref = cycle.get("supreme_commander_ref")
    if not isinstance(commander_ref, str) or not commander_ref.startswith("char_"):
        return None
    op_path, operation = _load_operation(planner, operation_ref)
    base_order = _latest_order(operation)
    base_order_ref = str(base_order.get("order_ref", "")) if isinstance(base_order, Mapping) else ""
    kind, text = _directive_semantics(operation)
    state_owned, excluded = _directive_state_owned_refs(planner, operation)
    semantic = f"{operation_ref}|{commander_ref}|{base_order_ref}|{kind}|{'|'.join(state_owned)}"
    directive_ref = f"campaign_directive_{_digest('directive', semantic)}"
    rows = operation.get("campaign_command_directives")
    if not isinstance(rows, list):
        rows = []
    existing = next((row for row in reversed(rows) if isinstance(row, Mapping) and row.get("directive_ref") == directive_ref), None)
    if isinstance(existing, Mapping):
        return copy.deepcopy(dict(existing))
    # Retire older active directives from the same superior command. The exact
    # operational order remains separate and authoritative for legal mission scope.
    for row in rows:
        if isinstance(row, dict) and row.get("status") == "active":
            row["status"] = "superseded"
            row["superseded_at"] = at
    directive = {
        "directive_ref": directive_ref,
        "issued_at": at,
        "status": "active",
        "issuer_ref": operation.get("institutional_owner_ref") or "state_qin",
        "issuing_commander_ref": commander_ref,
        "coordination_authority_ref": cycle.get("coordination_authority_ref"),
        "base_operational_order_ref": base_order_ref or None,
        "kind": kind,
        "directive_text": text,
        "applies_to_formation_refs": state_owned,
        "excluded_non_state_formation_refs": excluded,
        "authority_rule": (
            "Supreme command may direct the player field command only inside existing Qin legal/operational authority. "
            "This directive does not transfer ownership, legalize hostile entry, compel private House auxiliaries, "
            "or choose Tang Wei's protected tactics."
        ),
    }
    rows.append(directive)
    operation["campaign_command_directives"] = rows[-16:]
    operation["last_campaign_command_directive_ref"] = directive_ref
    operation["last_campaign_command_directive_at"] = at
    planner.put(op_path, operation)
    return copy.deepcopy(directive)


def _current_superior_directive(operation: Mapping[str, Any]) -> dict[str, Any] | None:
    ref = str(operation.get("last_campaign_command_directive_ref", ""))
    rows = operation.get("campaign_command_directives") if isinstance(operation.get("campaign_command_directives"), list) else []
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        if ref and str(row.get("directive_ref", "")) != ref:
            continue
        if str(row.get("status", "")) != "active":
            continue
        return copy.deepcopy(dict(row))
    return None


def _current_superior_order(operation: Mapping[str, Any], cycle: Mapping[str, Any]) -> dict[str, Any] | None:
    order = _latest_order(operation)
    if not isinstance(order, Mapping):
        return None
    return {
        key: copy.deepcopy(order.get(key))
        for key in (
            "order_ref", "issued_at", "issuer_ref", "superior_commander_ref", "objective",
            "status", "actionability_status", "follow_on_requirement", "mission_packet",
            "applies_to_formation_refs", "excluded_non_state_formation_refs",
        ) if key in order
    } | {
        "superior_command_ref": cycle.get("superior_command_ref"),
        "coordination_authority_ref": cycle.get("coordination_authority_ref"),
    }


def _player_hq_people(planner: Any, *, location_ref: str) -> list[str]:
    refs: list[str] = [_PLAYER_REF]
    try:
        root = planner.read("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    except (FileNotFoundError, KeyError, ValueError):
        root = None
    if isinstance(root, Mapping):
        commander = root.get("commander_ref")
        if isinstance(commander, str):
            refs.append(commander)
        roles = root.get("role_assignments") if isinstance(root.get("role_assignments"), Mapping) else {}
        refs.extend(str(ref) for ref in roles if isinstance(ref, str) and ref.startswith("char_"))
        for unit in (root.get("direct_units") if isinstance(root.get("direct_units"), list) else root.get("units", []) if isinstance(root.get("units"), list) else []):
            if not isinstance(unit, Mapping) or unit.get("kind") != "nested_army":
                continue
            group_ref = unit.get("ref")
            if not isinstance(group_ref, str):
                continue
            try:
                group = planner.read(f"state/cmd/command-groups/{group_ref}.json")
            except (FileNotFoundError, KeyError, ValueError):
                continue
            commander = group.get("commander_ref") if isinstance(group, Mapping) else None
            if isinstance(commander, str) and commander.startswith("char_"):
                refs.append(commander)
    return [ref for ref in dict.fromkeys(refs) if _person_location(planner, ref) == location_ref]


def _own_snapshot(planner: Any, operation: Mapping[str, Any], *, at: str) -> dict[str, Any]:
    opposing = {str(ref) for ref in operation.get("opposing_formation_refs", []) if isinstance(ref, str)}
    refs = [str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref not in opposing]
    personnel = 0
    locations: dict[str, int] = {}
    readiness: list[int] = []
    morale: list[int] = []
    cohesion: list[int] = []
    fatigue: list[int] = []
    supply_scores: list[int] = []
    for ref in refs:
        try:
            formation = planner.read(planner.owner_path(ref))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if not isinstance(formation, Mapping):
            continue
        count = max(0, int(formation.get("personnel", 0) or 0))
        personnel += count
        loc = formation.get("location_ref")
        if isinstance(loc, str) and loc:
            locations[loc] = locations.get(loc, 0) + count
        for dest, key in ((readiness, "readiness"), (morale, "morale"), (cohesion, "cohesion"), (fatigue, "fatigue")):
            value = formation.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                dest.append(value)
        try:
            supply = evaluate_military_supply(planner, formation, at=at)
            score = supply.get("score_milli") if isinstance(supply, Mapping) else None
            if isinstance(score, int) and not isinstance(score, bool):
                supply_scores.append(score)
        except (ValueError, KeyError, FileNotFoundError):
            pass
    avg = lambda xs: int(round(sum(xs) / len(xs))) if xs else None
    return {
        "personnel": personnel,
        "formation_count": len(refs),
        "locations": locations,
        "readiness_mean": avg(readiness),
        "morale_mean": avg(morale),
        "cohesion_mean": avg(cohesion),
        "fatigue_mean": avg(fatigue),
        "strategic_supply_mean_milli": avg(supply_scores),
        "last_battlefield_after_action": copy.deepcopy(operation.get("last_battlefield_after_action")) if isinstance(operation.get("last_battlefield_after_action"), Mapping) else None,
        "last_battlefield_outcome": copy.deepcopy(operation.get("last_battlefield_outcome")) if isinstance(operation.get("last_battlefield_outcome"), Mapping) else None,
    }


def _command_context(planner: Any, operation_ref: str, cycle: Mapping[str, Any], *, at: str) -> dict[str, Any]:
    _path, operation = _load_operation(planner, operation_ref)
    dossier = build_campaign_dossier(planner, operation_ref)
    context = safe_campaign_context(dossier)
    context["command_cycle_ref"] = cycle.get("cycle_ref")
    context["coordination_authority_ref"] = cycle.get("coordination_authority_ref")
    context["supreme_commander_ref"] = cycle.get("supreme_commander_ref")
    context["superior_command_ref"] = cycle.get("superior_command_ref")
    context["current_superior_order"] = _current_superior_order(operation, cycle)
    context["current_superior_directive"] = _current_superior_directive(operation)
    context["own_command_snapshot"] = _own_snapshot(planner, operation, at=at)
    context["forum_kind"] = cycle.get("forum_kind")
    context["court_state_ref"] = cycle.get("court_state_ref")
    return context


def _settle_council(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    operation_ref = str(host.get("operation_ref", ""))
    existing = _read_cycle(planner, operation_ref)
    if existing is None:
        return None
    path, cycle = existing
    council = cycle.get("war_council") if isinstance(cycle.get("war_council"), Mapping) else {}
    if str(council.get("status", "")) == "held":
        return None
    venue_ref = str(cycle.get("venue_ref", ""))
    present: list[str] = []
    absent: list[str] = []
    for row in council.get("travel_obligations", []) if isinstance(council.get("travel_obligations"), list) else []:
        if not isinstance(row, Mapping):
            continue
        ref = row.get("person_ref")
        if not isinstance(ref, str):
            continue
        current = _person_location(planner, ref)
        origin = row.get("origin_ref")
        due_at = row.get("due_at")
        can_arrive = not isinstance(due_at, str) or CampaignTime.parse(due_at) <= CampaignTime.parse(at)
        if current == venue_ref:
            present.append(ref)
        elif can_arrive and isinstance(origin, str) and current == origin and row.get("status") in {"summoned_in_transit", "already_present"}:
            if _set_person_location(planner, ref, venue_ref):
                present.append(ref)
            else:
                absent.append(ref)
        else:
            absent.append(ref)
    if _person_location(planner, _PLAYER_REF) == venue_ref:
        present.insert(0, _PLAYER_REF)
    else:
        absent.insert(0, _PLAYER_REF)

    court_projection: dict[str, Any] | None = None
    court_state_ref = cycle.get("court_state_ref")
    if str(cycle.get("forum_kind", "")) == "royal_court" and isinstance(court_state_ref, str) and court_state_ref:
        court_projection = court_session_projection(
            planner, state_ref=court_state_ref, venue_ref=venue_ref,
            additional_candidate_refs=present,
        )
        present = list(dict.fromkeys(present + [
            str(ref) for ref in court_projection.get("present_person_refs", []) if isinstance(ref, str)
        ]))
        absent = list(dict.fromkeys(absent + [
            str(ref) for ref in court_projection.get("absent_person_refs", []) if isinstance(ref, str)
        ]))
        # A person actually established in the session is not simultaneously absent.
        absent = [ref for ref in absent if ref not in set(present)]

    appointment = _appoint_supreme_commander_if_needed(
        planner, operation_ref=operation_ref, cycle=cycle, present_person_refs=present, at=at
    )
    directive = _ensure_supreme_directive(planner, operation_ref=operation_ref, cycle=cycle, at=at)
    command_context = _command_context(planner, operation_ref, cycle, at=at)
    if isinstance(appointment, Mapping):
        command_context["campaign_command_appointment"] = copy.deepcopy(dict(appointment))
    if isinstance(directive, Mapping):
        command_context["current_superior_directive"] = copy.deepcopy(dict(directive))
    if isinstance(court_projection, Mapping):
        command_context["court_session"] = copy.deepcopy(dict(court_projection))
    total = int(command_context.get("friendly_total_strength", 0) or 0)
    participant_set = {
        str(ref) for ref in cycle.get("participant_commander_refs", [])
        if isinstance(ref, str)
    }
    commander_names = [_person_name(planner, ref) for ref in present if ref != _PLAYER_REF and ref in participant_set]
    commander_text = ", ".join(commander_names) if commander_names else "no other senior campaign commander physically present"
    court_text = ""
    if isinstance(court_projection, Mapping):
        role_map = court_projection.get("court_role_by_person_ref") if isinstance(court_projection.get("court_role_by_person_ref"), Mapping) else {}
        court_refs = [
            ref for ref in present
            if ref not in participant_set and ref != _PLAYER_REF and ref in set(court_projection.get("candidate_person_refs", []))
        ]
        labels = []
        for ref in court_refs:
            role = role_map.get(ref) if isinstance(role_map, Mapping) else None
            label = _person_name(planner, ref)
            if isinstance(role, str) and role:
                label = f"{label} ({role.replace('_', ' ')})"
            labels.append(label)
        if labels:
            court_text = " Royal-court attendees present beyond the campaign commanders: " + ", ".join(labels) + "."
    supreme = cycle.get("supreme_commander_ref")
    command_text = (
        f"Named supreme commander: {_person_name(planner, str(supreme))}."
        if isinstance(supreme, str) and supreme else
        f"No named supreme commander has yet been established; {_person_name(planner, str(cycle.get('coordination_authority_ref')))} remains the institutional command authority."
    )
    directive_text = ""
    if isinstance(directive, Mapping):
        directive_text = f" Supreme command issues Tang Wei this standing directive: {directive.get('directive_text')}"
    summary = (
        f"Qin's formal campaign command conference convenes at {venue_ref}. Tang Wei's campaign roster represents {total:,} friendly troops. "
        f"Senior commanders physically present: {commander_text}. {command_text}{court_text}{directive_text} "
        "The conference agenda is command hierarchy, current intelligence, army assignments, routes and supply, reserve responsibilities, entry authority, and the standing order for the next campaign phase. "
        "The conference does not move armies, invent enemy knowledge, transfer troop ownership, or choose Tang Wei's protected tactics."
    )
    event_ref = f"event_campaign_command_council_{_digest('council', cycle['cycle_ref'] + '|' + at)}"
    _write_event(
        planner, event_ref=event_ref, kind="campaign_command_council", summary=summary, at=at,
        cycle=cycle, present_person_refs=present, command_context=command_context,
    )
    council = copy.deepcopy(dict(council))
    council.update({
        "status": "held",
        "held_at": at,
        "event_ref": event_ref,
        "present_person_refs": sorted(set(present)),
        "absent_person_refs": sorted(set(absent)),
        "forum_kind": cycle.get("forum_kind"),
        "court_state_ref": cycle.get("court_state_ref"),
        "court_session": copy.deepcopy(dict(court_projection)) if isinstance(court_projection, Mapping) else None,
    })
    cycle["war_council"] = council
    cycle["status"] = "campaign_command_active"
    cycle.setdefault("daily_cycle", {})["status"] = "active"
    current_order = command_context.get("current_superior_order") if isinstance(command_context.get("current_superior_order"), Mapping) else None
    if isinstance(current_order, Mapping):
        order_ref = current_order.get("order_ref")
        if isinstance(order_ref, str) and order_ref:
            delivered = [
                str(ref) for ref in cycle.get("delivered_superior_order_refs", [])
                if isinstance(ref, str) and ref
            ]
            delivered.append(order_ref)
            cycle["delivered_superior_order_refs"] = list(dict.fromkeys(delivered))[-32:]
            cycle["current_superior_order"] = copy.deepcopy(dict(current_order))
    if isinstance(directive, Mapping):
        cycle["current_superior_directive_ref"] = directive.get("directive_ref")
    cycle["updated_at"] = at
    planner.put(path, cycle)

    # The senior commanders travelled to the conference without their armies.
    # Schedule their physical return to the exact saved origins after the
    # configured council duration.  If another causal event moves one of them in
    # the meantime, the return settlement refuses to teleport that person.
    mechanics = _mechanics(planner)
    duration_hours = max(1, int(mechanics.get("war_council_duration_hours", 4) or 4))
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    _register_host(
        runtime, cycle_ref=str(cycle["cycle_ref"]), operation_ref=operation_ref,
        phase="council_return", due_at=str(CampaignTime.parse(at).add_seconds(duration_hours * 3600)),
        priority=_RETURN_PRIORITY,
    )
    planner.put(_RUNTIME_PATH, runtime)
    return {"event_ref": event_ref, "present_person_refs": present, "command_context": command_context}


def _settle_council_return(planner: Any, host: Mapping[str, Any], at: str) -> None:
    operation_ref = str(host.get("operation_ref", ""))
    existing = _read_cycle(planner, operation_ref)
    if existing is None:
        return
    path, cycle = existing
    council = cycle.get("war_council") if isinstance(cycle.get("war_council"), Mapping) else {}
    venue_ref = str(cycle.get("venue_ref", ""))
    returned: list[str] = []
    for row in council.get("travel_obligations", []) if isinstance(council.get("travel_obligations"), list) else []:
        if not isinstance(row, Mapping):
            continue
        ref = row.get("person_ref")
        origin = row.get("origin_ref")
        if not isinstance(ref, str) or not isinstance(origin, str) or not origin or origin == venue_ref:
            continue
        if _person_location(planner, ref) != venue_ref:
            continue
        if _set_person_location(planner, ref, origin):
            returned.append(ref)
    council2 = copy.deepcopy(dict(council))
    council2["return_completed_at"] = at
    council2["returned_person_refs"] = returned
    cycle["war_council"] = council2
    cycle["updated_at"] = at
    planner.put(path, cycle)


def _format_location_strength(locations: Mapping[str, Any]) -> str:
    rows = [f"{ref} {int(count):,}" for ref, count in sorted(locations.items()) if isinstance(count, int)]
    return ", ".join(rows) if rows else "location accounting unavailable"


def _record_upward_report(
    cycle: dict[str, Any], *, at: str, phase: str, snapshot: Mapping[str, Any], event_ref: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    rows = cycle.setdefault("upward_reports", [])
    if not isinstance(rows, list):
        rows = []
        cycle["upward_reports"] = rows
    report = {
        "reported_at": at,
        "phase": phase,
        "from_ref": _PLAYER_REF,
        "to_ref": cycle.get("superior_command_ref"),
        "event_ref": event_ref,
        "personnel": snapshot.get("personnel"),
        "locations": copy.deepcopy(snapshot.get("locations")),
        "order_ref": (cycle.get("current_superior_order") or {}).get("order_ref") if isinstance(cycle.get("current_superior_order"), Mapping) else None,
        "directive_ref": cycle.get("current_superior_directive_ref"),
        "rule": "Routine field-command reporting transmits already-saved command facts upward; it does not choose tactics or fabricate outcomes.",
    }
    if isinstance(extra, Mapping):
        report.update(copy.deepcopy(dict(extra)))
    rows.append(report)
    cycle["upward_reports"] = rows[-48:]


def _find_order(operation: Mapping[str, Any], order_ref: str) -> dict[str, Any] | None:
    rows = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    for row in reversed(rows):
        if isinstance(row, Mapping) and str(row.get("order_ref", "")) == order_ref:
            return copy.deepcopy(dict(row))
    return None


def _service_appraisals_for_after_action(planner: Any, after_action: Mapping[str, Any]) -> list[dict[str, Any]]:
    evidence_refs = {
        str(ref) for ref in after_action.get("battle_event_refs", [])
        if isinstance(ref, str) and ref
    }
    if not evidence_refs:
        return []
    rows: list[dict[str, Any]] = []
    for event in iter_history_events(planner):
        if str(event.get("kind", "")) != "career_merit" or str(event.get("person_ref", "")) != _PLAYER_REF:
            continue
        if str(event.get("evidence_ref", "")) not in evidence_refs:
            continue
        rows.append({
            key: copy.deepcopy(event.get(key))
            for key in ("event_id", "at", "merit", "evidence_ref", "service_appraisal")
            if key in event
        })
    rows.sort(key=lambda row: (str(row.get("at", "")), str(row.get("event_id", ""))))
    return rows[-8:]


def _settle_superior_order(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    operation_ref = str(host.get("operation_ref", ""))
    order_ref = str(host.get("phase_instance_ref", ""))
    if not operation_ref or not order_ref:
        return None
    existing = _read_cycle(planner, operation_ref)
    if existing is None:
        return None
    cycle_path, cycle = existing
    delivered = [str(ref) for ref in cycle.get("delivered_superior_order_refs", []) if isinstance(ref, str) and ref]
    if order_ref in set(delivered):
        return None
    _op_path, operation = _load_operation(planner, operation_ref)
    order = _find_order(operation, order_ref)
    if not isinstance(order, Mapping):
        return None
    directive = _ensure_supreme_directive(planner, operation_ref=operation_ref, cycle=cycle, at=at)
    command_context = _command_context(planner, operation_ref, cycle, at=at)
    command_context["delivered_superior_order"] = copy.deepcopy(dict(order))
    if isinstance(directive, Mapping):
        command_context["current_superior_directive"] = copy.deepcopy(dict(directive))
    player = planner.read("state/player.json")
    location_ref = str(player.get("location", "")) if isinstance(player, Mapping) else ""
    present = _player_hq_people(planner, location_ref=location_ref) if location_ref else [_PLAYER_REF]
    issuer_ref = order.get("issuer_ref") or cycle.get("coordination_authority_ref")
    commander_ref = order.get("superior_commander_ref") or cycle.get("supreme_commander_ref")
    objective = order.get("objective") or order.get("follow_on_requirement") or order.get("status") or "continue the current campaign mission"
    if isinstance(commander_ref, str) and commander_ref and commander_ref != issuer_ref:
        chain = f"{_person_name(planner, str(issuer_ref))}, transmitted through {_person_name(planner, commander_ref)}"
    else:
        chain = _person_name(planner, str(issuer_ref))
    summary = (
        f"A new superior campaign order reaches Tang Wei's field headquarters from {chain}: {objective}. "
        "The order carries only its exact saved authority and does not silently commit private auxiliaries, choose Tang Wei's protected tactics, or create a military result before execution."
    )
    event_ref = f"event_campaign_command_order_{_digest('superior-order', cycle['cycle_ref'] + '|' + order_ref)}"
    _write_event(
        planner, event_ref=event_ref, kind="campaign_command_superior_order", summary=summary, at=at,
        cycle=cycle, present_person_refs=present, command_context=command_context, location_ref=location_ref or None,
    )
    delivered.append(order_ref)
    cycle["delivered_superior_order_refs"] = list(dict.fromkeys(delivered))[-32:]
    cycle["current_superior_order"] = copy.deepcopy(dict(command_context.get("current_superior_order") or order))
    if isinstance(directive, Mapping):
        cycle["current_superior_directive_ref"] = directive.get("directive_ref")
    cycle["last_superior_order_event_ref"] = event_ref
    cycle["updated_at"] = at
    planner.put(cycle_path, cycle)
    return {"event_ref": event_ref, "present_person_refs": present, "command_context": command_context}


def _settle_after_action_review(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    operation_ref = str(host.get("operation_ref", ""))
    review_key = str(host.get("phase_instance_ref", ""))
    if not operation_ref or not review_key:
        return None
    existing = _read_cycle(planner, operation_ref)
    if existing is None:
        return None
    cycle_path, cycle = existing
    reviewed = [
        str(ref) for ref in cycle.get("reviewed_battlefield_after_action_refs", [])
        if isinstance(ref, str) and ref
    ]
    if review_key in set(reviewed):
        return None
    _op_path, operation = _load_operation(planner, operation_ref)
    after_action = next((row for row in _operation_after_actions(operation) if _after_action_key(row) == review_key), None)
    if not isinstance(after_action, Mapping):
        return None
    directive = _ensure_supreme_directive(planner, operation_ref=operation_ref, cycle=cycle, at=at)
    command_context = _command_context(planner, operation_ref, cycle, at=at)
    command_context["battlefield_after_action"] = copy.deepcopy(dict(after_action))
    appraisals = _service_appraisals_for_after_action(planner, after_action)
    if appraisals:
        command_context["player_service_appraisals"] = copy.deepcopy(appraisals)
    if isinstance(directive, Mapping):
        command_context["current_superior_directive"] = copy.deepcopy(dict(directive))

    player_refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}
    player_killed = sum(
        max(0, int(row.get("battle_killed", 0) or 0))
        for row in after_action.get("formation_summary", [])
        if isinstance(row, Mapping) and str(row.get("formation_ref", "")) in player_refs
    )
    outcome = after_action.get("outcome") if isinstance(after_action.get("outcome"), Mapping) else {}
    winner = outcome.get("winner_side_ref")
    loser = outcome.get("loser_side_ref")
    reason = outcome.get("reason") or "field battle concluded"
    order = command_context.get("current_superior_order") if isinstance(command_context.get("current_superior_order"), Mapping) else None
    order_text = "No new superior follow-on order is established yet."
    if isinstance(order, Mapping):
        order_text = f"Current superior direction: {order.get('objective') or order.get('follow_on_requirement') or order.get('status')}."
    merit_text = ""
    if appraisals:
        total_merit = sum(max(0, int(row.get("merit", 0) or 0)) for row in appraisals)
        merit_text = f" Exact service appraisal records tied to this battle credit {total_merit} merit in total; court reward remains a separate sovereign review."
    summary = (
        f"Tang Wei's field headquarters conducts the formal after-action command review for {after_action.get('battlefield_ref')}. "
        f"The settled field outcome records winner {winner}, loser {loser}, reason {reason}; Tang Wei's participating command records {player_killed:,} battle dead in the reviewed formation receipts. "
        f"{order_text}{merit_text} The review reports settled facts upward and does not itself grant rewards, end the wider campaign, or choose the next protected maneuver."
    )
    player = planner.read("state/player.json")
    location_ref = str(player.get("location", "")) if isinstance(player, Mapping) else ""
    present = _player_hq_people(planner, location_ref=location_ref) if location_ref else [_PLAYER_REF]
    event_ref = f"event_campaign_command_after_action_{_digest('after-action', cycle['cycle_ref'] + '|' + review_key)}"
    _write_event(
        planner, event_ref=event_ref, kind="campaign_command_after_action_review", summary=summary, at=at,
        cycle=cycle, present_person_refs=present, command_context=command_context, location_ref=location_ref or None,
    )
    own = command_context.get("own_command_snapshot") if isinstance(command_context.get("own_command_snapshot"), Mapping) else {}
    cycle["current_superior_order"] = copy.deepcopy(command_context.get("current_superior_order"))
    if isinstance(directive, Mapping):
        cycle["current_superior_directive_ref"] = directive.get("directive_ref")
    _record_upward_report(
        cycle, at=at, phase="after_action", snapshot=own, event_ref=event_ref,
        extra={
            "battlefield_ref": after_action.get("battlefield_ref"),
            "battle_killed": player_killed,
            "battle_outcome": copy.deepcopy(dict(outcome)),
        },
    )
    reviewed.append(review_key)
    cycle["reviewed_battlefield_after_action_refs"] = list(dict.fromkeys(reviewed))[-32:]
    review_rows = cycle.get("after_action_reviews") if isinstance(cycle.get("after_action_reviews"), list) else []
    review_rows.append({
        "review_key": review_key,
        "reviewed_at": at,
        "battlefield_ref": after_action.get("battlefield_ref"),
        "event_ref": event_ref,
        "battle_killed": player_killed,
        "service_appraisal_refs": [row.get("event_id") for row in appraisals if isinstance(row.get("event_id"), str)],
    })
    cycle["after_action_reviews"] = review_rows[-16:]
    cycle["last_after_action_review_event_ref"] = event_ref
    cycle["updated_at"] = at
    planner.put(cycle_path, cycle)
    return {"event_ref": event_ref, "present_person_refs": present, "command_context": command_context}


def _settle_daily(planner: Any, host: Mapping[str, Any], at: str, *, phase: str) -> dict[str, Any] | None:
    operation_ref = str(host.get("operation_ref", ""))
    existing = _read_cycle(planner, operation_ref)
    if existing is None:
        return None
    path, cycle = existing
    if str(cycle.get("war_council", {}).get("status", "")) != "held":
        return None
    _operation_path_value, operation = _load_operation(planner, operation_ref)
    if not _daily_cycle_enabled(operation, _mechanics(planner)):
        return None
    _ensure_supreme_directive(planner, operation_ref=operation_ref, cycle=cycle, at=at)
    command_context = _command_context(planner, operation_ref, cycle, at=at)
    own = command_context.get("own_command_snapshot") if isinstance(command_context.get("own_command_snapshot"), Mapping) else {}
    current_order = command_context.get("current_superior_order") if isinstance(command_context.get("current_superior_order"), Mapping) else None
    order_text = "No current superior operational order is established."
    if isinstance(current_order, Mapping):
        legal_issuer = current_order.get("issuer_ref") or cycle.get("coordination_authority_ref")
        chain_ref = current_order.get("superior_commander_ref") or cycle.get("supreme_commander_ref")
        objective_text = current_order.get("objective") or current_order.get("follow_on_requirement") or current_order.get("status")
        if isinstance(chain_ref, str) and chain_ref and chain_ref != legal_issuer:
            order_text = (
                f"Standing order issued by {_person_name(planner, str(legal_issuer))}, now carried through "
                f"{_person_name(planner, chain_ref)}'s campaign command: {objective_text}."
            )
        else:
            order_text = f"Standing superior order from {_person_name(planner, str(legal_issuer))}: {objective_text}."
    current_directive = command_context.get("current_superior_directive") if isinstance(command_context.get("current_superior_directive"), Mapping) else None
    directive_text = ""
    if isinstance(current_directive, Mapping):
        directive_text = f" Supreme-command directive: {current_directive.get('directive_text')}"
    enemy = command_context.get("enemy_intelligence") if isinstance(command_context.get("enemy_intelligence"), Mapping) else {}
    contact = str(enemy.get("contact_status") or "no confirmed contact")
    location_text = _format_location_strength(own.get("locations", {}) if isinstance(own.get("locations"), Mapping) else {})
    player = planner.read("state/player.json")
    hq_location_ref = str(player.get("location", "")) if isinstance(player, Mapping) else ""
    hq_people = _player_hq_people(planner, location_ref=hq_location_ref) if hq_location_ref else [_PLAYER_REF]
    command_context["field_headquarters_location_ref"] = hq_location_ref or None

    daily = cycle.setdefault("daily_cycle", {})
    if not isinstance(daily, dict):
        daily = {}; cycle["daily_cycle"] = daily
    if phase == "dawn":
        summary = (
            f"Dawn field-command briefing. Tang Wei's command accounts for {int(own.get('personnel', 0) or 0):,} troops in {int(own.get('formation_count', 0) or 0)} formations; current distribution: {location_text}. "
            f"Readiness {own.get('readiness_mean')}, morale {own.get('morale_mean')}, cohesion {own.get('cohesion_mean')}, fatigue {own.get('fatigue_mean')}, strategic-supply mean {own.get('strategic_supply_mean_milli')}/1000. "
            f"Enemy report: {contact}. {order_text}{directive_text} The briefing consolidates already-known command information and leaves today's tactics to Tang Wei within the standing order."
        )
        event_kind = "campaign_command_dawn_briefing"
        event_ref = f"event_campaign_command_dawn_{_digest('dawn', cycle['cycle_ref'] + '|' + at)}"
        daily["last_dawn_at"] = at
        daily["morning_snapshot"] = copy.deepcopy(dict(own))
    else:
        morning = daily.get("morning_snapshot") if isinstance(daily.get("morning_snapshot"), Mapping) else {}
        delta = int(own.get("personnel", 0) or 0) - int(morning.get("personnel", own.get("personnel", 0)) or 0)
        after_action = own.get("last_battlefield_after_action")
        after_text = ""
        if isinstance(after_action, Mapping):
            after_text = f" A settled battlefield after-action picture is available for {after_action.get('battlefield_ref') or 'the latest battle'}."
        summary = (
            f"Evening field-command situation conference. Tang Wei's command now accounts for {int(own.get('personnel', 0) or 0):,} troops; net personnel change since the dawn accounting is {delta:+,}. "
            f"Current distribution: {location_text}. Readiness {own.get('readiness_mean')}, morale {own.get('morale_mean')}, cohesion {own.get('cohesion_mean')}, fatigue {own.get('fatigue_mean')}, strategic-supply mean {own.get('strategic_supply_mean_milli')}/1000. "
            f"Enemy report: {contact}.{after_text} {order_text}{directive_text} The evening conference closes the day's headquarters accounting and carries the standing order into the next day unless superior command issues a new one."
        )
        event_kind = "campaign_command_evening_sitrep"
        event_ref = f"event_campaign_command_evening_{_digest('evening', cycle['cycle_ref'] + '|' + at)}"
        daily["last_evening_at"] = at

    _write_event(
        planner, event_ref=event_ref, kind=event_kind, summary=summary, at=at,
        cycle=cycle, present_person_refs=hq_people, command_context=command_context,
        location_ref=hq_location_ref or None,
    )
    cycle["current_superior_order"] = copy.deepcopy(current_order)
    if isinstance(current_directive, Mapping):
        cycle["current_superior_directive_ref"] = current_directive.get("directive_ref")
    _record_upward_report(cycle, at=at, phase=phase, snapshot=own, event_ref=event_ref)
    cycle["updated_at"] = at
    planner.put(path, cycle)
    return {"event_ref": event_ref, "command_context": command_context, "present_person_refs": hq_people}


def settle_campaign_command_host(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    kind = str(host.get("kind", ""))
    if kind == "campaign_command_council":
        return _settle_council(planner, host, at)
    if kind == "campaign_command_council_return":
        _settle_council_return(planner, host, at)
        return None
    if kind == "campaign_command_superior_order":
        return _settle_superior_order(planner, host, at)
    if kind == "campaign_command_after_action":
        return _settle_after_action_review(planner, host, at)
    if kind == "campaign_command_dawn":
        return _settle_daily(planner, host, at, phase="dawn")
    if kind == "campaign_command_evening":
        return _settle_daily(planner, host, at, phase="evening")
    raise ValueError(f"unsupported campaign command host kind: {kind}")


def campaign_command_projection(planner: Any, operation_ref: str) -> dict[str, Any] | None:
    """Read-only player-safe projection used by get_play_context.

    If the exact cycle has not yet been registered, derive only the current
    command-chain facts from the exact operation.  This lets a fresh deployment
    explain that a council is pending without mutating state during a read.
    """
    planner = _reader(planner)
    path = _operation_path(planner, operation_ref)
    operation = planner.read_optional(path) if isinstance(path, str) else None
    if not isinstance(operation, Mapping):
        return None
    existing = _read_cycle(planner, operation_ref)
    if existing is not None:
        cycle = existing[1]
        return {
            "cycle_ref": cycle.get("cycle_ref"),
            "status": cycle.get("status"),
            "venue_ref": cycle.get("venue_ref"),
            "forum_kind": cycle.get("forum_kind"),
            "court_state_ref": cycle.get("court_state_ref"),
            "coordination_authority_ref": cycle.get("coordination_authority_ref"),
            "supreme_commander_ref": cycle.get("supreme_commander_ref"),
            "superior_command_ref": cycle.get("superior_command_ref"),
            "participant_operation_refs": copy.deepcopy(cycle.get("participant_operation_refs", [])),
            "participant_commander_refs": copy.deepcopy(cycle.get("participant_commander_refs", [])),
            "war_council": copy.deepcopy(cycle.get("war_council")),
            "daily_cycle": copy.deepcopy(cycle.get("daily_cycle")),
            "delivered_superior_order_refs": copy.deepcopy(cycle.get("delivered_superior_order_refs", [])),
            "after_action_reviews": copy.deepcopy(cycle.get("after_action_reviews", [])),
            "upward_reports": copy.deepcopy(cycle.get("upward_reports", [])[-8:]) if isinstance(cycle.get("upward_reports"), list) else [],
            "current_superior_order": _current_superior_order(operation, cycle),
            "current_superior_directive": _current_superior_directive(operation),
        }
    coordination = _coordination_authority(operation)
    supreme = _supreme_commander(operation)
    participant_refs, commanders = _campaign_participants(planner, operation)
    return {
        "cycle_ref": _cycle_ref(operation_ref),
        "status": "pending_registration",
        "venue_ref": operation.get("location_ref"),
        "forum_kind": _council_forum(planner, operation, default_venue_ref=str(operation.get("location_ref") or "")).get("forum_kind"),
        "court_state_ref": _council_forum(planner, operation, default_venue_ref=str(operation.get("location_ref") or "")).get("court_state_ref"),
        "coordination_authority_ref": coordination,
        "supreme_commander_ref": supreme,
        "superior_command_ref": supreme or coordination,
        "participant_operation_refs": participant_refs,
        "participant_commander_refs": commanders,
        "war_council": {"status": "pending_registration"},
        "daily_cycle": {"status": "pending_war_council"},
        "delivered_superior_order_refs": [],
        "after_action_reviews": [],
        "upward_reports": [],
        "current_superior_order": _current_superior_order(operation, {
            "superior_command_ref": supreme or coordination,
            "coordination_authority_ref": coordination,
            "supreme_commander_ref": supreme,
        }),
        "current_superior_directive": _current_superior_directive(operation),
    }


__all__ = [
    "campaign_command_projection",
    "settle_campaign_command_host",
    "sync_campaign_command_cycle",
]
