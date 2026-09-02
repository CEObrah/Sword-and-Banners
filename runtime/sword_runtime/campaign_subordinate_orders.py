"""Materialize exact NPC subordinate orders from a held campaign command decision.

The campaign staff scheme is advisory.  It becomes executable only when the exact
campaign command cycle is already held, a named NPC supreme commander exists, the
sovereign has lawful hostile-entry authority, and the assigned formations belong to
the exact autonomous participant operation.  This module records that command
consequence; it never moves a formation, transfers ownership, or acts for Tang Wei.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_briefing import build_campaign_dossier
from sword_runtime.operation_routing import exact_operation_record
from sword_runtime.sovereign_campaign_authority import hostile_entry_authorized


_PLAYER_REF = "char_tang_wei"
_PLAYER_ROOT_GROUP = "cmdgrp.tang_wei.field_army"
_RUNTIME_PATH = "state/runtime.json"
_ACTIVE_OPERATION_STATUSES = frozenset({"planned", "mobilizing", "active", "advancing"})
_TERMINAL_ORDER_STATUSES = frozenset({"completed", "cancelled", "canceled", "withdrawn", "terminated", "superseded"})


def _digest(*parts: object) -> str:
    text = "|".join(str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def _player_operation_ref(planner: Any) -> str | None:
    try:
        root = planner.read(f"state/cmd/command-groups/{_PLAYER_ROOT_GROUP}.json")
    except (FileNotFoundError, KeyError, ValueError):
        return None
    ref = root.get("active_context_ref") if isinstance(root, Mapping) else None
    return str(ref) if isinstance(ref, str) and ref else None


def _latest_order(operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    ref = str(operation.get("last_operational_order_ref", ""))
    rows = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    for row in reversed(rows):
        if not isinstance(row, Mapping):
            continue
        if ref and str(row.get("order_ref", "")) != ref:
            continue
        return row
    current = operation.get("current_operational_order")
    return current if isinstance(current, Mapping) else None


def _actionable_destination(order: Mapping[str, Any] | None) -> str | None:
    if not isinstance(order, Mapping):
        return None
    if str(order.get("status", "")) in _TERMINAL_ORDER_STATUSES:
        return None
    if str(order.get("actionability_status", "")) not in {"actionable", "executing"}:
        return None
    packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else {}
    destination = packet.get("destination_ref")
    return str(destination) if isinstance(destination, str) and destination else None


def _campaign_cycle(planner: Any, operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    cycle_ref = operation.get("campaign_command_cycle_ref")
    if not isinstance(cycle_ref, str) or not cycle_ref:
        return None
    try:
        row = planner.read(planner.owner_path(cycle_ref))
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _scheme_assignments(planner: Any, player_operation_ref: str) -> tuple[Mapping[str, Any], list[dict[str, Any]]]:
    dossier = build_campaign_dossier(planner, player_operation_ref)
    planning = dossier.get("march_planning") if isinstance(dossier.get("march_planning"), Mapping) else {}
    scheme = planning.get("campaign_scheme") if isinstance(planning.get("campaign_scheme"), Mapping) else {}
    rows = scheme.get("command_assignments") if isinstance(scheme.get("command_assignments"), list) else []
    return scheme, [copy.deepcopy(dict(row)) for row in rows if isinstance(row, Mapping)]


def sync_campaign_subordinate_orders(planner: Any, *, at: str | None = None) -> list[str]:
    """Adopt current staff assignments into exact NPC operational orders.

    The staff projection is not itself authority.  This function is the explicit
    command-adoption boundary: a held campaign council plus a named supreme
    commander and sovereign entry authority are required before an NPC participant
    operation receives a formation-scoped executable order.
    """
    player_operation_ref = _player_operation_ref(planner)
    if not player_operation_ref:
        return []
    player_resolved = exact_operation_record(planner, player_operation_ref)
    if player_resolved is None:
        return []
    _player_path, player_operation = player_resolved
    cycle = _campaign_cycle(planner, player_operation)
    if not isinstance(cycle, Mapping):
        return []
    council = cycle.get("war_council") if isinstance(cycle.get("war_council"), Mapping) else {}
    if str(council.get("status", "")) != "held":
        return []
    supreme = cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref")
    if not isinstance(supreme, str) or not supreme or supreme == _PLAYER_REF:
        return []
    participant_refs = {
        str(ref) for ref in cycle.get("participant_operation_refs", [])
        if isinstance(ref, str) and ref
    }
    if not participant_refs:
        return []

    scheme, assignments = _scheme_assignments(planner, player_operation_ref)
    state_ref = scheme.get("campaign_state_ref")
    target_state_ref = scheme.get("target_state_ref")
    if not isinstance(state_ref, str) or not state_ref.startswith("state_"):
        return []
    if not isinstance(target_state_ref, str) or not target_state_ref.startswith("state_"):
        return []
    if not hostile_entry_authorized(planner, state_ref, target_state_ref):
        return []

    if at is None:
        runtime = planner.read(_RUNTIME_PATH)
        at = runtime.get("world_time") if isinstance(runtime, Mapping) else None
    if not isinstance(at, str) or not at:
        return []

    created: list[str] = []
    cycle_ref = str(cycle.get("cycle_ref") or "")
    coordination_ref = cycle.get("coordination_authority_ref")
    for assignment in assignments:
        commander_ref = assignment.get("commander_ref")
        command_ref = assignment.get("command_ref")
        if commander_ref == _PLAYER_REF or command_ref == _PLAYER_ROOT_GROUP:
            continue
        destination_ref = assignment.get("objective_ref")
        if not isinstance(destination_ref, str) or not destination_ref:
            continue
        operation_refs = [
            str(ref) for ref in assignment.get("operation_refs", [])
            if isinstance(ref, str) and ref in participant_refs and ref != player_operation_ref
        ]
        assignment_formations = {
            str(ref) for ref in assignment.get("formation_refs", [])
            if isinstance(ref, str) and ref
        }
        for operation_ref in operation_refs:
            resolved = exact_operation_record(planner, operation_ref)
            if resolved is None:
                raise ValueError(f"campaign command lost participant operation: {operation_ref}")
            path, raw = resolved
            operation = copy.deepcopy(dict(raw))
            if operation.get("autonomous") is not True:
                continue
            if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
                continue
            if str(operation.get("campaign_commander_ref") or "") != supreme:
                continue
            owner = str(
                operation.get("institutional_owner_ref")
                or operation.get("administrative_authority")
                or ""
            )
            if owner != state_ref:
                continue
            existing_destination = _actionable_destination(_latest_order(operation))
            if existing_destination:
                # Exact executable orders outrank the current planning projection.
                continue

            operation_formations = {
                str(ref) for ref in operation.get("formation_refs", [])
                if isinstance(ref, str) and ref
            }
            applies = sorted(assignment_formations & operation_formations)
            if not applies:
                continue
            if not assignment_formations.issubset(operation_formations):
                raise ValueError(
                    f"campaign staff assignment crosses operation custody: {operation_ref}"
                )

            order_ref = "operational_order_" + _digest(
                "campaign_subordinate",
                cycle_ref,
                operation_ref,
                command_ref or "",
                destination_ref,
                at,
                ",".join(applies),
            )
            orders = operation.get("operational_orders")
            if not isinstance(orders, list):
                orders = []
            prior = next(
                (row for row in orders if isinstance(row, Mapping) and row.get("order_ref") == order_ref),
                None,
            )
            if isinstance(prior, Mapping):
                operation["last_operational_order_ref"] = order_ref
                planner.put(path, operation)
                created.append(order_ref)
                continue

            packet = {
                "schema": "sword-campaign-subordinate-mission-packet-1.0",
                "mission_phase": "campaign_advance",
                "phase_status": "ready_for_commander_execution",
                "destination_ref": destination_ref,
                "strategic_target_ref": destination_ref,
                "target_state_ref": target_state_ref,
                "hostile_entry_authorized": True,
                "entry_status": "authorized",
                "campaign_arc_ref": player_operation.get("campaign_arc_ref"),
                "source_campaign_cycle_ref": cycle_ref,
                "source_staff_command_ref": command_ref,
                "success_condition": "every surviving formation named by this order physically reaches the exact destination",
                "next_phase_trigger": "arrival completes this march order only; battle, siege, occupation, pursuit, or further maneuver require their own lawful consequences",
                "authority_rule": "exact NPC supreme-command adoption of a bounded staff assignment; the staff projection alone is never executable",
            }
            order = {
                "order_ref": order_ref,
                "order_kind": "campaign_subordinate_march_order",
                "issued_at": at,
                "issuer_ref": owner,
                "superior_commander_ref": supreme,
                "coordination_authority_ref": coordination_ref,
                "status": "staff_briefed_awaiting_commander_execution",
                "actionability_status": "actionable",
                "objective": f"Advance the assigned campaign command toward {destination_ref} under supreme campaign coordination.",
                "follow_on_requirement": "Complete the ordered march and report material interruption or arrival; this order does not itself start a battle, seize territory, or transfer troop ownership.",
                "applies_to_formation_refs": applies,
                "mission_packet": packet,
                "source_staff_assignment": {
                    "command_ref": command_ref,
                    "commander_ref": commander_ref,
                    "role": assignment.get("role"),
                    "objective_ref": destination_ref,
                },
            }
            orders.append(order)
            operation["operational_orders"] = orders[-32:]
            operation["last_operational_order_ref"] = order_ref
            operation["order_status"] = "staff_briefed_awaiting_commander_execution"
            operation["campaign_phase"] = "campaign_advance"
            planner.put(path, operation)
            created.append(order_ref)
    return created


__all__ = ["sync_campaign_subordinate_orders"]
