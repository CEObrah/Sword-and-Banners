"""Deterministic fatigue clocks for exact people and aggregate formations."""
from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime

RULES_PATH = "game/data/mechanics/fatigue.json"


def _clamp(value: int) -> int:
    return max(0, min(100, int(value)))


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


__all__ = ["RULES_PATH", "settle_formation_idle_fatigue", "project_formation_idle_fatigue", "stamp_formation_activity_fatigue", "settle_person_idle_fatigue", "stamp_person_activity_fatigue"]
