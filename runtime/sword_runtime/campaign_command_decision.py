"""Causal superior-command review after a player field phase completes.

Campaign headquarters already owns council cadence, upward reports, and delivery of
persisted superior orders. This module fills the missing middle of that chain:
player-known material command intelligence and explicit follow-on requests are
reported through the exact campaign cycle, the named superior reviews them once,
and a bounded mission-level follow-on order is persisted for the existing delivery
host. It never moves formations, invents hidden enemy truth, chooses Tang Wei's
tactics, or transfers ownership.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_command_cycle import _latest_order, _load_operation, _read_cycle
from sword_runtime.sim.calendar import CampaignTime


_PLAYER_REF = "char_tang_wei"
_RUNTIME_PATH = "state/runtime.json"
_INFO_INDEX = "state/information/index.json"
_ATTEMPT_LEDGER = "state/index/interaction-attempts.json"
_COMPLETED_ORDER_STATES = {"completed", "phase_complete_awaiting_follow_on_direction"}
_FOLLOW_ON_TOPIC_TERMS = (
    "follow_on_order",
    "follow-on order",
    "follow on order",
    "follow-on operational order",
    "follow on operational order",
    "next operational order",
    "next campaign order",
    "follow-on campaign order",
    "follow on campaign order",
)


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def _now(planner: Any) -> str | None:
    runtime = planner.read_optional(_RUNTIME_PATH)
    value = runtime.get("world_time") if isinstance(runtime, Mapping) else None
    return str(value) if isinstance(value, str) and value else None


def _known_command_intelligence(planner: Any, *, at: str) -> list[dict[str, Any]]:
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
            "source_ref": (holder or {}).get("source_ref") if isinstance(holder, Mapping) else claim.get("source_ref"),
            "provenance": claim.get("provenance"),
        })
    rows.sort(key=lambda row: (str(row.get("learned_at", "")), str(row.get("information_ref", ""))))
    return rows


def _follow_on_request_refs(planner: Any, *, cycle: Mapping[str, Any]) -> list[str]:
    ledger = planner.read_optional(_ATTEMPT_LEDGER)
    rows = ledger.get("attempts", []) if isinstance(ledger, Mapping) else []
    cycle_ref = str(cycle.get("cycle_ref") or "")
    operation_ref = str(cycle.get("operation_ref") or "")
    venue_ref = str(cycle.get("venue_ref") or "")
    refs: list[str] = []
    for row in rows[-256:] if isinstance(rows, list) else []:
        if not isinstance(row, Mapping) or row.get("actor_id") != _PLAYER_REF:
            continue
        if str(row.get("action", "")) not in {"ask", "request", "petition", "report", "present", "seek_contact"}:
            continue
        target = str(row.get("target_ref") or "")
        process = str(row.get("process_ref") or "")
        if target not in {cycle_ref, operation_ref, venue_ref} and process not in {cycle_ref, operation_ref}:
            continue
        text = " ".join(str(row.get(key) or "").lower() for key in ("topic", "player_statement", "posture"))
        if not any(term in text for term in _FOLLOW_ON_TOPIC_TERMS):
            continue
        attempt_ref = row.get("event_id")
        if isinstance(attempt_ref, str) and attempt_ref:
            refs.append(attempt_ref)
    return list(dict.fromkeys(refs))


def _report_new_intelligence(
    cycle: dict[str, Any], *, at: str, intelligence: list[dict[str, Any]], request_refs: list[str]
) -> tuple[list[str], list[str]]:
    reported = [
        str(ref) for ref in cycle.get("reported_command_information_refs", [])
        if isinstance(ref, str) and ref
    ]
    reported_requests = [
        str(ref) for ref in cycle.get("reported_follow_on_request_refs", [])
        if isinstance(ref, str) and ref
    ]
    new_info = [row for row in intelligence if str(row.get("information_ref", "")) not in set(reported)]
    new_requests = [ref for ref in request_refs if ref not in set(reported_requests)]
    if not new_info and not new_requests:
        return [], []

    upward = cycle.get("upward_reports") if isinstance(cycle.get("upward_reports"), list) else []
    info_refs = [str(row["information_ref"]) for row in new_info if isinstance(row.get("information_ref"), str)]
    report_ref = f"campaign_command_material_report.{_digest('material-report', str(cycle.get('cycle_ref')) + '|' + '|'.join(info_refs + new_requests))}"
    upward.append({
        "report_ref": report_ref,
        "reported_at": at,
        "phase": "material_intelligence",
        "from_ref": _PLAYER_REF,
        "to_ref": cycle.get("superior_command_ref"),
        "information_refs": info_refs,
        "follow_on_request_refs": new_requests,
        "information": copy.deepcopy(new_info),
        "rule": (
            "This report forwards only command intelligence already known to Tang Wei and explicit saved player requests. "
            "It creates no enemy truth, movement, tactical choice, or command outcome."
        ),
    })
    cycle["upward_reports"] = upward[-48:]
    cycle["reported_command_information_refs"] = list(dict.fromkeys(reported + info_refs))[-128:]
    cycle["reported_follow_on_request_refs"] = list(dict.fromkeys(reported_requests + new_requests))[-128:]
    return info_refs, new_requests


def _order_is_complete(operation: Mapping[str, Any], order: Mapping[str, Any] | None) -> bool:
    if not isinstance(order, Mapping):
        return False
    if str(order.get("actionability_status", "")) == "completed":
        return True
    if str(order.get("status", "")) in _COMPLETED_ORDER_STATES:
        return True
    return str(operation.get("order_status", "")) in _COMPLETED_ORDER_STATES


def _mission_order(
    operation: Mapping[str, Any], cycle: Mapping[str, Any], base_order: Mapping[str, Any], *,
    at: str, information_refs: list[str], request_refs: list[str], signature: str,
) -> dict[str, Any]:
    packet = base_order.get("mission_packet") if isinstance(base_order.get("mission_packet"), Mapping) else {}
    strategic_ref = (
        operation.get("strategic_target_ref")
        or packet.get("strategic_target_ref")
        or operation.get("operational_area_ref")
        or operation.get("location_ref")
    )
    strategic_name = packet.get("strategic_target_name") or strategic_ref or "the current campaign axis"
    anchor_ref = operation.get("location_ref") or packet.get("destination_ref") or strategic_ref
    anchor_name = packet.get("destination_name") or anchor_ref or strategic_name
    mission_packet = copy.deepcopy(dict(packet))
    mission_packet.update({
        "mission_phase": "contact_development",
        "phase_status": "ready_for_commander_execution",
        "source_order_ref": base_order.get("order_ref"),
        "source_information_refs": list(information_refs),
        "source_follow_on_request_refs": list(request_refs),
        "strategic_target_ref": strategic_ref,
        "field_command_anchor_ref": anchor_ref,
        "decision_scope": "mission_level_follow_on_only",
        "agency_rule": (
            "Superior command sets the mission and reporting requirement only. Tang Wei retains the exact route, formation assignment, "
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
            f"Develop contact with the reported enemy formations affecting the {strategic_name} axis while maintaining {anchor_name} "
            "as the field-command anchor; preserve campaign coordination and report material changes."
        ),
        "follow_on_requirement": (
            "Execute this mission within current campaign authority. Exact march sequence, formation use, reconnaissance depth, "
            "and battle tactics remain Tang Wei's decisions; report confirmed contact or another material change to superior command."
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
            "This follow-on order is issued through the existing campaign superior-command chain. It neither transfers ownership nor "
            "commits excluded private auxiliaries, moves formations automatically, chooses tactics, or creates battle contact."
        ),
    }


def sync_campaign_command_decisions(planner: Any) -> list[str]:
    """Forward material player-known intelligence and issue one bounded follow-on mission when due."""
    at = _now(planner)
    if at is None:
        return []
    created: list[str] = []
    intelligence = _known_command_intelligence(planner, at=at)

    player = planner.read_optional("state/player.json")
    appointments = ((player or {}).get("career_state") or {}).get("appointments", []) if isinstance(player, Mapping) else []
    operation_refs = [
        str(row.get("operation_ref")) for row in appointments
        if isinstance(row, Mapping)
        and row.get("status") == "active"
        and row.get("kind") in {"qin_field_command", "state_field_command"}
        and isinstance(row.get("operation_ref"), str)
    ] if isinstance(appointments, list) else []
    if not operation_refs:
        try:
            root = planner.read("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
        except (FileNotFoundError, KeyError, ValueError):
            root = None
        active = root.get("active_context_ref") if isinstance(root, Mapping) else None
        if isinstance(active, str) and active:
            operation_refs = [active]

    for operation_ref in dict.fromkeys(operation_refs):
        existing = _read_cycle(planner, operation_ref)
        if existing is None:
            continue
        cycle_path, cycle = existing
        if str((cycle.get("war_council") or {}).get("status", "")) != "held":
            continue
        if not isinstance(cycle.get("supreme_commander_ref") or cycle.get("superior_command_ref"), str):
            continue
        op_path, operation = _load_operation(planner, operation_ref)
        base_order = _latest_order(operation)
        if not isinstance(base_order, Mapping):
            continue

        request_refs = _follow_on_request_refs(planner, cycle=cycle)
        new_info_refs, new_request_refs = _report_new_intelligence(
            cycle, at=at, intelligence=intelligence, request_refs=request_refs,
        )
        cycle["updated_at"] = at
        planner.put(cycle_path, cycle)

        if not _order_is_complete(operation, base_order):
            continue
        reported_info = [str(ref) for ref in cycle.get("reported_command_information_refs", []) if isinstance(ref, str)]
        reported_requests = [str(ref) for ref in cycle.get("reported_follow_on_request_refs", []) if isinstance(ref, str)]
        if not reported_info and not reported_requests:
            continue

        basis = {
            "operation_ref": operation_ref,
            "base_order_ref": base_order.get("order_ref"),
            "information_refs": reported_info,
            "request_refs": reported_requests,
            "phase": operation.get("campaign_phase") or operation.get("order_status"),
        }
        signature = _digest("campaign-decision", json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        decision_refs = [str(ref) for ref in cycle.get("campaign_command_decision_refs", []) if isinstance(ref, str)]
        decision_ref = f"campaign_command_decision.{signature}"
        if decision_ref in set(decision_refs):
            continue
        order_ref = f"operational_order_{signature}"
        orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
        if any(isinstance(row, Mapping) and str(row.get("order_ref", "")) == order_ref for row in orders):
            operation["last_operational_order_ref"] = order_ref
            planner.put(op_path, operation)
            continue

        order = _mission_order(
            operation, cycle, base_order, at=at,
            information_refs=reported_info, request_refs=reported_requests, signature=signature,
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
            "superior_command_ref": cycle.get("superior_command_ref"),
            "order_ref": order_ref,
            "base_order_ref": base_order.get("order_ref"),
            "information_refs": reported_info,
            "follow_on_request_refs": reported_requests,
            "new_information_refs": new_info_refs,
            "new_follow_on_request_refs": new_request_refs,
        })
        cycle["campaign_command_decisions"] = decisions[-32:]
        cycle["campaign_command_decision_refs"] = list(dict.fromkeys(decision_refs + [decision_ref]))[-64:]
        cycle["current_superior_order"] = copy.deepcopy(order)
        cycle["updated_at"] = at
        planner.put(cycle_path, cycle)
        created.append(order_ref)
    return created


class CampaignCommandDecisionMixin:
    """Hosted composition hook for the one campaign-command decision owner."""

    def _sync_campaign_command_decisions(self) -> list[str]:
        return sync_campaign_command_decisions(self)


__all__ = ["CampaignCommandDecisionMixin", "sync_campaign_command_decisions"]
