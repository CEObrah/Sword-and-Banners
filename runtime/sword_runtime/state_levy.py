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
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.military_doctrine import default_formation_doctrine_ref, doctrine_behavior
from sword_runtime.support_tasks import FORBIDDEN_PERMANENT_SUPPORT_ROLES

RULES_PATH = "game/data/mechanics/settlement.json"
PROFILE_PATH = "game/data/mil/recruitment-cohort-profiles.json"
LEVY_TERMINAL_HISTORY_LIMIT = 32


def _rules(runtime: Any) -> Mapping[str, Any]:
    doc = runtime.read(RULES_PATH)
    row = doc.get("levy_system", {}) if isinstance(doc, Mapping) else {}
    if not isinstance(row, Mapping):
        raise ValueError("levy mechanics are missing")
    return row


def _levy_refs(state_doc: Mapping[str, Any]) -> list[str]:
    raw = state_doc.get("active_levy_refs", []) if isinstance(state_doc, Mapping) else []
    return [str(x) for x in raw if isinstance(x, str) and x]


def _compact_levy_history(state_doc: dict[str, Any]) -> None:
    """Keep every active levy plus only a bounded recent terminal tail.

    Active levy records are current obligations and must remain exact for
    demobilization. Completed records are recent operational evidence only;
    transaction idempotency lives in the write/receipt layer, so they must not
    turn the sovereign state owner into an append-only campaign diary.
    """
    raw = state_doc.get("levy_history")
    if not isinstance(raw, Mapping):
        state_doc["levy_history"] = {}
        return
    active: dict[str, Any] = {}
    terminal: list[tuple[str, str, dict[str, Any]]] = []
    for ref, record in raw.items():
        if not isinstance(ref, str) or not isinstance(record, Mapping):
            continue
        row = deepcopy(dict(record))
        if str(row.get("status", "")) == "active":
            active[ref] = row
            continue
        stamp = str(row.get("demobilized_at") or row.get("called_at") or "")
        terminal.append((stamp, ref, row))
    terminal.sort(key=lambda item: (item[0], item[1]))
    kept = terminal[-LEVY_TERMINAL_HISTORY_LIMIT:]
    state_doc["levy_history"] = {**active, **{ref: row for _stamp, ref, row in kept}}


def _strain_rules(rules: Mapping[str, Any]) -> Mapping[str, Any]:
    row = rules.get("mobilization_strain", {}) if isinstance(rules.get("mobilization_strain"), Mapping) else {}
    return row


