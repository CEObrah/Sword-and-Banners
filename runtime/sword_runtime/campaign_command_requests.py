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

from sword_runtime.causal_event_store import get_causal_event_from_reader, iter_causal_events_newest
from sword_runtime.contact_request_flow import (
    _followup_response_ref,
    _response_ref as contact_response_ref,
)
from sword_runtime.sim.calendar import CampaignTime


_PLAYER_REF = "char_tang_wei"
_LEDGER_PATH = "state/index/interaction-attempts.json"
_MECHANICS_PATH = "game/data/mechanics/campaign-command.json"
_HISTORY_WINDOW = 256
_REQUEST_PRIORITY = 48
_CLOSED_CYCLE_STATUSES = {"closed", "completed", "cancelled", "inactive"}

_MARCH_TERMS = (
    "march order", "march orders", "exact order", "exact orders", "march sequence",
    "order to march", "orders for sanyou",
)
_VANGUARD_TERMS = ("vanguard", "advance guard", "lead the van", "lead the advance")


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
    text = " ".join(str(attempt.get(key, "") or "").lower() for key in ("player_statement", "posture"))
    topics: list[str] = []
    if any(term in text for term in _MARCH_TERMS):
        topics.append("march_orders")
    if any(term in text for term in _VANGUARD_TERMS):
        topics.append("vanguard")
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


def _cycle_for_attempt(planner: Any, attempt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    process_ref = attempt.get("process_ref")
    cycle = _cycle_from_ref(planner, process_ref)
    if cycle is None and isinstance(process_ref, str):
        process = get_causal_event_from_reader(planner, process_ref)
        cycle = _cycle_from_ref(planner, process.get("campaign_command_cycle_ref") if isinstance(process, Mapping) else None)
    if cycle is None:
        return None

    action = str(attempt.get("action", ""))
    target_ref = attempt.get("target_ref")
    venue_ref = cycle.get("venue_ref")
    superior_ref = cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref")
    operation_ref = cycle.get("operation_ref")
    coordination_ref = cycle.get("coordination_authority_ref")

    if action == "seek_contact":
        if target_ref not in {venue_ref, superior_ref}:
            return None
    elif action in {"ask", "request", "petition", "present", "report"}:
        if target_ref == superior_ref:
            # Person-targeted substantive speech is routable only when the saved
            # attempt itself proves an established co-located scene. A permitted
            # person ID or broad same-city location is never access.
            if not isinstance(attempt.get("scene_session_ref"), str) or not attempt.get("scene_session_ref"):
                return None
        elif target_ref not in {cycle.get("cycle_ref"), operation_ref, coordination_ref, venue_ref}:
            return None
    else:
        return None
    return cycle


def _settled_cycle_contact(planner: Any, cycle_ref: str) -> Mapping[str, Any] | None:
    for _event_ref, event in iter_causal_events_newest(planner, kinds={"audience_response"}):
        if not isinstance(event, Mapping):
            continue
        if event.get("route_domain") == "campaign_command_contact" and event.get("source_event_ref") == cycle_ref:
            return event
    return None


def _pending_cycle_contact(runtime: Mapping[str, Any], cycle_ref: str) -> Mapping[str, Any] | None:
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
            and isinstance(host.get("next_due"), str)
        ):
            return host
    return None


def _pending_request_host(runtime: Mapping[str, Any], cycle_ref: str) -> tuple[str, dict[str, Any]] | None:
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


def _operation_for_cycle(planner: Any, cycle: Mapping[str, Any]) -> Mapping[str, Any]:
    operation_ref = cycle.get("operation_ref")
    if not isinstance(operation_ref, str) or not operation_ref:
        raise ValueError("campaign command cycle lost operation authority")
    try:
        path = planner.owner_path(operation_ref)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise ValueError("campaign command operation owner is missing") from exc
    operation = planner.read(path)
    if not isinstance(operation, Mapping):
        raise ValueError("campaign command operation owner is invalid")
    return operation


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


def _response_for(planner: Any, cycle: Mapping[str, Any], topics: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    operation = _operation_for_cycle(planner, cycle)
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
            text = f"Headquarters confirms exact march order {order_ref}: {objective}"
            if follow_on:
                text += f" {follow_on}"
            parts.append(text[:2500])
        else:
            dispositions["march_orders"] = "no_executable_order"
            order_ref = str(order.get("order_ref", "current order")) if isinstance(order, Mapping) else "none"
            status = str(order.get("actionability_status") or order.get("status") or "not actionable") if isinstance(order, Mapping) else "not issued"
            parts.append(
                f"Headquarters confirms that {order_ref} is not a new executable march order in its current state ({status}). Staff planning does not itself move Tang Wei's army or authorize tactics."
            )
    if "vanguard" in topics:
        if _order_has_player_vanguard_assignment(operation, order):
            dispositions["vanguard"] = "already_assigned_by_exact_order"
            parts.append(
                "Headquarters confirms that Tang Wei's current exact campaign order/directive already carries the vanguard or advance-guard assignment; that exact owner, not this reply, is the assignment authority."
            )
        else:
            dispositions["vanguard"] = "not_granted_currently"
            parts.append(
                "Mou Gou's headquarters does not grant Tang Wei the vanguard or advance-guard lead through this request. His current exact campaign assignment remains controlling. Any later vanguard assignment requires a new exact campaign order or directive."
            )
    if not parts:
        raise ValueError("campaign command request produced no disposition")
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

        # Physical ledger order is the actual append order for same-timestamp
        # zero-time requests. Keep the newest substantive declaration per cycle.
        newest_by_cycle: dict[str, tuple[dict[str, Any], Mapping[str, Any], tuple[str, ...]]] = {}
        for attempt in reversed(_ledger_attempts(self)):
            topics = _request_topics(attempt)
            if not topics or isinstance(attempt.get("response_ref"), str):
                continue
            cycle = _cycle_for_attempt(self, attempt)
            if cycle is None:
                continue
            cycle_ref = str(cycle["cycle_ref"])
            if cycle_ref not in newest_by_cycle:
                newest_by_cycle[cycle_ref] = (attempt, cycle, topics)

        for cycle_ref, (attempt, cycle, topics) in newest_by_cycle.items():
            attempt_ref = str(attempt.get("event_id") or "")
            requested_at = attempt.get("at")
            if not attempt_ref or not isinstance(requested_at, str):
                continue
            if isinstance(get_causal_event_from_reader(self, campaign_command_request_response_ref(attempt_ref)), Mapping):
                continue

            due = max(current, CampaignTime.parse(requested_at).add_seconds(review_seconds))
            if attempt.get("action") == "seek_contact":
                settled_contact = _settled_cycle_contact(self, cycle_ref)
                pending_contact = _pending_cycle_contact(runtime, cycle_ref)
                if settled_contact is None and pending_contact is None:
                    # Substantive text embedded in seek_contact never skips the
                    # receiving stage. Missing routing is an audit defect, not
                    # permission to fabricate receipt.
                    continue
                if settled_contact is None and isinstance(pending_contact, Mapping):
                    contact_due = pending_contact.get("next_due")
                    if not isinstance(contact_due, str):
                        continue
                    due = max(due, CampaignTime.parse(contact_due).add_seconds(review_seconds))

            response_summary, dispositions = _response_for(self, cycle, topics)
            pending = _pending_request_host(runtime, cycle_ref)
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
                raise ValueError("campaign command request lost superior command")
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
]
