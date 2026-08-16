"""Assumption lifecycle for a registered multi-formation Qin field command.

A detachment appointment may own several persistent Qin formations while each unit
keeps its own commander and deputy. Tang Wei's assumption therefore transfers the
higher formation command authority only after he physically reports; it never
overwrites the units' exact senior officers or their Qin administrative ownership.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.player_story_flow import (
    _ACTIVE_OPERATION_STATES,
    _BASE_PLAYER_AUTHORITY,
    _OPERATIONS_INDEX,
    _PLAYER_PATH,
    _QIN_PATH,
    _event_owner_write,
    _player_delivery,
)


def appointment_formation_refs(appointment: Mapping[str, Any]) -> list[str]:
    raw = appointment.get("formation_refs")
    refs = [str(ref) for ref in raw if isinstance(ref, str) and ref] if isinstance(raw, list) else []
    lead = appointment.get("formation_ref")
    if isinstance(lead, str) and lead and lead not in refs:
        refs.insert(0, lead)
    return list(dict.fromkeys(refs))


def _event_ref(appointment: Mapping[str, Any]) -> str:
    refs = appointment_formation_refs(appointment)
    payload = "|".join(refs + [str(appointment.get("source_event_ref", ""))])
    return "event_story_qin_detachment_assumed_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _appointment_row(player: dict[str, Any], office: str) -> dict[str, Any] | None:
    rows = player.setdefault("career_state", {}).setdefault("appointments", [])
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("office", "")) == office:
            return row
    return None


def assume_registered_qin_detachment_command(planner: Any, at: str) -> str | None:
    """Assume one already-accepted multi-formation Qin appointment when co-located."""

    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    appointments = player.get("career_state", {}).get("appointments", []) if isinstance(player.get("career_state"), Mapping) else []
    if not isinstance(appointments, list):
        return None
    operation_index = planner.read(_OPERATIONS_INDEX)

    for raw in appointments:
        if not isinstance(raw, Mapping) or raw.get("kind") != "qin_field_command":
            continue
        if str(raw.get("status", "")) != "awaiting_assumption":
            continue
        refs = appointment_formation_refs(raw)
        if len(refs) <= 1 and str(raw.get("command_scope", "")) != "multi_formation_detachment":
            continue
        office = str(raw.get("office", ""))
        operation_ref = str(raw.get("operation_ref", ""))
        offer_ref = str(raw.get("source_event_ref", ""))
        if not office or not operation_ref or not offer_ref or not refs:
            continue

        operation_path = operation_index.get("operations", {}).get(operation_ref) if isinstance(operation_index, Mapping) else None
        operation = copy.deepcopy(planner.read(operation_path)) if isinstance(operation_path, str) else None
        formations: list[tuple[str, str, dict[str, Any]]] = []
        valid = isinstance(operation, Mapping) and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
        if valid:
            operation_refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}
            valid = all(ref in operation_refs for ref in refs)
        if valid:
            for ref in refs:
                try:
                    path = planner.owner_path(ref)
                    formation = copy.deepcopy(planner.read(path))
                except (KeyError, ValueError, FileNotFoundError):
                    valid = False
                    break
                if (
                    str(formation.get("administrative_owner", "")) != "state_qin"
                    or int(formation.get("personnel", 0)) <= 0
                ):
                    valid = False
                    break
                formations.append((ref, path, formation))

        event_ref = _event_ref(raw)
        if not valid:
            if isinstance(get_causal_event(planner, event_ref), Mapping):
                continue
            row = _appointment_row(player, office)
            if row is not None:
                row["status"] = "lapsed_before_assumption"
                row["lapsed_at"] = at
                player["authority"] = str(row.get("prior_authority", _BASE_PLAYER_AUTHORITY))
            qin = copy.deepcopy(planner.read(_QIN_PATH))
            qin_row = qin.setdefault("appointments", {}).get(office)
            if isinstance(qin_row, dict):
                qin_row["status"] = "lapsed_before_assumption"
                qin_row["lapsed_at"] = at
            planner.put(_PLAYER_PATH, player)
            planner.put(_QIN_PATH, qin)
            return _event_owner_write(planner, event_ref, {
                "event_ref": event_ref,
                "kind": "institutional_response",
                "status": "triggered",
                "due_at": at,
                "triggered_at": at,
                "actor_ref": "inst_qin_military_bureau",
                "target_ref": "char_tang_wei",
                "process_kind": "qin_field_command_offer",
                "process_stage": "multi_formation_command_lapsed_before_assumption",
                "source_event_ref": offer_ref,
                "summary": "The Qin Military Bureau reports that the accepted multi-formation field command can no longer be assumed because its registered operation or one of its constituent Qin units ceased to be available. No command authority or troop custody transfers.",
                "delivery": _player_delivery(planner, "Qin Military Bureau courier"),
            }, at, source_owner_ref="inst_qin_military_bureau")

        report_location = str(raw.get("report_to_location_ref", ""))
        if not report_location and formations:
            report_location = str(formations[0][2].get("location_ref", ""))
        if str(player.get("location", "")) != report_location:
            continue
        if isinstance(get_causal_event(planner, event_ref), Mapping):
            continue

        for ref, path, formation in formations:
            formation["command_authority"] = "char_tang_wei"
            formation["higher_command_appointment_ref"] = office
            formation["command_last_changed_at"] = at
            formation["command_assignment_source_ref"] = offer_ref
            planner.put(path, formation)

        row = _appointment_row(player, office)
        if row is not None:
            row["status"] = "active"
            row["assumed_at"] = at
            row["formation_refs"] = refs
        total_fighting = sum(int(formation.get("personnel", 0)) for _ref, _path, formation in formations)
        player["authority"] = (
            "House Tang heir; patron and commander of Tang Wei Personal Retinue; "
            f"Qin field commander of the Qin Border Detachment ({len(refs)} persistent units, {total_fighting} fighting troops)"
        )
        planner.put(_PLAYER_PATH, player)

        qin = copy.deepcopy(planner.read(_QIN_PATH))
        qin_row = qin.setdefault("appointments", {}).get(office)
        if isinstance(qin_row, dict):
            qin_row["status"] = "active"
            qin_row["assumed_at"] = at
            qin_row["formation_refs"] = refs
        administration = qin.setdefault("military_administration", {})
        administration["last_detachment_command_assumed_at"] = at
        planner.put(_QIN_PATH, qin)

        names = ", ".join(str(formation.get("name", ref)) for ref, _path, formation in formations)
        summary = (
            f"Tang Wei reports to {report_location} and formally assumes the accepted Qin Border Detachment field command. "
            f"Higher command authority now covers {len(refs)} persistent Qin units totaling {total_fighting} fighting troops: {names}. "
            "Each unit keeps its own exact commander and deputy; administrative ownership remains Qin's. The appointment itself chooses no march route, battle plan, sovereign allegiance, or permanent strategy."
        )[:4000]
        return _event_owner_write(planner, event_ref, {
            "event_ref": event_ref,
            "kind": "institutional_response",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": "inst_qin_military_bureau",
            "target_ref": "char_tang_wei",
            "basis_goal": "Assume an already-accepted multi-formation Qin field command at its exact report location",
            "process_kind": "qin_field_command_offer",
            "process_stage": "multi_formation_command_assumed",
            "source_event_ref": offer_ref,
            "summary": summary,
            "delivery": _player_delivery(planner, "Qin detachment field-command assumption record"),
        }, at, source_owner_ref="inst_qin_military_bureau")
    return None


__all__ = ["appointment_formation_refs", "assume_registered_qin_detachment_command"]
