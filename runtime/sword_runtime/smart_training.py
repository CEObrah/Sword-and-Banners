"""Deterministic role-aware training focus selection.

This module does not grant training time. Existing chronology/training reducers
own verified hours and EDU. It only chooses *where already-lawful training time
is spent* so standing plans do not waste most of their time on already-maxed
skills while promotion-critical or loadout-critical capability lags behind.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from sword_runtime.cohort_personnel import ATTRIBUTE_ORDER, SKILL_ORDER, advance_cohort_training

_COMMAND_SKILLS = ("Leadership", "Formation Command", "Tactics", "Strategy", "Logistics", "Training")
_INFANTRY_CORE = ("Bow", "Spear", "Shield", "Defense", "Formation Fighting", "Mass Combat", "Athletics", "Survival")
_CAVALRY_CORE = ("Bow", "Spear", "Riding", "Shield", "Defense", "Formation Fighting", "Mass Combat", "Scouting")
_SCOUT_CORE = ("Scouting", "Navigation", "Survival", "Stealth", "Athletics", "Riding", "Bow", "Defense")
_LOGISTICS_CORE = ("Logistics", "Navigation", "Trade", "Engineering", "Medicine", "Leadership", "Training", "Mass Combat")
_ENGINEERING_CORE = ("Engineering", "Logistics", "Training", "Athletics", "Mass Combat", "Defense", "Crossbow", "Tactics")
_MISSILE_CORE = ("Bow", "Crossbow", "Defense", "Formation Fighting", "Mass Combat", "Athletics", "Scouting", "Survival")
_SIGNAL_CORE = ("Intelligence Operations", "Scouting", "Navigation", "Leadership", "Tactics", "Logistics", "Training", "Survival")


def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def contract_skill_candidates(person: Mapping[str, Any], contract: Mapping[str, Any]) -> list[str]:
    value = contract.get("focus")
    if isinstance(value, str):
        candidates = [part.strip() for part in value.split(",")]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        candidates = [str(part).strip() for part in value]
    else:
        candidates = []
    skills = person.get("skills") if isinstance(person.get("skills"), Mapping) else {}
    equipment = person.get("equipment_manifest") if isinstance(person.get("equipment_manifest"), Mapping) else {}
    items = equipment.get("items") if isinstance(equipment.get("items"), Mapping) else {}
    item_text = " ".join(str(v).lower() for v in items.values())
    if "bow" in item_text:
        candidates.append("Bow")
    if "lance" in item_text or "spear" in item_text:
        candidates.append("Spear")
    if "shield" in item_text:
        candidates.extend(("Shield", "Defense"))
    if "sword" in item_text:
        candidates.append("Sword")
    if "horse" in item_text or "mount" in item_text:
        candidates.append("Riding")
    role_text = " ".join(str(person.get(k, "")) for k in ("role", "authority", "current_goal")).lower()
    if any(token in role_text for token in ("commander", "deputy", "marshal", "officer", "command")):
        candidates.extend(_COMMAND_SKILLS)
    return [name for name in _dedupe(candidates) if name in skills]


def select_exact_focus(person: Mapping[str, Any], contract: Mapping[str, Any], cursor: int) -> str | None:
    """Choose one useful exact-person focus for the next already-earned cycle.

    Lowest saved skill is favored, while a small deterministic rotation among the
    weakest six prevents a permanent tunnel on one statistic. Declared standing
    plan and current equipment/command role bound the candidate set.
    """
    candidates = contract_skill_candidates(person, contract)
    skills = person.get("skills") if isinstance(person.get("skills"), Mapping) else {}
    if not candidates:
        return None
    order = {name: i for i, name in enumerate(candidates)}
    ranked = sorted(candidates, key=lambda name: (float(skills.get(name, 0.0)), order[name], name))
    window = ranked[: min(6, len(ranked))]
    return window[max(0, int(cursor)) % len(window)]


def role_core_skills(role: str) -> list[str]:
    text = str(role).lower()
    if any(token in text for token in ("scout", "recon", "ranger")):
        skills = list(_SCOUT_CORE)
    elif any(token in text for token in ("logistics", "supply", "quartermaster", "wagon")):
        skills = list(_LOGISTICS_CORE)
    elif any(token in text for token in ("engineer", "sapper", "siege")):
        skills = list(_ENGINEERING_CORE)
    elif any(token in text for token in ("crossbow", "archer", "missile", "bow guard")):
        skills = list(_MISSILE_CORE)
    elif any(token in text for token in ("signal", "intelligence")):
        skills = list(_SIGNAL_CORE)
    elif any(token in text for token in ("cavalry", "rider", "mounted", "champion")):
        skills = list(_CAVALRY_CORE)
    else:
        skills = list(_INFANTRY_CORE)
    if any(token in text for token in ("commander", "deputy", "officer", "champion", "senior", "general_disciple", "marshal")):
        skills.extend(_COMMAND_SKILLS)
    return _dedupe(skills)


def _threshold_map(order: Sequence[str], values: Any) -> dict[str, float]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return {}
    return {str(name): float(value) for name, value in zip(order, values)}


def select_cohort_focuses(
    cohort: Mapping[str, Any],
    *,
    role: str,
    role_profile: Mapping[str, Any],
    promotion_facts: Mapping[str, Any] | None = None,
    cursor: int = 0,
    skill_slots: int = 6,
    attribute_slots: int = 3,
) -> tuple[list[str], list[str]]:
    """Select bounded rotating cohort focuses from role, loadout and promotion deficits."""
    skills_now = cohort.get("skill_means") if isinstance(cohort.get("skill_means"), Mapping) else {}
    attrs_now = cohort.get("attribute_means") if isinstance(cohort.get("attribute_means"), Mapping) else {}
    base_skills = _dedupe([str(x) for x in role_profile.get("skills", [])] + role_core_skills(role))
    base_attrs = _dedupe([str(x) for x in role_profile.get("attributes", [])])
    facts = promotion_facts if isinstance(promotion_facts, Mapping) else {}
    skill_targets = _threshold_map(SKILL_ORDER, facts.get("minimum_skill_values"))
    attr_targets = _threshold_map(ATTRIBUTE_ORDER, facts.get("minimum_attribute_values"))

    def rank(names: list[str], now: Mapping[str, Any], targets: Mapping[str, float], slots: int) -> list[str]:
        if not names or slots <= 0:
            return []
        rows: list[tuple[float, float, str]] = []
        for name in names:
            current = float(now.get(name, 0.0))
            target = targets.get(name)
            deficit = max(0.0, float(target) - current) if target is not None else 0.0
            # Promotion deficit dominates; otherwise weaker useful stats rise first.
            score = deficit * 10.0 + max(0.0, 140.0 - current)
            if name in role_core_skills(role):
                score += 18.0
            if name in _COMMAND_SKILLS and any(t in str(role).lower() for t in ("commander", "officer", "champion", "senior", "general")):
                score += 12.0
            rows.append((-score, current, name))
        ranked = [name for _neg, _cur, name in sorted(rows)]
        if len(ranked) <= slots:
            return ranked
        # Rotate only the tail slot so core deficits remain continuously trained while
        # the wider useful set is revisited over long campaigns.
        fixed = ranked[: max(1, slots - 1)]
        tail = ranked[max(1, slots - 1):]
        if tail:
            fixed.append(tail[max(0, int(cursor)) % len(tail)])
        return _dedupe(fixed)[:slots]

    return rank(base_skills, skills_now, skill_targets, skill_slots), rank(base_attrs, attrs_now, attr_targets, attribute_slots)


def train_person_lite(
    person: dict[str, Any],
    *,
    deliberate_hours: float,
    role_exposure_hours: float,
    training_rules: Mapping[str, Any],
    facility_grade: str,
    equipment_grade: str,
    recovery_grade: str,
    evidence_ref: str,
) -> dict[str, Any]:
    """Advance one already-materialized conserved person-lite body.

    The same aggregate EDU law is reused through a one-body cohort-shaped view.
    No headcount field is touched and no new person is created.
    """
    stats = person.get("stats") if isinstance(person.get("stats"), Mapping) else {}
    skills = stats.get("skills") if isinstance(stats.get("skills"), Mapping) else {}
    attrs = stats.get("attributes") if isinstance(stats.get("attributes"), Mapping) else {}
    if not skills or not attrs:
        return {"trained": False, "reason": "missing_person_lite_stats"}
    dev = person.setdefault("development_state", {})
    cursor = max(0, int(dev.get("smart_training_cursor", 0)))
    role = str(person.get("role", person.get("rank", "officer")))
    profile = {"skills": _dedupe(role_core_skills(role) + list(_COMMAND_SKILLS)), "attributes": list(ATTRIBUTE_ORDER)}
    pseudo = {
        "skill_means": deepcopy(dict(skills)),
        "attribute_means": deepcopy(dict(attrs)),
        "skill_edu_banks": deepcopy(dev.get("skill_edu_banks", {})) if isinstance(dev.get("skill_edu_banks"), Mapping) else {},
        "attribute_edu_banks": deepcopy(dev.get("attribute_edu_banks", {})) if isinstance(dev.get("attribute_edu_banks"), Mapping) else {},
        "aptitude_means": deepcopy(person.get("aptitude", {})) if isinstance(person.get("aptitude"), Mapping) else {},
        "age_distribution": {"mean": 28.0},
    }
    skill_focuses, attr_focuses = select_cohort_focuses(
        pseudo, role=role, role_profile=profile, promotion_facts=None, cursor=cursor, skill_slots=6, attribute_slots=3
    )
    result = advance_cohort_training(
        pseudo,
        deliberate_hours=deliberate_hours,
        role_exposure_hours=role_exposure_hours,
        skill_focuses=skill_focuses,
        attribute_focuses=attr_focuses,
        training_rules=training_rules,
        facility_grade=facility_grade,
        equipment_grade=equipment_grade,
        recovery_grade=recovery_grade,
        practice_mode="drill",
        evidence_ref=evidence_ref,
    )
    person.setdefault("stats", {})["skills"] = pseudo["skill_means"]
    person["stats"]["attributes"] = pseudo["attribute_means"]
    dev["skill_edu_banks"] = pseudo.get("skill_edu_banks", {})
    dev["attribute_edu_banks"] = pseudo.get("attribute_edu_banks", {})
    dev["smart_training_cursor"] = cursor + 1
    dev["verified_training_hours"] = round(float(dev.get("verified_training_hours", 0.0)) + max(0.0, deliberate_hours), 3)
    dev["verified_role_exposure_hours"] = round(float(dev.get("verified_role_exposure_hours", 0.0)) + max(0.0, role_exposure_hours), 3)
    history = dev.setdefault("training_history", [])
    history.append({"evidence_ref": evidence_ref, "skill_focuses": skill_focuses, "attribute_focuses": attr_focuses, "deliberate_hours": round(deliberate_hours, 3), "role_exposure_hours": round(role_exposure_hours, 3)})
    dev["training_history"] = history[-24:]
    return {"trained": True, **result, "skill_focuses": skill_focuses, "attribute_focuses": attr_focuses}


__all__ = [
    "contract_skill_candidates",
    "select_exact_focus",
    "role_core_skills",
    "select_cohort_focuses",
    "train_person_lite",
]
