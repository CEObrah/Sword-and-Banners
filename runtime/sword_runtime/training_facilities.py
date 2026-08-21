"""Deterministic physical training-site access.

Registered drill ``facility_tag`` values are mechanical requirements, not prose.
This module resolves those tags against the trainee's saved physical location and
its containing location chain. Portable field setups remain possible for ordinary
martial/command drills, while specialist infrastructure (artillery, engineering,
medical, household/estate work) requires matching physical site evidence.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import math
from typing import Any

from sword_runtime.sim.calendar import CampaignTime

LOCATIONS_PATH = "game/data/world/locations.json"
LAND_STATE_PATH = "state/development/land.json"
SETTLEMENT_INFRASTRUCTURE_PATH = "state/infrastructure/settlements.json"
TRAINING_RULES_PATH = "game/data/mechanics/training.json"

# These can be established in ordinary physical open space by a present formation
# or individual without materializing a permanent building. Facility *quality* is
# still owned by the regimen passed to the EDU law.
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

# Specialist tags require explicit function/site evidence somewhere in the saved
# containment chain. They are intentionally not satisfied by a generic field camp.
_SPECIALIST_REQUIREMENTS: dict[str, tuple[set[str], set[str]]] = {
    "engineering_yard": ({"engineering"}, set()),
    "artillery_range": ({"artillery"}, set()),
    "medical_training": ({"medical", "training"}, set()),
    "household_classroom": (set(), {"household", "house", "academy"}),
    "audience_hall": (set(), {"household", "house", "politics", "academy"}),
    "estate_routes": (set(), {"estate"}),
}

# Shared institutional resources proven by a specialist facility. Ordinary weapons,
# shields, mounts, arrows and bolts remain conserved loadout/supervised resources.
_SHARED_RESOURCES_BY_TAG: dict[str, set[str]] = {
    "engineering_yard": {"engineering_tools"},
    "artillery_range": {"artillery"},
    "signal_ground": {"signals"},
}


def _location_rows(runtime: Any) -> dict[str, Mapping[str, Any]]:
    try:
        doc = runtime.read(LOCATIONS_PATH)
    except Exception:
        return {}
    rows = doc.get("locations", []) if isinstance(doc, Mapping) else []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return {}
    return {
        str(row.get("ref")): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("ref"), str) and row.get("ref")
    }


def _location_chain_rows(runtime: Any, location_ref: str) -> list[Mapping[str, Any]]:
    rows = _location_rows(runtime)
    current = str(location_ref or "")
    if not current or current not in rows:
        return []
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
    return out


def _explicit_tags(chain: Sequence[Mapping[str, Any]]) -> set[str]:
    out: set[str] = set()
    for row in chain:
        raw = row.get("training_facility_tags", [])
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            out.update(str(value) for value in raw if str(value))
    return out


def training_facility_access(runtime: Any, *, location_ref: str, facility_tag: str) -> float:
    """Return 1/0 physical access for one registered drill facility tag.

    Missing location evidence fails closed. Ordinary field-compatible tags can be
    established at any real mapped physical location. Specialist tags require an
    explicit matching location function/kind or an explicit facility tag in the
    current location's containment chain.
    """
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
        functions = {
            str(value)
            for value in row.get("functions", [])
            if isinstance(row.get("functions"), Sequence) and not isinstance(row.get("functions"), (str, bytes, bytearray))
        }
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
    """Resolve the facility gate for every drill in a registered program."""
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
    """Return only specialist shared resources proven by the physical training site."""
    chain = _location_chain_rows(runtime, str(location_ref or ""))
    if not chain:
        return set()
    explicit = _explicit_tags(chain)
    resources: set[str] = set()
    for tag, provided in _SHARED_RESOURCES_BY_TAG.items():
        if tag in explicit or training_facility_access(runtime, location_ref=location_ref, facility_tag=tag) > 0:
            resources.update(provided)
    return resources


def _current_time(runtime: Any) -> CampaignTime:
    try:
        rt = runtime.read("state/runtime.json")
        return CampaignTime.parse(str(rt.get("world_time")))
    except Exception:
        meta = runtime.read("state/meta.json")
        return CampaignTime.parse(str(meta.get("time")))


def _hours_between(start: str, end: CampaignTime) -> float:
    try:
        a = CampaignTime.parse(str(start))
        return max(0.0, a.seconds_until(end) / 3600.0)
    except Exception:
        return 0.0


def _land_owner_row(registry: Mapping[str, Any], location_ref: str) -> tuple[str, Mapping[str, Any]] | tuple[None, None]:
    sites = registry.get("sites", {}) if isinstance(registry.get("sites"), Mapping) else {}
    if location_ref in sites and isinstance(sites[location_ref], Mapping):
        return "site", sites[location_ref]
    regions = registry.get("regions", {}) if isinstance(registry.get("regions"), Mapping) else {}
    if location_ref in regions and isinstance(regions[location_ref], Mapping):
        return "region", regions[location_ref]
    return None, None


def _containing_land_owner_row(runtime: Any, registry: Mapping[str, Any], location_ref: str) -> tuple[str | None, Mapping[str, Any] | None, str | None]:
    """Resolve finite land at the exact site or its physical containment chain.

    Facilities such as depots can occupy a mapped region without owning a separate
    land parcel. A formation at such a child site may use the surrounding region's
    finite ground, but a temporary prepared area remains scoped to the child's exact
    location so another site in the same region cannot borrow it for free.
    """
    for row in _location_chain_rows(runtime, str(location_ref or "")):
        ref = str(row.get("ref", ""))
        kind, owner = _land_owner_row(registry, ref)
        if isinstance(owner, Mapping):
            return kind, owner, ref
    kind, owner = _land_owner_row(registry, str(location_ref or ""))
    if isinstance(owner, Mapping):
        return kind, owner, str(location_ref)
    return None, None, None


def _temporary_area_condition(record: Mapping[str, Any], *, now: CampaignTime, rules: Mapping[str, Any]) -> float:
    if str(record.get("status", "active")) not in {"active", "abandoned"}:
        return 0.0
    base = max(0.0, min(1.0, float(record.get("condition", 1.0))))
    if str(record.get("status")) != "abandoned":
        return base
    cfg = rules.get("physical_environment", {}).get("temporary_condition", {}) if isinstance(rules.get("physical_environment"), Mapping) else {}
    decay = max(0.0, float(cfg.get("abandoned_decay_per_30d", 0.25)))
    hours = _hours_between(str(record.get("abandoned_at") or record.get("last_maintained_at") or record.get("completed_at") or ""), now)
    return max(0.0, base - decay * hours / (30.0 * 24.0))


def training_environment(
    runtime: Any,
    *,
    location_ref: str,
    simultaneous_trainees: int = 1,
) -> dict[str, Any]:
    """Resolve physical training quality/capacity from current location evidence.

    Permanent facility quality comes from current physical infrastructure. Temporary
    prepared areas come from finite land records. If neither exists, lawful suitable
    open ground is a bare field with the lower field factor. Curriculum never changes
    this result.
    """
    trainees = max(1, int(simultaneous_trainees))
    rules = runtime.read(TRAINING_RULES_PATH)
    env = rules.get("physical_environment", {}) if isinstance(rules, Mapping) else {}
    space_per_1000 = max(1e-9, float(env.get("simultaneous_space_km2_per_1000_trainees", 0.12)))
    grade_map = env.get("environment_to_facility_grade", {}) if isinstance(env.get("environment_to_facility_grade"), Mapping) else {}

    # Permanent support is authoritative when explicitly built.
    try:
        infra = runtime.read(SETTLEMENT_INFRASTRUCTURE_PATH)
    except Exception:
        infra = {}
    infra_sites = infra.get("sites", {}) if isinstance(infra.get("sites"), Mapping) else {}
    # A drill yard, barracks district, citadel court, or other child location is
    # physically inside its containing site. Use the nearest containing site with
    # built training support instead of requiring every child node to duplicate the
    # same capacity record. This is containment, not remote access: an unrelated
    # location never inherits the facility.
    support = {}
    support_site_ref = None
    for row in _location_chain_rows(runtime, str(location_ref or "")):
        candidate_ref = str(row.get("ref", ""))
        site_support = infra_sites.get(candidate_ref, {}) if isinstance(infra_sites, Mapping) else {}
        candidate = site_support.get("training_support", {}) if isinstance(site_support, Mapping) and isinstance(site_support.get("training_support"), Mapping) else {}
        if max(0, int(candidate.get("simultaneous_trainee_capacity", 0))) > 0:
            support = candidate
            support_site_ref = candidate_ref
            break
    permanent_capacity = max(0, int(support.get("simultaneous_trainee_capacity", 0)))
    if permanent_capacity > 0:
        named = str(support.get("facility_grade", "standard_permanent"))
        canonical = named if named in grade_map else ({
            "adequate": "standard_permanent", "good": "developed_permanent", "excellent": "excellent_permanent"
        }.get(named, "standard_permanent"))
        capacity_factor = min(1.0, permanent_capacity / trainees)
        return {
            "environment": canonical,
            "facility_grade": str(grade_map.get(canonical, "adequate")),
            "capacity_factor": round(capacity_factor, 6),
            "simultaneous_capacity": permanent_capacity,
            "required_area_km2": round(trainees / 1000.0 * space_per_1000, 6),
            "source": "permanent_physical_training_support",
            "source_site_ref": support_site_ref,
        }

    try:
        land = runtime.read(LAND_STATE_PATH)
    except Exception:
        land = {}
    kind, owner, land_owner_ref = _containing_land_owner_row(runtime, land, location_ref)
    if isinstance(owner, Mapping):
        training_area = 0.0
        if kind == "site":
            for key in ("enclosed_land_use_km2", "external_land_use_km2"):
                use = owner.get(key, {}) if isinstance(owner.get(key), Mapping) else {}
                training_area += max(0.0, float(use.get("training", 0.0)))
        else:
            use = owner.get("land_use_km2", {}) if isinstance(owner.get("land_use_km2"), Mapping) else {}
            training_area = max(0.0, float(use.get("training", 0.0)))
        if training_area > 0:
            land_capacity = max(1, int(math.floor(training_area / space_per_1000 * 1000.0)))
            return {
                "environment": "standard_permanent",
                "facility_grade": str(grade_map.get("standard_permanent", "adequate")),
                "capacity_factor": round(min(1.0, land_capacity / trainees), 6),
                "simultaneous_capacity": land_capacity,
                "required_area_km2": round(trainees / 1000.0 * space_per_1000, 6),
                "source": "permanent_training_land",
            }
    now = _current_time(runtime)
    best_temp_capacity = 0
    best_ref = None
    temporary = owner.get("temporary_training_areas", {}) if isinstance(owner, Mapping) and isinstance(owner.get("temporary_training_areas"), Mapping) else {}
    min_condition = float(env.get("temporary_condition", {}).get("minimum_usable_condition", 0.25)) if isinstance(env.get("temporary_condition"), Mapping) else 0.25
    for ref, row in temporary.items():
        if not isinstance(row, Mapping):
            continue
        area_location = str(row.get("location_ref", land_owner_ref or ""))
        if area_location not in {str(location_ref), str(land_owner_ref or "")}:
            continue
        cond = _temporary_area_condition(row, now=now, rules=rules)
        if cond + 1e-9 < min_condition:
            continue
        cap = int(max(0.0, float(row.get("simultaneous_trainee_capacity", 0))) * cond)
        if cap > best_temp_capacity:
            best_temp_capacity = cap; best_ref = str(ref)
    if best_temp_capacity > 0:
        return {
            "environment": "prepared_field",
            "facility_grade": str(grade_map.get("prepared_field", "basic")),
            "capacity_factor": round(min(1.0, best_temp_capacity / trainees), 6),
            "simultaneous_capacity": best_temp_capacity,
            "required_area_km2": round(trainees / 1000.0 * space_per_1000, 6),
            "temporary_area_ref": best_ref,
            "source": "temporary_prepared_training_area",
        }

    # Bare suitable land is still usable, but only at the bare-field grade and within
    # the actual amount of non-unsuitable, non-water physical ground.
    suitable_area = 0.0
    if isinstance(owner, Mapping):
        if kind == "site":
            for key in ("enclosed_land_use_km2", "external_land_use_km2"):
                use = owner.get(key, {}) if isinstance(owner.get(key), Mapping) else {}
                suitable_area += sum(max(0.0, float(v)) for k, v in use.items() if str(k) not in {"water", "unsuitable", "fortification"})
        else:
            use = owner.get("land_use_km2", {}) if isinstance(owner.get("land_use_km2"), Mapping) else {}
            suitable_area = sum(max(0.0, float(v)) for k, v in use.items() if str(k) not in {"water", "unsuitable", "nested_site_parcels"})
    bare_capacity = max(0, int(math.floor(suitable_area / space_per_1000 * 1000.0)))
    return {
        "environment": "bare_suitable_field",
        "facility_grade": str(grade_map.get("bare_suitable_field", "none")),
        "capacity_factor": round(min(1.0, bare_capacity / trainees), 6) if bare_capacity > 0 else 0.0,
        "simultaneous_capacity": bare_capacity,
        "required_area_km2": round(trainees / 1000.0 * space_per_1000, 6),
        "source": "finite_suitable_land",
    }


def field_training_preparation_spec(runtime: Any, *, simultaneous_trainees: int) -> dict[str, Any]:
    trainees = max(1, int(simultaneous_trainees))
    rules = runtime.read(TRAINING_RULES_PATH)
    env = rules.get("physical_environment", {}) if isinstance(rules, Mapping) else {}
    unit = env.get("prepared_field_per_1000_trainees", {}) if isinstance(env.get("prepared_field_per_1000_trainees"), Mapping) else {}
    units = trainees / 1000.0
    area = max(0.0, float(env.get("simultaneous_space_km2_per_1000_trainees", 0.12))) * units
    labor = {
        "general": int(math.ceil(max(0.0, float(unit.get("general_labor_hours", 3000))) * units)),
        "skilled": int(math.ceil(max(0.0, float(unit.get("skilled_labor_hours", 750))) * units)),
        "engineering": int(math.ceil(max(0.0, float(unit.get("engineering_labor_hours", 250))) * units)),
    }
    return {
        "simultaneous_trainee_capacity": trainees,
        "area_km2": round(area, 6),
        "construction_material_units": int(math.ceil(max(0.0, float(unit.get("construction_material_units", 100))) * units)),
        "labor_hours_by_class": labor,
        "labor_hours": sum(labor.values()),
        "minimum_calendar_hours": max(1, int(unit.get("minimum_calendar_hours", 24))),
    }


def prepare_field_training_area(
    runtime: Any,
    *,
    location_ref: str,
    simultaneous_trainees: int,
    formation_ref: str,
    available_workers: int,
    at: str,
) -> dict[str, Any]:
    """Create a completed temporary prepared training area using real formation material.

    This helper performs the conservative physical transaction at completion time.
    The caller must advance chronology by ``duration_hours`` before invoking it when
    used by a command reducer.
    """
    spec = field_training_preparation_spec(runtime, simultaneous_trainees=simultaneous_trainees)
    land = deepcopy(runtime.read(LAND_STATE_PATH))
    kind, owner, land_owner_ref = _containing_land_owner_row(runtime, land, location_ref)
    if not isinstance(owner, dict):
        raise ValueError("field training preparation requires a finite land owner")
    existing = training_environment(runtime, location_ref=location_ref, simultaneous_trainees=simultaneous_trainees)
    # Permanent training land may already satisfy the entire request. Do not waste
    # campaign material merely because a caller asks to prepare a field.
    if existing.get("source") == "permanent_physical_training_support" and float(existing.get("capacity_factor", 0)) >= 1.0:
        raise ValueError("permanent training capacity already satisfies this preparation request")
    suitable = 0.0
    if kind == "site":
        for key in ("enclosed_land_use_km2", "external_land_use_km2"):
            use = owner.get(key, {}) if isinstance(owner.get(key), Mapping) else {}
            suitable += sum(max(0.0, float(v)) for k, v in use.items() if str(k) in {"open_developable", "military", "training", "transport", "pasture", "agriculture"})
    else:
        use = owner.get("land_use_km2", {}) if isinstance(owner.get("land_use_km2"), Mapping) else {}
        suitable = sum(max(0.0, float(v)) for k, v in use.items() if str(k) in {"open_developable", "military", "training", "transport", "pasture", "agriculture"})
    active_area = sum(max(0.0, float(v.get("area_km2", 0))) for v in owner.get("temporary_training_areas", {}).values() if isinstance(v, Mapping) and str(v.get("status", "active")) == "active") if isinstance(owner.get("temporary_training_areas"), Mapping) else 0.0
    if suitable + 1e-9 < active_area + float(spec["area_km2"]):
        raise ValueError("insufficient suitable land for prepared field training area")

    fpath = runtime.owner_path(formation_ref)
    formation = deepcopy(runtime.read(fpath))
    if str(formation.get("location_ref", "")) != str(location_ref):
        raise ValueError("formation must be physically present at the prepared field location")
    logistics = formation.setdefault("logistics", {})
    materials = int(spec["construction_material_units"])
    if int(logistics.get("construction_material_units", 0)) < materials:
        raise ValueError("formation lacks construction material for prepared field training area")
    workers = max(1, min(max(1, int(available_workers)), max(1, int(formation.get("personnel", 0)))))
    labor_hours = max(0, int(spec["labor_hours"]))
    labor_calendar = int(math.ceil(labor_hours / max(1.0, workers * 8.0 * 0.9) * 24.0))
    duration = max(int(spec["minimum_calendar_hours"]), labor_calendar)
    logistics["construction_material_units"] = int(logistics.get("construction_material_units", 0)) - materials
    runtime.put(fpath, formation)

    digest = hashlib.sha256(f"{location_ref}|{formation_ref}|{at}|{simultaneous_trainees}".encode()).hexdigest()[:16]
    ref = f"field_training.{digest}"
    record = {
        "training_area_ref": ref,
        "location_ref": location_ref,
        "land_owner_ref": str(land_owner_ref or location_ref),
        "formation_ref": formation_ref,
        "status": "active",
        "area_km2": spec["area_km2"],
        "simultaneous_trainee_capacity": int(spec["simultaneous_trainee_capacity"]),
        "construction_material_units_consumed": materials,
        "labor_hours_by_class": dict(spec["labor_hours_by_class"]),
        "labor_hours": labor_hours,
        "construction_workers": workers,
        "duration_hours": duration,
        "completed_at": str(at),
        "last_maintained_at": str(at),
        "condition": 1.0,
        "temporary": True,
    }
    owner.setdefault("temporary_training_areas", {})[ref] = record
    runtime.put(LAND_STATE_PATH, land)
    return deepcopy(record)


def abandon_field_training_area(runtime: Any, *, location_ref: str, training_area_ref: str, at: str) -> dict[str, Any]:
    land = deepcopy(runtime.read(LAND_STATE_PATH))
    _kind, owner, _land_owner_ref = _containing_land_owner_row(runtime, land, location_ref)
    if not isinstance(owner, dict):
        raise ValueError("field training area location has no finite land owner")
    areas = owner.get("temporary_training_areas", {}) if isinstance(owner.get("temporary_training_areas"), dict) else {}
    record = areas.get(training_area_ref)
    if not isinstance(record, dict):
        raise ValueError("unknown field training area")
    if str(record.get("status")) == "abandoned":
        return deepcopy(record)
    record["status"] = "abandoned"
    record["abandoned_at"] = str(at)
    runtime.put(LAND_STATE_PATH, land)
    return deepcopy(record)


__all__ = [
    "LOCATIONS_PATH", "LAND_STATE_PATH", "SETTLEMENT_INFRASTRUCTURE_PATH", "TRAINING_RULES_PATH",
    "program_facility_access",
    "shared_training_resources",
    "training_facility_access",
    "training_environment", "field_training_preparation_spec", "prepare_field_training_area", "abandon_field_training_area",
]
