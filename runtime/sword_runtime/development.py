from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Mapping, Sequence

from sword_runtime.sim.calendar import CampaignTime

_BIRTH = re.compile(r"^(?P<year>[0-9]{1,4})-BCE-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})$")

CAPABILITY_REFERENCE_VALUE = 200
ROUTINE_SKILL_TRAINING_CEILING = 180
_PREPARATION_BANK_MAX_FRACTION = Decimal("0.95")

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


def _next_skill_point_cost(score: int) -> float:
    return 18.0 * ((1.0 + score / 50.0) ** 1.75)


def _progression_values(training: Mapping[str, Any]) -> tuple[int, int, Decimal]:
    topology = training.get("progression_topology", {})
    if not isinstance(topology, Mapping):
        topology = {}
    routine = int(topology.get("routine_training_ceiling", ROUTINE_SKILL_TRAINING_CEILING))
    reference = int(topology.get("reference_value", CAPABILITY_REFERENCE_VALUE))
    fraction = Decimal(str(topology.get("preparation_bank_max_fraction_of_next_point", _PREPARATION_BANK_MAX_FRACTION)))
    if routine < 1 or reference < routine or not Decimal("0") < fraction < Decimal("1"):
        raise ValueError("invalid progression topology")
    return routine, reference, fraction


def settle_skill_training(
    person: dict[str, Any],
    skill: str,
    hours: int,
    at: CampaignTime,
    training: Mapping[str, Any],
    *,
    facility_grade: str = "adequate",
    equipment_grade: str = "adequate",
    recovery_grade: str = "adequate",
    practice_mode: str | None = None,
    intensity: str = "standard",
    feedback_grade: str = "ordinary",
    instruction_factor: float = 1.0,
    instructor_capacity_factor: float = 1.0,
    instructor_ref: str | None = None,
) -> dict[str, Any]:
    skills = person.setdefault("skills", {})
    if skill not in skills:
        raise ValueError(f"unknown trainable skill: {skill}")
    score = int(skills[skill])
    if score < 0:
        raise ValueError("saved skill must be nonnegative")
    routine_ceiling, reference_value, bank_fraction = _progression_values(training)
    aptitude = float(person.get("aptitude", {}).get(aptitude_key(skill), 100))
    if aptitude < 0:
        raise ValueError("saved aptitude must be nonnegative")
    potential_name, potential_factor = _potential(aptitude)
    age = age_years(person, at)
    age_factor = _age_factor(training, skill_category(skill), age)
    tables = training.get("factor_tables", {})
    self_factor = float(tables.get("self_practice", {}).get("default", 0.85))
    mode_factor = self_factor if practice_mode is None else float(tables.get("practice_mode", {}).get(practice_mode, self_factor))
    intensity_factor = float(tables.get("intensity", {}).get(intensity, 1.0))
    facility = float(tables.get("facility", {}).get(facility_grade, tables.get("facility", {}).get("adequate", 1.0)))
    equipment = float(tables.get("equipment", {}).get(equipment_grade, tables.get("equipment", {}).get("adequate", 0.92)))
    recovery = float(tables.get("recovery", {}).get(recovery_grade, tables.get("recovery", {}).get("adequate", 0.92)))
    feedback = float(tables.get("feedback", {}).get(feedback_grade, tables.get("feedback", {}).get("ordinary", 1.0)))
    instruction = max(0.0, min(1.35, float(instruction_factor)))
    instructor_capacity = max(0.0, min(1.0, float(instructor_capacity_factor)))
    health = 1.0 if str(person.get("health", person.get("health_status", "healthy"))) in {"healthy","fit","stable"} else 0.68
    aptitude_factor = max(0.25, min(3.0, aptitude / 100.0))
    raw = hours * mode_factor * intensity_factor * instruction * instructor_capacity * facility * equipment * recovery * feedback * health * age_factor * aptitude_factor * potential_factor
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
    effective = max(0.0, raw * max(0.05, diminishing))
    ds = person.setdefault("development_state", {})
    banks = ds.setdefault("skill_edu_banks", {})
    bank = float(banks.get(skill, 0.0)) + effective
    gained = 0
    while gained < 25 and score < routine_ceiling:
        cost = _next_skill_point_cost(score)
        if bank + 1e-9 < cost:
            break
        bank -= cost
        score += 1
        gained += 1
    if score >= routine_ceiling:
        preparation_cap = float(Decimal(str(_next_skill_point_cost(score))) * bank_fraction)
        bank = min(bank, preparation_cap)
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
        "routine_training_ceiling": routine_ceiling,
        "capability_reference_value": reference_value,
        "exceptional_progression_required": score >= routine_ceiling,
        "edu_bank_milli": int(round(bank * 1000)),
        "training_inputs": {
            "facility_grade": facility_grade,
            "equipment_grade": equipment_grade,
            "recovery_grade": recovery_grade,
            "practice_mode": practice_mode or "self_practice",
            "intensity": intensity,
            "feedback_grade": feedback_grade,
            "instruction_factor_milli": int(round(instruction * 1000)),
            "instructor_capacity_factor_milli": int(round(instructor_capacity * 1000)),
            "instructor_ref": instructor_ref,
        },
    }


