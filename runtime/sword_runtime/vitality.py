"""Read-only player-facing causal-throughput diagnostics.

The simulation can be mechanically healthy while still producing stale play if
active pressures have no lawful progression route or already-established facts
never reach the player. This module diagnoses that condition without creating
story, scheduling events, or mutating campaign truth.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.world_arc_report_handoff import source_has_player_safe_world_arc_report
from sword_runtime.world_arcs import _visibility as _world_arc_visibility


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_json(store: Any, path: str) -> Mapping[str, Any]:
    try:
        return _mapping(store.read_json(path))
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError):
        return {}


def _awaiting_qin_command_without_receiving_path(
    player: Mapping[str, Any], hosts: Mapping[str, Any], causal_head: Mapping[str, Any]
) -> int:
    location_ref = player.get("location")
    career = _mapping(player.get("career_state"))
    appointments = career.get("appointments", [])
    if not isinstance(location_ref, str) or not isinstance(appointments, list):
        return 0
    blocked = 0
    for appointment in appointments:
        if not isinstance(appointment, Mapping):
            continue
        if appointment.get("kind") != "qin_field_command" or appointment.get("state_ref") != "state_qin":
            continue
        if appointment.get("status") != "awaiting_assumption" or appointment.get("report_to_location_ref") != location_ref:
            continue
        office = str(appointment.get("office", ""))
        source_ref = str(appointment.get("source_event_ref", ""))
        has_host = any(
            isinstance(host, Mapping)
            and host.get("kind") in {"qin_command_receiving", "qin_command_assumption"}
            and host.get("next_due") is not None
            and (
                (office and host.get("appointment_office") == office)
                or (source_ref and host.get("source_event_ref") == source_ref)
            )
            for host in hosts.values()
        )
        has_receiver = any(
            isinstance(event, Mapping)
            and event.get("process_kind") == "qin_field_command_assumption"
            and event.get("process_stage") == "receiver_ready"
            and (
                (office and event.get("appointment_office") == office)
                or (source_ref and event.get("source_event_ref") == source_ref)
            )
            for event in causal_head.values()
        )
        if not has_host and not has_receiver:
            blocked += 1
    return blocked


def summarize_playability_vitality(store: Any) -> dict[str, Any]:
    meta = _mapping(store.read_json("state/meta.json"))
    runtime = _mapping(store.read_json("state/runtime.json"))
    arcs = _mapping(store.read_json("state/arc/kingdom-arcs.json"))
    events = _mapping(store.read_json("state/event/events-messages-and-movement.json"))
    information = _mapping(store.read_json("state/information/index.json"))
    scene = _mapping(store.read_json("state/scene.json"))
    process_routes = _mapping(store.read_json("state/index/institutional-process-routing.json"))
    player = _optional_json(store, "state/player.json")

    active_arcs = 0
    active_visible_arcs = 0
    for row in arcs.get("records", []):
        facts = _mapping(row.get("facts")) if isinstance(row, Mapping) else {}
        status = str(facts.get("status", "")).lower()
        if status.startswith("active"):
            active_arcs += 1
            visibility, route = _world_arc_visibility(row)
            if visibility in {"discoverable", "direct"} and isinstance(route, str) and route:
                active_visible_arcs += 1

    hosts = _mapping(runtime.get("hosts"))
    scheduled_world_arcs = sum(
        1 for host in hosts.values()
        if isinstance(host, Mapping) and host.get("kind") == "world_arc" and host.get("next_due") is not None
    )
    scheduled_arc_reports = sum(
        1 for host in hosts.values()
        if isinstance(host, Mapping) and host.get("kind") == "world_arc_report" and host.get("next_due") is not None
    )
    player_relevant_kinds = {
        "world_arc_report",
        "campaign_event",
        "institutional_process",
        "household_request",
        "household_recruitment_watch",
        "player_story_review",
        "story_appointment_reply",
        "qin_command_receiving",
        "qin_command_assumption",
    }
    scheduled_reports = sum(
        1 for host in hosts.values()
        if isinstance(host, Mapping) and host.get("kind") in player_relevant_kinds and host.get("next_due") is not None
    )
    pending_wake = isinstance(runtime.get("pending_wake"), Mapping)
    causal_head = _mapping(events.get("causal_events"))
    causal_events = max(0, int(events.get("archived_event_count", 0))) + len(causal_head)
    blocked_qin_assumptions = _awaiting_qin_command_without_receiving_path(player, hosts, causal_head)
    scheduler = _mapping(runtime.get("scheduler"))
    scheduler_frontier = scheduler.get("causal_settled_through")
    scheduler_frontier_matches = isinstance(scheduler_frontier, str) and scheduler_frontier == runtime.get("world_time")
    scheduler_dirty = scheduler.get("dirty") is True
    scheduler_coverage = _mapping(scheduler.get("last_coverage"))
    scheduler_coverage_complete = scheduler_coverage.get("complete") is True

    report_sources = {
        str(event.get("source_event_ref"))
        for event in causal_head.values()
        if isinstance(event, Mapping)
        and event.get("kind") == "world_arc_report"
        and isinstance(event.get("source_event_ref"), str)
    }
    routed_sources = {
        str(host.get("source_event_ref"))
        for host in hosts.values()
        if isinstance(host, Mapping)
        and host.get("kind") == "world_arc_report"
        and isinstance(host.get("source_event_ref"), str)
    }
    visible_arc_activities_without_delivery_route = 0
    suppressed_nonmaterial_visible_arc_activities = 0
    for event_ref, event in causal_head.items():
        if not isinstance(event_ref, str) or not isinstance(event, Mapping) or event.get("kind") != "world_arc_activity":
            continue
        if str(event.get("visibility_class", "hidden")) not in {"discoverable", "direct"}:
            continue
        if not source_has_player_safe_world_arc_report(event):
            suppressed_nonmaterial_visible_arc_activities += 1
            continue
        if event_ref not in report_sources and event_ref not in routed_sources:
            visible_arc_activities_without_delivery_route += 1

    player_id = str(meta.get("player_id", ""))
    known_claims = 0
    for path in _mapping(information.get("claims")).values():
        if not isinstance(path, str):
            continue
        try:
            claim = _mapping(store.read_json(path))
        except (FileNotFoundError, OSError, TypeError, ValueError):
            continue
        if player_id and player_id in claim.get("knowers", []):
            known_claims += 1

    narrative = _mapping(scene.get("narrative"))
    visible_reports = len(narrative.get("available_reports", [])) if isinstance(narrative.get("available_reports"), list) else 0
    scene_fresh = scene.get("world_time") == meta.get("time") and scene.get("projection_revision") == meta.get("revision")
    routes = process_routes.get("processes", [])
    institutional_routes = len(routes) if isinstance(routes, list) else 0

    diagnostics: list[str] = []
    suggestions: list[str] = []
    if active_arcs and scheduled_world_arcs == 0:
        diagnostics.append("active_world_arcs_without_scheduled_progression")
        suggestions.append("review_world_arc_scheduler_routing")
    if active_arcs and active_visible_arcs == 0:
        diagnostics.append("active_world_arcs_have_no_player_visible_route")
        suggestions.append("review_world_arc_visibility_and_handoff_routing")
    if visible_arc_activities_without_delivery_route:
        diagnostics.append("player_visible_world_arc_activity_without_delivery_route")
        suggestions.append("restore_world_arc_report_routing_before_increasing_arc_frequency")
    if (known_claims or causal_events) and visible_reports == 0 and scene_fresh:
        diagnostics.append("established_information_without_player_facing_scene_report")
        suggestions.append("review_information_and_scene_delivery_routing")
    if active_arcs and not pending_wake and scheduled_world_arcs + scheduled_reports == 0:
        diagnostics.append("world_pressure_exists_but_no_near_term_causal_handoff_is_scheduled")
        suggestions.append("review_causal_throughput_before_treating_waiting_as_empty_time")
    if active_arcs and causal_events and known_claims == 0 and scheduled_reports == 0 and not pending_wake:
        diagnostics.append("world_pressure_exists_but_player_information_and_handoff_are_empty")
        suggestions.append("bridge_delivered_reports_into_information_and_opportunity_routing")
    if blocked_qin_assumptions:
        diagnostics.append("awaiting_qin_command_at_report_site_without_receiving_path")
        suggestions.append("route_qin_command_report_attempt_into_institutional_receiving_process")
    if not scheduler_frontier_matches:
        diagnostics.append("global_causal_frontier_diverged_from_world_time")
        suggestions.append("repair_scheduler_frontier_before_advancing_time")
    if scheduler_coverage and not scheduler_coverage_complete:
        diagnostics.append("scheduler_registry_coverage_incomplete")
        suggestions.append("reconcile_scheduler_routes_before_treating_world_as_current")

    return {
        "active_world_arcs": active_arcs,
        "active_world_arcs_with_player_visible_routes": active_visible_arcs,
        "scheduled_world_arc_hosts": scheduled_world_arcs,
        "scheduled_world_arc_report_hosts": scheduled_arc_reports,
        "scheduled_player_relevant_hosts": scheduled_reports,
        "visible_arc_activities_without_delivery_route": visible_arc_activities_without_delivery_route,
        "suppressed_nonmaterial_visible_arc_activities": suppressed_nonmaterial_visible_arc_activities,
        "institutional_process_routes": institutional_routes,
        "exact_causal_events": causal_events,
        "player_known_information_claims": known_claims,
        "scene_visible_reports": visible_reports,
        "scene_projection_fresh": bool(scene_fresh),
        "pending_wake": pending_wake,
        "blocked_awaiting_qin_command_assumptions": blocked_qin_assumptions,
        "scheduler_causal_settled_through": scheduler_frontier,
        "scheduler_frontier_matches_world_time": bool(scheduler_frontier_matches),
        "scheduler_dirty": bool(scheduler_dirty),
        "scheduler_registry_revision": int(scheduler.get("registry_revision", 0)) if scheduler else 0,
        "scheduler_coverage_complete": bool(scheduler_coverage_complete),
        "scheduler_next_global_due": scheduler.get("next_global_due"),
        "scheduler_next_safety_reconcile_at": scheduler.get("next_safety_reconcile_at"),
        "diagnostics": diagnostics,
        "suggestions": list(dict.fromkeys(suggestions)),
    }


__all__ = ["summarize_playability_vitality"]