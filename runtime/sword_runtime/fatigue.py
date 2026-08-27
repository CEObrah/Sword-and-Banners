"""Deterministic fatigue clocks for exact people and aggregate formations."""
from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime

RULES_PATH = "game/data/mechanics/fatigue.json"


def _clamp(value: int) -> int:
    return max(0, min(100, int(value)))


def _clampf(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))


def _parse_optional(value: Any) -> CampaignTime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return CampaignTime.parse(value)
    except Exception:
        return None


def _elapsed_recovery_points(start: CampaignTime, end: CampaignTime, points_per_8h: float) -> int:
    if end <= start or points_per_8h <= 0:
        return 0
    hours = start.seconds_until(end) / 3600.0
    return max(0, int(math.floor(hours * points_per_8h / 8.0 + 1e-9)))


def endurance_fatigue_rate_factor(endurance: float) -> float:
    """Return how quickly physical work accumulates fatigue.

    Endurance changes sustainable output, not the meaning of saved fatigue itself.
    A fighter with Endurance 200 therefore accumulates fatigue substantially more
    slowly than one with Endurance 40, but once both are at fatigue 100 both are
    severely exhausted. The square-root law keeps growth meaningful above 100
    without allowing extreme Endurance to erase exertion.
    """
    e = max(25.0, float(endurance or 0.0))
    return _clampf(math.sqrt(100.0 / e), 0.55, 2.0)


def person_fatigue_factors(*, fatigue: float, endurance: float = 0.0) -> dict[str, float]:
    """Bounded exact-person performance factors for current saved fatigue.

    ``endurance`` is accepted for a stable call contract but intentionally does
    not make an equally exhausted person magically fresh. Endurance already acts
    on the rate at which fatigue is accumulated.
    """
    fraction = _clampf(float(fatigue or 0.0) / 100.0, 0.0, 1.0)
    return {
        "fatigue_fraction": round(fraction, 6),
        "control_factor": _clampf(1.0 - 0.48 * fraction, 0.52, 1.0),
        "tempo_factor": _clampf(1.0 - 0.68 * fraction, 0.32, 1.0),
        "movement_factor": _clampf(1.0 - 0.58 * fraction, 0.42, 1.0),
        "exertion_capacity_factor": _clampf(1.0 - 0.80 * fraction, 0.20, 1.0),
    }


def battle_person_fatigue_gain(
    *,
    rules: Mapping[str, Any],
    battle_hours: float,
    role: str,
    endurance: float,
    available_contact_seconds: float = 0.0,
    physical_contacts: int = 0,
    burden_multiplier: float = 1.0,
) -> int:
    """Deterministic fatigue gained by one named person during mass battle duty.

    The 120-second hero-contact window is only a bounded physics sample. Fatigue
    is charged from the full battle-duty interval plus local contact intensity,
    then scaled by Endurance and carried equipment burden. This prevents repeated
    battle contacts from refreshing a named combatant for free.
    """
    person = rules.get("person", {}) if isinstance(rules, Mapping) else {}
    cfg = person.get("battle_activity", {}) if isinstance(person, Mapping) else {}
    role_rates = cfg.get("base_points_per_hour_by_role", {}) if isinstance(cfg, Mapping) else {}
    base_rate = float(role_rates.get(str(role), role_rates.get("default", 3.0))) if isinstance(role_rates, Mapping) else 3.0
    hours = max(0.0, float(battle_hours or 0.0))
    contact_minutes = max(0.0, float(available_contact_seconds or 0.0)) / 60.0
    contacts = max(0, int(physical_contacts or 0))
    duty = hours * max(0.0, base_rate)
    contact = contact_minutes * float(cfg.get("contact_points_per_minute", 0.10) or 0.10)
    contact += math.sqrt(float(contacts)) * float(cfg.get("contact_points_per_sqrt_contact", 0.80) or 0.80)
    burden = _clampf(float(burden_multiplier or 1.0), 0.65, float(cfg.get("maximum_burden_multiplier", 2.25) or 2.25))
    raw = (duty + contact) * burden * endurance_fatigue_rate_factor(endurance)
    minimum = max(0, int(cfg.get("minimum_gain_if_duty", 1) or 1)) if hours > 0.0 else 0
    maximum = max(minimum, int(cfg.get("maximum_gain_per_battle", 70) or 70))
    return max(minimum, min(maximum, int(math.ceil(raw - 1e-9))))


def settle_formation_idle_fatigue(
    formation: MutableMapping[str, Any],
    *,
    current: CampaignTime,
    rules: Mapping[str, Any],
    initialize_if_missing: bool = True,
) -> dict[str, Any]:
    section = rules.get("formation", {}) if isinstance(rules, Mapping) else {}
    status = str(formation.get("status", "default")).lower()
    before = _clamp(int(formation.get("fatigue", 0) or 0))
    start = _parse_optional(formation.get("fatigue_recovery_through"))
    if start is None:
        if initialize_if_missing:
            formation["fatigue_recovery_through"] = str(current)
        return {"fatigue_before": before, "fatigue_after": before, "recovery_points": 0, "elapsed_hours": 0.0, "status": status, "initialized": True}
    if start > current:
        # The last activity has not physically completed yet. Preserve its future
        # recovery boundary so an intermediate touch cannot convert work/march
        # hours into free rest.
        return {"fatigue_before": before, "fatigue_after": before, "recovery_points": 0, "elapsed_hours": 0.0, "status": status, "initialized": False, "activity_in_progress": True}
    blocked = {str(x).lower() for x in section.get("no_recovery_statuses", [])} if isinstance(section, Mapping) else set()
    elapsed_hours = max(0.0, start.seconds_until(current) / 3600.0)
    if status in blocked:
        points = 0
    else:
        rates = section.get("recovery_points_per_8h", {}) if isinstance(section, Mapping) else {}
        rate = float(rates.get(status, rates.get("default", 8.0))) if isinstance(rates, Mapping) else 8.0
        points = _elapsed_recovery_points(start, current, rate)
    after = _clamp(before - points)
    formation["fatigue"] = after
    formation["fatigue_recovery_through"] = str(current)
    return {"fatigue_before": before, "fatigue_after": after, "recovery_points": max(0, before - after), "elapsed_hours": round(elapsed_hours, 3), "status": status, "initialized": False}


