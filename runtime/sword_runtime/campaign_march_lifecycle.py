"""Causal routing for autonomous campaign-participant marches.

Campaign march planning remains advisory and never moves a formation by itself.
This module may materialize one bounded autonomous NPC march assignment only when
an exact active state campaign, a held campaign command council, a named NPC
supreme commander, lawful hostile-entry authority, and the participant operation's
saved autonomous/subordinate status all agree. The staff scheme supplies the
bounded destination candidate; the persisted assignment is the NPC command
consequence. Tang Wei's command is always excluded.

Physical movement has one authority: ``_autonomy_move_formation_step``. Campaign
march hosts only make that existing resolver causally reachable one route leg at a
time. They never teleport a formation, duplicate fatigue/supply mechanics, or
create manpower, battle, territory, or ownership consequences.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_briefing import build_campaign_dossier
from sword_runtime.operation_routing import exact_operation_record
from sword_runtime.sim.calendar import CampaignTime


CAMPAIGN_MARCH_HOST_KIND = "campaign_march"
_ACTIVE_OPERATION_STATUSES = {"mobilizing", "active", "advancing"}
_TERMINAL_OPERATION_STATUSES = {
    "completed", "cancelled", "canceled", "failed", "closed", "resolved",
    "terminated", "withdrawn", "abandoned",
}
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


def _authority_ready(
    planner: Any,
    player_operation: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    """Return the exact campaign order/cycle that permits NPC route execution.

    The player's order is used only as evidence that the shared state campaign has
    crossed its entry gate and that the current supreme-command cycle is active.
    Its applies-to list is never reused as authority over NPC formations.
    """
    order = _latest_order(player_operation)
    if not isinstance(order, Mapping):
        return None
    packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else {}
    if (
        str(order.get("actionability_status", "")) != "actionable"
        or packet.get("hostile_entry_authorized") is not True
        or str(packet.get("entry_status", "")) != "authorized"
    ):
        return None
    cycle = _campaign_cycle(planner, player_operation)
    if not isinstance(cycle, Mapping):
        return None
    council = cycle.get("war_council") if isinstance(cycle.get("war_council"), Mapping) else {}
    if str(council.get("status", "")) != "held":
        return None
    supreme = cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref")
    if not isinstance(supreme, str) or not supreme or supreme == _PLAYER_REF:
        return None
    participant_refs = {
        str(ref) for ref in cycle.get("participant_operation_refs", [])
        if isinstance(ref, str) and ref
    }
    if not participant_refs:
        return None
    return order, cycle


def _scheme_assignments(planner: Any, player_operation_ref: str) -> list[dict[str, Any]]:
    """Read bounded staff destination candidates without treating them as truth."""
    dossier = build_campaign_dossier(planner, player_operation_ref)
    planning = dossier.get("march_planning") if isinstance(dossier.get("march_planning"), Mapping) else {}
    scheme = planning.get("campaign_scheme") if isinstance(planning.get("campaign_scheme"), Mapping) else {}
    rows = scheme.get("command_assignments") if isinstance(scheme.get("command_assignments"), list) else []
    return [copy.deepcopy(dict(row)) for row in rows if isinstance(row, Mapping)]


def _host_ids(operation_ref: str, formation_ref: str, destination_ref: str) -> tuple[str, str]:
    token = _digest(operation_ref, formation_ref, destination_ref)
    return f"host_campaign_march_{token}", f"event_campaign_march_{token}"


def _event_for_host(events: list[Any], host_id: str) -> dict[str, Any] | None:
    for row in events:
        if isinstance(row, dict) and row.get("target_host") == host_id:
            return row
    return None


def _remove_host(runtime: dict[str, Any], host_id: str) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    hosts.pop(host_id, None)
    runtime["events"] = [
        row for row in events
        if not (isinstance(row, Mapping) and row.get("target_host") == host_id)
    ]


def _active_host_for_formation(
    runtime: Mapping[str, Any], formation_ref: str
) -> tuple[str, Mapping[str, Any]] | None:
    hosts = runtime.get("hosts") if isinstance(runtime.get("hosts"), Mapping) else {}
    for host_id, host in hosts.items():
        if (
            isinstance(host_id, str)
            and isinstance(host, Mapping)
            and str(host.get("kind", "")) == CAMPAIGN_MARCH_HOST_KIND
            and str(host.get("formation_ref", "")) == formation_ref
            and host.get("next_due") is not None
        ):
            return host_id, host
    return None


def _materialize_assignment(
    planner: Any,
    operation_path: str,
    operation: dict[str, Any],
    *,
    assignment: Mapping[str, Any],
    player_operation_ref: str,
    cycle: Mapping[str, Any],
    at: str,
) -> dict[str, Any]:
    """Persist one autonomous NPC command consequence after all authority gates.

    The generated staff scheme is not itself an order. This write records the
    named NPC supreme commander's autonomous adoption of one bounded assignment
    for an already-subordinate autonomous operation. A pre-existing exact NPC
    operational order always wins and may supply its own typed destination.
    """
    latest = _latest_order(operation)
    destination_ref = ""
    source_kind = "autonomous_supreme_command_assignment"
    source_order_ref = None
    if isinstance(latest, Mapping) and str(latest.get("actionability_status", "")) == "actionable":
        packet = latest.get("mission_packet") if isinstance(latest.get("mission_packet"), Mapping) else {}
        explicit = packet.get("destination_ref")
        if isinstance(explicit, str) and explicit:
            destination_ref = explicit
            source_kind = "exact_operation_order"
            source_order_ref = latest.get("order_ref")
    if not destination_ref:
        destination_ref = str(assignment.get("objective_ref") or "")
    if not destination_ref:
        raise ValueError("campaign NPC assignment lacks exact destination_ref")

    formation_refs = sorted(
        str(ref) for ref in assignment.get("formation_refs", []) if isinstance(ref, str) and ref
    )
    if not formation_refs:
        raise ValueError("campaign NPC assignment lacks exact formation refs")

    current = operation.get("campaign_march_assignment")
    if isinstance(current, Mapping):
        same = (
            str(current.get("destination_ref", "")) == destination_ref
            and str(current.get("command_ref", "")) == str(assignment.get("command_ref") or "")
            and str(current.get("source_player_operation_ref", "")) == player_operation_ref
            and sorted(str(ref) for ref in current.get("formation_refs", []) if isinstance(ref, str)) == formation_refs
        )
        if same and str(current.get("status", "")) not in {"superseded", "cancelled"}:
            return copy.deepcopy(dict(current))

    row = {
        "schema": "sword-campaign-march-assignment.v2",
        "assignment_ref": f"campaign_march_assignment.{_digest(operation.get('operation_ref'), assignment.get('command_ref'), destination_ref)}",
        "status": "ordered",
        "operation_ref": str(operation.get("operation_ref") or operation.get("owner_id") or ""),
        "command_ref": assignment.get("command_ref"),
        "commander_ref": assignment.get("commander_ref"),
        "formation_refs": formation_refs,
        "destination_ref": destination_ref,
        "issued_at": at,
        "issuer_ref": cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref"),
        "coordination_authority_ref": cycle.get("coordination_authority_ref"),
        "source_player_operation_ref": player_operation_ref,
        "source_campaign_cycle_ref": cycle.get("cycle_ref"),
        "source_kind": source_kind,
        "source_operation_order_ref": source_order_ref,
        "authority_basis": (
            "The operation is an exact autonomous state campaign participant under the saved NPC supreme commander. "
            "The held campaign cycle and lawful entry authority permit routine autonomous execution; the staff scheme contributes only the bounded destination candidate when no exact NPC order already supplies one."
        ),
    }
    operation["campaign_march_assignment"] = row
    planner.put(operation_path, operation)
    return copy.deepcopy(row)


def _formation_route_eligible(planner: Any, formation_ref: str) -> tuple[str, Mapping[str, Any]] | None:
    try:
        path, formation = planner._load_formation(formation_ref)
    except (FileNotFoundError, KeyError, ValueError):
        return None
    if str(formation.get("command_authority", "")) == _PLAYER_REF:
        return None
    if str(formation.get("administrative_owner", "")) != "state_qin":
        return None
    if int(formation.get("personnel", 0) or 0) <= 0:
        return None
    if not bool(formation.get("mobilized", False)):
        return None
    return path, formation


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
    eligible = _formation_route_eligible(planner, formation_ref)
    if eligible is None:
        return False
    _formation_path, formation = eligible
    if str(formation.get("location_ref") or "") == destination_ref:
        return False

    existing = _active_host_for_formation(runtime, formation_ref)
    if existing is not None:
        host_id, host = existing
        if (
            str(host.get("operation_ref", "")) == operation_ref
            and str(host.get("destination_ref", "")) == destination_ref
            and str(host.get("assignment_ref", "")) == str(assignment.get("assignment_ref", ""))
        ):
            return False
        _remove_host(runtime, host_id)

    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    now = CampaignTime.parse(at)
    host_id, event_id = _host_ids(operation_ref, formation_ref, destination_ref)
    hosts[host_id] = {
        "host_id": host_id,
        "kind": CAMPAIGN_MARCH_HOST_KIND,
        "owner_ref": operation_ref,
        "operation_ref": operation_ref,
        "formation_ref": formation_ref,
        "destination_ref": destination_ref,
        "assignment_ref": assignment.get("assignment_ref"),
        "recurrence_seconds": 1,
        "next_due": at,
        "resolved_through": str(now.add_seconds(-1)),
        "safe_through": str(now.add_seconds(-1)),
        "retire_after_settlement": False,
    }
    events.append({
        "event_id": event_id,
        "kind": CAMPAIGN_MARCH_HOST_KIND,
        "priority": _MARCH_PRIORITY,
        "target_host": host_id,
        "due_at": at,
    })
    return True


def _prune_stale_routes(planner: Any, runtime: dict[str, Any]) -> None:
    hosts = runtime.get("hosts")
    if not isinstance(hosts, dict):
        raise ValueError("runtime causal hosts are invalid")
    stale: list[str] = []
    for host_id, host in hosts.items():
        if not isinstance(host_id, str) or not isinstance(host, Mapping) or host.get("kind") != CAMPAIGN_MARCH_HOST_KIND:
            continue
        operation_ref = str(host.get("operation_ref") or host.get("owner_ref") or "")
        formation_ref = str(host.get("formation_ref") or "")
        destination_ref = str(host.get("destination_ref") or "")
        resolved = exact_operation_record(planner, operation_ref) if operation_ref else None
        if resolved is None:
            stale.append(host_id)
            continue
        _path, operation = resolved
        if str(operation.get("status", "")) in _TERMINAL_OPERATION_STATUSES:
            stale.append(host_id)
            continue
        assignment = operation.get("campaign_march_assignment") if isinstance(operation.get("campaign_march_assignment"), Mapping) else {}
        if (
            str(assignment.get("destination_ref") or "") != destination_ref
            or formation_ref not in {str(ref) for ref in assignment.get("formation_refs", []) if isinstance(ref, str)}
            or _formation_route_eligible(planner, formation_ref) is None
        ):
            stale.append(host_id)
    for host_id in stale:
        _remove_host(runtime, host_id)


def _refresh_assignment_completion(
    planner: Any,
    operation_path: str,
    operation: dict[str, Any],
    *,
    destination_ref: str,
    at: str,
) -> bool:
    assignment = operation.get("campaign_march_assignment") if isinstance(operation.get("campaign_march_assignment"), Mapping) else {}
    refs = [str(ref) for ref in assignment.get("formation_refs", []) if isinstance(ref, str)]
    operation_refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}
    relevant = [ref for ref in refs if ref in operation_refs]
    if not relevant:
        return False
    for ref in relevant:
        try:
            _path, formation = planner._load_formation(ref)
        except (FileNotFoundError, KeyError, ValueError):
            return False
        if int(formation.get("personnel", 0) or 0) > 0 and str(formation.get("location_ref") or "") != destination_ref:
            return False
    updated = copy.deepcopy(dict(assignment))
    updated["status"] = "arrived"
    updated["arrived_at"] = at
    operation["campaign_march_assignment"] = updated
    operation["location_ref"] = destination_ref
    operation["status"] = "active"
    operation["last_campaign_march_arrival_at"] = at
    planner.put(operation_path, operation)
    return True


def sync_campaign_march_routes(planner: Any) -> list[str]:
    """Reconcile lawful autonomous NPC march assignments into causal leg hosts."""
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
    _player_order, cycle = authority
    participant_refs = {
        str(ref) for ref in cycle.get("participant_operation_refs", [])
        if isinstance(ref, str) and ref
    }
    at = str(planner.read(_RUNTIME_PATH)["world_time"])
    assignments = _scheme_assignments(planner, player_operation_ref)
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    _prune_stale_routes(planner, runtime)
    registered: list[str] = []

    for assignment in assignments:
        command_ref = str(assignment.get("command_ref") or "")
        if command_ref == _PLAYER_ROOT_GROUP or str(assignment.get("commander_ref") or "") == _PLAYER_REF:
            continue
        for operation_ref in assignment.get("operation_refs", []) if isinstance(assignment.get("operation_refs"), list) else []:
            if not isinstance(operation_ref, str) or operation_ref == player_operation_ref or operation_ref not in participant_refs:
                continue
            resolved = exact_operation_record(planner, operation_ref)
            if resolved is None:
                raise ValueError(f"campaign scheme lost participant operation: {operation_ref}")
            operation_path, raw = resolved
            operation = copy.deepcopy(dict(raw))
            if operation.get("autonomous") is not True:
                continue
            if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATUSES:
                continue
            supreme = str(cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref") or "")
            if str(operation.get("campaign_commander_ref") or "") != supreme:
                continue
            assignment_record = _materialize_assignment(
                planner,
                operation_path,
                operation,
                assignment=assignment,
                player_operation_ref=player_operation_ref,
                cycle=cycle,
                at=at,
            )
            destination_ref = str(assignment_record.get("destination_ref") or "")
            if not destination_ref:
                continue
            op_formations = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}
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
            latest = copy.deepcopy(dict(planner.read(operation_path)))
            _refresh_assignment_completion(
                planner, operation_path, latest, destination_ref=destination_ref, at=at
            )

    planner.put(_RUNTIME_PATH, runtime)
    return registered


def _mutable_runtime_host(planner: Any, host: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    hosts = runtime.get("hosts")
    if not isinstance(hosts, dict):
        raise ValueError("runtime causal hosts are invalid")
    active_id = getattr(planner, "_active_host_id", None)
    if isinstance(active_id, str) and isinstance(hosts.get(active_id), dict):
        return runtime, hosts[active_id]
    host_id = host.get("host_id")
    if isinstance(host_id, str) and isinstance(hosts.get(host_id), dict):
        return runtime, hosts[host_id]
    for row in hosts.values():
        if not isinstance(row, dict) or row.get("kind") != CAMPAIGN_MARCH_HOST_KIND:
            continue
        if (
            str(row.get("operation_ref") or "") == str(host.get("operation_ref") or "")
            and str(row.get("formation_ref") or "") == str(host.get("formation_ref") or "")
            and str(row.get("destination_ref") or "") == str(host.get("destination_ref") or "")
        ):
            return runtime, row
    return runtime, None


def _retire_current_host(planner: Any, host: Mapping[str, Any], at: str, reason: str) -> None:
    runtime, current = _mutable_runtime_host(planner, host)
    if isinstance(current, dict):
        current["recurrence_seconds"] = 0
        current["retire_after_settlement"] = True
        current["terminal_at"] = at
        current["terminal_reason"] = reason[:240]
        planner.put(_RUNTIME_PATH, runtime)


def _reschedule_current_host(planner: Any, host: Mapping[str, Any], at: str, hours: int, location_ref: str) -> None:
    runtime, current = _mutable_runtime_host(planner, host)
    if not isinstance(current, dict):
        raise ValueError("campaign march settlement lost its active scheduler host")
    current["recurrence_seconds"] = max(3600, int(hours) * 3600)
    current["retire_after_settlement"] = False
    current["last_leg_settled_at"] = at
    current["last_location_ref"] = location_ref
    planner.put(_RUNTIME_PATH, runtime)


def settle_campaign_march_host(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    """Advance one autonomous formation by exactly one canonical route leg."""
    operation_ref = str(host.get("operation_ref") or host.get("owner_ref") or "")
    formation_ref = str(host.get("formation_ref") or "")
    destination_ref = str(host.get("destination_ref") or "")
    if not operation_ref or not formation_ref or not destination_ref:
        raise ValueError("campaign march host routing is invalid")

    resolved = exact_operation_record(planner, operation_ref)
    if resolved is None:
        _retire_current_host(planner, host, at, "operation_missing")
        return None
    operation_path, raw_operation = resolved
    operation = copy.deepcopy(dict(raw_operation))
    if str(operation.get("status", "")) in _TERMINAL_OPERATION_STATUSES:
        _retire_current_host(planner, host, at, "operation_terminal")
        return None

    assignment = operation.get("campaign_march_assignment") if isinstance(operation.get("campaign_march_assignment"), Mapping) else {}
    if (
        str(assignment.get("destination_ref") or "") != destination_ref
        or formation_ref not in {str(ref) for ref in assignment.get("formation_refs", []) if isinstance(ref, str)}
    ):
        _retire_current_host(planner, host, at, "assignment_superseded")
        return None

    eligible = _formation_route_eligible(planner, formation_ref)
    if eligible is None:
        _retire_current_host(planner, host, at, "formation_no_longer_autonomous_march_eligible")
        return None
    _formation_path, formation = eligible
    current_location = str(formation.get("location_ref") or "")
    if current_location == destination_ref:
        _retire_current_host(planner, host, at, "already_arrived")
        _refresh_assignment_completion(
            planner, operation_path, operation, destination_ref=destination_ref, at=at
        )
        return {
            "operation_ref": operation_ref,
            "formation_ref": formation_ref,
            "destination_ref": destination_ref,
            "location_ref": destination_ref,
            "status": "arrived",
            "operation_concentrated": True,
        }

    try:
        movement = planner._autonomy_move_formation_step(formation_ref, destination_ref, at)
    except ValueError as exc:
        blocked = copy.deepcopy(dict(assignment))
        blocked["status"] = "blocked"
        blocked["blocked_at"] = at
        blocked["blocked_formation_ref"] = formation_ref
        blocked["blocked_reason"] = str(exc)[:240]
        operation["campaign_march_assignment"] = blocked
        planner.put(operation_path, operation)
        _retire_current_host(planner, host, at, "canonical_route_blocked")
        return {
            "operation_ref": operation_ref,
            "formation_ref": formation_ref,
            "destination_ref": destination_ref,
            "location_ref": current_location,
            "status": "blocked",
        }

    _after_path, after = planner._load_formation(formation_ref)
    reached = str(after.get("location_ref") or "")
    hours = max(1, int(movement.get("hours", 1) or 1)) if isinstance(movement, Mapping) else 1
    if reached == current_location:
        blocked = copy.deepcopy(dict(assignment))
        blocked["status"] = "blocked"
        blocked["blocked_at"] = at
        blocked["blocked_formation_ref"] = formation_ref
        blocked["blocked_reason"] = str(movement.get("status", "canonical_movement_did_not_advance")) if isinstance(movement, Mapping) else "canonical_movement_did_not_advance"
        operation["campaign_march_assignment"] = blocked
        planner.put(operation_path, operation)
        _retire_current_host(planner, host, at, "canonical_movement_did_not_advance")
        return {
            "operation_ref": operation_ref,
            "formation_ref": formation_ref,
            "destination_ref": destination_ref,
            "location_ref": reached,
            "status": "blocked",
        }

    latest = copy.deepcopy(dict(planner.read(operation_path)))
    latest_assignment = latest.get("campaign_march_assignment") if isinstance(latest.get("campaign_march_assignment"), Mapping) else assignment
    marching = copy.deepcopy(dict(latest_assignment))
    marching["status"] = "marching"
    marching.setdefault("started_at", at)
    marching["last_leg_at"] = at
    marching["last_location_ref"] = reached
    latest["campaign_march_assignment"] = marching
    latest["status"] = "advancing"
    planner.put(operation_path, latest)

    concentrated = _refresh_assignment_completion(
        planner,
        operation_path,
        copy.deepcopy(dict(planner.read(operation_path))),
        destination_ref=destination_ref,
        at=at,
    )
    if reached == destination_ref:
        _retire_current_host(planner, host, at, "arrived")
    else:
        _reschedule_current_host(planner, host, at, hours, reached)

    return {
        "operation_ref": operation_ref,
        "formation_ref": formation_ref,
        "destination_ref": destination_ref,
        "location_ref": reached,
        "status": "arrived" if reached == destination_ref else "marching",
        "leg_hours": hours,
        "operation_concentrated": concentrated,
    }


class CampaignMarchLifecycleMixin:
    """Hosted scheduler dispatch extension for autonomous campaign march routes."""

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