def settle_combat_experience(person: dict[str, Any], focuses: Sequence[str] | Mapping[str, float], exposure_hours: float, at: CampaignTime, training: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Apply bounded role-relevant field experience without pretending battle is drill.

    Combat supplies execution-under-pressure EDU to skills only.  It does not directly
    raise physical attributes, and it is deliberately less technically efficient than
    deliberate practice.  Existing aptitude, age, soft ceilings, diminishing returns
    and routine ceilings remain authoritative.
    """
    skills = person.setdefault("skills", {})
    if isinstance(focuses, Mapping):
        raw_weights = {str(k): max(0.0, float(v)) for k, v in focuses.items() if str(k) in skills and float(v) > 0}
    else:
        valid_names = [str(x) for x in focuses if str(x) in skills]
        raw_weights = {name: 1.0 for name in valid_names}
    total_weight = sum(raw_weights.values())
    if total_weight <= 0 or exposure_hours <= 0:
        return []
    weights = {name: value / total_weight for name, value in raw_weights.items()}
    valid = list(weights)
    routine_ceiling, reference_value, bank_fraction = _progression_values(training)
    age = age_years(person, at)
    ds = person.setdefault("development_state", {})
    banks = ds.setdefault("skill_edu_banks", {})
    results: list[dict[str, Any]] = []
    for skill in valid:
        per_hours = max(0.0, float(exposure_hours)) * weights[skill]
        score = int(skills[skill])
        aptitude = float(person.get("aptitude", {}).get(aptitude_key(skill), 100))
        potential_name, potential_factor = _potential(aptitude)
        age_factor = _age_factor(training, skill_category(skill), age)
        field_efficiency = 0.48 if skill in COMMAND_SKILLS else 0.36
        health_raw = person.get("health", person.get("health_status", "healthy"))
        if isinstance(health_raw, Mapping):
            health_raw = health_raw.get("status", "healthy")
        health = 1.0 if str(health_raw) in {"healthy", "fit", "stable"} else 0.62
        aptitude_factor = max(0.25, min(3.0, aptitude / 100.0))
        raw = per_hours * field_efficiency * health * age_factor * aptitude_factor * potential_factor
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
        effective = max(0.0, raw * max(0.05, diminishing))
        bank = float(banks.get(skill, 0.0)) + effective
        gained = 0
        while gained < 12 and score < routine_ceiling:
            cost = _next_skill_point_cost(score)
            if bank + 1e-9 < cost:
                break
            bank -= cost
            score += 1
            gained += 1
        if score >= routine_ceiling:
            preparation_cap = float(Decimal(str(_next_skill_point_cost(score))) * bank_fraction)
            bank = min(bank, preparation_cap)
        skills[skill] = score
        banks[skill] = round(bank, 3)
        results.append({
            "skill": skill, "exposure_hours_milli": int(round(per_hours * 1000)), "exposure_weight_milli": int(round(weights[skill] * 1000)),
            "effective_edu_milli": int(round(effective * 1000)), "skill_points_gained": gained,
            "skill_score": score, "routine_training_ceiling": routine_ceiling,
            "capability_reference_value": reference_value, "edu_bank_milli": int(round(bank * 1000)),
        })
    ds["combat_experience_hours_milli"] = int(ds.get("combat_experience_hours_milli", 0)) + int(round(float(exposure_hours) * 1000))
    ds["completed_reviews"] = int(ds.get("completed_reviews", 0)) + 1
    return results


def _breakthrough_requirements(score: int) -> tuple[int, int, int, Decimal]:
    if score < CAPABILITY_REFERENCE_VALUE:
        return 2, 2, 7, Decimal("0.25")
    if score < 225:
        return 3, 2, 14, Decimal("0.35")
    return 4, 3, 30, Decimal("0.50")


def _event_ref(event: Mapping[str, Any]) -> str:
    ref = event.get("event_id", event.get("id"))
    if not isinstance(ref, str) or not ref:
        raise ValueError("breakthrough evidence requires a stable event id")
    return ref


def _event_involves(event: Mapping[str, Any], person_ref: str) -> bool:
    if event.get("person_ref") == person_ref or event.get("subject_ref") == person_ref:
        return True
    for key in ("actor_refs", "subject_refs", "participant_refs", "participants"):
        refs = event.get(key)
        if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes, bytearray)) and person_ref in refs:
            return True
    return False


def _event_context(event: Mapping[str, Any]) -> str:
    for key in ("mission_ref", "operation_ref", "battle_ref", "siege_ref", "project_ref", "location_ref", "theater_ref"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return f"{key}:{value}"
    hosts = event.get("host_refs")
    if isinstance(hosts, Sequence) and not isinstance(hosts, (str, bytes, bytearray)):
        first = next((str(x) for x in hosts if isinstance(x, str) and x), None)
        if first:
            return "host:" + first
    return "kind:" + str(event.get("kind", "unknown"))


def resolve_exceptional_skill_breakthrough(
    person: dict[str, Any],
    skill: str,
    evidence_events: Sequence[Mapping[str, Any]],
    at: CampaignTime,
    training: Mapping[str, Any],
) -> dict[str, Any]:
    """Advance one exact-person skill point from persisted, already-authored evidence.

    The function deliberately accepts full saved event records, not caller-asserted
    booleans. It verifies that every consumed event names the exact person, requires
    distinct contexts, consumes target-specific consolidation, enforces a persistent
    cooldown, and records one-use evidence. It never creates or infers an event.
    """
    person_ref = person.get("owner_id", person.get("id"))
    if not isinstance(person_ref, str) or not person_ref:
        raise ValueError("exceptional progression requires an exact persisted person")
    skills = person.get("skills")
    if not isinstance(skills, dict) or skill not in skills:
        raise ValueError("unknown exceptional skill target")
    score = int(skills[skill])
    routine_ceiling, reference_value, _bank_fraction = _progression_values(training)
    if score < routine_ceiling:
        raise ValueError("routine training remains authoritative below the exceptional threshold")
    evidence_count, distinct_contexts, cooldown_days, consolidation_fraction = _breakthrough_requirements(score)
    if len(evidence_events) < evidence_count:
        raise ValueError("exceptional progression evidence depth is insufficient")
    ds = person.setdefault("development_state", {})
    banks = ds.setdefault("skill_edu_banks", {})
    consumed = ds.setdefault("breakthrough_event_refs", [])
    dossiers = ds.setdefault("breakthrough_dossiers", {})
    dossier = dossiers.setdefault(skill, {})
    if not isinstance(consumed, list) or not isinstance(dossier, dict):
        raise ValueError("invalid exceptional progression state")
    last_raw = dossier.get("last_breakthrough_at")
    if isinstance(last_raw, str):
        last = CampaignTime.parse(last_raw)
        if at < last.add_seconds(cooldown_days * 86400):
            raise ValueError("exceptional progression cooldown is active")
    selected: list[str] = []
    contexts: set[str] = set()
    for event in evidence_events:
        ref = _event_ref(event)
        if ref in consumed or ref in selected:
            continue
        if not _event_involves(event, person_ref):
            continue
        selected.append(ref)
        contexts.add(_event_context(event))
        if len(selected) >= evidence_count and len(contexts) >= distinct_contexts:
            break
    if len(selected) < evidence_count:
        raise ValueError("exceptional progression lacks enough unused exact-person evidence")
    if len(contexts) < distinct_contexts:
        raise ValueError("exceptional progression evidence lacks contextual novelty")
    available = Decimal(str(banks.get(skill, 0.0)))
    required = Decimal(str(_next_skill_point_cost(score))) * consolidation_fraction
    if available < required:
        raise ValueError("exceptional progression consolidation is insufficient")
    banks[skill] = round(float(available - required), 3)
    skills[skill] = score + 1
    consumed.extend(selected)
    if len(consumed) > 512:
        del consumed[:-512]
    dossier.update({
        "last_breakthrough_at": str(at),
        "last_starting_value": score,
        "last_ending_value": score + 1,
        "last_evidence_refs": list(selected),
        "last_context_signatures": sorted(contexts),
        "last_consolidation_units": float(required),
        "resolved_breakthroughs": int(dossier.get("resolved_breakthroughs", 0)) + 1,
    })
    return {
        "skill": skill,
        "starting_value": score,
        "ending_value": score + 1,
        "evidence_event_refs": list(selected),
        "distinct_contexts": len(contexts),
        "consolidation_units": float(required),
        "capability_reference_value": reference_value,
    }


__all__ = [
    "CAPABILITY_REFERENCE_VALUE",
    "ROUTINE_SKILL_TRAINING_CEILING",
    "age_years",
    "resolve_exceptional_skill_breakthrough",
    "settle_skill_training",
]
