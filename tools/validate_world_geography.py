#!/usr/bin/env python3
"""Focused authority/conservation checks for the routed world geography model."""
from __future__ import annotations

import heapq
import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
STATES = ("qin", "zhao", "chu", "wei", "han", "yan", "qi")
STRATEGIC_KINDS = {"capital", "city", "town", "fortress", "pass", "region", "frontier", "strategic_access", "settlement"}
INTERNAL_KINDS = {"facility", "institution", "gate", "compound", "scene_venue", "depot"}


def load(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _sum_nested_roles(by_location: dict[str, dict[str, int]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for roles in by_location.values():
        for role, value in roles.items():
            out[role] = out.get(role, 0) + int(value)
    return out


def _shortest_route_refs(routes: dict[str, Any], start: str, goal: str, mode: str) -> list[str] | None:
    adj: dict[str, list[tuple[str, str, float]]] = {}
    for row in routes.get("routes", []):
        if mode not in row.get("modes", []):
            continue
        a, b = row.get("a"), row.get("b")
        if not isinstance(a, str) or not isinstance(b, str):
            continue
        cost = float(row.get("hours", row.get("base_distance_units", 1)) or 1)
        adj.setdefault(a, []).append((b, row.get("ref", ""), cost))
        adj.setdefault(b, []).append((a, row.get("ref", ""), cost))
    q: list[tuple[float, str, tuple[str, ...]]] = [(0.0, start, ())]
    best: dict[str, float] = {start: 0.0}
    while q:
        cost, node, chain = heapq.heappop(q)
        if node == goal:
            return list(chain)
        if cost != best.get(node):
            continue
        for nxt, ref, edge_cost in adj.get(node, []):
            nc = cost + edge_cost
            if nc < best.get(nxt, float("inf")):
                best[nxt] = nc
                heapq.heappush(q, (nc, nxt, chain + (ref,)))
    return None


def validate(root: Path | None = None) -> list[str]:
    global ROOT
    if root is not None:
        ROOT = Path(root)
    errors: list[str] = []

    locations_doc = load("game/data/world/locations.json")
    locations = locations_doc.get("locations", [])
    loc_by_ref = {row.get("ref"): row for row in locations if isinstance(row, dict) and isinstance(row.get("ref"), str)}
    if len(loc_by_ref) != len(locations):
        errors.append("location refs are not unique")

    function_doc = load("game/data/world/location-functions.json")
    function_registry = function_doc.get("functions", {})
    role_semantics = function_doc.get("role_semantics", {})
    allowed_function_roles = set(role_semantics) if isinstance(role_semantics, dict) else set()
    if not isinstance(function_registry, dict) or not function_registry:
        errors.append("location function registry is missing or empty")
        function_registry = {}
    for function_name, definition in function_registry.items():
        if not isinstance(function_name, str) or not function_name or not isinstance(definition, dict):
            errors.append(f"invalid location function registry entry: {function_name!r}")
            continue
        roles = definition.get("roles")
        if not isinstance(roles, list) or not roles or not all(isinstance(role, str) and role in allowed_function_roles for role in roles):
            errors.append(f"location function {function_name} has invalid semantic roles")
        if not isinstance(definition.get("meaning"), str) or not definition.get("meaning", "").strip():
            errors.append(f"location function {function_name} must state its current meaning")

    # Location metadata declares only the functions the site actually needs. Flavor-only
    # sites remain legitimate scene/reference locations and must not acquire mutable
    # population or strategic authority merely to look "complete".
    for ref, row in loc_by_ref.items():
        functions = row.get("functions")
        if not isinstance(row.get("flavor_only"), bool):
            errors.append(f"location {ref} must explicitly classify flavor_only")
        if not isinstance(functions, list) or not functions or not all(isinstance(x, str) and x for x in functions):
            errors.append(f"location {ref} must declare at least one current function")
        else:
            unknown_functions = sorted(set(functions) - set(function_registry))
            if unknown_functions:
                errors.append(f"location {ref} declares unregistered functions: {unknown_functions}")
            if row.get("flavor_only") is True:
                non_scene_roles = {
                    role
                    for function_name in functions
                    for role in function_registry.get(function_name, {}).get("roles", [])
                    if role != "scene_anchor"
                }
                if non_scene_roles:
                    errors.append(f"flavor-only location {ref} declares mechanical/strategic function roles: {sorted(non_scene_roles)}")
        if row.get("demographic_role") == "facility" and row.get("national_population_eligible") is not False:
            errors.append(f"facility {ref} cannot own national demographic population")
        if row.get("flavor_only") is True:
            if row.get("strategic_node") is True:
                errors.append(f"flavor-only location {ref} cannot be a strategic node")
            if row.get("national_population_eligible") is True:
                errors.append(f"flavor-only location {ref} cannot be a national population owner")
        if row.get("strategic_node") is True and not ({"movement", "chokepoint", "fortification", "military", "politics", "market", "supply", "battlefield", "recruitment", "information"} & set(functions or [])):
            errors.append(f"strategic location {ref} has no strategic gameplay function")

    # Hierarchy is exact enough to resolve containment but never a second population owner.
    top_roots = {f"state_{s}" for s in STATES} | {"minor_polity_quanrong", "minor_polity_yotanwa_confederation", "minor_polity_northern_steppe", "polity_jo"}
    for ref, row in loc_by_ref.items():
        parent = row.get("parent_ref")
        if isinstance(parent, str) and parent not in loc_by_ref and parent not in top_roots:
            errors.append(f"location {ref} parent does not resolve: {parent}")
        region = row.get("region_ref")
        if isinstance(region, str) and region not in loc_by_ref:
            errors.append(f"location {ref} region does not resolve: {region}")
        enclosure = row.get("contained_by_fortification_site_ref")
        if isinstance(enclosure, str) and enclosure not in loc_by_ref:
            errors.append(f"location {ref} fortification enclosure does not resolve: {enclosure}")
    for ref in loc_by_ref:
        seen: set[str] = set()
        cur = ref
        while cur in loc_by_ref:
            if cur in seen:
                errors.append(f"location hierarchy cycle at {ref}")
                break
            seen.add(cur)
            parent = loc_by_ref[cur].get("parent_ref")
            if not isinstance(parent, str):
                break
            cur = parent

    routes = load("game/data/world/routes.json")
    strategic = routes.get("routes", [])
    local_routes = routes.get("local_routes", [])
    route_by_ref: dict[str, dict[str, Any]] = {}
    unordered_edges: dict[tuple[str, str], str] = {}
    for row in strategic:
        ref = row.get("ref")
        if not isinstance(ref, str) or ref in route_by_ref:
            errors.append(f"invalid/duplicate strategic route ref: {ref}")
            continue
        route_by_ref[ref] = row
        a, b = row.get("a"), row.get("b")
        if a not in loc_by_ref or b not in loc_by_ref:
            errors.append(f"route {ref} endpoint does not resolve: {a} -> {b}")
            continue
        if not loc_by_ref[a].get("strategic_node") or not loc_by_ref[b].get("strategic_node"):
            errors.append(f"strategic route {ref} enters non-strategic endpoint {a} or {b}")
        if row.get("scope") != "strategic":
            errors.append(f"route {ref} missing strategic scope")
        key = tuple(sorted((a, b)))
        if key in unordered_edges:
            errors.append(f"duplicate strategic edge {unordered_edges[key]} and {ref}")
        unordered_edges[key] = ref
        sa, sb = loc_by_ref[a].get("state"), loc_by_ref[b].get("state")
        if sa and sb and sa != sb and not row.get("border_crossing"):
            errors.append(f"cross-state route {ref} lacks border_crossing metadata")
        control = row.get("control_site_ref")
        if control is not None and control not in loc_by_ref:
            errors.append(f"route {ref} control site does not resolve: {control}")

    local_route_refs: set[str] = set()
    for row in local_routes:
        ref = row.get("ref")
        if not isinstance(ref, str) or ref in local_route_refs or ref in route_by_ref:
            errors.append(f"invalid/duplicate local route ref: {ref}")
            continue
        local_route_refs.add(ref)
        a, b = row.get("a"), row.get("b")
        if a not in loc_by_ref or b not in loc_by_ref:
            errors.append(f"local route {ref} endpoint does not resolve: {a} -> {b}")
        if row.get("scope") != "local":
            errors.append(f"local route {ref} missing local scope")

    # All current strategic nodes belong to one queryable strategic network;
    # local-only children are intentionally excluded from this connectivity gate.
    strategic_nodes = {ref for ref, row in loc_by_ref.items() if row.get("strategic_node") is True}
    adjacency: dict[str, set[str]] = {ref: set() for ref in strategic_nodes}
    for row in strategic:
        a, b = row.get("a"), row.get("b")
        if a in adjacency and b in adjacency:
            adjacency[a].add(b)
            adjacency[b].add(a)
    isolated = sorted(ref for ref, neighbors in adjacency.items() if not neighbors)
    if isolated:
        errors.append(f"isolated strategic locations: {isolated}")
    if strategic_nodes:
        start_ref = next(iter(strategic_nodes))
        seen_nodes = {start_ref}
        stack = [start_ref]
        while stack:
            node = stack.pop()
            for nxt in adjacency.get(node, set()):
                if nxt not in seen_nodes:
                    seen_nodes.add(nxt)
                    stack.append(nxt)
        missing = sorted(strategic_nodes - seen_nodes)
        if missing:
            errors.append(f"disconnected strategic locations: {missing}")

    control = load("state/territory/control.json")
    route_states = control.get("route_states", {})
    for ref, row in route_states.items():
        if ref not in route_by_ref:
            errors.append(f"persistent route state has no strategic route: {ref}")
        cs = row.get("control_site_ref") if isinstance(row, dict) else None
        if isinstance(cs, str) and cs not in loc_by_ref:
            errors.append(f"route state {ref} control site does not resolve: {cs}")

    # Static chokepoint/fort authority must name the exact edges it controls.
    fort_doc = load("game/data/world/fortification-profiles.json")
    profiles = fort_doc.get("profiles", [])
    profile_by_site = {p.get("site_ref"): p for p in profiles if isinstance(p, dict)}
    profile_ids = {p.get("profile_id") for p in profiles if isinstance(p, dict)}
    for p in profiles:
        site = p.get("site_ref")
        if site not in loc_by_ref:
            errors.append(f"fortification profile site does not resolve: {site}")
        if not isinstance(p.get("physical_baseline"), dict):
            errors.append(f"fortification profile {p.get('profile_id')} lacks physical baseline")
        for rr in p.get("route_control_refs", []):
            if rr not in route_by_ref:
                errors.append(f"fortification {site} controls nonexistent route {rr}")
            elif route_by_ref[rr].get("control_site_ref") != site:
                errors.append(f"fortification {site} route-control disagreement on {rr}")
    for ref, loc in loc_by_ref.items():
        if loc.get("kind") == "pass" and loc.get("chokepoint") and not profile_by_site.get(ref, {}).get("route_control_refs"):
            errors.append(f"chokepoint pass {ref} controls no authoritative routes")

    fort_index = load("state/fortifications/index.json")
    static = fort_index.get("static_profiles", {})
    for site, p in profile_by_site.items():
        if static.get(site, {}).get("profile_id") != p.get("profile_id"):
            errors.append(f"fortification discovery index mismatch: {site}")
    for site, row in fort_index.get("fortifications", {}).items():
        if row.get("location_ref", site) not in loc_by_ref:
            errors.append(f"materialized fortification has invalid site: {site}")

    siege_inv = load("state/inv/tang-manor-siege-inventory.json")
    if siege_inv.get("fortification_site_ref") != "loc_tang_manor" or siege_inv.get("fortification_profile_ref") not in profile_ids:
        errors.append("Tang Manor siege inventory is not linked to generic fortification authority")
    # Tang Manor uses nested exact fortifications. Internal children must name a
    # real enclosing fortified ancestor, but that ancestor may be Sword Manor or
    # the Inner Citadel rather than always the outer estate wall.
    tang_root = "loc_tang_manor"
    for ref, loc in loc_by_ref.items():
        chain = []
        cur = ref
        seen = set()
        while cur in loc_by_ref and cur not in seen:
            seen.add(cur); chain.append(cur)
            parent = loc_by_ref[cur].get("parent_ref")
            if not isinstance(parent, str): break
            cur = parent
        if tang_root not in chain and ref != tang_root:
            continue
        enclosure = loc.get("contained_by_fortification_site_ref")
        if enclosure is None:
            continue
        if enclosure not in chain[1:]:
            errors.append(f"Tang Manor internal child names non-ancestor fortification enclosure: {ref} -> {enclosure}")
        elif not (loc_by_ref.get(enclosure, {}).get("fortified") and loc_by_ref.get(enclosure, {}).get("strategic_node")):
            errors.append(f"Tang Manor internal child enclosure is not a fortified strategic ancestor: {ref} -> {enclosure}")

    # Population/local economy: only legitimate demographic owners may hold national people/production.
    for state in STATES:
        pop = load(f"state/population/{state}.json")
        sites = pop.get("local_population", {}).get("sites", {})
        for ref in sites:
            loc = loc_by_ref.get(ref)
            if not loc or not loc.get("national_population_eligible"):
                errors.append(f"{state} local population assigned to ineligible location: {ref}")
        strata = pop.get("strata", {})
        civilian_keys = [k for k in strata if k not in {"active_military", "private_household_military", "foreign_military_service", "rebel_military", "displaced", "deaths_cumulative"}]
        for key in civilian_keys:
            local_total = sum(int(row.get("civilian_strata", {}).get(key, 0)) for row in sites.values())
            if local_total != int(strata.get(key, 0)):
                errors.append(f"{state} civilian local partition mismatch for {key}: {local_total}!={strata.get(key,0)}")
        native = sum(int(row.get("serving_native_military", 0)) for row in sites.values())
        if native != int(strata.get("active_military", 0)):
            errors.append(f"{state} native military local partition mismatch: {native}!={strata.get('active_military',0)}")
        private = sum(int(row.get("private_household_military", 0)) for row in sites.values())
        if private != int(strata.get("private_household_military", 0)):
            errors.append(f"{state} private military local partition mismatch: {private}!={strata.get('private_household_military',0)}")
        for ref, row in sites.items():
            computed = int(row.get("civilian_population", 0)) + int(row.get("service_population", 0)) + int(row.get("candidates_reserved", 0)) + int(row.get("displaced", 0))
            if computed != int(row.get("initial_population", computed)):
                errors.append(f"{state} local site population balance mismatch: {ref}")

        econ = load(f"state/economy/private/{state}.json")
        regions = econ.get("local_regions", {}).get("regions", {})
        if set(regions) != set(sites):
            errors.append(f"{state} local economy sites do not match population sites")
        for ref in regions:
            if not loc_by_ref.get(ref, {}).get("national_population_eligible"):
                errors.append(f"{state} local economy attached to ineligible facility: {ref}")

    # State forces: spatial disposition is a partition of the exact available force, not another owner.
    for state in STATES:
        force = load(f"state/forces/state-{state}.json")
        if _sum_nested_roles(force.get("available_by_location", {})) != {k: int(v) for k, v in force.get("available_by_role", {}).items()}:
            errors.append(f"{state} available_by_location does not conserve role totals")
        for ref in force.get("available_by_location", {}):
            if ref not in loc_by_ref:
                errors.append(f"{state} force disposition location does not resolve: {ref}")
        if force.get("geographic_disposition", {}).get("authority") is not True:
            errors.append(f"{state} force has no authoritative regional disposition")
        equipment_by_location = force.get("available_equipment_by_location", {})
        if equipment_by_location:
            equipment_totals = _sum_nested_roles(equipment_by_location)
            expected_equipment = {str(k): int(v) for k, v in force.get("available_equipment_units_by_role", {}).items()}
            if equipment_totals != expected_equipment:
                errors.append(f"{state} force geographic equipment partition does not reconcile to exact role stock")
            for location_ref in equipment_by_location:
                if location_ref not in loc_by_ref:
                    errors.append(f"{state} force equipment is parked at invalid location {location_ref}")

    # All persistent formation locations resolve; formation remains allocation, not body creation.
    for path in sorted((ROOT / "state/formations").glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        ref = row.get("location_ref")
        if isinstance(ref, str) and ref not in loc_by_ref:
            errors.append(f"formation {row.get('ref', path.stem)} has invalid location {ref}")

    # Operations are organizational overlays only: every current formation and
    # operation location must resolve, while the operation owns no independent bodies.
    formation_refs: set[str] = set()
    for path in sorted((ROOT / "state/formations").glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        ref = row.get("formation_ref") or row.get("ref") or row.get("owner_id")
        if isinstance(ref, str):
            formation_refs.add(ref)
    op_index = load("state/operations/index.json").get("operations", {})
    for op_ref, op_path in op_index.items():
        if not isinstance(op_path, str) or not (ROOT / op_path).is_file():
            errors.append(f"operation index path does not resolve: {op_ref}:{op_path}")
            continue
        op = load(op_path)
        if op.get("operation_ref") != op_ref:
            errors.append(f"operation index/ref disagreement: {op_ref}")
        loc = op.get("location_ref")
        if isinstance(loc, str) and loc not in loc_by_ref:
            errors.append(f"operation {op_ref} has invalid location {loc}")
        for formation_ref in op.get("formation_refs", []):
            if formation_ref not in formation_refs:
                errors.append(f"operation {op_ref} references missing formation {formation_ref}")
        if op.get("headcount") or op.get("manpower") or op.get("bodies"):
            errors.append(f"operation {op_ref} appears to own manpower instead of organizing formations")

    # Mount pools: regional reserve plus formation allocations exactly conserve each type.
    for path in sorted((ROOT / "state/mounts").glob("*.json")):
        pool = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(pool.get("types"), dict):
            continue
        reserve = _sum_nested_roles(pool.get("regional_reserve", {}))
        allocated: dict[str, int] = {}
        for rolemap in pool.get("allocated_to_formations", {}).values():
            for mount_type, n in rolemap.items():
                allocated[mount_type] = allocated.get(mount_type, 0) + int(n)
        for mount_type, total in pool.get("types", {}).items():
            if reserve.get(mount_type, 0) + allocated.get(mount_type, 0) != int(total):
                errors.append(f"mount pool {pool.get('owner_id')} does not conserve {mount_type}")
        for ref in pool.get("regional_reserve", {}):
            if ref not in loc_by_ref:
                errors.append(f"mount pool {pool.get('owner_id')} has invalid regional reserve location {ref}")

    # Four Bastion Corps are permanent House Tang exact force owners, never mercenary-market bodies.
    bastion_expected = {
        "force_bastion_iron_rampart": 75000,
        "force_bastion_red_crane": 16000,
        "force_bastion_white_lantern": 10000,
        "force_bastion_deep_earth": 9000,
    }
    owner_index = load("state/index/owner-index.json").get("owners", {})
    bastion_total = 0
    for force_id, expected_heads in bastion_expected.items():
        owner_path = owner_index.get(force_id)
        if not owner_path or not (ROOT / owner_path).is_file():
            errors.append(f"Four Bastion Corps owner does not resolve: {force_id}")
            continue
        force = load(owner_path)
        heads = int(force.get("headcount", 0))
        bastion_total += heads
        if heads != expected_heads:
            errors.append(f"{force_id} headcount {heads} != establishment {expected_heads}")
        if force.get("institution_ref") != "institution_four_bastion_corps" or force.get("administrative_owner") != "house_tang":
            errors.append(f"{force_id} is not a permanent House Tang Four Bastion Corps force owner")
    if bastion_total != 110000:
        errors.append(f"Four Bastion Corps exact owner total is {bastion_total}, expected 110000")
    for stale in ("state/merc/iron-rampart.json", "state/merc/red-crane.json", "state/merc/white-lantern.json", "state/merc/deep-earth.json"):
        if (ROOT / stale).exists():
            errors.append(f"obsolete Bastion mercenary owner still exists: {stale}")

    # Capability records may describe potential, never manufacture owner bodies.
    for path in sorted((ROOT / "state/manpower-capability").glob("*.json")):
        cap = json.loads(path.read_text(encoding="utf-8"))
        if cap.get("authority") is not False:
            errors.append(f"capability profile is not authority:false: {path.name}")
        source = cap.get("source_owner")
        if cap.get("current_owner_required") and source not in owner_index:
            errors.append(f"required current capability owner does not resolve: {path.name}:{source}")

    # Current force universe classification is complete and explicitly separates exact owners from zero-body projections.
    class_index = load("state/index/military-owner-classification.json")
    class_rows = class_index.get("classes", {}) if isinstance(class_index, dict) else {}
    classified_paths = {str(row.get("path")) for rows in class_rows.values() for row in rows if isinstance(row, dict) and row.get("path")}
    for path in sorted((ROOT / "state/forces").glob("*.json")):
        rel = path.relative_to(ROOT).as_posix()
        if rel not in classified_paths:
            errors.append(f"exact force owner missing from military universe classification: {rel}")
    for path in sorted((ROOT / "state/merc").rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("owner_id") and path.relative_to(ROOT).as_posix() not in classified_paths:
            errors.append(f"mercenary owner/registry missing from military universe classification: {path.relative_to(ROOT).as_posix()}")
    for path in sorted((ROOT / "state/formations").glob("*.json")):
        if path.relative_to(ROOT).as_posix() not in classified_paths:
            errors.append(f"formation missing from military universe classification: {path.name}")
    if any(row.get("ref") == "merc.regional.pool" and row.get("projected_total") is None for row in class_rows.get("mercenary_registry_zero_bodies", [])):
        errors.append("regional mercenary registry classification is missing its projected total")

    # Institutions and depots are physically routed without becoming demographic or manpower owners.
    for path in sorted((ROOT / "state/institutions").glob("*.json")):
        inst = json.loads(path.read_text(encoding="utf-8"))
        state = inst.get("state")
        if state in STATES:
            loc = inst.get("location_ref")
            if loc not in loc_by_ref:
                errors.append(f"institution {inst.get('owner_id')} lacks valid geographic headquarters")
            if inst.get("geography", {}).get("owns_local_population") is not False:
                errors.append(f"institution {inst.get('owner_id')} may be mistaken for a demographic owner")
            for region in inst.get("service_region_refs", []):
                if region not in loc_by_ref or loc_by_ref[region].get("kind") != "region":
                    errors.append(f"institution {inst.get('owner_id')} has invalid service region {region}")
    for path in sorted((ROOT / "state/depots").rglob("*.json")):
        depot = json.loads(path.read_text(encoding="utf-8"))
        if depot.get("location_ref") not in loc_by_ref:
            errors.append(f"depot {depot.get('owner_id')} location does not resolve")
        if depot.get("geography", {}).get("owns_local_population") is not False:
            errors.append(f"depot {depot.get('owner_id')} may be mistaken for a demographic owner")
        geo = depot.get("geography", {})
        access = geo.get("access_node_ref")
        if isinstance(access, str) and access not in loc_by_ref:
            errors.append(f"depot {depot.get('owner_id')} access node does not resolve: {access}")
        if depot.get("depot_kind") == "fortified_site_garrison":
            site = depot.get("site_ref")
            if site not in profile_by_site:
                errors.append(f"fortified-site depot {depot.get('owner_id')} has no exact fortification profile: {site}")
            if depot.get("location_ref") != site:
                errors.append(f"fortified-site depot {depot.get('owner_id')} is not physically at its site")
            if geo.get("owns_demographic_production") is not False:
                errors.append(f"fortified-site depot {depot.get('owner_id')} may be mistaken for an economic/demographic owner")
            if depot.get("hot_state", {}).get("status") != "hot":
                errors.append(f"materialized fortified-site depot {depot.get('owner_id')} is not marked hot")

    # Non-geographic workflow routers must declare their namespace explicitly so
    # `route_ref` cannot be mistaken for strategic-road authority.
    contact_routes = load("game/data/politics/contact-routes.json")
    if contact_routes.get("geographic_route_authority") is not False or contact_routes.get("route_domain") != "institutional_contact":
        errors.append("institutional contact routes are not explicitly separated from geographic route authority")
    process_routes = load("state/index/institutional-process-routing.json")
    if process_routes.get("authority") is not False or process_routes.get("geographic_route_authority") is not False or process_routes.get("route_domain") != "institutional_process":
        errors.append("institutional process routing is not explicitly separated from geographic route authority")
    runtime_state = load("state/runtime.json")
    for host_ref, host in runtime_state.get("hosts", {}).items():
        if not isinstance(host, dict) or not isinstance(host.get("route_ref"), str):
            continue
        rr = host["route_ref"]
        if rr.startswith("contact_") and host.get("route_domain") != "institutional_contact":
            errors.append(f"runtime host {host_ref} has an unclassified contact route_ref")
        if rr.startswith("process_") and host.get("route_domain") != "institutional_process":
            errors.append(f"runtime host {host_ref} has an unclassified institutional process route_ref")

    # Merchant houses retain capital/credit authority only; their geographic home
    # is a legitimate settlement anchor and never an implicit physical stock owner.
    merchant_registry = load("state/economy/merchant-houses.json")
    for merchant_ref, merchant in merchant_registry.get("houses", {}).items():
        home = merchant.get("home_market_location_ref")
        if home not in loc_by_ref:
            errors.append(f"merchant house {merchant_ref} has invalid home market location {home}")
        elif loc_by_ref[home].get("kind") not in {"capital", "city", "town", "settlement"}:
            errors.append(f"merchant house {merchant_ref} home market is not a settlement-scale location: {home}")
        geo = merchant.get("geography", {})
        if geo.get("owns_physical_market_stock") is not False or geo.get("owns_local_population") is not False:
            errors.append(f"merchant house {merchant_ref} geography conflates capital with physical stock/population")

    # Current supply contracts resolve to the authoritative graph and require their declared route.
    supply = load("state/contract/tang-supply-contracts.json")
    for record in supply.get("records", []):
        facts = record.get("facts", {})
        if not isinstance(facts, dict) or not facts.get("route_ref"):
            continue
        rr = str(facts["route_ref"])
        if rr not in route_by_ref:
            errors.append(f"supply contract route does not resolve: {facts['route_ref']}")
            continue
        source, dest = facts.get("source_location_ref"), facts.get("delivery_location_ref")
        chain = _shortest_route_refs(routes, source, dest, "convoy") if source in loc_by_ref and dest in loc_by_ref else None
        if not chain:
            errors.append(f"no convoy path for supply contract {record.get('record_id')}")
        elif rr not in chain:
            errors.append(f"declared supply route {rr} is not on convoy path for {record.get('record_id')}")

    # Diagnostic topology invariants from actual graph, not narrative assumptions.
    chain = _shortest_route_refs(routes, "loc_kankoku_pass", "loc_kanyou", "formation")
    if not chain:
        errors.append("Kankoku to Kanyou has no formation route")
    else:
        tang_refs = {r for r in chain if "tang_manor" in r}
        if tang_refs:
            errors.append(f"Kankoku->Kanyou incorrectly routes through Tang Manor: {sorted(tang_refs)}")
    if not _shortest_route_refs(routes, "loc_qin_regional_03", "loc_ryouyou", "formation"):
        errors.append("Qin northern frontier to Ryouyou has no strategic formation route")

    if any(row.get("kind") == "region" and row.get("fortified") for row in locations):
        errors.append("broad demographic region is incorrectly marked as a fortified site")

    # Minor-polity readiness is explicitly non-manpower until exact owners exist.
    minor = load("game/data/world/minor-polities.json")
    quanrong = minor.get("polities", {}).get("minor_polity_quanrong", {})
    if quanrong.get("exact_population_ref") is not None or quanrong.get("exact_force_ref") is not None:
        errors.append("Quanrong cold/readiness representation was silently converted into exact manpower")

    jo = minor.get("polities", {}).get("minor_polity_jo", {})
    for key, expected in (("polity_ref", "polity_jo"), ("exact_population_ref", "population_jo"), ("exact_force_ref", "force_jo")):
        if jo.get(key) != expected:
            errors.append(f"Jo living minor-polity authority missing {key}: {expected}")
    if "loc_jo_city" not in loc_by_ref or "loc_jo_mountain_region" not in loc_by_ref:
        errors.append("Jo living polity lacks its city/territorial geography")
    else:
        for neighbor in ("loc_zhao_regional_04", "loc_wei_regional_03", "loc_chu_regional_02"):
            if not _shortest_route_refs(routes, "loc_jo_city", neighbor, "formation"):
                errors.append(f"Jo lacks strategic formation route to {neighbor}")
    try:
        jo_pop = load("state/population/jo.json"); jo_force = load("state/forces/jo.json")
        active = int(jo_pop.get("strata", {}).get("active_military", 0))
        if int(jo_force.get("headcount", 0)) != active:
            errors.append("Jo exact force does not reconcile to Jo active_military population")
    except Exception as exc:
        errors.append(f"Jo exact authority failed to load: {exc}")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(f"validate_world_geography: FAIL ({len(errors)} errors)")
        for e in errors:
            print(" - " + e)
        return 1
    print("validate_world_geography: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
