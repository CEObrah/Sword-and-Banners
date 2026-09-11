"""Shared deterministic House nobility rules.

Nobility is formal political standing, not a second economy or force owner.  The
hot House record stores only the current grade and compact provenance.  Court
precedence and other consequences are derived from canonical game data.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RULES_PATH = "game/data/mechanics/nobility.json"
DEFAULT_GRADE = "recognized_house"


def grade_order(rules: Mapping[str, Any]) -> dict[str, int]:
    return {str(k): int(v) for k, v in (rules.get("grade_order") or {}).items()}


def grade_profile(rules: Mapping[str, Any], grade: str) -> Mapping[str, Any]:
    profiles = rules.get("grades") if isinstance(rules.get("grades"), Mapping) else {}
    profile = profiles.get(str(grade)) if isinstance(profiles, Mapping) else None
    if not isinstance(profile, Mapping):
        raise ValueError(f"unknown House nobility grade: {grade}")
    return profile


def ensure_nobility_state(house: dict[str, Any], rules: Mapping[str, Any], *, default_grade: str = DEFAULT_GRADE) -> dict[str, Any]:
    order = grade_order(rules)
    if default_grade not in order:
        raise ValueError("default House nobility grade is not registered")
    current = house.get("nobility")
    if not isinstance(current, Mapping):
        current = {"grade": default_grade}
    else:
        current = dict(current)
    grade = str(current.get("grade", default_grade))
    if grade not in order:
        raise ValueError(f"House has invalid nobility grade: {grade}")
    current["grade"] = grade
    # Derived rank numbers/benefits are deliberately not persisted here.
    house["nobility"] = current
    return current


def next_grade(rules: Mapping[str, Any], current_grade: str) -> str | None:
    order = grade_order(rules)
    if current_grade not in order:
        raise ValueError(f"unknown current House nobility grade: {current_grade}")
    rows = sorted(order.items(), key=lambda kv: kv[1])
    for idx, (grade, _value) in enumerate(rows):
        if grade == current_grade:
            return rows[idx + 1][0] if idx + 1 < len(rows) else None
    return None


def apply_nobility_grant(
    house: dict[str, Any],
    rules: Mapping[str, Any],
    *,
    target_grade: str,
    grantor_ref: str,
    evidence_ref: str,
    at: str,
    grant_ref: str,
) -> dict[str, Any]:
    state = ensure_nobility_state(house, rules)
    order = grade_order(rules)
    current_grade = str(state["grade"])
    target_grade = str(target_grade)
    if target_grade not in order:
        raise ValueError("unknown target House nobility grade")
    if order[target_grade] <= order[current_grade]:
        raise ValueError("nobility advancement requires a higher House grade")
    normal_steps = max(1, int((rules.get("grant_rules") or {}).get("normal_max_grade_steps_per_grant", 1)))
    rows = [g for g, _ in sorted(order.items(), key=lambda kv: kv[1])]
    current_idx = rows.index(current_grade)
    target_idx = rows.index(target_grade)
    if target_idx - current_idx > normal_steps:
        raise ValueError("normal nobility grant may advance only one registered grade at a time")
    if not str(grantor_ref):
        raise ValueError("nobility advancement requires a lawful grantor")
    if not str(evidence_ref):
        raise ValueError("nobility advancement requires saved evidence")
    state.update({
        "grade": target_grade,
        "last_changed_at": str(at),
        "last_grant_ref": str(grant_ref),
        "last_grantor_ref": str(grantor_ref),
        "last_evidence_ref": str(evidence_ref),
    })
    house["nobility"] = state
    return state


def derived_nobility_effects(house: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    current = house.get("nobility") if isinstance(house.get("nobility"), Mapping) else {}
    grade = str(current.get("grade", DEFAULT_GRADE))
    profile = grade_profile(rules, grade)
    return {"grade": grade, **{str(k): v for k, v in profile.items()}}


__all__ = [
    "DEFAULT_GRADE",
    "RULES_PATH",
    "apply_nobility_grant",
    "derived_nobility_effects",
    "ensure_nobility_state",
    "grade_order",
    "grade_profile",
    "next_grade",
]
