"""Project Qin's persisted command establishment into the player briefing."""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.warfare_depth import build_formation_command_structure

_PLAYER_PATH = "state/player.json"
_QIN_PATH = "state/states/qin.json"
_RULES_PATH = "game/data/mechanics/warfare-organization.json"


def _hierarchy_text(structure: Mapping[str, Any]) -> str:
    rows = structure.get("internal_hierarchy", [])
    parts = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        parts.append(f"{int(row.get('count', 0))} x {int(row.get('scale', 0))}-man commanders")
    return ", ".join(parts)


def _structure_text(structure: Mapping[str, Any]) -> str:
    fighting = int(structure.get("fighting_establishment", 0))
    command = structure.get("unit_command", {}) if isinstance(structure.get("unit_command"), Mapping) else {}
    commander_billets = int(command.get("commander_billets", 0))
    senior = commander_billets
    return (
        f"Qin Unit fighting establishment: {fighting}. "
        f"The Unit has {commander_billets} top commander outside that fighting-strength count. "
        f"Inside the same conserved {fighting} fighting troops are {_hierarchy_text(structure)}. "
        "Internal commanders occupy soldier slots already counted in fighting strength. "
        "Routine staff work, messengers, supply handling and medical assistance create no separate mandatory manpower quota; their effectiveness comes from the actual command hierarchy, communications, logistics, medicine, resources, readiness, cohesion and conditions. "
        f"Authorized attached headcount is therefore {int(structure.get('attached_personnel_target', fighting + senior))} including Unit command, while fighting establishment remains {fighting}."
    )


def project_qin_command_structure_briefing(planner: Any, host: Mapping[str, Any]) -> None:
    formation_ref = str(host.get("formation_ref", ""))
    response_ref = str(host.get("response_event_ref", ""))
    office = str(host.get("office", ""))
    if not formation_ref or not response_ref:
        return
    path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(path))
    structure = build_formation_command_structure(formation, planner.read(_RULES_PATH))
    formation.pop("command_structure", None)
    planner.put(path, formation)

    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    appointments = player.setdefault("career_state", {}).setdefault("appointments", [])
    for row in appointments:
        if isinstance(row, MutableMapping) and row.get("office") == office and str(row.get("status", "")) in {"awaiting_assumption", "active"}:
            row["command_structure_status"] = "scale_aware_command_establishment_registered"
            row["staffing_request_status"] = "named_unit_command_requires_conserved_materialization"
            row["briefed_command_structure"] = copy.deepcopy(dict(structure))
    planner.put(_PLAYER_PATH, player)

    qin = copy.deepcopy(planner.read(_QIN_PATH))
    appointment = qin.setdefault("appointments", {}).get(office)
    if isinstance(appointment, MutableMapping):
        appointment["command_structure_status"] = "scale_aware_command_establishment_registered"
        appointment["staffing_request_status"] = "named_unit_command_requires_conserved_materialization"
        appointment["briefed_command_structure"] = copy.deepcopy(dict(structure))
        planner.put(_QIN_PATH, qin)

    _event_path, owner = read_causal_event_owner(planner)
    event = owner.get("causal_events", {}).get(response_ref)
    if isinstance(event, MutableMapping):
        replacement = _structure_text(structure)
        event["summary"] = (str(event.get("summary", "")) + " " + replacement).strip()[:4000]
        event["process_stage"] = "briefing_delivered_scale_aware_command_establishment_registered"
        write_causal_event_owner(planner, owner)
        wake = getattr(planner, "_pending_wake_created", None)
        if isinstance(wake, MutableMapping) and wake.get("campaign_event_ref") == response_ref:
            wake["reason"] = event["summary"]


class QinCommandStructureBriefingProjectionMixin:
    pass  # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = ["QinCommandStructureBriefingProjectionMixin", "project_qin_command_structure_briefing"]
