"""Player-safe campaign scheme and march-planning projection.

This module does not issue orders, move formations, authorize hostile entry, or
invent logistics.  It turns the exact friendly campaign roster plus authored
strategic geography into a bounded pre-entry staff scheme: which intact commands
are proposed for which objectives, which command remains reserve, and what
physical route/capacity constraints those proposed axes create.

The scheme is deliberately a planning projection.  Exact campaign-command orders,
formation movement, troop ownership, interstate war authority, siege outcomes,
and territorial consequences remain with their existing owners.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sword_runtime.geography import shortest_path
from sword_runtime.strategic_war_planning import _assign_commands, _border_objectives, _command_catalog

_ROUTES_PATH = "game/data/world/routes.json"
_LOCATIONS_PATH = "game/data/world/locations.json"
_COMMAND_GROUP_INDEX = "state/cmd/command-groups/index.json"
_TERRITORY_PATH = "state/territory/control.json"
_PLAYER_REF = "char_tang_wei"
_STRATEGIC_SITE_KINDS = {"capital", "major_city", "city", "fortress", "fort", "pass"}


def _route_rows(read: Callable[[str], Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    doc = read(_ROUTES_PATH)
    rows = list(doc.get("routes", [])) + list(doc.get("local_routes", [])) if isinstance(doc, Mapping) else []
    return {
        str(row.get("ref")): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("ref"), str) and row.get("ref")
    }


def _location_rows(read: Callable[[str], Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    doc = read(_LOCATIONS_PATH)
    return {
        str(row.get("ref")): row
        for row in doc.get("locations", []) if isinstance(doc, Mapping) and isinstance(row, Mapping) and row.get("ref")
    }


def _location_name(locations: Mapping[str, Mapping[str, Any]], ref: str) -> str:
    row = locations.get(str(ref))
    return str(row.get("name") or ref) if isinstance(row, Mapping) else str(ref)


def _person_name(planner: Any, ref: str | None) -> str | None:
    if not isinstance(ref, str) or not ref:
        return None
    try:
        person = planner.read(planner.owner_path(ref))
    except (FileNotFoundError, KeyError, ValueError):
        return ref
    return str(person.get("name") or person.get("display_name") or ref) if isinstance(person, Mapping) else ref


def _bounded_geometry(route: Mapping[str, Any]) -> dict[str, Any]:
    geometry = route.get("physical_geometry") if isinstance(route.get("physical_geometry"), Mapping) else {}
    allowed = (
        "length_km",
        "surface",
        "usable_road_width_m",
        "formation_files_abreast_baseline",
        "daily_troop_throughput",
        "daily_wagon_throughput",
        "maximum_sustained_grade_percent",
    )
    return {key: geometry.get(key) for key in allowed if geometry.get(key) is not None}


def _bounded_water_crossing(route: Mapping[str, Any]) -> dict[str, Any] | None:
    crossing = route.get("water_crossing")
    if not isinstance(crossing, Mapping):
        return None
    allowed = (
        "crossing_type",
        "river_width_m",
        "normal_depth_m",
        "normal_current_m_per_s",
        "bridge_span_m",
        "bridge_width_m",
        "bridge_load_capacity_tonnes",
        "ferry_boats",
        "ferry_payload_tonnes_each",
        "ferry_cycle_minutes",
        "ford_available_low_stage",
        "ford_available_normal_stage",
    )
    return {key: crossing.get(key) for key in allowed if crossing.get(key) is not None}


def project_route_path(
    read: Callable[[str], Mapping[str, Any]],
    path: Mapping[str, Any],
    *,
    strength: int,
) -> dict[str, Any]:
    """Project one exact path into staff-readable physical movement constraints.

    Clearance days are a lower bound based only on authored troop throughput.
    They deliberately exclude baggage, supply wagons, rests, departure spacing,
    traffic control, enemy action, and any other burden not owned by the source.
    """
    routes = _route_rows(read)
    locations = _location_rows(read)
    nodes = [str(x) for x in path.get("path", []) if isinstance(x, str)]
    route_refs = [str(x) for x in path.get("route_refs", []) if isinstance(x, str)]
    modes = [str(x) for x in path.get("edge_modes", []) if isinstance(x, str)]
    edge_hours = [int(x) for x in path.get("edge_hours", []) if isinstance(x, (int, float))]
    segments: list[dict[str, Any]] = []
    for index, route_ref in enumerate(route_refs):
        route = routes.get(route_ref)
        if not isinstance(route, Mapping):
            continue
        geometry = _bounded_geometry(route)
        throughput = max(0, int(geometry.get("daily_troop_throughput", 0) or 0))
        row: dict[str, Any] = {
            "route_ref": route_ref,
            "from_ref": nodes[index] if index < len(nodes) else route.get("a"),
            "to_ref": nodes[index + 1] if index + 1 < len(nodes) else route.get("b"),
            "edge_hours": edge_hours[index] if index < len(edge_hours) else int(route.get("duration_hours", route.get("hours", 0)) or 0),
            "movement_mode": modes[index] if index < len(modes) else None,
            "road_quality": route.get("road_quality"),
            "terrain": route.get("terrain"),
            "scope": route.get("scope"),
            "physical_geometry": geometry,
            "water_crossing": _bounded_water_crossing(route),
            "troop_clearance_days_floor": int(math.ceil(max(0, int(strength)) / throughput)) if throughput > 0 and strength > 0 else None,
        }
        row["from_name"] = _location_name(locations, str(row["from_ref"]))
        row["to_name"] = _location_name(locations, str(row["to_ref"]))
        segments.append(row)
    return {
        "duration_hours": int(path.get("duration_hours", 0) or 0),
        "path_refs": nodes,
        "path_names": [_location_name(locations, ref) for ref in nodes],
        "segments": segments,
    }


def _state_side(value: str | None) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.removeprefix("state_")


def _side_owner_ref(side: str) -> str:
    return side if str(side).startswith("polity_") else f"state_{side}"


def _campaign_region_context(
    planner: Any,
    *,
    defender: str,
    strategic_anchor_ref: str,
) -> dict[str, Any] | None:
    """Expand a strategic anchor site into its current regional objective set.

    A campaign may be commonly identified by one important city while the actual
    military task is to secure the surrounding region.  The authored location
    hierarchy provides that regional scope; current territory control decides
    which strategic sites still belong to the defender.  No enemy formation,
    garrison strength, or hidden deployment is read here.
    """
    locations = _location_rows(planner.read)
    anchor = locations.get(str(strategic_anchor_ref))
    if not isinstance(anchor, Mapping):
        return None

    region_ref = anchor.get("region_ref")
    if not isinstance(region_ref, str) or not region_ref:
        parent_ref = anchor.get("parent_ref")
        parent = locations.get(str(parent_ref)) if isinstance(parent_ref, str) else None
        if isinstance(parent, Mapping) and str(parent.get("kind", "")) == "region":
            region_ref = parent_ref
    if not isinstance(region_ref, str) or not region_ref:
        return None

    region = locations.get(region_ref)
    if not isinstance(region, Mapping) or str(region.get("kind", "")) != "region":
        return None
    defender_owner = _side_owner_ref(defender)
    if str(region.get("polity_ref") or "") != defender_owner:
        return None

    territory = planner.read(_TERRITORY_PATH)
    sites = territory.get("sites", {}) if isinstance(territory, Mapping) else {}
    objectives: list[dict[str, Any]] = []
    for ref, row in locations.items():
        if ref == region_ref or not isinstance(row, Mapping):
            continue
        if str(row.get("region_ref") or row.get("parent_ref") or "") != region_ref:
            continue
        kind = str(row.get("kind", ""))
        if kind not in _STRATEGIC_SITE_KINDS or not bool(row.get("strategic_node")):
            continue
        site = sites.get(ref, {}) if isinstance(sites, Mapping) else {}
        controller = str(site.get("controller", "")) if isinstance(site, Mapping) else ""
        if controller != defender_owner:
            continue

        priority = 70
        if ref == strategic_anchor_ref:
            priority += 60
        if bool(row.get("fortified")):
            priority += 20
        if kind in {"capital", "major_city"}:
            priority += 30
        elif kind in {"city", "fortress", "fort", "pass"}:
            priority += 15
        objectives.append({
            "objective_ref": ref,
            "priority": priority,
            "kind": kind,
            "fortified": bool(row.get("fortified")),
            "regional_role": "strategic_anchor" if ref == strategic_anchor_ref else "regional_objective",
        })

    if not objectives:
        return None
    objectives.sort(key=lambda row: (-int(row["priority"]), str(row["objective_ref"])))
    anchor_name = _location_name(locations, strategic_anchor_ref)
    return {
        "campaign_region_ref": region_ref,
        "campaign_region_name": f"{anchor_name} Region",
        "geography_region_name": _location_name(locations, region_ref),
        "strategic_anchor_ref": strategic_anchor_ref,
        "strategic_anchor_name": anchor_name,
        "objective_candidates": objectives[:6],
        "scope_basis": "authored parent region around the strategic anchor plus current defender-controlled strategic sites",
    }


def _formation(planner: Any, ref: str) -> Mapping[str, Any] | None:
    try:
        row = planner.read(planner.owner_path(ref))
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _root_group_for_formation(planner: Any, formation_ref: str) -> Mapping[str, Any] | None:
    try:
        index = planner.read(_COMMAND_GROUP_INDEX)
    except (FileNotFoundError, KeyError, ValueError):
        return None
    primary = index.get("primary_formation_group") if isinstance(index, Mapping) else None
    current = primary.get(formation_ref) if isinstance(primary, Mapping) else None
    if not isinstance(current, str) or not current:
        return None
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        try:
            group = planner.read(f"state/cmd/command-groups/{current}.json")
        except (FileNotFoundError, KeyError, ValueError):
            return None
        if not isinstance(group, Mapping):
            return None
        parent = group.get("parent_command_group_ref")
        if not isinstance(parent, str) or not parent:
            return group
        current = parent
    return None


def _campaign_force_inputs(
    planner: Any,
    friendly_participants: Sequence[Mapping[str, Any]],
) -> tuple[str | None, list[str], dict[str, str], list[str], int]:
    """Return one state-owned campaign pool without commandeering auxiliaries."""
    state_refs: set[str] = set()
    eligible: list[str] = []
    formation_operation: dict[str, str] = {}
    excluded_private: list[str] = []
    excluded_strength = 0
    for participant in friendly_participants:
        if not isinstance(participant, Mapping):
            continue
        operation_ref = str(participant.get("operation_ref") or "")
        rows = participant.get("formations") if isinstance(participant.get("formations"), list) else []
        for summary in rows:
            if not isinstance(summary, Mapping):
                continue
            ref = summary.get("formation_ref")
            if not isinstance(ref, str) or not ref:
                continue
            formation = _formation(planner, ref)
            if not isinstance(formation, Mapping):
                continue
            administrative_owner = str(formation.get("administrative_owner") or "")
            owner_force = str(formation.get("owner_force_ref") or "")
            state_ref = administrative_owner if administrative_owner.startswith("state_") else (
                owner_force.replace("force_", "", 1) if owner_force.startswith("force_state_") else ""
            )
            if state_ref:
                state_refs.add(state_ref)
            is_state_owned = bool(state_ref) and owner_force == f"force_{state_ref}"
            if is_state_owned:
                if ref not in eligible:
                    eligible.append(ref)
                if operation_ref:
                    formation_operation[ref] = operation_ref
            else:
                excluded_private.append(ref)
                excluded_strength += max(0, int(formation.get("personnel", 0) or 0))
    campaign_state_ref = next(iter(state_refs)) if len(state_refs) == 1 else None
    return campaign_state_ref, eligible, formation_operation, sorted(set(excluded_private)), excluded_strength


def _player_command_rows(planner: Any, eligible_refs: Sequence[str], covered_refs: set[str]) -> list[dict[str, Any]]:
    """Recover player-led state formations omitted by autonomous-planner agency guards."""
    grouped: dict[str, dict[str, Any]] = {}
    for ref in eligible_refs:
        if ref in covered_refs:
            continue
        group = _root_group_for_formation(planner, ref)
        if not isinstance(group, Mapping) or str(group.get("commander_ref") or "") != _PLAYER_REF:
            continue
        group_ref = str(group.get("command_group_ref") or group.get("owner_id") or "cmdgrp.tang_wei.field_army")
        formation = _formation(planner, ref)
        if not isinstance(formation, Mapping):
            continue
        row = grouped.setdefault(group_ref, {
            "command_group_ref": group_ref,
            "commander_ref": _PLAYER_REF,
            "context": str(group.get("context") or "state_field_army"),
            "formation_refs": [],
            "personnel": 0,
            "readiness_score": 0.0,
            "location_ref": None,
            "mobility": "mobile",
            "_weighted_readiness": 0,
            "_locations": {},
        })
        personnel = max(0, int(formation.get("personnel", 0) or 0))
        row["formation_refs"].append(ref)
        row["personnel"] += personnel
        readiness = (int(formation.get("readiness", 50)) + int(formation.get("cohesion", 50)) + int(formation.get("morale", 50))) / 3.0
        row["_weighted_readiness"] += personnel * readiness
        location_ref = str(formation.get("location_ref") or "")
        if location_ref:
            row["_locations"][location_ref] = row["_locations"].get(location_ref, 0) + personnel
    result: list[dict[str, Any]] = []
    for row in grouped.values():
        personnel = max(1, int(row["personnel"]))
        locations = row.pop("_locations")
        row["readiness_score"] = round(float(row.pop("_weighted_readiness")) / personnel, 3)
        row["location_ref"] = max(locations, key=lambda key: (locations[key], key)) if locations else None
        row["formation_refs"] = sorted(set(row["formation_refs"]))
        result.append(row)
    return result


def _command_operation_refs(command: Mapping[str, Any], formation_operation: Mapping[str, str]) -> list[str]:
    return sorted({
        formation_operation[ref]
        for ref in command.get("formation_refs", [])
        if isinstance(ref, str) and ref in formation_operation
    })


def _build_campaign_scheme(
    planner: Any,
    *,
    friendly_participants: Sequence[Mapping[str, Any]],
    operational_area: Mapping[str, Any],
) -> dict[str, Any] | None:
    strategic_anchor = operational_area.get("strategic_target_ref")
    target_state_ref = operational_area.get("target_state_ref")
    if not isinstance(strategic_anchor, str) or not strategic_anchor or not isinstance(target_state_ref, str) or not target_state_ref:
        return None
    campaign_state_ref, eligible_refs, formation_operation, excluded_private, excluded_private_strength = _campaign_force_inputs(
        planner, friendly_participants
    )
    attacker = _state_side(campaign_state_ref)
    defender = _state_side(target_state_ref)
    if not attacker or not defender or not eligible_refs:
        return None

    region_context = _campaign_region_context(
        planner,
        defender=defender,
        strategic_anchor_ref=strategic_anchor,
    )
    if isinstance(region_context, Mapping) and isinstance(region_context.get("objective_candidates"), list):
        objectives = [dict(row) for row in region_context["objective_candidates"] if isinstance(row, Mapping)]
    else:
        objectives = _border_objectives(planner, attacker, defender, strategic_anchor)
    if not objectives:
        objectives = [{"objective_ref": strategic_anchor, "priority": 100, "kind": "strategic", "fortified": False}]

    commands = [dict(row) for row in _command_catalog(planner, attacker, list(eligible_refs))]
    covered = {str(ref) for row in commands for ref in row.get("formation_refs", []) if isinstance(ref, str)}
    commands.extend(_player_command_rows(planner, eligible_refs, covered))
    commands.sort(key=lambda row: (0 if row.get("mobility") == "mobile" else 1, -int(row.get("personnel", 0)), str(row.get("command_group_ref") or row.get("independent_formation_ref") or "")))
    if not commands:
        return None

    # Pre-entry staff planning deliberately does not read hidden enemy formation
    # power. If enough intact commands and physical objectives exist, open more
    # than one axis; otherwise mass on the anchor objective. Exact opposition can
    # lawfully cause replanning later as reports arrive.
    mode = "multi_axis" if len(objectives) >= 2 and len(commands) >= 4 else "decisive_concentration"
    assignments, reserve = _assign_commands(commands, objectives, mode=mode)
    locations = _location_rows(planner.read)
    objective_by_ref = {str(row["objective_ref"]): row for row in objectives}

    assignment_rows: list[dict[str, Any]] = []
    for command in assignments:
        objective_ref = str(command.get("objective_ref") or strategic_anchor)
        assignment_rows.append({
            "command_ref": command.get("command_group_ref") or command.get("independent_formation_ref"),
            "commander_ref": command.get("commander_ref"),
            "commander_name": _person_name(planner, command.get("commander_ref")),
            "operation_refs": _command_operation_refs(command, formation_operation),
            "formation_refs": sorted(str(ref) for ref in command.get("formation_refs", []) if isinstance(ref, str)),
            "personnel": max(0, int(command.get("personnel", 0) or 0)),
            "role": command.get("role"),
            "objective_ref": objective_ref,
            "objective_name": _location_name(locations, objective_ref),
        })
    reserve_rows = [{
        "command_ref": command.get("command_group_ref") or command.get("independent_formation_ref"),
        "commander_ref": command.get("commander_ref"),
        "commander_name": _person_name(planner, command.get("commander_ref")),
        "operation_refs": _command_operation_refs(command, formation_operation),
        "formation_refs": sorted(str(ref) for ref in command.get("formation_refs", []) if isinstance(ref, str)),
        "personnel": max(0, int(command.get("personnel", 0) or 0)),
        "role": "strategic_reserve",
    } for command in reserve]

    assigned_objective_refs = list(dict.fromkeys(str(row["objective_ref"]) for row in assignment_rows))
    objective_rows: list[dict[str, Any]] = []
    for objective_ref in assigned_objective_refs:
        source = objective_by_ref.get(objective_ref, {})
        assigned = [row for row in assignment_rows if row["objective_ref"] == objective_ref]
        objective_rows.append({
            "objective_ref": objective_ref,
            "objective_name": _location_name(locations, objective_ref),
            "priority": int(source.get("priority", 0) or 0),
            "kind": source.get("kind"),
            "fortified": bool(source.get("fortified")),
            "regional_role": source.get("regional_role"),
            "axis_role": "primary" if objective_ref == strategic_anchor else "secondary",
            "assigned_command_refs": [row.get("command_ref") for row in assigned],
            "assigned_commanders": [row.get("commander_name") for row in assigned if row.get("commander_name")],
            "assigned_strength": sum(int(row.get("personnel", 0) or 0) for row in assigned),
        })
    objective_rows.sort(key=lambda row: (0 if row["objective_ref"] == strategic_anchor else 1, -int(row.get("priority", 0)), str(row["objective_ref"])))

    regional = isinstance(region_context, Mapping)
    campaign_region_ref = region_context.get("campaign_region_ref") if regional else None
    campaign_region_name = region_context.get("campaign_region_name") if regional else None
    geography_region_name = region_context.get("geography_region_name") if regional else None
    success_condition = (
        "Resolve the assigned strategic sites across the campaign region under supreme command; control of the strategic anchor alone is not equivalent to securing the whole region."
        if regional
        else "Secure the primary objective and resolve every assigned campaign front before supreme command closes or redirects this campaign phase."
    )

    return {
        "kind": "pre_entry_campaign_staff_scheme",
        "status": "staff_plan_pending_exact_orders_and_entry_authority",
        "campaign_state_ref": campaign_state_ref,
        "target_state_ref": target_state_ref,
        "campaign_scope_kind": "regional_campaign" if regional else "site_campaign",
        "campaign_region_ref": campaign_region_ref,
        "campaign_region_name": campaign_region_name,
        "geography_region_name": geography_region_name,
        "strategic_anchor_ref": strategic_anchor,
        "strategic_anchor_name": _location_name(locations, strategic_anchor),
        "primary_objective_ref": strategic_anchor,
        "primary_objective_name": _location_name(locations, strategic_anchor),
        "concentration_mode": mode,
        "objective_count": len(objective_rows),
        "objectives": objective_rows,
        "command_assignments": assignment_rows,
        "strategic_reserve_commands": reserve_rows,
        "state_owned_planned_strength": sum(int(row.get("personnel", 0) or 0) for row in assignment_rows + reserve_rows),
        "excluded_non_state_formation_refs": excluded_private,
        "excluded_non_state_strength": excluded_private_strength,
        "operational_end_state": {
            "campaign_region_ref": campaign_region_ref,
            "campaign_region_name": campaign_region_name,
            "required_objective_refs": assigned_objective_refs,
            "strategic_anchor_ref": strategic_anchor,
            "success_condition": success_condition,
            "war_termination_rule": "Political war termination, annexation, treaty terms, and follow-on territorial settlement remain separate sovereign and diplomatic decisions.",
        },
        "planning_basis": (
            "current campaign roster plus authored strategic geography; when the strategic anchor belongs to a defender region, current defender-controlled strategic sites in that region define the regional campaign objective set; hidden enemy deployments are not used to choose the pre-entry axes"
        ),
        "authority_rule": "staff planning projection only; it does not issue an order, move a formation, authorize hostile entry, transfer troop ownership, or choose Tang Wei's tactics",
        "ownership_rule": "non-state/private auxiliaries are excluded from Qin planning strength unless a separate lawful commitment and acceptance establishes their use",
    }


def build_march_planning_baseline(
    planner: Any,
    *,
    friendly_participants: Sequence[Mapping[str, Any]],
    operational_area: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a bounded campaign scheme plus route/capacity baseline."""
    if not isinstance(operational_area, Mapping):
        return None
    strategic_target_ref = operational_area.get("strategic_target_ref")
    if not isinstance(strategic_target_ref, str) or not strategic_target_ref:
        return None
    locations = _location_rows(planner.read)
    scheme = _build_campaign_scheme(
        planner, friendly_participants=friendly_participants, operational_area=operational_area
    )

    command_routes: list[dict[str, Any]] = []
    route_loads: dict[str, dict[str, Any]] = {}
    if isinstance(scheme, Mapping):
        assignments = scheme.get("command_assignments") if isinstance(scheme.get("command_assignments"), list) else []
        for assignment in assignments:
            if not isinstance(assignment, Mapping):
                continue
            objective_ref = assignment.get("objective_ref")
            if not isinstance(objective_ref, str) or not objective_ref:
                continue
            refs = [str(ref) for ref in assignment.get("formation_refs", []) if isinstance(ref, str)]
            by_origin: dict[str, int] = {}
            for ref in refs:
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
                    "command_ref": assignment.get("command_ref"),
                    "commander_ref": assignment.get("commander_ref"),
                    "commander_name": assignment.get("commander_name"),
                    "operation_refs": list(assignment.get("operation_refs", [])),
                    "role": assignment.get("role"),
                    "strength": strength,
                    "origin_ref": origin_ref,
                    "origin_name": _location_name(locations, origin_ref),
                    "objective_ref": objective_ref,
                    "objective_name": _location_name(locations, objective_ref),
                    **projected,
                }
                command_routes.append(command_row)
                for segment in projected["segments"]:
                    route_ref = str(segment.get("route_ref", ""))
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
                    command_ref = assignment.get("command_ref")
                    if command_ref not in load["command_refs"]:
                        load["command_refs"].append(command_ref)
                    if objective_ref not in load["objective_refs"]:
                        load["objective_refs"].append(objective_ref)
                    load["combined_strength"] += strength
    else:
        # Compatibility fallback for campaign records that do not yet expose
        # enough ownership/command information for a multi-axis staff scheme.
        for participant in friendly_participants:
            if not isinstance(participant, Mapping):
                continue
            operation_ref = participant.get("operation_ref")
            strength_total = max(0, int(participant.get("strength", 0) or 0))
            location_refs = [str(x) for x in participant.get("location_refs", []) if isinstance(x, str)]
            location_strength = participant.get("location_strength") if isinstance(participant.get("location_strength"), Mapping) else {}
            commanders = [
                {"person_ref": row.get("person_ref"), "name": row.get("name")}
                for row in participant.get("commanders", [])
                if isinstance(row, Mapping)
            ]
            for origin_ref in location_refs:
                strength = max(0, int(location_strength.get(origin_ref, strength_total if len(location_refs) == 1 else 0) or 0))
                if strength <= 0:
                    continue
                try:
                    path = shortest_path(planner.read, origin_ref, strategic_target_ref, modes=("formation",))
                except ValueError:
                    continue
                projected = project_route_path(planner.read, path, strength=strength)
                command_routes.append({
                    "operation_ref": operation_ref,
                    "strength": strength,
                    "formation_count": participant.get("formation_count"),
                    "commanders": commanders,
                    "origin_ref": origin_ref,
                    "origin_name": _location_name(locations, origin_ref),
                    "objective_ref": strategic_target_ref,
                    "objective_name": _location_name(locations, strategic_target_ref),
                    **projected,
                })

    shared_bottlenecks: list[dict[str, Any]] = []
    for load in route_loads.values():
        throughput = max(0, int(load.get("daily_troop_throughput", 0) or 0))
        combined = max(0, int(load.get("combined_strength", 0) or 0))
        if len(load["command_refs"]) < 2 and (throughput <= 0 or combined <= throughput):
            continue
        load["minimum_troop_clearance_days_floor"] = int(math.ceil(combined / throughput)) if throughput > 0 and combined > 0 else None
        shared_bottlenecks.append(load)
    shared_bottlenecks.sort(key=lambda row: (-int(row.get("combined_strength", 0) or 0), str(row.get("route_ref", ""))))
    command_routes.sort(key=lambda row: (-int(row.get("strength", 0) or 0), str(row.get("command_ref") or row.get("operation_ref") or ""), str(row.get("origin_ref", ""))))
    return {
        "kind": "staff_route_capacity_baseline",
        "strategic_target_ref": strategic_target_ref,
        "strategic_target_name": _location_name(locations, strategic_target_ref),
        "campaign_region_ref": scheme.get("campaign_region_ref") if isinstance(scheme, Mapping) else None,
        "campaign_region_name": scheme.get("campaign_region_name") if isinstance(scheme, Mapping) else None,
        "campaign_scheme": scheme,
        "command_routes": command_routes,
        "shared_bottlenecks": shared_bottlenecks,
        "authority_rule": "planning projection only; this does not assign a route, authorize hostile entry, move a formation, or issue an order",
        "capacity_rule": "troop clearance is a floor from authored route throughput only; baggage, wagons, supply, rests, traffic spacing, enemy action, and other unrepresented burdens are not invented",
        "knowledge_rule": "campaign axes use current roster, current territorial control, and authored geography only; the projection does not expose private enemy deployments or fabricate reconnaissance",
    }