from __future__ import annotations

import heapq
import math
from typing import Any, Callable, Iterable, Mapping

ROUTES_PATH = "game/data/world/routes.json"
LOCATIONS_PATH = "game/data/world/locations.json"
TRAVEL_RULES_PATH = "game/data/mechanics/travel-geography.json"
TERRITORY_PATH = "state/territory/control.json"


def _locations(read: Callable[[str], Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    doc = read(LOCATIONS_PATH)
    return {str(row.get("ref")): row for row in doc.get("locations", []) if isinstance(row, Mapping) and row.get("ref")}


def resolve_route_alias(read: Callable[[str], Mapping[str, Any]], route_ref: str) -> str:
    doc = read(ROUTES_PATH)
    aliases = doc.get("aliases", {}) if isinstance(doc.get("aliases"), Mapping) else {}
    seen: set[str] = set()
    current = str(route_ref)
    while current in aliases:
        if current in seen:
            raise ValueError(f"route alias cycle at {current}")
        seen.add(current)
        current = str(aliases[current])
    return current


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
    if not isinstance(state, Mapping):
        return True
    return str(state.get("status", "open")) not in {"closed", "destroyed", "blocked"}


def _edge_hours(read: Callable[[str], Mapping[str, Any]], route: Mapping[str, Any], mode: str) -> int:
    rules = read(TRAVEL_RULES_PATH)
    mode_factor = float((rules.get("mode_factors", {}) or {}).get(mode, 1.0))
    terrain_factor = float((rules.get("terrain_factors", {}) or {}).get(str(route.get("terrain", "plain")), 1.0))
    road_factor = float((rules.get("road_quality_factors", {}) or {}).get(str(route.get("road_quality", "maintained")), 1.0))
    base = max(1, int(route.get("duration_hours", route.get("hours", 24))))
    return max(1, int(math.ceil(base * mode_factor * terrain_factor * road_factor)))


def shortest_path(
    read: Callable[[str], Mapping[str, Any]],
    origin: str,
    destination: str,
    *,
    modes: Iterable[str],
    edge_allowed: Callable[[str, str, Mapping[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    origin = str(origin); destination = str(destination)
    if origin == destination:
        return {"ref": "route_same_location", "route_refs": [], "path": [origin], "duration_hours": 0, "modes": list(modes)}
    rows = _locations(read)
    if origin not in rows or destination not in rows:
        raise ValueError(f"unknown route endpoint: {origin} -> {destination}")
    requested = tuple(str(x) for x in modes)
    if not requested:
        raise ValueError("route planning requires at least one movement mode")
    doc = read(ROUTES_PATH)
    edges = list(doc.get("routes", [])) + list(doc.get("local_routes", []))
    graph: dict[str, list[tuple[int, str, str, str, Mapping[str, Any]]]] = {}
    for route in edges:
        if not isinstance(route, Mapping):
            continue
        allowed_modes = {str(x) for x in route.get("modes", [])}
        compatible = [mode for mode in requested if mode in allowed_modes]
        if not compatible or not route_is_usable(read, route):
            continue
        a, b = str(route.get("a", "")), str(route.get("b", ""))
        if a not in rows or b not in rows or a == b:
            continue
        # Choose the fastest compatible requested mode for generic messenger queries;
        # callers asking for one specific mode get exactly that mode.
        mode = min(compatible, key=lambda m: _edge_hours(read, route, m))
        cost = _edge_hours(read, route, mode)
        graph.setdefault(a, []).append((cost, b, str(route.get("ref")), mode, route))
        graph.setdefault(b, []).append((cost, a, str(route.get("ref")), mode, route))
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
    wanted = resolve_route_alias(read, route_ref)
    doc = read(ROUTES_PATH)
    return any(str(row.get("ref")) == wanted for row in doc.get("routes", []) if isinstance(row, Mapping))
