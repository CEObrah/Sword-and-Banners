"""Evidence-backed sovereign reward reviews and conserved grant packages.

Merit is evidence, never an automatic promotion.  A review may later settle one
or more independent grants.  Nobility, silver, land, and office are intentionally
separate authorities.  Office to the player is represented only as an offer.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.house_nobility import RULES_PATH as NOBILITY_RULES_PATH, apply_nobility_grant, ensure_nobility_state, next_grade
from sword_runtime.history_store import iter_history_events, write_history_index
from sword_runtime.land_development import LAND_STATE_PATH, grant_house_land

OWNER_INDEX_PATH = "state/index/owner-index.json"
REWARD_ROOT = "state/politics/rewards"


def _state_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("state_", "")


def _saved_evidence(planner, evidence_ref: str) -> bool:
    try:
        planner.owner_path(str(evidence_ref))
        return True
    except (KeyError, ValueError, FileNotFoundError):
        return any(str(row.get("event_id", "")) == str(evidence_ref) for row in iter_history_events(planner))


def _grantor_authorized(planner, *, state: str, grantor_ref: str) -> Mapping[str, Any]:
    _path, grantor = planner._exact_person(grantor_ref)
    grantor_state = _state_key(grantor.get("state"))
    state_doc = planner.read(f"state/states/{state}.json")
    if grantor_state != state:
        raise PermissionError("reward grantor belongs to a different state")
    career = grantor.get("career_state") if isinstance(grantor.get("career_state"), Mapping) else {}
    authorities = {str(x) for x in career.get("authorities", []) if isinstance(x, str)} if isinstance(career.get("authorities"), list) else set()
    if str(state_doc.get("sovereign_ref", "")) != grantor_ref and "grant_court_rewards" not in authorities:
        raise PermissionError("reward grantor lacks sovereign or delegated reward authority")
    return grantor


def _evidence_supports_state_review(planner, *, evidence_ref: str, subject_ref: str, state: str) -> bool:
    """Return whether exact saved evidence places the subject under this state's review.

    A commander need not be a citizen of the rewarding state. A war-closure
    ceremony or other exact state-scoped service record can lawfully establish
    review jurisdiction without rewriting the person's identity/allegiance.
    """
    state_ref = f"state_{_state_key(state)}"
    for row in iter_history_events(planner):
        if str(row.get("event_id", "")) != str(evidence_ref):
            continue
        if str(row.get("state_ref", "")) == state_ref and str(row.get("subject_ref", "")) == subject_ref:
            return True
        ceremonies = row.get("ceremonies")
        if isinstance(ceremonies, list):
            for ceremony in ceremonies:
                if not isinstance(ceremony, Mapping) or str(ceremony.get("state_ref", "")) != state_ref:
                    continue
                if subject_ref in {str(ref) for ref in ceremony.get("summoned_person_refs", []) if isinstance(ref, str)}:
                    return True
        participants = {str(ref) for ref in row.get("participant_person_refs", []) if isinstance(ref, str)} if isinstance(row.get("participant_person_refs"), list) else set()
        party_refs = {str(ref) for ref in row.get("party_refs", []) if isinstance(ref, str)} if isinstance(row.get("party_refs"), list) else set()
        if subject_ref in participants and state_ref in party_refs:
            return True
        return False
    return False


def open_reward_review(
    planner,
    *,
    state: str,
    subject_ref: str,
    evidence_ref: str,
    at: str,
    review_ref: str | None = None,
) -> dict[str, Any]:
    state = _state_key(state)
    subject_path, subject = planner._exact_person(subject_ref)
    subject_state = _state_key(subject.get("state") or subject.get("state_ref"))
    if subject_state != state and not _evidence_supports_state_review(
        planner, evidence_ref=evidence_ref, subject_ref=subject_ref, state=state
    ):
        raise ValueError("reward subject lacks exact service evidence under this state")
    if not _saved_evidence(planner, evidence_ref):
        raise ValueError("reward review requires exact saved evidence")
    if review_ref is None:
        token = hashlib.sha256(f"{state}|{subject_ref}|{evidence_ref}".encode()).hexdigest()[:16]
        review_ref = f"reward_review.{state}.{token}"
    index = copy.deepcopy(planner.read(OWNER_INDEX_PATH))
    owners = index.setdefault("owners", {})
    path = f"{REWARD_ROOT}/{review_ref}.json"
    existing_path = owners.get(review_ref)
    if isinstance(existing_path, str):
        existing = planner.read(existing_path)
        return {"review_ref": review_ref, "status": str(existing.get("status", "open")), "created": False}
    review = {
        "schema": "court-reward-review",
        "owner_id": review_ref,
        "review_ref": review_ref,
        "state": state,
        "subject_ref": subject_ref,
        "subject_house_ref": subject.get("house_ref"),
        "evidence_refs": [str(evidence_ref)],
        "opened_at": str(at),
        "status": "open",
        "decision": None,
        "grants": [],
        "rule": "Verified evidence opens review only; every reward component requires separate lawful authority and conserved resources.",
    }
    owners[review_ref] = path
    planner.put(path, review)
    planner.put(OWNER_INDEX_PATH, index)
    return {"review_ref": review_ref, "status": "open", "created": True}


def settle_reward_package(
    planner,
    *,
    review_ref: str,
    grantor_ref: str,
    at: str,
    silver_silver: int = 0,
    nobility_target_grade: str | None = None,
    land_region_ref: str | None = None,
    land_km2: float = 0.0,
    office_offer: str | None = None,
) -> dict[str, Any]:
    path = planner.owner_path(review_ref)
    review = copy.deepcopy(planner.read(path))
    if str(review.get("schema")) != "court-reward-review" or str(review.get("status")) != "open":
        raise ValueError("reward review is not open")
    state = _state_key(review.get("state"))
    _grantor_authorized(planner, state=state, grantor_ref=grantor_ref)
    evidence_refs = [str(x) for x in review.get("evidence_refs", []) if isinstance(x, str)]
    if not evidence_refs or not all(_saved_evidence(planner, ref) for ref in evidence_refs):
        raise ValueError("reward review lost its exact evidence authority")
    subject_ref = str(review.get("subject_ref"))
    _sp, subject = planner._exact_person(subject_ref)
    house_ref = review.get("subject_house_ref") or subject.get("house_ref")
    house_path = planner.owner_path(str(house_ref)) if isinstance(house_ref, str) and house_ref else None
    house = copy.deepcopy(planner.read(house_path)) if house_path else None

    state_path = f"state/states/{state}.json"
    state_doc = copy.deepcopy(planner.read(state_path))
    grants: list[dict[str, Any]] = []

    silver = max(0, int(silver_silver))
    if silver:
        if not isinstance(house, dict):
            raise ValueError("cash House reward requires an exact subject House")
        if int(state_doc.get("treasury_silver", 0)) < silver:
            raise ValueError("state treasury cannot fund reward")
        state_doc["treasury_silver"] = int(state_doc.get("treasury_silver", 0)) - silver
        house["treasury_silver"] = int(house.get("treasury_silver", 0)) + silver
        grants.append({"kind": "silver", "amount_silver": silver})

    if nobility_target_grade:
        if not isinstance(house, dict):
            raise ValueError("nobility reward requires an exact subject House")
        rules = planner.read(NOBILITY_RULES_PATH)
        prior = str(ensure_nobility_state(house, rules).get("grade"))
        grant_ref = "reward_nobility." + hashlib.sha256(f"{review_ref}|{nobility_target_grade}|{at}".encode()).hexdigest()[:16]
        apply_nobility_grant(
            house, rules, target_grade=str(nobility_target_grade), grantor_ref=grantor_ref,
            evidence_ref=evidence_refs[0], at=str(at), grant_ref=grant_ref,
        )
        grants.append({"kind": "nobility", "prior_grade": prior, "target_grade": str(nobility_target_grade), "grant_ref": grant_ref})

    land = max(0.0, float(land_km2 or 0.0))
    if land:
        if not isinstance(house, dict) or not isinstance(land_region_ref, str) or not land_region_ref:
            raise ValueError("land reward requires exact House and conserved source region")
        land_doc = copy.deepcopy(planner.read(LAND_STATE_PATH))
        grant_ref = "reward_land." + hashlib.sha256(f"{review_ref}|{land_region_ref}|{land}|{at}".encode()).hexdigest()[:16]
        land_result = grant_house_land(land_doc, house_ref=str(house_ref), region_ref=land_region_ref, area_km2=land, grant_ref=grant_ref)
        planner.put(LAND_STATE_PATH, land_doc)
        grants.append({"kind": "land", "grant_ref": grant_ref, **land_result})

    if office_offer:
        # Grantor may offer an office, but acceptance remains a separate subject decision.
        offers = state_doc.setdefault("office_offers", {})
        offer_ref = "office_offer." + hashlib.sha256(f"{review_ref}|{subject_ref}|{office_offer}|{at}".encode()).hexdigest()[:16]
        offers[offer_ref] = {
            "offer_ref": offer_ref,
            "person_ref": subject_ref,
            "office": str(office_offer),
            "offered_by": grantor_ref,
            "offered_at": str(at),
            "status": "pending_acceptance",
            "evidence_ref": evidence_refs[0],
        }
        grants.append({"kind": "office_offer", "office": str(office_offer), "offer_ref": offer_ref, "status": "pending_acceptance"})

    if not grants:
        grants.append({"kind": "honor_only", "resource_effect": "none"})
    review["status"] = "settled"
    review["decided_at"] = str(at)
    review["grantor_ref"] = grantor_ref
    review["decision"] = "grant"
    review["grants"] = grants
    planner.put(state_path, state_doc)
    if house_path and isinstance(house, dict):
        planner.put(house_path, house)
    planner.put(path, review)

    event_id = "court_reward_" + hashlib.sha256(f"{review_ref}|{grantor_ref}|{at}".encode()).hexdigest()[:16]
    history = copy.deepcopy(planner.read("state/history/events/index.json"))
    history.setdefault("events", []).append({
        "event_id": event_id,
        "kind": "court_reward_package",
        "at": str(at),
        "state_ref": f"state_{state}",
        "subject_ref": subject_ref,
        "house_ref": house_ref,
        "grantor_ref": grantor_ref,
        "review_ref": review_ref,
        "evidence_refs": evidence_refs,
        "grants": copy.deepcopy(grants),
    })
    write_history_index(planner, history)
    return {"review_ref": review_ref, "event_id": event_id, "grants": grants, "status": "settled"}


def review_state_reward_candidates(planner, *, state: str, at: str) -> dict[str, Any]:
    """Open at most one new evidence-backed review per state wake.

    The autonomous step deliberately opens review only.  It does not auto-promote,
    auto-grant land, or spend treasury merely because a merit counter crossed a line.
    """
    state = _state_key(state)
    state_doc = planner.read(f"state/states/{state}.json")
    if not isinstance(state_doc.get("sovereign_ref"), str):
        return {"created": False, "reason": "no_exact_sovereign_authority"}
    rules = planner.read(NOBILITY_RULES_PATH)
    reward = rules.get("reward_review") if isinstance(rules.get("reward_review"), Mapping) else {}
    floor = max(1, int(reward.get("minimum_verified_career_merit", 50)))
    candidates: list[tuple[int, int, str, str]] = []
    for row in iter_history_events(planner):
        if str(row.get("kind", "")) != "career_merit":
            continue
        person_ref = str(row.get("person_ref", ""))
        if not person_ref or person_ref == "char_tang_wei":
            continue
        try:
            _pp, person = planner._exact_person(person_ref)
        except (KeyError, ValueError, FileNotFoundError):
            continue
        if _state_key(person.get("state")) != state:
            continue
        career = person.get("career_state") if isinstance(person.get("career_state"), Mapping) else {}
        merit = max(0, int(career.get("merit_total", 0) or 0))
        if merit < floor:
            continue
        appraisal = row.get("service_appraisal") if isinstance(row.get("service_appraisal"), Mapping) else {}
        appraisal_merit = max(0, int(appraisal.get("adjudicated_merit", row.get("merit", 0)) or 0))
        candidates.append((merit, appraisal_merit, person_ref, str(row.get("event_id", ""))))
    if not candidates:
        return {"created": False, "reason": "no_reward_candidate"}
    candidates.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
    _merit, _appraisal_merit, person_ref, evidence_ref = candidates[0]
    return open_reward_review(planner, state=state, subject_ref=person_ref, evidence_ref=evidence_ref, at=at)


class CourtRewardMixin:
    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_state(host, occurrences, at)
        if int(occurrences) <= 0:
            return
        state = self._state_key(str(host.get("owner_ref", "")))
        review_state_reward_candidates(self, state=state, at=at)


__all__ = ["CourtRewardMixin", "open_reward_review", "settle_reward_package", "review_state_reward_candidates"]
