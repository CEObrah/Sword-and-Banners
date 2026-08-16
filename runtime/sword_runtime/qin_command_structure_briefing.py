"""Replace the legacy flat-Qin briefing with persisted aggregate command depth."""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.warfare_depth import build_formation_command_structure

_PLAYER_PATH = "state/player.json"
_QIN_PATH = "state/states/qin.json"
_RULES_PATH = "game/data/mechanics/warfare-organization.json"
_OLD = (
    "The current formation record contains no subordinate formation registry, no deputy commander, and no named subordinate commander or officer billets. "
    "Qin therefore cannot truthfully provide names or smaller-unit commanders that are not registered. Tang Wei's request to establish qualified subordinate command and deputy coverage is recorded as a command-readiness requirement, not treated as already completed."
)


def _structure_text(structure: Mapping[str, Any]) -> str:
    return (
        f"The formation's internal command ledger registers {int(structure.get('century_elements', 0))} hundred-man elements, "
        f"{int(structure.get('company_elements', 0))} roughly five-hundred-man companies and {int(structure.get('wing_elements', 0))} roughly two-thousand-man wings, "
        f"with {int(structure.get('deputy_billets', 0))} deputy billet, {int(structure.get('staff_billets', 0))} staff billets, "
        f"{int(structure.get('signal_billets', 0))} signal billets and {int(structure.get('logistics_billets', 0))} logistics billets. "
        "Those functions are contained inside the formation's existing personnel and add no bodies. Named subordinate officers are not fabricated from aggregate staff; exact officers are materialized only when individually relevant or formally appointed."
    )


def project_qin_command_structure_briefing(planner: Any, host: Mapping[str, Any]) -> None:
    formation_ref = str(host.get("formation_ref", ""))
    response_ref = str(host.get("response_event_ref", ""))
    office = str(host.get("office", ""))
    if not formation_ref or not response_ref:
        return
    path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(path))
    structure = formation.get("command_structure")
    if not isinstance(structure, Mapping):
        structure = build_formation_command_structure(formation, planner.read(_RULES_PATH))
        formation["command_structure"] = copy.deepcopy(structure)
        planner.put(path, formation)

    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    appointments = player.setdefault("career_state", {}).setdefault("appointments", [])
    for row in appointments:
        if isinstance(row, MutableMapping) and row.get("office") == office and str(row.get("status", "")) in {"awaiting_assumption", "active"}:
            row["command_structure_status"] = "aggregate_internal_echelons_registered"
            row["staffing_request_status"] = "aggregate_staff_registered_named_officers_unmaterialized"
            row["briefed_command_structure"] = copy.deepcopy(dict(structure))
    planner.put(_PLAYER_PATH, player)

    qin = copy.deepcopy(planner.read(_QIN_PATH))
    appointment = qin.setdefault("appointments", {}).get(office)
    if isinstance(appointment, MutableMapping):
        appointment["command_structure_status"] = "aggregate_internal_echelons_registered"
        appointment["staffing_request_status"] = "aggregate_staff_registered_named_officers_unmaterialized"
        appointment["briefed_command_structure"] = copy.deepcopy(dict(structure))
        planner.put(_QIN_PATH, qin)

    _event_path, owner = read_causal_event_owner(planner)
    event = owner.get("causal_events", {}).get(response_ref)
    if isinstance(event, MutableMapping):
        summary = str(event.get("summary", ""))
        replacement = _structure_text(structure)
        if _OLD in summary:
            summary = summary.replace(_OLD, replacement)
        elif replacement not in summary:
            summary = (summary + " " + replacement)[:4000]
        event["summary"] = summary[:4000]
        event["process_stage"] = "briefing_delivered_aggregate_command_structure_registered"
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
