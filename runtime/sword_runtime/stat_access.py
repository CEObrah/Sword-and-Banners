"""Canonical access helpers for the split Sword & Banners skill ontology.

All military people carry the 21 core skills in their ordinary ``skills`` map.
The five professional disciplines are sparse and live in ``professional_skills``.
Person-lite records keep their core map under ``stats.skills`` but use the same
sparse top-level professional map. Callers that need a capability view should
merge on read rather than repadding every person with professional zeroes.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import PROFESSIONAL_SKILLS

_PROFESSIONAL = frozenset(PROFESSIONAL_SKILLS)


def is_professional_skill(skill: object) -> bool:
    return str(skill) in _PROFESSIONAL


def core_skill_map(person: Mapping[str, Any]) -> Mapping[str, Any]:
    stats = person.get("stats")
    if str(person.get("schema", "")) == "person-lite" or (
        not isinstance(person.get("skills"), Mapping)
        and isinstance(stats, Mapping)
        and isinstance(stats.get("skills"), Mapping)
    ):
        value = stats.get("skills", {}) if isinstance(stats, Mapping) else {}
    else:
        value = person.get("skills", {})
    return value if isinstance(value, Mapping) else {}


def mutable_core_skill_map(person: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    stats = person.get("stats")
    if str(person.get("schema", "")) == "person-lite" or (
        "skills" not in person and isinstance(stats, Mapping)
    ):
        if not isinstance(stats, MutableMapping):
            stats = {}
            person["stats"] = stats
        value = stats.get("skills")
        if not isinstance(value, MutableMapping):
            value = {}
            stats["skills"] = value
        return value
    value = person.get("skills")
    if not isinstance(value, MutableMapping):
        value = {}
        person["skills"] = value
    return value


def professional_skill_map(person: Mapping[str, Any]) -> Mapping[str, Any]:
    value = person.get("professional_skills", {})
    return value if isinstance(value, Mapping) else {}


def mutable_professional_skill_map(person: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    value = person.get("professional_skills")
    if not isinstance(value, MutableMapping):
        value = {}
        person["professional_skills"] = value
    return value


def merged_skill_map(person: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(core_skill_map(person))
    out.update(professional_skill_map(person))
    return out


def skill_container(person: MutableMapping[str, Any], skill: str) -> MutableMapping[str, Any]:
    if is_professional_skill(skill):
        return mutable_professional_skill_map(person)
    return mutable_core_skill_map(person)


def skill_value(person: Mapping[str, Any], skill: str, default: Any = 0) -> Any:
    if is_professional_skill(skill):
        return professional_skill_map(person).get(skill, default)
    return core_skill_map(person).get(skill, default)


def set_skill_value(person: MutableMapping[str, Any], skill: str, value: Any) -> None:
    skill_container(person, skill)[skill] = value


__all__ = [
    "core_skill_map",
    "is_professional_skill",
    "merged_skill_map",
    "mutable_core_skill_map",
    "mutable_professional_skill_map",
    "professional_skill_map",
    "set_skill_value",
    "skill_container",
    "skill_value",
]
