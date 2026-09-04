"""Causal substantive request handling for Tang Wei's campaign headquarters.

`seek_contact` establishes only a lawful headquarters receiving channel. This
module carries a player statement that already included substantive campaign
business into a separate superior-command review after that receiving stage, or
handles a request made during an exact established command scene. It never
moves troops, invents tactics, changes ownership, or grants a vanguard role
without an exact order/directive owner.

The final response uses the existing institution-owned follow-up host and event
settlement path. This keeps one chronology dispatcher and one response-delivery
authority instead of introducing a second ad-hoc message system.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_communications import (
    command_endpoint_location,
    command_message_route,
    player_command_location,
)
from sword_runtime.causal_event_store import get_causal_event_from_reader, iter_causal_events_newest
from sword_runtime.contact_request_flow import _followup_response_ref, _response_ref
from sword_runtime.sim.calendar import CampaignTime


_PLAYER_REF = "char_tang_wei"
_LEDGER_PATH = "state/index/interaction-attempts.json"
_MECHANICS_PATH = "game/data/mechanics/campaign-command.json"
_HISTORY_WINDOW = 256
_REQUEST_PRIORITY = 48
_CLOSED_CYCLE_STATUSES = {"closed", "completed", "cancelled", "inactive"}

_LEGACY_MARCH_TERMS = (
    "march order", "march orders", "exact order", "exact orders", "march sequence",
    "order to march", "orders for sanyou",
)
_LEGACY_VANGUARD_TERMS = ("vanguard", "advance guard", "lead the van", "lead the advance")
_LEGACY_JUNCTION_TERMS = (
    "junction plan", "junction point", "joining point", "rendezvous",
    "join the main body", "where to join",
)
_SEMANTIC_TOPIC_ALIASES = {
    "march_orders": "march_orders",
    "campaign_command:march_orders": "march_orders",
    "vanguard": "vanguard",
    "vanguard_assignment": "vanguard",
    "campaign_command:vanguard": "vanguard",
    "campaign_command:vanguard_assignment": "vanguard",
    "junction_plan": "junction_plan",
    "campaign_command:junction_plan": "junction_plan",
}


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def campaign_command_request_response_ref(attempt_ref: str) -> str:
    """Return the exact generic institutional-followup response identity."""
    return _followup_response_ref(attempt_ref)


def _request_ids(attempt_ref: str) -> tuple[str, str]:
    token = _digest("request", attempt_ref)
    return f"host_campaign_command_request_{token}", f"event_campaign_command_request_due_{token}"


def _mechanics(planner: Any) -> Mapping[str, Any]:
    raw = planner.read(_MECHANICS_PATH)
    section = raw.get("campaign_command_cycle") if isinstance(raw, Mapping) else None
    if not isinstance(section, Mapping):
        raise ValueError("campaign command mechanics are missing")
    return section


def _ledger_attempts(planner: Any) -> list[dict[str, Any]]:
    raw = planner.read_optional(_LEDGER_PATH)
    rows = raw.get("attempts", []) if isinstance(raw, Mapping) else []
    if not isinstance(rows, list):
        return []
    values = [copy.deepcopy(dict(row)) for row in rows[-_HISTORY_WINDOW:] if isinstance(row, Mapping)]
    return [row for row in values if row.get("actor_id") == _PLAYER_REF]


def _request_topics(attempt: Mapping[str, Any]) -> tuple[str, ...]:
    """Resolve mechanical follow-up topics without making prose an action whitelist.

    New interactions should carry a semantic ``topic`` chosen after the GM has
    understood the player's request. Phrase matching remains only as a backward-
    compatibility route for already-persisted interaction rows that predate the
    semantic topic contract. Ordinary dialogue never depends on this function.
    """
    topic = str(attempt.get("topic") or "").strip().lower()
    topics: list[str] = []
    if topic:
        for token in (part.strip() for part in topic.replace(";", ",").replace("|", ",").split(",")):
            resolved = _SEMANTIC_TOPIC_ALIASES.get(token)
            if resolved and resolved not in topics:
                topics.append(resolved)
        if topics:
            return tuple(topics)

    # Legacy persisted rows did not consistently carry semantic topic metadata.
    # Keep them resumable, but do not advertise text matching as the new route.
    text = " ".join(str(attempt.get(key, "") or "").lower() for key in ("player_statement", "posture"))
    if any(term in text for term in _LEGACY_MARCH_TERMS):
        topics.append("march_orders")
    if any(term in text for term in _LEGACY_VANGUARD_TERMS):
        topics.append("vanguard")
    if any(term in text for term in _LEGACY_JUNCTION_TERMS):
        topics.append("junction_plan")
    return tuple(topics)


def _cycle_from_ref(planner: Any, cycle_ref: object) -> Mapping[str, Any] | None:
    if not isinstance(cycle_ref, str) or not cycle_ref.startswith("campaign_command_cycle."):
        return None
    try:
        path = planner.owner_path(cycle_ref)
    except (KeyError, FileNotFoundError, ValueError):
        return None
    cycle = planner.read_optional(path)
    if not isinstance(cycle, Mapping):
        return None
    if cycle.get("kind") != "campaign_command_cycle" or cycle.get("cycle_ref") != cycle_ref:
        return None
    if str(cycle.get("status", "")).lower() in _CLOSED_CYCLE_STATUSES:
        return None
    participants = cycle.get("participant_commander_refs")
    if not isinstance(participants, list) or _PLAYER_REF not in participants:
        return None
    return cycle


def _campaign_contact_process(planner: Any, process_ref: object) -> tuple[Mapping[str, Any], str] | None:
    """Resolve one settled campaign-headquarters receiving event and its cycle."""
    if not isinstance(process_ref, str) or not process_ref:
        return None
    process = get_causal_event_from_reader(planner, process_ref)
    if not isinstance(process, Mapping):
        return None
    if (
        process.get("kind") != "audience_response"
        or process.get("status") != "triggered"
        or process.get("route_domain") != "campaign_command_contact"
    ):
        return None
    cycle_ref = process.get("campaign_command_cycle_ref") or process.get("source_event_ref")
    if not isinstance(cycle_ref, str) or not cycle_ref.startswith("campaign_command_cycle."):
        return None
    return process, cycle_ref


def _cycle_for_attempt(planner: Any, attempt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    process_ref = attempt.get("process_ref")
    cycle = _cycle_from_ref(planner, process_ref)
    contact_process = _campaign_contact_process(planner, process_ref)
    if cycle is None and contact_process is not None:
        _process, cycle_ref = contact_process
        cycle = _cycle_from_ref(planner, cycle_ref)
    if cycle is None and isinstance(process_ref, str):
        process = get_causal_event_from_reader(planner, process_ref)
        if isinstance(process, Mapping):
            cycle_ref = process.get("campaign_command_cycle_ref")
            if not isinstance(cycle_ref, str) and process.get("route_domain") == "campaign_command_contact":
                cycle_ref = process.get("source_event_ref")
            cycle = _cycle_from_ref(planner, cycle_ref)
    if cycle is None:
        return None

    action = str(attempt.get("action", ""))
    target_ref = attempt.get("target_ref")
    venue_ref = cycle.get("venue_ref")
    superior_ref = cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref")
    operation_ref = cycle.get("operation_ref")
    coordination_ref = cycle.get("coordination_authority_ref")
    cycle_ref = cycle.get("cycle_ref")
    in_scene = isinstance(attempt.get("scene_session_ref"), str) and bool(attempt.get("scene_session_ref"))
    has_staff_channel = contact_process is not None and contact_process[1] == cycle_ref

    if action == "seek_contact":
        if target_ref not in {venue_ref, superior_ref}:
            return None
    elif action in {"ask", "request", "petition", "present", "report"}:
        if target_ref == superior_ref:
            # Staff-channel receipt is not personal access to the named superior.
            # Person-targeted substantive speech requires a saved direct scene.
            if not in_scene:
                return None
        elif target_ref in {cycle_ref, operation_ref, coordination_ref, venue_ref, process_ref}:
            # A direct substantive request to a headquarters object/location must
            # come from an established scene or the exact settled receiving event.
            # Mere visibility of the cycle, institution, operation, or venue is
            # not itself proof that anyone heard the request.
            if not (in_scene or has_staff_channel):
                return None
            if target_ref == process_ref and not has_staff_channel:
                return None
        else:
            return None
    else:
        return None
    return cycle


def _settled_cycle_contact(
    planner: Any, cycle_ref: str, contact_ref: str | None = None,
) -> Mapping[str, Any] | None:
    expected_event_ref = _response_ref(contact_ref) if isinstance(contact_ref, str) and contact_ref else None
    for event_ref, event in iter_causal_events_newest(planner, kinds={"audience_response"}):
        if not isinstance(event, Mapping):
            continue
        if expected_event_ref is not None and event_ref != expected_event_ref:
            continue
        if event.get("route_domain") == "campaign_command_contact" and event.get("source_event_ref") == cycle_ref:
            return event
    return None


def _pending_cycle_contact(
    runtime: Mapping[str, Any], cycle_ref: str, contact_ref: str | None = None,
) -> Mapping[str, Any] | None:
    hosts = runtime.get("hosts") if isinstance(runtime, Mapping) else None
    if not isinstance(hosts, Mapping):
        return None
    for host in hosts.values():
        if not isinstance(host, Mapping):
            continue
        if (
            host.get("kind") == "contact_request"
            and host.get("route_domain") == "campaign_command_contact"
            and host.get("campaign_command_cycle_ref") == cycle_ref
            and (not isinstance(contact_ref, str) or not contact_ref or host.get("contact_ref") == contact_ref)
            and isinstance(host.get("next_due"), str)
        ):
            return host
    return None


def _pending_request_host(
    runtime: Mapping[str, Any], cycle_ref: str, attempt_ref: str | None = None,
) -> tuple[str, dict[str, Any]] | None:
    hosts = runtime.get("hosts") if isinstance(runtime, Mapping) else None
    if not isinstance(hosts, dict):
        return None
    for host_id, host in hosts.items():
        if (
            isinstance(host_id, str)
            and isinstance(host, dict)
            and host.get("kind") == "institutional_followup"
            and host.get("route_domain") == "campaign_command_request"
            and host.get("campaign_command_cycle_ref") == cycle_ref
            and (not isinstance(attempt_ref, str) or not attempt_ref or host.get("contact_ref") == attempt_ref)
            and isinstance(host.get("next_due"), str)
        ):
            return host_id, host
    return None


def _latest_order(operation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    order_ref = str(operation.get("last_operational_order_ref", ""))
    orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    for row in reversed(orders):
        if not isinstance(row, Mapping):
            continue
        if order_ref and str(row.get("order_ref", "")) != order_ref:
            continue
        return row
    return None


def _operation_for_cycle(planner: Any, cycle: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return exact operation authority or None when this is only a contact shell.

    Campaign contact receipt remains useful for synthetic/partial cycles and for
    recovery diagnostics. A substantive command answer is stricter: if the cycle
    cannot resolve its exact operation owner, no march/vanguard response is
    scheduled and the contact layer continues independently.
    """
    operation_ref = cycle.get("operation_ref")
    if not isinstance(operation_ref, str) or not operation_ref:
        return None
    try:
        path = planner.owner_path(operation_ref)
        operation = planner.read(path)
    except (KeyError, FileNotFoundError, ValueError):
        return None
    return operation if isinstance(operation, Mapping) else None


