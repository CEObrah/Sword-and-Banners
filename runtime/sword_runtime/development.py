from __future__ import annotations

import math
import re
from typing import Any, Mapping

from sword_runtime.sim.calendar import CampaignTime

_BIRTH = re.compile(r"^(?P<year>[0-9]{1,4})-BCE-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})$")

# Sword's authored current-performance tables top out at 200. Soft potential
# ceilings control how difficult exceptional development becomes; they are not
# themselves a numerical bound. This absolute scale guard prevents arbitrarily
# long time horizons from increasing an exact skill forever.
ABSOLUTE_SKILL_HARD_CAP = 200

PHYSICAL_SKILLS = {
    "Athletics","Axe","Bow","Crossbow","Dagger","Defense","Glaive","Grappling","Mace","Riding",
    "Shield","Spear","Staff","Stealth","Survival","Sword","Unarmed","Formation Fighting"
}
COMMAND_SKILLS = {
    "Formation Command","Leadership","Logistics","Mass Combat","Strategy","Tactics","Governance","Law",
    "Diplomacy","Intelligence Operations","Trade","Training"
}


def age_years(person: Mapping[str, Any], at: CampaignTime) -> int:
    value = person.get("birth_date")
    if not isinstance(value, str):
        return max(0, int(person.get("life_course_age_index", 25)))
    m = _BIRTH.fullmatch(value)
    if not m:
        return max(0, int(person.get("life_course_age_index", 25)))
    birth_year = int(m.group("year")); birth_month = int(m.group("month")); birth_day = int(m.group("day"))
    age = birth_year - at.bce_year
    if (at.month, at.day) < (birth_month, birth_day):
        age -= 1
    return max(0, age)


def skill_category(skill: str) -> str:
    if skill in PHYSICAL_SKILLS:
        return "physical_or_martial_skill"
    if skill in COMMAND_SKILLS:
        return "command_or_civil_skill"
    return "mental_skill"


def aptitude_key(skill: str) -> str:
    if skill in PHYSICAL_SKILLS:
        return "physical_learning"
    if skill in {"Formation Command","Leadership","Logistics","Mass Combat","Strategy","Tactics","Intelligence Operations","Training"}:
        return "tactical_learning"
    if skill in {"Engineering","Medicine","Navigation","Scouting"}:
        return "technical_learning"
    if skill in {"Diplomacy","Intrigue","Trade"}:
        return "social_learning"
    return "academic_learning"


def _age_factor(training: Mapping[str, Any], category: str, age: int) -> float:
    rows = training.get("age_factors", {}).get(category, [])
    for row in rows:
        if int(row.get("min_age", 0)) <= age <= int(row.get("max_age", 999)):
            return float(row.get("factor", 1.0))
    return 1.0


def _potential(aptitude: float) -> tuple[str, float]:
    if aptitude >= 190: return "legendary", 1.36
    if aptitude >= 175: return "heroic", 1.24
    if aptitude >= 150: return "exceptional", 1.12
    if aptitude >= 120: return "capable", 1.0
    return "common", 0.9


def settle_skill_training(person: dict[str, Any], skill: str, hours: int, at: CampaignTime, training: Mapping[str, Any]) -> dict[str, Any]:
    skills = person.setdefault("skills", {})
    if skill not in skills:
        raise ValueError(f"unknown trainable skill: {skill}")
    score = int(skills[skill])
    if score > ABSOLUTE_SKILL_HARD_CAP:
        raise ValueError("saved skill exceeds the absolute Sword progression scale")
    aptitude = float(person.get("aptitude", {}).get(aptitude_key(skill), 100))
    potential_name, potential_factor = _potential(aptitude)
    age = age_years(person, at)
    age_factor = _age_factor(training, skill_category(skill), age)
    tables = training.get("factor_tables", {})
    self_factor = float(tables.get("self_practice", {}).get("default", 0.85))
    facility = float(tables.get("facility", {}).get("adequate", 1.0))
    equipment = float(tables.get("equipment", {}).get("adequate", 0.92))
    recovery = float(tables.get("recovery", {}).get("adequate", 0.92))
    health = 1.0 if str(person.get("health", person.get("health_status", "healthy"))) in {"healthy","fit","stable"} else 0.68
    aptitude_factor = max(0.25, min(2.0, aptitude / 100.0))
    raw = hours * self_factor * facility * equipment * recovery * health * age_factor * aptitude_factor * potential_factor
    ceilings = training.get("potential_soft_ceilings", {}).get("skill", {})
    ceiling = float(ceilings.get(potential_name, 100))
    if score <= ceiling - 20:
        diminishing = 1.0
    elif score <= ceiling:
        diminishing = 1.0 - (score - (ceiling - 20)) * (0.55 / 20.0)
    elif score <= ceiling + 20:
        diminishing = 0.45 - (score - ceiling) * (0.35 / 20.0)
    else:
        diminishing = 0.05
    effective = 0.0 if score >= ABSOLUTE_SKILL_HARD_CAP else max(0.0, raw * max(0.05, diminishing))
    ds = person.setdefault("development_state", {})
    banks = ds.setdefault("skill_edu_banks", {})
    bank = float(banks.get(skill, 0.0)) + effective
    gained = 0
    while gained < 25 and score < ABSOLUTE_SKILL_HARD_CAP:
        cost = 18.0 * ((1.0 + score / 50.0) ** 1.75)
        if bank + 1e-9 < cost:
            break
        bank -= cost
        score += 1
        gained += 1
    skills[skill] = score
    banks[skill] = round(bank, 3)
    ds["settled_training_hours"] = int(ds.get("settled_training_hours", 0)) + hours
    ds["training_credit"] = 0.0
    ds["completed_reviews"] = int(ds.get("completed_reviews", 0)) + 1
    return {
        "skill": skill,
        "hours": hours,
        "age": age,
        "aptitude": int(round(aptitude)),
        "effective_edu_milli": int(round(effective * 1000)),
        "skill_points_gained": gained,
        "skill_score": score,
        "skill_hard_cap": ABSOLUTE_SKILL_HARD_CAP,
        "edu_bank_milli": int(round(bank * 1000)),
    }


__all__ = ["ABSOLUTE_SKILL_HARD_CAP", "age_years", "settle_skill_training"]
