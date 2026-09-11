"""Universal deterministic land, enclosure and development physics.

This module deliberately owns no population, treasury, political control or construction
inventory.  It makes finite land and wall geometry explicit, then lets the existing
construction/economy layer reserve the real silver, material stock, labor and time.
The same functions apply to Houses, settlements, fortresses and sovereign polities.
"""
from __future__ import annotations

from copy import deepcopy
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

LAND_RULES_PATH = "game/data/mechanics/land-development.json"
LAND_STATE_PATH = "state/development/land.json"
LOCATIONS_PATH = "game/data/world/locations.json"
FORTIFICATION_PROFILES_PATH = "game/data/world/fortification-profiles.json"
CONSTRUCTION_PHYSICS_PATH = "game/data/mechanics/construction-physics.json"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(v: float) -> float:
    return round(float(v), 6)


def rectangle_dimensions_from_perimeter(perimeter_km: float, aspect_ratio: float) -> tuple[float, float, float]:
    """Return long side, short side and area for a rectangle with exact perimeter."""
    p = max(0.0, float(perimeter_km))
    r = max(1.0, float(aspect_ratio))
    short = p / (2.0 * (r + 1.0)) if p > 0 else 0.0
    long = r * short
    return _round(long), _round(short), _round(long * short)


def rectangle_dimensions_from_area(area_km2: float, aspect_ratio: float) -> tuple[float, float, float]:
    a = max(0.0, float(area_km2))
    r = max(1.0, float(aspect_ratio))
    short = math.sqrt(a / r) if a > 0 else 0.0
    long = r * short
    perimeter = 2.0 * (long + short)
    return _round(long), _round(short), _round(perimeter)


def stadium_geometry_from_area_perimeter(area_km2: float, perimeter_km: float) -> dict[str, float]:
    """Solve A=2rL+pi r^2 and P=2L+2pi r for a stadium geometry."""
    area = max(0.0, float(area_km2)); perimeter = max(0.0, float(perimeter_km))
    if area <= 0 or perimeter <= 0:
        raise ValueError("stadium geometry requires positive area and perimeter")
    # Substitute L=P/2-pi*r into A=P*r-pi*r^2.
    disc = perimeter * perimeter - 4.0 * math.pi * area
    if disc < -1e-9:
        raise ValueError("area/perimeter pair cannot form a stadium")
    disc = max(0.0, disc)
    roots = [(perimeter + math.sqrt(disc)) / (2.0 * math.pi), (perimeter - math.sqrt(disc)) / (2.0 * math.pi)]
    candidates = []
    for r in roots:
        L = perimeter / 2.0 - math.pi * r
        if r > 0 and L >= -1e-9:
            candidates.append((r, max(0.0, L)))
    if not candidates:
        raise ValueError("area/perimeter pair has no nonnegative stadium straight section")
    r, L = min(candidates, key=lambda x: x[0])
    return {"radius_km": _round(r), "straight_length_km": _round(L)}


def _sum_uses(mapping: Mapping[str, Any] | None) -> float:
    if not isinstance(mapping, Mapping):
        return 0.0
    return sum(max(0.0, _num(v)) for v in mapping.values())


def validate_land_registry(registry: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if str(registry.get("schema")) != "land-development-registry":
        errors.append("invalid land registry schema")
    regions = registry.get("regions", {}) if isinstance(registry.get("regions"), Mapping) else {}
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), Mapping) else {}
    holdings = registry.get("holdings", {}) if isinstance(registry.get("holdings"), Mapping) else {}
    for ref, row in regions.items():
        if not isinstance(row, Mapping):
            errors.append(f"{ref}: invalid region row"); continue
        area = max(0.0, _num(row.get("area_km2")))
        uses = _sum_uses(row.get("land_use_km2"))
        child = max(0.0, _num(row.get("nested_site_parcels_km2")))
        if abs((uses + child) - area) > max(1e-5, area * 1e-7):
            errors.append(f"{ref}: region land use + nested parcels does not conserve area")
    child_area_by_parent: dict[str, dict[str, float]] = {}
    for child_ref, child_row in sites.items():
        if not isinstance(child_row, Mapping):
            continue
        parent_ref = child_row.get("parent_site_ref")
        if not isinstance(parent_ref, str) or not parent_ref:
            continue
        if parent_ref not in sites:
            errors.append(f"{child_ref}: parent site is missing")
            continue
        zone = str(child_row.get("placement_zone_in_parent", "inside_defended_perimeter"))
        if zone not in {"inside_defended_perimeter", "outside_defended_perimeter"}:
            errors.append(f"{child_ref}: invalid placement_zone_in_parent")
            continue
        bucket = child_area_by_parent.setdefault(parent_ref, {"inside_defended_perimeter": 0.0, "outside_defended_perimeter": 0.0})
        bucket[zone] += max(0.0, _num(child_row.get("parcel_area_km2")))

    for ref, row in sites.items():
        if not isinstance(row, Mapping):
            errors.append(f"{ref}: invalid site row"); continue
        parcel = max(0.0, _num(row.get("parcel_area_km2")))
        enclosed = max(0.0, _num(row.get("enclosed_area_km2")))
        if enclosed > parcel + 1e-6:
            errors.append(f"{ref}: enclosure exceeds parcel")
        children = child_area_by_parent.get(ref, {})
        nested_inside = max(0.0, _num(children.get("inside_defended_perimeter")))
        nested_outside = max(0.0, _num(children.get("outside_defended_perimeter")))
        if nested_inside > enclosed + 1e-6:
            errors.append(f"{ref}: enclosed nested sites exceed enclosure")
        if nested_outside > max(0.0, parcel - enclosed) + 1e-6:
            errors.append(f"{ref}: external nested sites exceed external parcel")
        eu = _sum_uses(row.get("enclosed_land_use_km2")); xu = _sum_uses(row.get("external_land_use_km2"))
        if abs((eu + nested_inside) - enclosed) > max(1e-5, parcel * 1e-7):
            errors.append(f"{ref}: enclosed land use + nested sites does not conserve enclosed area")
        if abs((xu + nested_outside) - max(0.0, parcel - enclosed)) > max(1e-5, parcel * 1e-7):
            errors.append(f"{ref}: external land use + nested sites does not conserve external parcel")
        reserved = row.get("reserved_land_km2", {}) if isinstance(row.get("reserved_land_km2"), Mapping) else {}
        if any(_num(v) < -1e-9 for v in reserved.values()):
            errors.append(f"{ref}: negative reserved land")
    for ref, row in holdings.items():
        if not isinstance(row, Mapping):
            errors.append(f"{ref}: invalid holding row"); continue
        area = max(0.0, _num(row.get("area_km2")))
        if area <= 0:
            errors.append(f"{ref}: holding must own positive land")
        site_ref = row.get("site_ref")
        if isinstance(site_ref, str) and site_ref:
            site = sites.get(site_ref)
            if not isinstance(site, Mapping):
                errors.append(f"{ref}: holding site is missing")
            elif _num(site.get("parcel_area_km2")) > area + 1e-6:
                errors.append(f"{ref}: site parcel exceeds holding area")
    return errors



def nested_site_children(registry: Mapping[str, Any], site_ref: str, *, recursive: bool = False) -> list[str]:
    """Return stable child-site refs physically nested inside ``site_ref``.

    Child parcels are one use of the parent parcel, not extra sovereign land.  The
    helper is intentionally representation-neutral: a House citadel, a capital's
    inner city, and a generated fortress keep all using the same containment rule.
    """
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), Mapping) else {}
    direct = sorted(
        str(ref) for ref, row in sites.items()
        if isinstance(row, Mapping) and str(row.get("parent_site_ref", "")) == str(site_ref)
    )
    if not recursive:
        return direct
    out: list[str] = []
    stack = list(reversed(direct))
    while stack:
        ref = stack.pop()
        if ref in out:
            continue
        out.append(ref)
        children = sorted(
            str(child_ref) for child_ref, row in sites.items()
            if isinstance(row, Mapping) and str(row.get("parent_site_ref", "")) == ref
        )
        stack.extend(reversed(children))
    return out