def _order_has_player_vanguard_assignment(operation: Mapping[str, Any], order: Mapping[str, Any] | None) -> bool:
    if not isinstance(order, Mapping):
        return False
    command_group_ref = operation.get("command_group_ref")
    formation_refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref}
    packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else {}
    for key in ("vanguard_command_ref", "advance_guard_command_ref"):
        value = packet.get(key) if isinstance(packet, Mapping) else None
        if isinstance(value, str) and value and value == command_group_ref:
            return True
    for key in ("vanguard_formation_refs", "advance_guard_formation_refs"):
        values = packet.get(key) if isinstance(packet, Mapping) else None
        if isinstance(values, list) and formation_refs.intersection(str(ref) for ref in values if isinstance(ref, str)):
            return True
    for directive in operation.get("campaign_command_directives", []) if isinstance(operation.get("campaign_command_directives"), list) else []:
        if not isinstance(directive, Mapping) or str(directive.get("status", "active")) != "active":
            continue
        role = str(directive.get("role", directive.get("assignment_role", ""))).lower()
        if role not in {"vanguard", "advance_guard"}:
            continue
        applies = {str(ref) for ref in directive.get("applies_to_formation_refs", []) if isinstance(ref, str)}
        if not applies or formation_refs.intersection(applies):
            return True
    return False


