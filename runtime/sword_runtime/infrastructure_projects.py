"""Exact settlement infrastructure work above the funded project transaction layer."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

BLUEPRINT_PATH = "game/data/mechanics/infrastructure-blueprints.json"
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


def infrastructure_work_spec(read, *, blueprint_ref: str, target_site_ref: str, quantity: int) -> dict[str, Any]:
    q = max(1, int(quantity))
    bp = infrastructure_blueprint(read, blueprint_ref)
    support = {str(k): float(v) * q for k, v in (bp.get("support_capacity_add", {}) or {}).items()}
    works = {str(k): float(v) * q for k, v in (bp.get("works_add", {}) or {}).items()}
    return {
        "blueprint_ref": str(blueprint_ref),
        "target_site_ref": str(target_site_ref),
        "quantity": q,
        "category": str(bp.get("category", "infrastructure")),
        "unit_name": str(bp.get("unit_name", blueprint_ref)),
        "silver_cost": int(bp.get("silver_cost", 0)) * q,
        "construction_material_units": int(bp.get("construction_material_units", 0)) * q,
        "labor_hours": int(bp.get("labor_hours", 0)) * q,
        "minimum_calendar_hours": int(bp.get("minimum_calendar_hours", 1)),
        "support_capacity_add": support,
        "works_add": works,
        "physical_geometry_per_unit": deepcopy(bp.get("physical_geometry", {})),
    }


def _coerce_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clean_number(value: float) -> int | float:
    rounded = round(value, 6)
    return int(rounded) if abs(rounded - round(rounded)) < 1e-9 else rounded


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
        support[key] = _clean_number(_coerce_number(support.get(key, 0)) + _coerce_number(delta))

    works = site.setdefault("works", {})
    if not isinstance(works, dict):
        raise ValueError("settlement physical works aggregate is invalid")
    for key, delta in (work.get("works_add", {}) or {}).items():
        works[str(key)] = _clean_number(_coerce_number(works.get(str(key), 0)) + _coerce_number(delta))

    capacities = [max(0.0, _coerce_number(support.get(key, 0))) for key in _SUPPORT_KEYS]
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
        "authority_rule": "This record is completed physical infrastructure only. It creates no population, cash, material stock, military bodies, or route control by itself.",
    }
    records[project_ref] = record
    site["last_physical_project_completed_at"] = str(completed_at)
    return record


__all__ = ["BLUEPRINT_PATH", "INFRASTRUCTURE_PATH", "infrastructure_blueprint", "infrastructure_work_spec", "apply_infrastructure_work"]
