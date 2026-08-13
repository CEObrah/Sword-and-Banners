"""Conserved aggregate cohort mechanics for every force owner.

The force document remains the headcount/material authority. ``cohort_ledger`` is
an exact decomposition of that headcount into provenance/development cohorts; it
may never create or delete people independently of the force counters.

Ordinary soldiers do not receive persistent per-person identities. Cohorts keep
source provenance, age/aptitude/capability distributions, verified training and
service evidence, and formation allocations. Exact people are materialized only
by an explicit higher-fidelity transaction (named/relevant people or a player's
true personal recruit), and that transaction must debit one conserved body.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from statistics import NormalDist
from typing import Any

ATTRIBUTE_ORDER: tuple[str, ...] = (
    "Strength", "Agility", "Endurance", "Toughness", "Coordination",
    "Awareness", "Composure", "Intelligence", "Presence",
)
SKILL_ORDER: tuple[str, ...] = (
    "Sword", "Spear", "Glaive", "Axe", "Mace", "Staff", "Dagger", "Bow",
    "Crossbow", "Shield", "Defense", "Athletics", "Mass Combat", "Grappling",
    "Unarmed", "Riding", "Formation Fighting", "Survival", "Stealth",
    "Scouting", "Navigation", "Medicine", "Engineering", "Leadership",
    "Formation Command", "Tactics", "Strategy", "Logistics",
    "Intelligence Operations", "Training", "Diplomacy", "Law", "Trade",
    "Intrigue", "Governance",
)
PHYSICAL_SKILLS = {
    "Athletics", "Axe", "Bow", "Crossbow", "Dagger", "Defense", "Glaive",
    "Grappling", "Mace", "Riding", "Shield", "Spear", "Staff", "Stealth",
    "Survival", "Sword", "Unarmed", "Formation Fighting",
}
TACTICAL_SKILLS = {
    "Formation Command", "Leadership", "Logistics", "Mass Combat", "Strategy",
    "Tactics", "Intelligence Operations", "Training",
}
TECHNICAL_SKILLS = {"Engineering", "Medicine", "Navigation", "Scouting"}
SOCIAL_SKILLS = {"Diplomacy", "Intrigue", "Trade"}


def _stable_u64(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def stable_fraction(*parts: object) -> float:
    return _stable_u64(*parts) / float(1 << 64)


def _slug(value: object) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value))
    return "_".join(part for part in out.split("_") if part) or "unknown"


def _cohort_id(force: Mapping[str, Any], *parts: object) -> str:
    owner = _slug(force.get("owner_id", "force"))
    digest = hashlib.sha256("|".join(str(x) for x in parts).encode("utf-8")).hexdigest()[:12]
    return f"cohort_{owner}_{digest}"


def role_count(force: Mapping[str, Any], role: str) -> int:
    roles = force.get("available_by_role", {})
    return int(roles.get(role, 0)) if isinstance(roles, Mapping) else 0


def _allocation_count(value: Any) -> int:
    if isinstance(value, Mapping):
        return int(value.get("personnel", 0))
    return int(value)


def _allocation_role(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("role", "unknown"))
    return "unknown"


def ensure_cohort_ledger(force: MutableMapping[str, Any], *, at: str | None = None) -> dict[str, Any]:
    """Ensure one cohort ledger whose totals exactly decompose force manpower.

    Pre-feature manpower is deliberately marked ``legacy_baseline`` with unknown
    demographic origin rather than inventing recruitment history. New cohorts
    are created only by explicit recruitment/promotion/transfer code.
    """

    ledger = force.setdefault("cohort_ledger", {})
    ledger.setdefault("schema", "force-cohort-ledger.v1")
    ledger.setdefault("representation", "aggregate_provenance_cohorts")
    ledger.setdefault(
        "individualization_policy",
        "anonymous cohorts remain aggregate; exact people require an explicit conserved-body materialization transaction",
    )
    cohorts = ledger.setdefault("cohorts", {})
    if cohorts:
        return ledger

    source_loc = str(force.get("source_location_ref", "unknown"))
    by_loc = force.get("available_by_location", {})
    if isinstance(by_loc, Mapping) and by_loc:
        for location_ref in sorted(by_loc):
            pool = by_loc.get(location_ref, {})
            if not isinstance(pool, Mapping):
                continue
            for role in sorted(pool):
                count = max(0, int(pool.get(role, 0)))
                if not count:
                    continue
                cid = _cohort_id(force, "legacy_reserve", location_ref, role)
                cohorts[cid] = _legacy_cohort(cid, role, count, location_ref, at)
    else:
        for role in sorted(force.get("available_by_role", {})):
            count = max(0, int(force.get("available_by_role", {}).get(role, 0)))
            if count:
                cid = _cohort_id(force, "legacy_reserve", source_loc, role)
                cohorts[cid] = _legacy_cohort(cid, role, count, source_loc, at)

    for formation_ref, allocation in sorted(force.get("allocated_to_formations", {}).items()):
        count = max(0, _allocation_count(allocation))
        if not count:
            continue
        role = _allocation_role(allocation)
        cid = _cohort_id(force, "legacy_allocation", formation_ref, role)
        cohorts[cid] = _legacy_cohort(cid, role, 0, None, at)
        cohorts[cid]["allocated_by_formation"] = {str(formation_ref): count}
        cohorts[cid]["origin"]["kind"] = "legacy_pre_cohort_formation"

    ledger["last_reconciled_at"] = at
    validate_cohort_ledger(force)
    return ledger


def _legacy_cohort(cid: str, role: str, reserve: int, location_ref: str | None, at: str | None) -> dict[str, Any]:
    return {
        "cohort_id": cid,
        "role": str(role),
        "origin": {
            "kind": "legacy_baseline",
            "population_ref": None,
            "source_stratum": None,
            "source_location_ref": location_ref,
            "recruited_at": None,
            "migration_recorded_at": at,
            "provenance_note": "pre-cohort personnel preserved without fabricating earlier recruitment ancestry",
        },
        "reserve_by_location": ({str(location_ref): int(reserve)} if location_ref and reserve else {}),
        "allocated_by_formation": {},
        "age_distribution": {},
        "aptitude_means": {},
        "attribute_means": {},
        "attribute_sd": {},
        "skill_means": {},
        "skill_sd": {},
        "skill_edu_banks": {},
        "attribute_edu_banks": {},
        "service_months_mean": 0.0,
        "verified_training_hours_per_person": 0.0,
        "verified_role_exposure_hours_per_person": 0.0,
        "training_history": [],
        "tags": ["legacy_baseline", "quality_not_reconstructed"],
    }


def validate_cohort_ledger(force: Mapping[str, Any]) -> None:
    ledger = force.get("cohort_ledger")
    if not isinstance(ledger, Mapping):
        return
    cohorts = ledger.get("cohorts", {})
    if not isinstance(cohorts, Mapping):
        raise ValueError("force cohort ledger cohorts must be an object")

    total = 0
    reserve_by_role: dict[str, int] = {}
    allocations: dict[str, int] = {}
    for cid, cohort in cohorts.items():
        if not isinstance(cohort, Mapping):
            raise ValueError(f"invalid cohort record: {cid}")
        role = str(cohort.get("role", "unknown"))
        reserve = sum(max(0, int(v)) for v in cohort.get("reserve_by_location", {}).values())
        allocated = sum(max(0, int(v)) for v in cohort.get("allocated_by_formation", {}).values())
        total += reserve + allocated
        reserve_by_role[role] = reserve_by_role.get(role, 0) + reserve
        for ref, value in cohort.get("allocated_by_formation", {}).items():
            allocations[str(ref)] = allocations.get(str(ref), 0) + max(0, int(value))

    materialized = sum(
        int(v.get("personnel", 1)) if isinstance(v, Mapping) else int(v)
        for v in force.get("materialized_people", {}).values()
    )
    if total + materialized != int(force.get("headcount", -1)):
        raise ValueError("cohort ledger does not conserve force headcount")

    top_reserve = {str(k): int(v) for k, v in force.get("available_by_role", {}).items()}
    for role, value in top_reserve.items():
        if reserve_by_role.get(role, 0) != value:
            raise ValueError(f"cohort reserve mismatch for role {role}")
    for role, value in reserve_by_role.items():
        if value and top_reserve.get(role, 0) != value:
            raise ValueError(f"cohort ledger has unknown reserve role {role}")

    top_alloc = {str(k): _allocation_count(v) for k, v in force.get("allocated_to_formations", {}).items()}
    if allocations != top_alloc:
        raise ValueError("cohort formation allocation mismatch")


def _profile_for_source(registry: Mapping[str, Any], source_stratum: str) -> Mapping[str, Any]:
    profiles = registry.get("source_profiles", {})
    if isinstance(profiles, Mapping) and isinstance(profiles.get(source_stratum), Mapping):
        return profiles[source_stratum]
    if isinstance(profiles, Mapping) and isinstance(profiles.get("civilian_common"), Mapping):
        return profiles["civilian_common"]
    return {}


def _mean_map(profile: Mapping[str, Any], key: str) -> dict[str, float]:
    value = profile.get(key, {})
    return {str(k): float(v) for k, v in value.items()} if isinstance(value, Mapping) else {}


def record_recruitment_cohort(
    force: MutableMapping[str, Any],
    *,
    role: str,
    count: int,
    location_ref: str,
    source_population_ref: str,
    source_stratum: str,
    recruited_at: str,
    profile_registry: Mapping[str, Any],
    selection_profile: str | None = None,
    provenance_ref: str | None = None,
) -> str | None:
    """Add provenance for bodies already added to top-level force counters."""

    n = max(0, int(count))
    if n <= 0:
        return None
    ledger = ensure_cohort_ledger(force, at=recruited_at)
    source = deepcopy(dict(_profile_for_source(profile_registry, source_stratum)))
    if selection_profile:
        selections = profile_registry.get("selection_profiles", {})
        overlay = selections.get(selection_profile, {}) if isinstance(selections, Mapping) else {}
        if isinstance(overlay, Mapping):
            _apply_profile_overlay(source, overlay)
    cid = _cohort_id(force, "recruit", recruited_at, source_population_ref, source_stratum, role, provenance_ref or "")
    if cid in ledger["cohorts"]:
        suffix = 2
        base = cid
        while cid in ledger["cohorts"]:
            cid = f"{base}_{suffix}"
            suffix += 1
    age = source.get("age_distribution", {}) if isinstance(source.get("age_distribution"), Mapping) else {}
    cohort = {
        "cohort_id": cid,
        "role": str(role),
        "origin": {
            "kind": "recruitment",
            "population_ref": str(source_population_ref),
            "source_stratum": str(source_stratum),
            "source_location_ref": str(location_ref),
            "recruited_at": str(recruited_at),
            "selection_profile": selection_profile,
            "provenance_ref": provenance_ref,
        },
        "reserve_by_location": {str(location_ref): n},
        "allocated_by_formation": {},
        "age_distribution": deepcopy(dict(age)),
        "aptitude_means": _mean_map(source, "aptitude_means"),
        "attribute_means": _mean_map(source, "attribute_means"),
        "attribute_sd": _mean_map(source, "attribute_sd"),
        "skill_means": _mean_map(source, "skill_means"),
        "skill_sd": _mean_map(source, "skill_sd"),
        "skill_edu_banks": {},
        "attribute_edu_banks": {},
        "service_months_mean": 0.0,
        "verified_training_hours_per_person": 0.0,
        "verified_role_exposure_hours_per_person": 0.0,
        "training_history": [],
        "correlation_groups": deepcopy(source.get("correlation_groups", [])),
        "tags": ["prospective_recruitment", str(source_stratum)],
    }
    ledger["cohorts"][cid] = cohort
    validate_cohort_ledger(force)
    return cid


def _apply_profile_overlay(profile: MutableMapping[str, Any], overlay: Mapping[str, Any]) -> None:
    for key in ("attribute_means", "skill_means", "aptitude_means"):
        base = profile.setdefault(key, {})
        add = overlay.get(key, {})
        if isinstance(base, MutableMapping) and isinstance(add, Mapping):
            for metric, delta in add.items():
                base[str(metric)] = float(base.get(str(metric), 0.0)) + float(delta)
    for key in ("attribute_sd", "skill_sd"):
        if isinstance(overlay.get(key), Mapping):
            profile[key] = deepcopy(dict(overlay[key]))
    if isinstance(overlay.get("age_distribution"), Mapping):
        profile["age_distribution"] = deepcopy(dict(overlay["age_distribution"]))
    if isinstance(overlay.get("correlation_groups"), Sequence) and not isinstance(overlay.get("correlation_groups"), (str, bytes)):
        profile["correlation_groups"] = deepcopy(list(overlay["correlation_groups"]))


def consume_population_recruits(
    population: MutableMapping[str, Any],
    count: int,
    *,
    source_roles: Sequence[str],
    destination_role: str = "private_household_military",
) -> tuple[int, dict[str, int]]:
    """Move real people between population strata and return exact source mix."""

    remaining = max(0, int(count))
    strata = population.setdefault("strata", {})
    moved = 0
    source_mix: dict[str, int] = {}
    for source in source_roles:
        if remaining <= 0:
            break
        available = max(0, int(strata.get(source, 0)))
        take = min(remaining, available)
        if take:
            strata[source] = available - take
            source_mix[str(source)] = take
            moved += take
            remaining -= take
    if moved:
        strata[destination_role] = int(strata.get(destination_role, 0)) + moved
    return moved, source_mix


def add_recruits(force: MutableMapping[str, Any], role: str, count: int, *, location_ref: str) -> int:
    """Add bodies already conserved by a population transfer to top-level force counters."""

    added = max(0, int(count))
    if added <= 0:
        return 0
    roles = force.setdefault("available_by_role", {})
    roles[role] = int(roles.get(role, 0)) + added
    loc = force.setdefault("available_by_location", {}).setdefault(location_ref, {})
    loc[role] = int(loc.get(role, 0)) + added
    force["headcount"] = int(force.get("headcount", 0)) + added
    force["authorized_strength"] = max(int(force.get("authorized_strength", 0)), int(force["headcount"]))
    return added


def _cohort_total(cohort: Mapping[str, Any]) -> int:
    return sum(int(v) for v in cohort.get("reserve_by_location", {}).values()) + sum(
        int(v) for v in cohort.get("allocated_by_formation", {}).values()
    )


def take_reserve_slices(
    force: MutableMapping[str, Any],
    *,
    role: str,
    count: int,
    location_ref: str,
    formation_ref: str,
) -> list[dict[str, Any]]:
    """Move reserve cohort slices into one formation, FIFO by intake/provenance id."""

    remaining = max(0, int(count))
    if remaining <= 0:
        return []
    ledger = ensure_cohort_ledger(force)
    candidates: list[tuple[str, MutableMapping[str, Any]]] = []
    for cid, raw in ledger["cohorts"].items():
        if not isinstance(raw, MutableMapping) or str(raw.get("role")) != str(role):
            continue
        if int(raw.get("reserve_by_location", {}).get(location_ref, 0)) <= 0:
            continue
        candidates.append((str(cid), raw))
    candidates.sort(key=lambda x: (str(x[1].get("origin", {}).get("recruited_at") or ""), x[0]))
    slices: list[dict[str, Any]] = []
    for cid, cohort in candidates:
        if remaining <= 0:
            break
        reserve = cohort.setdefault("reserve_by_location", {})
        available = max(0, int(reserve.get(location_ref, 0)))
        take = min(remaining, available)
        if not take:
            continue
        reserve[location_ref] = available - take
        if reserve[location_ref] == 0:
            reserve.pop(location_ref, None)
        allocated = cohort.setdefault("allocated_by_formation", {})
        allocated[formation_ref] = int(allocated.get(formation_ref, 0)) + take
        slices.append({"cohort_id": cid, "count": take})
        remaining -= take
    if remaining:
        raise ValueError("cohort ledger lacks the conserved reserve bodies taken by formation reducer")
    validate_cohort_ledger(force)
    return slices


def ensure_formation_composition(
    force: MutableMapping[str, Any],
    formation: MutableMapping[str, Any],
    *,
    at: str | None = None,
) -> list[dict[str, Any]]:
    """Attach a pre-feature allocation to its deterministic legacy cohort."""

    existing = formation.get("cohort_composition")
    if isinstance(existing, Sequence) and not isinstance(existing, (str, bytes)) and existing:
        return [deepcopy(dict(x)) for x in existing if isinstance(x, Mapping)]
    ledger = ensure_cohort_ledger(force, at=at)
    ref = str(formation.get("formation_ref"))
    expected = int(formation.get("personnel", 0))
    slices: list[dict[str, Any]] = []
    for cid, cohort in ledger["cohorts"].items():
        count = int(cohort.get("allocated_by_formation", {}).get(ref, 0))
        if count:
            slices.append({"cohort_id": str(cid), "count": count})
    if sum(int(x["count"]) for x in slices) != expected:
        raise ValueError("formation cohort allocation does not match formation personnel")
    formation["cohort_composition"] = slices
    return slices


def append_formation_slices(formation: MutableMapping[str, Any], slices: Sequence[Mapping[str, Any]]) -> None:
    current: dict[str, int] = {}
    for item in formation.get("cohort_composition", []):
        if isinstance(item, Mapping):
            current[str(item.get("cohort_id"))] = current.get(str(item.get("cohort_id")), 0) + int(item.get("count", 0))
    for item in slices:
        cid = str(item.get("cohort_id"))
        current[cid] = current.get(cid, 0) + int(item.get("count", 0))
    formation["cohort_composition"] = [
        {"cohort_id": cid, "count": count} for cid, count in sorted(current.items()) if count > 0
    ]


def return_formation_slices(force: MutableMapping[str, Any], formation: Mapping[str, Any]) -> None:
    ledger = ensure_cohort_ledger(force)
    ref = str(formation.get("formation_ref"))
    location = str(formation.get("location_ref"))
    for item in formation.get("cohort_composition", []):
        if not isinstance(item, Mapping):
            continue
        cid = str(item.get("cohort_id"))
        count = max(0, int(item.get("count", 0)))
        cohort = ledger["cohorts"].get(cid)
        if not isinstance(cohort, MutableMapping):
            raise ValueError("formation references unknown force cohort")
        allocated = cohort.setdefault("allocated_by_formation", {})
        held = max(0, int(allocated.get(ref, 0)))
        if held < count:
            raise ValueError("formation cohort return exceeds conserved allocation")
        if held == count:
            allocated.pop(ref, None)
        else:
            allocated[ref] = held - count
        reserve = cohort.setdefault("reserve_by_location", {})
        reserve[location] = int(reserve.get(location, 0)) + count
    validate_cohort_ledger(force)


def partition_formation_slices(
    force: MutableMapping[str, Any],
    source: MutableMapping[str, Any],
    child: MutableMapping[str, Any],
    child_count: int,
) -> None:
    """Deterministically split cohort slices without creating identities."""

    ensure_formation_composition(force, source)
    total = int(source.get("personnel", 0)) + int(child_count)
    if total <= 0:
        raise ValueError("cannot partition empty formation cohorts")
    target = max(0, int(child_count))
    raw = [deepcopy(dict(x)) for x in source.get("cohort_composition", []) if isinstance(x, Mapping)]
    allocations: list[tuple[str, int, float]] = []
    assigned = 0
    for item in raw:
        cid = str(item["cohort_id"])
        count = int(item["count"])
        exact = count * target / total
        base = int(math.floor(exact))
        allocations.append((cid, base, exact - base))
        assigned += base
    remainder = target - assigned
    allocations.sort(key=lambda x: (-x[2], x[0]))
    child_map = {cid: base for cid, base, _ in allocations}
    for cid, _, _ in allocations[:remainder]:
        child_map[cid] += 1
    parent_map = {str(x["cohort_id"]): int(x["count"]) - child_map.get(str(x["cohort_id"]), 0) for x in raw}
    src_ref = str(source.get("formation_ref")); child_ref = str(child.get("formation_ref"))
    ledger = ensure_cohort_ledger(force)
    for cid, moved in child_map.items():
        cohort = ledger["cohorts"].get(cid)
        if not isinstance(cohort, MutableMapping):
            raise ValueError("unknown split cohort")
        allocated = cohort.setdefault("allocated_by_formation", {})
        held = int(allocated.get(src_ref, 0))
        if moved > held:
            raise ValueError("split cohort exceeds source allocation")
        allocated[src_ref] = held - moved
        if allocated[src_ref] == 0:
            allocated.pop(src_ref, None)
        if moved:
            allocated[child_ref] = int(allocated.get(child_ref, 0)) + moved
    source["cohort_composition"] = [{"cohort_id": cid, "count": n} for cid, n in sorted(parent_map.items()) if n > 0]
    child["cohort_composition"] = [{"cohort_id": cid, "count": n} for cid, n in sorted(child_map.items()) if n > 0]
    validate_cohort_ledger(force)


def merge_formation_slices(
    force: MutableMapping[str, Any],
    primary: MutableMapping[str, Any],
    secondaries: Sequence[Mapping[str, Any]],
) -> None:
    ensure_formation_composition(force, primary)
    ledger = ensure_cohort_ledger(force)
    primary_ref = str(primary.get("formation_ref"))
    merged: dict[str, int] = {str(x["cohort_id"]): int(x["count"]) for x in primary.get("cohort_composition", []) if isinstance(x, Mapping)}
    for secondary in secondaries:
        secondary_ref = str(secondary.get("formation_ref"))
        for item in secondary.get("cohort_composition", []):
            if not isinstance(item, Mapping):
                continue
            cid = str(item.get("cohort_id")); count = int(item.get("count", 0))
            cohort = ledger["cohorts"].get(cid)
            if not isinstance(cohort, MutableMapping):
                raise ValueError("unknown merge cohort")
            allocated = cohort.setdefault("allocated_by_formation", {})
            held = int(allocated.get(secondary_ref, 0))
            if held != count:
                raise ValueError("secondary cohort allocation mismatch during merge")
            allocated.pop(secondary_ref, None)
            allocated[primary_ref] = int(allocated.get(primary_ref, 0)) + count
            merged[cid] = merged.get(cid, 0) + count
    primary["cohort_composition"] = [{"cohort_id": cid, "count": n} for cid, n in sorted(merged.items()) if n > 0]
    validate_cohort_ledger(force)


def trim_formation_to_personnel(
    force: MutableMapping[str, Any],
    formation: MutableMapping[str, Any],
    *,
    old_personnel: int,
    new_personnel: int,
    casualty_ref: str,
) -> dict[str, int]:
    """Apply aggregate casualties proportionally and remove bodies from the ledger.

    The battle reducer already owns the top-level casualty result. This helper
    only decomposes that result across cohorts and therefore must be called after
    the reducer has updated force/formation counts.
    """

    losses = max(0, int(old_personnel) - int(new_personnel))
    if losses <= 0:
        return {}
    ensure_formation_composition(force, formation)
    items = [deepcopy(dict(x)) for x in formation.get("cohort_composition", []) if isinstance(x, Mapping)]
    total = sum(int(x["count"]) for x in items)
    if total != int(old_personnel):
        raise ValueError("pre-casualty cohort total mismatch")
    assigned = 0
    rows: list[tuple[str, int, int, float]] = []
    for item in items:
        cid = str(item["cohort_id"]); count = int(item["count"])
        exact = count * losses / max(1, old_personnel)
        base = min(count, int(math.floor(exact)))
        rows.append((cid, count, base, exact - base)); assigned += base
    remainder = losses - assigned
    rows.sort(key=lambda row: (-row[3], _stable_u64(casualty_ref, row[0])))
    loss_map = {cid: base for cid, _, base, _ in rows}
    for cid, count, _, _ in rows:
        if remainder <= 0:
            break
        if loss_map[cid] < count:
            loss_map[cid] += 1; remainder -= 1
    ref = str(formation.get("formation_ref")); ledger = ensure_cohort_ledger(force)
    survivors: list[dict[str, Any]] = []
    for cid, count, _, _ in rows:
        lost = loss_map.get(cid, 0); remain = count - lost
        cohort = ledger["cohorts"].get(cid)
        if not isinstance(cohort, MutableMapping):
            raise ValueError("unknown casualty cohort")
        allocated = cohort.setdefault("allocated_by_formation", {})
        held = int(allocated.get(ref, 0))
        if held < lost:
            raise ValueError("cohort casualty exceeds allocation")
        new_held = held - lost
        if new_held:
            allocated[ref] = new_held
        else:
            allocated.pop(ref, None)
        cohort.setdefault("casualty_history", []).append({"ref": casualty_ref, "count": lost})
        cohort["casualty_history"] = cohort["casualty_history"][-24:]
        if remain:
            survivors.append({"cohort_id": cid, "count": remain})
    formation["cohort_composition"] = sorted(survivors, key=lambda x: x["cohort_id"])
    return loss_map


def transfer_role(
    force: MutableMapping[str, Any],
    source_role: str,
    destination_role: str,
    count: int,
    *,
    location_ref: str,
    evidence_ref: str | None = None,
) -> int:
    """Move qualified aggregate slices to another role while preserving provenance."""

    requested = max(0, int(count))
    available = role_count(force, source_role)
    moved = min(requested, available)
    if moved <= 0:
        return 0
    ledger = ensure_cohort_ledger(force)
    remaining = moved
    eligible: list[tuple[str, MutableMapping[str, Any]]] = []
    for cid, cohort in ledger["cohorts"].items():
        if not isinstance(cohort, MutableMapping) or str(cohort.get("role")) != source_role:
            continue
        if int(cohort.get("reserve_by_location", {}).get(location_ref, 0)) > 0:
            eligible.append((str(cid), cohort))
    eligible.sort(key=lambda x: (str(x[1].get("origin", {}).get("recruited_at") or ""), x[0]))
    created: list[dict[str, Any]] = []
    for cid, cohort in eligible:
        if remaining <= 0:
            break
        reserve = cohort.setdefault("reserve_by_location", {})
        take = min(remaining, int(reserve.get(location_ref, 0)))
        if not take:
            continue
        reserve[location_ref] = int(reserve.get(location_ref, 0)) - take
        if reserve[location_ref] == 0:
            reserve.pop(location_ref, None)
        promoted = deepcopy(cohort)
        promoted_id = _cohort_id(force, "promotion", cid, destination_role, evidence_ref or "", _cohort_total(cohort), take)
        promoted["cohort_id"] = promoted_id
        promoted["role"] = destination_role
        promoted["reserve_by_location"] = {location_ref: take}
        promoted["allocated_by_formation"] = {}
        promoted["service_months_mean"] = 0.0
        promoted.setdefault("promotion_history", []).append({"from_cohort_id": cid, "from_role": source_role, "to_role": destination_role, "count": take, "evidence_ref": evidence_ref})
        promoted["promotion_history"] = promoted["promotion_history"][-24:]
        promoted.setdefault("tags", []).append(f"promoted_from:{source_role}")
        created.append(promoted)
        remaining -= take
    if remaining:
        raise ValueError("cohort ledger lacks promotable reserve bodies")
    roles = force.setdefault("available_by_role", {})
    roles[source_role] = int(roles.get(source_role, 0)) - moved
    roles[destination_role] = int(roles.get(destination_role, 0)) + moved
    loc = force.setdefault("available_by_location", {}).setdefault(location_ref, {})
    loc[source_role] = int(loc.get(source_role, 0)) - moved
    loc[destination_role] = int(loc.get(destination_role, 0)) + moved
    for promoted in created:
        ledger["cohorts"][promoted["cohort_id"]] = promoted
    validate_cohort_ledger(force)
    return moved


def transfer_between_forces(
    source_force: MutableMapping[str, Any],
    destination_force: MutableMapping[str, Any],
    *,
    source_role: str,
    destination_role: str,
    count: int,
    source_location_ref: str,
    destination_location_ref: str,
    evidence_ref: str,
) -> int:
    """Transfer whole aggregate cohort slices between force owners without cloning."""

    requested = min(max(0, int(count)), role_count(source_force, source_role))
    if requested <= 0:
        return 0
    src_ledger = ensure_cohort_ledger(source_force)
    dst_ledger = ensure_cohort_ledger(destination_force)
    remaining = requested
    moved_rows: list[dict[str, Any]] = []
    rows = [(str(cid), cohort) for cid, cohort in src_ledger["cohorts"].items() if isinstance(cohort, MutableMapping) and str(cohort.get("role")) == source_role and int(cohort.get("reserve_by_location", {}).get(source_location_ref, 0)) > 0]
    rows.sort(key=lambda x: (str(x[1].get("origin", {}).get("recruited_at") or ""), x[0]))
    for cid, cohort in rows:
        if remaining <= 0:
            break
        reserve = cohort.setdefault("reserve_by_location", {})
        take = min(remaining, int(reserve.get(source_location_ref, 0)))
        if not take:
            continue
        reserve[source_location_ref] = int(reserve.get(source_location_ref, 0)) - take
        if reserve[source_location_ref] == 0:
            reserve.pop(source_location_ref, None)
        moved = deepcopy(cohort)
        moved_id = _cohort_id(destination_force, "cross_force", cid, destination_role, evidence_ref)
        moved["cohort_id"] = moved_id
        moved["role"] = destination_role
        moved["reserve_by_location"] = {destination_location_ref: take}
        moved["allocated_by_formation"] = {}
        moved["service_months_mean"] = 0.0
        moved.setdefault("transfer_history", []).append({"from_force": source_force.get("owner_id"), "from_cohort_id": cid, "from_role": source_role, "to_force": destination_force.get("owner_id"), "to_role": destination_role, "count": take, "evidence_ref": evidence_ref})
        moved["transfer_history"] = moved["transfer_history"][-24:]
        moved_rows.append(moved)
        remaining -= take
    if remaining:
        raise ValueError("source cohort ledger lacks transfer bodies")

    src_roles = source_force.setdefault("available_by_role", {})
    src_roles[source_role] = int(src_roles.get(source_role, 0)) - requested
    src_loc = source_force.setdefault("available_by_location", {}).setdefault(source_location_ref, {})
    src_loc[source_role] = int(src_loc.get(source_role, 0)) - requested
    source_force["headcount"] = int(source_force.get("headcount", 0)) - requested

    dst_roles = destination_force.setdefault("available_by_role", {})
    dst_roles[destination_role] = int(dst_roles.get(destination_role, 0)) + requested
    dst_loc = destination_force.setdefault("available_by_location", {}).setdefault(destination_location_ref, {})
    dst_loc[destination_role] = int(dst_loc.get(destination_role, 0)) + requested
    destination_force["headcount"] = int(destination_force.get("headcount", 0)) + requested
    destination_force["authorized_strength"] = max(int(destination_force.get("authorized_strength", 0)), int(destination_force["headcount"]))
    for moved in moved_rows:
        dst_ledger["cohorts"][moved["cohort_id"]] = moved
    validate_cohort_ledger(source_force)
    validate_cohort_ledger(destination_force)
    return requested


def _aptitude_key(skill: str) -> str:
    if skill in PHYSICAL_SKILLS:
        return "physical_learning"
    if skill in TACTICAL_SKILLS:
        return "tactical_learning"
    if skill in TECHNICAL_SKILLS:
        return "technical_learning"
    if skill in SOCIAL_SKILLS:
        return "social_learning"
    return "academic_learning"


def _potential(aptitude: float) -> tuple[str, float]:
    if aptitude >= 190: return "legendary", 1.36
    if aptitude >= 175: return "heroic", 1.24
    if aptitude >= 150: return "exceptional", 1.12
    if aptitude >= 120: return "capable", 1.0
    return "common", 0.9


def _age_factor(training: Mapping[str, Any], category: str, age: float) -> float:
    for row in training.get("age_factors", {}).get(category, []):
        max_age = row.get("max_age")
        hi = 999 if max_age is None else float(max_age)
        if float(row.get("min_age", 0)) <= age <= hi:
            return float(row.get("factor", 1.0))
    return 1.0


def _advance_score_mean(
    current: float,
    bank: float,
    raw_edu: float,
    *,
    aptitude: float,
    potential_ceilings: Mapping[str, Any],
    kind: str,
) -> tuple[float, float]:
    potential_name, potential_factor = _potential(aptitude)
    ceiling = float(potential_ceilings.get(kind, {}).get(potential_name, 100))
    score = float(current)
    if score <= ceiling - 20:
        diminishing = 1.0
    elif score <= ceiling:
        diminishing = 1.0 - (score - (ceiling - 20)) * (0.55 / 20.0)
    elif score <= ceiling + 20:
        diminishing = 0.45 - (score - ceiling) * (0.35 / 20.0)
    else:
        diminishing = 0.05
    edu = bank + max(0.0, raw_edu * max(0.05, diminishing) * potential_factor)
    exponent = 1.75 if kind == "skill" else 2.10
    base_cost = 18.0 if kind == "skill" else 120.0
    gained = 0
    while gained < 25:
        cost = base_cost * ((1.0 + score / 50.0) ** exponent)
        if edu + 1e-9 < cost:
            break
        edu -= cost
        score += 1.0
        gained += 1
    return round(score, 3), round(edu, 3)


def advance_cohort_training(
    cohort: MutableMapping[str, Any],
    *,
    deliberate_hours: float,
    role_exposure_hours: float,
    skill_focuses: Sequence[str],
    attribute_focuses: Sequence[str],
    training_rules: Mapping[str, Any],
    facility_grade: str = "adequate",
    equipment_grade: str = "adequate",
    recovery_grade: str = "adequate",
    practice_mode: str = "drill",
    evidence_ref: str,
) -> dict[str, Any]:
    """Advance aggregate means under the same EDU/cost law as exact people."""

    deliberate = max(0.0, float(deliberate_hours))
    exposure = max(0.0, float(role_exposure_hours))
    if deliberate <= 0 and exposure <= 0:
        return {"deliberate_hours": 0.0, "role_exposure_hours": 0.0}
    factors = training_rules.get("factor_tables", {})
    facility = float(factors.get("facility", {}).get(facility_grade, 1.0))
    equipment = float(factors.get("equipment", {}).get(equipment_grade, 0.92))
    recovery = float(factors.get("recovery", {}).get(recovery_grade, 0.92))
    mode = float(factors.get("practice_mode", {}).get(practice_mode, 0.95))
    field = float(factors.get("practice_mode", {}).get("field_practice", 1.0))
    share_skill = float(training_rules.get("share_limits", {}).get("skill", 1.0))
    share_attr = float(training_rules.get("share_limits", {}).get("attribute_stimulus", 0.35))
    age = float(cohort.get("age_distribution", {}).get("mean", 25.0))
    aptitude = cohort.setdefault("aptitude_means", {})
    skill_means = cohort.setdefault("skill_means", {})
    skill_banks = cohort.setdefault("skill_edu_banks", {})
    attr_means = cohort.setdefault("attribute_means", {})
    attr_banks = cohort.setdefault("attribute_edu_banks", {})
    ceilings = training_rules.get("potential_soft_ceilings", {})

    focuses = [str(x) for x in skill_focuses if str(x)]
    if focuses:
        hours_each = (deliberate * share_skill + exposure * 0.55) / len(focuses)
        for skill in focuses:
            score = float(skill_means.get(skill, 0.0))
            apt = float(aptitude.get(_aptitude_key(skill), 100.0))
            age_category = "physical_or_martial_skill" if skill in PHYSICAL_SKILLS else ("command_or_civil_skill" if skill in TACTICAL_SKILLS or skill in SOCIAL_SKILLS else "mental_skill")
            age_f = _age_factor(training_rules, age_category, age)
            apt_f = max(0.25, min(2.0, apt / 100.0))
            raw = hours_each * facility * equipment * recovery * age_f * apt_f * ((mode + field) / 2.0)
            new_score, new_bank = _advance_score_mean(score, float(skill_banks.get(skill, 0.0)), raw, aptitude=apt, potential_ceilings=ceilings, kind="skill")
            skill_means[skill] = new_score; skill_banks[skill] = new_bank

    attrs = [str(x) for x in attribute_focuses if str(x)]
    if attrs:
        hours_each = (deliberate * share_attr + exposure * 0.20) / len(attrs)
        apt = float(aptitude.get("physical_learning", 100.0))
        age_f = _age_factor(training_rules, "physical_attribute", age)
        apt_f = max(0.25, min(2.0, apt / 100.0))
        for attribute in attrs:
            score = float(attr_means.get(attribute, 0.0))
            raw = hours_each * facility * equipment * recovery * age_f * apt_f * ((mode + field) / 2.0)
            new_score, new_bank = _advance_score_mean(score, float(attr_banks.get(attribute, 0.0)), raw, aptitude=apt, potential_ceilings=ceilings, kind="attribute")
            attr_means[attribute] = new_score; attr_banks[attribute] = new_bank

    cohort["verified_training_hours_per_person"] = round(float(cohort.get("verified_training_hours_per_person", 0.0)) + deliberate, 3)
    cohort["verified_role_exposure_hours_per_person"] = round(float(cohort.get("verified_role_exposure_hours_per_person", 0.0)) + exposure, 3)
    cohort.setdefault("training_history", []).append({
        "evidence_ref": evidence_ref,
        "deliberate_hours": round(deliberate, 3),
        "role_exposure_hours": round(exposure, 3),
        "skill_focuses": focuses,
        "attribute_focuses": attrs,
        "facility_grade": facility_grade,
        "equipment_grade": equipment_grade,
        "recovery_grade": recovery_grade,
    })
    cohort["training_history"] = cohort["training_history"][-24:]
    return {"deliberate_hours": round(deliberate, 3), "role_exposure_hours": round(exposure, 3)}


def advance_service_months(cohort: MutableMapping[str, Any], months: float) -> None:
    cohort["service_months_mean"] = round(float(cohort.get("service_months_mean", 0.0)) + max(0.0, float(months)), 3)
    age = cohort.setdefault("age_distribution", {})
    if "mean" in age:
        age["mean"] = round(float(age.get("mean", 25.0)) + max(0.0, float(months)) / 12.0, 3)


def qualification_capacity(
    cohort: Mapping[str, Any],
    *,
    minimum_attribute_values: Sequence[int] | None = None,
    minimum_skill_values: Sequence[int] | None = None,
    minimum_service_months: float = 0.0,
    available_count: int | None = None,
) -> int:
    """Estimate a positively-correlated qualifying tail without minting people.

    Cohorts retain distributions rather than exact anonymous identities. For an
    all-gates qualification we use the tightest marginal tail as the maximum
    correlated intersection. Promotions then move that many conserved bodies;
    named materialization, if later needed, occurs only after the transfer.
    """

    count = max(0, int(_cohort_total(cohort) if available_count is None else available_count))
    if count <= 0 or float(cohort.get("service_months_mean", 0.0)) < float(minimum_service_months):
        return 0
    fractions: list[float] = []
    attrs = cohort.get("attribute_means", {}); attr_sd = cohort.get("attribute_sd", {})
    if minimum_attribute_values:
        for name, threshold in zip(ATTRIBUTE_ORDER, minimum_attribute_values):
            if name not in attrs:
                return 0
            fractions.append(_tail_fraction(float(attrs[name]), float(attr_sd.get(name, 8.0)), float(threshold)))
    skills = cohort.get("skill_means", {}); skill_sd = cohort.get("skill_sd", {})
    if minimum_skill_values:
        for name, threshold in zip(SKILL_ORDER, minimum_skill_values):
            if name not in skills:
                return 0
            fractions.append(_tail_fraction(float(skills[name]), float(skill_sd.get(name, 10.0)), float(threshold)))
    if not fractions:
        return count
    fraction = min(fractions)
    return max(0, min(count, int(math.floor(count * fraction + 1e-9))))


def _tail_fraction(mean: float, sd: float, threshold: float) -> float:
    if sd <= 0:
        return 1.0 if mean >= threshold else 0.0
    z = (threshold - mean) / sd
    return max(0.0, min(1.0, 1.0 - NormalDist().cdf(z)))


def seed_cohort_capability(
    cohort: MutableMapping[str, Any],
    *,
    attribute_means: Mapping[str, Any] | None = None,
    skill_means: Mapping[str, Any] | None = None,
    attribute_sd: float | Mapping[str, Any] = 8.0,
    skill_sd: float | Mapping[str, Any] = 10.0,
    aptitude_means: Mapping[str, Any] | None = None,
    service_months_mean: float | None = None,
    age_mean: float | None = None,
    evidence_ref: str,
) -> None:
    if attribute_means:
        cohort["attribute_means"] = {str(k): float(v) for k, v in attribute_means.items()}
    if skill_means:
        cohort["skill_means"] = {str(k): float(v) for k, v in skill_means.items()}
    if isinstance(attribute_sd, Mapping):
        cohort["attribute_sd"] = {str(k): float(v) for k, v in attribute_sd.items()}
    elif attribute_means:
        cohort["attribute_sd"] = {str(k): float(attribute_sd) for k in attribute_means}
    if isinstance(skill_sd, Mapping):
        cohort["skill_sd"] = {str(k): float(v) for k, v in skill_sd.items()}
    elif skill_means:
        cohort["skill_sd"] = {str(k): float(skill_sd) for k in skill_means}
    if aptitude_means:
        cohort["aptitude_means"] = {str(k): float(v) for k, v in aptitude_means.items()}
    if service_months_mean is not None:
        cohort["service_months_mean"] = float(service_months_mean)
    if age_mean is not None:
        cohort.setdefault("age_distribution", {})["mean"] = float(age_mean)
    cohort.setdefault("capability_evidence", []).append(str(evidence_ref))
    cohort["capability_evidence"] = cohort["capability_evidence"][-12:]
    tags = cohort.setdefault("tags", [])
    if "quality_not_reconstructed" in tags:
        tags.remove("quality_not_reconstructed")
    if "evidence_seeded_capability" not in tags:
        tags.append("evidence_seeded_capability")


__all__ = [
    "ATTRIBUTE_ORDER", "SKILL_ORDER", "add_recruits", "advance_cohort_training",
    "advance_service_months", "append_formation_slices", "consume_population_recruits",
    "ensure_cohort_ledger", "ensure_formation_composition", "merge_formation_slices",
    "partition_formation_slices", "qualification_capacity", "record_recruitment_cohort",
    "return_formation_slices", "role_count", "seed_cohort_capability", "stable_fraction",
    "take_reserve_slices", "transfer_between_forces", "transfer_role",
    "trim_formation_to_personnel", "validate_cohort_ledger",
]
