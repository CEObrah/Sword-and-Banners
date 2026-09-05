"""Campaign superior-review lifecycle for completed field phases.

The campaign cycle already owns councils, daily headquarters cadence, and delivery
of persisted superior orders. This module owns the missing middle: material
command intelligence already known to Tang Wei is forwarded upward, explicit
follow-on requests travel in the same upward command report, and the named
superior may persist one bounded mission-level follow-on order. No hidden enemy
truth is read and no formation is moved, reassigned, or committed to battle here.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_command_cycle import _latest_order, _load_operation, _read_cycle, _reader
from sword_runtime.campaign_communications import (
    command_message_route,
    command_person_location,
    player_command_location,
    queue_upward_report,
)
from sword_runtime.campaign_command_requests import campaign_command_request_response_ref
from sword_runtime.causal_event_store import get_causal_event_from_reader
from sword_runtime.sim.calendar import CampaignTime


_PLAYER_REF = "char_tang_wei"
_RUNTIME_PATH = "state/runtime.json"
_INFO_INDEX = "state/information/index.json"
_ATTEMPT_LEDGER = "state/index/interaction-attempts.json"
_REQUEST_PRIORITY = 48
_COMPLETED_ORDER_STATES = {"completed", "phase_complete_awaiting_follow_on_direction"}
_CLOSED_CYCLE_STATUSES = {"closed", "completed", "cancelled", "inactive"}
_FOLLOW_ON_TERMS = (
    "follow_on_order", "follow-on order", "follow on order",
    "follow-on operational order", "follow on operational order",
    "next operational order", "next campaign order",
    "follow-on campaign order", "follow on campaign order",
    "follow_on_direction", "follow-on direction", "follow on direction",
    "next_objective", "next objective", "next mission",
)


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def _now(planner: Any) -> str | None:
    runtime = planner.read_optional(_RUNTIME_PATH)
    value = runtime.get("world_time") if isinstance(runtime, Mapping) else None
    return str(value) if isinstance(value, str) and value else None


def _known_command_intelligence(planner: Any, *, at: str) -> list[dict[str, Any]]:
    """Return only command intelligence already held by Tang Wei by ``at``."""
    index = planner.read_optional(_INFO_INDEX)
    if not isinstance(index, Mapping):
        return []
    by_holder = index.get("by_holder") if isinstance(index.get("by_holder"), Mapping) else {}
    claims = index.get("claims") if isinstance(index.get("claims"), Mapping) else {}
    refs = by_holder.get(_PLAYER_REF, []) if isinstance(by_holder, Mapping) else []
    now = CampaignTime.parse(at)
    rows: list[dict[str, Any]] = []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, str):
            continue
        path = claims.get(ref) if isinstance(claims, Mapping) else None
        if not isinstance(path, str):
            continue
        claim = planner.read_optional(path)
        if not isinstance(claim, Mapping) or str(claim.get("classification", "")) != "command_intelligence":
            continue
        holders = claim.get("holder_states") if isinstance(claim.get("holder_states"), Mapping) else {}
        holder = holders.get(_PLAYER_REF) if isinstance(holders, Mapping) else None
        learned_at = holder.get("learned_at") if isinstance(holder, Mapping) else None
        if not isinstance(learned_at, str) or CampaignTime.parse(learned_at) > now:
            continue
        rows.append({
            "information_ref": ref,
            "learned_at": learned_at,
            "subject_ref": claim.get("subject_ref"),
            "claim": claim.get("claim") or claim.get("fact"),
            "confidence_milli": claim.get("confidence_milli"),
            "source_ref": holder.get("source_ref") if isinstance(holder, Mapping) else claim.get("source_ref"),
            "provenance": claim.get("provenance"),
        })
    rows.sort(key=lambda row: (str(row.get("learned_at", "")), str(row.get("information_ref", ""))))
    return rows


def _attempt_rows(planner: Any) -> list[dict[str, Any]]:
    ledger = planner.read_optional(_ATTEMPT_LEDGER)
    rows = ledger.get("attempts", []) if isinstance(ledger, Mapping) else []
    return [copy.deepcopy(dict(row)) for row in rows[-256:] if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _is_follow_on_request(row: Mapping[str, Any]) -> bool:
    """Return whether one interaction explicitly expects a campaign follow-on answer."""
    if row.get("actor_id") != _PLAYER_REF:
        return False
    if "expects_response" in row and row.get("expects_response") is not True:
        return False
    if str(row.get("action", "")) not in {"ask", "request", "petition", "report", "present", "seek_contact"}:
        return False
    text = " ".join(str(row.get(key) or "").lower() for key in ("topic", "player_statement", "posture"))
    return any(term in text for term in _FOLLOW_ON_TERMS)


def _valid_cycle(cycle: object) -> Mapping[str, Any] | None:
    if not isinstance(cycle, Mapping):
        return None
    if cycle.get("kind") != "campaign_command_cycle":
        return None
    if str(cycle.get("status", "")).lower() in _CLOSED_CYCLE_STATUSES:
        return None
    participants = cycle.get("participant_commander_refs")
    if not isinstance(participants, list) or _PLAYER_REF not in participants:
        return None
    cycle_ref = cycle.get("cycle_ref")
    operation_ref = cycle.get("operation_ref")
    if not isinstance(cycle_ref, str) or not cycle_ref or not isinstance(operation_ref, str) or not operation_ref:
        return None
    return cycle


def _cycle_from_route_ref(planner: Any, ref: object) -> Mapping[str, Any] | None:
    if not isinstance(ref, str) or not ref:
        return None
    if ref.startswith("campaign_command_cycle."):
        try:
            path = planner.owner_path(ref)
        except (KeyError, FileNotFoundError, ValueError):
            return None
        return _valid_cycle(planner.read_optional(path))
    existing = _read_cycle(planner, ref)
    return _valid_cycle(existing[1]) if existing is not None else None


def _active_field_cycle(planner: Any) -> Mapping[str, Any] | None:
    try:
        root = planner.read_optional("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    except (FileNotFoundError, KeyError, ValueError):
        return None
    operation_ref = root.get("active_context_ref") if isinstance(root, Mapping) else None
    return _cycle_from_route_ref(planner, operation_ref)


def campaign_command_follow_on_route(
    source: Any,
    attempt: Mapping[str, Any],
    *,
    cycle: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve one follow-on request to the exact physical superior-command route."""
    if not _is_follow_on_request(attempt):
        return None
    planner = _reader(source)
    resolved = _valid_cycle(cycle)
    if resolved is None:
        for ref in (attempt.get("process_ref"), attempt.get("target_ref")):
            resolved = _cycle_from_route_ref(planner, ref)
            if resolved is not None:
                break
    if resolved is None:
        resolved = _active_field_cycle(planner)
    if resolved is None:
        return None

    cycle_ref = str(resolved.get("cycle_ref") or "")
    operation_ref = str(resolved.get("operation_ref") or "")
    venue_ref = str(resolved.get("venue_ref") or "")
    coordination_ref = str(resolved.get("coordination_authority_ref") or "")
    target_ref = str(attempt.get("target_ref") or "")
    process_ref = str(attempt.get("process_ref") or "")
    channel_targets = {ref for ref in (cycle_ref, operation_ref, venue_ref, coordination_ref) if ref}
    if target_ref not in channel_targets:
        return None
    if process_ref and process_ref not in {cycle_ref, operation_ref}:
        return None

    superior_ref = resolved.get("superior_command_ref") or resolved.get("supreme_commander_ref")
    if not isinstance(superior_ref, str) or not superior_ref:
        return None
    target_location = command_person_location(planner, superior_ref)
    if not target_location:
        return None
    request_origin = attempt.get("origin_location_ref")
    if not isinstance(request_origin, str) or not request_origin:
        request_origin = player_command_location(planner)
    if not isinstance(request_origin, str) or not request_origin:
        return None
    try:
        courier_route = command_message_route(planner.read, request_origin, target_location, round_trip=True)
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None

    return {
        "cycle_ref": cycle_ref,
        "operation_ref": operation_ref,
        "superior_ref": superior_ref,
        "request_origin_location_ref": request_origin,
        "target_location_ref": target_location,
        "courier_route": copy.deepcopy(dict(courier_route)),
    }