def _response_for(
    planner: Any,
    cycle: Mapping[str, Any],
    topics: tuple[str, ...],
) -> tuple[str, dict[str, str]] | None:
    operation = _operation_for_cycle(planner, cycle)
    if operation is None:
        return None
    order = _latest_order(operation)
    dispositions: dict[str, str] = {}
    parts: list[str] = []
    if "march_orders" in topics:
        if isinstance(order, Mapping) and (
            str(order.get("actionability_status", "")) == "actionable"
            or str(order.get("status", "")) == "staff_briefed_awaiting_commander_execution"
        ):
            dispositions["march_orders"] = "confirmed_actionable_order"
            order_ref = str(order.get("order_ref", "current order"))
            objective = str(order.get("objective") or "Execute the current campaign march order.")
            follow_on = str(order.get("follow_on_requirement") or "")
            text = f"Exact march order {order_ref} is currently actionable. Objective: {objective}"
            if follow_on:
                text += f" {follow_on}"
            parts.append(text[:2500])
        else:
            dispositions["march_orders"] = "no_executable_order"
            order_ref = str(order.get("order_ref", "current order")) if isinstance(order, Mapping) else "none"
            status = str(order.get("actionability_status") or order.get("status") or "not actionable") if isinstance(order, Mapping) else "not issued"
            parts.append(
                f"No new executable march order is established by {order_ref} in its current state ({status}). Staff planning alone does not move Tang Wei's army or authorize tactics."
            )
    if "vanguard" in topics:
        if _order_has_player_vanguard_assignment(operation, order):
            dispositions["vanguard"] = "already_assigned_by_exact_order"
            parts.append(
                "Tang Wei's current exact campaign order/directive already assigns his command to vanguard or advance-guard duty. The assignment exists in that authoritative order/directive rather than in this response record."
            )
        else:
            dispositions["vanguard"] = "unresolved_no_exact_ruling"
            parts.append(
                "No binding vanguard decision exists yet. Tang Wei's request remains unresolved. The current march order neither grants nor denies it; any later binding assignment must come from the lawful campaign-command authority."
            )
    if "junction_plan" in topics:
        packet = order.get("mission_packet") if isinstance(order, Mapping) and isinstance(order.get("mission_packet"), Mapping) else {}
        order_actionable = isinstance(order, Mapping) and (
            str(order.get("actionability_status", "")) == "actionable"
            or str(order.get("status", "")) == "staff_briefed_awaiting_commander_execution"
        )
        rendezvous_ref = packet.get("rendezvous_location_ref") if isinstance(packet, Mapping) else None
        destination_ref = packet.get("destination_ref") if isinstance(packet, Mapping) else None
        current_location = player_command_location(planner)
        if (
            order_actionable
            and isinstance(rendezvous_ref, str)
            and rendezvous_ref
            and current_location not in {rendezvous_ref, destination_ref}
        ):
            dispositions["junction_plan"] = "confirmed_current_junction_order"
            order_ref = str(order.get("order_ref", "current order"))
            text = f"Current exact order {order_ref} establishes {rendezvous_ref} as the rendezvous point"
            if isinstance(destination_ref, str) and destination_ref:
                text += f" on the way to {destination_ref}"
            parts.append(text + ". This response repeats the saved order; it does not create a new route, timing decision, or tactical commitment.")
        else:
            dispositions["junction_plan"] = "no_separate_current_junction_order"
            order_ref = str(order.get("order_ref", "none")) if isinstance(order, Mapping) else "none"
            status = str(order.get("actionability_status") or order.get("status") or "not actionable") if isinstance(order, Mapping) else "not issued"
            parts.append(
                f"No separate current junction point with the main body is established beyond the exact campaign authority already on record. The latest exact order is {order_ref} ({status}); headquarters does not invent a rendezvous from staff expectation or an old completed movement packet. Any new binding joining point must arrive as a lawful campaign-command order or directive."
            )
    if not parts:
        return None
    return " ".join(parts)[:4000], dispositions


