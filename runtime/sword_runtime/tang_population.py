"""Tang estate population projection and permanent-residence resolution.

Tang Manor is the enclosing estate/demographic geography. Inner Walls is its
nested permanent civilian residential compound. Qin's local Tang row is the
single conserved civilian body-count authority. The private Tang population file
is an occupational projection over those same civilians and never owns an
independent birth/death clock.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

QIN_POPULATION_PATH = "state/population/qin.json"
TANG_POPULATION_PATH = "state/population/tang-manor.json"
TANG_SITE_REF = "loc_tang_manor"
INNER_WALLS_REF = "loc_tang_inner_walls"

_DETAIL_GROUPS: dict[str, tuple[str, ...]] = {
    "administration_and_education": ("administrative_clerks",),
    "agricultural": ("agricultural_workers_and_supervisors",),
    "camp_medical_support": ("inner_walls_civilian_medical",),
    "craft_and_industry": (
        "construction_and_maintenance_workers",
        "craft_and_industry",
        "resource_extraction_and_forestry",
    ),
    "dependents_children_elderly": ("dependents_and_nonworking_children",),
    "household_and_service": (
        "household_and_civic_services",
        "water_sanitation_and_firefighting",
    ),
    "merchant_and_transport": (
        "merchant_and_transport",
        "stable_remount_and_carriage_workers",
        "warehouse_and_granary_workers",
    ),
    "retired_military_veterans": ("veterans_and_retired_service",),
}


def _partition(total: int, weights: Mapping[str, int]) -> dict[str, int]:
    total = max(0, int(total))
    keys = [str(key) for key in weights]
    if not keys:
        return {}
    positive = {key: max(0, int(weights[key])) for key in keys}
    denom = sum(positive.values())
    if denom <= 0:
        positive = {key: 1 for key in keys}
        denom = len(keys)
    raw = {key: total * positive[key] / denom for key in keys}
    out = {key: int(math.floor(raw[key])) for key in keys}
    remaining = total - sum(out.values())
    for key in sorted(keys, key=lambda item: (-(raw[item] - out[item]), item))[:remaining]:
        out[key] += 1
    return out


def resident_support_site_ref(infrastructure_sites: Mapping[str, Any], site_ref: str) -> str:
    """Resolve the explicit nested site that physically houses residents."""
    current = str(site_ref)
    seen: set[str] = set()
    while current:
        if current in seen:
            raise ValueError("residence policy contains a cycle")
        seen.add(current)
        row = infrastructure_sites.get(current)
        if not isinstance(row, Mapping):
            return current
        policy = row.get("residence_policy") if isinstance(row.get("residence_policy"), Mapping) else {}
        target = policy.get("resident_site_ref") if isinstance(policy, Mapping) else None
        if not isinstance(target, str) or not target or target == current:
            return current
        current = target
    return str(site_ref)


def resident_support_capacity(
    infrastructure_sites: Mapping[str, Any], site_ref: str, fallback: int = 0
) -> tuple[str, int]:
    physical_ref = resident_support_site_ref(infrastructure_sites, site_ref)
    row = infrastructure_sites.get(physical_ref)
    if not isinstance(row, Mapping):
        return physical_ref, max(0, int(fallback))
    value = row.get("effective_resident_support_capacity_people")
    return physical_ref, max(0, int(fallback if value is None else value))


def sync_tang_private_population(
    planner: Any, *, at: str, reason: str, evidence_ref: str | None = None
) -> dict[str, Any]:
    """Project Qin's exact Tang civilian partition into House Tang detail."""
    del at, reason, evidence_ref  # synchronization provenance is deliberately not persisted
    qin = planner.read(QIN_POPULATION_PATH)
    local = qin.get("local_population") if isinstance(qin, Mapping) else None
    sites = local.get("sites", {}) if isinstance(local, Mapping) else {}
    parent_row = sites.get(TANG_SITE_REF) if isinstance(sites, Mapping) else None
    if not isinstance(parent_row, Mapping):
        raise ValueError("Qin Tang Manor local population row is missing")
    parent_strata = parent_row.get("civilian_strata") if isinstance(parent_row.get("civilian_strata"), Mapping) else None
    if not isinstance(parent_strata, Mapping):
        raise ValueError("Qin Tang Manor civilian strata are missing")
    parent_total = sum(max(0, int(value)) for value in parent_strata.values())
    if parent_total != max(0, int(parent_row.get("civilian_population", 0))):
        raise ValueError("Qin Tang Manor local civilian total is internally inconsistent")

    tang = copy.deepcopy(planner.read(TANG_POPULATION_PATH))
    current = tang.get("strata") if isinstance(tang.get("strata"), Mapping) else {}
    next_strata: dict[str, int] = {}
    claimed_parent: set[str] = set()
    claimed_detail: set[str] = set()
    for parent_key, detail_keys in _DETAIL_GROUPS.items():
        target = max(0, int(parent_strata.get(parent_key, 0)))
        weights = {key: max(0, int(current.get(key, 0))) for key in detail_keys}
        next_strata.update(_partition(target, weights))
        claimed_parent.add(parent_key)
        claimed_detail.update(detail_keys)

    for parent_key, value in sorted(parent_strata.items()):
        key = str(parent_key)
        if key not in claimed_parent:
            next_strata[key] = max(0, int(value))
    for detail_key, value in sorted(current.items()):
        if detail_key in claimed_detail or detail_key in next_strata:
            continue
        if max(0, int(value)) > 0:
            raise ValueError(f"Tang detailed civilian stratum lacks parent mapping: {detail_key}")

    if sum(next_strata.values()) != parent_total:
        raise ValueError("Tang private detail failed to reconcile to Qin local civilians")
    tang["strata"] = dict(sorted(next_strata.items()))
    tang["population_total"] = parent_total
    tang["subset_of_parent"] = True
    tang["parent_population_ref"] = "population_qin"
    partition = tang.setdefault("geographic_partition", {})
    partition["location_ref"] = TANG_SITE_REF
    partition["permanent_residence_site_ref"] = INNER_WALLS_REF
    partition["body_count_authority_ref"] = "state/population/qin.json#/local_population/sites/loc_tang_manor"
    partition.pop("basis", None)
    demography = tang.get("demography") if isinstance(tang.get("demography"), dict) else {}
    demography.pop("birth_rate_per_thousand", None)
    demography.pop("death_rate_per_thousand", None)
    demography["authority"] = "parent_population_only"
    demography.pop("rule", None)
    tang["demography"] = demography
    tang.pop("last_parent_sync", None)
    tang.pop("last_population_mobility", None)
    planner.put(TANG_POPULATION_PATH, tang)
    return {
        "population_total": parent_total,
        "site_ref": TANG_SITE_REF,
        "residence_site_ref": INNER_WALLS_REF,
    }


__all__ = [
    "QIN_POPULATION_PATH",
    "TANG_POPULATION_PATH",
    "TANG_SITE_REF",
    "INNER_WALLS_REF",
    "resident_support_site_ref",
    "resident_support_capacity",
    "sync_tang_private_population",
]
