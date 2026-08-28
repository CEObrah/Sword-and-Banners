"""Player-safe campaign march-planning projection from existing route owners.

This module does not issue orders, move formations, authorize hostile entry, or
invent logistics. It exposes a bounded staff planning baseline from current
friendly force locations plus the authored physical route graph that the
campaign runtime already uses for movement.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sword_runtime.geography import shortest_path

_ROUTES_PATH = "game/data/world/routes.json"
_LOCATIONS_PATH = "game/data/world/locations.json"


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


def build_march_planning_baseline(
    planner: Any,
    *,
    friendly_participants: Sequence[Mapping[str, Any]],
    operational_area: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a bounded staff route/capacity baseline for current friendly commands."""
    if not isinstance(operational_area, Mapping):
        return None
    strategic_target_ref = operational_area.get("strategic_target_ref")
    if not isinstance(strategic_target_ref, str) or not strategic_target_ref:
        return None
    locations = _location_rows(planner.read)
    command_routes: list[dict[str, Any]] = []
    route_loads: dict[str, dict[str, Any]] = {}
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
            command_row = {
                "operation_ref": operation_ref,
                "strength": strength,
                "formation_count": participant.get("formation_count"),
                "commanders": commanders,
                "origin_ref": origin_ref,
                "origin_name": _location_name(locations, origin_ref),
                "strategic_target_ref": strategic_target_ref,
                "strategic_target_name": _location_name(locations, strategic_target_ref),
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
                    "operation_refs": [],
                    "combined_strength": 0,
                })
                if operation_ref not in load["operation_refs"]:
                    load["operation_refs"].append(operation_ref)
                load["combined_strength"] += strength
    shared_bottlenecks: list[dict[str, Any]] = []
    for load in route_loads.values():
        throughput = max(0, int(load.get("daily_troop_throughput", 0) or 0))
        combined = max(0, int(load.get("combined_strength", 0) or 0))
        if len(load["operation_refs"]) < 2 and (throughput <= 0 or combined <= throughput):
            continue
        load["minimum_troop_clearance_days_floor"] = int(math.ceil(combined / throughput)) if throughput > 0 and combined > 0 else None
        shared_bottlenecks.append(load)
    shared_bottlenecks.sort(key=lambda row: (-int(row.get("combined_strength", 0) or 0), str(row.get("route_ref", ""))))
    command_routes.sort(key=lambda row: (-int(row.get("strength", 0) or 0), str(row.get("operation_ref", "")), str(row.get("origin_ref", ""))))
    return {
        "kind": "staff_route_capacity_baseline",
        "strategic_target_ref": strategic_target_ref,
        "strategic_target_name": _location_name(locations, strategic_target_ref),
        "command_routes": command_routes,
        "shared_bottlenecks": shared_bottlenecks,
        "authority_rule": "planning projection only; this does not assign a route, authorize hostile entry, move a formation, or issue an order",
        "capacity_rule": "troop clearance is a floor from authored route throughput only; baggage, wagons, supply, rests, traffic spacing, enemy action, and other unrepresented burdens are not invented",
        "knowledge_rule": "route geometry is staff planning material; the projection does not expose private enemy deployments or fabricate reconnaissance",
    }
