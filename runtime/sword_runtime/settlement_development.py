"""Conserved dynamic settlement founding and physical settlement classification.

A settlement is a geographic/physical owner, never a source of people.  Founding
creates an empty routed site plus already-funded physical works, then queues real
households to travel from an existing demographic owner.  Later classification is
computed from current residents and completed physical support, not from RPG levels.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.land_development import LAND_RULES_PATH, LAND_STATE_PATH, apply_site_land_reservation, reserve_site_land

DYNAMIC_GEOGRAPHY_PATH = "state/geography/dynamic.json"
INFRASTRUCTURE_PATH = "state/infrastructure/settlements.json"
TERRITORY_PATH = "state/territory/control.json"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned[:48] or "settlement"


def _location_rows(planner) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    static = planner.read("game/data/world/locations.json")
    for row in static.get("locations", []):
        if isinstance(row, Mapping) and row.get("ref"):
            rows[str(row["ref"])] = row
    dynamic = planner.read_optional(DYNAMIC_GEOGRAPHY_PATH)
    if isinstance(dynamic, Mapping):
        for row in dynamic.get("locations", []):
            if isinstance(row, Mapping) and row.get("ref"):
                rows[str(row["ref"])] = row
    return rows


def settlement_classification(*, residents: int, site: Mapping[str, Any]) -> str:
    """Classify a settlement by people plus physical/civic capability.

    Thresholds classify names only. They never cap population, construction, or
    migration. A large unsupported camp therefore does not become a city merely
    because many bodies are present.
    """
    n = max(0, int(residents))
    support = site.get("physical_support", {}) if isinstance(site.get("physical_support"), Mapping) else {}
    effective = max(0, int(site.get("effective_resident_support_capacity_people", 0)))
    works = site.get("works", {}) if isinstance(site.get("works"), Mapping) else {}
    market = float(works.get("market_floor_area_m2", 0)) > 0 or float(works.get("workshop_positions", 0)) >= 120
    admin = float(works.get("administrative_floor_area_m2", 0)) > 0
    sanitation = max(0, int(support.get("sanitation_capacity_people", 0))) >= n if n else False
    if n >= 20_000 and effective >= n and sanitation and market and admin:
        return "city"
    if n >= 5_000 and effective >= n and sanitation and market:
        return "town"
    if n >= 500 and effective >= n:
        return "village"
    return "hamlet"


def refresh_dynamic_settlement_class(planner, site_ref: str) -> str | None:
    dynamic = planner.read_optional(DYNAMIC_GEOGRAPHY_PATH)
    if not isinstance(dynamic, Mapping):
        return None
    doc = copy.deepcopy(dict(dynamic))
    row = next((x for x in doc.get("locations", []) if isinstance(x, dict) and str(x.get("ref")) == str(site_ref)), None)
    if not isinstance(row, dict):
        return None
    state = str(row.get("state", ""))
    pop = planner.read_optional(f"state/population/{state}.json")
    infra = planner.read_optional(INFRASTRUCTURE_PATH)
    if not isinstance(pop, Mapping) or not isinstance(infra, Mapping):
        return None
    prow = pop.get("local_population", {}).get("sites", {}).get(site_ref, {})
    residents = 0
    if isinstance(prow, Mapping):
        residents = max(0, int(prow.get("civilian_population", 0))) + max(0, int(prow.get("service_population", 0)))
    irow = infra.get("sites", {}).get(site_ref, {}) if isinstance(infra.get("sites"), Mapping) else {}
    if not isinstance(irow, Mapping):
        return None
    cls = settlement_classification(residents=residents, site=irow)
    row["settlement_class"] = cls
    row["current_residents"] = residents
    planner.put(DYNAMIC_GEOGRAPHY_PATH, doc)
    return cls


def complete_settlement_foundation(planner, *, institution: Mapping[str, Any], project: MutableMapping[str, Any], at: str) -> dict[str, Any]:
    effect = project.get("effect", {}) if isinstance(project.get("effect"), Mapping) else {}
    source_site = str(effect.get("source_site_ref", ""))
    name = str(effect.get("new_settlement_name", "")).strip()
    settlers = max(1, int(effect.get("initial_settlers", 0)))
    if not source_site or not name:
        raise ValueError("settlement foundation requires source_site_ref and new_settlement_name")
    rows = _location_rows(planner)
    source = rows.get(source_site)
    if not isinstance(source, Mapping):
        raise ValueError("settlement foundation source is not a routed location")
    state = str(source.get("state", ""))
    if not state:
        raise ValueError("settlement foundation source lacks a native state")
    population_path = f"state/population/{state}.json"
    population = copy.deepcopy(planner.read(population_path))
    source_pop = population.get("local_population", {}).get("sites", {}).get(source_site, {})
    if not isinstance(source_pop, Mapping) or int(source_pop.get("civilian_population", 0)) < settlers:
        raise ValueError("settlement foundation lacks conserved source civilians")

    digest = hashlib.sha256(f"{project.get('project_ref')}|{state}|{source_site}|{name}".encode()).hexdigest()[:12]
    new_ref = f"loc_{state}_{_slug(name)}_{digest[:6]}"
    route_ref = f"route_{source_site.removeprefix('loc_')}_{new_ref.removeprefix('loc_')}"
    dynamic0 = planner.read_optional(DYNAMIC_GEOGRAPHY_PATH)
    dynamic = copy.deepcopy(dict(dynamic0)) if isinstance(dynamic0, Mapping) else {
        "schema": "generic-object", "authority": True, "locations": [], "routes": [],
        "rule": "Dynamic settlements and routes are exact current geography. They create no people, economy, troops, or claims by existence alone.",
    }
    if any(isinstance(x, Mapping) and str(x.get("ref")) == new_ref for x in dynamic.get("locations", [])):
        raise ValueError("settlement foundation already exists")

    region_ref = source_site if str(source.get("kind", "")) == "region" else str(source.get("region_ref") or source.get("parent_ref") or "")
    if not region_ref:
        raise ValueError("settlement foundation source has no conserved territorial region")
    parent_ref = region_ref
    location = {
        "ref": new_ref, "name": name, "kind": "settlement", "settlement_class": "hamlet",
        "state": state, "parent_ref": parent_ref, "region_ref": region_ref,
        "strategic_node": False, "demographic_eligible": True, "fortified": False,
        "founded_at": at, "foundation_project_ref": str(project.get("project_ref", "")),
        "authority_basis": "completed funded settlement foundation; residents arrive only through conserved population movement",
    }
    dynamic.setdefault("locations", []).append(location)
    dynamic.setdefault("routes", []).append({
        "ref": route_ref, "a": source_site, "b": new_ref, "kind": "local_access_road",
        "modes": ["foot", "horse", "convoy", "formation"], "terrain": str(source.get("terrain", "plain")),
        "road_quality": "track", "duration_hours": 2, "length_km": 5.0, "road_width_m": 4.0,
        "surface": "compacted_earth", "maximum_grade_percent": 6.0, "files_abreast": 4,
        "daily_troop_throughput": 18000, "daily_wagon_throughput": 650,
        "authority_basis": "game-authored exact settlement foundation access road",
    })
    planner.put(DYNAMIC_GEOGRAPHY_PATH, dynamic)

    # A new settlement consumes a real parcel inside its parent region. The parcel
    # is sized from the shared village density/buffer rule, not from state identity.
    from sword_runtime.land_development import LAND_STATE_PATH, create_settlement_site_parcel
    land = copy.deepcopy(planner.read(LAND_STATE_PATH))
    land_rules = planner.read("game/data/mechanics/land-development.json")
    village_rule = land_rules.get("site_geometry_defaults", {}).get("village", {})
    density = max(1.0, float(village_rule.get("unwalled_population_density", 2500) or 2500))
    parcel_multiplier = max(1.0, float(village_rule.get("parcel_multiplier_over_enclosure", 2.5) or 2.5))
    # The foundation package is designed for 1,000 supported residents even when
    # the first arriving household cohort is smaller. That prevents tiny arbitrary
    # parcels from becoming permanent caps on later growth.
    parcel_area_km2 = max(0.01, (1000.0 / density) * parcel_multiplier)
    create_settlement_site_parcel(
        land, site_ref=new_ref, region_ref=region_ref, state=state, name=name,
        terrain=str(source.get("terrain", "default")), parcel_area_km2=parcel_area_km2,
    )
    planner.put(LAND_STATE_PATH, land)

    # Empty demographic destination. The same households are debited from the
    # source only when the normal population-mobility transaction is queued.
    sites = population.setdefault("local_population", {}).setdefault("sites", {})
    strata_keys = list((source_pop.get("civilian_strata", {}) or {}).keys())
    sites[new_ref] = {
        "location_ref": new_ref, "initial_population": 0, "civilian_population": 0,
        "civilian_strata": {str(k): 0 for k in strata_keys}, "agricultural_available": 0,
        "service_population": 0, "serving_native_military": 0, "serving_foreign_military": 0,
        "private_household_military": 0, "rebel_military": 0, "candidate_reservations": {},
        "candidates_reserved": 0, "reserved_candidates": 0, "deaths_cumulative": 0, "displaced": 0,
        "service_allocations": {},
    }
    planner.put(population_path, population)

    infra = copy.deepcopy(planner.read(INFRASTRUCTURE_PATH))
    # Foundation package physically supports 1,000 people. Later growth requires
    # ordinary infrastructure projects and therefore real labor/materials/time.
    support_people = 1000
    infra.setdefault("sites", {})[new_ref] = {
        "site_ref": new_ref, "authority_basis": "completed settlement foundation package",
        "physical_support": {
            "housing_capacity_people": support_people, "water_capacity_people": support_people,
            "sanitation_capacity_people": support_people, "food_storage_distribution_capacity_people": support_people,
            "ordinary_work_access_capacity_people": support_people,
        },
        "effective_resident_support_capacity_people": support_people, "condition": 1.0,
        "works": {"access_road_km": 5.0, "public_wells": 6, "housing_floor_area_m2": 30000,
                  "granary_storage_kg": 350000, "workshop_positions": 40},
        "constructed_works": {str(project.get("project_ref", "")): {
            "project_ref": str(project.get("project_ref", "")), "category": "settlement_foundation",
            "completed_at": at, "condition": 1.0, "design_residents": support_people,
        }},
        "capacity_rule": "effective support is physical headroom, not a legal population cap",
    }
    planner.put(INFRASTRUCTURE_PATH, infra)

    territory = copy.deepcopy(planner.read(TERRITORY_PATH))
    source_control = territory.get("sites", {}).get(source_site, {}) if isinstance(territory.get("sites"), Mapping) else {}
    territory.setdefault("sites", {})[new_ref] = {
        "controller": str(source_control.get("controller", f"state_{state}")),
        "claimant": str(source_control.get("claimant", f"state_{state}")),
        "control_basis": f"founded from {source_site} under the same saved territorial authority",
        "fortified": False,
    }
    territory.setdefault("route_states", {})[route_ref] = {"status": "open", "controller": str(source_control.get("controller", f"state_{state}"))}
    planner.put(TERRITORY_PATH, territory)

    # Add an empty local private-economy region so later production/tax/migration
    # can route without inventing a second economy owner.
    ep, eco = planner._private_economy(state)
    regions = eco.setdefault("local_regions", {}).setdefault("regions", {})
    regions[new_ref] = {
        "location_ref": new_ref, "resident_population": 0, "cash_silver": 0,
        "commodity_stock": {k: 0 for k in eco.get("commodity_stock", {})},
    }
    planner._write_private_economy(ep, eco)

    move = planner._queue_population_move(
        source_population_path=population_path, destination_population_path=population_path,
        origin_site_ref=source_site, destination_site_ref=new_ref, count=min(settlers, support_people),
        departed_at=at, basis=f"settlement foundation {project.get('project_ref')}",
    )
    project["founded_settlement_ref"] = new_ref
    project["foundation_route_ref"] = route_ref
    project["initial_population_movement_ref"] = move.get("migration_ref") if isinstance(move, Mapping) else None
    refresh_dynamic_settlement_class(planner, new_ref)
    return {"settlement_ref": new_ref, "route_ref": route_ref, "initial_settlers": min(settlers, support_people), "migration_ref": project.get("initial_population_movement_ref")}


__all__ = ["DYNAMIC_GEOGRAPHY_PATH", "complete_settlement_foundation", "refresh_dynamic_settlement_class", "settlement_classification"]

# ---------------------------------------------------------------------------
# Deterministic long-horizon settlement development
# ---------------------------------------------------------------------------

_DEVELOPABLE_KINDS = {"settlement", "village", "town", "city", "capital", "fort", "fortress", "pass", "fortified_settlement", "estate"}
_SUPPORT_TO_BLUEPRINT = {
    "housing_capacity_people": "settlement_housing_courtyard_block",
    "water_capacity_people": "settlement_public_well_cluster",
    "sanitation_capacity_people": "settlement_drainage_latrine_district",
    "food_storage_distribution_capacity_people": "settlement_granary_1000t",
    "ordinary_work_access_capacity_people": "settlement_workshop_court_120",
}
_SUPPORT_TARGET_KEYS = {
    "housing_capacity_people": "housing",
    "water_capacity_people": "water",
    "sanitation_capacity_people": "sanitation",
    "food_storage_distribution_capacity_people": "food_storage_distribution",
    "ordinary_work_access_capacity_people": "ordinary_work_access",
}


def _static_location_map(planner) -> dict[str, Mapping[str, Any]]:
    rows = _location_rows(planner)
    return {str(ref): row for ref, row in rows.items()}


def _site_residents(planner, state: str, site_ref: str) -> tuple[int, Mapping[str, Any]]:
    pop = planner.read_optional(f"state/population/{state}.json")
    if not isinstance(pop, Mapping):
        return 0, {}
    sites = pop.get("local_population", {}).get("sites", {}) if isinstance(pop.get("local_population"), Mapping) else {}
    row = sites.get(site_ref, {}) if isinstance(sites, Mapping) else {}
    if not isinstance(row, Mapping):
        return 0, {}
    residents = max(0, int(row.get("civilian_population", 0))) + max(0, int(row.get("service_population", 0)))
    return residents, row


def _functional_profiles(location: Mapping[str, Any], territory_site: Mapping[str, Any]) -> list[str]:
    kind = str(location.get("kind", ""))
    out: list[str] = []
    if kind in {"capital", "city", "town", "fortified_settlement"}:
        out.extend(["administrative", "market"])
    if kind in {"fort", "fortress", "pass"} or territory_site.get("fortified") is True:
        out.extend(["military", "logistics"])
    if kind in {"village", "estate"}:
        out.append("agrarian")
    if location.get("strategic_node") is True:
        out.append("transport")
    return sorted(set(out))


def _fortification_class(location: Mapping[str, Any], territory_site: Mapping[str, Any], site: Mapping[str, Any]) -> str:
    kind = str(location.get("kind", ""))
    works = site.get("works", {}) if isinstance(site.get("works"), Mapping) else {}
    wall_m = max(0.0, float(works.get("fortification_wall_length_m", 0) or 0))
    towers = max(0, int(works.get("fortification_towers", 0) or 0))
    if kind in {"fortress", "pass"}:
        return "major_fortress" if kind == "fortress" or wall_m >= 3000 or towers >= 12 else "fortress"
    if kind == "fort":
        return "fort"
    if wall_m >= 6000 or towers >= 30:
        return "major_fortress"
    if wall_m >= 3000 or towers >= 12:
        return "fortress"
    if wall_m >= 1000 or towers >= 4:
        return "fort"
    if territory_site.get("fortified") is True:
        return "walled_or_fortified"
    if wall_m > 0 or towers > 0:
        return "local_defensive_works"
    return "none"


def ensure_settlement_development_profile(planner, *, site_ref: str, at: str) -> dict[str, Any] | None:
    registry = copy.deepcopy(planner.read(INFRASTRUCTURE_PATH))
    site = registry.get("sites", {}).get(site_ref) if isinstance(registry.get("sites"), Mapping) else None
    if not isinstance(site, dict):
        return None
    location = _static_location_map(planner).get(site_ref, {})
    if str(location.get("kind", "")) not in _DEVELOPABLE_KINDS:
        return None
    territory = planner.read(TERRITORY_PATH)
    tsite = territory.get("sites", {}).get(site_ref, {}) if isinstance(territory.get("sites"), Mapping) else {}
    state = str(location.get("state", ""))
    residents, _row = _site_residents(planner, state, site_ref) if state else (0, {})
    profile = site.setdefault("development_profile", {})
    if not isinstance(profile, dict):
        profile = {}; site["development_profile"] = profile
    profile["legal_status"] = str(location.get("kind", "settlement"))
    profile["physical_settlement_class"] = settlement_classification(residents=residents, site=site)
    profile["fortification_class"] = _fortification_class(location, tsite if isinstance(tsite, Mapping) else {}, site)
    profile["functional_profiles"] = _functional_profiles(location, tsite if isinstance(tsite, Mapping) else {})
    profile["current_residents"] = residents
    profile.setdefault("review_month_accumulator", 0)
    profile.setdefault("last_review", at)
    planner.put(INFRASTRUCTURE_PATH, registry)
    return copy.deepcopy(profile)


def _development_coverage(site: Mapping[str, Any], residents: int, physics: Mapping[str, Any]) -> dict[str, float]:
    support = site.get("physical_support", {}) if isinstance(site.get("physical_support"), Mapping) else {}
    targets = physics.get("development", {}).get("minimum_coverage", {}) if isinstance(physics.get("development"), Mapping) else {}
    n = max(1, int(residents))
    result: dict[str, float] = {}
    for key, target_key in _SUPPORT_TARGET_KEYS.items():
        capacity = max(0.0, float(support.get(key, 0) or 0))
        required = n * max(0.01, float(targets.get(target_key, 1.0) or 1.0))
        result[key] = capacity / required if required > 0 else 99.0
    return result


def _register_development_project_host(planner, *, project_ref: str, site_ref: str, state: str, due_at: str) -> None:
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    hosts = runtime.setdefault("hosts", {})
    events = runtime.setdefault("events", [])
    token = hashlib.sha256(project_ref.encode("utf-8")).hexdigest()[:18]
    host_id = f"host_settlement_project_{token}"
    event_id = f"event_settlement_project_{token}"
    hosts[host_id] = {
        "host_id": host_id,
        "kind": "settlement_development_project",
        "owner_ref": site_ref,
        "state": state,
        "project_ref": project_ref,
        "event_id": event_id,
        "next_due": due_at,
        "resolved_through": str(runtime.get("world_time")),
        "safe_through": str(CampaignTime.parse(due_at).add_seconds(-1)),
        "recurrence_seconds": 0,
    }
    existing = next((x for x in events if isinstance(x, dict) and x.get("event_id") == event_id), None)
    payload = {"event_id": event_id, "kind": "settlement_development_project", "priority": 88, "target_host": host_id, "due_at": due_at}
    if isinstance(existing, dict):
        existing.clear(); existing.update(payload)
    else:
        events.append(payload)
    planner.put("state/runtime.json", runtime)


def _autonomous_start_project(planner, *, state: str, site_ref: str, blueprint_ref: str, quantity: int, at: str) -> dict[str, Any] | None:
    from sword_runtime.infrastructure_projects import calculate_project_schedule, infrastructure_work_spec
    work = infrastructure_work_spec(planner.read, blueprint_ref=blueprint_ref, target_site_ref=site_ref, quantity=quantity)
    state_path = f"state/states/{state}.json"
    state_doc = copy.deepcopy(planner.read(state_path))
    treasury = max(0, int(state_doc.get("treasury_silver", 0)))
    silver = max(0, int(work.get("silver_cost", 0)))
    if treasury < silver:
        return None
    ep, eco = planner._private_economy(state)
    try:
        local_ref, local = planner._local_economy_region(state, eco, site_ref)
    except ValueError:
        return None
    commodities = local.setdefault("commodity_stock", {})
    materials = max(0, int(work.get("construction_material_units", 0)))
    if int(commodities.get("construction_material_units", 0)) < materials:
        return None
    pop = planner.read(f"state/population/{state}.json")
    local_pop = pop.get("local_population", {}).get("sites", {}).get(local_ref, {}) if isinstance(pop.get("local_population"), Mapping) else {}
    strata = local_pop.get("civilian_strata", {}) if isinstance(local_pop, Mapping) and isinstance(local_pop.get("civilian_strata"), Mapping) else {}
    craft = max(0, int(strata.get("craft_and_industry", 0)))
    civil_rules = planner.read("game/data/mechanics/civil-economy.json")
    fraction = max(0.0, min(1.0, float(civil_rules.get("labor", {}).get("construction_labor_fraction_of_craft_workers", 0.12))))
    pool = max(1, int(math.floor(craft * fraction)))
    labor = eco.setdefault("labor_allocation", {})
    active = labor.setdefault("projects", {})
    active_workers = 0
    current = CampaignTime.parse(at)
    for row in active.values() if isinstance(active, Mapping) else []:
        if not isinstance(row, Mapping):
            continue
        release = row.get("releases_at")
        if isinstance(release, str) and CampaignTime.parse(release) <= current:
            continue
        active_workers += max(0, int(row.get("workers", 0)))
    available = max(0, pool - active_workers)
    if available <= 0:
        return None
    schedule = calculate_project_schedule(planner.read, work=work, available_workers=available)
    workers = int(schedule["construction_workers"])
    due = str(current.add_seconds(int(schedule["duration_hours"]) * 3600))
    project_ref = "settlement_dev_" + hashlib.sha256(f"{state}|{site_ref}|{blueprint_ref}|{quantity}|{at}".encode("utf-8")).hexdigest()[:20]
    land = copy.deepcopy(planner.read(LAND_STATE_PATH))
    try:
        land_reservation = reserve_site_land(
            land, site_ref=site_ref, project_ref=project_ref, work=work, rules=planner.read(LAND_RULES_PATH)
        )
    except ValueError:
        return None

    state_doc["treasury_silver"] = treasury - silver
    local["cash_silver"] = int(local.get("cash_silver", 0)) + silver
    commodities["construction_material_units"] = int(commodities.get("construction_material_units", 0)) - materials
    active[project_ref] = {
        "workers": workers, "labor_hours": int(work.get("labor_hours", 0)), "allocated_at": at,
        "releases_at": due, "institution_ref": f"settlement_development:{site_ref}", "location_ref": local_ref,
        "schedule": copy.deepcopy(schedule),
    }
    labor["construction_worker_pool"] = pool
    labor["allocated_construction_workers"] = active_workers + workers

    infra = copy.deepcopy(planner.read(INFRASTRUCTURE_PATH))
    site = infra["sites"][site_ref]
    projects = site.setdefault("development_projects", {})
    projects[project_ref] = {
        "project_ref": project_ref, "status": "active", "state": state, "site_ref": site_ref,
        "blueprint_ref": blueprint_ref, "quantity": quantity, "started_at": at, "completes_at": due,
        "physical_work_spec": copy.deepcopy(work), "construction_schedule": copy.deepcopy(schedule),
        "land_reservation": copy.deepcopy(land_reservation),
        "inputs_reserved": {
            "silver": silver, "construction_material_units": materials, "labor_hours": int(work.get("labor_hours", 0)),
            "construction_workers": workers, "funding_ref": state_path, "material_source_ref": ep,
            "regional_source_ref": local_ref, "cash_cost_breakdown": copy.deepcopy(work.get("cash_cost_breakdown", {})),
            "material_equivalent_tonnes": work.get("material_equivalent_tonnes"),
        },
    }
    planner.put(LAND_STATE_PATH, land)
    planner.put(state_path, state_doc)
    planner._sync_local_economy_aggregate(eco)
    planner._write_private_economy(ep, eco)
    planner.put(INFRASTRUCTURE_PATH, infra)
    _register_development_project_host(planner, project_ref=project_ref, site_ref=site_ref, state=state, due_at=due)
    return copy.deepcopy(projects[project_ref])



def start_private_infrastructure_project(
    planner,
    *,
    owner_ref: str,
    treasury_path: str,
    state: str,
    site_ref: str,
    blueprint_ref: str,
    quantity: int,
    at: str,
    economic_source_site_ref: str | None = None,
) -> dict[str, Any] | None:
    """Start one normal physical project for a private owner such as a House.

    The owner gets no alternate construction law. Geometry, land, materials,
    labor, wages, haul and calendar time come from the same shared blueprints as
    sovereign/autonomous settlement work. The only difference is the exact
    treasury that pays the bill.
    """
    from sword_runtime.infrastructure_projects import calculate_project_schedule, infrastructure_work_spec

    work = infrastructure_work_spec(planner.read, blueprint_ref=blueprint_ref, target_site_ref=site_ref, quantity=quantity)
    treasury = copy.deepcopy(planner.read(treasury_path))
    silver = max(0, int(work.get("silver_cost", 0)))
    if max(0, int(treasury.get("silver", 0))) < silver:
        return None
    ep, eco = planner._private_economy(state)
    source_site = str(economic_source_site_ref or site_ref)
    try:
        local_ref, local = planner._local_economy_region(state, eco, source_site)
    except ValueError:
        return None
    commodities = local.setdefault("commodity_stock", {})
    materials = max(0, int(work.get("construction_material_units", 0)))
    if int(commodities.get("construction_material_units", 0)) < materials:
        return None

    pop = planner.read(f"state/population/{state}.json")
    local_pop = pop.get("local_population", {}).get("sites", {}).get(local_ref, {}) if isinstance(pop.get("local_population"), Mapping) else {}
    strata = local_pop.get("civilian_strata", {}) if isinstance(local_pop, Mapping) and isinstance(local_pop.get("civilian_strata"), Mapping) else {}
    craft = max(0, int(strata.get("craft_and_industry", 0)))
    civil_rules = planner.read("game/data/mechanics/civil-economy.json")
    fraction = max(0.0, min(1.0, float(civil_rules.get("labor", {}).get("construction_labor_fraction_of_craft_workers", 0.12))))
    pool = max(1, int(math.floor(craft * fraction)))
    labor = eco.setdefault("labor_allocation", {})
    active = labor.setdefault("projects", {})
    active_workers = 0
    current = CampaignTime.parse(at)
    for row in active.values() if isinstance(active, Mapping) else []:
        if not isinstance(row, Mapping):
            continue
        release = row.get("releases_at")
        if isinstance(release, str) and CampaignTime.parse(release) <= current:
            continue
        active_workers += max(0, int(row.get("workers", 0)))
    available = max(0, pool - active_workers)
    if available <= 0:
        return None
    schedule = calculate_project_schedule(planner.read, work=work, available_workers=available)
    workers = int(schedule["construction_workers"])
    due = str(current.add_seconds(int(schedule["duration_hours"]) * 3600))
    token = hashlib.sha256(f"{owner_ref}|{site_ref}|{blueprint_ref}|{quantity}|{at}".encode("utf-8")).hexdigest()[:20]
    project_ref = f"private_site_dev_{token}"

    land = copy.deepcopy(planner.read(LAND_STATE_PATH))
    try:
        land_reservation = reserve_site_land(
            land, site_ref=site_ref, project_ref=project_ref, work=work, rules=planner.read(LAND_RULES_PATH)
        )
    except ValueError:
        return None

    treasury["silver"] = int(treasury.get("silver", 0)) - silver
    local["cash_silver"] = int(local.get("cash_silver", 0)) + silver
    commodities["construction_material_units"] = int(commodities.get("construction_material_units", 0)) - materials
    active[project_ref] = {
        "workers": workers,
        "labor_hours": int(work.get("labor_hours", 0)),
        "allocated_at": at,
        "releases_at": due,
        "institution_ref": f"private_owner:{owner_ref}",
        "location_ref": local_ref,
        "schedule": copy.deepcopy(schedule),
    }
    labor["construction_worker_pool"] = pool
    labor["allocated_construction_workers"] = active_workers + workers

    infra = copy.deepcopy(planner.read(INFRASTRUCTURE_PATH))
    site = infra.get("sites", {}).get(site_ref) if isinstance(infra.get("sites"), Mapping) else None
    if not isinstance(site, dict):
        raise ValueError("private physical project target has no settlement infrastructure owner")
    projects = site.setdefault("development_projects", {})
    projects[project_ref] = {
        "project_ref": project_ref,
        "status": "active",
        "state": state,
        "private_owner_ref": str(owner_ref),
        "site_ref": site_ref,
        "blueprint_ref": blueprint_ref,
        "quantity": max(1, int(quantity)),
        "started_at": at,
        "completes_at": due,
        "physical_work_spec": copy.deepcopy(work),
        "construction_schedule": copy.deepcopy(schedule),
        "land_reservation": copy.deepcopy(land_reservation),
        "inputs_reserved": {
            "silver": silver,
            "construction_material_units": materials,
            "labor_hours": int(work.get("labor_hours", 0)),
            "construction_workers": workers,
            "funding_ref": treasury_path,
            "funding_owner_ref": str(owner_ref),
            "material_source_ref": ep,
            "regional_source_ref": local_ref,
            "cash_cost_breakdown": copy.deepcopy(work.get("cash_cost_breakdown", {})),
            "material_equivalent_tonnes": work.get("material_equivalent_tonnes"),
        },
    }
    planner.put(LAND_STATE_PATH, land)
    planner.put(treasury_path, treasury)
    planner._sync_local_economy_aggregate(eco)
    planner._write_private_economy(ep, eco)
    planner.put(INFRASTRUCTURE_PATH, infra)
    _register_development_project_host(planner, project_ref=project_ref, site_ref=site_ref, state=state, due_at=due)
    return copy.deepcopy(projects[project_ref])



def _autonomous_start_settlement_foundation(
    planner,
    *,
    state: str,
    source_site_ref: str,
    settlement_name: str,
    initial_settlers: int,
    at: str,
) -> dict[str, Any] | None:
    """Start one conserved state settlement foundation from real inputs.

    This is the autonomous counterpart of the player/institution foundation route.
    It spends the same registered package, reserves actual construction labor and
    materials, and creates no site or population until the scheduled completion.
    """
    from sword_runtime.infrastructure_projects import calculate_project_schedule, infrastructure_work_spec

    settlers = max(1, min(1000, int(initial_settlers)))
    pop_path = f"state/population/{state}.json"
    population = planner.read_optional(pop_path)
    source_pop = (population.get("local_population", {}).get("sites", {}).get(source_site_ref, {})
                  if isinstance(population, Mapping) else {})
    if not isinstance(source_pop, Mapping) or max(0, int(source_pop.get("civilian_population", 0))) < settlers:
        return None
    land = planner.read(LAND_STATE_PATH)
    region = land.get("regions", {}).get(source_site_ref, {}) if isinstance(land, Mapping) else {}
    if not isinstance(region, Mapping) or float((region.get("land_use_km2") or {}).get("open_developable", 0) or 0) < 1.0:
        return None

    work = infrastructure_work_spec(
        planner.read,
        blueprint_ref="settlement_foundation_package",
        target_site_ref=source_site_ref,
        quantity=1,
    )
    state_path = f"state/states/{state}.json"
    state_doc = copy.deepcopy(planner.read(state_path))
    treasury = max(0, int(state_doc.get("treasury_silver", 0)))
    silver = max(0, int(work.get("silver_cost", 0)))
    if treasury < silver:
        return None
    ep, eco = planner._private_economy(state)
    try:
        local_ref, local = planner._local_economy_region(state, eco, source_site_ref)
    except ValueError:
        return None
    commodities = local.setdefault("commodity_stock", {})
    materials = max(0, int(work.get("construction_material_units", 0)))
    if max(0, int(commodities.get("construction_material_units", 0))) < materials:
        return None

    strata = source_pop.get("civilian_strata", {}) if isinstance(source_pop.get("civilian_strata"), Mapping) else {}
    craft = max(0, int(strata.get("craft_and_industry", 0)))
    civil_rules = planner.read("game/data/mechanics/civil-economy.json")
    fraction = max(0.0, min(1.0, float(civil_rules.get("labor", {}).get("construction_labor_fraction_of_craft_workers", 0.12))))
    pool = max(0, int(math.floor(craft * fraction)))
    if pool <= 0:
        return None
    labor = eco.setdefault("labor_allocation", {})
    active = labor.setdefault("projects", {})
    current = CampaignTime.parse(at)
    active_workers = 0
    for row in active.values() if isinstance(active, Mapping) else []:
        if not isinstance(row, Mapping):
            continue
        release = row.get("releases_at")
        if isinstance(release, str) and CampaignTime.parse(release) <= current:
            continue
        active_workers += max(0, int(row.get("workers", 0)))
    available = max(0, pool - active_workers)
    if available <= 0:
        return None
    schedule = calculate_project_schedule(planner.read, work=work, available_workers=available)
    workers = max(1, int(schedule["construction_workers"]))
    due = str(current.add_seconds(max(1, int(schedule["duration_hours"])) * 3600))
    project_ref = "settlement_foundation_" + hashlib.sha256(
        f"{state}|{source_site_ref}|{settlement_name}|{at}".encode("utf-8")
    ).hexdigest()[:20]

    state_doc["treasury_silver"] = treasury - silver
    local["cash_silver"] = max(0, int(local.get("cash_silver", 0))) + silver
    commodities["construction_material_units"] = max(0, int(commodities.get("construction_material_units", 0))) - materials
    if hasattr(planner, "_record_private_realized_sale"):
        planner._record_private_realized_sale(
            local,
            amount_silver=silver,
            at=at,
            kind="autonomous_settlement_foundation_contract",
            resource="construction_material_units",
            quantity=materials,
        )
    active[project_ref] = {
        "workers": workers,
        "labor_hours": int(work.get("labor_hours", 0)),
        "allocated_at": at,
        "releases_at": due,
        "institution_ref": f"state_settlement_development:{state}",
        "location_ref": local_ref,
        "schedule": copy.deepcopy(schedule),
    }
    labor["construction_worker_pool"] = pool
    labor["allocated_construction_workers"] = active_workers + workers

    infra = copy.deepcopy(planner.read(INFRASTRUCTURE_PATH))
    source_site = infra.get("sites", {}).get(source_site_ref) if isinstance(infra.get("sites"), Mapping) else None
    if not isinstance(source_site, dict):
        return None
    projects = source_site.setdefault("development_projects", {})
    projects[project_ref] = {
        "project_ref": project_ref,
        "kind": "settlement_foundation",
        "status": "active",
        "state": state,
        "site_ref": source_site_ref,
        "source_site_ref": source_site_ref,
        "blueprint_ref": "settlement_foundation_package",
        "quantity": 1,
        "started_at": at,
        "completes_at": due,
        "effect": {
            "source_site_ref": source_site_ref,
            "new_settlement_name": settlement_name,
            "initial_settlers": settlers,
        },
        "physical_work_spec": copy.deepcopy(work),
        "construction_schedule": copy.deepcopy(schedule),
        "land_reservation": None,
        "inputs_reserved": {
            "silver": silver,
            "construction_material_units": materials,
            "labor_hours": int(work.get("labor_hours", 0)),
            "construction_workers": workers,
            "funding_ref": state_path,
            "funding_owner_ref": f"state_{state}",
            "material_source_ref": ep,
            "regional_source_ref": local_ref,
            "cash_cost_breakdown": copy.deepcopy(work.get("cash_cost_breakdown", {})),
            "material_equivalent_tonnes": work.get("material_equivalent_tonnes"),
        },
    }
    planner.put(state_path, state_doc)
    planner._sync_local_economy_aggregate(eco)
    planner._write_private_economy(ep, eco)
    planner.put(INFRASTRUCTURE_PATH, infra)
    _register_development_project_host(planner, project_ref=project_ref, site_ref=source_site_ref, state=state, due_at=due)
    return copy.deepcopy(projects[project_ref])


def _autonomous_foundation_candidate(planner, *, state: str) -> dict[str, Any] | None:
    """Choose a bounded lawful parent region for one new settlement."""
    rows = _location_rows(planner)
    pop = planner.read_optional(f"state/population/{state}.json")
    land = planner.read_optional(LAND_STATE_PATH)
    territory = planner.read_optional(TERRITORY_PATH)
    if not isinstance(pop, Mapping) or not isinstance(land, Mapping) or not isinstance(territory, Mapping):
        return None
    local_sites = pop.get("local_population", {}).get("sites", {}) if isinstance(pop.get("local_population"), Mapping) else {}
    dynamic_counts: dict[str, int] = {}
    all_settlement_counts: dict[str, int] = {}
    for ref, row in rows.items():
        if not isinstance(row, Mapping) or str(row.get("state", "")) != state:
            continue
        region_ref = str(row.get("region_ref", ""))
        if not region_ref or str(row.get("kind", "")) == "region":
            continue
        all_settlement_counts[region_ref] = all_settlement_counts.get(region_ref, 0) + 1
        if row.get("foundation_project_ref"):
            dynamic_counts[region_ref] = dynamic_counts.get(region_ref, 0) + 1
    candidates: list[tuple[float, str, int, str, int]] = []
    for ref, row in rows.items():
        if not isinstance(row, Mapping) or str(row.get("state", "")) != state or str(row.get("kind", "")) != "region":
            continue
        control = territory.get("sites", {}).get(ref, {}) if isinstance(territory.get("sites"), Mapping) else {}
        if isinstance(control, Mapping) and str(control.get("controller", f"state_{state}")) != f"state_{state}":
            continue
        region = land.get("regions", {}).get(ref, {}) if isinstance(land.get("regions"), Mapping) else {}
        open_land = max(0.0, float((region.get("land_use_km2") or {}).get("open_developable", 0) or 0)) if isinstance(region, Mapping) else 0.0
        if open_land < 1.0:
            continue
        prow = local_sites.get(ref, {}) if isinstance(local_sites, Mapping) else {}
        civilians = max(0, int(prow.get("civilian_population", 0))) if isinstance(prow, Mapping) else 0
        if civilians < 50_000:
            continue
        settlement_count = max(0, int(all_settlement_counts.get(ref, 0)))
        # More people and fewer existing named settlement nodes increase pressure.
        # The score is a routing heuristic only; it creates no resources or people.
        score = civilians / float(max(1, settlement_count + 1))
        ordinal = max(1, int(dynamic_counts.get(ref, 0)) + 1)
        candidates.append((score, ref, civilians, str(row.get("name", ref)), ordinal))
    if not candidates:
        return None
    _score, ref, civilians, region_name, ordinal = max(candidates, key=lambda x: (x[0], x[2], x[1]))
    settlers = max(250, min(1000, civilians // 1500))
    return {
        "source_site_ref": ref,
        "initial_settlers": settlers,
        "settlement_name": f"{region_name} Hamlet {ordinal}",
        "regional_civilian_population": civilians,
    }

def settle_development_project(planner, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    from sword_runtime.infrastructure_projects import apply_infrastructure_work
    project_ref = str(host.get("project_ref", "")); site_ref = str(host.get("owner_ref", "")); state = str(host.get("state", ""))
    if not project_ref or not site_ref or not state:
        return None
    infra = copy.deepcopy(planner.read(INFRASTRUCTURE_PATH))
    site = infra.get("sites", {}).get(site_ref) if isinstance(infra.get("sites"), Mapping) else None
    if not isinstance(site, dict):
        return None
    projects = site.get("development_projects", {}) if isinstance(site.get("development_projects"), Mapping) else {}
    project = projects.get(project_ref) if isinstance(projects, dict) else None
    if not isinstance(project, dict) or str(project.get("status")) != "active":
        return None
    due = str(project.get("completes_at", at))
    if CampaignTime.parse(at) < CampaignTime.parse(due):
        return None
    if str(project.get("kind", "")) == "settlement_foundation":
        foundation = complete_settlement_foundation(
            planner, institution={"administrative_owner": f"state_{state}", "state": state},
            project=project, at=due,
        )
        # complete_settlement_foundation writes the new site into the latest registry.
        # Reload before marking the source project complete so neither write erases the other.
        infra = copy.deepcopy(planner.read(INFRASTRUCTURE_PATH))
        site = infra.get("sites", {}).get(site_ref) if isinstance(infra.get("sites"), Mapping) else None
        if not isinstance(site, dict):
            raise ValueError("settlement foundation source site disappeared during completion")
        projects = site.setdefault("development_projects", {})
        project = projects.get(project_ref) if isinstance(projects, Mapping) else None
        if not isinstance(project, dict):
            raise ValueError("settlement foundation project disappeared during completion")
        project["status"] = "completed"; project["resolved_at"] = due; project["completed_settlement_foundation"] = copy.deepcopy(foundation)
        record = {"category": "settlement_foundation", **foundation}
        profile = site.setdefault("development_profile", {})
        profile["last_completed_project_ref"] = project_ref
        profile["last_completed_at"] = due
        planner.put(INFRASTRUCTURE_PATH, infra)
    else:
        land = copy.deepcopy(planner.read(LAND_STATE_PATH))
        land_result = apply_site_land_reservation(land, site_ref=site_ref, project_ref=project_ref)
        record = apply_infrastructure_work(infra, work=project["physical_work_spec"], project_ref=project_ref, completed_at=due)
        project["status"] = "completed"; project["resolved_at"] = due; project["completed_physical_work"] = copy.deepcopy(record)
        project["completed_land_allocation"] = copy.deepcopy(land_result)
        profile = site.setdefault("development_profile", {})
        profile["last_completed_project_ref"] = project_ref
        profile["last_completed_at"] = due
        planner.put(LAND_STATE_PATH, land)
        planner.put(INFRASTRUCTURE_PATH, infra)
    ep, eco = planner._private_economy(state)
    labor = eco.setdefault("labor_allocation", {}); active = labor.setdefault("projects", {})
    if isinstance(active, dict):
        active.pop(project_ref, None)
        labor["allocated_construction_workers"] = sum(max(0, int(row.get("workers", 0))) for row in active.values() if isinstance(row, Mapping))
    planner._write_private_economy(ep, eco)
    refresh_dynamic_settlement_class(planner, site_ref)
    return {"project_ref": project_ref, "site_ref": site_ref, "completed_at": due, "record": record}


def settle_state_settlement_development(planner, *, state: str, at: str, occurrences: int = 1) -> dict[str, Any]:
    """Review controlled named settlements on a quarterly deterministic cadence.

    This is bounded by the exact infrastructure registry (currently dozens, not a
    directory scan). It chooses only from registered physical blueprints and starts
    work only when the controller owns enough treasury, local material stock and
    unallocated construction labor.
    """
    registry = copy.deepcopy(planner.read(INFRASTRUCTURE_PATH))
    territory = planner.read(TERRITORY_PATH)
    locations = _static_location_map(planner)
    physics = planner.read("game/data/mechanics/construction-physics.json")
    review_months = max(1, int(physics.get("development", {}).get("review_months", 3)))
    reviewed = 0; started: list[str] = []; blocked: list[dict[str, Any]] = []
    for site_ref in sorted(registry.get("sites", {})):
        site = registry["sites"][site_ref]
        loc = locations.get(site_ref, {})
        if str(loc.get("state", "")) != state or str(loc.get("kind", "")) not in _DEVELOPABLE_KINDS:
            continue
        tsite = territory.get("sites", {}).get(site_ref, {}) if isinstance(territory.get("sites"), Mapping) else {}
        if str(tsite.get("controller", "")) != f"state_{state}":
            continue
        # Private estates under a separate owner are not silently developed by the
        # state despite territorial sovereignty.
        if isinstance(tsite, Mapping) and tsite.get("private_owner_ref"):
            continue
        residents, _poprow = _site_residents(planner, state, site_ref)
        profile = site.setdefault("development_profile", {})
        if not isinstance(profile, dict):
            profile = {}; site["development_profile"] = profile
        profile["legal_status"] = str(loc.get("kind", "settlement"))
        profile["physical_settlement_class"] = settlement_classification(residents=residents, site=site)
        profile["fortification_class"] = _fortification_class(loc, tsite if isinstance(tsite, Mapping) else {}, site)
        profile["functional_profiles"] = _functional_profiles(loc, tsite if isinstance(tsite, Mapping) else {})
        profile["current_residents"] = residents
        accumulator = max(0, int(profile.get("review_month_accumulator", 0))) + max(0, int(occurrences))
        profile["review_month_accumulator"] = accumulator
        if accumulator < review_months:
            continue
        profile["review_month_accumulator"] = accumulator % review_months
        profile["last_review"] = at
        reviewed += 1
        active_projects = site.get("development_projects", {}) if isinstance(site.get("development_projects"), Mapping) else {}
        if any(isinstance(row, Mapping) and row.get("status") == "active" for row in active_projects.values()):
            continue
        coverage = _development_coverage(site, residents, physics)
        profile["coverage"] = {k: round(v, 4) for k, v in coverage.items()}
        if residents <= 0:
            continue
        worst_key, worst_ratio = min(coverage.items(), key=lambda kv: (kv[1], kv[0]))
        if worst_ratio >= 1.0:
            continue
        blueprint_ref = _SUPPORT_TO_BLUEPRINT[worst_key]
        # Work out how many independent blueprint units close the physical deficit.
        from sword_runtime.infrastructure_projects import infrastructure_work_spec
        one = infrastructure_work_spec(planner.read, blueprint_ref=blueprint_ref, target_site_ref=site_ref, quantity=1)
        unit_add = max(1.0, float(one.get("support_capacity_add", {}).get(worst_key, 0) or 0))
        support = site.get("physical_support", {}) if isinstance(site.get("physical_support"), Mapping) else {}
        target_key = _SUPPORT_TARGET_KEYS[worst_key]
        target_factor = float(physics.get("development", {}).get("minimum_coverage", {}).get(target_key, 1.0))
        target_capacity = residents * target_factor
        deficit = max(1.0, target_capacity - float(support.get(worst_key, 0) or 0))
        desired_quantity = max(1, int(math.ceil(deficit / unit_add)))
        # Start the largest fully funded/materialized tranche rather than making a
        # large city wait until it can close the entire deficit in one purchase.
        # This is a resource consequence, not an arbitrary per-review project cap.
        state_now = planner.read(f"state/states/{state}.json")
        treasury_now = max(0, int(state_now.get("treasury_silver", 0)))
        ep_now, eco_now = planner._private_economy(state)
        try:
            _local_ref_now, local_now = planner._local_economy_region(state, eco_now, site_ref)
        except ValueError:
            local_now = {}
        stock_now = max(0, int((local_now.get("commodity_stock", {}) if isinstance(local_now, Mapping) else {}).get("construction_material_units", 0)))
        unit_material = max(1, int(one.get("construction_material_units", 0)))
        unit_silver = max(1, int(one.get("silver_cost", 0)))
        feasible_quantity = min(desired_quantity, stock_now // unit_material, treasury_now // unit_silver)
        quantity = max(0, int(feasible_quantity))
        started_project = _autonomous_start_project(planner, state=state, site_ref=site_ref, blueprint_ref=blueprint_ref, quantity=quantity, at=at) if quantity > 0 else None
        if started_project is None:
            blocked.append({"site_ref": site_ref, "blueprint_ref": blueprint_ref, "quantity": quantity, "desired_quantity": desired_quantity})
        else:
            started.append(str(started_project["project_ref"]))
    # _autonomous_start_project writes newer copies while iterating. Re-apply only
    # profile fields from this bounded review onto the latest registry so project
    # records are never lost by this final profile write.
    latest = copy.deepcopy(planner.read(INFRASTRUCTURE_PATH))
    for site_ref, row in registry.get("sites", {}).items():
        if site_ref in latest.get("sites", {}) and isinstance(row, Mapping) and isinstance(row.get("development_profile"), Mapping):
            latest["sites"][site_ref]["development_profile"] = copy.deepcopy(row["development_profile"])
    foundation_reviews = latest.setdefault("autonomous_foundation_reviews", {})
    review = foundation_reviews.setdefault(state, {"month_accumulator": 0})
    review["month_accumulator"] = max(0, int(review.get("month_accumulator", 0))) + max(0, int(occurrences))
    foundation_started = None
    if review["month_accumulator"] >= 12:
        review["month_accumulator"] %= 12
        review["last_review_at"] = at
        active_foundation = any(
            isinstance(project, Mapping)
            and str(project.get("kind", "")) == "settlement_foundation"
            and str(project.get("status", "")) == "active"
            and str(project.get("state", "")) == state
            for site_row in latest.get("sites", {}).values() if isinstance(site_row, Mapping)
            for project in ((site_row.get("development_projects", {}) or {}).values() if isinstance(site_row.get("development_projects", {}), Mapping) else [])
        )
        if not active_foundation:
            candidate = _autonomous_foundation_candidate(planner, state=state)
            review["last_candidate"] = copy.deepcopy(candidate)
            planner.put(INFRASTRUCTURE_PATH, latest)
            if isinstance(candidate, Mapping):
                foundation_started = _autonomous_start_settlement_foundation(
                    planner, state=state, source_site_ref=str(candidate["source_site_ref"]),
                    settlement_name=str(candidate["settlement_name"]), initial_settlers=int(candidate["initial_settlers"]), at=at,
                )
                if foundation_started is not None:
                    started.append(str(foundation_started.get("project_ref", "")))
        else:
            review["blocked_reason"] = "existing active settlement foundation"
    planner.put(INFRASTRUCTURE_PATH, planner.read(INFRASTRUCTURE_PATH) if foundation_started is not None else latest)
    return {
        "state": state, "reviewed_sites": reviewed, "started_project_refs": started, "blocked_projects": blocked,
        "autonomous_foundation_project_ref": (str(foundation_started.get("project_ref")) if isinstance(foundation_started, Mapping) else None),
    }


__all__.extend([
    "ensure_settlement_development_profile", "settle_development_project", "settle_state_settlement_development"
])
