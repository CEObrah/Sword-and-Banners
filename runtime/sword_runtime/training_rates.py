"""Shared standing-activity rate resolution.

The game-data regimen registry is the single authority for standard training
rates. Saved activity state may cache the resolved rate for inspection, but it
must not override House Tang's canonical maximum-sustainable regimen. Child
household development is intentionally excluded from adult standing-role skill
settlement.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SECONDS_PER_30D = 30 * 86400
_HOUSE_TANG_REGIMEN = "house_tang_max_sustainable"
_HOUSE_TANG_STANDING_MODE = "standing_role_training"
_CHILD_HOUSEHOLD_MODE = "age_appropriate_household_training"


def verified_activity_hours_per_cycle(
    person: Mapping[str, Any],
    contract: Mapping[str, Any],
    profiles: Mapping[str, Any],
    cadence_seconds: int,
    *,
    fallback_hours: float = 48.0,
) -> float:
    """Resolve verified deliberate-training hours for one autonomous cycle.

    House Tang adults on the standing-role contract always derive their rate
    from ``house_tang_max_sustainable``. This intentionally supersedes stale
    cached values such as the historical 48-hour/30-day default. Children on
    the age-appropriate household contract receive no adult skill-training
    cycle here; their supervised development remains owned by the child/life
    course systems.
    """
    cadence = max(1, int(cadence_seconds))
    mode = str(contract.get("mode", ""))
    if mode == _CHILD_HOUSEHOLD_MODE:
        return 0.0

    regimens = profiles.get("training_regimens") if isinstance(profiles, Mapping) else None
    requested_regimen = str(contract.get("training_regimen_ref", "")).strip()
    if requested_regimen and isinstance(regimens, Mapping):
        regimen = regimens.get(requested_regimen)
        if isinstance(regimen, Mapping):
            monthly = float(regimen.get("deliberate_hours_per_30d", 0.0) or 0.0)
            if monthly > 0:
                return monthly * cadence / _SECONDS_PER_30D

    if str(person.get("affiliation", "")) == "House Tang" and mode == _HOUSE_TANG_STANDING_MODE:
        regimen = regimens.get(_HOUSE_TANG_REGIMEN) if isinstance(regimens, Mapping) else None
        if isinstance(regimen, Mapping):
            monthly = float(regimen.get("deliberate_hours_per_30d", 0.0) or 0.0)
            if monthly > 0:
                return monthly * cadence / _SECONDS_PER_30D

    activity = person.get("autonomous_activity_state")
    if isinstance(activity, Mapping):
        cached = float(activity.get("verified_hours_per_cycle", 0.0) or 0.0)
        if cached > 0:
            return cached
    return max(0.0, float(fallback_hours))


__all__ = ["verified_activity_hours_per_cycle"]
