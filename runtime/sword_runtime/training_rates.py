"""Shared standing-activity regimen and rate resolution.

Training volume is institution/role driven, never allegiance driven.  Exact
specialized contracts remain authoritative.  Generic placeholders such as
``regular_army`` and ``civilian_skilled`` may be superseded by a registered
institution, career path, role archetype, or current billet standard.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SECONDS_PER_30D = 30 * 86400
_CHILD_HOUSEHOLD_MODE = "age_appropriate_household_training"


def _training_standards(profiles: Mapping[str, Any]) -> Mapping[str, Any]:
    rules = profiles.get("rules") if isinstance(profiles, Mapping) else None
    if not isinstance(rules, Mapping):
        return {}
    standards = rules.get("activity_training_standards")
    return standards if isinstance(standards, Mapping) else {}


def _mapped(mapping: object, key: object) -> str:
    if not isinstance(mapping, Mapping):
        return ""
    value = mapping.get(str(key or ""))
    return str(value).strip() if isinstance(value, str) else ""


def resolve_activity_regimen_ref(
    person: Mapping[str, Any],
    contract: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> str:
    """Resolve the lawful regimen for a named person's current activity.

    Precedence is deliberately neutral to faction identity:

    1. explicit non-generic saved regimen / explicitly locked regimen;
    2. registered exact assignment/institution standard;
    3. registered professional-path standard;
    4. registered role-archetype standard;
    5. registered current-billet standard;
    6. the saved generic regimen when present;
    7. registered civilian/default fallback.

    A House, state, or faction name is never itself a multiplier.
    """
    mode = str(contract.get("mode", ""))
    if mode == _CHILD_HOUSEHOLD_MODE:
        return ""

    regimens = profiles.get("training_regimens") if isinstance(profiles, Mapping) else None
    if not isinstance(regimens, Mapping):
        return ""
    standards = _training_standards(profiles)
    generic_refs = {
        str(x)
        for x in standards.get("generic_regimen_refs", ["regular_army", "civilian_skilled"])
        if isinstance(x, str)
    }
    requested = str(contract.get("training_regimen_ref", "")).strip()
    if requested and requested in regimens:
        if bool(contract.get("training_regimen_locked")) or requested not in generic_refs:
            return requested

    career = person.get("career_state") if isinstance(person.get("career_state"), Mapping) else {}
    assignment_ref = str(career.get("current_assignment_ref", "") or "")
    professional_path = str(career.get("current_professional_path", "") or "")
    role_archetype = str(person.get("role_archetype", "") or "")
    billet = str(career.get("current_billet", "") or "")
    command_assignment = person.get("command_assignment")
    if isinstance(command_assignment, Mapping):
        billet = str(command_assignment.get("billet", billet) or billet)

    candidates = (
        _mapped(standards.get("assignment_refs"), assignment_ref),
        _mapped(standards.get("professional_paths"), professional_path),
        _mapped(standards.get("role_archetypes"), role_archetype),
        _mapped(standards.get("billets"), billet),
    )
    for ref in candidates:
        if ref and ref in regimens:
            return ref

    if requested and requested in regimens:
        return requested
    fallback_ref = str(standards.get("fallback_regimen_ref", "civilian_skilled") or "civilian_skilled")
    if fallback_ref in regimens:
        return fallback_ref
    return "regular_army" if "regular_army" in regimens else next(iter(regimens), "")


def resolved_activity_regimen(
    person: Mapping[str, Any],
    contract: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any]]:
    ref = resolve_activity_regimen_ref(person, contract, profiles)
    regimens = profiles.get("training_regimens") if isinstance(profiles, Mapping) else None
    regimen = regimens.get(ref) if isinstance(regimens, Mapping) and ref else None
    return ref, regimen if isinstance(regimen, Mapping) else {}


def verified_activity_hours_per_cycle(
    person: Mapping[str, Any],
    contract: Mapping[str, Any],
    profiles: Mapping[str, Any],
    cadence_seconds: int,
    *,
    fallback_hours: float = 48.0,
) -> float:
    """Resolve verified deliberate-training hours for one autonomous cycle."""
    cadence = max(1, int(cadence_seconds))
    if str(contract.get("mode", "")) == _CHILD_HOUSEHOLD_MODE:
        return 0.0

    _ref, regimen = resolved_activity_regimen(person, contract, profiles)
    monthly = float(regimen.get("deliberate_hours_per_30d", 0.0) or 0.0)
    if monthly > 0:
        return monthly * cadence / _SECONDS_PER_30D

    activity = person.get("autonomous_activity_state")
    if isinstance(activity, Mapping):
        cached = float(activity.get("verified_hours_per_cycle", 0.0) or 0.0)
        if cached > 0:
            return cached
    return max(0.0, float(fallback_hours))


__all__ = [
    "resolve_activity_regimen_ref",
    "resolved_activity_regimen",
    "verified_activity_hours_per_cycle",
]