def _requests_for_cycle(planner: Any, cycle: Mapping[str, Any]) -> list[dict[str, Any]]:
    cycle_ref = str(cycle.get("cycle_ref") or "")
    values: list[dict[str, Any]] = []
    for row in _attempt_rows(planner):
        route = campaign_command_follow_on_route(planner, row, cycle=cycle)
        if route is not None and route.get("cycle_ref") == cycle_ref:
            values.append(row)
    return values


def _report_material_inputs(
    planner: Any, cycle: dict[str, Any], *, at: str, intelligence: list[dict[str, Any]], requests: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    delivered_info = {str(ref) for ref in cycle.get("reported_command_information_refs", []) if isinstance(ref, str)}
    delivered_requests = {str(ref) for ref in cycle.get("reported_follow_on_request_refs", []) if isinstance(ref, str)}
    queued_info: set[str] = set()
    queued_requests: set[str] = set()
    for report in cycle.get("upward_reports", []) if isinstance(cycle.get("upward_reports"), list) else []:
        if not isinstance(report, Mapping):
            continue
        queued_info.update(str(ref) for ref in report.get("information_refs", []) if isinstance(ref, str))
        queued_requests.update(str(ref) for ref in report.get("follow_on_request_refs", []) if isinstance(ref, str))
    new_info = [row for row in intelligence if str(row.get("information_ref", "")) not in delivered_info | queued_info]
    request_refs = [str(row.get("event_id")) for row in requests if isinstance(row.get("event_id"), str)]
    new_request_refs = [ref for ref in request_refs if ref not in delivered_requests | queued_requests]
    if not new_info and not new_request_refs:
        return [], []

    info_refs = [str(row["information_ref"]) for row in new_info if isinstance(row.get("information_ref"), str)]
    material = info_refs + new_request_refs
    player = planner.read_optional("state/player.json")
    source_location = ""
    if isinstance(player, Mapping):
        source_location = str(player.get("location") or player.get("current_location") or player.get("location_ref") or "")
    queue_upward_report(
        planner, cycle, at=at, phase="material_intelligence", source_location_ref=source_location,
        payload={
            "report_ref": f"campaign_command_material_report.{_digest('material-report', str(cycle.get('cycle_ref')) + '|' + '|'.join(material))}",
            "information_refs": info_refs,
            "follow_on_request_refs": new_request_refs,
            "information": copy.deepcopy(new_info),
            "rule": (
                "Only saved information already held by Tang Wei and exact saved player requests are prepared for forwarding. "
                "Superior command may use them only after the shared physical command-message route marks this report delivered."
            ),
        },
    )
    return info_refs, new_request_refs


def _request_is_causally_received(
    planner: Any,
    row: Mapping[str, Any],
    cycle: Mapping[str, Any] | None = None,
) -> bool:
    """Return whether superior command has physically received this request.

    Current authority is the delivered upward campaign report. Historical generic
    follow-up responses remain a compatibility route for old saves only.
    """
    attempt_ref = row.get("event_id")
    if not isinstance(attempt_ref, str) or not attempt_ref:
        return False
    if isinstance(cycle, Mapping):
        delivered = {
            str(ref) for ref in cycle.get("reported_follow_on_request_refs", [])
            if isinstance(ref, str) and ref
        }
        if attempt_ref in delivered:
            return True
    response_ref = row.get("response_ref")
    if isinstance(response_ref, str) and response_ref:
        return True
    return isinstance(
        get_causal_event_from_reader(planner, campaign_command_request_response_ref(attempt_ref)),
        Mapping,
    )


def _order_is_complete(operation: Mapping[str, Any], order: Mapping[str, Any] | None) -> bool:
    if not isinstance(order, Mapping):
        return False
    return bool(
        str(order.get("actionability_status", "")) == "completed"
        or str(order.get("status", "")) in _COMPLETED_ORDER_STATES
        or str(operation.get("order_status", "")) in _COMPLETED_ORDER_STATES
    )


def _mission_order(
    operation: Mapping[str, Any], cycle: Mapping[str, Any], base_order: Mapping[str, Any], *,
    at: str, information_refs: list[str], request_refs: list[str], signature: str,
) -> dict[str, Any]:
    packet = base_order.get("mission_packet") if isinstance(base_order.get("mission_packet"), Mapping) else {}
    strategic_ref = operation.get("strategic_target_ref") or packet.get("strategic_target_ref") or operation.get("operational_area_ref") or operation.get("location_ref")
    strategic_name = packet.get("strategic_target_name") or strategic_ref or "the current campaign axis"
    anchor_ref = operation.get("location_ref") or packet.get("destination_ref") or strategic_ref
    anchor_name = packet.get("destination_name") or anchor_ref or strategic_name
    mission_packet = copy.deepcopy(dict(packet))
    mission_packet.update({
        "mission_phase": "contact_development",
        "operational_intent": "develop_contact",
        "battle_commitment_authorized": False,
        "independent_detachment": False,
        "contact_goal": "locate_confirm_observe_and_report_enemy_disposition",
        "phase_status": "ready_for_commander_execution",
        "source_order_ref": base_order.get("order_ref"),
        "source_information_refs": list(information_refs),
        "source_follow_on_request_refs": list(request_refs),
        "strategic_target_ref": strategic_ref,
        "field_command_anchor_ref": anchor_ref,
        "decision_scope": "mission_level_follow_on_only",
        "support_continuity_rule": (
            "This field command remains a supported component of the wider campaign unless an exact later order detaches it. "
            "Developing contact does not make the parent army disappear and does not itself authorize a general attack."
        ),
        "agency_rule": (
            "Superior command sets mission and reporting scope only. Tang Wei retains exact route, formation assignment, "
            "reconnaissance depth, reserve posture, battle commitment, and tactics unless a later exact lawful order states otherwise."
        ),
    })
    return {
        "order_ref": f"operational_order_{signature}",
        "order_kind": "campaign_command_follow_on_mission",
        "source_order_ref": base_order.get("order_ref"),
        "issued_at": at,
        "issuer_ref": base_order.get("issuer_ref") or operation.get("institutional_owner_ref") or "state_qin",
        "superior_commander_ref": cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref"),
        "coordination_authority_ref": cycle.get("coordination_authority_ref"),
        "status": "staff_briefed_awaiting_commander_execution",
        "actionability_status": "actionable",
        "objective": (
            f"Locate, confirm, observe, and report the enemy formations affecting the {strategic_name} axis while maintaining {anchor_name} "
            "as the field-command anchor. Develop tactical contact without treating contact itself as a general-attack order; preserve campaign coordination and report material changes."
        ),
        "follow_on_requirement": (
            "Execute this contact-development mission within current campaign authority. Exact march sequence, formation use, reconnaissance depth, "
            "and local self-defense remain Tang Wei's decisions. Deliberate general battle commitment is not contained in this order; report confirmed contact or another material change to superior command."
        ),
        "mission_packet": mission_packet,
        "applies_to_formation_refs": copy.deepcopy(base_order.get("applies_to_formation_refs", [])),
        "excluded_non_state_formation_refs": copy.deepcopy(base_order.get("excluded_non_state_formation_refs", [])),
        "decision_basis": {
            "information_refs": list(information_refs),
            "follow_on_request_refs": list(request_refs),
            "base_order_ref": base_order.get("order_ref"),
        },
        "authority_rule": (
            "The order uses only existing campaign authority. It does not transfer ownership, compel excluded private auxiliaries, "
            "move formations automatically, choose tactics, or create battle contact."
        ),
    }


def sync_campaign_command_decisions(planner: Any) -> list[str]:
    """Forward material inputs and persist one deduplicated superior follow-on mission when warranted."""
    at = _now(planner)
    if at is None:
        return []
    intelligence = _known_command_intelligence(planner, at=at)
    try:
        root = planner.read("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    except (FileNotFoundError, KeyError, ValueError):
        return []
    operation_ref = root.get("active_context_ref") if isinstance(root, Mapping) else None
    if not isinstance(operation_ref, str) or not operation_ref:
        return []
    existing = _read_cycle(planner, operation_ref)
    if existing is None:
        return []
    cycle_path, cycle = existing
    if str((cycle.get("war_council") or {}).get("status", "")) != "held":
        return []
    superior = cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref")
    if not isinstance(superior, str) or not superior:
        return []

    op_path, operation = _load_operation(planner, operation_ref)
    base_order = _latest_order(operation)
    if not isinstance(base_order, Mapping):
        return []
    requests = _requests_for_cycle(planner, cycle)
    new_info_refs, new_request_refs = _report_material_inputs(planner, cycle, at=at, intelligence=intelligence, requests=requests)
    cycle["updated_at"] = at
    planner.put(cycle_path, cycle)
    if not _order_is_complete(operation, base_order):
        return []

    reported_info = [str(ref) for ref in cycle.get("reported_command_information_refs", []) if isinstance(ref, str)]
    received_request_refs = [
        str(row.get("event_id")) for row in requests
        if isinstance(row.get("event_id"), str) and _request_is_causally_received(planner, row, cycle)
    ]
    if not reported_info and not received_request_refs:
        return []

    basis = {
        "operation_ref": operation_ref,
        "base_order_ref": base_order.get("order_ref"),
        "information_refs": reported_info,
        "received_request_refs": received_request_refs,
        "phase": operation.get("campaign_phase") or operation.get("order_status"),
    }
    signature = _digest("campaign-decision", json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    decision_ref = f"campaign_command_decision.{signature}"
    decision_refs = [str(ref) for ref in cycle.get("campaign_command_decision_refs", []) if isinstance(ref, str)]
    if decision_ref in set(decision_refs):
        return []
    order_ref = f"operational_order_{signature}"
    orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
    if any(isinstance(row, Mapping) and str(row.get("order_ref", "")) == order_ref for row in orders):
        return []

    prior_operation_state = {
        "last_operational_order_ref": operation.get("last_operational_order_ref"),
        "order_status": operation.get("order_status"),
        "campaign_phase": operation.get("campaign_phase"),
    }
    order = _mission_order(
        operation, cycle, base_order, at=at,
        information_refs=reported_info, request_refs=received_request_refs, signature=signature,
    )
    orders.append(order)
    operation["operational_orders"] = orders
    operation["last_operational_order_ref"] = order_ref
    operation["order_status"] = "staff_briefed_awaiting_commander_execution"
    operation["campaign_phase"] = "contact_development"
    planner.put(op_path, operation)

    decisions = cycle.get("campaign_command_decisions") if isinstance(cycle.get("campaign_command_decisions"), list) else []
    decisions.append({
        "decision_ref": decision_ref,
        "decided_at": at,
        "superior_command_ref": superior,
        "order_ref": order_ref,
        "base_order_ref": base_order.get("order_ref"),
        "information_refs": reported_info,
        "follow_on_request_refs": received_request_refs,
        "new_information_refs": new_info_refs,
        "new_follow_on_request_refs": new_request_refs,
        "prior_operation_state": prior_operation_state,
    })
    cycle["campaign_command_decisions"] = decisions[-32:]
    cycle["campaign_command_decision_refs"] = list(dict.fromkeys(decision_refs + [decision_ref]))[-64:]
    cycle["current_superior_order"] = copy.deepcopy(order)
    cycle["updated_at"] = at
    planner.put(cycle_path, cycle)
    return [order_ref]


def _route_follow_on_requests(planner: Any, runtime: dict[str, Any]) -> None:
    """Legacy parallel review route retained for compatibility tests/old saves.

    Production composition retires these hosts in the same reconciliation pass;
    current requests travel upward in the ordinary campaign report and current
    decision orders return through ``campaign_command_superior_order`` delivery.
    """
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    current_text = runtime.get("world_time")
    if not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(current_text, str):
        raise ValueError("runtime causal queue is invalid")
    current = CampaignTime.parse(current_text)
    mechanics = planner.read("game/data/mechanics/campaign-command.json")
    section = mechanics.get("campaign_command_cycle") if isinstance(mechanics, Mapping) else {}
    delay_minutes = section.get("superior_request_response_delay_minutes", 15) if isinstance(section, Mapping) else 15
    if isinstance(delay_minutes, bool) or not isinstance(delay_minutes, int) or delay_minutes <= 0:
        raise ValueError("campaign superior request response delay is invalid")

    try:
        root = planner.read("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    except (FileNotFoundError, KeyError, ValueError):
        return
    operation_ref = root.get("active_context_ref") if isinstance(root, Mapping) else None
    if not isinstance(operation_ref, str) or not operation_ref:
        return
    existing = _read_cycle(planner, operation_ref)
    if existing is None:
        return
    _cycle_path, cycle = existing
    cycle_ref = str(cycle.get("cycle_ref") or "")
    superior = cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref")
    if not cycle_ref or not isinstance(superior, str) or not superior:
        return

    existing_by_attempt = {
        str(host.get("source_interaction_attempt_ref")): (host_id, host)
        for host_id, host in hosts.items()
        if isinstance(host_id, str) and isinstance(host, dict)
        and host.get("kind") == "institutional_followup"
        and host.get("route_domain") == "campaign_command_follow_on_review"
        and host.get("campaign_command_cycle_ref") == cycle_ref
        and isinstance(host.get("source_interaction_attempt_ref"), str)
    }

    for attempt in reversed(_requests_for_cycle(planner, cycle)):
        route = campaign_command_follow_on_route(planner, attempt, cycle=cycle)
        if route is None:
            continue
        attempt_ref = attempt.get("event_id")
        if not isinstance(attempt_ref, str) or not attempt_ref or isinstance(attempt.get("response_ref"), str):
            continue
        if isinstance(get_causal_event_from_reader(planner, campaign_command_request_response_ref(attempt_ref)), Mapping):
            continue
        requested_at = attempt.get("at")
        if not isinstance(requested_at, str):
            continue
        request_origin = str(route["request_origin_location_ref"])
        target_location = str(route["target_location_ref"])
        courier_route = copy.deepcopy(dict(route["courier_route"]))
        travel_seconds = max(0, int(courier_route.get("travel_seconds", 0) or 0))
        staff_seconds = delay_minutes * 60
        due = max(current, CampaignTime.parse(requested_at).add_seconds(travel_seconds + staff_seconds))
        summary = (
            "Campaign headquarters receives Tang Wei's request for a follow-on operational order and places the completed field phase "
            "and current reported command intelligence before superior command for review. Any binding order will arrive separately "
            "through the superior-order channel."
        )
        common = {
            "contact_ref": attempt_ref,
            "source_interaction_attempt_ref": attempt_ref,
            "source_event_id": attempt_ref,
            "source_process_ref": cycle_ref,
            "source_owner_ref": cycle_ref,
            "actor_ref": superior,
            "response_summary": summary,
            "response_stage": "campaign_command_follow_on_review_received",
            "request_topics": ["follow_on_order"],
            "request_dispositions": {"follow_on_order": "under_superior_review"},
            "requested_statement": str(attempt.get("player_statement") or "")[:2000],
            "request_origin_location_ref": request_origin,
            "source_location_ref": request_origin,
            "target_location_ref": target_location,
            "response_target_location_ref": request_origin,
            "communication_travel_seconds": travel_seconds,
            "courier_route": courier_route,
            "communication_rule": "request dispatch is not headquarters receipt; reply delivery is not player receipt until the physical return route settles",
            "delivery_route": (
                f"physical courier {request_origin} -> {target_location} -> {request_origin}; superior headquarters staff review follows receipt"
                if travel_seconds > 0 else
                "co-located superior headquarters staff review; no courier travel required"
            ),
        }
        prior = existing_by_attempt.get(attempt_ref)
        if prior is not None:
            host_id, host = prior
            old_due = CampaignTime.parse(str(host.get("next_due") or due))
            final_due = due if due > old_due else old_due
            host.update({**common, "next_due": str(final_due), "safe_through": str(final_due.add_seconds(-1))})
            for event in events:
                if isinstance(event, dict) and event.get("target_host") == host_id:
                    event["due_at"] = str(final_due)
            continue

        token = _digest("follow-on-request", attempt_ref)
        host_id = f"host_campaign_command_follow_on_{token}"
        event_id = f"event_campaign_command_follow_on_due_{token}"
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "institutional_followup",
            "event_id": event_id,
            "owner_ref": cycle_ref,
            "route_domain": "campaign_command_follow_on_review",
            "campaign_command_cycle_ref": cycle_ref,
            "operation_ref": operation_ref,
            **common,
            "recurrence_seconds": 0,
            "next_due": str(due),
            "resolved_through": str(current if current < due else due.add_seconds(-1)),
            "safe_through": str(due.add_seconds(-1)),
        }
        events.append({
            "event_id": event_id,
            "kind": "institutional_followup",
            "priority": _REQUEST_PRIORITY,
            "target_host": host_id,
            "due_at": str(due),
        })
        existing_by_attempt[attempt_ref] = (host_id, hosts[host_id])


class CampaignCommandDecisionMixin:
    """Hosted composition hook for superior review and follow-on request routing."""

    def _sync_campaign_command_decisions(self) -> list[str]:
        return sync_campaign_command_decisions(self)

    def _sync_contact_request_routes(self, runtime: dict[str, Any]) -> None:
        super()._sync_contact_request_routes(runtime)
        _route_follow_on_requests(self, runtime)


__all__ = [
    "CampaignCommandDecisionMixin",
    "campaign_command_follow_on_route",
    "sync_campaign_command_decisions",
]
