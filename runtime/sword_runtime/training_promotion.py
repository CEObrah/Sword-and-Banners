"""Deterministic promotion-threshold lookup for named military trainees.

Only registered progression records may bias adaptive training. A billet, prose role,
or current command span never invents a promotion threshold. When no lawful next gate
is registered, the returned mapping is empty and the closed program simply follows
role/loadout/weak-useful priorities.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any

_SWORD_PATH = "game/data/mil/sword-manor-progression.json"
_CHAMPION_PATH = "game/data/mil/house-tang-champion-progression.json"


def _record_facts(runtime: Any, path: str, record_id: str) -> Mapping[str, Any]:
    try:
        doc = runtime.read(path)
    except Exception:
        return {}
    for row in doc.get("records", []) if isinstance(doc, Mapping) else []:
        if isinstance(row, Mapping) and str(row.get("record_id", "")) == record_id:
            facts = row.get("facts")
            return facts if isinstance(facts, Mapping) else {}
    return {}


def exact_promotion_facts(runtime: Any, person: Mapping[str, Any]) -> Mapping[str, Any]:
    role = str(person.get("role", "")).lower()
    # Sword Manor institutional progression is explicit and stat-gated.
    if "sword manor" in role:
        if "trainee" in role:
            return _record_facts(runtime, _SWORD_PATH, "trainee_to_junior_disciple")
        if "junior disciple" in role:
            return _record_facts(runtime, _SWORD_PATH, "junior_to_general_disciple")
        if "general disciple" in role:
            return _record_facts(runtime, _SWORD_PATH, "general_to_senior_disciple")
        if "senior disciple" in role:
            return _record_facts(runtime, _SWORD_PATH, "sword_manor_officer")
        return {}
    if "guardian cavalry" in role:
        return _record_facts(runtime, _CHAMPION_PATH, "guardian_cavalry_to_tang_champion")
    if "house guard" in role and "guardian" not in role:
        return _record_facts(runtime, _SWORD_PATH, "house_guard_to_house_guardian_cavalry")
    return {}


__all__ = ["exact_promotion_facts"]
