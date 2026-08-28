"""Live read-only campaign-planning projection for API play context.

Historical briefing claims remain historical snapshots. This adapter augments
current campaign-command views with the campaign planner's present player-safe
staff projection so campaigns created before later planning features were added
do not remain permanently starved of current objectives, hierarchy, routes, and
capacity constraints.

The overlay also joins the exact current command-group hierarchy back onto the
state-owned staff allocation. This matters because an intact field army may
contain House/private subordinate formations that remain under their own owners
while still contributing bodies to that command's real marching span. Those
bodies must count for army strength and road burden without becoming Qin-owned.

The overlay is read-only. It does not rewrite the saved briefing, issue orders,
move formations, authorize hostile entry, transfer troop ownership, or advance
campaign time.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.warfare_operations import WarfareCampaignOperations
from sword_runtime.campaign_briefing import build_campaign_dossier
from sword_runtime.campaign_march_planning import project_route_path
from sword_runtime.geography import shortest_path

_INTERACTION_ATTEMPT_LEDGER_PATH = "state/index/interaction-attempts.json"
_COMMAND_GROUP_PATH = "state/cmd/command-groups/{ref}.json"
_LOCATIONS_PATH = "game/data/world/locations.json"


def _formation(planner: Any, ref: str) -> Mapping[str, Any] | None:
    try:
        row = planner.read(planner.owner_path(ref))
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _command_group(planner: Any, ref: str) -> Mapping[str, Any] | None:
    try:
        row = planner.read(_COMMAND_GROUP_PATH.format(ref=ref))
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _command_span_formation_refs(planner: Any, command_ref: str) -> list[str]:
    if not command_ref:
        return []
    if not command_ref.startswith("cmdgrp."):
        return [command_ref] if _formation(planner, command_ref) is not None else []

    refs: list[str] = []
    stack = [command_ref]
    seen: set[str] = set()
    while stack:
        group_ref = stack.pop()
        if group_ref in seen:
            continue
        seen.add(group_ref)
        group = _command_group(planner, group_ref)
        if not isinstance(group, Mapping):
            continue
        for unit in group.get("units", []) if isinstance(group.get("units"), list) else []:
            if not isinstance(unit, Mapping):
                continue
            ref = unit.get("ref")
            kind = unit.get("kind")
            if not isinstance(ref, str) or not ref:
                continue
            if kind == "nested_army":
                stack.append(ref)
            elif kind == "formation" and ref not in refs:
                refs.append(ref)
    return refs


def _is_state_owned_formation(formation: Mapping[str, Any], state_ref: str) -> bool:
    owner_force = str(formation.get("owner_force_ref") or "")
    administrative_owner = str(formation.get("administrative_owner") or "")
    return owner_force == f"force_{state_ref}" and administrative_owner == state_ref


def _location_names(planner: Any) -> dict[str, str]:
    try:
        doc = planner.read(_LOCATIONS_PATH)
    except (FileNotFoundError, KeyError, ValueError):
        return {}
    rows = doc.get("locations", []) if isinstance(doc, Mapping) else []
    return {
        str(row.get("ref")): str(row.get("name") or row.get("ref"))
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("ref"), str)
    }


def _apply_recursive_command_span(planner: Any, planning: dict[str, Any]) -> None:
    scheme = planning.get("campaign_scheme")
    if not isinstance(scheme, dict):
        return
    campaign_state_ref = scheme.get("campaign_state_ref")
    if not isinstance(campaign_state_ref, str) or not campaign_state_ref:
        return

    assignments = scheme.get("command_assignments") if isinstance(scheme.get("command_assignments"), list) else []
    reserves = scheme.get("strategic_reserve_commands") if isinstance(scheme.get("strategic_reserve_commands"), list) else []
    all_rows = [row for row in assignments + reserves if isinstance(row, dict)]
    all_non_state_refs: set[str] = set()
    non_state_strength = 0
    command_span_strength = 0
    route_origin_strength: dict[tuple[str, str], int] = {}

    for row in all_rows:
        command_ref = str(row.get("command_ref") or "")
        state_owned_personnel = max(0, int(row.get("personnel", 0) or 0))
        state_refs = [str(ref) for ref in row.get("formation_refs", []) if isinstance(ref, str)]
        span_refs = _command_span_formation_refs(planner, command_ref)
        non_state_refs: list[str] = []
        non_state_personnel = 0
        origin_strength: dict[str, int] = {}

        for ref in span_refs:
            formation = _formation(planner, ref)
            if not isinstance(formation, Mapping):
                continue
            personnel = max(0, int(formation.get("personnel", 0) or 0))
            if personnel <= 0:
                continue
            origin_ref = str(formation.get("location_ref") or "")
            if origin_ref:
                origin_strength[origin_ref] = origin_strength.get(origin_ref, 0) + personnel
            if not _is_state_owned_formation(formation, campaign_state_ref):
                non_state_refs.append(ref)
                non_state_personnel += personnel

        full_personnel = state_owned_personnel + non_state_personnel
        row["state_owned_personnel"] = state_owned_personnel
        row["non_state_subordinate_personnel"] = non_state_personnel
        row["personnel"] = full_personnel
        row["state_owned_formation_refs"] = state_refs
        row["command_span_formation_refs"] = sorted(set(state_refs + non_state_refs))
        row["non_state_subordinate_formation_refs"] = sorted(set(non_state_refs))
        command_span_strength += full_personnel
        non_state_strength += non_state_personnel
        all_non_state_refs.update(non_state_refs)
        for origin_ref, strength in origin_strength.items():
            route_origin_strength[(command_ref, origin_ref)] = strength

    scheme["command_span_planned_strength"] = command_span_strength
    scheme["non_state_subordinate_strength"] = non_state_strength
    scheme["excluded_non_state_formation_refs"] = sorted(all_non_state_refs)
    scheme["excluded_non_state_strength"] = non_state_strength
    scheme["ownership_rule"] = (
        "Assignment personnel is the full current recursive command span. "
        "state_owned_planned_strength is the Qin-owned component; excluded_non_state_strength is the House/private subordinate component already nested inside those intact field commands. "
        "Counting those bodies in command strength and movement burden does not transfer ownership or authorize detachment outside the existing command hierarchy."
    )

    objectives = scheme.get("objectives") if isinstance(scheme.get("objectives"), list) else []
    for objective in objectives:
        if not isinstance(objective, dict):
            continue
        objective_ref = objective.get("objective_ref")
        objective["assigned_strength"] = sum(
            max(0, int(row.get("personnel", 0) or 0))
            for row in assignments
            if isinstance(row, Mapping) and row.get("objective_ref") == objective_ref
        )

    hierarchy = scheme.get("command_hierarchy")
    if isinstance(hierarchy, dict):
        hierarchy["command_span_strength"] = command_span_strength
        hierarchy["non_state_subordinate_strength"] = non_state_strength
        hierarchy["subordination_rule"] = (
            "All listed field commands remain beneath campaign supreme command. Their persistent internal command groups stay intact, including House/private subordinate formations already nested inside them; this temporary campaign hierarchy does not flatten, re-own, or permanently reparent formations."
        )
        by_command = {
            str(row.get("command_ref")): row
            for row in assignments
            if isinstance(row, Mapping) and isinstance(row.get("command_ref"), str)
        }
        for detachment in hierarchy.get("operational_detachments", []) if isinstance(hierarchy.get("operational_detachments"), list) else []:
            if not isinstance(detachment, dict):
                continue
            source = by_command.get(str(detachment.get("command_ref") or ""))
            if source:
                detachment["personnel"] = max(0, int(source.get("personnel", 0) or 0))

    names = _location_names(planner)
    command_routes: list[dict[str, Any]] = []
    route_loads: dict[str, dict[str, Any]] = {}
    for assignment in assignments:
        if not isinstance(assignment, Mapping):
            continue
        command_ref = str(assignment.get("command_ref") or "")
        objective_ref = assignment.get("objective_ref")
        if not command_ref or not isinstance(objective_ref, str) or not objective_ref:
            continue
        span_refs = [str(ref) for ref in assignment.get("command_span_formation_refs", []) if isinstance(ref, str)]
        by_origin: dict[str, int] = {}
        for ref in span_refs:
            formation = _formation(planner, ref)
            if not isinstance(formation, Mapping):
                continue
            origin_ref = str(formation.get("location_ref") or "")
            if not origin_ref:
                continue
            by_origin[origin_ref] = by_origin.get(origin_ref, 0) + max(0, int(formation.get("personnel", 0) or 0))

        for origin_ref, strength in sorted(by_origin.items()):
            if strength <= 0:
                continue
            try:
                path = shortest_path(planner.read, origin_ref, objective_ref, modes=("formation",))
            except ValueError:
                continue
            projected = project_route_path(planner.read, path, strength=strength)
            command_row = {
                "command_ref": command_ref,
                "commander_ref": assignment.get("commander_ref"),
                "commander_name": assignment.get("commander_name"),
                "operation_refs": list(assignment.get("operation_refs", [])),
                "role": assignment.get("role"),
                "strength": strength,
                "origin_ref": origin_ref,
                "origin_name": names.get(origin_ref, origin_ref),
                "objective_ref": objective_ref,
                "objective_name": names.get(objective_ref, objective_ref),
                **projected,
            }
            command_routes.append(command_row)
            for segment in projected.get("segments", []):
                if not isinstance(segment, Mapping):
                    continue
                route_ref = str(segment.get("route_ref") or "")
                if not route_ref:
                    continue
                load = route_loads.setdefault(route_ref, {
                    "route_ref": route_ref,
                    "from_name": segment.get("from_name"),
                    "to_name": segment.get("to_name"),
                    "daily_troop_throughput": (segment.get("physical_geometry") or {}).get("daily_troop_throughput"),
                    "daily_wagon_throughput": (segment.get("physical_geometry") or {}).get("daily_wagon_throughput"),
                    "command_refs": [],
                    "objective_refs": [],
                    "combined_strength": 0,
                })
                if command_ref not in load["command_refs"]:
                    load["command_refs"].append(command_ref)
                if objective_ref not in load["objective_refs"]:
                    load["objective_refs"].append(objective_ref)
                load["combined_strength"] += strength

    shared_bottlenecks: list[dict[str, Any]] = []
    for load in route_loads.values():
        throughput = max(0, int(load.get("daily_troop_throughput", 0) or 0))
        combined = max(0, int(load.get("combined_strength", 0) or 0))
        if len(load["command_refs"]) < 2 and (throughput <= 0 or combined <= throughput):
            continue
        load["minimum_troop_clearance_days_floor"] = int(math.ceil(combined / throughput)) if throughput > 0 and combined > 0 else None
        shared_bottlenecks.append(load)
    shared_bottlenecks.sort(key=lambda row: (-int(row.get("combined_strength", 0) or 0), str(row.get("route_ref", ""))))
    command_routes.sort(key=lambda row: (-int(row.get("strength", 0) or 0), str(row.get("command_ref") or ""), str(row.get("origin_ref", ""))))
    planning["command_routes"] = command_routes
    planning["shared_bottlenecks"] = shared_bottlenecks


class CampaignPlanningAwareOperations(WarfareCampaignOperations):
    """Expose current safe campaign planning beside immutable briefing history."""

    def _stabilize_same_time_attempt_order(self, context: dict[str, Any]) -> None:
        """Prefer persisted ledger order to hash order for public recent attempts."""
        attempts = context.get("recent_interaction_attempts")
        if not isinstance(attempts, list) or len(attempts) < 2:
            return
        try:
            ledger = self.store.read_json(_INTERACTION_ATTEMPT_LEDGER_PATH)
        except (FileNotFoundError, KeyError, ValueError):
            return
        raw_rows = ledger.get("attempts") if isinstance(ledger, Mapping) else None
        if not isinstance(raw_rows, list):
            return
        positions = {
            str(row.get("event_id")): index
            for index, row in enumerate(raw_rows)
            if isinstance(row, Mapping) and isinstance(row.get("event_id"), str)
        }
        if not positions:
            return
        context["recent_interaction_attempts"] = sorted(
            attempts,
            key=lambda row: positions.get(str(row.get("event_id")), -1)
            if isinstance(row, Mapping) else -1,
            reverse=True,
        )

    def play_context(self) -> dict[str, Any]:
        context = super().play_context()
        self._stabilize_same_time_attempt_order(context)
        planner = getattr(self.runtime, "planner", None)
        if planner is None:
            return context

        controlled = context.get("controlled_operations")
        if not isinstance(controlled, list):
            return context

        for operation in controlled:
            if not isinstance(operation, dict):
                continue
            operation_ref = operation.get("operation_ref")
            campaign_command = operation.get("campaign_command")
            if not isinstance(operation_ref, str) or not operation_ref:
                continue
            if not isinstance(campaign_command, dict):
                continue

            try:
                dossier = build_campaign_dossier(planner, operation_ref)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            planning = dossier.get("march_planning")
            if not isinstance(planning, Mapping):
                continue

            live_planning = copy.deepcopy(dict(planning))
            _apply_recursive_command_span(planner, live_planning)
            campaign_command["march_planning"] = live_planning
            scheme = live_planning.get("campaign_scheme") if isinstance(live_planning.get("campaign_scheme"), Mapping) else None
            campaign_context = operation.get("campaign_context")
            if isinstance(scheme, Mapping) and isinstance(campaign_context, dict):
                span_strength = scheme.get("command_span_planned_strength")
                if isinstance(span_strength, int) and span_strength > 0:
                    campaign_context["friendly_total_strength"] = span_strength

            campaign_command["march_planning_projection"] = {
                "status": "current_read_only_projection",
                "historical_briefing_unchanged": True,
                "authority_rule": (
                    "current planning projection only; it does not rewrite the historical briefing, issue an order, move a formation, authorize hostile entry, transfer troop ownership, or advance campaign time"
                ),
            }

        return context


__all__ = ["CampaignPlanningAwareOperations"]