class CampaignCommandRequestMixin:
    """Schedule one coalesced substantive superior-command response per active cycle."""

    def _sync_contact_request_routes(self, runtime: dict[str, Any]) -> None:
        # First let the access/contact layer register any required receiving host.
        super()._sync_contact_request_routes(runtime)
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        current_text = runtime.get("world_time")
        if not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(current_text, str):
            raise ValueError("runtime causal queue is invalid")
        current = CampaignTime.parse(current_text)
        delay_minutes = _mechanics(self).get("superior_request_response_delay_minutes", 15)
        if isinstance(delay_minutes, bool) or not isinstance(delay_minutes, int) or delay_minutes <= 0:
            raise ValueError("campaign superior request response delay is invalid")
        review_seconds = delay_minutes * 60

        # Each distinct player attempt is its own causal work item. Idempotency
        # is attempt-scoped, never cycle-scoped: two requests made in the same
        # command cycle must not overwrite or silently coalesce each other.
        routed_attempts: list[tuple[dict[str, Any], Mapping[str, Any], tuple[str, ...]]] = []
        for attempt in _ledger_attempts(self):
            topics = _request_topics(attempt)
            if not topics or isinstance(attempt.get("response_ref"), str):
                continue
            cycle = _cycle_for_attempt(self, attempt)
            if cycle is None:
                continue
            routed_attempts.append((attempt, cycle, topics))

        for attempt, cycle, topics in routed_attempts:
            cycle_ref = str(cycle["cycle_ref"])
            attempt_ref = str(attempt.get("event_id") or "")
            requested_at = attempt.get("at")
            if not attempt_ref or not isinstance(requested_at, str):
                continue
            if isinstance(get_causal_event_from_reader(self, campaign_command_request_response_ref(attempt_ref)), Mapping):
                continue

            request_origin = attempt.get("origin_location_ref")
            if not isinstance(request_origin, str) or not request_origin:
                request_origin = player_command_location(self)
            superior_ref = cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref")
            if not isinstance(request_origin, str) or not request_origin or not isinstance(superior_ref, str) or not superior_ref:
                continue
            superior_location = command_endpoint_location(self, superior_ref)
            if not superior_location:
                continue
            try:
                courier = command_message_route(self.read, request_origin, superior_location, round_trip=True)
            except (FileNotFoundError, KeyError, TypeError, ValueError):
                continue
            travel_seconds = max(0, int(courier.get("travel_seconds", 0) or 0))
            due = max(current, CampaignTime.parse(requested_at).add_seconds(travel_seconds + review_seconds))
            if attempt.get("action") == "seek_contact":
                settled_contact = _settled_cycle_contact(self, cycle_ref, attempt_ref)
                pending_contact = _pending_cycle_contact(runtime, cycle_ref, attempt_ref)
                if settled_contact is None and pending_contact is None:
                    # Substantive text embedded in seek_contact never skips the
                    # receiving stage. Missing routing is an audit defect, not
                    # permission to fabricate receipt.
                    continue
                if isinstance(pending_contact, Mapping):
                    # A fresh seek_contact attempt that is still being received
                    # must finish that receiving beat before headquarters can
                    # answer the substantive request embedded in it.  An older
                    # settled contact from the same campaign cycle proves the
                    # channel existed historically, but it must not collapse a
                    # newly scheduled access/receipt into an instantaneous reply.
                    contact_due = pending_contact.get("next_due")
                    if not isinstance(contact_due, str):
                        continue
                    due = max(due, CampaignTime.parse(contact_due).add_seconds(travel_seconds + review_seconds))

            response = _response_for(self, cycle, topics)
            if response is None:
                continue
            response_summary, dispositions = response
            pending = _pending_request_host(runtime, cycle_ref, attempt_ref)
            if pending is not None:
                host_id, host = pending
                old_due = CampaignTime.parse(str(host["next_due"]))
                final_due = due if due > old_due else old_due
                host.update({
                    "contact_ref": attempt_ref,
                    "source_interaction_attempt_ref": attempt_ref,
                    "source_event_id": attempt_ref,
                    "source_process_ref": cycle_ref,
                    "source_owner_ref": cycle_ref,
                    "actor_ref": cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref"),
                    "response_summary": response_summary,
                    "response_stage": "campaign_command_request_answered",
                    "request_topics": list(topics),
                    "request_dispositions": dispositions,
                    "requested_statement": str(attempt.get("player_statement") or "")[:2000],
                    "request_origin_location_ref": request_origin,
                    "source_location_ref": superior_location,
                    "response_target_location_ref": request_origin,
                    "communication_travel_seconds": travel_seconds,
                    "institution_processing_seconds": review_seconds,
                    "courier_route": copy.deepcopy(dict(courier)),
                    "communication_rule": "each request is distinct; dispatch is not receipt and the superior response uses physical geography",
                    "next_due": str(final_due),
                    "safe_through": str(final_due.add_seconds(-1)),
                })
                for event in events:
                    if isinstance(event, dict) and event.get("target_host") == host_id:
                        event["due_at"] = str(final_due)
                continue

            host_id, event_id = _request_ids(attempt_ref)
            superior_ref = cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref")
            if not isinstance(superior_ref, str) or not superior_ref:
                continue
            hosts[host_id] = {
                "host_id": host_id,
                "kind": "institutional_followup",
                "event_id": event_id,
                "owner_ref": cycle_ref,
                "route_domain": "campaign_command_request",
                "campaign_command_cycle_ref": cycle_ref,
                "operation_ref": cycle.get("operation_ref"),
                "contact_ref": attempt_ref,
                "source_interaction_attempt_ref": attempt_ref,
                "source_event_id": attempt_ref,
                "source_process_ref": cycle_ref,
                "source_owner_ref": cycle_ref,
                "actor_ref": superior_ref,
                "response_summary": response_summary,
                "response_stage": "campaign_command_request_answered",
                "delivery_route": "campaign headquarters staff through the saved superior-command channel",
                "request_topics": list(topics),
                "request_dispositions": dispositions,
                "requested_statement": str(attempt.get("player_statement") or "")[:2000],
                "request_origin_location_ref": request_origin,
                "source_location_ref": superior_location,
                "response_target_location_ref": request_origin,
                "communication_travel_seconds": travel_seconds,
                "institution_processing_seconds": review_seconds,
                "courier_route": copy.deepcopy(dict(courier)),
                "communication_rule": "each request is distinct; dispatch is not receipt and the superior response uses physical geography",
                "recurrence_seconds": 0,
                "next_due": str(due),
                "resolved_through": str(current if current < due else due.add_seconds(-1)),
                "safe_through": str(due.add_seconds(-1)),
            }
            if not any(isinstance(event, Mapping) and event.get("event_id") == event_id for event in events):
                events.append({
                    "event_id": event_id,
                    "kind": "institutional_followup",
                    "priority": _REQUEST_PRIORITY,
                    "target_host": host_id,
                    "due_at": str(due),
                })


__all__ = [
    "CampaignCommandRequestMixin",
    "campaign_command_request_response_ref",
    "_cycle_for_attempt",
    "_operation_for_cycle",
]
