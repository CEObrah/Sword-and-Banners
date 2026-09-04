"""Post-assumption Qin field-command support and campaign briefing routing.

Player interaction attempts remain intent-only. This module claims only attempts
inside Tang Wei's active Qin field-command scope, schedules an institution-owned
review, and settles replies from exact operation/formation owners. Ordinary army
ration/feed is not an inventory: support readiness is derived from current routes,
territory, force size, mounts and civilian food stress. Discrete ammunition,
equipment and remounts remain conserved through their normal command surfaces.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import (
    get_causal_event,
    read_causal_event_owner,
    write_causal_event_owner,
)
from sword_runtime.military_supply import evaluate_military_supply
from sword_runtime.campaign_communications import (
    command_endpoint_location,
    command_message_route,
    ensure_player_message_delivery,
    player_command_location,
)
from sword_runtime.campaign_briefing import (
    build_campaign_dossier,
    ensure_actionable_mission_packet,
    persist_campaign_briefing,
    reconcile_campaign_arrival,
    render_campaign_briefing,
)
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.operation_routing import exact_operation_record

_RUNTIME_PATH = "state/runtime.json"
_PLAYER_PATH = "state/player.json"
_LOGISTICS_RULES_PATH = "game/data/mechanics/logistics.json"
_HISTORY_WINDOW = 512
_REVIEW_PRIORITY = 43
_PLAYER_REF = "char_tang_wei"
_QIN_BUREAU_REF = "inst_qin_military_bureau"
QIN_COMMAND_SUPPORT_DELIVERY_INDEX = "state/index/qin-command-support-delivery.json"


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def _response_ref(work_ref: str) -> str:
    return f"event_qin_command_support_{_digest('response', work_ref)}"


def _review_ids(work_ref: str) -> tuple[str, str]:
    d = _digest("review", work_ref)
    return f"host_qin_command_support_{d}", f"event_qin_command_support_due_{d}"


def _policy(planner: Any) -> Mapping[str, Any]:
    rules = planner.read(_LOGISTICS_RULES_PATH)
    policy = rules.get("military_supply_policy") if isinstance(rules, Mapping) else None
    if not isinstance(policy, Mapping):
        raise ValueError("military supply policy is missing")
    review_hours = policy.get("qin_support_review_delay_hours", 4)
    if isinstance(review_hours, bool) or not isinstance(review_hours, int) or review_hours <= 0:
        raise ValueError("Qin support review delay is invalid")
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
        operation_ref = _resolve_scope_operation_ref(planner, row, refs)
        scopes.append({
            "office": str(row.get("office", "")),
            "operation_ref": operation_ref,
            "formation_refs": refs,
        })
    return scopes


def _active_operation_order(planner: Any, operation_ref: str) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    if not operation_ref:
        return None
    resolved = exact_operation_record(planner, operation_ref)
    if resolved is None:
        return None
    _path, operation = resolved
    if not isinstance(operation, Mapping) or str(operation.get("status", "")) not in {"active", "mobilizing", "advancing", "engaged", "occupied"}:
        return None
    order_ref = str(operation.get("last_operational_order_ref", ""))
    orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    order = None
    for row in reversed(orders):
        if not isinstance(row, Mapping):
            continue
        if order_ref and str(row.get("order_ref", "")) != order_ref:
            continue
        order = row; break
    return (operation, order) if isinstance(order, Mapping) else None


def _resolve_scope_operation_ref(planner: Any, appointment: Mapping[str, Any], formation_refs: list[str]) -> str:
    """Resolve the current operation for a long-lived Qin field appointment.

    Older campaign appointments predate the persisted ``operation_ref`` field.
    Their command group is still the exact authority for the currently active
    operational context, so use that link rather than requiring a state repair.
    Fail closed if the context is not an active operation for this command group
    or does not contain any of the appointment's Qin formations.
    """
    direct = appointment.get("operation_ref")
    if isinstance(direct, str) and direct and _active_operation_order(planner, direct) is not None:
        return direct

    command_group_ref = appointment.get("command_group_ref")
    if not isinstance(command_group_ref, str) or not command_group_ref:
        return ""
    try:
        group_path = planner.owner_path(command_group_ref)
    except (KeyError, FileNotFoundError, ValueError):
        return ""
    group = planner.read_optional(group_path)
    if not isinstance(group, Mapping):
        return ""
    candidate = group.get("active_context_ref")
    if not isinstance(candidate, str) or not candidate:
        return ""
    active = _active_operation_order(planner, candidate)
    if active is None:
        return ""
    operation, _order = active
    operation_group_ref = operation.get("command_group_ref")
    if isinstance(operation_group_ref, str) and operation_group_ref and operation_group_ref != command_group_ref:
        return ""
    participants = {
        str(ref) for ref in operation.get("formation_refs", [])
        if isinstance(ref, str) and ref
    }
    if formation_refs and not participants.intersection(formation_refs):
        return ""
    return candidate


def _auto_briefing_work_ref(operation_ref: str, order_ref: str) -> str:
    return f"auto_qin_campaign_briefing_{_digest('auto-briefing', operation_ref + '|' + order_ref)}"


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
    supply_terms = ("provision", "supply", "food", "grain", "ration", "animal feed", "resupply")
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
    work_ref: str,
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
    event = {
        "event_ref": event_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": _QIN_BUREAU_REF,
        "target_ref": _PLAYER_REF,
        "basis_goal": f"Qin field-command support review for {work_ref}"[:500],
        "process_kind": "qin_field_command_support",
        "process_stage": support_kind,
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
            "source_work_ref": work_ref,
        },
    }
    if isinstance(source_event_ref, str) and source_event_ref:
        event["source_event_ref"] = source_event_ref
    owner["causal_events"][event_ref] = event
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return event_ref


def _provision(planner: Any, host: Mapping[str, Any], at: str) -> str:
    work_ref = str(host["work_ref"])
    raw_refs = host.get("formation_refs")
    refs = [str(ref) for ref in raw_refs if isinstance(ref, str) and ref] if isinstance(raw_refs, list) else []
    if not refs:
        raise ValueError("Qin support review lost its formations")
    rows: list[str] = []
    for formation_ref in refs:
        formation = planner.read(planner.owner_path(formation_ref))
        if str(formation.get("administrative_owner", "")) != "state_qin" or str(formation.get("command_authority", "")) != _PLAYER_REF:
            raise PermissionError("Qin support review may inspect only Qin-owned formations under Tang Wei's active field command")
        supply = evaluate_military_supply(planner, formation, at=at)
        rows.append(
            f"{formation.get('name', formation_ref)}: strategic supply {supply.get('condition', 'adequate')} "
            f"({int(supply.get('score_milli', 0))}/1000), nearest support {supply.get('nearest_support_ref') or 'none'} "
            f"at {supply.get('nearest_support_route_hours') if supply.get('nearest_support_route_hours') is not None else 'unreachable'} route-hours."
        )
    return (
        "Qin field support reviews Tang Wei's assigned formations. Ordinary food and animal feed are handled by the strategic support network rather than issued as formation inventory. "
        + " ".join(rows)
        + " If ammunition, replacement equipment or remounts are needed, those remain separate conserved assets and require their normal exact issue/resupply path."
    )[:4000]


def _operation_summary(planner: Any, host: Mapping[str, Any], at: str) -> tuple[str, str]:
    operation_ref = str(host.get("operation_ref", ""))
    if not operation_ref:
        raise ValueError("Qin support review lost its active operation")
    dossier = build_campaign_dossier(planner, operation_ref)
    packet = ensure_actionable_mission_packet(planner, operation_ref, dossier, at=at)
    # Rebuild after staff work so rendering reflects the newly established packet.
    dossier = build_campaign_dossier(planner, operation_ref)
    summary = render_campaign_briefing(planner, dossier, packet)
    information_ref = persist_campaign_briefing(planner, dossier=dossier, summary=summary, at=at)
    return summary, information_ref


def _march_summary(planner: Any, host: Mapping[str, Any]) -> str:
    raw_refs = host.get("formation_refs")
    refs = [str(ref) for ref in raw_refs if isinstance(ref, str) and ref] if isinstance(raw_refs, list) else []
    rows: list[str] = []
    for ref in refs:
        formation = planner.read(planner.owner_path(ref))
        if str(formation.get("administrative_owner", "")) != "state_qin":
            continue
        supply = evaluate_military_supply(planner, formation, at=str(planner._world_time()))
        rows.append(f"{formation.get('name', ref)} {supply.get('condition', 'adequate')} ({int(supply.get('score_milli', 0))}/1000)")
    return (
        f"Qin acknowledges Tang Wei's march-preparation notice for {len(refs)} assigned Qin formations. "
        + ("Current strategic supply: " + "; ".join(rows) + ". " if rows else "")
        + "This acknowledgment does not move the army, choose a route, or authorize tactics. Ordinary baggage moves with the formations; discrete ammunition, equipment and remount shortages remain exact assets."
    )[:4000]


def settle_qin_command_support(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    if not ensure_player_message_delivery(planner, host, at):
        return None
    work_ref = str(host.get("work_ref", ""))
    support_kind = str(host.get("support_kind", ""))
    if not work_ref or support_kind not in {"provisioning", "operational_briefing", "march_support"}:
        raise ValueError("Qin command support host is invalid")
    event_ref = _response_ref(work_ref)
    existing = get_causal_event(planner, event_ref)
    if isinstance(existing, Mapping):
        return None
    information_ref = None
    prior_delivery_ref = None
    prior_delivery_established = False
    delivery_index = None
    operation_ref = ""
    if support_kind == "operational_briefing" and work_ref.startswith("auto_qin_campaign_briefing_"):
        delivery_index = copy.deepcopy(planner.read_optional(QIN_COMMAND_SUPPORT_DELIVERY_INDEX) or {
            "schema": "generic-object", "authority": False, "by_operation": {}
        })
        operation_ref = str(host.get("operation_ref", ""))
        prior = delivery_index.setdefault("by_operation", {}).get(operation_ref)
        prior_delivery_ref = str(prior.get("information_ref", "")) if isinstance(prior, Mapping) else None
        if prior_delivery_ref:
            exact_prior = planner.read_optional(f"state/information/{prior_delivery_ref}.json")
            prior_delivery_established = bool(
                isinstance(exact_prior, Mapping)
                and str(exact_prior.get("information_ref", "")) == prior_delivery_ref
                and _PLAYER_REF in exact_prior.get("knowers", [])
            )
    if support_kind == "provisioning":
        summary = _provision(planner, host, at)
    elif support_kind == "operational_briefing":
        summary, information_ref = _operation_summary(planner, host, at)
        if work_ref.startswith("auto_qin_campaign_briefing_"):
            # The delivery index is routing/dedupe only.  It may suppress an
            # unchanged auto-briefing only when its pointer was already backed
            # by an exact player-known information owner before this settlement.
            # A stale index entry alone must never swallow the first real
            # briefing response or its player-facing wake.
            if prior_delivery_established and prior_delivery_ref == str(information_ref):
                return None
            assert isinstance(delivery_index, dict)
            delivery_index["by_operation"][operation_ref] = {"information_ref": information_ref}
            planner.put(QIN_COMMAND_SUPPORT_DELIVERY_INDEX, delivery_index)
    else:
        summary = _march_summary(planner, host)
    _write_response(
        planner,
        event_ref=event_ref,
        work_ref=work_ref,
        support_kind=support_kind,
        summary=summary,
        at=at,
        source_event_ref=str(host.get("operation_ref", "")) or None,
    )
    wake = {
        "wake_ref": f"wake.qin.command_support.{_digest('wake', event_ref + '|' + at)}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": event_ref,
        "reason": summary,
    }
    if isinstance(information_ref, str) and information_ref:
        wake["information_ref"] = information_ref
        wake["operation_ref"] = str(host.get("operation_ref", ""))
    return wake




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

    # An accepted field command should not require the player to guess that a
    # strategic directive is missing staff work. Pending Qin orders automatically
    # route one idempotent operational briefing review.
    for scope in scopes:
        operation_ref = str(scope.get("operation_ref", ""))
        current_order = _active_operation_order(planner, operation_ref)
        if current_order is None:
            continue
        operation, order = current_order
        if str(order.get("actionability_status", "")) != "pending_operational_briefing":
            continue
        order_ref = str(order.get("order_ref", ""))
        if not order_ref:
            continue
        work_ref = _auto_briefing_work_ref(operation_ref, order_ref)
        if isinstance(get_causal_event(planner, _response_ref(work_ref)), Mapping):
            continue
        host_id, event_id = _review_ids(work_ref)
        if host_id in hosts:
            continue
        bureau_location = command_endpoint_location(planner, _QIN_BUREAU_REF)
        response_target = player_command_location(planner)
        if not bureau_location or not response_target:
            raise ValueError("automatic Qin command briefing lacks physical delivery endpoints")
        route = command_message_route(planner.read, bureau_location, response_target, round_trip=False)
        travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
        due = current.add_seconds(review_delay + travel_seconds)
        hosts[host_id] = {
            "host_id": host_id, "kind": "qin_command_support_review", "owner_ref": _QIN_BUREAU_REF,
            "work_ref": work_ref, "source_event_id": None, "support_kind": "operational_briefing",
            "appointment_office": scope.get("office"), "operation_ref": operation_ref,
            "formation_refs": list(scope.get("formation_refs", [])),
            "bureau_location_ref": bureau_location, "response_target_location_ref": response_target,
            "communication_travel_seconds": travel_seconds, "institution_processing_seconds": review_delay,
            "courier_route": copy.deepcopy(dict(route)),
            "communication_rule": "automatic staff briefing is not delivered until review and physical courier travel complete",
            "recurrence_seconds": 0,
            "next_due": str(due), "resolved_through": str(due.add_seconds(-1)), "safe_through": str(due.add_seconds(-1)),
        }
        if event_id not in event_ids:
            events.append({"event_id": event_id, "kind": "qin_command_support_review", "priority": _REVIEW_PRIORITY, "target_host": host_id, "due_at": str(due)})
            event_ids.add(event_id)

    attempts, _ = recent_interaction_attempts(planner, _PLAYER_REF, limit=_HISTORY_WINDOW)
    for attempt in attempts:
        work_ref = interaction_attempt_ref(attempt)
        requested_at = attempt.get("at")
        if not work_ref or not isinstance(requested_at, str):
            continue
        if isinstance(get_causal_event(planner, _response_ref(work_ref)), Mapping):
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
        host_id, event_id = _review_ids(work_ref)
        if host_id in hosts:
            continue
        origin_location = attempt.get("origin_location_ref")
        if not isinstance(origin_location, str) or not origin_location:
            origin_location = player_command_location(planner)
        bureau_location = command_endpoint_location(planner, _QIN_BUREAU_REF)
        if not origin_location or not bureau_location:
            raise ValueError("Qin command support request lacks physical communication endpoints")
        route = command_message_route(planner.read, origin_location, bureau_location, round_trip=True)
        travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
        due_raw = CampaignTime.parse(requested_at).add_seconds(review_delay + travel_seconds)
        due = due_raw if due_raw > current else current
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "qin_command_support_review",
            "owner_ref": _QIN_BUREAU_REF,
            "work_ref": work_ref,
            "source_event_id": attempt.get("event_id"),
            "support_kind": support_kind,
            "appointment_office": scope.get("office"),
            "operation_ref": scope.get("operation_ref"),
            "formation_refs": list(qin_refs),
            "request_origin_location_ref": origin_location,
            "bureau_location_ref": bureau_location,
            "response_target_location_ref": origin_location,
            "communication_travel_seconds": travel_seconds,
            "institution_processing_seconds": review_delay,
            "courier_route": copy.deepcopy(dict(route)),
            "communication_rule": "request is not receipt; Bureau response follows physical round-trip courier travel",
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

    def _command_layer_qin_command_support(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        result = next_dispatch()
        is_group_move = command.command_type == "command_group_action" and str(payload.get("action", "")) == "move_army"
        is_escorted_travel = command.command_type == "travel" and isinstance(payload.get("formation_refs"), list)
        if not is_group_move and not is_escorted_travel:
            return result
        group_ref = str(payload.get("command_group_ref", "")) if is_group_move else ""
        destination_ref = str(payload.get("location_ref", "")) if is_group_move else str(payload.get("destination_ref", ""))
        moved_refs = {str(ref) for ref in payload.get("formation_refs", []) if isinstance(ref, str) and ref} if is_escorted_travel else set()
        if not destination_ref:
            return result
        for scope in _active_qin_scopes(self):
            operation_ref = str(scope.get("operation_ref", ""))
            current = _active_operation_order(self, operation_ref)
            if current is None:
                continue
            operation, _order = current
            if is_group_move:
                if str(operation.get("command_group_ref", "")) != group_ref:
                    continue
            else:
                scope_refs = {str(ref) for ref in scope.get("formation_refs", []) if isinstance(ref, str) and ref}
                if not (moved_refs & scope_refs):
                    continue
            # The reconciler itself is the authority for completion: it returns
            # None until every friendly operation participant is physically at
            # the packet destination. Calling it after grouped travel is safe and
            # closes the handoff path that used to exist only for move_army.
            handoff = reconcile_campaign_arrival(
                self, operation_ref, destination_ref=destination_ref,
                at=str(result.get("world_time") or self._world_time()),
                unit_duties=result.get("unit_duties") if isinstance(result.get("unit_duties"), list) else None,
            )
            if isinstance(handoff, Mapping):
                result = dict(result); result["campaign_handoff"] = copy.deepcopy(dict(handoff))
                break
        return result

    # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = [
    "QinCommandSupportFlowMixin",
    "settle_qin_command_support",
    "sync_qin_command_support",
]
