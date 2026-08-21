"""Post-assumption Qin field-command support and supply routing.

Player interaction attempts remain intent-only. This module claims only attempts
that fall inside Tang Wei's already-active Qin field-command scope, schedules an
institution-owned review, and settles replies from exact operation/formation/
depot owners. Provisioning never mints stock: remote issues move first into a
field-depot incoming-convoy escrow and reach the formation only after route time.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.causal_event_store import (
    get_causal_event,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.history_store import recent_history_events
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_PLAYER_PATH = "state/player.json"
_QIN_DEPOT_PATH = "state/depots/qin.json"
_LOGISTICS_RULES_PATH = "game/data/mechanics/logistics.json"
_HISTORY_WINDOW = 512
_REVIEW_PRIORITY = 43
_CONVOY_PRIORITY = 49
_PLAYER_REF = "char_tang_wei"
_QIN_BUREAU_REF = "inst_qin_military_bureau"


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def _response_ref(request_id: str) -> str:
    return f"event_qin_command_support_{_digest('response', request_id)}"


def _review_ids(request_id: str) -> tuple[str, str]:
    d = _digest("review", request_id)
    return f"host_qin_command_support_{d}", f"event_qin_command_support_due_{d}"


def _convoy_ref(request_id: str, formation_ref: str) -> str:
    return f"qin_support_convoy.{_digest('convoy', request_id + '|' + formation_ref)}"


def _convoy_ids(convoy_ref: str) -> tuple[str, str]:
    d = _digest("convoy-host", convoy_ref)
    return f"host_qin_support_convoy_{d}", f"event_qin_support_convoy_due_{d}"


def _convoy_response_ref(convoy_ref: str) -> str:
    return f"event_qin_support_arrival_{_digest('convoy-response', convoy_ref)}"


def _policy(planner: Any) -> Mapping[str, Any]:
    rules = planner.read(_LOGISTICS_RULES_PATH)
    policy = rules.get("military_field_supply_policy") if isinstance(rules, Mapping) else None
    if not isinstance(policy, Mapping):
        raise ValueError("military field supply policy is missing")
    food_rate = policy.get("food_kg_per_person_day")
    fodder_rate = policy.get("fodder_kg_per_mount_day")
    reserve_days = policy.get("commanded_initial_reserve_days")
    review_hours = policy.get("qin_support_review_delay_hours")
    if (
        isinstance(food_rate, bool) or not isinstance(food_rate, (int, float)) or food_rate <= 0
        or isinstance(fodder_rate, bool) or not isinstance(fodder_rate, (int, float)) or fodder_rate < 0
        or isinstance(reserve_days, bool) or not isinstance(reserve_days, int) or reserve_days <= 0
        or isinstance(review_hours, bool) or not isinstance(review_hours, int) or review_hours <= 0
    ):
        raise ValueError("military field supply policy is invalid")
    return policy


def _active_qin_scopes(planner: Any) -> list[dict[str, Any]]:
    player = planner.read(_PLAYER_PATH)
    career = player.get("career_state", {}) if isinstance(player, Mapping) else {}
    appointments = career.get("appointments", []) if isinstance(career, Mapping) else []
    scopes: list[dict[str, Any]] = []
    for row in appointments if isinstance(appointments, list) else ():
        if (
            not isinstance(row, Mapping)
            or row.get("kind") != "qin_field_command"
            or row.get("state_ref") != "state_qin"
            or row.get("status") != "active"
        ):
            continue
        refs: list[str] = []
        raw_refs = row.get("formation_refs")
        if isinstance(raw_refs, list):
            refs.extend(str(ref) for ref in raw_refs if isinstance(ref, str) and ref)
        single = row.get("formation_ref")
        if isinstance(single, str) and single:
            refs.append(single)
        refs = list(dict.fromkeys(refs))
        operation_ref = row.get("operation_ref")
        scopes.append({
            "office": str(row.get("office", "")),
            "operation_ref": str(operation_ref) if isinstance(operation_ref, str) else "",
            "formation_refs": refs,
        })
    return scopes


def _attempt_scope(attempt: Mapping[str, Any], scopes: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]] | None:
    raw_refs = attempt.get("formation_refs")
    requested = [str(ref) for ref in raw_refs if isinstance(ref, str) and ref] if isinstance(raw_refs, list) else []
    process_ref = attempt.get("process_ref")
    target_ref = attempt.get("target_ref")
    for scope in scopes:
        allowed = set(scope["formation_refs"])
        qin_refs = [ref for ref in requested if ref in allowed]
        op_ref = scope.get("operation_ref")
        op_match = isinstance(op_ref, str) and op_ref and op_ref in {process_ref, target_ref}
        if qin_refs or op_match:
            return scope, qin_refs
    return None


def _support_kind(attempt: Mapping[str, Any], scope: Mapping[str, Any], qin_refs: list[str]) -> str | None:
    action = str(attempt.get("action", ""))
    target_ref = str(attempt.get("target_ref", ""))
    process_ref = str(attempt.get("process_ref", ""))
    operation_ref = str(scope.get("operation_ref", ""))
    text = " ".join(
        str(attempt.get(key, "") or "").lower()
        for key in ("player_statement", "posture")
    )
    supply_terms = ("provision", "supply", "food", "grain", "ration", "fodder", "resupply")
    if action == "request" and qin_refs and (
        any(term in text for term in supply_terms) or target_ref.startswith("loc_")
    ):
        return "provisioning"
    if operation_ref and operation_ref in {target_ref, process_ref}:
        if action in {"ask", "request", "petition"}:
            return "operational_briefing"
        if action in {"proceed", "comply"} and qin_refs:
            return "march_support"
    return None


def _write_response(
    planner: Any,
    *,
    event_ref: str,
    request_id: str,
    support_kind: str,
    summary: str,
    at: str,
    source_event_ref: str | None = None,
) -> str:
    existing = get_causal_event(planner, event_ref)
    if isinstance(existing, Mapping):
        return event_ref
    player = planner.read(_PLAYER_PATH)
    location_ref = str(player.get("location", "")) if isinstance(player, Mapping) else ""
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = {
        "event_ref": event_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": _QIN_BUREAU_REF,
        "target_ref": _PLAYER_REF,
        "basis_goal": f"Qin field-command support review for {request_id}"[:500],
        "process_kind": "qin_field_command_support",
        "process_stage": support_kind,
        "source_event_ref": source_event_ref,
        "summary": summary[:4000],
        "delivery": {
            "target_ref": _PLAYER_REF,
            "location_ref": location_ref,
            "route": "Qin field-command military dispatch channel",
        },
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": _QIN_BUREAU_REF,
            "work_ref": event_ref,
            "late_catch_up": False,
            "source_request_id": request_id,
        },
    }
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return event_ref


def _schedule_convoy(
    planner: Any,
    *,
    convoy_ref: str,
    request_id: str,
    formation_ref: str,
    depot_path: str,
    destination_location_ref: str,
    arrival: CampaignTime,
) -> None:
    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    hosts, events = runtime.get("hosts"), runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = _convoy_ids(convoy_ref)
    if host_id in hosts:
        return
    due = str(arrival)
    hosts[host_id] = {
        "host_id": host_id,
        "kind": "qin_command_supply_convoy",
        "owner_ref": _QIN_BUREAU_REF,
        "convoy_ref": convoy_ref,
        "request_id": request_id,
        "formation_ref": formation_ref,
        "destination_depot_path": depot_path,
        "destination_location_ref": destination_location_ref,
        "recurrence_seconds": 0,
        "next_due": due,
        "resolved_through": str(arrival.add_seconds(-1)),
        "safe_through": str(arrival.add_seconds(-1)),
    }
    events.append({
        "event_id": event_id,
        "kind": "qin_command_supply_convoy",
        "priority": _CONVOY_PRIORITY,
        "target_host": host_id,
        "due_at": due,
    })
    planner.put(_RUNTIME_PATH, runtime)


def _provision(planner: Any, host: Mapping[str, Any], at: str) -> str:
    policy = _policy(planner)
    food_rate = float(policy["food_kg_per_person_day"])
    fodder_rate = float(policy["fodder_kg_per_mount_day"])
    reserve_days = int(policy["commanded_initial_reserve_days"])
    request_id = str(host["request_id"])
    raw_refs = host.get("formation_refs")
    refs = [str(ref) for ref in raw_refs if isinstance(ref, str) and ref] if isinstance(raw_refs, list) else []
    if not refs:
        raise ValueError("Qin provisioning review lost its formations")

    source = copy.deepcopy(planner.read(_QIN_DEPOT_PATH))
    source_loc = str(source.get("location_ref", ""))
    source_stocks = source.setdefault("stocks", {})
    rows: list[str] = []
    source_changed = False
    now = CampaignTime.parse(at)

    for formation_ref in refs:
        formation_path = planner.owner_path(formation_ref)
        formation = copy.deepcopy(planner.read(formation_path))
        if (
            str(formation.get("administrative_owner", "")) != "state_qin"
            or str(formation.get("command_authority", "")) != _PLAYER_REF
        ):
            raise PermissionError("Qin support may provision only Qin-owned formations under Tang Wei's active field command")
        personnel = max(0, int(formation.get("personnel", 0)))
        mounts = sum(max(0, int(value)) for value in (formation.get("mounts", {}) or {}).values())
        logistics = formation.setdefault("logistics", {})
        target_food = max(0, int(math.ceil(personnel * food_rate * reserve_days)))
        target_fodder = max(0, int(math.ceil(mounts * fodder_rate * reserve_days)))
        food_need = max(0, target_food - int(logistics.get("food_kg", 0)))
        fodder_need = max(0, target_fodder - int(logistics.get("fodder_kg", 0)))
        if food_need == 0 and fodder_need == 0:
            rows.append(f"{formation.get('name', formation_ref)} already carries the registered {reserve_days}-day field reserve.")
            continue

        formation_loc = str(formation.get("location_ref", ""))
        direct = bool(source_loc and source_loc == formation_loc)
        available_food = max(0, int(source_stocks.get("grain_kg", 0)))
        available_fodder = max(0, int(source_stocks.get("fodder_kg", 0)))
        food = min(food_need, available_food)
        fodder = min(fodder_need, available_fodder)
        food_short = food_need - food
        fodder_short = fodder_need - fodder

        if direct:
            if food:
                source_stocks["grain_kg"] = available_food - food
                logistics["food_kg"] = int(logistics.get("food_kg", 0)) + food
                source_changed = True
            if fodder:
                source_stocks["fodder_kg"] = available_fodder - fodder
                logistics["fodder_kg"] = int(logistics.get("fodder_kg", 0)) + fodder
                source_changed = True
            planner.put(formation_path, formation)
            rows.append(
                f"{formation.get('name', formation_ref)} receives {food} kg grain and {fodder} kg fodder immediately"
                + (f"; depot shortfall remains {food_short} kg grain and {fodder_short} kg fodder" if food_short or fodder_short else "")
                + "."
            )
            continue

        if food <= 0 and fodder <= 0:
            rows.append(
                f"{formation.get('name', formation_ref)} receives no dispatch because the Qin source depot lacks the requested reserve; shortfall is {food_need} kg grain and {fodder_need} kg fodder."
            )
            continue
        try:
            travel_hours = max(1, int(planner._route_travel_hours(source_loc, formation_loc, modes=("formation",))))
        except (KeyError, ValueError, FileNotFoundError):
            rows.append(
                f"{formation.get('name', formation_ref)} cannot receive a convoy because no lawful formation-supply route currently connects the Qin source depot to {formation_loc}; no stock is removed."
            )
            continue

        destination_path, destination = planner._material_depot(formation)
        if destination_path == _QIN_DEPOT_PATH:
            raise ValueError("remote Qin provisioning unexpectedly resolved to the home depot")
        convoy_ref = _convoy_ref(request_id, formation_ref)
        incoming = destination.setdefault("incoming_convoys", {})
        existing = incoming.get(convoy_ref)
        if isinstance(existing, Mapping):
            rows.append(f"{formation.get('name', formation_ref)} already has Qin convoy {convoy_ref} in transit.")
            continue

        source_stocks["grain_kg"] = available_food - food
        source_stocks["fodder_kg"] = available_fodder - fodder
        source_changed = True
        arrival = now.add_seconds(travel_hours * 3600)
        incoming[convoy_ref] = {
            "convoy_ref": convoy_ref,
            "status": "in_transit",
            "source_depot_ref": str(source.get("owner_id", "state_depot_qin")),
            "destination_location_ref": formation_loc,
            "formation_ref": formation_ref,
            "dispatched_at": at,
            "arrives_at": str(arrival),
            "food_kg": food,
            "fodder_kg": fodder,
        }
        planner.put(destination_path, destination)
        _schedule_convoy(
            planner,
            convoy_ref=convoy_ref,
            request_id=request_id,
            formation_ref=formation_ref,
            depot_path=destination_path,
            destination_location_ref=formation_loc,
            arrival=arrival,
        )
        rows.append(
            f"{formation.get('name', formation_ref)}: Qin dispatches {food} kg grain and {fodder} kg fodder; arrival {arrival}"
            + (f"; source-depot shortfall remains {food_short} kg grain and {fodder_short} kg fodder" if food_short or fodder_short else "")
            + "."
        )

    if source_changed:
        planner.put(_QIN_DEPOT_PATH, source)
    return (
        f"Qin field support accepts Tang Wei's provisioning request. The registered initial carried reserve is {reserve_days} days at {food_rate:g} kg food per soldier per day. "
        + " ".join(rows)
        + " Stock is conserved from the exact Qin depot; remote issues remain in convoy escrow until physical arrival."
    )[:4000]


def _operation_summary(planner: Any, host: Mapping[str, Any]) -> str:
    operation_ref = str(host.get("operation_ref", ""))
    op_path = planner.read("state/operations/index.json").get("operations", {}).get(operation_ref)
    operation = planner.read(op_path) if isinstance(op_path, str) else None
    if not isinstance(operation, Mapping):
        raise ValueError("Qin support review lost its active operation")
    order = operation.get("current_operational_order") if isinstance(operation.get("current_operational_order"), Mapping) else {}
    raw_refs = host.get("formation_refs")
    refs = [str(ref) for ref in raw_refs if isinstance(ref, str) and ref] if isinstance(raw_refs, list) else []
    total_people = 0
    total_food = 0
    locations: set[str] = set()
    for ref in refs:
        formation = planner.read(planner.owner_path(ref))
        if str(formation.get("administrative_owner", "")) != "state_qin":
            continue
        total_people += max(0, int(formation.get("personnel", 0)))
        total_food += max(0, int((formation.get("logistics", {}) or {}).get("food_kg", 0)))
        locations.add(str(formation.get("location_ref", "")))
    objective = str(order.get("objective") or operation.get("objective") or "the active Qin operation")
    order_ref = str(order.get("order_ref", "current Qin operational order"))
    return (
        f"The Qin Military Bureau answers Tang Wei's operational request from the exact current command record. Order {order_ref} remains active: {objective}. "
        f"The reviewed Qin command contains {len(refs)} persistent formations with {total_people} fighting troops, currently carrying {total_food} kg food across locations {', '.join(sorted(x for x in locations if x)) or 'not established'}. "
        "The current order does not itself establish an enemy contact, march route, or battle plan beyond those saved facts. Qin does not choose Tang Wei's route or tactics through this support reply."
    )[:4000]


def _march_summary(planner: Any, host: Mapping[str, Any]) -> str:
    policy = _policy(planner)
    reserve_days = int(policy["commanded_initial_reserve_days"])
    food_rate = float(policy["food_kg_per_person_day"])
    raw_refs = host.get("formation_refs")
    refs = [str(ref) for ref in raw_refs if isinstance(ref, str) and ref] if isinstance(raw_refs, list) else []
    total_people = 0
    total_food = 0
    ready = 0
    for ref in refs:
        formation = planner.read(planner.owner_path(ref))
        if str(formation.get("administrative_owner", "")) != "state_qin":
            continue
        n = max(0, int(formation.get("personnel", 0)))
        food = max(0, int((formation.get("logistics", {}) or {}).get("food_kg", 0)))
        total_people += n
        total_food += food
        if food >= int(math.ceil(n * food_rate * reserve_days)):
            ready += 1
    return (
        f"Qin acknowledges Tang Wei's march-preparation notice for {len(refs)} assigned Qin formations. Their current carried food is {total_food} kg for {total_people} troops; {ready} of {len(refs)} meet the registered {reserve_days}-day initial field reserve. "
        "This acknowledgment does not move the army, choose a route, or authorize tactics. Any provisioning already dispatched remains subject to physical arrival before movement can consume it."
    )[:4000]


def settle_qin_command_support(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    request_id = str(host.get("request_id", ""))
    support_kind = str(host.get("support_kind", ""))
    if not request_id or support_kind not in {"provisioning", "operational_briefing", "march_support"}:
        raise ValueError("Qin command support host is invalid")
    event_ref = _response_ref(request_id)
    existing = get_causal_event(planner, event_ref)
    if isinstance(existing, Mapping):
        return None
    if support_kind == "provisioning":
        summary = _provision(planner, host, at)
    elif support_kind == "operational_briefing":
        summary = _operation_summary(planner, host)
    else:
        summary = _march_summary(planner, host)
    _write_response(
        planner,
        event_ref=event_ref,
        request_id=request_id,
        support_kind=support_kind,
        summary=summary,
        at=at,
        source_event_ref=str(host.get("operation_ref", "")) or None,
    )
    return {
        "wake_ref": f"wake.qin.command_support.{_digest('wake', event_ref + '|' + at)}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": event_ref,
        "reason": summary,
    }


def settle_qin_supply_convoy(planner: Any, host: Mapping[str, Any], at: str) -> str | None:
    convoy_ref = str(host.get("convoy_ref", ""))
    formation_ref = str(host.get("formation_ref", ""))
    depot_path = str(host.get("destination_depot_path", ""))
    destination_location = str(host.get("destination_location_ref", ""))
    if not convoy_ref or not formation_ref or not depot_path or not destination_location:
        raise ValueError("Qin supply convoy host is invalid")
    response_ref = _convoy_response_ref(convoy_ref)
    if isinstance(get_causal_event(planner, response_ref), Mapping):
        return response_ref

    depot = copy.deepcopy(planner.read(depot_path))
    incoming = depot.get("incoming_convoys")
    row = incoming.get(convoy_ref) if isinstance(incoming, dict) else None
    if not isinstance(row, Mapping) or row.get("status") != "in_transit":
        raise ValueError("Qin supply convoy lost its conserved in-transit cargo")
    food = max(0, int(row.get("food_kg", 0)))
    fodder = max(0, int(row.get("fodder_kg", 0)))
    incoming.pop(convoy_ref, None)
    stocks = depot.setdefault("stocks", {})
    stocks["grain_kg"] = int(stocks.get("grain_kg", 0)) + food
    stocks["fodder_kg"] = int(stocks.get("fodder_kg", 0)) + fodder

    formation_path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(formation_path))
    issued = str(formation.get("location_ref", "")) == destination_location
    if issued:
        logistics = formation.setdefault("logistics", {})
        stocks["grain_kg"] -= food
        stocks["fodder_kg"] -= fodder
        logistics["food_kg"] = int(logistics.get("food_kg", 0)) + food
        logistics["fodder_kg"] = int(logistics.get("fodder_kg", 0)) + fodder
        planner.put(formation_path, formation)
    depot.setdefault("completed_convoys", []).append({
        "convoy_ref": convoy_ref,
        "formation_ref": formation_ref,
        "arrived_at": at,
        "food_kg": food,
        "fodder_kg": fodder,
        "disposition": "issued_to_formation" if issued else "cached_at_destination",
    })
    depot["completed_convoys"] = depot["completed_convoys"][-24:]
    planner.put(depot_path, depot)

    summary = (
        f"Qin supply convoy {convoy_ref} reaches {destination_location} with {food} kg grain and {fodder} kg fodder. "
        + (f"The cargo is issued to {formation.get('name', formation_ref)} at the destination." if issued else "The formation has moved; the conserved cargo remains in the destination field cache instead of teleporting after it.")
    )
    _write_response(
        planner,
        event_ref=response_ref,
        request_id=str(host.get("request_id", convoy_ref)),
        support_kind="supply_arrived" if issued else "supply_cached",
        summary=summary,
        at=at,
    )
    return response_ref


def sync_qin_command_support(planner: Any, runtime: dict[str, Any]) -> None:
    hosts, events = runtime.get("hosts"), runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    scopes = _active_qin_scopes(planner)
    if not scopes:
        return
    current = CampaignTime.parse(str(runtime["world_time"]))
    review_delay = int(_policy(planner)["qin_support_review_delay_hours"]) * 3600
    event_ids = {str(row.get("event_id")) for row in events if isinstance(row, Mapping)}

    for history in recent_history_events(planner, _HISTORY_WINDOW):
        if not isinstance(history, Mapping):
            continue
        attempt = parse_interaction_attempt_summary(history.get("summary"))
        if not isinstance(attempt, Mapping) or attempt.get("actor_id") != _PLAYER_REF:
            continue
        request_id = attempt.get("request_id")
        requested_at = history.get("at")
        if not isinstance(request_id, str) or not request_id or not isinstance(requested_at, str):
            continue
        if isinstance(get_causal_event(planner, _response_ref(request_id)), Mapping):
            continue
        matched = _attempt_scope(attempt, scopes)
        if matched is None:
            continue
        scope, qin_refs = matched
        support_kind = _support_kind(attempt, scope, qin_refs)
        if support_kind is None:
            continue
        if support_kind in {"operational_briefing", "march_support"} and not qin_refs:
            qin_refs = list(scope["formation_refs"])
        host_id, event_id = _review_ids(request_id)
        if host_id in hosts:
            continue
        due_raw = CampaignTime.parse(requested_at).add_seconds(review_delay)
        due = due_raw if due_raw > current else current
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "qin_command_support_review",
            "owner_ref": _QIN_BUREAU_REF,
            "request_id": request_id,
            "source_event_id": history.get("event_id"),
            "support_kind": support_kind,
            "appointment_office": scope.get("office"),
            "operation_ref": scope.get("operation_ref"),
            "formation_refs": list(qin_refs),
            "recurrence_seconds": 0,
            "next_due": str(due),
            "resolved_through": str(current if current < due else due.add_seconds(-1)),
            "safe_through": str(due.add_seconds(-1)),
        }
        if event_id not in event_ids:
            events.append({
                "event_id": event_id,
                "kind": "qin_command_support_review",
                "priority": _REVIEW_PRIORITY,
                "target_host": host_id,
                "due_at": str(due),
            })
            event_ids.add(event_id)


class QinCommandSupportFlowMixin:
    """Make active Qin field-command support causally reachable after assumption."""

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        if getattr(self, "_central_scheduler_reconciliation_active", False):
            return super()._advance_runtime(target_text)
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        sync_qin_command_support(self, runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        kind = str(host.get("kind", ""))
        if kind == "qin_command_support_review":
            wake = settle_qin_command_support(self, host, due_text)
            if isinstance(wake, dict):
                wake["target_host"] = self._active_host_id
                wake["event_id"] = self._active_event_id
            self._pending_wake_created = wake
            return
        if kind == "qin_command_supply_convoy":
            settle_qin_supply_convoy(self, host, due_text)
            self._pending_wake_created = None
            return
        return super()._run_due_host(host, due_text)


__all__ = [
    "QinCommandSupportFlowMixin",
    "settle_qin_command_support",
    "settle_qin_supply_convoy",
    "sync_qin_command_support",
]
