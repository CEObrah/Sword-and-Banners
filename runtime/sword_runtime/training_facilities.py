"""Deterministic physical training access with exactly two ordinary contexts.

Ordinary deliberate training is either:

* ``home_garrison``: permanent settlement/garrison infrastructure; or
* ``field``: ordinary drill on suitable open ground while deployed.

There are no temporary field-training construction objects and no quality tiers such
as basic/adequate/good/excellent. Specialist artillery, engineering, medical,
household and estate drills still require their actual specialist facilities.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any


LOCATIONS_PATH = "game/data/world/locations.json"
LAND_STATE_PATH = "state/development/land.json"
SETTLEMENT_INFRASTRUCTURE_PATH = "state/infrastructure/settlements.json"
TRAINING_RULES_PATH = "game/data/mechanics/training.json"

# Portable ordinary drill requirements. They do not create a facility owner.
_PORTABLE_FIELD_TAGS = {
    "field_terrain",
    "training_ground",
    "maneuver_ground",
    "command_ground",
    "staff_room",
    "riding_ground",
    "riding_range",
    "range",
    "signal_ground",
}

# Established sites count as permanent ordinary training infrastructure. This is a
# classification, not a quality ladder.
_HOME_GARRISON_KINDS = {
    "capital",
    "city",
    "town",
    "fort",
    "fortress",
    "fortified_settlement",
    "pass",
    "military_compound",
    "military_district",
    "depot",
    "academy",
    "estate",
}

# Old labels are accepted only as read compatibility and collapse immediately to
# one of the two current contexts.
_LEGACY_FACILITY_CONTEXT = {
    "poor": "field",
    "basic": "field",
    "ordinary_field": "field",
    "field_deployed": "field",
    "adequate": "home_garrison",
    "good": "home_garrison",
    "excellent": "home_garrison",
    "standard_permanent": "home_garrison",
    "developed_permanent": "home_garrison",
    "excellent_permanent": "home_garrison",
    "permanent_training_ground": "home_garrison",
    "infrastructure": "home_garrison",
    "permanent_infrastructure": "home_garrison",
}

_SPECIALIST_REQUIREMENTS: dict[str, tuple[set[str], set[str]]] = {
    "engineering_yard": ({"engineering"}, set()),
    "artillery_range": ({"artillery"}, set()),
    "medical_training": ({"medical", "training"}, set()),
    "household_classroom": (set(), {"household", "house", "academy"}),
    "audience_hall": (set(), {"household", "house", "politics", "academy"}),
    "estate_routes": (set(), {"estate"}),
}

_SHARED_RESOURCES_BY_TAG: dict[str, set[str]] = {
    "engineering_yard": {"engineering_tools"},
    "artillery_range": {"artillery"},
    "signal_ground": {"signals"},
}


def canonical_training_context(value: object) -> str:
    raw = str(value or "").strip()
    if raw in {"none", "field", "home_garrison"}:
        return raw
    return _LEGACY_FACILITY_CONTEXT.get(raw, "home_garrison" if raw else "none")


def training_facility_factor(training_rules: Mapping[str, Any], facility_context: object) -> float:
    tables = training_rules.get("factor_tables", {}) if isinstance(training_rules, Mapping) else {}
    table = tables.get("facility", {}) if isinstance(tables, Mapping) else {}
    context = canonical_training_context(facility_context)
    if isinstance(table, Mapping) and context in table:
        return float(table[context])
    return 1.0 if context == "home_garrison" else (0.9 if context == "field" else 0.0)


def _location_rows(runtime: Any) -> dict[str, Mapping[str, Any]]:
    # Static location blueprints do not change during a campaign transaction.
    # Training access calls this thousands of times, so build the ref map once
    # per planner instead of re-indexing the immutable location list per drill.
    cached = getattr(runtime, "_training_location_rows_cache", None)
    if isinstance(cached, dict):
        return cached
    try:
        doc = runtime.read(LOCATIONS_PATH)
    except Exception:
        return {}
    rows = doc.get("locations", []) if isinstance(doc, Mapping) else []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return {}
    indexed = {
        str(row.get("ref")): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("ref"), str) and row.get("ref")
    }
    try:
        runtime._training_location_rows_cache = indexed
        runtime._training_location_chain_cache = {}
    except Exception:
        pass
    return indexed


def _location_chain_rows(runtime: Any, location_ref: str) -> list[Mapping[str, Any]]:
    rows = _location_rows(runtime)
    current = str(location_ref or "")
    if not current or current not in rows:
        return []
    chain_cache = getattr(runtime, "_training_location_chain_cache", None)
    if not isinstance(chain_cache, dict):
        chain_cache = {}
        try:
            runtime._training_location_chain_cache = chain_cache
        except Exception:
            pass
    if current in chain_cache:
        return list(chain_cache[current])
    key = current
    out: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    while current in rows and current not in seen:
        seen.add(current)
        row = rows[current]
        out.append(row)
        parent = row.get("parent_ref")
        if not isinstance(parent, str) or not parent.startswith("loc_"):
            break
        current = parent
    chain_cache[key] = tuple(out)
    return list(out)


def _explicit_tags(chain: Sequence[Mapping[str, Any]]) -> set[str]:
    out: set[str] = set()
    for row in chain:
        raw = row.get("training_facility_tags", [])
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            out.update(str(value) for value in raw if str(value))
    return out


def _is_home_garrison_row(row: Mapping[str, Any]) -> bool:
    # Child yards and scene venues inherit the containing permanent settlement.
    # They do not create a third training context or a separate quality tier.
    return str(row.get("kind", "")) in _HOME_GARRISON_KINDS


def training_facility_access(runtime: Any, *, location_ref: str, facility_tag: str) -> float:
    """Return 1/0 physical access for one registered drill requirement."""
    tag = str(facility_tag or "").strip()
    if not tag:
        return 1.0
    chain = _location_chain_rows(runtime, str(location_ref or ""))
    if not chain:
        return 0.0
    if tag in _explicit_tags(chain):
        return 1.0
    if tag in _PORTABLE_FIELD_TAGS:
        return 1.0

    required_functions, allowed_kinds = _SPECIALIST_REQUIREMENTS.get(tag, (set(), set()))
    for row in chain:
        raw_functions = row.get("functions", [])
        functions = (
            {str(value) for value in raw_functions}
            if isinstance(raw_functions, Sequence) and not isinstance(raw_functions, (str, bytes, bytearray))
            else set()
        )
        kind = str(row.get("kind", ""))
        if required_functions and required_functions.issubset(functions):
            return 1.0
        if allowed_kinds and (kind in allowed_kinds or bool(functions & allowed_kinds)):
            return 1.0
    return 0.0


def program_facility_access(
    runtime: Any,
    *,
    registry: Mapping[str, Any],
    program_ref: str,
    location_ref: str,
) -> dict[str, float]:
    programs = registry.get("programs", {}) if isinstance(registry, Mapping) else {}
    drills = registry.get("drills", {}) if isinstance(registry, Mapping) else {}
    program = programs.get(program_ref, {}) if isinstance(programs, Mapping) else {}
    rotation = program.get("rotation", []) if isinstance(program, Mapping) else []
    out: dict[str, float] = {}
    if not isinstance(rotation, Sequence) or isinstance(rotation, (str, bytes, bytearray)):
        return out
    for row in rotation:
        if not isinstance(row, Mapping):
            continue
        dref = str(row.get("drill_ref", ""))
        drill = drills.get(dref, {}) if isinstance(drills, Mapping) else {}
        facility_tag = str(drill.get("facility_tag", "")) if isinstance(drill, Mapping) else ""
        out[dref] = training_facility_access(runtime, location_ref=location_ref, facility_tag=facility_tag)
    return out


def shared_training_resources(runtime: Any, *, location_ref: str) -> set[str]:
    chain = _location_chain_rows(runtime, str(location_ref or ""))
    if not chain:
        return set()
    explicit = _explicit_tags(chain)
    resources: set[str] = set()
    for tag, provided in _SHARED_RESOURCES_BY_TAG.items():
        if tag in explicit or training_facility_access(runtime, location_ref=location_ref, facility_tag=tag) > 0:
            resources.update(provided)
    return resources


def _land_owner_row(registry: Mapping[str, Any], location_ref: str) -> Mapping[str, Any] | None:
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), Mapping) else {}
    if location_ref in sites and isinstance(sites[location_ref], Mapping):
        return sites[location_ref]
    regions = registry.get("regions", {}) if isinstance(registry.get("regions"), Mapping) else {}
    if location_ref in regions and isinstance(regions[location_ref], Mapping):
        return regions[location_ref]
    return None


def _land_area(owner: Mapping[str, Any] | None, keys: set[str]) -> float:
    if not isinstance(owner, Mapping):
        return 0.0
    total = 0.0
    for field in ("enclosed_land_use_km2", "external_land_use_km2", "land_use_km2"):
        use = owner.get(field, {}) if isinstance(owner.get(field), Mapping) else {}
        total += sum(max(0.0, float(v)) for k, v in use.items() if str(k) in keys)
    return max(0.0, total)


def _nearest_land_owner(runtime: Any, land: Mapping[str, Any], location_ref: str) -> tuple[Mapping[str, Any] | None, str | None]:
    for row in _location_chain_rows(runtime, str(location_ref or "")):
        ref = str(row.get("ref", ""))
        owner = _land_owner_row(land, ref)
        if isinstance(owner, Mapping):
            return owner, ref
    owner = _land_owner_row(land, str(location_ref or ""))
    return (owner, str(location_ref)) if isinstance(owner, Mapping) else (None, None)


def training_environment(
    runtime: Any,
    *,
    location_ref: str,
    simultaneous_trainees: int = 1,
) -> dict[str, Any]:
    """Resolve exactly one ordinary training context and physical throughput."""
    trainees = max(1, int(simultaneous_trainees))
    rules = runtime.read(TRAINING_RULES_PATH)
    env = rules.get("physical_environment", {}) if isinstance(rules, Mapping) else {}
    space_per_1000 = max(1e-9, float(env.get("simultaneous_space_km2_per_1000_trainees", 0.12)))
    required_area = trainees / 1000.0 * space_per_1000

    try:
        land = runtime.read(LAND_STATE_PATH)
    except Exception:
        land = {}
    try:
        infrastructure = runtime.read(SETTLEMENT_INFRASTRUCTURE_PATH)
    except Exception:
        infrastructure = {}
    infra_sites = infrastructure.get("sites", {}) if isinstance(infrastructure, Mapping) else {}

    # Home/garrison is binary. A nested barracks, drill yard, academy or military
    # compound can use the strongest permanent training capacity in its containing
    # settlement/garrison chain. Capacity is physical throughput, not a quality tier.
    best_home: dict[str, Any] | None = None
    for row in _location_chain_rows(runtime, str(location_ref or "")):
        if not _is_home_garrison_row(row):
            continue
        ref = str(row.get("ref", ""))
        land_owner = _land_owner_row(land, ref)
        training_area = _land_area(land_owner, {"training"})
        land_capacity = max(0, int(math.floor(training_area / space_per_1000 * 1000.0)))
        site_support = infra_sites.get(ref, {}) if isinstance(infra_sites, Mapping) else {}
        condition = float(site_support.get("condition", 1.0) or 0.0) if isinstance(site_support, Mapping) else 1.0
        if condition <= 0.25:
            continue
        resident_capacity = max(0, int(site_support.get("effective_resident_support_capacity_people", 0) or 0)) if isinstance(site_support, Mapping) else 0
        training_support = site_support.get("training_support", {}) if isinstance(site_support, Mapping) and isinstance(site_support.get("training_support"), Mapping) else {}
        explicit_capacity = max(0, int(training_support.get("simultaneous_trainee_capacity", 0) or 0))
        fallback_fraction = max(0.01, float(env.get("home_garrison_capacity_fraction", 0.10)))
        fallback_floor = max(100, int(env.get("home_garrison_minimum_capacity", 2000)))
        fallback_capacity = max(fallback_floor, int(resident_capacity * fallback_fraction))
        permanent_capacity = max(explicit_capacity, land_capacity, fallback_capacity)
        candidate = {
            "environment": "home_garrison",
            "facility_grade": "home_garrison",
            "capacity_factor": round(min(1.0, permanent_capacity / trainees), 6),
            "simultaneous_capacity": permanent_capacity,
            "required_area_km2": round(required_area, 6),
            "source": "permanent_home_garrison_infrastructure",
            "source_site_ref": ref,
        }
        if best_home is None or permanent_capacity > int(best_home.get("simultaneous_capacity", 0)):
            best_home = candidate
    if best_home is not None:
        return best_home

    # Field drill uses suitable ground immediately; there is no setup lifecycle.
    owner, land_ref = _nearest_land_owner(runtime, land, location_ref)
    field_area = _land_area(owner, {"open_developable", "pasture", "military"})
    field_capacity = max(0, int(math.floor(field_area / space_per_1000 * 1000.0)))
    if field_capacity > 0:
        return {
            "environment": "field",
            "facility_grade": "field",
            "capacity_factor": round(min(1.0, field_capacity / trainees), 6),
            "simultaneous_capacity": field_capacity,
            "required_area_km2": round(required_area, 6),
            "available_field_area_km2": round(field_area, 6),
            "source": "suitable_field_ground",
            "source_site_ref": land_ref,
        }

    return {
        "environment": "no_suitable_ground",
        "facility_grade": "none",
        "capacity_factor": 0.0,
        "simultaneous_capacity": 0,
        "required_area_km2": round(required_area, 6),
        "source": "no_suitable_ground",
        "source_site_ref": land_ref,
    }


__all__ = [
    "LOCATIONS_PATH",
    "LAND_STATE_PATH",
    "SETTLEMENT_INFRASTRUCTURE_PATH",
    "TRAINING_RULES_PATH",
    "canonical_training_context",
    "program_facility_access",
    "shared_training_resources",
    "training_facility_access",
    "training_facility_factor",
    "training_environment",
]
