"""Institution-owned receiving flow for already-accepted Qin field commands."""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any
from sword_runtime.operation_routing import exact_operation_record

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import get_causal_event, get_causal_event_from_reader
from sword_runtime.player_story_flow import (
    _ACTIVE_OPERATION_STATES,
    _BASE_PLAYER_AUTHORITY,
    _OPERATIONS_INDEX,
    _QIN_PATH,
    _appointment_row_mutable,
    _assumption_event_ref,
    _career_offer,
    _dispatch_player_story_message,
    _event_owner_write,
    _expire_pending_career_offers,
    _family_invitation_event,
    _house_digest_event,
    _pending_offer_refs,
    _player_delivery,
)
from sword_runtime.qin_command_progression import (
    assume_probationary_command,
    close_completed_service,
    normalize_new_qin_offers,
)
from sword_runtime.qin_detachment_command import assume_registered_qin_detachment_command
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_PLAYER_PATH = "state/player.json"
_HISTORY_WINDOW = 256
_INSTITUTION_REF = "inst_qin_military_bureau"
_RECEIVING_DELAY_SECONDS = 3600
_ASSUMPTION_DELAY_SECONDS = 60


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def _appointment_key(appointment: Mapping[str, Any]) -> str:
    return str(appointment.get("office") or appointment.get("source_event_ref") or appointment.get("formation_ref") or "")


def _receiving_ids(appointment: Mapping[str, Any]) -> tuple[str, str, str]:
    key = _appointment_key(appointment)
    digest = _digest("qin-command-receiving", key)
    return (
        f"host_qin_command_receiving_{digest}",
        f"event_qin_command_receiving_{digest}",
        f"event_qin_command_receiver_ready_{digest}",
    )


def _assumption_ids(appointment: Mapping[str, Any]) -> tuple[str, str]:
    digest = _digest("qin-command-assumption", _appointment_key(appointment))
    return f"host_qin_command_assumption_{digest}", f"event_qin_command_assumption_{digest}"


