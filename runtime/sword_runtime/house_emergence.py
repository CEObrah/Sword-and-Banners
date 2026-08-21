"""Sparse autonomous House emergence from already-conserved exact people.

A new House is a political/kinship owner, never a population generator.  Formation
reclassifies one already-existing exact person as the founding member and creates
no land, silver, force, office, nobility grant, spouse, child, or retainer.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.history_store import iter_history_events, write_history_index

NOBILITY_RULES_PATH = "game/data/mechanics/nobility.json"
OWNER_INDEX_PATH = "state/index/owner-index.json"


def _state_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("state_", "")
    aliases = {
        "independent mountain confederation": "yotanwa_confederation",
        "mountain confederation": "yotanwa_confederation",
    }
    return aliases.get(text, text)


def _safe_token(text: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return token[:64] or "new_house"


def _existing_person_house(person: Mapping[str, Any]) -> str | None:
    direct = person.get("house_ref")
    if isinstance(direct, str) and direct:
        return direct
    household = person.get("household") if isinstance(person.get("household"), Mapping) else {}
    ref = household.get("house_ref") if isinstance(household, Mapping) else None
    return str(ref) if isinstance(ref, str) and ref else None


def form_house_from_existing_person(
    planner,
    *,
    founder_ref: str,
    state: str,
    at: str,
    evidence_ref: str,
    house_ref: str | None = None,
    house_name: str | None = None,
) -> dict[str, Any]:
    """Create one zero-asset House around an existing exact person.

    This is deliberately narrower than a court recognition grant.  The new House
    starts unranked and receives no property or fiscal/military authority.
    """
    person_path = planner.owner_path(founder_ref)
    person = copy.deepcopy(planner.read(person_path))
    if _existing_person_house(person):
        raise ValueError("House founder already belongs to an exact House")
    if str(founder_ref) == "char_tang_wei":
        raise PermissionError("player House formation requires an explicit player decision")

    normalized_state = _state_key(state)
    person_state = _state_key(person.get("state"))
    if person_state and person_state != normalized_state:
        raise ValueError("House founder does not belong to the requested polity")
    if not evidence_ref:
        raise ValueError("House emergence requires exact saved evidence")
    evidence_saved = False
    try:
        planner.owner_path(str(evidence_ref))
        evidence_saved = True
    except (KeyError, ValueError, FileNotFoundError):
        evidence_saved = any(str(row.get("event_id", "")) == str(evidence_ref) for row in iter_history_events(planner))
    if not evidence_saved:
        raise ValueError("House emergence requires an exact saved evidence reference")

    founder_name = str(person.get("name") or founder_ref)
    if house_ref is None:
        digest = hashlib.sha256(f"{founder_ref}|{normalized_state}|{evidence_ref}".encode()).hexdigest()[:12]
        house_ref = f"house_{_safe_token(founder_name)}_{digest}"
    if not house_ref.startswith("house_"):
        raise ValueError("dynamic House refs must use house_ prefix")

    owner_index = copy.deepcopy(planner.read(OWNER_INDEX_PATH))
    owners = owner_index.setdefault("owners", {})
    if house_ref in owners:
        raise ValueError("House ref already exists")
    house_path = f"state/houses/{house_ref}.json"

    house = {
        "schema": "sword-house",
        "owner_id": house_ref,
        "house_ref": house_ref,
        "name": str(house_name or f"{founder_name} Household"),
        "state": normalized_state,
        "leader_ref": founder_ref,
        "lineage_cohort": {
            "adults": 1,
            "children": 0,
            "elders": 0,
            "marriages": 0,
            "exact_member_refs": [founder_ref],
            "last_close": str(at),
        },
        "nobility": {"grade": "unranked_house"},
        "treasury_silver": 0,
        "projects": [],
        "goals": ["preserve household", "improve standing"],
        "threat_level": "0.1",
        "formed_at": str(at),
        "formation_evidence_ref": str(evidence_ref),
        "autonomous_reviews": [],
    }
    # Membership is a reclassification of the same exact body.
    person["house_ref"] = house_ref
    owners[house_ref] = house_path
    planner.put(person_path, person)
    planner.put(house_path, house)
    planner.put(OWNER_INDEX_PATH, owner_index)

    event_id = "house_formation_" + hashlib.sha256(f"{house_ref}|{founder_ref}|{at}".encode()).hexdigest()[:16]
    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    history.setdefault("events", []).append({
        "event_id": event_id,
        "kind": "house_formation",
        "at": str(at),
        "house_ref": house_ref,
        "founder_ref": founder_ref,
        "state_ref": f"state_{normalized_state}",
        "evidence_ref": str(evidence_ref),
        "resource_grants": {"silver": 0, "land_km2": 0, "troops": 0},
    })
    write_history_index(planner, history)
    return {"house_ref": house_ref, "founder_ref": founder_ref, "event_id": event_id, "created": True}


def review_house_emergence(planner, *, state: str, at: str) -> dict[str, Any]:
    """Bounded state review for a proven standout without an existing House.

    The threshold only authorizes household independence, never noble recognition.
    One candidate at most can emerge per state review, preventing House spam.
    """
    rules = planner.read(NOBILITY_RULES_PATH)
    policy = rules.get("house_emergence") if isinstance(rules.get("house_emergence"), Mapping) else {}
    merit_floor = max(1, int(policy.get("minimum_verified_career_merit", 100)))
    state_key = _state_key(state)
    index = planner.read(OWNER_INDEX_PATH)
    owners = index.get("owners", {}) if isinstance(index, Mapping) else {}
    candidates: list[tuple[int, str, str, Mapping[str, Any]]] = []
    for ref, path in sorted(owners.items()):
        if not isinstance(ref, str) or not ref.startswith("char_") or ref == "char_tang_wei":
            continue
        if not isinstance(path, str) or not path.startswith("state/char/"):
            continue
        person = planner.read(path)
        if not isinstance(person, Mapping) or _existing_person_house(person):
            continue
        if _state_key(person.get("state")) != state_key:
            continue
        career = person.get("career_state") if isinstance(person.get("career_state"), Mapping) else {}
        merit = max(0, int(career.get("merit_total", 0) or 0))
        if merit < merit_floor:
            continue
        candidates.append((merit, ref, path, person))
    if not candidates:
        return {"created": False, "reason": "no_qualified_exact_founder"}
    candidates.sort(key=lambda row: (-row[0], row[1]))
    _merit, founder_ref, _path, _person = candidates[0]
    evidence = None
    for row in reversed(list(iter_history_events(planner))):
        if str(row.get("kind", "")) == "career_merit" and str(row.get("person_ref", "")) == founder_ref:
            evidence = str(row.get("event_id", ""))
            break
    if not evidence:
        return {"created": False, "reason": "qualified_founder_lacks_saved_merit_evidence", "founder_ref": founder_ref}
    return form_house_from_existing_person(planner, founder_ref=founder_ref, state=state_key, at=at, evidence_ref=evidence)


class HouseEmergenceMixin:
    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_state(host, occurrences, at)
        if int(occurrences) <= 0:
            return
        state = self._state_key(str(host.get("owner_ref", "")))
        review_house_emergence(self, state=state, at=at)


__all__ = ["HouseEmergenceMixin", "form_house_from_existing_person", "review_house_emergence"]