def stamp_formation_activity_fatigue(
    formation: MutableMapping[str, Any],
    *,
    completed_at: CampaignTime,
    fatigue_gain: int,
    activity_kind: str,
) -> dict[str, Any]:
    before = _clamp(int(formation.get("fatigue", 0) or 0))
    after = _clamp(before + max(0, int(fatigue_gain)))
    formation["fatigue"] = after
    formation["fatigue_recovery_through"] = str(completed_at)
    formation["last_fatigue_activity"] = {"at": str(completed_at), "kind": str(activity_kind), "fatigue_gain": max(0, int(fatigue_gain))}
    return {"fatigue_before": before, "fatigue_after": after, "fatigue_gain": max(0, int(fatigue_gain)), "activity_kind": str(activity_kind)}


def project_formation_idle_fatigue(
    formation: Mapping[str, Any],
    *,
    current: CampaignTime,
    rules: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a read-only formation image with elapsed rest fatigue settled."""
    projected = dict(formation)
    # Nested fields are not mutated by the formation fatigue helper; shallow copy
    # is therefore sufficient and avoids copying large logistics/equipment ledgers.
    settle_formation_idle_fatigue(projected, current=current, rules=rules)
    return projected


def settle_person_idle_fatigue(
    person: MutableMapping[str, Any],
    *,
    current: CampaignTime,
    rules: Mapping[str, Any],
    state: str = "ordinary",
    initialize_if_missing: bool = True,
) -> dict[str, Any]:
    section = rules.get("person", {}) if isinstance(rules, Mapping) else {}
    health = person.get("health") if isinstance(person.get("health"), MutableMapping) else None
    raw_before = health.get("fatigue", person.get("fatigue", 0)) if health is not None else person.get("fatigue", 0)
    before = _clamp(int(raw_before or 0))
    ds = person.setdefault("development_state", {})
    start = _parse_optional(ds.get("fatigue_recovery_through"))
    if start is None:
        if initialize_if_missing:
            ds["fatigue_recovery_through"] = str(current)
        return {"fatigue_before": before, "fatigue_after": before, "recovery_points": 0, "elapsed_hours": 0.0, "state": state, "initialized": True}
    if start > current:
        return {"fatigue_before": before, "fatigue_after": before, "recovery_points": 0, "elapsed_hours": 0.0, "state": state, "initialized": False, "activity_in_progress": True}
    blocked = {str(x).lower() for x in section.get("no_recovery_states", [])} if isinstance(section, Mapping) else set()
    elapsed_hours = max(0.0, start.seconds_until(current) / 3600.0)
    if str(state).lower() in blocked:
        points = 0
    else:
        rates = section.get("recovery_points_per_8h", {}) if isinstance(section, Mapping) else {}
        rate = float(rates.get(state, rates.get("default", 14.0))) if isinstance(rates, Mapping) else 14.0
        points = _elapsed_recovery_points(start, current, rate)
    after = _clamp(before - points)
    if health is not None and "fatigue" in health:
        health["fatigue"] = after
    else:
        person["fatigue"] = after
    ds["fatigue_recovery_through"] = str(current)
    return {"fatigue_before": before, "fatigue_after": after, "recovery_points": max(0, before - after), "elapsed_hours": round(elapsed_hours, 3), "state": state, "initialized": False}


def stamp_person_activity_fatigue(person: MutableMapping[str, Any], *, completed_at: CampaignTime, fatigue_gain: int, activity_kind: str) -> dict[str, Any]:
    health = person.get("health") if isinstance(person.get("health"), MutableMapping) else None
    raw = health.get("fatigue", person.get("fatigue", 0)) if health is not None else person.get("fatigue", 0)
    before = _clamp(int(raw or 0)); after = _clamp(before + max(0, int(fatigue_gain)))
    if health is not None and "fatigue" in health: health["fatigue"] = after
    else: person["fatigue"] = after
    ds = person.setdefault("development_state", {}); ds["fatigue_recovery_through"] = str(completed_at)
    ds["last_fatigue_activity"] = {"at": str(completed_at), "kind": str(activity_kind), "fatigue_gain": max(0, int(fatigue_gain))}
    return {"fatigue_before": before, "fatigue_after": after, "fatigue_gain": max(0, int(fatigue_gain)), "activity_kind": str(activity_kind)}


__all__ = ["RULES_PATH", "endurance_fatigue_rate_factor", "person_fatigue_factors", "battle_person_fatigue_gain", "settle_formation_idle_fatigue", "project_formation_idle_fatigue", "stamp_formation_activity_fatigue", "settle_person_idle_fatigue", "stamp_person_activity_fatigue"]
