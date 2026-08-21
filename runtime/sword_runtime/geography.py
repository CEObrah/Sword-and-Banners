from __future__ import annotations

import heapq
import math
from typing import Any, Callable, Iterable, Mapping

from sword_runtime.strategic_crossings import crossing_delay_hours, crossing_mode_is_usable, crossing_operational_profile

ROUTES_PATH = "game/data/world/routes.json"
LOCATIONS_PATH = "game/data/world/locations.json"
TRAVEL_RULES_PATH = "game/data/mechanics/travel-geography.json"
TERRITORY_PATH = "state/territory/control.json"
DYNAMIC_GEOGRAPHY_PATH = "state/geography/dynamic.json"


def _locations(read: Callable[[str], Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    doc = read(LOCATIONS_PATH)
    rows = {str(row.get("ref")): row for row in doc.get("locations", []) if isinstance(row, Mapping) and row.get("ref")}
    try:
        dynamic = read(DYNAMIC_GEOGRAPHY_PATH)
    except (FileNotFoundError, KeyError):
        dynamic = {}
    if isinstance(dynamic, Mapping):
        for row in dynamic.get("locations", []):
            if isinstance(row, Mapping) and row.get("ref"):
                rows[str(row.get("ref"))] = row
    return rows


def _route_rows(read: Callable[[str], Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    doc = read(ROUTES_PATH)
    rows = [row for row in list(doc.get("routes", [])) + list(doc.get("local_routes", [])) if isinstance(row, Mapping)]
    try:
        dynamic = read(DYNAMIC_GEOGRAPHY_PATH)
    except (FileNotFoundError, KeyError):
        dynamic = {}
    if isinstance(dynamic, Mapping):
        rows.extend(row for row in dynamic.get("routes", []) if isinstance(row, Mapping))
    return rows


def location_chain(read: Callable[[str], Mapping[str, Any]], location_ref: str) -> list[str]:
    rows = _locations(read)
    current = str(location_ref)
    chain: list[str] = []
    seen: set[str] = set()
    while current in rows:
        if current in seen:
            raise ValueError(f"location hierarchy cycle at {current}")
        seen.add(current)
        chain.append(current)
        parent = rows[current].get("parent_ref")
        if not isinstance(parent, str) or not parent.startswith("loc_"):
            break
        current = parent
    return chain


def enclosing_fortification_site(read: Callable[[str], Mapping[str, Any]], location_ref: str) -> str | None:
    rows = _locations(read)
    current = str(location_ref)
    seen: set[str] = set()
    while current in rows and current not in seen:
        seen.add(current)
        row = rows[current]
        access_for = row.get("access_for_ref")
        if isinstance(access_for, str) and access_for in rows:
            access_site = rows[access_for]
            if bool(access_site.get("fortified")) and bool(access_site.get("strategic_node")):
                return access_for
        if bool(row.get("fortified")) and bool(row.get("strategic_node")) and row.get("fortification_profile_ref"):
            return current
        enclosed = row.get("contained_by_fortification_site_ref")
        if isinstance(enclosed, str) and enclosed:
            return enclosed
        if bool(row.get("fortified")) and bool(row.get("strategic_node")):
            return current
        parent = row.get("parent_ref")
        if not isinstance(parent, str) or not parent.startswith("loc_"):
            break
        current = parent
    return None


def demographic_anchor(read: Callable[[str], Mapping[str, Any]], location_ref: str, eligible_refs: Iterable[str]) -> str | None:
    eligible = set(str(x) for x in eligible_refs)
    rows = _locations(read)
    current = str(location_ref)
    seen: set[str] = set()
    while current in rows and current not in seen:
        seen.add(current)
        if current in eligible:
            return current
        row = rows[current]
        for key in ("demographic_parent_ref", "settlement_ref", "region_ref", "parent_ref", "access_node_ref"):
            nxt = row.get(key)
            if isinstance(nxt, str) and nxt.startswith("loc_") and nxt != current:
                current = nxt
                break
        else:
            return None
    return current if current in eligible else None


def _route_state(read: Callable[[str], Mapping[str, Any]]) -> Mapping[str, Any]:
    try:
        territory = read(TERRITORY_PATH)
    except (FileNotFoundError, KeyError):
        return {}
    states = territory.get("route_states", {}) if isinstance(territory, Mapping) else {}
    return states if isinstance(states, Mapping) else {}


def route_is_usable(read: Callable[[str], Mapping[str, Any]], route: Mapping[str, Any]) -> bool:
    state = _route_state(read).get(str(route.get("ref")), {})
    if isinstance(state, Mapping) and str(state.get("status", "open")) in {"closed", "destroyed", "blocked"}:
        return False
    crossing = crossing_operational_profile(read, route)
    if crossing is None:
        return True
    return int(crossing.get("daily_troop_throughput", 0)) > 0


def _edge_hours(read: Callable[[str], Mapping[str, Any]], route: Mapping[str, Any], mode: str) -> int:
    rules = read(TRAVEL_RULES_PATH)
    mode_factor = float((rules.get("mode_factors", {}) or {}).get(mode, 1.0))
    terrain_factor = float((rules.get("terrain_factors", {}) or {}).get(str(route.get("terrain", "plain")), 1.0))
    road_factor = float((rules.get("road_quality_factors", {}) or {}).get(str(route.get("road_quality", "maintained")), 1.0))
    base = max(1, int(route.get("duration_hours", route.get("hours", 24))))
    if not crossing_mode_is_usable(read, route, mode):
        raise ValueError(f"route crossing is unusable for movement mode {mode}")
    crossing_delay = crossing_delay_hours(read, route, mode)
    return max(1, int(math.ceil(base * mode_factor * terrain_factor * road_factor + crossing_delay)))


def _weighted_route_graph(
    read: Callable[[str], Mapping[str, Any]],
    requested: tuple[str, ...],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[tuple[int, str, str, str, Mapping[str, Any]]]]]:
    """Build one weighted physical route graph for a routing query.

    Crossing/serviceability reads can be materially more expensive than Dijkstra on
    the compact strategic graph.  Multi-target strategic review therefore reuses one
    graph build instead of rebuilding it once for every possible destination.
    """
    rows = _locations(read)
    graph: dict[str, list[tuple[int, str, str, str, Mapping[str, Any]]]] = {}
    for route in _route_rows(read):
        if not isinstance(route, Mapping):
            continue
        allowed_modes = {str(x) for x in route.get("modes", [])}
        compatible = [mode for mode in requested if mode in allowed_modes and crossing_mode_is_usable(read, route, mode)]
        if not compatible or not route_is_usable(read, route):
            continue
        a, b = str(route.get("a", "")), str(route.get("b", ""))
        if a not in rows or b not in rows or a == b:
            continue
        mode = min(compatible, key=lambda m: _edge_hours(read, route, m))
        cost = _edge_hours(read, route, mode)
        graph.setdefault(a, []).append((cost, b, str(route.get("ref")), mode, route))
        graph.setdefault(b, []).append((cost, a, str(route.get("ref")), mode, route))
    return rows, graph


def nearest_reachable_destination(
    read: Callable[[str], Mapping[str, Any]],
    origin: str,
    destinations: Iterable[str],
    *,
    modes: Iterable[str],
    edge_allowed: Callable[[str, str, Mapping[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Return the nearest physically reachable destination from one graph search.

    This is intended for bounded strategic target selection.  It does not replace
    exact formation movement admission: callers that omit ``edge_allowed`` are only
    proving a physical route exists, and the movement command must still validate
    sovereignty/access when the force actually marches.
    """
    origin = str(origin)
    targets = {str(x) for x in destinations if isinstance(x, str) and str(x)}
    requested = tuple(str(x) for x in modes)
    if not targets:
        raise ValueError("route planning requires at least one destination")
    if not requested:
        raise ValueError("route planning requires at least one movement mode")
    rows, graph = _weighted_route_graph(read, requested)
    if origin not in rows:
        raise ValueError(f"unknown route endpoint: {origin}")
    unknown = sorted(target for target in targets if target not in rows)
    if unknown:
        raise ValueError(f"unknown route destination: {unknown[0]}")
    if origin in targets:
        return {"destination": origin, "duration_hours": 0, "modes": list(requested)}
    queue: list[tuple[int, str]] = [(0, origin)]
    best = {origin: 0}
    while queue:
        cost, node = heapq.heappop(queue)
        if cost != best.get(node):
            continue
        if node in targets:
            return {"destination": node, "duration_hours": int(cost), "modes": list(requested)}
        for edge_cost, nxt, _ref, _mode, route in graph.get(node, []):
            if edge_allowed is not None and not edge_allowed(node, nxt, route):
                continue
            nc = cost + edge_cost
            if nc < best.get(nxt, 10**18):
                best[nxt] = nc
                heapq.heappush(queue, (nc, nxt))
    raise ValueError(f"no usable route from {origin} to any requested destination for modes {requested}")


def shortest_path(
    read: Callable[[str], Mapping[str, Any]],
    origin: str,
    destination: str,
    *,
    modes: Iterable[str],
    edge_allowed: Callable[[str, str, Mapping[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    origin = str(origin); destination = str(destination)
    requested = tuple(str(x) for x in modes)
    if origin == destination:
        return {"ref": "route_same_location", "route_refs": [], "path": [origin], "duration_hours": 0, "modes": list(requested)}
    if not requested:
        raise ValueError("route planning requires at least one movement mode")
    rows, graph = _weighted_route_graph(read, requested)
    if origin not in rows or destination not in rows:
        raise ValueError(f"unknown route endpoint: {origin} -> {destination}")
    queue: list[tuple[int, str]] = [(0, origin)]
    best = {origin: 0}
    previous: dict[str, tuple[str, str, str, int]] = {}
    while queue:
        cost, node = heapq.heappop(queue)
        if cost != best.get(node):
            continue
        if node == destination:
            break
        for edge_cost, nxt, ref, mode, route in graph.get(node, []):
            if edge_allowed is not None and not edge_allowed(node, nxt, route):
                continue
            nc = cost + edge_cost
            if nc < best.get(nxt, 10**18):
                best[nxt] = nc
                previous[nxt] = (node, ref, mode, edge_cost)
                heapq.heappush(queue, (nc, nxt))
    if destination not in best:
        raise ValueError(f"no usable route between {origin} and {destination} for modes {requested}")
    nodes = [destination]
    route_refs: list[str] = []
    edge_modes: list[str] = []
    edge_hours: list[int] = []
    cur = destination
    while cur != origin:
        prev, ref, mode, hours = previous[cur]
        nodes.append(prev); route_refs.append(ref); edge_modes.append(mode); edge_hours.append(hours); cur = prev
    nodes.reverse(); route_refs.reverse(); edge_modes.reverse(); edge_hours.reverse()
    return {
        "ref": route_refs[0] if len(route_refs) == 1 else "route_path",
        "route_refs": route_refs,
        "path": nodes,
        "edge_modes": edge_modes,
        "edge_hours": edge_hours,
        "duration_hours": int(best[destination]),
        "modes": list(requested),
    }


def route_exists(read: Callable[[str], Mapping[str, Any]], route_ref: str) -> bool:
    wanted = str(route_ref)
    return any(str(row.get("ref")) == wanted for row in _route_rows(read))
