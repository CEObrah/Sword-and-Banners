"""Conserved dynamic settlement founding and physical settlement classification.

A settlement is a geographic/physical owner, never a source of people.  Founding
creates an empty routed site plus already-funded physical works, then queues real
households to travel from an existing demographic owner.  Later classification is
computed from current residents and completed physical support, not from RPG levels.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping, MutableMapping
from typing import Any

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
    row["classification_rule"] = "derived from real residents plus physical/civic support; classification is not a population cap"
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

    parent_ref = str(source.get("region_ref") or source.get("parent_ref") or source_site)
    location = {
        "ref": new_ref, "name": name, "kind": "settlement", "settlement_class": "hamlet",
        "state": state, "parent_ref": parent_ref, "region_ref": str(source.get("region_ref") or parent_ref),
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
            "authority_rule": "physical foundation only; no people were created",
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