def _strain_at(state_doc: Mapping[str, Any], *, at: str, rules: Mapping[str, Any]) -> dict[str, Any]:
    cfg = _strain_rules(rules)
    maximum = max(1, int(cfg.get("maximum_milli", 1000) or 1000))
    recovery = max(0, int(cfg.get("recovery_milli_per_day", 3) or 0))
    raw = state_doc.get("mobilization_strain", {}) if isinstance(state_doc.get("mobilization_strain"), Mapping) else {}
    milli = max(0, min(maximum, int(raw.get("milli", 0) or 0)))
    prior = raw.get("as_of")
    elapsed_days = 0
    if isinstance(prior, str) and prior:
        try:
            elapsed = CampaignTime.parse(str(at)).seconds_since(CampaignTime.parse(prior))
            elapsed_days = max(0, elapsed // 86400)
        except (TypeError, ValueError):
            elapsed_days = 0
    current = max(0, milli - elapsed_days * recovery)
    return {"milli": current, "as_of": str(at), "elapsed_recovery_days": elapsed_days}


def mobilization_strain_snapshot(runtime: Any, *, state: str, at: str | None = None) -> dict[str, Any]:
    """Derive current war-mobilization exhaustion without creating another owner.

    Active levies already remove real workers from civilian strata.  This compact
    state-level accumulator models the *recovery lag* after mass call-ups and
    casualties so demobilization cannot restore full civil output and immediate
    remobilization capacity on the same day.  The value decays deterministically
    from its saved ``as_of`` frontier and never appends history.
    """
    rules = _rules(runtime)
    review_at = str(at or _world_time(runtime))
    state_path = f"state/states/{state}.json"
    try:
        state_doc = runtime.read(state_path)
    except (FileNotFoundError, KeyError, ValueError):
        # Aggregate private economies also exist for non-sovereign regional
        # actors (for example the northern steppe). They have no lawful state
        # levy owner and therefore no sovereign mobilization-strain authority.
        return {
            "state": state,
            "as_of": review_at,
            "mobilization_strain_milli": 0,
            "elapsed_recovery_days": 0,
            "civil_labor_factor_milli": 1000,
            "rule_ref": RULES_PATH,
            "applicability": "no_sovereign_state_levy_owner",
        }
    strain = _strain_at(state_doc, at=review_at, rules=rules)
    cfg = _strain_rules(rules)
    maximum = max(1, int(cfg.get("maximum_milli", 1000) or 1000))
    ratio = max(0.0, min(1.0, int(strain["milli"]) / maximum))
    labor_penalty_max = max(0.0, min(0.75, float(cfg.get("maximum_civil_labor_penalty_fraction", 0.25) or 0.0)))
    labor_factor = max(0.25, 1.0 - labor_penalty_max * ratio)
    return {
        "state": state,
        "as_of": review_at,
        "mobilization_strain_milli": int(strain["milli"]),
        "elapsed_recovery_days": int(strain.get("elapsed_recovery_days", 0) or 0),
        "civil_labor_factor_milli": int(round(labor_factor * 1000)),
        "rule_ref": RULES_PATH,
    }


def _world_time(runtime: Any) -> str:
    meta = runtime.read("state/meta.json")
    value = meta.get("time") if isinstance(meta, Mapping) else None
    if not isinstance(value, str) or not value:
        raise ValueError("campaign time is missing")
    return value


def _add_strain(state_doc: dict[str, Any], *, at: str, rules: Mapping[str, Any], added_milli: int, reason: str) -> dict[str, Any]:
    current = _strain_at(state_doc, at=at, rules=rules)
    maximum = max(1, int(_strain_rules(rules).get("maximum_milli", 1000) or 1000))
    current["milli"] = max(0, min(maximum, int(current["milli"]) + max(0, int(added_milli))))
    current["last_change_reason"] = str(reason)
    state_doc["mobilization_strain"] = current
    return current


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


def levy_eligibility(runtime: Any, *, state: str, location_ref: str, at: str | None = None) -> dict[str, Any]:
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
    review_at = str(at or _world_time(runtime))
    strain_snapshot = mobilization_strain_snapshot(runtime, state=state, at=review_at)
    strain_cfg = _strain_rules(rules)
    maximum = max(1, int(strain_cfg.get("maximum_milli", 1000) or 1000))
    penalty_fraction = max(0.0, min(0.95, float(strain_cfg.get("maximum_active_cap_penalty_fraction", 0.50) or 0.0))) * (int(strain_snapshot["mobilization_strain_milli"]) / maximum)
    effective_cap = max(0, int(round(total_cap * (1.0 - penalty_fraction))))
    exhaustion_equivalent = max(0, total_cap - effective_cap)
    return {
        "state": state,
        "location_ref": location_ref,
        "source_headroom": headroom,
        "local_eligible_personnel": sum(headroom.values()),
        "active_levy_personnel": active,
        "state_active_levy_cap": total_cap,
        "mobilization_strain_milli": int(strain_snapshot["mobilization_strain_milli"]),
        "civil_labor_factor_milli": int(strain_snapshot["civil_labor_factor_milli"]),
        "recent_levy_exhaustion_personnel_equivalent": exhaustion_equivalent,
        "effective_state_levy_cap_after_strain": effective_cap,
        "remaining_state_levy_cap": max(0, effective_cap - active),
        "currently_callable_personnel": max(0, min(sum(headroom.values()), effective_cap - active)),
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
    role = str(role).strip()
    if not role:
        raise ValueError("levy must be organized into an actual combat troop role")
    if role == "command_personnel" or role in FORBIDDEN_PERMANENT_SUPPORT_ROLES or role == "levy":
        raise ValueError("levy is a manpower source, not a combat/support troop role")
    rules = _rules(runtime)
    minimum = max(1, int(rules.get("minimum_call_personnel", 500)))
    if n < minimum:
        raise ValueError(f"levy call requires at least {minimum} personnel")
    state_path = f"state/states/{state}.json"
    pop_path = f"state/population/{state}.json"
    state_doc = deepcopy(runtime.read(state_path))
    if levy_ref in state_doc.get("levy_history", {}):
        raise ValueError("levy_ref has already been used")
    eligibility = levy_eligibility(runtime, state=state, location_ref=location_ref, at=at)
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
        "name": f"{state.upper()} Mobilized {role.replace('_', ' ').title()}",
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
        "doctrine_ref": None,
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
        "logistics": {"war_arrows": 0, "war_bolts": 0, "construction_material_units": 0},
        "mounts": {},
        "created_at": at,
        "temporary_levy_ref": levy_ref,
    }
    formation["doctrine_ref"] = default_formation_doctrine_ref(formation)
    formation["doctrine_behavior"] = doctrine_behavior(runtime.read, formation)
    normalize_formation_establishment(formation)
    ensure_officer_cadre(formation)
    reorganize_officer_cadre(formation, at=at, reason="levy_call")
    force["allocated_to_formations"][formation_ref] = runtime._formation_allocation_record(formation)
    validate_cohort_ledger(force)

    state_doc["treasury_silver"] = int(state_doc.get("treasury_silver", 0)) - organization_cost
    active = [x for x in _levy_refs(state_doc) if x != force_ref]
    active.append(force_ref)
    state_doc["active_levy_refs"] = active
    strain_cfg = _strain_rules(rules)
    full_cap = max(1, int(eligibility.get("state_active_levy_cap", n) or n))
    call_burden = int(round(max(0, int(strain_cfg.get("call_burden_milli_at_full_state_levy_cap", 650) or 0)) * n / full_cap))
    strain_after_call = _add_strain(state_doc, at=at, rules=rules, added_milli=call_burden, reason="state_levy_call")
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
    _compact_levy_history(state_doc)

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
        "mobilization_strain_after_call_milli": int(strain_after_call["milli"]),
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
    _compact_levy_history(state_doc)
    state_doc["active_levy_refs"] = [x for x in _levy_refs(state_doc) if x != force_ref]
    rules = _rules(runtime)
    strain_cfg = _strain_rules(rules)
    population_total = max(1, int(pop.get("population_total", 1) or 1))
    full_cap = max(1, int(population_total * max(0.0, float(rules.get("maximum_active_fraction_of_total_population", 0.08)))))
    casualties = max(0, int(rec.get("casualties_or_missing", 0) or 0))
    casualty_burden = int(round(max(0, int(strain_cfg.get("casualty_burden_milli_at_full_state_levy_cap", 450) or 0)) * casualties / full_cap))
    strain_after_demobilization = _add_strain(state_doc, at=at, rules=rules, added_milli=casualty_burden, reason="state_levy_demobilization")

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
        "mobilization_strain_after_demobilization_milli": int(strain_after_demobilization["milli"]),
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