def enclosure_chain(registry: Mapping[str, Any], site_ref: str) -> list[str]:
    """Return outer-to-inner defended containment ending at ``site_ref``.

    The chain follows physical parent-site containment only.  It never implies that
    capturing an outer layer captures an inner layer or transfers its stocks.
    """
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), Mapping) else {}
    if site_ref not in sites:
        raise KeyError(site_ref)
    chain: list[str] = []
    cursor = str(site_ref)
    seen: set[str] = set()
    while cursor:
        if cursor in seen:
            raise ValueError("site containment cycle")
        seen.add(cursor)
        row = sites.get(cursor)
        if not isinstance(row, Mapping):
            raise ValueError("site containment route is invalid")
        fort = row.get("fortification", {}) if isinstance(row.get("fortification"), Mapping) else {}
        if bool(fort.get("active")) and _num(row.get("enclosed_area_km2")) > 0:
            chain.append(cursor)
        parent = row.get("parent_site_ref")
        cursor = str(parent) if isinstance(parent, str) and parent else ""
    chain.reverse()
    return chain


def urban_capacity_land_budget(
    *,
    resident_support_capacity: int,
    civilian_capacity: int,
    permanent_service_population: int,
    site_kind: str,
    rules: Mapping[str, Any],
    preserved_external_land_km2: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive one shared physical urban land budget from capacity and service facts.

    This is a capacity/geometry calculation only.  It creates no people or economic
    output. Existing external productive land is preserved exactly so geometry
    recalculation cannot mint agriculture, woodland, pasture or extraction acreage.
    """
    plan = rules.get("urban_capacity_planning", {}) if isinstance(rules.get("urban_capacity_planning"), Mapping) else {}
    resident = max(0, int(resident_support_capacity))
    civilian = max(0, int(civilian_capacity))
    service = max(0, int(permanent_service_population))
    per1000 = lambda key, default: max(0.0, _num(plan.get(key), default)) / 1000.0
    required = {
        "residential": civilian * per1000("housing_land_km2_per_1000_civilian_capacity", 0.05),
        "water": resident * per1000("water_land_km2_per_1000_resident_capacity", 0.005),
        "sanitation": resident * per1000("sanitation_land_km2_per_1000_resident_capacity", 0.0006),
        "work_access": resident * per1000("work_access_land_km2_per_1000_resident_capacity", 0.03),
        "food_storage": resident * per1000("food_storage_land_km2_per_1000_resident_capacity", 0.00048),
        "civic": resident * per1000("civic_land_km2_per_1000_resident_capacity", 0.0012),
        "market": resident * per1000("market_land_km2_per_1000_resident_capacity", 0.0024),
        "military": service * per1000("military_barracks_land_km2_per_1000_permanent_service", 0.0306),
        "training": service * per1000("training_land_km2_per_1000_permanent_service", 0.012),
    }
    fixed_enclosed = {
        "residential": required["residential"],
        "water": required["water"] + required["sanitation"],
        "industry": required["work_access"],
        "civic_storage": required["food_storage"] + required["civic"] + required["market"],
        "military": required["military"],
        "training": required["training"],
    }
    external = {str(k): max(0.0, _num(v)) for k, v in (preserved_external_land_km2 or {}).items() if str(k) not in {"open_developable", "transport"}}
    fixed = sum(fixed_enclosed.values()) + sum(external.values())
    circ = rules.get("site_class_circulation_minimum_fraction", {}) if isinstance(rules.get("site_class_circulation_minimum_fraction"), Mapping) else {}
    kind = str(site_kind)
    circulation_key = kind if kind in circ else ("capital" if kind == "capital" else "city")
    circulation = max(0.0, min(0.5, _num(circ.get(circulation_key, circ.get("default", 0.10)), 0.10)))
    reserve = max(0.0, min(0.4, _num(plan.get("open_future_reserve_fraction"), 0.10)))
    denom = max(0.1, 1.0 - circulation - reserve)
    parcel = fixed / denom if fixed > 0 else 0.0
    transport = parcel * circulation
    open_reserve = parcel * reserve
    enclosed_fraction = max(0.5, min(1.0, _num(plan.get("default_enclosed_fraction"), 0.90)))
    # The urban-support uses themselves must all be protected. If 90% is too small,
    # increase enclosure size rather than push residents outside by arithmetic.
    minimum_enclosed = sum(fixed_enclosed.values()) + transport * 0.85 + open_reserve * 0.50
    enclosed_area = max(parcel * enclosed_fraction, minimum_enclosed)
    if enclosed_area > parcel:
        parcel = enclosed_area / max(0.5, enclosed_fraction)
        transport = parcel * circulation
        open_reserve = parcel * reserve
        enclosed_area = max(parcel * enclosed_fraction, sum(fixed_enclosed.values()) + transport * 0.85 + open_reserve * 0.50)
    return {
        "parcel_area_km2": _round(parcel),
        "enclosed_area_km2": _round(enclosed_area),
        "circulation_fraction": _round(circulation),
        "open_future_reserve_fraction": _round(reserve),
        "required_component_land_km2": {k: _round(v) for k, v in required.items()},
        "fixed_enclosed_land_use_km2": {k: _round(v) for k, v in fixed_enclosed.items()},
        "preserved_external_land_km2": {k: _round(v) for k, v in external.items()},
        "transport_land_km2": _round(transport),
        "open_future_reserve_km2": _round(open_reserve),
    }


def site_enclosure_layers(registry: Mapping[str, Any], site_ref: str) -> list[dict[str, Any]]:
    """Return current outer-to-inner defended layers for one physical site.

    Explicit intra-site layers are preferred. Parent-site nesting remains supported
    for estates such as Tang Manor -> Inner Walls -> Inner Citadel.
    """
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), Mapping) else {}
    site = sites.get(site_ref)
    if not isinstance(site, Mapping):
        raise KeyError(site_ref)
    explicit = site.get("enclosures")
    if isinstance(explicit, list) and explicit:
        return [deepcopy(row) for row in explicit if isinstance(row, Mapping)]
    fort = site.get("fortification", {}) if isinstance(site.get("fortification"), Mapping) else {}
    if bool(fort.get("active")) and _num(site.get("enclosed_area_km2")) > 0:
        return [{
            "enclosure_ref": f"{site_ref}.outer",
            "kind": "outer_perimeter",
            "area_km2": _round(_num(site.get("enclosed_area_km2"))),
            "fortification": deepcopy(fort),
            "protected_land_use_km2": deepcopy(site.get("enclosed_land_use_km2", {})),
        }]
    return []

def require_valid_land_registry(registry: Mapping[str, Any]) -> None:
    errors = validate_land_registry(registry)
    if errors:
        raise ValueError("; ".join(errors[:8]))



def productive_labor_access_factor(
    registry: Mapping[str, Any],
    *,
    site_ref: str,
    commuting_workers: int,
    rules: Mapping[str, Any],
) -> dict[str, float | int | str]:
    """Return a deterministic access cap for centralized-residence productive labor.

    Most sites return 1.0 because workers live at or around the productive site.
    A site that explicitly centralizes permanent residence elsewhere must prove that
    its actual gates, circulation land, and saved average commute can move workers
    to the productive parcel.  This is a physical access rule, not a Tang rule.
    """
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), Mapping) else {}
    site = sites.get(site_ref) if isinstance(sites, Mapping) else None
    if not isinstance(site, Mapping):
        # Regional/hinterland demographic owners are themselves the productive
        # land authority. They do not represent a centralized commuting estate
        # and therefore have no gate/inner-road bottleneck to prove. Returning
        # ordinary access here lets the same land+labor production formula serve
        # both exact sites and aggregate rural regions without inventing villages.
        regions = registry.get("regions", {}) if isinstance(registry.get("regions"), Mapping) else {}
        if isinstance(regions, Mapping) and isinstance(regions.get(site_ref), Mapping):
            return {
                "factor": 1.0,
                "gate_factor": 1.0,
                "road_factor": 1.0,
                "distance_factor": 1.0,
                "commuting_workers": max(0, int(commuting_workers)),
                "access_basis": "regional_hinterland_local_residence",
            }
        raise ValueError("productive labor access requires a physical site or productive region")
    access = site.get("labor_access", {}) if isinstance(site.get("labor_access"), Mapping) else {}
    if not bool(access.get("commute_required_for_productive_land")):
        return {"factor": 1.0, "gate_factor": 1.0, "road_factor": 1.0, "distance_factor": 1.0, "commuting_workers": max(0, int(commuting_workers))}
    cfg = rules.get("centralized_residence_labor_access", {}) if isinstance(rules.get("centralized_residence_labor_access"), Mapping) else {}
    residence_ref = str(access.get("resident_gate_site_ref") or access.get("permanent_residence_site_ref") or "")
    residence = sites.get(residence_ref) if residence_ref else None
    if not isinstance(residence, Mapping):
        raise ValueError("centralized productive labor has no physical resident enclosure")
    fort = residence.get("fortification", {}) if isinstance(residence.get("fortification"), Mapping) else {}
    gates = max(0, int(_num(fort.get("gate_count"))))
    per_gate_hour = max(1.0, _num(cfg.get("worker_gate_throughput_per_gate_hour"), 4500.0))
    window_hours = max(0.25, _num(cfg.get("outbound_commute_window_hours"), 3.0))
    gate_capacity = gates * per_gate_hour * window_hours
    workers = max(0, int(commuting_workers))
    gate_factor = 1.0 if workers <= 0 else min(1.0, gate_capacity / workers)

    site_kind = str(site.get("kind", "default"))
    minimums = rules.get("site_class_circulation_minimum_fraction", {}) if isinstance(rules.get("site_class_circulation_minimum_fraction"), Mapping) else {}
    minimum_fraction = max(1e-9, _num(minimums.get(site_kind, minimums.get("default", 0.1)), 0.1))
    land_map = site.get("enclosed_land_use_km2", {}) if isinstance(site.get("enclosed_land_use_km2"), Mapping) else {}
    land_map_external = site.get("external_land_use_km2", {}) if isinstance(site.get("external_land_use_km2"), Mapping) else {}
    transport_key = str(access.get("transport_land_category", "transport"))
    transport_area = max(0.0, _num(land_map.get(transport_key))) + max(0.0, _num(land_map_external.get(transport_key)))
    parcel = max(0.0, _num(site.get("parcel_area_km2")))
    required_transport = parcel * minimum_fraction
    road_factor = 1.0 if required_transport <= 0 else min(1.0, transport_area / required_transport)

    avg_km = max(0.0, _num(access.get("average_commute_distance_km")))
    full_km = max(0.0, _num(cfg.get("full_productivity_average_commute_km"), 20.0))
    maximum_km = max(full_km + 1e-9, _num(cfg.get("maximum_average_commute_km"), 50.0))
    minimum_at_max = max(0.0, min(1.0, _num(cfg.get("minimum_distance_factor_at_maximum"), 0.35)))
    if avg_km <= full_km:
        distance_factor = 1.0
    elif avg_km > maximum_km:
        distance_factor = 0.0
    else:
        progress = (avg_km - full_km) / (maximum_km - full_km)
        distance_factor = 1.0 - progress * (1.0 - minimum_at_max)
    factor = max(0.0, min(1.0, gate_factor, road_factor, distance_factor))
    return {
        "factor": round(factor, 6),
        "gate_factor": round(gate_factor, 6),
        "road_factor": round(road_factor, 6),
        "distance_factor": round(distance_factor, 6),
        "commuting_workers": workers,
        "gate_capacity_workers_per_outbound_window": int(math.floor(gate_capacity)),
        "resident_site_ref": residence_ref,
        "average_commute_distance_km": round(avg_km, 6),
    }

def site_land_requirement_km2(work: Mapping[str, Any], rules: Mapping[str, Any]) -> float:
    """Return the physical land footprint required inside a site enclosure.

    Roads and open training areas use their actual surface/ground area. Buildings use
    registered site footprint where available, otherwise a shared floor-to-land factor.
    Drainage/water works use a small explicit shared service footprint. Wall *expansion*
    is handled separately because enclosure geometry changes land classification.
    """
    geom = work.get("physical_geometry_per_unit", {}) if isinstance(work.get("physical_geometry_per_unit"), Mapping) else {}
    q = max(1.0, _num(work.get("quantity"), 1.0))
    factors = rules.get("building_site_area_factors", {}) if isinstance(rules.get("building_site_area_factors"), Mapping) else {}
    category = str(work.get("category", ""))
    if category == "fortification" and _num(geom.get("length_m")) > 0:
        # Linear walls consume their actual crown/base footprint, but ordinary wall
        # projects do not enlarge the enclosure by themselves.
        width_m = max(_num(geom.get("average_thickness_m")), _num(geom.get("base_thickness_m")), 1.0)
        return _round(_num(geom.get("length_m")) * width_m * q / 1_000_000.0)
    for key in ("district_land_area_m2", "training_ground_area_m2", "road_surface_area_m2", "site_land_area_m2"):
        if _num(geom.get(key)) > 0:
            return _round(_num(geom.get(key)) * q / 1_000_000.0)
    if _num(geom.get("floor_area_m2")) > 0:
        factor = _num(factors.get("floor_area_to_land_area"), 1.5)
        if category == "food_storage": factor = _num(factors.get("granary_floor_area_to_land_area"), factor)
        if category == "fortification" and _num(geom.get("gate_count")) > 0: factor = _num(factors.get("gatehouse_land_factor"), factor)
        if category == "fortification" and _num(geom.get("tower_count")) > 0: factor = _num(factors.get("tower_land_factor"), factor)
        return _round(_num(geom.get("floor_area_m2")) * factor * q / 1_000_000.0)
    if _num(geom.get("design_floor_area_m2")) > 0:
        factor = _num(factors.get("design_floor_area_to_land_area"), 1.7)
        return _round(_num(geom.get("design_floor_area_m2")) * factor * q / 1_000_000.0)
    if category == "water":
        return _round(_num(factors.get("well_cluster_land_m2"), 5000) * q / 1_000_000.0)
    if category == "sanitation":
        return _round(_num(factors.get("latrine_drainage_land_m2"), 3000) * q / 1_000_000.0)
    return 0.0


def land_category_for_work(work: Mapping[str, Any], rules: Mapping[str, Any]) -> str:
    mapping = rules.get("building_land_category_by_blueprint_category", {}) if isinstance(rules.get("building_land_category_by_blueprint_category"), Mapping) else {}
    return str(mapping.get(str(work.get("category", "")), "civic_storage"))


def site_default_build_zone(site: Mapping[str, Any]) -> str:
    fort = site.get("fortification", {}) if isinstance(site.get("fortification"), Mapping) else {}
    return "inside_defended_perimeter" if bool(fort.get("active")) and _num(site.get("enclosed_area_km2")) > 0 else "outside_defended_perimeter"


def _site_land_map_for_zone(site: MutableMapping[str, Any], zone: str) -> MutableMapping[str, Any]:
    key = "enclosed_land_use_km2" if zone == "inside_defended_perimeter" else "external_land_use_km2"
    mapping = site.get(key)
    if not isinstance(mapping, MutableMapping):
        raise ValueError("site land-use partition is invalid")
    return mapping


def reserve_site_land(registry: MutableMapping[str, Any], *, site_ref: str, project_ref: str, work: Mapping[str, Any], rules: Mapping[str, Any], placement_zone: str | None = None, source_land_category: str = "open_developable") -> dict[str, Any]:
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), MutableMapping) else None
    if not isinstance(sites, MutableMapping) or site_ref not in sites or not isinstance(sites[site_ref], MutableMapping):
        raise ValueError("development target has no finite land ledger")
    site: MutableMapping[str, Any] = sites[site_ref]
    required = site_land_requirement_km2(work, rules)
    if required <= 0:
        return {"site_ref": site_ref, "project_ref": project_ref, "area_km2": 0.0, "land_category": land_category_for_work(work, rules)}
    zone = str(placement_zone or site_default_build_zone(site))
    if zone not in {"inside_defended_perimeter", "outside_defended_perimeter"}:
        raise ValueError("invalid development placement zone")
    land_use = _site_land_map_for_zone(site, zone)
    source_category = str(source_land_category or "open_developable")
    if source_category in {"water", "fortification", "unsuitable"}:
        raise ValueError("this land category cannot be reallocated directly by ordinary construction")
    reserved = site.setdefault("reserved_land_km2", {})
    if not isinstance(reserved, MutableMapping):
        raise ValueError("site reserved land registry is invalid")
    if project_ref in reserved:
        raise ValueError("project already reserves site land")
    already_reserved = sum(
        max(0.0, _num(v.get("area_km2") if isinstance(v, Mapping) else v))
        for v in reserved.values()
        if not isinstance(v, Mapping)
        or (str(v.get("placement_zone") or site_default_build_zone(site)) == zone and str(v.get("source_land_category", "open_developable")) == source_category)
    )
    available = max(0.0, _num(land_use.get(source_category)) - already_reserved)
    if available + 1e-9 < required:
        where = "inside the current defended perimeter" if zone == "inside_defended_perimeter" else "outside the defended perimeter"
        raise ValueError(f"insufficient {source_category} land {where}; expand or choose another lawful source land category")
    row = {"area_km2": required, "land_category": land_category_for_work(work, rules), "placement_zone": zone, "source_land_category": source_category}
    reserved[project_ref] = row
    return {"site_ref": site_ref, "project_ref": project_ref, **row}


def release_site_land_reservation(registry: MutableMapping[str, Any], *, site_ref: str, project_ref: str) -> dict[str, Any] | None:
    site = registry.get("sites", {}).get(site_ref) if isinstance(registry.get("sites"), Mapping) else None
    if not isinstance(site, MutableMapping):
        return None
    reserved = site.get("reserved_land_km2")
    if not isinstance(reserved, MutableMapping):
        return None
    row = reserved.pop(project_ref, None)
    return deepcopy(row) if isinstance(row, Mapping) else None


def apply_site_land_reservation(registry: MutableMapping[str, Any], *, site_ref: str, project_ref: str) -> dict[str, Any] | None:
    site = registry.get("sites", {}).get(site_ref) if isinstance(registry.get("sites"), Mapping) else None
    if not isinstance(site, MutableMapping):
        return None
    reserved = site.get("reserved_land_km2")
    if not isinstance(reserved, MutableMapping):
        return None
    row = reserved.pop(project_ref, None)
    if not isinstance(row, Mapping):
        return None
    area = max(0.0, _num(row.get("area_km2"))); category = str(row.get("land_category", "civic_storage"))
    zone = str(row.get("placement_zone") or site_default_build_zone(site))
    land_use = _site_land_map_for_zone(site, zone)
    source_category = str(row.get("source_land_category", "open_developable"))
    if _num(land_use.get(source_category)) + 1e-9 < area:
        raise ValueError("reserved land no longer exists at project completion")
    land_use[source_category] = _round(_num(land_use.get(source_category)) - area)
    land_use[category] = _round(_num(land_use.get(category)) + area)
    require_valid_land_registry(registry)
    return {"area_km2": area, "land_category": category, "placement_zone": zone, "source_land_category": source_category}


def terrain_factor(rules: Mapping[str, Any], terrain: str) -> float:
    rows = rules.get("terrain_construction_factor", {}) if isinstance(rules.get("terrain_construction_factor"), Mapping) else {}
    return max(0.1, _num(rows.get(terrain, rows.get("default", 1.15)), 1.15))


def land_use_development_work_spec(*, area_km2: float, target_category: str, terrain: str, rules: Mapping[str, Any], target_ref: str) -> dict[str, Any]:
    """Return one shared physical land-improvement work specification.

    Land categories differ only because the registered physical work intensity and
    later productive output differ. Owner identity never changes this calculation.
    """
    area = max(0.01, float(area_km2))
    target = str(target_category)
    table = rules.get("land_use_development", {}) if isinstance(rules.get("land_use_development"), Mapping) else {}
    row = table.get(target) if isinstance(table, Mapping) else None
    if not isinstance(row, Mapping):
        raise ValueError("land use has no registered development work specification")
    factor = terrain_factor(rules, terrain)
    general = int(math.ceil(_num(row.get("general_labor_hours_per_km2")) * area * factor))
    skilled = int(math.ceil(_num(row.get("skilled_labor_hours_per_km2")) * area * factor))
    engineering = int(math.ceil(_num(row.get("engineering_labor_hours_per_km2")) * area * factor))
    materials = int(math.ceil(_num(row.get("material_units_per_km2")) * area * factor))
    return {
        "kind": "land_use_development",
        "target_ref": str(target_ref),
        "target_land_category": target,
        "area_km2": _round(area),
        "terrain": str(terrain),
        "terrain_factor": _round(factor),
        "construction_material_units": materials,
        "labor_hours_by_class": {"general": general, "skilled": skilled, "engineering": engineering},
        "labor_hours": general + skilled + engineering,
        "minimum_calendar_hours": max(1, int(_num(row.get("minimum_calendar_hours"), 720))),
        "workfront_capacity_workers": max(1, int(math.ceil(_num(row.get("workfront_workers_per_km2"), 400) * area))),
    }


def apply_land_use_conversion(
    registry: MutableMapping[str, Any],
    *,
    target_ref: str,
    target_category: str,
    area_km2: float,
    source_category: str = "open_developable",
    placement_zone: str = "outside_defended_perimeter",
) -> dict[str, Any]:
    """Conserve land while changing one current use into another."""
    area = max(0.0, float(area_km2))
    if area <= 0:
        raise ValueError("land conversion requires positive area")
    if target_category == source_category:
        raise ValueError("land conversion source and target categories are identical")
    regions = registry.get("regions", {}) if isinstance(registry.get("regions"), Mapping) else {}
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), Mapping) else {}
    if target_ref in regions and isinstance(regions[target_ref], MutableMapping):
        uses = regions[target_ref].get("land_use_km2")
        if not isinstance(uses, MutableMapping):
            raise ValueError("region land-use partition is invalid")
    elif target_ref in sites and isinstance(sites[target_ref], MutableMapping):
        site = sites[target_ref]
        uses = _site_land_map_for_zone(site, placement_zone)
    else:
        raise ValueError("land conversion target has no finite land ledger")
    available = max(0.0, _num(uses.get(source_category)))
    if available + 1e-9 < area:
        raise ValueError("insufficient source land for conversion")
    uses[source_category] = _round(available - area)
    uses[target_category] = _round(_num(uses.get(target_category)) + area)
    require_valid_land_registry(registry)
    return {
        "target_ref": str(target_ref), "area_km2": _round(area),
        "source_land_category": str(source_category), "target_land_category": str(target_category),
        "placement_zone": None if target_ref in regions else str(placement_zone),
    }


def productive_land_area_km2(registry: Mapping[str, Any], location_ref: str, category: str) -> float:
    """Return current physical productive area for a region or site."""
    ref = str(location_ref); cat = str(category)
    regions = registry.get("regions", {}) if isinstance(registry.get("regions"), Mapping) else {}
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), Mapping) else {}
    if ref in regions and isinstance(regions[ref], Mapping):
        return max(0.0, _num((regions[ref].get("land_use_km2") or {}).get(cat)))
    if ref in sites and isinstance(sites[ref], Mapping):
        site = sites[ref]
        return max(0.0, _num((site.get("enclosed_land_use_km2") or {}).get(cat)) + _num((site.get("external_land_use_km2") or {}).get(cat)))
    return 0.0


def site_circulation_minimum_km2(site: Mapping[str, Any], rules: Mapping[str, Any]) -> float:
    table = rules.get("site_class_circulation_minimum_fraction", {}) if isinstance(rules.get("site_class_circulation_minimum_fraction"), Mapping) else {}
    kind = str(site.get("kind", "default"))
    fraction = max(0.0, _num(table.get(kind, table.get("default", 0.10)), 0.10))
    return _round(max(0.0, _num(site.get("parcel_area_km2"))) * fraction)


def farmland_conversion_work_spec(*, area_km2: float, terrain: str, rules: Mapping[str, Any], target_ref: str) -> dict[str, Any]:
    work = land_use_development_work_spec(
        area_km2=area_km2, target_category="agriculture", terrain=terrain, rules=rules, target_ref=target_ref
    )
    work["kind"] = "land_conversion"
    return work


def apply_farmland_conversion(registry: MutableMapping[str, Any], *, target_ref: str, area_km2: float) -> dict[str, Any]:
    return apply_land_use_conversion(
        registry, target_ref=target_ref, target_category="agriculture", area_km2=area_km2,
        source_category="open_developable", placement_zone="outside_defended_perimeter",
    )


def _wall_profile_for_site(read, site_ref: str) -> Mapping[str, Any]:
    doc = read(FORTIFICATION_PROFILES_PATH)
    for row in doc.get("profiles", []) if isinstance(doc, Mapping) else []:
        if isinstance(row, Mapping) and str(row.get("site_ref")) == site_ref:
            return row
    return {}


def _wall_dimensions(profile: Mapping[str, Any]) -> dict[str, float]:
    base = profile.get("physical_baseline", {}) if isinstance(profile.get("physical_baseline"), Mapping) else {}
    wall = base.get("outer_wall", {}) if isinstance(base.get("outer_wall"), Mapping) else {}
    return {
        "height_m": max(1.0, _num(wall.get("wall_height_m"), 8.0)),
        "base_thickness_m": max(0.5, _num(wall.get("wall_base_thickness_m"), 6.0)),
        "crown_thickness_m": max(0.5, _num(wall.get("wall_crown_thickness_m"), _num(wall.get("wall_base_thickness_m"), 6.0) * 0.65)),
        "moat_width_m": max(0.0, _num(wall.get("moat_width_m"), 0.0)),
        "moat_depth_m": max(0.0, _num(wall.get("moat_depth_m"), 0.0)),
        "tower_interval_m": max(20.0, _num(wall.get("tower_station_interval_m"), 200.0)),
    }


def _physical_work_cash_cost(read, *, construction_material_units: int, labor_hours_by_class: Mapping[str, int], haul_km: float = 4.0) -> dict[str, Any]:
    physics = read(CONSTRUCTION_PHYSICS_PATH)
    meq = physics.get("material_equivalent", {}) if isinstance(physics.get("material_equivalent"), Mapping) else {}
    units = max(0, int(construction_material_units))
    tonnes_per_unit = max(1e-9, _num(meq.get("tonnes_per_construction_material_unit"), 0.25))
    material_tonnes = units * tonnes_per_unit
    material_procurement = units * _num(meq.get("base_procurement_silver_per_unit"), 1.25)
    transport = material_tonnes * max(0.0, float(haul_km)) * _num(meq.get("haul_silver_per_tonne_km"), 0.015)
    wage_rules = physics.get("labor", {}) if isinstance(physics.get("labor"), Mapping) else {}
    monthly_hours = max(1e-9, _num(wage_rules.get("monthly_productive_hours"), 216.0))
    wages = wage_rules.get("monthly_wage_silver", {}) if isinstance(wage_rules.get("monthly_wage_silver"), Mapping) else {}
    labor_silver = sum(max(0, int(hours)) * _num(wages.get(str(cls)), 4.5) / monthly_hours for cls, hours in labor_hours_by_class.items())
    silver = int(math.ceil(material_procurement + transport + labor_silver))
    return {
        "construction_material_units": units,
        "material_equivalent_tonnes": _round(material_tonnes),
        "labor_hours_by_class": {str(k): max(0, int(v)) for k, v in labor_hours_by_class.items()},
        "labor_hours": sum(max(0, int(v)) for v in labor_hours_by_class.values()),
        "silver_cost": silver,
        "cash_cost_breakdown": {
            "material_procurement_silver": round(material_procurement, 3),
            "labor_wages_silver": round(labor_silver, 3),
            "local_haul_silver": round(transport, 3),
        },
    }


def defensive_store_procurement_spec(read, units: int) -> dict[str, Any]:
    rules = read(LAND_RULES_PATH)
    ds = rules.get("defensive_stores", {}) if isinstance(rules.get("defensive_stores"), Mapping) else {}
    count = max(0, int(units))
    per = max(0.0, _num(ds.get("base_procurement_silver_per_unit"), 0.35))
    kg = count * max(0.0, _num(ds.get("unit_equivalent_kg"), 20.0))
    return {
        "defensive_stores_units": count,
        "equivalent_mass_kg": _round(kg),
        "silver_cost": int(math.ceil(count * per)),
        "base_procurement_silver_per_unit": per,
    }


def _installed_defense_counts(read, profile: Mapping[str, Any]) -> dict[str, int]:
    lb = profile.get("logistics_blueprint", {}) if isinstance(profile.get("logistics_blueprint"), Mapping) else {}
    installed = lb.get("installed_equipment", {}) if isinstance(lb.get("installed_equipment"), Mapping) else {}
    authority_ref = installed.get("authority_ref")
    if isinstance(authority_ref, str) and authority_ref:
        art = read(authority_ref)
        exact = art.get("installed_systems", {}) if isinstance(art, Mapping) and isinstance(art.get("installed_systems"), Mapping) else {}
        if exact:
            installed = exact
    stations = max(
        max(0, int(_num(installed.get("wall_defense_stations")))),
        max(0, int(_num(installed.get("stone_drop_cranes")))),
        max(0, int(_num(installed.get("firepot_systems")))),
    )
    return {
        "bed_crossbows": max(0, int(_num(installed.get("bed_crossbows")))),
        "counterweight_trebuchets": max(0, int(_num(installed.get("counterweight_trebuchets")))),
        "wall_defense_stations": stations,
        "gate_mechanism_sets": max(0, int(_num(installed.get("gate_mechanism_sets")))),
        "signal_tower_sets": max(0, int(_num(installed.get("signal_tower_sets")))),
    }


def baseline_fortification_work_spec(read, *, site_ref: str, defensive_store_units: int = 0) -> dict[str, Any]:
    """Return deterministic replacement work/cost for an existing defended site.

    This is a derived calibration/reporting surface.  It does not imply the historical
    site literally paid this exact price; it proves that the current physical design can
    be rebuilt by the same formulas later used for Jo, a generated House estate, or any
    other lawful site.
    """
    profile = _wall_profile_for_site(read, site_ref)
    if not profile:
        raise ValueError("site has no registered fortification profile")
    base = profile.get("physical_baseline", {}) if isinstance(profile.get("physical_baseline"), Mapping) else {}
    perimeter_km = max(0.0, _num(base.get("constructed_wall_centerline_perimeter_km")))
    dims = _wall_dimensions(profile)
    wall = base.get("outer_wall", {}) if isinstance(base.get("outer_wall"), Mapping) else {}
    length_m = perimeter_km * 1000.0
    avg_thickness = (dims["base_thickness_m"] + dims["crown_thickness_m"]) / 2.0
    wall_volume = length_m * dims["height_m"] * avg_thickness
    moat_volume = length_m * dims["moat_width_m"] * dims["moat_depth_m"]
    rules = read(LAND_RULES_PATH)
    phys = rules.get("wall_physics", {}) if isinstance(rules.get("wall_physics"), Mapping) else {}
    towers = max(0, int(_num(wall.get("tower_count")))) or int(math.ceil(length_m / max(20.0, dims["tower_interval_m"])))
    gates = max(0, int(_num(wall.get("external_strategic_gate_count"))))
    materials = int(math.ceil(wall_volume * _num(phys.get("material_units_per_wall_m3"), 0.42)))
    general = int(math.ceil(wall_volume * _num(phys.get("general_labor_hours_per_wall_m3"), 8.75) + moat_volume * _num(phys.get("moat_general_labor_hours_per_m3"), 0.55)))
    skilled = int(math.ceil(wall_volume * _num(phys.get("skilled_labor_hours_per_wall_m3"), 1.25) + moat_volume * _num(phys.get("moat_skilled_labor_hours_per_m3"), 0.05)))
    engineering = int(math.ceil(wall_volume * _num(phys.get("engineering_labor_hours_per_wall_m3"), 0.4166666667)))
    materials += towers * int(_num(phys.get("tower_material_units_each"), 420)) + gates * int(_num(phys.get("gate_material_units_each"), 1800))
    general += towers * int(_num(phys.get("tower_general_labor_hours_each"), 10000)) + gates * int(_num(phys.get("gate_general_labor_hours_each"), 28000))
    skilled += towers * int(_num(phys.get("tower_skilled_labor_hours_each"), 9000)) + gates * int(_num(phys.get("gate_skilled_labor_hours_each"), 22000))
    engineering += towers * int(_num(phys.get("tower_engineering_labor_hours_each"), 2000)) + gates * int(_num(phys.get("gate_engineering_labor_hours_each"), 7000))

    fixed = rules.get("fixed_defense_physics", {}) if isinstance(rules.get("fixed_defense_physics"), Mapping) else {}
    counts = _installed_defense_counts(read, profile)
    key_map = {
        "bed_crossbows": "bed_crossbow",
        "counterweight_trebuchets": "counterweight_trebuchet",
        "wall_defense_stations": "wall_defense_station",
        "gate_mechanism_sets": "gate_mechanism_set",
        "signal_tower_sets": "signal_tower_set",
    }
    for count_key, physics_key in key_map.items():
        count = counts[count_key]
        row = fixed.get(physics_key, {}) if isinstance(fixed.get(physics_key), Mapping) else {}
        materials += count * int(_num(row.get("material_units_each")))
        general += count * int(_num(row.get("general_labor_hours_each")))
        skilled += count * int(_num(row.get("skilled_labor_hours_each")))
        engineering += count * int(_num(row.get("engineering_labor_hours_each")))

    cash = _physical_work_cash_cost(
        read,
        construction_material_units=materials,
        labor_hours_by_class={"general": general, "skilled": skilled, "engineering": engineering},
        haul_km=4.0,
    )
    stores = defensive_store_procurement_spec(read, defensive_store_units)
    cash["silver_cost"] = int(cash["silver_cost"]) + int(stores["silver_cost"])
    cash["cash_cost_breakdown"]["defensive_stores_silver"] = stores["silver_cost"]
    return {
        "kind": "baseline_fortification_replacement",
        "site_ref": site_ref,
        "perimeter_km": _round(perimeter_km),
        "wall_dimensions": dims,
        "wall_volume_m3": _round(wall_volume),
        "moat_excavation_m3": _round(moat_volume),
        "tower_count": towers,
        "gate_count": gates,
        "installed_defense": counts,
        "defensive_stores": stores,
        **cash,
    }


def enclosure_expansion_geometry(site: Mapping[str, Any], add_area_km2: float) -> dict[str, Any]:
    add = max(0.000001, float(add_area_km2))
    old_area = max(0.0, _num(site.get("enclosed_area_km2")))
    parcel = max(0.0, _num(site.get("parcel_area_km2")))
    if old_area + add > parcel + 1e-9:
        raise ValueError("enclosure expansion exceeds the current site parcel; allocate/acquire more adjacent land first")
    geom = site.get("geometry", {}) if isinstance(site.get("geometry"), Mapping) else {}
    shape = str(geom.get("shape", "rectangle"))
    if shape == "stadium":
        radius = max(0.000001, _num(geom.get("radius_km")))
        old_L = max(0.0, _num(geom.get("straight_length_km")))
        delta_L = add / (2.0 * radius)
        new_L = old_L + delta_L
        old_per = 2.0 * old_L + 2.0 * math.pi * radius
        new_per = 2.0 * new_L + 2.0 * math.pi * radius
        new_wall = 2.0 * delta_L + math.pi * radius
        absorbed = math.pi * radius
        return {
            "shape": "stadium", "old_area_km2": _round(old_area), "new_area_km2": _round(old_area + add),
            "old_perimeter_km": _round(old_per), "new_perimeter_km": _round(new_per),
            "new_wall_construction_km": _round(new_wall), "absorbed_internal_wall_km": _round(absorbed),
            "new_geometry": {"shape": "stadium", "radius_km": _round(radius), "straight_length_km": _round(new_L)},
        }
    aspect = max(1.0, _num(geom.get("aspect_ratio"), 1.5))
    long = _num(geom.get("length_km")); short = _num(geom.get("width_km"))
    if long <= 0 or short <= 0:
        long, short, _p = rectangle_dimensions_from_area(old_area, aspect)
    if short > long:
        long, short = short, long
    depth = add / max(long, 1e-9)
    new_short = short + depth
    old_per = 2.0 * (long + short); new_per = 2.0 * (long + new_short)
    # One long boundary is absorbed; one replacement long boundary plus two connectors are built.
    new_wall = long + 2.0 * depth
    return {
        "shape": "rectangle", "old_area_km2": _round(old_area), "new_area_km2": _round(old_area + add),
        "old_perimeter_km": _round(old_per), "new_perimeter_km": _round(new_per),
        "new_wall_construction_km": _round(new_wall), "absorbed_internal_wall_km": _round(long),
        "new_geometry": {"shape": "rectangle", "length_km": _round(long), "width_km": _round(new_short), "aspect_ratio": _round(long / new_short if new_short else aspect)},
    }


def wall_expansion_work_spec(read, *, site_ref: str, add_area_km2: float) -> dict[str, Any]:
    registry = read(LAND_STATE_PATH); rules = read(LAND_RULES_PATH)
    site = registry.get("sites", {}).get(site_ref) if isinstance(registry.get("sites"), Mapping) else None
    if not isinstance(site, Mapping):
        raise ValueError("unknown site land ledger")
    geometry = enclosure_expansion_geometry(site, add_area_km2)
    profile = _wall_profile_for_site(read, site_ref)
    dims = _wall_dimensions(profile)
    length_m = geometry["new_wall_construction_km"] * 1000.0
    avg_thickness = (dims["base_thickness_m"] + dims["crown_thickness_m"]) / 2.0
    wall_volume = length_m * dims["height_m"] * avg_thickness
    moat_volume = length_m * dims["moat_width_m"] * dims["moat_depth_m"]
    phys = rules.get("wall_physics", {}) if isinstance(rules.get("wall_physics"), Mapping) else {}
    materials = int(math.ceil(wall_volume * _num(phys.get("material_units_per_wall_m3"), 0.42)))
    general = int(math.ceil(wall_volume * _num(phys.get("general_labor_hours_per_wall_m3"), 8.75) + moat_volume * _num(phys.get("moat_general_labor_hours_per_m3"), 0.55)))
    skilled = int(math.ceil(wall_volume * _num(phys.get("skilled_labor_hours_per_wall_m3"), 1.25) + moat_volume * _num(phys.get("moat_skilled_labor_hours_per_m3"), 0.05)))
    engineering = int(math.ceil(wall_volume * _num(phys.get("engineering_labor_hours_per_wall_m3"), 0.4166666667)))
    towers = int(math.ceil(length_m / max(20.0, dims["tower_interval_m"])))
    # The tower count is represented in the work result, but tower labor/material is
    # folded into a modest shared surcharge so expansion does not need thousands of
    # separate tower subprojects.
    tower_material = towers * int(_num(phys.get("tower_material_units_each"), 420))
    tower_general = towers * int(_num(phys.get("tower_general_labor_hours_each"), 10000))
    tower_skilled = towers * int(_num(phys.get("tower_skilled_labor_hours_each"), 9000))
    tower_engineering = towers * int(_num(phys.get("tower_engineering_labor_hours_each"), 2000))
    materials += tower_material; general += tower_general; skilled += tower_skilled; engineering += tower_engineering
    labor_by_class = {"general": general, "skilled": skilled, "engineering": engineering}
    cash = _physical_work_cash_cost(read, construction_material_units=materials, labor_hours_by_class=labor_by_class, haul_km=4.0)
    return {
        "kind": "enclosure_expansion",
        "site_ref": site_ref,
        "add_area_km2": _round(add_area_km2),
        "geometry_change": geometry,
        "wall_dimensions": dims,
        "new_wall_length_m": int(round(length_m)),
        "new_towers": towers,
        "wall_volume_m3": _round(wall_volume),
        "moat_excavation_m3": _round(moat_volume),
        "construction_material_units": cash["construction_material_units"],
        "material_equivalent_tonnes": cash["material_equivalent_tonnes"],
        "labor_hours_by_class": cash["labor_hours_by_class"],
        "labor_hours": cash["labor_hours"],
        "minimum_calendar_hours": max(1, int(_num(phys.get("reference_critical_path_hours"), 2160))),
        "workfront_capacity_workers": max(1, int(math.ceil(length_m * _num(phys.get("workfront_workers_per_wall_meter"), 2.2)))),
        "silver_cost": cash["silver_cost"],
        "cash_cost_breakdown": cash["cash_cost_breakdown"],
    }


def apply_enclosure_expansion(registry: MutableMapping[str, Any], *, site_ref: str, work: Mapping[str, Any]) -> dict[str, Any]:
    site = registry.get("sites", {}).get(site_ref) if isinstance(registry.get("sites"), Mapping) else None
    if not isinstance(site, MutableMapping):
        raise ValueError("unknown site land ledger")
    change = work.get("geometry_change", {}) if isinstance(work.get("geometry_change"), Mapping) else {}
    add = max(0.0, _num(work.get("add_area_km2")))
    external = site.get("external_land_use_km2")
    enclosed = site.get("enclosed_land_use_km2")
    if not isinstance(external, MutableMapping) or not isinstance(enclosed, MutableMapping):
        raise ValueError("site land-use partitions are invalid")
    if _num(external.get("open_developable")) + 1e-9 < add:
        raise ValueError("insufficient external open land to complete enclosure expansion")
    external["open_developable"] = _round(_num(external.get("open_developable")) - add)
    enclosed["open_developable"] = _round(_num(enclosed.get("open_developable")) + add)
    site["enclosed_area_km2"] = _round(_num(site.get("enclosed_area_km2")) + add)
    if isinstance(change.get("new_geometry"), Mapping):
        site["geometry"] = deepcopy(change["new_geometry"])
    site.setdefault("fortification", {})["constructed_outer_perimeter_km"] = _round(_num(change.get("new_perimeter_km")))
    site["fortification"]["internal_absorbed_wall_km"] = _round(_num(site["fortification"].get("internal_absorbed_wall_km")) + _num(change.get("absorbed_internal_wall_km")))
    site["fortification"]["outer_wall_length_built_cumulative_km"] = _round(_num(site["fortification"].get("outer_wall_length_built_cumulative_km")) + _num(change.get("new_wall_construction_km")))
    require_valid_land_registry(registry)
    return {"site_ref": site_ref, "enclosed_area_km2": site["enclosed_area_km2"], "geometry": deepcopy(site.get("geometry")), "fortification": deepcopy(site.get("fortification"))}




def strategic_region_frontiers(read) -> list[dict[str, Any]]:
    """Derive compact cross-polity region adjacency from authoritative routes.

    This is deliberately derived rather than persisted. The strategic map needs
    exact adjacency for territorial transfer and invasion options, not heavyweight
    polygon geometry in hot state.
    """
    loc_doc = read(LOCATIONS_PATH)
    locations = {str(r.get("ref")): r for r in loc_doc.get("locations", []) if isinstance(r, Mapping) and r.get("ref")}
    routes_doc = read("game/data/world/routes.json")
    routes = routes_doc.get("routes", []) if isinstance(routes_doc, Mapping) else []

    def region_of(ref: str) -> str | None:
        row = locations.get(str(ref))
        if not isinstance(row, Mapping):
            return None
        if str(row.get("kind")) == "region":
            return str(row.get("ref"))
        rr = row.get("region_ref")
        return str(rr) if isinstance(rr, str) and rr else None

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for route in routes:
        if not isinstance(route, Mapping) or not isinstance(route.get("border_crossing"), Mapping):
            continue
        a = region_of(str(route.get("a", ""))); b = region_of(str(route.get("b", "")))
        if not a or not b or a == b:
            continue
        pair = tuple(sorted((a, b)))
        if pair in seen:
            continue
        seen.add(pair)
        bc = route.get("border_crossing", {})
        out.append({
            "region_a_ref": pair[0], "region_b_ref": pair[1],
            "route_ref": str(route.get("ref", "")),
            "side_a": str(bc.get("from", "")), "side_b": str(bc.get("to", "")),
            "frontier": True, "unclaimed_gap_implied": False,
        })
    return sorted(out, key=lambda r: (r["region_a_ref"], r["region_b_ref"], r["route_ref"]))


def adjacent_regions(read, region_ref: str) -> list[str]:
    ref = str(region_ref)
    out = set()
    for row in strategic_region_frontiers(read):
        if row["region_a_ref"] == ref:
            out.add(row["region_b_ref"])
        elif row["region_b_ref"] == ref:
            out.add(row["region_a_ref"])
    return sorted(out)

def expand_site_parcel(
    registry: MutableMapping[str, Any],
    *,
    site_ref: str,
    area_km2: float,
    source_land_category: str = "open_developable",
) -> dict[str, Any]:
    """Allocate adjacent sovereign/private land into an existing site's parcel.

    A site parcel is a current administrative/physical footprint, never a permanent
    maximum. Public sites consume conserved regional land. Private sites may first
    consume already-granted but not-yet-developed holding area; that land moves from
    the region's private_holdings partition into nested site parcel area.
    """
    area = max(0.0, float(area_km2))
    if area <= 0:
        raise ValueError("site parcel expansion requires positive area")
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), MutableMapping) else None
    regions = registry.get("regions", {}) if isinstance(registry.get("regions"), MutableMapping) else None
    holdings = registry.get("holdings", {}) if isinstance(registry.get("holdings"), MutableMapping) else None
    if not isinstance(sites, MutableMapping) or site_ref not in sites or not isinstance(sites[site_ref], MutableMapping):
        raise ValueError("unknown site land ledger")
    if not isinstance(regions, MutableMapping):
        raise ValueError("land region registry is invalid")
    site = sites[site_ref]
    region_ref = str(site.get("region_ref", ""))
    region = regions.get(region_ref)
    if not isinstance(region, MutableMapping):
        raise ValueError("site has no conserved parent region")
    uses = region.get("land_use_km2")
    if not isinstance(uses, MutableMapping):
        raise ValueError("parent region land use is invalid")

    private_owner = str(site.get("private_owner_ref", "") or "")
    source_category = str(source_land_category or "open_developable")
    holding_ref = None
    if private_owner:
        linked = []
        if isinstance(holdings, MutableMapping):
            linked = [
                (ref, row) for ref, row in holdings.items()
                if isinstance(row, MutableMapping) and str(row.get("owner_ref")) == private_owner
                and str(row.get("region_ref")) == region_ref and str(row.get("site_ref") or "") == site_ref
            ]
        if linked:
            holding_ref, holding = sorted(linked, key=lambda x: str(x[0]))[0]
            slack = max(0.0, _num(holding.get("area_km2")) - _num(site.get("parcel_area_km2")))
            if slack + 1e-9 < area:
                raise ValueError("private site lacks enough already-granted adjacent holding area; acquire more land first")
            available_private = _num(uses.get("private_holdings"))
            if available_private + 1e-9 < area:
                raise ValueError("parent region private-holdings partition is smaller than the undeveloped granted area")
            uses["private_holdings"] = _round(available_private - area)
        else:
            raise ValueError("private site expansion requires a linked holding")
    else:
        available = _num(uses.get(source_category))
        if available + 1e-9 < area:
            raise ValueError(f"parent region lacks enough {source_category} land for site expansion")
        uses[source_category] = _round(available - area)

    region["nested_site_parcels_km2"] = _round(_num(region.get("nested_site_parcels_km2")) + area)
    site["parcel_area_km2"] = _round(_num(site.get("parcel_area_km2")) + area)
    external = site.setdefault("external_land_use_km2", {})
    if not isinstance(external, MutableMapping):
        raise ValueError("site external land-use partition is invalid")
    external["open_developable"] = _round(_num(external.get("open_developable")) + area)
    require_valid_land_registry(registry)
    return {
        "site_ref": site_ref,
        "region_ref": region_ref,
        "parcel_area_km2": site["parcel_area_km2"],
        "area_added_km2": _round(area),
        "source_land_category": "private_holdings" if private_owner else source_category,
        "holding_ref": holding_ref,
    }


def create_settlement_site_parcel(
    registry: MutableMapping[str, Any],
    *,
    site_ref: str,
    region_ref: str,
    state: str,
    name: str,
    terrain: str,
    parcel_area_km2: float,
) -> dict[str, Any]:
    """Create one unfortified settlement parcel by conserving parent-region land."""
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), MutableMapping) else None
    regions = registry.get("regions", {}) if isinstance(registry.get("regions"), MutableMapping) else None
    if not isinstance(sites, MutableMapping) or not isinstance(regions, MutableMapping):
        raise ValueError("land registry is invalid")
    if site_ref in sites:
        raise ValueError("settlement land parcel already exists")
    region = regions.get(region_ref)
    if not isinstance(region, MutableMapping):
        raise ValueError("settlement foundation requires a conserved parent region")
    area = max(0.01, float(parcel_area_km2))
    uses = region.get("land_use_km2")
    if not isinstance(uses, MutableMapping):
        raise ValueError("parent region land use is invalid")
    available = _num(uses.get("open_developable"))
    if available + 1e-9 < area:
        raise ValueError("parent region lacks open developable land for settlement foundation")
    uses["open_developable"] = _round(available - area)
    region["nested_site_parcels_km2"] = _round(_num(region.get("nested_site_parcels_km2")) + area)
    # A foundation parcel begins unwalled. The initial package occupies part of the
    # parcel, while the remainder stays available for later physical growth.
    residential = _round(area * 0.28)
    industry = _round(area * 0.06)
    civic = _round(area * 0.05)
    military = _round(area * 0.02)
    training = _round(area * 0.01)
    transport = _round(area * 0.08)
    water = _round(area * 0.03)
    committed = residential + industry + civic + military + training + transport + water
    open_land = _round(max(0.0, area - committed))
    sites[site_ref] = {
        "site_ref": site_ref, "name": str(name), "state": str(state), "region_ref": region_ref,
        "kind": "settlement", "terrain": str(terrain or region.get("terrain") or "default"),
        "private_owner_ref": None, "parent_site_ref": None,
        "parcel_area_km2": _round(area), "enclosed_area_km2": 0.0,
        "geometry": {"shape": "rectangle", "aspect_ratio": 1.8, **dict(zip(("length_km","width_km","perimeter_km"), rectangle_dimensions_from_area(area, 1.8)))},
        "enclosed_land_use_km2": {},
        "external_land_use_km2": {
            "residential": residential, "industry": industry, "civic_storage": civic,
            "military": military, "training": training, "transport": transport, "water": water,
            "fortification": 0.0, "open_developable": open_land,
        },
        "fortification": {
            "active": False, "constructed_outer_perimeter_km": 0.0, "outer_wall_length_built_cumulative_km": 0.0,
            "internal_absorbed_wall_km": 0.0, "wall_height_m": 0.0, "wall_base_thickness_m": 0.0,
            "wall_crown_thickness_m": 0.0, "moat_width_m": 0.0, "moat_depth_m": 0.0, "tower_count": 0, "gate_count": 0,
        },
        "reserved_land_km2": {},
    }
    require_valid_land_registry(registry)
    return deepcopy(sites[site_ref])

def owner_land_summary(registry: Mapping[str, Any], owner_ref: str) -> dict[str, Any]:
    holdings = registry.get("holdings", {}) if isinstance(registry.get("holdings"), Mapping) else {}
    rows = [dict(v) for v in holdings.values() if isinstance(v, Mapping) and str(v.get("owner_ref")) == owner_ref]
    private = sum(max(0.0, _num(v.get("area_km2"))) for v in rows)
    # Sovereign total is derived from controlled region authorities, never persisted as
    # a second land owner in this file.
    return {"owner_ref": owner_ref, "private_holding_area_km2": _round(private), "holding_refs": sorted(str(v.get("holding_ref")) for v in rows if v.get("holding_ref"))}


def grant_house_land(registry: MutableMapping[str, Any], *, house_ref: str, region_ref: str, area_km2: float, grant_ref: str, adjacent_to_holding_ref: str | None = None) -> dict[str, Any]:
    area = max(0.01, float(area_km2))
    regions = registry.get("regions", {}) if isinstance(registry.get("regions"), MutableMapping) else None
    holdings = registry.get("holdings", {}) if isinstance(registry.get("holdings"), MutableMapping) else None
    if not isinstance(regions, MutableMapping) or region_ref not in regions or not isinstance(regions[region_ref], MutableMapping):
        raise ValueError("land grant region has no conserved territorial ledger")
    if not isinstance(holdings, MutableMapping):
        raise ValueError("land holding registry is invalid")
    region = regions[region_ref]; uses = region.get("land_use_km2")
    if not isinstance(uses, MutableMapping):
        raise ValueError("land grant region use is invalid")
    available = _num(uses.get("open_developable"))
    if available + 1e-9 < area:
        raise ValueError("region lacks unallocated developable land for this grant")
    uses["open_developable"] = _round(available - area)
    # Private property is still inside sovereign territory, so the region area is not
    # reduced. The transferred area moves into a dedicated private-holdings partition.
    uses["private_holdings"] = _round(_num(uses.get("private_holdings")) + area)
    if adjacent_to_holding_ref and adjacent_to_holding_ref in holdings:
        holding = holdings[adjacent_to_holding_ref]
        if str(holding.get("owner_ref")) != house_ref or str(holding.get("region_ref")) != region_ref:
            raise ValueError("adjacent holding does not belong to the grantee in the same region")
        holding["area_km2"] = _round(_num(holding.get("area_km2")) + area)
        holding.setdefault("grant_refs", []).append(grant_ref)
        result_ref = adjacent_to_holding_ref
    else:
        token = grant_ref.replace(".", "_").replace(":", "_")[-36:]
        result_ref = f"holding_{house_ref.removeprefix('house_')}_{token}"
        suffix = 1
        base = result_ref
        while result_ref in holdings:
            suffix += 1; result_ref = f"{base}_{suffix}"
        holdings[result_ref] = {"holding_ref": result_ref, "owner_ref": house_ref, "region_ref": region_ref, "area_km2": _round(area), "site_ref": None, "grant_refs": [grant_ref], "status": "held"}
    require_valid_land_registry(registry)
    return {"holding_ref": result_ref, "owner_ref": house_ref, "region_ref": region_ref, "area_granted_km2": _round(area)}


__all__ = [
    "LAND_RULES_PATH", "LAND_STATE_PATH", "validate_land_registry", "require_valid_land_registry",
    "rectangle_dimensions_from_perimeter", "rectangle_dimensions_from_area", "stadium_geometry_from_area_perimeter",
    "site_land_requirement_km2", "land_category_for_work", "reserve_site_land", "release_site_land_reservation",
    "apply_site_land_reservation", "land_use_development_work_spec", "apply_land_use_conversion",
    "farmland_conversion_work_spec", "apply_farmland_conversion", "productive_land_area_km2", "site_circulation_minimum_km2",
    "enclosure_expansion_geometry", "wall_expansion_work_spec", "apply_enclosure_expansion",
    "nested_site_children", "enclosure_chain", "urban_capacity_land_budget", "site_enclosure_layers", "productive_labor_access_factor",
    "owner_land_summary", "grant_house_land", "expand_site_parcel", "create_settlement_site_parcel", "strategic_region_frontiers", "adjacent_regions", "terrain_factor", "site_default_build_zone",
    "defensive_store_procurement_spec", "baseline_fortification_work_spec",
]
