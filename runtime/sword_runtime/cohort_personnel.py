"""Conserved aggregate-cohort and selective latent-personnel mechanics.

Ordinary military populations remain aggregate distributions.  Persistent latent
identities are opt-in and are intended for unusually important personnel pools
(such as Tang Champions) or a player character's personally recruited retinue.
This module deliberately does not make every anonymous soldier in the world an
individual record.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from typing import Any

LATENT_VECTOR_LABELS: tuple[str, ...] = (
    "strength",
    "agility",
    "endurance",
    "perception",
    "intelligence",
    "willpower",
    "discipline",
    "leadership",
    "social",
    "bow",
    "riding",
    "lance",
    "sword",
    "shield",
    "athletics",
    "awareness",
    "formation_command",
    "mass_combat",
    "scouting",
    "survival",
    "medicine",
)


def _stable_u64(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def stable_fraction(*parts: object) -> float:
    """Return a deterministic [0, 1) draw without mutable RNG state."""

    return _stable_u64(*parts) / float(1 << 64)


def latent_member_id(catalog: Mapping[str, Any], index: int) -> str:
    count = int(catalog.get("count", 0))
    if index < 1 or index > count:
        raise IndexError("latent member index outside catalog")
    namespace = str(catalog.get("id_namespace") or catalog.get("owner_id") or "latent")
    width = max(3, len(str(max(1, count))))
    return f"{namespace}.{index:0{width}d}"


def latent_profile(catalog: Mapping[str, Any], index: int) -> dict[str, Any]:
    """Resolve the stable hidden profile for one opt-in latent person.

    Percentiles are stored by deterministic derivation rather than 21 hot stats
    per person.  Per-member overrides preserve wounds, awards, assignments, or
    other causal changes without rerolling the underlying person.
    """

    member_id = latent_member_id(catalog, index)
    seed = str(catalog.get("roster_seed", catalog.get("owner_id", "latent")))
    labels = catalog.get("latent_vector_labels")
    if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
        labels = LATENT_VECTOR_LABELS
    percentiles = {
        str(label): round(stable_fraction(seed, member_id, str(label)), 6)
        for label in labels
    }
    profile: dict[str, Any] = {
        "latent_id": member_id,
        "index": index,
        "rank": catalog.get("rank"),
        "institutional_owner": catalog.get("institutional_owner"),
        "source_kind": catalog.get("source_kind"),
        "trait_percentiles": percentiles,
    }
    overrides = catalog.get("member_overrides", {})
    if isinstance(overrides, Mapping) and isinstance(overrides.get(member_id), Mapping):
        profile.update(deepcopy(dict(overrides[member_id])))
    return profile


def materialize_latent_stats(
    catalog: Mapping[str, Any],
    index: int,
    baselines: Mapping[str, int],
    spreads: Mapping[str, int] | None = None,
) -> dict[str, int]:
    """Turn one persistent latent profile into exact integer capabilities.

    A percentile of .5 resolves to the baseline.  This is only a materialization
    helper; callers must conserve the same latent body rather than generating a
    replacement exact person.
    """

    profile = latent_profile(catalog, index)
    percentiles = profile["trait_percentiles"]
    spread_map = spreads or {}
    out: dict[str, int] = {}
    for label, baseline in baselines.items():
        spread = max(0, int(spread_map.get(label, max(4, round(abs(int(baseline)) * 0.12)))))
        percentile = float(percentiles.get(label, 0.5))
        delta = round((percentile - 0.5) * 2.0 * spread)
        out[label] = max(0, int(baseline) + delta)
    return out


def role_count(force: Mapping[str, Any], role: str) -> int:
    roles = force.get("available_by_role", {})
    return int(roles.get(role, 0)) if isinstance(roles, Mapping) else 0


def transfer_role(
    force: MutableMapping[str, Any],
    source_role: str,
    destination_role: str,
    count: int,
    *,
    location_ref: str | None = None,
) -> int:
    """Conserve bodies while moving aggregate people between roles."""

    requested = max(0, int(count))
    available = role_count(force, source_role)
    moved = min(requested, available)
    if moved <= 0:
        return 0
    roles = force.setdefault("available_by_role", {})
    roles[source_role] = int(roles.get(source_role, 0)) - moved
    roles[destination_role] = int(roles.get(destination_role, 0)) + moved
    if location_ref:
        by_location = force.setdefault("available_by_location", {}).setdefault(location_ref, {})
        by_location[source_role] = int(by_location.get(source_role, 0)) - moved
        by_location[destination_role] = int(by_location.get(destination_role, 0)) + moved
    return moved


def add_recruits(
    force: MutableMapping[str, Any],
    role: str,
    count: int,
    *,
    location_ref: str,
) -> int:
    """Add already-conserved recruits to a force after a population owner pays them."""

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


def consume_population_recruits(
    population: MutableMapping[str, Any],
    count: int,
    *,
    source_roles: Sequence[str],
    destination_role: str = "private_household_military",
) -> int:
    """Move real people between parent-population strata without changing total."""

    remaining = max(0, int(count))
    strata = population.setdefault("strata", {})
    moved = 0
    for source in source_roles:
        if remaining <= 0:
            break
        available = max(0, int(strata.get(source, 0)))
        take = min(remaining, available)
        if take:
            strata[source] = available - take
            moved += take
            remaining -= take
    if moved:
        strata[destination_role] = int(strata.get(destination_role, 0)) + moved
    return moved


def advance_aggregate_development(
    profile: MutableMapping[str, Any],
    count: int,
    occurrences: int,
) -> int:
    """Advance a cheap distribution summary and return newly assessment-ready bodies.

    The aggregate model intentionally does not mint latent identities.  It keeps
    service/training distributions and deterministic qualification throughput.
    Exact gates are still required when a person leaves an aggregate cohort for
    an individually persistent elite status.
    """

    occ = max(0, int(occurrences))
    bodies = max(0, int(count))
    if not occ or not bodies:
        return 0
    profile["service_months_mean"] = float(profile.get("service_months_mean", 0.0)) + occ
    monthly_hours = max(0.0, float(profile.get("verified_training_hours_per_month", 120.0)))
    profile["verified_training_hours_total"] = round(
        float(profile.get("verified_training_hours_total", 0.0)) + bodies * monthly_hours * occ,
        3,
    )
    minimum_months = max(0.0, float(profile.get("minimum_service_months", 0.0)))
    if float(profile["service_months_mean"]) < minimum_months:
        return 0
    rate = min(1.0, max(0.0, float(profile.get("monthly_newly_qualified_fraction", 0.0))))
    carry = float(profile.get("qualification_fraction_carry", 0.0)) + bodies * rate * occ
    newly_ready = int(carry)
    profile["qualification_fraction_carry"] = round(carry - newly_ready, 9)
    profile["assessment_ready"] = min(
        bodies,
        int(profile.get("assessment_ready", 0)) + newly_ready,
    )
    return newly_ready


__all__ = [
    "LATENT_VECTOR_LABELS",
    "add_recruits",
    "advance_aggregate_development",
    "consume_population_recruits",
    "latent_member_id",
    "latent_profile",
    "materialize_latent_stats",
    "role_count",
    "stable_fraction",
    "transfer_role",
]
