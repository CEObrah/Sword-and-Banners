"""Bounded routing index for autonomous House-emergence candidates.

The index is projection/routing only. Exact person owners and saved merit history
remain authority. It exists so each state House review does not scan the global
person registry or causal-history archive.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

INDEX_PATH = "state/index/house-emergence-candidates.json"


def _state_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("state_", "")


def _house_ref(person: Mapping[str, Any]) -> str | None:
    direct = person.get("house_ref")
    if isinstance(direct, str) and direct:
        return direct
    household = person.get("household") if isinstance(person.get("household"), Mapping) else {}
    ref = household.get("house_ref") if isinstance(household, Mapping) else None
    return str(ref) if isinstance(ref, str) and ref else None


def _index(planner: Any) -> dict[str, Any]:
    return copy.deepcopy(planner.read_optional(INDEX_PATH) or {
        "schema": "generic-object",
        "authority": False,
        "by_state": {},
    })


def remove_house_emergence_candidate(planner: Any, person_ref: str) -> None:
    idx = _index(planner)
    changed = False
    for rows in idx.setdefault("by_state", {}).values():
        if isinstance(rows, dict) and str(person_ref) in rows:
            rows.pop(str(person_ref), None)
            changed = True
    if changed or planner.read_optional(INDEX_PATH) is None:
        planner.put(INDEX_PATH, idx)


def record_house_emergence_candidate(planner: Any, *, person_ref: str, evidence_ref: str, at: str) -> None:
    """Update one exact person's candidacy after a saved career-merit event."""
    if not person_ref or person_ref == "char_tang_wei" or not evidence_ref:
        return
    try:
        path = planner.owner_path(person_ref)
        person = planner.read(path)
    except (KeyError, FileNotFoundError, ValueError):
        remove_house_emergence_candidate(planner, person_ref)
        return
    if not isinstance(person, Mapping) or _house_ref(person):
        remove_house_emergence_candidate(planner, person_ref)
        return
    if str(person.get("life_status", person.get("status", "active"))).lower() in {"dead", "deceased"}:
        remove_house_emergence_candidate(planner, person_ref)
        return
    state = _state_key(person.get("state"))
    merit = max(0, int((person.get("career_state") or {}).get("merit_total", 0) or 0)) if isinstance(person.get("career_state"), Mapping) else 0
    if not state or merit <= 0:
        remove_house_emergence_candidate(planner, person_ref)
        return
    idx = _index(planner)
    rows = idx.setdefault("by_state", {}).setdefault(state, {})
    rows[str(person_ref)] = {
        "person_ref": str(person_ref),
        "merit_total": merit,
        "latest_merit_evidence_ref": str(evidence_ref),
        "updated_at": str(at),
    }
    planner.put(INDEX_PATH, idx)


def best_house_emergence_candidate(planner: Any, *, state: str, minimum_merit: int) -> dict[str, Any] | None:
    """Return the best still-valid indexed candidate, bounded to that state."""
    idx = _index(planner)
    state_key = _state_key(state)
    rows = idx.setdefault("by_state", {}).get(state_key, {})
    if not isinstance(rows, Mapping):
        return None
    changed = False
    ordered = sorted(
        (row for row in rows.values() if isinstance(row, Mapping)),
        key=lambda row: (-max(0, int(row.get("merit_total", 0) or 0)), str(row.get("person_ref", ""))),
    )
    for row in ordered:
        person_ref = str(row.get("person_ref", ""))
        if person_ref == "char_tang_wei" or max(0, int(row.get("merit_total", 0) or 0)) < max(1, int(minimum_merit)):
            continue
        try:
            person = planner.read(planner.owner_path(person_ref))
        except (KeyError, FileNotFoundError, ValueError):
            rows.pop(person_ref, None); changed = True; continue
        career = person.get("career_state") if isinstance(person.get("career_state"), Mapping) else {}
        current_merit = max(0, int(career.get("merit_total", 0) or 0))
        valid = (
            isinstance(person, Mapping)
            and not _house_ref(person)
            and _state_key(person.get("state")) == state_key
            and str(person.get("life_status", person.get("status", "active"))).lower() not in {"dead", "deceased"}
            and current_merit >= max(1, int(minimum_merit))
            and bool(row.get("latest_merit_evidence_ref"))
        )
        if not valid:
            rows.pop(person_ref, None); changed = True; continue
        if current_merit != int(row.get("merit_total", 0) or 0):
            row = dict(row); row["merit_total"] = current_merit; rows[person_ref] = row; changed = True
        if changed:
            planner.put(INDEX_PATH, idx)
        return dict(row)
    if changed:
        planner.put(INDEX_PATH, idx)
    return None


__all__ = [
    "INDEX_PATH",
    "record_house_emergence_candidate",
    "remove_house_emergence_candidate",
    "best_house_emergence_candidate",
]
