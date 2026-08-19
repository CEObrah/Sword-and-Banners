"""Progression-integrity diagnostics for named people.

This module distinguishes proven under-settlement from representation changes.
A person materialized from an already-developed cohort inherits the cohort's
current capability in sampled attributes/skills; those cohort hours are
provenance, not a second exact-person EDU award.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.training_rates import verified_activity_hours_per_cycle


def inherited_training_baseline(cohort: Mapping[str, Any], source_cohort_ref: str) -> dict[str, Any]:
    return {
        "source_cohort_ref": str(source_cohort_ref),
        "verified_training_hours_per_person": round(
            float(cohort.get("verified_training_hours_per_person", 0.0) or 0.0), 3
        ),
        "verified_role_exposure_hours_per_person": round(
            float(cohort.get("verified_role_exposure_hours_per_person", 0.0) or 0.0), 3
        ),
        "rule": (
            "materialized attributes and skills were sampled from the current developed source cohort; "
            "inherited cohort hours are provenance only and must never be re-settled as exact-person training"
        ),
    }


def exact_activity_shortfall(
    person: Mapping[str, Any],
    contract: Mapping[str, Any],
    profiles: Mapping[str, Any],
    *,
    fallback_hours: float = 48.0,
) -> dict[str, Any]:
    """Return a proof surface for already-completed autonomous training cycles.

    Only ``completed_cycles`` count toward expected deliberate hours. Skipped or
    merely reviewed cycles are excluded. A positive result is therefore evidence
    that this exact record already claims completed training cycles whose canonical
    regimen hours were not fully settled into its exact development owner.
    """
    activity = person.get("autonomous_activity_state")
    if not isinstance(activity, Mapping):
        return {"completed_cycles": 0, "cycle_hours": 0.0, "expected_hours": 0, "settled_hours": 0, "shortfall_hours": 0}
    completed = max(0, int(activity.get("completed_cycles", 0) or 0))
    cadence = max(1, int(activity.get("cadence_seconds", 30 * 86400) or 30 * 86400))
    cycle_hours = verified_activity_hours_per_cycle(
        person, contract, profiles, cadence, fallback_hours=fallback_hours
    )
    # Exact-character settlement is whole-hour authoritative. Fractional schedule
    # time carries forward across cycles, so the proven cumulative expectation is
    # floor(total scheduled hours), never independent per-cycle rounding.
    expected = int(completed * cycle_hours + 1e-9)
    development = person.get("development_state")
    settled = max(0, int(development.get("settled_training_hours", 0) or 0)) if isinstance(development, Mapping) else 0
    # ``settled_training_hours`` counts only gain-bearing skill-module hours. A
    # registered module can be physically blocked while the person still spent a
    # verified training window on the lawful program. New settlement therefore
    # tracks verified deliberate hours separately. Legacy records fall back to the
    # settled counter so a migration can reconcile the missing verified clock once.
    verified = max(0, int(development.get("verified_deliberate_training_hours", settled) or 0)) if isinstance(development, Mapping) else settled
    return {
        "completed_cycles": completed,
        "cycle_hours": round(float(cycle_hours), 6),
        "expected_hours": expected,
        "settled_hours": settled,
        "verified_deliberate_hours": verified,
        "shortfall_hours": max(0, expected - verified),
    }


__all__ = ["exact_activity_shortfall", "inherited_training_baseline"]
