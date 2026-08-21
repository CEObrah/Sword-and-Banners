"""Sparse political-coalition lifecycle with zero duplicated material authority.

A faction is membership, goals, cohesion, influence and bounded political resources.
It never owns a member House's estate, troops, office or treasury merely because the
member joined. Splits transfer members/resources; they do not clone them.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

_FACTION_PROFILES = "game/data/politics/faction-profiles.json"
_NOBILITY_RULES = "game/data/mechanics/nobility.json"
_OWNER_INDEX = "state/index/owner-index.json"


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(value)))


def _unique(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(v) for v in values if isinstance(v, str) and v})


def _member_exists(planner: Any, ref: str) -> bool:
    try:
        planner.read(planner.owner_path(ref))
        return True
    except (KeyError, ValueError, FileNotFoundError):
        return False


def _person_weight(planner: Any, ref: str) -> int:
    try:
        person = planner.read(planner.owner_path(ref))
    except (KeyError, ValueError, FileNotFoundError):
        return 0
    rank = person.get("military_rank", {}) if isinstance(person, Mapping) else {}
    grade = str(rank.get("grade", "")) if isinstance(rank, Mapping) else ""
    rank_points = {
        "great_general": 12, "general": 8, "5000_commander": 6,
        "3000_commander": 5, "1000_commander": 4, "500_commander": 3,
        "100_commander": 2,
    }.get(grade, 1)
    offices = person.get("offices", person.get("office")) if isinstance(person, Mapping) else None
    office_points = min(6, len(offices)) if isinstance(offices, list) else (2 if offices else 0)
    return rank_points + office_points


def _house_weight(planner: Any, ref: str) -> int:
    try:
        house = planner.read(planner.owner_path(ref))
    except (KeyError, ValueError, FileNotFoundError):
        return 0
    nobility = house.get("nobility", {}) if isinstance(house, Mapping) else {}
    grade = str(nobility.get("grade", "unranked_house")) if isinstance(nobility, Mapping) else "unranked_house"
    rules = planner.read(_NOBILITY_RULES)
    row = rules.get("grades", {}).get(grade, {}) if isinstance(rules, Mapping) else {}
    points = int(row.get("faction_weight_points", 0)) if isinstance(row, Mapping) else 0
    if isinstance(house, Mapping) and isinstance(house.get("military_force_ref"), str):
        points += 3
    if isinstance(house, Mapping) and isinstance(house.get("treasury_ref"), str):
        points += 2
    return max(1, points)


def faction_member_influence(planner: Any, faction: Mapping[str, Any]) -> dict[str, Any]:
    people = _unique(faction.get("person_member_refs", []))
    houses = _unique(faction.get("house_member_refs", []))
    person_points = sum(_person_weight(planner, ref) for ref in people)
    house_points = sum(_house_weight(planner, ref) for ref in houses)
    return {
        "person_member_count": len(people), "house_member_count": len(houses),
        "person_points": person_points, "house_points": house_points,
        "total_points": person_points + house_points,
    }


def join_faction(planner: Any, *, faction_ref: str, member_ref: str, member_kind: str, at: str, basis: str) -> dict[str, Any]:
    path = planner.owner_path(faction_ref); doc = copy.deepcopy(planner.read(path))
    if str(doc.get("status", "active")) == "dissolved":
        raise ValueError("cannot join a dissolved faction")
    if not _member_exists(planner, member_ref):
        raise ValueError("faction member must already exist as an exact person or House")
    key = "house_member_refs" if member_kind == "house" else "person_member_refs"
    values = _unique(doc.get(key, []));
    if member_ref not in values: values.append(member_ref)
    doc[key] = sorted(values)
    doc.setdefault("membership_history", []).append({"at": at, "action": "join", "member_ref": member_ref, "member_kind": member_kind, "basis": basis})
    doc["membership_history"] = doc["membership_history"][-24:]
    doc["derived_member_influence"] = faction_member_influence(planner, doc)
    planner.put(path, doc); return doc


def leave_faction(planner: Any, *, faction_ref: str, member_ref: str, at: str, basis: str) -> dict[str, Any]:
    path = planner.owner_path(faction_ref); doc = copy.deepcopy(planner.read(path)); removed = False
    for key in ("person_member_refs", "house_member_refs"):
        values = _unique(doc.get(key, []))
        if member_ref in values:
            values.remove(member_ref); doc[key] = values; removed = True
    if removed:
        doc.setdefault("membership_history", []).append({"at": at, "action": "leave", "member_ref": member_ref, "basis": basis})
        doc["membership_history"] = doc["membership_history"][-24:]
    doc["derived_member_influence"] = faction_member_influence(planner, doc)
    planner.put(path, doc); return doc


def _split_resource_map(source: dict[str, Any]) -> dict[str, Any]:
    transferred: dict[str, Any] = {}
    for key in sorted(source):
        value = source.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            moved = value // 2 if isinstance(value, int) else value / 2.0
            source[key] = value - moved; transferred[key] = moved
    return transferred


def split_faction(planner: Any, *, faction_ref: str, at: str, basis: str) -> str | None:
    source_path = planner.owner_path(faction_ref); source = copy.deepcopy(planner.read(source_path))
    people = _unique(source.get("person_member_refs", [])); houses = _unique(source.get("house_member_refs", []))
    members = [("person", x) for x in people] + [("house", x) for x in houses]
    if len(members) < 4: return None
    ordered = sorted(members, key=lambda row: hashlib.sha256(f"{faction_ref}|{at}|{row[0]}|{row[1]}".encode()).hexdigest())
    moved = ordered[len(ordered)//2:]
    moved_people = sorted(ref for kind, ref in moved if kind == "person")
    moved_houses = sorted(ref for kind, ref in moved if kind == "house")
    source["person_member_refs"] = sorted(set(people) - set(moved_people)); source["house_member_refs"] = sorted(set(houses) - set(moved_houses))
    resources = source.setdefault("resources", {}); transferred = _split_resource_map(resources) if isinstance(resources, dict) else {}
    digest = hashlib.sha256(f"{faction_ref}|{at}|split".encode()).hexdigest()[:10]
    new_ref = f"faction_dynamic_{digest}"; new_path = f"state/factions/{new_ref}.json"
    goals = [str(x) for x in source.get("goals", []) if isinstance(x, str)]
    new_doc = {
        "schema": "sword-faction-agenda", "owner_id": new_ref,
        "name": f"{source.get('name', faction_ref)} Dissident Coalition",
        "status": "active", "state": source.get("state"), "scope": source.get("scope"),
        "goals": goals[-1:] or ["pursue member interests through lawful political coalition"],
        "knowledge": [], "resources": transferred,
        "person_member_refs": moved_people, "house_member_refs": moved_houses,
        "cohesion": 45, "pressure": max(0, int(source.get("pressure", 0)) // 2),
        "review_seconds": int(source.get("review_seconds", 30*86400)),
        "formed_at": at, "formation_basis": basis,
    }
    new_doc["derived_member_influence"] = faction_member_influence(planner, new_doc)
    source["cohesion"] = max(20, int(source.get("cohesion", 20)) + 15)
    source["derived_member_influence"] = faction_member_influence(planner, source)
    source.setdefault("membership_history", []).append({"at": at, "action": "split", "new_faction_ref": new_ref, "basis": basis})
    source["membership_history"] = source["membership_history"][-24:]
    index = copy.deepcopy(planner.read(_OWNER_INDEX)); owners = index.setdefault("owners", {})
    if new_ref in owners: return None
    owners[new_ref] = new_path
    planner.put(new_path, new_doc); planner.put(_OWNER_INDEX, index); planner.put(source_path, source)
    return new_ref


def dissolve_faction(planner: Any, *, faction_ref: str, at: str, basis: str) -> None:
    path = planner.owner_path(faction_ref); doc = copy.deepcopy(planner.read(path))
    doc["status"] = "dissolved"; doc["dissolved_at"] = at; doc["dissolution_basis"] = basis
    doc["person_member_refs"] = []; doc["house_member_refs"] = []
    planner.put(path, doc)


class PoliticalEcologyMixin:
    def _autonomy_faction(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_faction(host, occurrences, at)
        ref = str(host.get("owner_ref", ""))
        if not ref or ref.startswith("faction_occupation_revolt_"): return
        try: path = self.owner_path(ref); doc = copy.deepcopy(self.read(path))
        except (KeyError, ValueError, FileNotFoundError): return
        if str(doc.get("status", "active")) == "dissolved": return
        profiles = self.read(_FACTION_PROFILES).get("profiles", {})
        profile = profiles.get(ref, {}) if isinstance(profiles, Mapping) else {}
        if not doc.get("membership_initialized"):
            seeded_people = _unique(doc.get("person_member_refs", [])) or _unique(profile.get("representative_refs", []) if isinstance(profile, Mapping) else [])
            seeded_houses = _unique(doc.get("house_member_refs", [])) or _unique(profile.get("house_member_refs", []) if isinstance(profile, Mapping) else [])
            doc["person_member_refs"] = [x for x in seeded_people if _member_exists(self, x)]
            doc["house_member_refs"] = [x for x in seeded_houses if _member_exists(self, x)]
            doc["membership_initialized"] = True
            if isinstance(profile, Mapping) and not doc.get("state"): doc["state"] = profile.get("state")
            doc.setdefault("status", "active"); doc.setdefault("cohesion", 60)
        cohesion = int(doc.get("cohesion", 60))
        if doc.get("last_blocked_reason"): cohesion -= 2 * max(1, int(occurrences))
        elif isinstance(doc.get("last_action"), Mapping): cohesion += 1 * max(1, int(occurrences))
        if int(doc.get("pressure", 0)) >= 80: cohesion -= max(1, int(occurrences))
        doc["cohesion"] = _clamp(cohesion)
        doc["derived_member_influence"] = faction_member_influence(self, doc)
        self.put(path, doc)
        total_members = doc["derived_member_influence"]["person_member_count"] + doc["derived_member_influence"]["house_member_count"]
        if doc["cohesion"] <= 5 and total_members >= 4:
            split_faction(self, faction_ref=ref, at=at, basis="sustained low faction cohesion")
        elif doc["cohesion"] <= 10 and total_members >= 3:
            candidates = [("person",x) for x in _unique(doc.get("person_member_refs",[]))] + [("house",x) for x in _unique(doc.get("house_member_refs",[]))]
            if candidates:
                _kind, member = sorted(candidates, key=lambda row: hashlib.sha256(f"{ref}|{at}|leave|{row[1]}".encode()).hexdigest())[-1]
                leave_faction(self, faction_ref=ref, member_ref=member, at=at, basis="sustained low faction cohesion")


__all__ = ["PoliticalEcologyMixin", "faction_member_influence", "join_faction", "leave_faction", "split_faction", "dissolve_faction"]
