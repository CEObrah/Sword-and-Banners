"""Exact settlement infrastructure work above the funded project transaction layer.

Physical projects derive material-equivalent demand, labor classes, cash cost,
calendar time and resident-support outputs from registered geometry plus the shared
construction economy.
"""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

BLUEPRINT_PATH = "game/data/mechanics/infrastructure-blueprints.json"
CONSTRUCTION_PHYSICS_PATH = "game/data/mechanics/construction-physics.json"
ECONOMY_PATH = "game/data/mechanics/economy.json"
INFRASTRUCTURE_PATH = "state/infrastructure/settlements.json"
_SUPPORT_KEYS = (
    "housing_capacity_people",
    "water_capacity_people",
    "sanitation_capacity_people",
    "food_storage_distribution_capacity_people",
    "ordinary_work_access_capacity_people",
)


def infrastructure_blueprint(read, blueprint_ref: str) -> dict[str, Any]:
    doc = read(BLUEPRINT_PATH)
    rows = doc.get("blueprints", {}) if isinstance(doc, Mapping) else {}
    row = rows.get(str(blueprint_ref)) if isinstance(rows, Mapping) else None
    if not isinstance(row, Mapping):
        raise ValueError("unknown registered infrastructure blueprint")
    return deepcopy(dict(row))


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_number(value: float) -> int | float:
    rounded = round(value, 6)
    return int(rounded) if abs(rounded - round(rounded)) < 1e-9 else rounded


def _derived_support(bp: Mapping[str, Any], physics: Mapping[str, Any], quantity: int) -> dict[str, float]:
    geom = bp.get("physical_geometry", {}) if isinstance(bp.get("physical_geometry"), Mapping) else {}
    standards = physics.get("resident_support_standards", {}) if isinstance(physics.get("resident_support_standards"), Mapping) else {}
    q = max(1, int(quantity))
    out: dict[str, float] = {}
    floor = _num(geom.get("built_floor_area_m2"), 0.0)
    if floor > 0:
        out["housing_capacity_people"] = floor * q / max(1e-9, _num(standards.get("housing_floor_area_m2_per_person"), 30.0))
    water = _num((bp.get("works_add", {}) if isinstance(bp.get("works_add"), Mapping) else {}).get("potable_water_capacity_liters_per_day"), 0.0)
    if water > 0:
        out["water_capacity_people"] = water * q / max(1e-9, _num(standards.get("potable_water_liters_per_person_day"), 120.0))
    drains_km = _num(geom.get("lined_drain_length_km"), 0.0)
    latrines = _num(geom.get("public_latrine_points"), 0.0)
    if drains_km > 0 or latrines > 0:
        by_drain = drains_km * 1000.0 * q / max(1e-9, _num(standards.get("lined_drain_m_per_person"), 2.4)) if drains_km > 0 else float("inf")
        by_latrine = latrines * q * _num(standards.get("public_latrine_people_per_point"), 20.0) if latrines > 0 else float("inf")
        out["sanitation_capacity_people"] = min(by_drain, by_latrine)
    storage = _num(geom.get("dry_storage_kg"), 0.0)
    if storage > 0:
        monthly = _num(standards.get("civilian_grain_kg_per_person_month"), 8.0)
        reserve_days = _num(standards.get("food_reserve_days"), 180.0)
        kg_per_person = monthly / 30.0 * reserve_days
        out["food_storage_distribution_capacity_people"] = storage * q / max(1e-9, kg_per_person)
    workstations = _num(geom.get("workstations"), 0.0)
    if workstations > 0:
        out["ordinary_work_access_capacity_people"] = workstations * q * _num(standards.get("ordinary_work_access_people_per_skilled_workstation"), 5.0)
    # Settlement foundation is a composite package: derive its resident support
    # from its physical design residents until the component works are separately
    # decomposed in a later refit. It remains a physical design field, not a free
    # population grant.
    if str(bp.get("category")) == "settlement_foundation":
        design = _num(geom.get("design_residents"), 0.0) * q
        for key in _SUPPORT_KEYS:
            out.setdefault(key, design)
    return out


def _material_units_from_geometry(bp: Mapping[str, Any], quantity: int) -> tuple[float, dict[str, float]]:
    model = bp.get("physical_cost_model", {}) if isinstance(bp.get("physical_cost_model"), Mapping) else {}
    formula = model.get("material_unit_formula", {}) if isinstance(model.get("material_unit_formula"), Mapping) else {}
    geom = bp.get("physical_geometry", {}) if isinstance(bp.get("physical_geometry"), Mapping) else {}
    q = max(1, int(quantity))
    components: dict[str, float] = {}
    total = 0.0
    for key, coefficient in formula.items():
        coeff = max(0.0, _num(coefficient, 0.0))
        if key == "foundation_composite_units":
            amount = coeff
        else:
            amount = max(0.0, _num(geom.get(key), 0.0)) * coeff
        amount *= q
        if amount > 0:
            components[str(key)] = amount
            total += amount
    return total, components


