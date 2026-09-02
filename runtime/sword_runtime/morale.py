"""Single deterministic formation-morale authority.

Morale is a saved 0..100 formation fact.  This module evaluates only registered
physical/organizational triggers and returns a bounded result.  It has no hidden
random roll and does not create a second morale state owner.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RULES_PATH = "game/data/mechanics/morale.json"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _rules(planner: Any) -> Mapping[str, Any]:
    row = planner.read(RULES_PATH)
    if not isinstance(row, Mapping) or str(row.get("schema", "")) != "morale-mechanics":
        raise ValueError("registered morale mechanics are missing")
    return row


def morale_band(planner: Any, morale: int | float) -> str:
    rules = _rules(planner)
    value = int(round(_clamp(float(morale), 0.0, 100.0)))
    thresholds = rules.get("thresholds", {}) if isinstance(rules.get("thresholds"), Mapping) else {}
    for key, label in thresholds.items():
        try:
            lo, hi = [int(x) for x in str(key).split("-", 1)]
        except (TypeError, ValueError):
            continue
        if lo <= value <= hi:
            return str(label)
    return "steady"


def _trigger_weight(rules: Mapping[str, Any], group: str, key: str, default: float = 0.0) -> float:
    weights = rules.get("trigger_weights", {}) if isinstance(rules.get("trigger_weights"), Mapping) else {}
    row = weights.get(group, {}) if isinstance(weights.get(group), Mapping) else {}
    try:
        return float(row.get(key, default) or 0.0)
    except (TypeError, ValueError):
        return default


def resolve_formation_morale(
    planner: Any,
    *,
    base_morale: int | float,
    recent_casualty_fraction: float = 0.0,
    cumulative_casualty_fraction: float = 0.0,
    commander_lost: bool = False,
    key_staff_lost: bool = False,
    registered_fear_pressure: float = 0.0,
    cohesion: int | float = 50,
    positional_condition: str = "none",
    isolation_condition: str = "connected",
    supply_condition: str = "secure",
    command_action_used: bool = False,
    leadership: int | float = 0,
    presence: int | float = 0,
    formation_command: int | float = 0,
    commander_familiarity_factor: float = 1.0,
) -> dict[str, Any]:
    rules = _rules(planner)
    base = _clamp(float(base_morale), 0.0, 100.0)
    recent = _clamp(float(recent_casualty_fraction), 0.0, 1.0)
    cumulative = _clamp(float(cumulative_casualty_fraction), 0.0, 1.0)
    fear = _clamp(float(registered_fear_pressure), 0.0, 20.0)
    cohesion_value = _clamp(float(cohesion), 0.0, 100.0)

    casualty_pressure = _clamp(45.0 * recent + 20.0 * cumulative, 0.0, 30.0)
    command_loss_pressure = (9.0 if commander_lost else 0.0) + (4.0 if key_staff_lost else 0.0)
    positional_pressure = _trigger_weight(rules, "positional_pressure", str(positional_condition), 0.0)
    isolation_pressure = _trigger_weight(rules, "isolation_pressure", str(isolation_condition), 0.0)
    normalized_supply = str(supply_condition or "secure").lower()
    if normalized_supply in {"adequate", "good", "supplied", "normal"}:
        normalized_supply = "secure"
    elif normalized_supply in {"low", "strained", "undersupplied"}:
        normalized_supply = "strained"
    elif normalized_supply in {"isolated", "critical"}:
        normalized_supply = "critical"
    elif normalized_supply in {"empty", "exhausted", "starving"}:
        normalized_supply = "exhausted"
    supply_pressure = _trigger_weight(rules, "supply_pressure", normalized_supply, 0.0)
    cohesion_support = _clamp((cohesion_value - 55.0) * 0.18, -8.0, 8.0)

    rally = 0.0
    if command_action_used:
        command_quality = 0.40 * float(leadership) + 0.30 * float(presence) + 0.30 * float(formation_command)
        raw_rally = _clamp((command_quality - 60.0) * 0.18, 0.0, 18.0)
        familiarity = _clamp(float(commander_familiarity_factor), 0.85, 1.15)
        rally = _clamp(raw_rally * familiarity, 0.0, 18.0)

    registered_trigger = any((
        recent > 0.0, cumulative > 0.0, commander_lost, key_staff_lost, fear > 0.0,
        positional_pressure > 0.0, isolation_pressure > 0.0, supply_pressure > 0.0,
        command_action_used,
    ))
    if not registered_trigger:
        effective = base
        pressure = 0.0
    else:
        pressure = casualty_pressure + command_loss_pressure + positional_pressure + isolation_pressure + supply_pressure + fear - rally - cohesion_support
        effective = _clamp(base - pressure, 0.0, 100.0)

    result = int(round(effective))
    return {
        "base_morale": int(round(base)),
        "effective_morale": result,
        "band": morale_band(planner, result),
        "registered_trigger": registered_trigger,
        "morale_pressure": round(pressure, 3),
        "components": {
            "casualty_pressure": round(casualty_pressure, 3),
            "command_loss_pressure": round(command_loss_pressure, 3),
            "fear_pressure": round(fear, 3),
            "positional_pressure": round(positional_pressure, 3),
            "isolation_pressure": round(isolation_pressure, 3),
            "supply_pressure": round(supply_pressure, 3),
            "cohesion_support": round(cohesion_support, 3),
            "rally": round(rally, 3),
        },
        "rule_ref": RULES_PATH,
    }


__all__ = ["RULES_PATH", "morale_band", "resolve_formation_morale"]
