"""Derived strategic military supply.

Armies do not own ration/feed inventories.  Current supply is a deterministic
projection from physical location, state/control, route access, local civilian
food stress, force size, mounts and operational separation from friendly
support.  The projection is never persisted as authoritative state.

This module deliberately does *not* create provisions, forage, depots, convoys
or baggage owners.  Discrete military assets such as ammunition, equipment and
mounts remain conserved by their existing owners.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Callable

from sword_runtime.geography import nearest_reachable_destination

_LOCATIONS_PATH = "game/data/world/locations.json"
_TERRITORY_PATH = "state/territory/control.json"

_BANDS: tuple[tuple[int, str, float, float, float, int], ...] = (
    (850, "secure", 1.00, 1.00, 1.00, 0),
    (700, "adequate", 1.00, 1.00, 1.00, 0),
    (550, "strained", 0.95, 0.96, 0.90, 10),
    (400, "poor", 0.85, 0.88, 0.75, 25),
    (250, "critical", 0.70, 0.76, 0.55, 55),
    (0, "isolated", 0.55, 0.62, 0.35, 100),
)


def _read(reader: Any, path: str) -> Mapping[str, Any]:
    if hasattr(reader, "read"):
        value = reader.read(path)
    elif callable(reader):
        value = reader(path)
    else:
        raise TypeError("military supply reader must provide read(path) or be callable")
    return value if isinstance(value, Mapping) else {}


def _optional(reader: Any, path: str) -> Mapping[str, Any] | None:
    try:
        value = _read(reader, path)
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _locations(reader: Any) -> dict[str, Mapping[str, Any]]:
    doc = _read(reader, _LOCATIONS_PATH)
    return {
        str(row.get("ref")): row
        for row in doc.get("locations", [])
        if isinstance(row, Mapping) and isinstance(row.get("ref"), str)
    }


def _state_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.removeprefix("state_")


def _administrative_state(formation: Mapping[str, Any]) -> str | None:
    for key in ("administrative_owner", "state"):
        value = _state_key(formation.get(key))
        if value:
            return value
    force = formation.get("owner_force_ref")
    if isinstance(force, str) and force.startswith("force_state_"):
        return force.removeprefix("force_state_")
    return None


def _controller(reader: Any, location_ref: str) -> str | None:
    territory = _optional(reader, _TERRITORY_PATH)
    if not isinstance(territory, Mapping):
        return None
    sites = territory.get("sites")
    row = sites.get(location_ref) if isinstance(sites, Mapping) else None
    if not isinstance(row, Mapping):
        return None
    return _state_key(row.get("controller"))


def active_mount_count(formation: Mapping[str, Any]) -> int:
    mounts = formation.get("mounts")
    active = 0
    if isinstance(mounts, Mapping):
        active = sum(max(0, int(v or 0)) for v in mounts.values() if not isinstance(v, bool))
    elif isinstance(mounts, (int, float)) and not isinstance(mounts, bool):
        active = max(0, int(mounts))
    return active


def remount_count(formation: Mapping[str, Any]) -> int:
    logistics = formation.get("logistics")
    return max(0, int(logistics.get("remount_horses", 0) or 0)) if isinstance(logistics, Mapping) else 0


def formation_mount_burden(formation: Mapping[str, Any]) -> int:
    return active_mount_count(formation) + remount_count(formation)


def _regional_food_stress(reader: Any, state_key: str | None, location_ref: str) -> tuple[int, str | None]:
    """Return a bounded strategic penalty from the civilian food-security ledger.

    The military does not consume this grain.  We only use the most recent civil
    close as evidence that the surrounding economy can or cannot support field
    activity.  Missing data is neutral rather than magically abundant.
    """
    if not state_key:
        return 0, None
    doc = _optional(reader, f"state/economy/private/{state_key}.json")
    if not isinstance(doc, Mapping):
        return 0, None
    runtime = doc.get("production_runtime")
    close = runtime.get("last_regional_close") if isinstance(runtime, Mapping) else None
    row = close.get(location_ref) if isinstance(close, Mapping) else None
    if not isinstance(row, Mapping):
        return 0, None
    shortfall = max(0, int(row.get("grain_shortfall_kg", row.get("grain_shortfall_kg_before_internal_transfer", 0)) or 0))
    consumed = max(0, int(row.get("grain_consumed_kg", 0) or 0))
    if consumed <= 0 or shortfall <= 0:
        return 0, "local civilian food ledger reports no current shortage"
    ratio = min(1.0, shortfall / max(1, consumed))
    penalty = min(220, int(round(220 * math.sqrt(ratio))))
    return penalty, f"local civilian food stress reduces regional support ({ratio:.0%} shortfall signal)"


def _nearest_support(
    reader: Any,
    *,
    location_ref: str,
    state_key: str | None,
    locations: Mapping[str, Mapping[str, Any]],
) -> tuple[str | None, int | None]:
    if not state_key:
        return None, None
    candidates: list[str] = []
    for ref, row in locations.items():
        if str(row.get("state", "")) != state_key:
            continue
        if not bool(row.get("strategic_node")) or bool(row.get("flavor_only")):
            continue
        controller = _controller(reader, ref)
        if controller not in {None, state_key}:
            continue
        candidates.append(ref)
    if not candidates:
        return None, None
    if location_ref in candidates:
        return location_ref, 0
    try:
        nearest = nearest_reachable_destination(
            reader.read if hasattr(reader, "read") else reader,
            location_ref,
            sorted(candidates),
            modes=("formation", "foot", "horse"),
        )
    except (ValueError, FileNotFoundError, KeyError):
        return None, None
    ref = str(nearest.get("destination", "")) or None
    hours = max(0, int(nearest.get("duration_hours", 0) or 0))
    return ref, hours


def evaluate_military_supply(reader: Any, formation: Mapping[str, Any], *, at: str | None = None) -> dict[str, Any]:
    """Return the current non-authoritative supply projection for one formation."""
    location_ref = str(formation.get("location_ref", ""))
    personnel = max(0, int(formation.get("personnel", 0) or 0))
    mounts = formation_mount_burden(formation)
    state_key = _administrative_state(formation)
    locations = _locations(reader)
    location = locations.get(location_ref, {})
    physical_state = str(location.get("state", "")) or None
    controller = _controller(reader, location_ref)

    score = 760
    reasons: list[str] = []
    if state_key and (physical_state == state_key or controller == state_key):
        score += 120
        reasons.append("inside friendly-controlled or home logistical territory")
    elif controller and state_key and controller != state_key:
        score -= 170
        reasons.append("operating under hostile territorial control")
    elif physical_state and state_key and physical_state != state_key:
        score -= 90
        reasons.append("operating outside the home state")

    support_ref, support_hours = _nearest_support(reader, location_ref=location_ref, state_key=state_key, locations=locations)
    if support_hours is None:
        score -= 260
        reasons.append("no reachable friendly strategic support node")
    else:
        if support_hours <= 12:
            distance_penalty = 0
        elif support_hours <= 36:
            distance_penalty = 45
        elif support_hours <= 72:
            distance_penalty = 110
        elif support_hours <= 120:
            distance_penalty = 190
        else:
            distance_penalty = min(330, 190 + (support_hours - 120) // 2)
        score -= distance_penalty
        reasons.append(f"nearest friendly strategic support is about {support_hours} route-hour(s) away")

    # Large forces and horse-heavy forces impose real support burden without
    # inventing ration/feed inventories or per-day ration bookkeeping.
    size_penalty = min(150, max(0, personnel - 5000) // 500)
    mount_share = mounts / max(1, personnel)
    mount_penalty = min(130, int(round(110 * min(1.2, mount_share))))
    score -= size_penalty + mount_penalty
    if size_penalty:
        reasons.append("large field strength increases support burden")
    if mount_penalty:
        reasons.append("mounted/remount strength increases transport and grazing pressure")

    food_penalty, food_reason = _regional_food_stress(reader, physical_state or state_key, location_ref)
    score -= food_penalty
    if food_reason:
        reasons.append(food_reason)

    score = max(0, min(1000, int(score)))
    threshold, condition, movement, combat, recovery, mount_pressure = next(row for row in _BANDS if score >= row[0])
    return {
        "authority": False,
        "condition": condition,
        "score_milli": score,
        "movement_factor": movement,
        "combat_factor": combat,
        "recovery_factor": recovery,
        "mount_condition_pressure_milli_per_active_day": mount_pressure,
        "location_ref": location_ref or None,
        "administrative_state": f"state_{state_key}" if state_key else None,
        "nearest_support_ref": support_ref,
        "nearest_support_route_hours": support_hours,
        "personnel": personnel,
        "mounts_and_remounts": mounts,
        "reasons": reasons,
        "evaluated_at": at,
        "rule": "Strategic supply is derived from current world facts; armies own no food, animal feed or provisions inventory.",
    }


def military_supply_sufficiency(reader: Any, formation: Mapping[str, Any], *, reserve_days: float | None = None) -> dict[str, Any]:
    """Compatibility projection for older callers while they are migrated.

    `reserve_days` is intentionally ignored: supply is no longer a carried-ration
    reserve.  The returned ratio aliases the current derived strategic condition.
    """
    state = evaluate_military_supply(reader, formation)
    ratio = float(state["score_milli"]) / 1000.0
    return {
        **state,
        "overall_ratio": ratio,
        "overall_milli": int(state["score_milli"]),
        "reserve_days": None,
    }


__all__ = ["active_mount_count", "remount_count", "formation_mount_burden", "evaluate_military_supply", "military_supply_sufficiency"]
