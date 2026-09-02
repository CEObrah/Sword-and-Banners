"""Causal physical movement for autonomous campaign participant operations.

Campaign march planning is deliberately advisory. This module bridges an already
lawful supreme-command campaign scheme into exact NPC march assignments, then
settles those assignments through the production causal scheduler. It never moves
Tang Wei's formations, invents hostile-entry authority, transfers ownership, or
chooses player tactics.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_briefing import build_campaign_dossier
from sword_runtime.fatigue import (
    RULES_PATH as FATIGUE_RULES_PATH,
    settle_formation_idle_fatigue,
    settle_person_idle_fatigue,
    stamp_formation_activity_fatigue,
    stamp_person_activity_fatigue,
)
from sword_runtime.operation_routing import exact_operation_record
from sword_runtime.operational_logistics import formation_movement_profile
from sword_runtime.sim.calendar import CampaignTime


CAMPAIGN_MARCH_HOST_KIND = "campaign_march"
_ACTIVE_OPERATION_STATUSES = {"mobilizing", "active", "advancing"}
_TERMINAL_OPERATION_STATUSES = {"completed", "cancelled", "canceled", "failed", "closed", "terminated"}
_PLAYER_REF = "char_tang_wei"
_PLAYER_ROOT_GROUP = "cmdgrp.tang_wei.field_army"
_RUNTIME_PATH = "state/runtime.json"
_MARCH_PRIORITY = 44


def _digest(*parts: object) -> str:
    material = "|".join(str(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


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


def _player_operation_ref(planner: Any) -> str | None:
    try:
        root = planner.read(f"state/cmd/command-groups/{_PLAYER_ROOT_GROUP}.json")
    except (FileNotFoundError, KeyError, ValueError):
        return None
    ref = root.get("active_context_ref") if isinstance(root, Mapping) else None
    return str(ref) if isinstance(ref, str) and ref else None


def _campaign_cycle(planner: Any, operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    cycle_ref = operation.get("campaign_command_cycle_ref")
    if not isinstance(cycle_ref, str) or not cycle_ref:
        return None
    try:
        row = planner.read(planner.owner_path(cycle_ref))
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _authority_ready(planner: Any, operation: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    order = _latest_order(operation)
    if not isinstance(order, Mapping):
        return None
    packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else {}
    if (
        str(order.get("actionability_status", "")) != "actionable"
        or packet.get("hostile_entry_authorized") is not True
        or str(packet.get("entry_status", "")) != "authorized"
    ):
        return None
    cycle = _campaign_cycle(planner, operation)
    if not isinstance(cycle, Mapping):
        return None
    council = cycle.get("war_council") if isinstance(cycle.get("war_council"), Mapping) else {}
    if str(council.get("status", "")) != "held":
        return None
    supreme = cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref")
    if not isinstance(supreme, str) or not supreme or supreme == _PLAYER_REF:
        return None
    return order, cycle


def _scheme_assignments(planner: Any, player_operation_ref: str) -> list[dict[str, Any]]:
    dossier = build_campaign_dossier(planner, player_operation_ref)
    planning = dossier.get("march_planning") if isinstance(dossier.get("march_planning"), Mapping) else {}
    scheme = planning.get("campaign_scheme") if isinstance(planning.get("campaign_scheme"), Mapping) else {}
    rows = scheme.get("command_assignments") if isinstance(scheme.get("command_assignments"), list) else []
    return [copy.deepcopy(dict(row)) for row in rows if isinstance(row, Mapping)]


def _host_ids(operation_ref: str, formation_ref: str, destination_ref: str) -> tuple[str, str]:
    token = _digest(operation_ref, formation_ref, destination_ref)
    return f"host_campaign_march_{token}", f"event_campaign_march_{token}"


def _registered_host_for_formation(runtime: Mapping[str, Any], formation_ref: str) -> Mapping[str, Any] | None:
    hosts = runtime.get("hosts") if isinstance(runtime.get("hosts"), Mapping) else {}
    for host in hosts.values():
        if (
            isinstance(host, Mapping)
            and str(host.get("kind", "")) == CAMPAIGN_MARCH_HOST_KIND
            and str(host.get("formation_ref", "")) == formation_ref
            and host.get("next_due") is not None
        ):
            return host
    return None


def _materialize_assignment(
    planner: Any,
    operation_path: str,
    operation: dict[str, Any],
    *,
    assignment: Mapping[str, Any],
    player_operation_ref: str,
    order: Mapping[str, Any],
    cycle: Mapping[str, Any],
    at: str,
) -> dict[str, Any]:
    destination_ref = str(assignment.get("objective_ref") or "")
    if not destination_ref:
        raise ValueError("campaign NPC assignment lacks exact objective_ref")
    current = operation.get("campaign_march_assignment")
    if isinstance(current, Mapping):
        same = (
            str(current.get("destination_ref", "")) == destination_ref
            and str(current.get("command_ref", "")) == str(assignment.get("command_ref") or "")
            and str(current.get("source_player_operation_ref", "")) == player_operation_ref
        )
        if same and str(current.get("status", "")) not in {"superseded", "cancelled"}:
            return copy.deepcopy(dict(current))

    row = {
        "schema": "sword-campaign-march-assignment.v1",
        "status": "ordered",
        "operation_ref": str(operation.get("operation_ref") or operation.get("owner_id") or ""),
        "command_ref": assignment.get("command_ref"),
        "commander_ref": assignment.get("commander_ref"),
        "formation_refs": sorted(
            str(ref) for ref in assignment.get("formation_refs", []) if isinstance(ref, str)
        ),
        "destination_ref": destination_ref,
        "issued_at": at,
        "issuer_ref": cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref"),
        "coordination_authority_ref": cycle.get("coordination_authority_ref"),
        "source_player_operation_ref": player_operation_ref,
        "source_player_order_ref": order.get("order_ref"),
        "source_campaign_cycle_ref": cycle.get("cycle_ref"),
        "authority_basis": (
            "Exact state campaign entry authority plus a held supreme-command campaign cycle. "
            "The staff scheme selects NPC campaign axes only; Tang Wei's command is excluded from autonomous execution."
        ),
    }
    operation["campaign_march_assignment"] = row
    operation["status"] = "advancing"
    planner.put(operation_path, operation)
    return copy.deepcopy(row)


def _register_march_host(
    planner: Any,
    runtime: dict[str, Any],
    *,
    operation_ref: str,
    formation_ref: str,
    destination_ref: str,
    assignment: Mapping[str, Any],
    at: str,
) -> bool:
    if _registered_host_for_formation(runtime, formation_ref) is not None:
        return False
    formation_path, formation0 = planner._load_formation(formation_ref)
    formation = copy.deepcopy(formation0)
    if str(formation.get("command_authority", "")) == _PLAYER_REF:
        return False
    if str(formation.get("administrative_owner", "")) != "state_qin":
        return False
    if int(formation.get("personnel", 0) or 0) <= 0:
        return False
    if not bool(formation.get("mobilized", False)):
        raise ValueError(f"campaign NPC march requires mobilized formation: {formation_ref}")
    origin_ref = str(formation.get("location_ref") or "")
    if not origin_ref:
        raise ValueError(f"campaign NPC march formation lacks location: {formation_ref}")
    if origin_ref == destination_ref:
        return False
    if hasattr(planner, "_validate_formation_transit"):
        planner._validate_formation_transit(formation, destination_ref, at)
    route = planner._find_route(origin_ref, destination_ref, mode="formation")
    movement = formation_movement_profile(planner.read, formation, route)
    hours = max(1, int(movement.get("tail_arrival_hours", route.get("duration_hours", route.get("hours", 24)))))
    departure = CampaignTime.parse(at)
    due = departure.add_seconds(hours * 3600)

    commander_ref = formation.get("commander_ref")
    commander_path = None
    commander = None
    fatigue_rules = planner.read(FATIGUE_RULES_PATH)
    settle_formation_idle_fatigue(formation, current=departure, rules=fatigue_rules)
    if isinstance(commander_ref, str) and commander_ref:
        commander_path, commander = planner._validate_person_location_for_formation(commander_ref, formation)
        commander = copy.deepcopy(commander)
        settle_person_idle_fatigue(commander, current=departure, rules=fatigue_rules, state="ordinary")
        planner.put(commander_path, commander)

    ready_at = str(departure.add_seconds(int(movement.get("battle_ready_hours", hours)) * 3600))
    formation["status"] = "marching"
    formation["last_route_refs"] = list(route.get("route_refs", []))
    formation["last_route_path"] = list(route.get("path", []))
    formation["operational_movement"] = {
        **copy.deepcopy(dict(movement)),
        "origin_ref": origin_ref,
        "destination_ref": destination_ref,
        "departed_at": at,
        "tail_arrived_at": str(due),
        "deployment_ready_at": ready_at,
        "movement_owner": CAMPAIGN_MARCH_HOST_KIND,
        "operation_ref": operation_ref,
    }
    planner.put(formation_path, formation)

    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = _host_ids(operation_ref, formation_ref, destination_ref)
    hosts[host_id] = {
        "host_id": host_id,
        "kind": CAMPAIGN_MARCH_HOST_KIND,
        "owner_ref": operation_ref,
        "operation_ref": operation_ref,
        "formation_ref": formation_ref,
        "commander_ref": commander_ref,
        "origin_ref": origin_ref,
        "destination_ref": destination_ref,
        "assignment_ref": _digest(operation_ref, str(assignment.get("command_ref") or ""), destination_ref),
        "departed_at": at,
        "travel_hours": hours,
        "deployment_ready_at": ready_at,
        "recurrence_seconds": 0,
        "next_due": str(due),
        "resolved_through": at,
        "safe_through": str(due.add_seconds(-1)),
        "retire_after_settlement": True,
    }
    events.append({
        "event_id": event_id,
        "kind": CAMPAIGN_MARCH_HOST_KIND,
        "priority": _MARCH_PRIORITY,
        "target_host": host_id,
        "due_at": str(due),
    })
    return True


def sync_campaign_march_routes(planner: Any) -> list[str]:
    """Persist lawful NPC march assignments and register missing arrival hosts."""
    player_operation_ref = _player_operation_ref(planner)
    if not player_operation_ref:
        return []
    player_resolved = exact_operation_record(planner, player_operation_ref)
    if player_resolved is None:
        return []
    _player_path, player_operation = player_resolved
    authority = _authority_ready(planner, player_operation)
    if authority is None:
        return []
    order, cycle = authority
    at = str(planner.read(_RUNTIME_PATH)["world_time"])
    assignments = _scheme_assignments(planner, player_operation_ref)
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    registered: list[str] = []

    for assignment in assignments:
        command_ref = str(assignment.get("command_ref") or "")
        if command_ref == _PLAYER_ROOT_GROUP or str(assignment.get("commander_ref") or "") == _PLAYER_REF:
            continue
        destination_ref = str(assignment.get("objective_ref") or "")
        if not destination_ref:
            continue
        for operation_ref in assignment.get("operation_refs", []) if isinstance(assignment.get("operation_refs"), list) else []:
            if not isinstance(operation_ref, str) or operation_ref == player_operation_ref:
                continue
            resolved = exact_operation_record(planner, operation_ref)
            if resolved is None:
                raise ValueError(f"campaign scheme lost participant operation: {operation_ref}")
            operation_path, raw = resolved
            operation = copy.deepcopy(dict(raw))
            if operation.get("autonomous") is not True:
                continue
            if str(operation.get("status", "")) in _TERMINAL_OPERATION_STATUSES:
                continue
            if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
                continue
            if str(operation.get("campaign_commander_ref") or "") != str(cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref") or ""):
                continue
            assignment_record = _materialize_assignment(
                planner,
                operation_path,
                operation,
                assignment=assignment,
                player_operation_ref=player_operation_ref,
                order=order,
                cycle=cycle,
                at=at,
            )
            op_formations = {
                str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)
            }
            for formation_ref in assignment_record.get("formation_refs", []):
                if formation_ref not in op_formations:
                    continue
                if _register_march_host(
                    planner,
                    runtime,
                    operation_ref=operation_ref,
                    formation_ref=formation_ref,
                    destination_ref=destination_ref,
                    assignment=assignment_record,
                    at=at,
                ):
                    registered.append(formation_ref)
    if registered:
        planner.put(_RUNTIME_PATH, runtime)
    return registered


def settle_campaign_march_host(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    """Complete one previously scheduled autonomous formation march at arrival time."""
    operation_ref = str(host.get("operation_ref") or host.get("owner_ref") or "")
    formation_ref = str(host.get("formation_ref") or "")
    origin_ref = str(host.get("origin_ref") or "")
    destination_ref = str(host.get("destination_ref") or "")
    if not operation_ref or not formation_ref or not origin_ref or not destination_ref:
        raise ValueError("campaign march host routing is invalid")
    resolved = exact_operation_record(planner, operation_ref)
    if resolved is None:
        raise ValueError("campaign march operation disappeared")
    operation_path, raw_operation = resolved
    operation = copy.deepcopy(dict(raw_operation))
    if str(operation.get("status", "")) in _TERMINAL_OPERATION_STATUSES:
        return None
    assignment = operation.get("campaign_march_assignment") if isinstance(operation.get("campaign_march_assignment"), Mapping) else {}
    if str(assignment.get("destination_ref") or "") != destination_ref:
        raise ValueError("campaign march assignment changed while formation was in transit")

    formation_path, formation0 = planner._load_formation(formation_ref)
    formation = copy.deepcopy(formation0)
    if str(formation.get("command_authority", "")) == _PLAYER_REF:
        raise ValueError("campaign march may not settle a player-commanded formation")
    current_location = str(formation.get("location_ref") or "")
    if current_location == destination_ref:
        return None
    if current_location != origin_ref:
        raise ValueError("campaign march formation moved outside its registered lifecycle")

    travel_hours = max(1, int(host.get("travel_hours", 1) or 1))
    arrival = CampaignTime.parse(at)
    formation["location_ref"] = destination_ref
    planner._index_formation_location(formation_ref, origin_ref, destination_ref)
    stamp_formation_activity_fatigue(
        formation,
        completed_at=arrival,
        fatigue_gain=max(1, travel_hours // 12),
        activity_kind="march",
    )
    formation["last_moved_at"] = at
    ready_text = str(host.get("deployment_ready_at") or at)
    formation["status"] = "ready" if CampaignTime.parse(ready_text) <= arrival else "arrived_forming"
    planner.put(formation_path, formation)

    commander_ref = host.get("commander_ref")
    if isinstance(commander_ref, str) and commander_ref and formation.get("commander_ref") == commander_ref:
        try:
            commander_path, commander0 = planner._command_person(commander_ref)
        except (FileNotFoundError, KeyError, ValueError):
            commander_path, commander0 = planner._exact_person(commander_ref)
        commander = copy.deepcopy(commander0)
        commander_location = planner._person_location(commander)
        if commander_location == origin_ref:
            planner._set_person_location(commander, destination_ref)
            stamp_person_activity_fatigue(
                commander,
                completed_at=arrival,
                fatigue_gain=max(1, travel_hours // 12),
                activity_kind="march",
            )
            planner.put(commander_path, commander)
        elif commander_location != destination_ref:
            raise ValueError("campaign march commander detached during registered transit")

    assigned_refs = [str(ref) for ref in assignment.get("formation_refs", []) if isinstance(ref, str)]
    operation_refs = {str(x) for x in operation.get("formation_refs", []) if isinstance(x, str)}
    all_arrived = True
    for ref in assigned_refs:
        if ref not in operation_refs:
            continue
        try:
            _path, row = planner._load_formation(ref)
        except (FileNotFoundError, KeyError, ValueError):
            all_arrived = False
            break
        if int(row.get("personnel", 0) or 0) > 0 and str(row.get("location_ref") or "") != destination_ref:
            all_arrived = False
            break
    if all_arrived:
        assignment = copy.deepcopy(dict(assignment))
        assignment["status"] = "arrived"
        assignment["arrived_at"] = at
        operation["campaign_march_assignment"] = assignment
        operation["location_ref"] = destination_ref
        operation["status"] = "active"
        operation["last_campaign_march_arrival_at"] = at
        planner.put(operation_path, operation)

    return {
        "operation_ref": operation_ref,
        "formation_ref": formation_ref,
        "origin_ref": origin_ref,
        "destination_ref": destination_ref,
        "arrived_at": at,
        "operation_concentrated": all_arrived,
    }


class CampaignMarchLifecycleMixin:
    """Hosted scheduler hook for autonomous campaign formation marches."""

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if str(host.get("kind", "")) == CAMPAIGN_MARCH_HOST_KIND:
            settle_campaign_march_host(self, host, due_text)
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)


__all__ = [
    "CAMPAIGN_MARCH_HOST_KIND",
    "CampaignMarchLifecycleMixin",
    "settle_campaign_march_host",
    "sync_campaign_march_routes",
]