def infrastructure_work_spec(
    read,
    *,
    blueprint_ref: str,
    target_site_ref: str,
    quantity: int,
    local_haul_km: float | None = None,
) -> dict[str, Any]:
    q = max(1, int(quantity))
    bp = infrastructure_blueprint(read, blueprint_ref)
    physics = read(CONSTRUCTION_PHYSICS_PATH)
    economy = read(ECONOMY_PATH)
    model = bp.get("physical_cost_model", {}) if isinstance(bp.get("physical_cost_model"), Mapping) else {}
    if not model:
        raise ValueError("infrastructure blueprint has no physical cost model")

    material_units_f, material_formula = _material_units_from_geometry(bp, q)
    material_units = max(0, int(math.ceil(material_units_f)))
    labor_per_unit = model.get("labor_hours_by_class", {}) if isinstance(model.get("labor_hours_by_class"), Mapping) else {}
    labor_by_class = {str(k): max(0, int(round(_num(v) * q))) for k, v in labor_per_unit.items()}
    labor_hours = sum(labor_by_class.values())
    critical_path = max(1, int(model.get("critical_path_hours", bp.get("minimum_calendar_hours", 1))))
    workfront = max(1, int(model.get("workfront_capacity_workers", 1))) * q
    haul_km = max(0.0, _num(local_haul_km if local_haul_km is not None else model.get("reference_local_haul_km"), 8.0))
    meq = physics.get("material_equivalent", {}) if isinstance(physics.get("material_equivalent"), Mapping) else {}
    tonnes_per_unit = max(1e-9, _num(meq.get("tonnes_per_construction_material_unit"), 0.25))
    material_tonnes = material_units * tonnes_per_unit
    material_procurement = material_units * _num(meq.get("base_procurement_silver_per_unit"), 1.25)
    transport = material_tonnes * haul_km * _num(meq.get("haul_silver_per_tonne_km"), 0.015)
    wage_rules = physics.get("labor", {}) if isinstance(physics.get("labor"), Mapping) else {}
    monthly_hours = max(1e-9, _num(wage_rules.get("monthly_productive_hours"), 216.0))
    wages = wage_rules.get("monthly_wage_silver", {}) if isinstance(wage_rules.get("monthly_wage_silver"), Mapping) else {}
    labor_silver = sum(hours * _num(wages.get(cls), 4.5) / monthly_hours for cls, hours in labor_by_class.items())
    silver_cost = int(math.ceil(material_procurement + transport + labor_silver))
    support = _derived_support(bp, physics, q)

    works = {str(k): float(v) * q for k, v in (bp.get("works_add", {}) or {}).items()}
    return {
        "blueprint_ref": str(blueprint_ref),
        "target_site_ref": str(target_site_ref),
        "quantity": q,
        "category": str(bp.get("category", "infrastructure")),
        "unit_name": str(bp.get("unit_name", blueprint_ref)),
        "silver_cost": silver_cost,
        "cash_cost_breakdown": {
            "material_procurement_silver": round(material_procurement, 3),
            "labor_wages_silver": round(labor_silver, 3),
            "local_haul_silver": round(transport, 3),
        },
        "construction_material_units": material_units,
        "material_equivalent_tonnes": round(material_tonnes, 3),
        "material_formula_components": {k: round(v, 6) for k, v in material_formula.items()},
        "labor_hours": labor_hours,
        "labor_hours_by_class": labor_by_class,
        "minimum_calendar_hours": critical_path,
        "workfront_capacity_workers": workfront,
        "reference_local_haul_km": round(haul_km, 3),
        "support_capacity_add": {k: _clean_number(v) for k, v in support.items()},
        "works_add": works,
        "physical_geometry_per_unit": deepcopy(bp.get("physical_geometry", {})),
    }


def calculate_project_schedule(
    read,
    *,
    work: Mapping[str, Any],
    available_workers: int,
    requested_minimum_hours: int = 0,
) -> dict[str, Any]:
    physics = read(CONSTRUCTION_PHYSICS_PATH)
    day = physics.get("workday", {}) if isinstance(physics.get("workday"), Mapping) else {}
    productive = max(0.1, _num(day.get("productive_hours_per_worker_day"), 8.0))
    attendance = max(0.05, min(1.0, _num(day.get("attendance_factor"), 0.9)))
    calendar = max(1.0, _num(day.get("calendar_hours_per_day"), 24.0))
    workfront = max(1, int(work.get("workfront_capacity_workers", available_workers or 1)))
    workers = max(1, min(max(1, int(available_workers)), workfront))
    hours = max(0, int(work.get("labor_hours", 0)))
    labor_days = hours / max(1e-9, workers * productive * attendance)
    labor_calendar_hours = int(math.ceil(labor_days * calendar))
    duration = max(int(work.get("minimum_calendar_hours", 1)), int(requested_minimum_hours), labor_calendar_hours)
    return {
        "construction_workers": workers,
        "labor_calendar_hours": labor_calendar_hours,
        "critical_path_hours": int(work.get("minimum_calendar_hours", 1)),
        "duration_hours": duration,
        "productive_hours_per_worker_day": productive,
        "attendance_factor": attendance,
    }


