"""Deterministic temporary-duty capacity for military support work.

Support work does not own a separate manpower species. Existing formation personnel
are temporarily assigned to engineering, baggage, signals, casualty handling, and
similar duties. Command/officer capability determines how effectively that labor is
organized; physical tools, stores, carts, facilities, geography, and time remain
separate conserved constraints.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.stat_access import merged_skill_map


FORBIDDEN_PERMANENT_SUPPORT_ROLES = frozenset({
    "siege_engineering", "engineer_sapper", "engineer", "sapper",
    "logistics", "signal", "medical", "support", "support_staff",
    "bastion_engineer", "bastion_logistics", "bastion_signal", "bastion_medical",
})

DUTY_FRACTIONS: dict[str, float] = {
    "engineering": 0.50,
    "logistics": 0.35,
    "signal": 0.08,
    "medical": 0.10,
}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def task_leader_score(person: Mapping[str, Any] | None, task: str) -> float:
    """Return an uncapped deterministic command/technical score for one task."""
    if not isinstance(person, Mapping):
        return 0.0
    skills = merged_skill_map(person)
    attrs = person.get("attributes", {}) if isinstance(person.get("attributes"), Mapping) else {}
    if not attrs:
        stats = person.get("stats", {}) if isinstance(person.get("stats"), Mapping) else {}
        attrs = stats.get("attributes", {}) if isinstance(stats.get("attributes"), Mapping) else {}
    task = str(task)
    if task == "engineering":
        return (
            0.55 * _number(skills.get("Engineering"))
            + 0.15 * _number(skills.get("Leadership"))
            + 0.15 * _number(skills.get("Logistics"))
            + 0.10 * _number(skills.get("Formation Command"))
            + 0.05 * _number(attrs.get("Intelligence"))
        )
    if task == "logistics":
        return (
            0.50 * _number(skills.get("Logistics"))
            + 0.20 * _number(skills.get("Leadership"))
            + 0.15 * _number(skills.get("Formation Command"))
            + 0.10 * _number(skills.get("Strategy"))
            + 0.05 * _number(attrs.get("Intelligence"))
        )
    if task == "signal":
        return (
            0.35 * _number(skills.get("Formation Command"))
            + 0.25 * _number(skills.get("Leadership"))
            + 0.15 * _number(skills.get("Logistics"))
            + 0.15 * _number(attrs.get("Awareness"))
            + 0.10 * _number(attrs.get("Intelligence"))
        )
    if task == "medical":
        return (
            0.65 * _number(skills.get("Medicine"))
            + 0.15 * _number(skills.get("Leadership"))
            + 0.10 * _number(skills.get("Logistics"))
            + 0.10 * _number(attrs.get("Intelligence"))
        )
    return 0.0


def task_efficiency(score: float, difficulty: float = 0.0) -> float:
    """Convert uncapped skill into bounded labor efficiency with difficulty drag.

    Skill has diminishing returns rather than a hard cap. A score of zero still
    permits ordinary labor at half baseline speed; technically difficult work is
    slower when leadership/technical capability is below the registered difficulty.
    """
    s = max(0.0, float(score))
    base = 0.5 + s / (100.0 + s)
    shortfall = max(0.0, float(difficulty) - s)
    return max(0.15, base / (1.0 + shortfall / 100.0))


def temporary_duty_personnel(personnel: int, task: str, *, minimum: int = 1) -> int:
    """Return the maximum ordinary manpower that may be assigned to one support task."""
    n = max(0, int(personnel))
    if n <= 0:
        return 0
    fraction = DUTY_FRACTIONS.get(str(task), 0.10)
    return min(n, max(int(minimum), int(math.floor(n * fraction))))


def blueprint_difficulty(blueprint: Mapping[str, Any]) -> float:
    return max(0.0, _number(blueprint.get("engineering_difficulty"), 20.0))


__all__ = [
    "DUTY_FRACTIONS",
    "FORBIDDEN_PERMANENT_SUPPORT_ROLES",
    "blueprint_difficulty",
    "task_efficiency",
    "task_leader_score",
    "temporary_duty_personnel",
]
