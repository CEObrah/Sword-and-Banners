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


def _support_text(structure: Mapping[str, Any]) -> str:
    support = structure.get("external_support", {})
    if not isinstance(support, Mapping):
        return "no external support target registered"
    targets = support.get("targets_by_role", {})
    if not isinstance(targets, Mapping):
        return "no external support target registered"
    labels = {
        "command_personnel": "command staff/clerks",
        "signal": "signal/scout personnel",
        "logistics": "quartermaster/medical/logistics personnel",
    }
    return ", ".join(f"{int(count)} {labels.get(str(role), str(role))}" for role, count in targets.items())


def _structure_text(structure: Mapping[str, Any]) -> str:
    fighting = int(structure.get("fighting_establishment", 0))
    command = structure.get("unit_command", {}) if isinstance(structure.get("unit_command"), Mapping) else {}
    commander_billets = int(command.get("commander_billets", 0))
    deputy_billets = int(command.get("deputy_billets", 0))
    senior = commander_billets + deputy_billets
    support = structure.get("external_support", {}) if isinstance(structure.get("external_support"), Mapping) else {}
    support_total = int(support.get("target_total", 0))
    return (
        f"QIN Border Line fighting establishment: {fighting}. "
        f"Senior unit command sits above that fighting-strength count: {commander_billets} acting senior officer and {deputy_billets} deputy, so the command establishment is {fighting + senior} before support. "
        f"Inside the same conserved {fighting} fighting troops are {_hierarchy_text(structure)}. "
        "Those internal commanders occupy soldier slots already counted in fighting strength; their command nodes neither add manpower nor create persistent unit slots. "
        f"External support is separately conserved outside fighting strength: {_support_text(structure)}, {support_total} support bodies when fully staffed. "
        f"Fully staffed attached headcount is therefore {int(structure.get('attached_personnel_target', fighting + senior + support_total))}, while combat strength remains {fighting}. "
        "Named officers must be materialized from their lawful conserved source before the briefing may identify them as real people."
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
    formation["command_structure"] = copy.deepcopy(structure)
    planner.put(path, formation)

    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    appointments = player.setdefault("career_state", {}).setdefault("appointments", [])
    for row in appointments:
        if isinstance(row, MutableMapping) and row.get("office") == office and str(row.get("status", "")) in {"awaiting_assumption", "active"}:
            row["command_structure_status"] = "scale_aware_command_establishment_registered"
            row["staffing_request_status"] = "named_command_and_support_require_conserved_materialization"
            row["briefed_command_structure"] = copy.deepcopy(dict(structure))
    planner.put(_PLAYER_PATH, player)

    qin = copy.deepcopy(planner.read(_QIN_PATH))
    appointment = qin.setdefault("appointments", {}).get(office)
    if isinstance(appointment, MutableMapping):
        appointment["command_structure_status"] = "scale_aware_command_establishment_registered"
        appointment["staffing_request_status"] = "named_command_and_support_require_conserved_materialization"
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
    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        if host.get("kind") == "qin_command_briefing_reply":
            project_qin_command_structure_briefing(self, host)


__all__ = ["QinCommandStructureBriefingProjectionMixin", "project_qin_command_structure_briefing"]