def _awaiting_appointments(player: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    career = player.get("career_state", {})
    appointments = career.get("appointments", []) if isinstance(career, Mapping) else []
    if not isinstance(appointments, list):
        return []
    return [
        row for row in appointments
        if isinstance(row, Mapping)
        and row.get("kind") == "qin_field_command"
        and row.get("state_ref") == "state_qin"
        and row.get("status") == "awaiting_assumption"
    ]


def _matching_appointment(planner: Any, attempt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if attempt.get("actor_id") != "char_tang_wei" or attempt.get("action") not in {"report", "seek_contact"}:
        return None
    target_ref = attempt.get("target_ref")
    if not isinstance(target_ref, str) or not target_ref.startswith("loc_"):
        return None
    player = planner.read(_PLAYER_PATH)
    if not isinstance(player, Mapping) or player.get("location") != target_ref:
        return None
    matches = [
        row for row in _awaiting_appointments(player)
        if row.get("report_to_location_ref") == target_ref
    ]
    return matches[0] if len(matches) == 1 else None


def _appointment_by_key(planner: Any, key: str) -> Mapping[str, Any] | None:
    player = planner.read(_PLAYER_PATH)
    if not isinstance(player, Mapping):
        return None
    matches = [row for row in _awaiting_appointments(player) if _appointment_key(row) == key]
    return matches[0] if len(matches) == 1 else None


def _schedule_one_shot(
    runtime: dict[str, Any], *, host_id: str, event_id: str, kind: str,
    priority: int, due: CampaignTime, row: dict[str, Any],
) -> None:
    hosts, events = runtime.get("hosts"), runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    existing_host = hosts.get(host_id)
    rescheduled = not isinstance(existing_host, dict) or existing_host.get("next_due") is None
    if rescheduled:
        row.update({
            "host_id": host_id,
            "kind": kind,
            "event_id": event_id,
            "recurrence_seconds": 0,
            "next_due": str(due),
            "safe_through": str(due.add_seconds(-1)),
        })
        hosts[host_id] = row
    existing_event = next(
        (event for event in events if isinstance(event, dict) and event.get("event_id") == event_id),
        None,
    )
    if isinstance(existing_event, dict):
        if rescheduled:
            existing_event.update({
                "kind": kind,
                "priority": priority,
                "target_host": host_id,
                "due_at": str(due),
            })
            existing_event.pop("suspended", None)
    else:
        events.append({
            "event_id": event_id,
            "kind": kind,
            "priority": priority,
            "target_host": host_id,
            "due_at": str(due),
        })


def _write_receiving_event(planner: Any, host: Mapping[str, Any], at: str) -> str | None:
    key = str(host.get("appointment_key", ""))
    appointment = _appointment_by_key(planner, key)
    if appointment is None:
        return None
    player = planner.read(_PLAYER_PATH)
    report_to = str(appointment.get("report_to_location_ref", ""))
    if not isinstance(player, Mapping) or player.get("location") != report_to:
        return None
    _host_id, _event_id, response_ref = _receiving_ids(appointment)
    if isinstance(get_causal_event_from_reader(planner, response_ref), Mapping):
        return response_ref
    summary = (
        "At the saved Qin reporting site, the Qin Military Bureau receiving authority accepts Tang Wei's already-declared report for his pending field command. "
        "A lawful receiver and assumption process are now established. This handoff does not itself transfer command authority, troop custody, ownership, deployment authority, or manpower."
    )
    return _event_owner_write(planner, response_ref, {
        "event_ref": response_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": _INSTITUTION_REF,
        "target_ref": "char_tang_wei",
        "basis_goal": "Receive Tang Wei's already-authorized report for an accepted Qin field command",
        "process_kind": "qin_field_command_assumption",
        "process_stage": "receiver_ready",
        "source_event_ref": str(appointment.get("source_event_ref", "")),
        "summary": summary,
        "delivery": _player_delivery(planner, "Qin Military Bureau receiving authority at the saved report site"),
    }, at, source_owner_ref=_INSTITUTION_REF)


def _assume_direct_qin_command(planner: Any, appointment: Mapping[str, Any], at: str) -> str | None:
    """Settle one exact Qin unit command at its saved institutional report site."""
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    formation_ref = str(appointment.get("formation_ref", ""))
    operation_ref = str(appointment.get("operation_ref", ""))
    offer_ref = str(appointment.get("source_event_ref", ""))
    office = str(appointment.get("office", f"field_command:{formation_ref}"))
    report_to = str(appointment.get("report_to_location_ref", ""))
    if not formation_ref or not operation_ref or not offer_ref or not report_to:
        return None
    if str(player.get("location", "")) != report_to:
        return None

    try:
        formation_path = planner.owner_path(formation_ref)
        formation = copy.deepcopy(planner.read(formation_path))
    except (KeyError, ValueError, FileNotFoundError):
        return None
    resolved_operation = exact_operation_record(planner, operation_ref)
    operation_path, operation = resolved_operation if resolved_operation is not None else (None, None)
    still_open = (
        isinstance(operation, Mapping)
        and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
        and formation.get("commander_ref") in {None, ""}
        and str(formation.get("administrative_owner", "")) == "state_qin"
        and formation_ref in operation.get("formation_refs", [])
    )
    event_ref = _assumption_event_ref(formation_ref, offer_ref)
    if not still_open:
        if isinstance(get_causal_event(planner, event_ref), Mapping):
            return event_ref
        row = _appointment_row_mutable(player, office)
        if row is not None:
            row["status"] = "lapsed_before_assumption"
            row["lapsed_at"] = at
            player["authority"] = str(row.get("prior_authority", _BASE_PLAYER_AUTHORITY))
        qin = copy.deepcopy(planner.read(_QIN_PATH))
        qin_appointment = qin.setdefault("appointments", {}).get(office)
        if isinstance(qin_appointment, dict):
            qin_appointment["status"] = "lapsed_before_assumption"
            qin_appointment["lapsed_at"] = at
        planner.put(_PLAYER_PATH, player)
        planner.put(_QIN_PATH, qin)
        summary = (
            "A Qin Military Bureau courier reports that the field-command appointment could not be assumed because the exact vacancy or operation ceased to be available before Tang Wei reported in. "
            "No formation command authority or troop custody transfers from the lapsed appointment."
        )
        return _event_owner_write(planner, event_ref, {
            "event_ref": event_ref,
            "kind": "institutional_response",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": _INSTITUTION_REF,
            "target_ref": "char_tang_wei",
            "process_kind": "qin_field_command_offer",
            "process_stage": "lapsed_before_assumption",
            "source_event_ref": offer_ref,
            "summary": summary,
            "delivery": _player_delivery(planner, "Qin Military Bureau courier"),
        }, at, source_owner_ref=_INSTITUTION_REF)

    if isinstance(get_causal_event(planner, event_ref), Mapping):
        return event_ref
    personnel_before = int(formation.get("personnel", 0))
    administrative_owner = str(formation.get("administrative_owner", ""))
    planner._assign_commander_index("char_tang_wei", formation_ref)
    formation["commander_ref"] = "char_tang_wei"
    formation["command_authority"] = "char_tang_wei"
    formation["command_last_changed_at"] = at
    formation["command_assignment_source_ref"] = offer_ref
    if int(formation.get("personnel", 0)) != personnel_before or str(formation.get("administrative_owner", "")) != administrative_owner:
        raise ValueError("Qin command assumption must conserve formation manpower and administrative ownership")
    planner.put(formation_path, formation)

    row = _appointment_row_mutable(player, office)
    if row is not None:
        row["status"] = "active"
        row["assumed_at"] = at
    player["authority"] = (
        f"House Tang heir; patron and commander of Tang Wei Personal Retinue; Qin field commander of {formation.get('name', formation_ref)}"
    )
    planner.put(_PLAYER_PATH, player)

    qin = copy.deepcopy(planner.read(_QIN_PATH))
    qin_appointment = qin.setdefault("appointments", {}).get(office)
    if isinstance(qin_appointment, dict):
        qin_appointment["status"] = "active"
        qin_appointment["assumed_at"] = at
    administration = qin.setdefault("military_administration", {})
    administration["commander_vacancy_count"] = max(0, int(administration.get("commander_vacancy_count", 0)) - 1)
    administration["last_commander_assignment_at"] = at
    planner.put(_QIN_PATH, qin)

    staffing_status = str(appointment.get("staffing_request_status", ""))
    staffing_note = (
        " The saved staffing requirement remains outstanding and must be satisfied before tactical employment."
        if staffing_status == "required_before_tactical_employment"
        else ""
    )
    summary = (
        f"Tang Wei reports through the lawful Qin receiving authority at {report_to} and formally assumes the Qin field command already accepted. "
        f"Command authority over {formation.get('name', formation_ref)}, an existing {personnel_before}-man Qin formation, is now active under Tang Wei. "
        "Administrative ownership and existing manpower remain Qin's; the appointment does not itself move the formation, choose a march route, battle plan, sovereign allegiance, or permanent strategy."
        + staffing_note
    )
    return _event_owner_write(planner, event_ref, {
        "event_ref": event_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": _INSTITUTION_REF,
        "target_ref": "char_tang_wei",
        "basis_goal": "Assume an already-accepted Qin field command at its exact registered report location",
        "process_kind": "qin_field_command_offer",
        "process_stage": "command_assumed",
        "source_event_ref": offer_ref,
        "summary": summary[:4000],
        "delivery": _player_delivery(planner, "Qin field-command assumption record"),
    }, at, source_owner_ref=_INSTITUTION_REF)


def _settle_assumption(planner: Any, host: Mapping[str, Any], at: str) -> str | None:
    key = str(host.get("appointment_key", ""))
    appointment = _appointment_by_key(planner, key)
    if appointment is None:
        return None
    _rh, _re, receiver_ref = _receiving_ids(appointment)
    receiver = get_causal_event_from_reader(planner, receiver_ref)
    if not isinstance(receiver, Mapping) or receiver.get("process_stage") != "receiver_ready":
        return None
    player = planner.read(_PLAYER_PATH)
    report_to = str(appointment.get("report_to_location_ref", ""))
    if not isinstance(player, Mapping) or player.get("location") != report_to:
        return None
    colocated = [row for row in _awaiting_appointments(player) if row.get("report_to_location_ref") == report_to]
    if len(colocated) != 1 or _appointment_key(colocated[0]) != key:
        raise ValueError("Qin command assumption requires one exact pending appointment at the receiving site")

    offer_kind = str(appointment.get("offer_kind", ""))
    if offer_kind == "qin_probationary_detachment_command":
        return assume_probationary_command(planner, at)
    formation_refs = appointment.get("formation_refs")
    if isinstance(formation_refs, list) and formation_refs:
        return assume_registered_qin_detachment_command(planner, at)
    return _assume_direct_qin_command(planner, appointment, at)


def _close_unavailable_awaiting_appointments(planner: Any, at: str) -> list[str]:
    """Close accepted Qin appointments whose physical command no longer exists.

    This runs independently of Wei reporting to the appointment site. Otherwise
    a closed operation can leave an `awaiting_assumption` decision blocking later
    career flow forever merely because no receiving host ever becomes eligible.
    """
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    qin = copy.deepcopy(planner.read(_QIN_PATH))
    changed = False
    notices: list[tuple[str, str, str]] = []
    for appointment in _awaiting_appointments(player):
        formation_ref = str(appointment.get("formation_ref", ""))
        parent_ref = str(appointment.get("parent_formation_ref", ""))
        operation_ref = str(appointment.get("operation_ref", ""))
        offer_ref = str(appointment.get("source_event_ref", ""))
        office = str(appointment.get("office", ""))
        offer_kind = str(appointment.get("offer_kind", ""))
        resolved = exact_operation_record(planner, operation_ref)
        operation = resolved[1] if resolved is not None else None
        valid = False
        if offer_kind == "qin_probationary_detachment_command":
            try:
                parent = planner.read(planner.owner_path(parent_ref))
            except (KeyError, ValueError, FileNotFoundError):
                parent = None
            valid = bool(
                isinstance(parent, Mapping)
                and isinstance(operation, Mapping)
                and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
                and str(parent.get("administrative_owner", "")) == "state_qin"
                and parent_ref in operation.get("formation_refs", [])
                and int(parent.get("personnel", 0)) > int(appointment.get("personnel", 0)) > 0
            )
        else:
            try:
                formation = planner.read(planner.owner_path(formation_ref))
            except (KeyError, ValueError, FileNotFoundError):
                formation = None
            valid = bool(
                isinstance(formation, Mapping)
                and isinstance(operation, Mapping)
                and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
                and formation.get("commander_ref") in {None, ""}
                and str(formation.get("administrative_owner", "")) == "state_qin"
                and formation_ref in operation.get("formation_refs", [])
            )
        if valid:
            continue
        row = _appointment_row_mutable(player, office)
        if row is not None:
            row["status"] = "lapsed_before_assumption"
            row["lapsed_at"] = at
            player["authority"] = str(row.get("prior_authority", _BASE_PLAYER_AUTHORITY))
        qin_row = qin.setdefault("appointments", {}).get(office)
        if isinstance(qin_row, dict):
            qin_row["status"] = "lapsed_before_assumption"
            qin_row["lapsed_at"] = at
        changed = True
        notice_ref = "event_story_qin_command_lapsed_" + _digest("lapse", f"{office}|{offer_ref}")
        summary = (
            "A Qin Military Bureau courier reports that the accepted field-command appointment can no longer be assumed because the exact vacancy or operation ceased to be available before Tang Wei reported in. "
            "No formation command authority or troop custody transfers from the lapsed appointment."
        )
        notices.append((notice_ref, offer_ref, summary))
    if changed:
        planner.put(_PLAYER_PATH, player)
        planner.put(_QIN_PATH, qin)
    created: list[str] = []
    for notice_ref, offer_ref, summary in notices:
        if isinstance(get_causal_event(planner, notice_ref), Mapping):
            continue
        _dispatch_player_story_message(
            planner, event_ref=notice_ref, at=at, actor_ref=_INSTITUTION_REF,
            source_owner_ref=_INSTITUTION_REF, event_kind="institutional_response",
            process_kind="qin_field_command_offer", transit_stage="lapse_notice_in_transit",
            delivered_stage="lapsed_before_assumption", delivered_summary=summary,
            route_label="Qin Military Bureau courier", source_event_ref=offer_ref,
            delivery_kind="qin_appointment_lapse_notice",
        )
        created.append(notice_ref)
    return created


def _safe_story_review(planner: Any, at: str) -> None:
    """Run durable story work without manufacturing a chronology wake.

    Offers that expire are closed in their exact career owner here, so the
    production review cannot leave an ignored decision blocking later career
    flow forever. Player-directed messages are dispatched through physical
    courier hosts by their builders and become player-facing only on delivery.
    """
    before = set(_pending_offer_refs(planner.read(_PLAYER_PATH)))
    lapsed_offers = _expire_pending_career_offers(planner, at)
    _close_unavailable_awaiting_appointments(planner, at)
    close_completed_service(planner, at)
    builders = [_house_digest_event, _family_invitation_event]
    if not lapsed_offers:
        builders.insert(0, _career_offer)
    for builder in builders:
        builder(planner, at)
    after = set(_pending_offer_refs(planner.read(_PLAYER_PATH)))
    # Co-located delivery can make a new offer live during this same callback;
    # remote offers normalize only when their courier actually arrives.
    normalize_new_qin_offers(planner, at, after - before)
    return None


def sync_qin_command_assumption_flow(planner: Any, runtime: dict[str, Any]) -> None:
    current_text = runtime.get("world_time")
    if not isinstance(current_text, str):
        raise ValueError("runtime causal queue is invalid")
    current = CampaignTime.parse(current_text)

    attempts, _ = recent_interaction_attempts(planner, "char_tang_wei", limit=_HISTORY_WINDOW)
    for attempt in attempts:
        requested_at = attempt.get("at")
        if not isinstance(requested_at, str):
            continue
        attempt_ref = interaction_attempt_ref(attempt)
        appointment = _matching_appointment(planner, attempt)
        if appointment is None:
            continue
        host_id, event_id, response_ref = _receiving_ids(appointment)
        if isinstance(get_causal_event_from_reader(planner, response_ref), Mapping):
            continue
        due_raw = CampaignTime.parse(requested_at).add_seconds(_RECEIVING_DELAY_SECONDS)
        due = max(current, due_raw)
        _schedule_one_shot(runtime, host_id=host_id, event_id=event_id, kind="qin_command_receiving", priority=44, due=due, row={
            "owner_ref": _INSTITUTION_REF,
            "appointment_key": _appointment_key(appointment),
            "appointment_office": str(appointment.get("office", "")),
            "source_event_ref": str(appointment.get("source_event_ref", "")),
            "report_to_location_ref": str(appointment.get("report_to_location_ref", "")),
            "attempt_ref": attempt_ref,
            "source_event_id": str(attempt.get("event_id", "")),
            "resolved_through": str(current if current < due else due.add_seconds(-1)),
        })

    player = planner.read(_PLAYER_PATH)
    if not isinstance(player, Mapping):
        return
    for appointment in _awaiting_appointments(player):
        host_id, event_id = _assumption_ids(appointment)
        _rh, _re, receiver_ref = _receiving_ids(appointment)
        if not isinstance(get_causal_event_from_reader(planner, receiver_ref), Mapping):
            continue
        if player.get("location") != appointment.get("report_to_location_ref"):
            continue
        due = current.add_seconds(_ASSUMPTION_DELAY_SECONDS)
        _schedule_one_shot(runtime, host_id=host_id, event_id=event_id, kind="qin_command_assumption", priority=45, due=due, row={
            "owner_ref": _INSTITUTION_REF,
            "appointment_key": _appointment_key(appointment),
            "appointment_office": str(appointment.get("office", "")),
            "source_event_ref": str(appointment.get("source_event_ref", "")),
            "source_receiver_ref": receiver_ref,
            "report_to_location_ref": str(appointment.get("report_to_location_ref", "")),
            "resolved_through": str(current),
        })


class QinCommandAssumptionFlowMixin:
    """Bridge player report attempts into Qin-owned receiving and assumption work."""

    # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = [
    "QinCommandAssumptionFlowMixin",
    "sync_qin_command_assumption_flow",
]
