"""Shared exact-person deliberate-training stimulus and standing recovery.

Skill EDU remains owned by ``development.settle_skill_training``. Aggregate
cohorts remain owned by ``cohort_personnel.advance_cohort_training``. This module
closes the representation gap between them: an exact person doing verified
training receives low, role-relevant attribute stimulus under the same aggregate
attribute point-cost law, while multi-day standing training accounts for the
ordinary nightly recovery already implied by its elapsed calendar window.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.cohort_personnel import _advance_score_mean
from sword_runtime.development import age_years, settle_skill_training
from sword_runtime.sim.calendar import CampaignTime


def _health_factor(person: Mapping[str, Any]) -> float:
    raw = person.get("health", person.get("health_status", "healthy"))
    if isinstance(raw, Mapping):
        raw = raw.get("status", "healthy")
    return 1.0 if str(raw).lower() in {"healthy", "fit", "stable"} else 0.68


def _age_factor(training: Mapping[str, Any], category: str, age: int) -> float:
    rows = training.get("age_factors", {}).get(category, [])
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return 1.0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        lo = int(row.get("min_age", 0))
        raw_hi = row.get("max_age", 999)
        hi = 999 if raw_hi is None else int(raw_hi)
        if lo <= age <= hi:
            return float(row.get("factor", 1.0))
    return 1.0


def settle_training_session(
    person: dict[str, Any],
    skill: str,
    hours: int,
    at: CampaignTime,
    training: Mapping[str, Any],
    session_rules: Mapping[str, Any],
) -> dict[str, Any]:
    """Settle one exact-person skill focus plus its low attribute stimulus.

    The returned mapping preserves the established skill-result keys and adds an
    ``attribute_development`` list. Attribute banks are persistent, so elite
    people may show no integer point this cycle while still making real progress.
    """

    result = settle_skill_training(person, skill, hours, at, training)
    attributes = person.get("attributes")
    if not isinstance(attributes, dict):
        result["attribute_development"] = []
        return result

    stimulus_registry = session_rules.get("skill_attribute_stimulus", {})
    raw_targets = stimulus_registry.get(skill, []) if isinstance(stimulus_registry, Mapping) else []
    if not isinstance(raw_targets, Sequence) or isinstance(raw_targets, (str, bytes, bytearray)):
        raw_targets = []
    targets = [str(name) for name in raw_targets if str(name) in attributes]
    if not targets:
        result["attribute_development"] = []
        return result

    share = float(training.get("share_limits", {}).get("attribute_stimulus", 0.35) or 0.0)
    share = max(0.0, min(1.0, share))
    if share <= 0:
        result["attribute_development"] = []
        return result

    tables = training.get("factor_tables", {})
    self_factor = float(tables.get("self_practice", {}).get("default", 0.85))
    facility = float(tables.get("facility", {}).get("adequate", 1.0))
    equipment = float(tables.get("equipment", {}).get("adequate", 0.92))
    recovery = float(tables.get("recovery", {}).get("adequate", 0.92))
    health = _health_factor(person)
    age = age_years(person, at)
    aptitude = person.get("aptitude", {}) if isinstance(person.get("aptitude"), Mapping) else {}
    aptitude_map = session_rules.get("attribute_aptitude_map", {})
    category_map = session_rules.get("attribute_age_category_map", {})
    ceilings = training.get("potential_soft_ceilings", {})
    ds = person.setdefault("development_state", {})
    banks = ds.setdefault("attribute_edu_banks", {})
    per_target_hours = max(0.0, float(hours)) * share / len(targets)
    development: list[dict[str, Any]] = []

    for attribute in targets:
        aptitude_key = str(aptitude_map.get(attribute, "physical_learning")) if isinstance(aptitude_map, Mapping) else "physical_learning"
        apt = float(aptitude.get(aptitude_key, 100.0))
        if apt < 0:
            raise ValueError("saved aptitude must be nonnegative")
        category = str(category_map.get(attribute, "physical_attribute")) if isinstance(category_map, Mapping) else "physical_attribute"
        age_factor = _age_factor(training, category, age)
        aptitude_factor = max(0.25, min(2.0, apt / 100.0))
        raw_edu = per_target_hours * self_factor * facility * equipment * recovery * health * age_factor * aptitude_factor
        before_score = float(attributes.get(attribute, 0.0))
        before_bank = float(banks.get(attribute, 0.0))
        after_score, after_bank = _advance_score_mean(
            before_score,
            before_bank,
            raw_edu,
            aptitude=apt,
            potential_ceilings=ceilings,
            kind="attribute",
        )
        attributes[attribute] = int(after_score) if float(after_score).is_integer() else after_score
        banks[attribute] = after_bank
        development.append(
            {
                "attribute": attribute,
                "age": age,
                "aptitude": int(round(apt)),
                "stimulus_hours_milli": int(round(per_target_hours * 1000)),
                "raw_edu_milli": int(round(raw_edu * 1000)),
                "attribute_points_gained": int(round(after_score - before_score)),
                "attribute_score": attributes[attribute],
                "edu_bank_milli": int(round(after_bank * 1000)),
            }
        )

    ds["attribute_stimulus_hours_milli"] = int(ds.get("attribute_stimulus_hours_milli", 0)) + int(round(float(hours) * share * 1000))
    result["attribute_development"] = development
    return result


def standing_recovery_result(
    *,
    fatigue: int,
    started_at: CampaignTime,
    completed_at: CampaignTime,
    completed_deliberate_hours: float,
    normal_deliberate_hours_per_7d: float,
    session_rules: Mapping[str, Any],
) -> dict[str, Any]:
    """Net chronic fatigue for a distributed standing-training window.

    Full elapsed days contribute ordinary nightly recovery. Training inside the
    normal weekly deliberate ceiling adds no residual chronic fatigue; only the
    hours beyond that ceiling add overload. Acute single-session fatigue remains
    owned by immediate-training reducers and is intentionally not handled here.
    """

    if completed_at < started_at:
        raise ValueError("standing recovery window is inverted")
    elapsed_seconds = max(0, started_at.seconds_until(completed_at))
    elapsed_hours = elapsed_seconds / 3600.0
    rules = session_rules.get("standing_recovery", {}) if isinstance(session_rules, Mapping) else {}
    recovery_per_day = max(0.0, float(rules.get("fatigue_recovery_per_24h", 8.0) or 0.0))
    excess_cost = max(0.0, float(rules.get("excess_deliberate_training_fatigue_per_hour", 0.5) or 0.0))
    recovery_points = int(math.floor((elapsed_hours / 24.0) * recovery_per_day + 1e-9))
    normal_capacity = max(0.0, float(normal_deliberate_hours_per_7d)) * elapsed_hours / (7.0 * 24.0)
    excess_hours = max(0.0, float(completed_deliberate_hours) - normal_capacity)
    overload_points = int(math.ceil(excess_hours * excess_cost - 1e-9)) if excess_hours > 0 else 0
    before = max(0, min(100, int(fatigue)))
    after = max(0, min(100, before - recovery_points + overload_points))
    return {
        "fatigue_before": before,
        "fatigue_after": after,
        "elapsed_recovery_hours": round(elapsed_hours, 3),
        "recovery_points": recovery_points,
        "normal_deliberate_capacity_hours": round(normal_capacity, 3),
        "excess_deliberate_hours": round(excess_hours, 3),
        "overload_fatigue_points": overload_points,
    }


__all__ = ["settle_training_session", "standing_recovery_result"]