def apply_infrastructure_work(registry: dict[str, Any], *, work: Mapping[str, Any], project_ref: str, completed_at: str) -> dict[str, Any]:
    sites = registry.get("sites")
    if not isinstance(sites, dict):
        raise ValueError("settlement infrastructure registry is invalid")
    target = str(work.get("target_site_ref", ""))
    site = sites.get(target)
    if not isinstance(site, dict):
        raise ValueError("infrastructure project target has no physical settlement-capacity owner")

    support = site.setdefault("physical_support", {})
    if not isinstance(support, dict):
        raise ValueError("settlement physical support owner is invalid")
    for key, delta in (work.get("support_capacity_add", {}) or {}).items():
        if key not in _SUPPORT_KEYS:
            raise ValueError(f"unsupported resident-support capacity dimension: {key}")
        support[key] = _clean_number(_num(support.get(key, 0)) + _num(delta))

    works = site.setdefault("works", {})
    if not isinstance(works, dict):
        raise ValueError("settlement physical works aggregate is invalid")
    work_add = work.get("works_add", {}) or {}
    for key, delta in work_add.items():
        works[str(key)] = _clean_number(_num(works.get(str(key), 0)) + _num(delta))

    # Military and specialist capacity is still physical capacity.  Registered
    # military blueprints update the same grouped site owner used by garrison and
    # training systems rather than creating a parallel House/state-specific field.
    military = site.setdefault("military_support", {})
    training = site.setdefault("training_support", {})
    institution = site.setdefault("institutional_support", {})
    if not isinstance(military, dict) or not isinstance(training, dict) or not isinstance(institution, dict):
        raise ValueError("settlement specialist support owner is invalid")
    if _num(work_add.get("military_barracks_beds")):
        military["permanent_bed_capacity_people"] = _clean_number(
            _num(military.get("permanent_bed_capacity_people")) + _num(work_add.get("military_barracks_beds"))
        )
    if _num(work_add.get("stable_capacity_horses")):
        military["stable_capacity_horses"] = _clean_number(
            _num(military.get("stable_capacity_horses")) + _num(work_add.get("stable_capacity_horses"))
        )
    if _num(work_add.get("training_capacity_people")):
        training["simultaneous_trainee_capacity"] = _clean_number(
            _num(training.get("simultaneous_trainee_capacity")) + _num(work_add.get("training_capacity_people"))
        )
    if _num(work_add.get("training_ground_area_m2")):
        training["prepared_training_ground_area_km2"] = _clean_number(
            _num(training.get("prepared_training_ground_area_km2")) + _num(work_add.get("training_ground_area_m2")) / 1_000_000.0
        )
    if _num(work_add.get("medical_beds")):
        institution["medical_support_capacity_people"] = _clean_number(
            _num(institution.get("medical_support_capacity_people")) + _num(work_add.get("medical_beds"))
        )

    capacities = [max(0.0, _num(support.get(key, 0))) for key in _SUPPORT_KEYS]
    if all(value > 0 for value in capacities):
        site["effective_resident_support_capacity_people"] = int(min(capacities))

    records = site.setdefault("constructed_works", {})
    if not isinstance(records, dict):
        raise ValueError("settlement constructed-work registry is invalid")
    if project_ref in records:
        raise ValueError("infrastructure project already has a completed physical work record")
    record = {
        "project_ref": str(project_ref),
        "blueprint_ref": str(work.get("blueprint_ref")),
        "category": str(work.get("category")),
        "unit_name": str(work.get("unit_name")),
        "quantity": int(work.get("quantity", 1)),
        "completed_at": str(completed_at),
        "condition": 1.0,
        "support_capacity_add": deepcopy(work.get("support_capacity_add", {})),
        "works_add": deepcopy(work.get("works_add", {})),
        "physical_geometry_per_unit": deepcopy(work.get("physical_geometry_per_unit", {})),
        "material_equivalent_tonnes": work.get("material_equivalent_tonnes"),
        "construction_material_units": int(work.get("construction_material_units", 0)),
        "labor_hours_by_class": deepcopy(work.get("labor_hours_by_class", {})),
        "cash_cost_breakdown": deepcopy(work.get("cash_cost_breakdown", {})),
    }
    records[project_ref] = record
    site["last_physical_project_completed_at"] = str(completed_at)
    return record


__all__ = [
    "BLUEPRINT_PATH", "CONSTRUCTION_PHYSICS_PATH", "INFRASTRUCTURE_PATH",
    "infrastructure_blueprint", "infrastructure_work_spec", "calculate_project_schedule",
    "apply_infrastructure_work",
]
