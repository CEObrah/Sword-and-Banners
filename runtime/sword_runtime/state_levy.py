"""Universal sovereign-state levy transactions.

A levy is temporary service by conserved civilians.  It is not a permanent troop
species and receives no special combat law.  This module moves real bodies from a
population owner into a temporary force, issues only equipment that physically
exists, and returns surviving bodies/equipment on demobilization.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
from typing import Any

from sword_runtime.cohort_personnel import (
    append_formation_slices,
    record_recruitment_cohort,
    return_formation_slices,
    take_reserve_slices,
    validate_cohort_ledger,
)
from sword_runtime.officer_cadre import ensure_officer_cadre, reorganize_officer_cadre
from sword_runtime.unit_establishment import normalize_formation_establishment

RULES_PATH = "game/data/mechanics/settlement.json"
PROFILE_PATH = "game/data/mil/recruitment-cohort-profiles.json"


def _rules(runtime: Any) -> Mapping[str, Any]:
    doc = runtime.read(RULES_PATH)
    row = doc.get("levy_system", {}) if isinstance(doc, Mapping) else {}
    if not isinstance(row, Mapping):
        raise ValueError("levy mechanics are missing")
    return row


def _levy_refs(state_doc: Mapping[str, Any]) -> list[str]:
    raw = state_doc.get("active_levy_refs", []) if isinstance(state_doc, Mapping) else []
    return [str(x) for x in raw if isinstance(x, str) and x]


def _levy_force_ref(state: str, levy_ref: str) -> str:
    token = hashlib.sha256(f"{state}|{levy_ref}".encode()).hexdigest()[:16]
    return f"force_state_levy_{state}_{token}"


def _levy_formation_ref(state: str, levy_ref: str) -> str:
    token = hashlib.sha256(f"{state}|{levy_ref}|formation".encode()).hexdigest()[:16]
    return f"formation_state_levy_{state}_{token}"


def _levy_force_path(force_ref: str) -> str:
    return f"state/forces/levies/{force_ref.replace('force_', '').replace('_', '-')}.json"


def _levy_formation_path(formation_ref: str) -> str:
    return f"state/formations/{formation_ref.replace('formation_', '').replace('_', '-')}.json"


def _source_headroom(row: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, int]:
    strata = row.get("civilian_strata", {}) if isinstance(row.get("civilian_strata"), Mapping) else {}
    floors = rules.get("essential_labor_floor_fraction", {}) if isinstance(rules.get("essential_labor_floor_fraction"), Mapping) else {}
    out: dict[str, int] = {}
    for key in rules.get("source_strata_order", []):
        source = str(key)
        current = max(0, int(strata.get(source, 0)))
        floor_fraction = max(0.0, min(1.0, float(floors.get(source, 0.65))))
        floor = int(current * floor_fraction)
        out[source] = max(0, current - floor)
    return out


def levy_eligibility(runtime: Any, *, state: str, location_ref: str) -> dict[str, Any]:
    rules = _rules(runtime)
    pop_path = f"state/population/{state}.json"
    pop = deepcopy(runtime.read(pop_path))
    if not hasattr(runtime, "_local_population_row"):
        raise ValueError("levy requires local population authority")
    _path, pop, row = runtime._local_population_row(state, location_ref, pop)
    headroom = _source_headroom(row, rules)
    state_doc = runtime.read(f"state/states/{state}.json")
    active = 0
    for force_ref in _levy_refs(state_doc):
        try:
            force = runtime.read(runtime.owner_path(force_ref))
        except Exception:
            continue
        active += max(0, int(force.get("headcount", 0)))
    total_cap = int(max(0, int(pop.get("population_total", 0))) * max(0.0, float(rules.get("maximum_active_fraction_of_total_population", 0.08))))
    return {
        "state": state,
        "location_ref": location_ref,
        "source_headroom": headroom,
        "local_eligible_personnel": sum(headroom.values()),
        "active_levy_personnel": active,
        "state_active_levy_cap": total_cap,
        "remaining_state_levy_cap": max(0, total_cap - active),
        "currently_callable_personnel": max(0, min(sum(headroom.values()), total_cap - active)),
    }


def call_state_levy(
    runtime: Any,
    *,
    state: str,
    personnel: int,
    location_ref: str,
    role: str,
    levy_ref: str,
    at: str,
) -> dict[str, Any]:
    """Call one temporary levy and immediately organize it as one formation."""
    n = max(0, int(personnel))
    rules = _rules(runtime)
    minimum = max(1, int(rules.get("minimum_call_personnel", 500)))
    if n < minimum:
        raise ValueError(f"levy call requires at least {minimum} personnel")
    state_path = f"state/states/{state}.json"
    pop_path = f"state/population/{state}.json"
    state_doc = deepcopy(runtime.read(state_path))
    if levy_ref in state_doc.get("levy_history", {}):
        raise ValueError("levy_ref has already been used")
    eligibility = levy_eligibility(runtime, state=state, location_ref=location_ref)
    if n > int(eligibility["currently_callable_personnel"]):
        raise ValueError("requested levy exceeds conserved eligibility and essential-labor floors")

    organization_cost = max(0, int(rules.get("organization_silver_per_person", 2))) * n
    if int(state_doc.get("treasury_silver", 0)) < organization_cost:
        raise ValueError("state treasury cannot organize the requested levy")

    force_ref = _levy_force_ref(state, levy_ref)
    formation_ref = _levy_formation_ref(state, levy_ref)
    force_path = _levy_force_path(force_ref)
    formation_path = _levy_formation_path(formation_ref)
    if runtime.read_optional(force_path) is not None or runtime.read_optional(formation_path) is not None:
        raise ValueError("levy owner collision")

    pop = deepcopy(runtime.read(pop_path))
    _pp, pop, row = runtime._local_population_row(state, location_ref, pop)
    headroom = _source_headroom(row, rules)
    remaining = n
    sources: dict[str, int] = {}
    # Move actual local civilians into temporary native military service.
    for source in rules.get("source_strata_order", []):
        source = str(source)
        take = min(remaining, int(headroom.get(source, 0)))
        if take <= 0:
            continue
        moved = runtime._consume_local_recruitment(
            pop,
            state,
            location_ref,
            take,
            service_key="serving_native_military",
            source_stratum=source,
            service_owner_ref=force_ref,
        )
        if moved != take:
            raise ValueError("levy local population transfer failed conservation")
        pop["strata"][source] = int(pop["strata"].get(source, 0)) - take
        pop["strata"]["active_military"] = int(pop["strata"].get("active_military", 0)) + take
        sources[source] = take
        remaining -= take
        if remaining <= 0:
            break
    if remaining:
        raise ValueError("levy source partition exhausted unexpectedly")

    force = {
        "schema": "sword-force",
        "owner_id": force_ref,
        "owner_type": "force",
        "kind": "temporary_state_levy",
        "service_class": "state_levy",
        "temporary_service": True,
        "state": state,
        "administrative_owner": f"state_{state}",
        "source_location_ref": location_ref,
        "headcount": n,
        "authorized_strength": n,
        "available_by_role": {role: n},
        "available_by_location": {location_ref: {role: n}},
        "allocated_to_formations": {},
        "available_equipment_units_by_role": {role: 0},
        "available_equipment_by_location": {location_ref: {role: 0}},
        "cohort_ledger": {"schema": "force-cohort-ledger", "cohorts": {}, "last_reconciled_at": at},
        "levy": {
            "levy_ref": levy_ref,
            "called_at": at,
            "source_location_ref": location_ref,
            "source_strata": deepcopy(sources),
            "organization_silver_paid": organization_cost,
            "training_regimen_ref": str(rules.get("training_regimen_ref", "levy_basic")),
            "status": "active",
        },
    }
    profiles = runtime.read(PROFILE_PATH)
    background_map = rules.get("background_profile_by_source_stratum", {}) if isinstance(rules.get("background_profile_by_source_stratum"), Mapping) else {}
    for source, count in sources.items():
        record_recruitment_cohort(
            force,
            role=role,
            count=count,
            location_ref=location_ref,
            source_population_ref=f"population_{state}",
            source_stratum=source,
            recruited_at=at,
            profile_registry=profiles,
            background_profile=str(background_map.get(source, "civilian_common")),
            selection_profile=None,
            provenance_ref=f"levy:{levy_ref}",
            intake_ref=levy_ref,
            validate=False,
        )
    validate_cohort_ledger(force)

    # Issue only real state-owned equipment. Missing kit remains a real shortfall.
    state_force_path = f"state/forces/state-{state}.json"
    state_force = runtime._ct_force(state_force_path) if hasattr(runtime, "_ct_force") else deepcopy(runtime.read(state_force_path))
    equipped = runtime._take_force_equipment(state_force, role, n, location_ref)
    force["available_equipment_units_by_role"][role] = equipped
    force["available_equipment_by_location"][location_ref][role] = equipped
    runtime.put(state_force_path, state_force)

    # Organize the levy as an ordinary formation so it can march/fight through the
    # same formation/battle pipeline.  Capability comes from its actual cohorts.
    runtime._take_force_personnel(force, role, n, location_ref)
    formation_equipment = runtime._take_force_equipment(force, role, equipped, location_ref)
    slices = take_reserve_slices(force, role=role, count=n, location_ref=location_ref, formation_ref=formation_ref, validate=False)
    formation_state = rules.get("initial_formation_state", {}) if isinstance(rules.get("initial_formation_state"), Mapping) else {}
    formation = {
        "schema": "sword-formation",
        "formation_ref": formation_ref,
        "name": f"{state.upper()} Temporary Levy",
        "owner_force_ref": force_ref,
        "administrative_owner": f"state_{state}",
        "command_authority": f"state_{state}",
        "commander_ref": None,
        "personnel": n,
        "authorized_strength": n,
        "composition": {role: n},
        "cohort_composition": slices,
        "location_ref": location_ref,
        "training_ref": None,
        "training_regimen_ref": str(rules.get("training_regimen_ref", "levy_basic")),
        "doctrine_behavior": {"casualty_tolerance": "moderate", "reserve_commitment": 35, "withdrawal_threshold": 35},
        "training_progress": int(formation_state.get("training_progress", 5)),
        "readiness": int(formation_state.get("readiness", 30)),
        "morale": int(formation_state.get("morale", 55)),
        "cohesion": int(formation_state.get("cohesion", 20)),
        "fatigue": 0,
        "experience": str(formation_state.get("experience", "unblooded")),
        "mobilized": True,
        "status": "mobilized",
        "equipment_units_by_role": {role: formation_equipment},
        "equipment_completeness": round(formation_equipment / max(1, n), 4),
        "logistics": {"food_kg": 0, "fodder_kg": 0, "war_arrows": 0, "war_bolts": 0, "construction_material_units": 0},
        "mounts": {},
        "created_at": at,
        "temporary_levy_ref": levy_ref,
    }
    normalize_formation_establishment(formation)
    ensure_officer_cadre(formation)
    reorganize_officer_cadre(formation, at=at, reason="levy_call")
    force["allocated_to_formations"][formation_ref] = runtime._formation_allocation_record(formation)
    validate_cohort_ledger(force)

    state_doc["treasury_silver"] = int(state_doc.get("treasury_silver", 0)) - organization_cost
    active = [x for x in _levy_refs(state_doc) if x != force_ref]
    active.append(force_ref)
    state_doc["active_levy_refs"] = active
    history = state_doc.setdefault("levy_history", {})
    history[levy_ref] = {
        "status": "active",
        "force_ref": force_ref,
        "formation_ref": formation_ref,
        "called_at": at,
        "personnel_called": n,
        "source_location_ref": location_ref,
        "source_strata": deepcopy(sources),
        "equipment_issued": formation_equipment,
        "organization_silver_paid": organization_cost,
    }

    runtime.put(pop_path, pop)
    runtime.put(force_path, force)
    runtime.put(formation_path, formation)
    runtime.put(state_path, state_doc)
    runtime._register_owner(force_ref, force_path)
    runtime._register_owner(formation_ref, formation_path)
    runtime._index_formation_location(formation_ref, None, location_ref)
    return {
        "levy_ref": levy_ref,
        "force_ref": force_ref,
        "formation_ref": formation_ref,
        "personnel": n,
        "source_strata": sources,
        "equipment_issued": formation_equipment,
        "equipment_completeness": round(formation_equipment / max(1, n), 4),
        "organization_silver_paid": organization_cost,
        "eligibility_before": eligibility,
    }


def demobilize_state_levy(runtime: Any, *, state: str, levy_ref: str, at: str) -> dict[str, Any]:
    """Return surviving levy bodies to their exact source strata and state equipment."""
    state_path = f"state/states/{state}.json"
    state_doc = deepcopy(runtime.read(state_path))
    history = state_doc.get("levy_history", {}) if isinstance(state_doc.get("levy_history"), Mapping) else {}
    record = history.get(levy_ref) if isinstance(history, Mapping) else None
    if not isinstance(record, Mapping) or str(record.get("status")) != "active":
        raise ValueError("levy is not active")
    force_ref = str(record.get("force_ref", ""))
    force_path = runtime.owner_path(force_ref)
    force = runtime._ct_force(force_path) if hasattr(runtime, "_ct_force") else deepcopy(runtime.read(force_path))

    # Dissolve every surviving levy formation back into the temporary force first.
    for formation_ref in list(force.get("allocated_to_formations", {})):
        try:
            formation_path, formation0 = runtime._load_formation(str(formation_ref))
        except Exception:
            continue
        formation = deepcopy(formation0)
        location = str(formation.get("location_ref") or force.get("source_location_ref"))
        for role, count in formation.get("composition", {}).items():
            runtime._return_force_personnel(force, str(role), int(count), location)
        for role, count in runtime._equipment_units(formation).items():
            runtime._return_force_equipment(force, str(role), int(count), location)
        # Top-level formation allocation and cohort slices are one conserved view.
        # Remove the top-level allocation before the cohort helper validates the
        # now-returned slices against current force allocations.
        force.get("allocated_to_formations", {}).pop(formation_ref, None)
        if formation.get("cohort_composition"):
            return_formation_slices(force, formation)
        runtime._release_commander_index(formation.get("commander_ref"), formation_ref)
        runtime.delete(formation_path)
        runtime._unregister_owner(str(formation_ref))
        runtime._index_formation_location(str(formation_ref), location, None)

    validate_cohort_ledger(force)
    survivors = max(0, int(force.get("headcount", 0)))
    pop_path = f"state/population/{state}.json"
    pop = deepcopy(runtime.read(pop_path))
    _pp, pop = runtime._ensure_local_population_ledger(state, pop)
    source_returns: dict[str, int] = {}
    local_returns: dict[str, dict[str, int]] = {}

    # Survivor provenance is carried by the actual remaining cohort bodies.
    cohorts = force.get("cohort_ledger", {}).get("cohorts", {}) if isinstance(force.get("cohort_ledger"), Mapping) else {}
    for cohort in cohorts.values():
        if not isinstance(cohort, Mapping):
            continue
        origin = cohort.get("origin", {}) if isinstance(cohort.get("origin"), Mapping) else {}
        source = str(origin.get("source_stratum", "agricultural"))
        location = str(origin.get("source_location_ref", force.get("source_location_ref", "")))
        count = sum(max(0, int(v)) for v in cohort.get("reserve_by_location", {}).values()) + sum(max(0, int(v)) for v in cohort.get("allocated_by_formation", {}).values())
        if count <= 0:
            continue
        # Remove the exact local service allocation owned by this levy force and
        # return bodies to the original civilian stratum.
        _path, pop, row = runtime._local_population_row(state, location, pop)
        allocations = row.get("service_allocations", {}) if isinstance(row.get("service_allocations"), dict) else {}
        allocation = allocations.get(force_ref) if isinstance(allocations.get(force_ref), dict) else None
        if not isinstance(allocation, dict) or int(allocation.get("personnel", 0)) < count:
            raise ValueError("levy demobilization exceeds conserved local service allocation")
        allocation["personnel"] = int(allocation.get("personnel", 0)) - count
        if allocation["personnel"] <= 0:
            allocations.pop(force_ref, None)
        civ = row.setdefault("civilian_strata", {})
        civ[source] = int(civ.get(source, 0)) + count
        runtime._sync_local_population_row(row)
        source_returns[source] = source_returns.get(source, 0) + count
        local_returns.setdefault(location, {})[source] = local_returns.setdefault(location, {}).get(source, 0) + count

    if sum(source_returns.values()) != survivors:
        raise ValueError("levy survivor provenance does not equal surviving force headcount")
    for source, count in source_returns.items():
        pop["strata"][source] = int(pop["strata"].get(source, 0)) + count
    if int(pop["strata"].get("active_military", 0)) < survivors:
        raise ValueError("population active military is smaller than surviving levy")
    pop["strata"]["active_military"] = int(pop["strata"].get("active_military", 0)) - survivors

    # Return surviving issued equipment to the ordinary state equipment authority.
    state_force_path = f"state/forces/state-{state}.json"
    state_force = runtime._ct_force(state_force_path) if hasattr(runtime, "_ct_force") else deepcopy(runtime.read(state_force_path))
    returned_equipment: dict[str, int] = {}
    source_location = str(force.get("source_location_ref", ""))
    for role, raw in force.get("available_equipment_units_by_role", {}).items():
        count = max(0, int(raw))
        if count:
            runtime._return_force_equipment(state_force, str(role), count, source_location)
            returned_equipment[str(role)] = count
    runtime.put(state_force_path, state_force)

    history = state_doc.setdefault("levy_history", {})
    rec = dict(history[levy_ref])
    rec.update({
        "status": "demobilized",
        "demobilized_at": at,
        "survivors_returned": survivors,
        "casualties_or_missing": max(0, int(rec.get("personnel_called", 0)) - survivors),
        "returned_by_source_stratum": source_returns,
        "returned_equipment_by_role": returned_equipment,
    })
    history[levy_ref] = rec
    state_doc["active_levy_refs"] = [x for x in _levy_refs(state_doc) if x != force_ref]

    runtime.put(pop_path, pop)
    runtime.put(state_path, state_doc)
    runtime.delete(force_path)
    runtime._unregister_owner(force_ref)
    return {
        "levy_ref": levy_ref,
        "force_ref": force_ref,
        "survivors_returned": survivors,
        "casualties_or_missing": rec["casualties_or_missing"],
        "returned_by_source_stratum": source_returns,
        "returned_equipment_by_role": returned_equipment,
        "local_returns": local_returns,
    }


def active_levy_formations(runtime: Any, state: str) -> list[str]:
    """Return exact active levy formation refs for one sovereign state."""
    state_doc = runtime.read(f"state/states/{state}.json")
    out: list[str] = []
    for force_ref in _levy_refs(state_doc):
        try:
            force = runtime.read(runtime.owner_path(force_ref))
        except Exception:
            continue
        for formation_ref in force.get("allocated_to_formations", {}):
            try:
                _p, formation = runtime._load_formation(str(formation_ref))
            except Exception:
                continue
            if int(formation.get("personnel", 0)) > 0:
                out.append(str(formation_ref))
    return sorted(set(out))


__all__ = [
    "RULES_PATH",
    "PROFILE_PATH",
    "levy_eligibility",
    "call_state_levy",
    "demobilize_state_levy",
    "active_levy_formations",
]
