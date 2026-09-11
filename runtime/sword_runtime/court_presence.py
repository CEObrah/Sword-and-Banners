"""Bounded exact-person routing for formal royal-court scenes.

The court attendance index is authority:false. It is only a bounded candidate
route. Exact person owners remain authority for life state, office/career facts,
and physical location. A court session never creates office, allegiance, consent,
or presence merely because somebody appears in the candidate index.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

_INDEX_PATH = "state/index/court-attendance-index.json"
_OWNER_INDEX = "state/index/owner-index.json"


def _read(source: Any, path: str) -> Any:
    if hasattr(source, "read"):
        return source.read(path)
    return source.read_json(path)


def _read_optional(source: Any, path: str) -> Any:
    if hasattr(source, "read_optional"):
        return source.read_optional(path)
    try:
        return _read(source, path)
    except (FileNotFoundError, KeyError, OSError, ValueError):
        return None


def _owner_path(source: Any, ref: str) -> str | None:
    if hasattr(source, "owner_path"):
        try:
            return source.owner_path(ref)
        except (FileNotFoundError, KeyError, ValueError):
            return None
    index = _read(source, _OWNER_INDEX)
    owners = index.get("owners") if isinstance(index, Mapping) else None
    path = owners.get(ref) if isinstance(owners, Mapping) else None
    return str(path) if isinstance(path, str) and path else None


def _person(source: Any, ref: str) -> Mapping[str, Any] | None:
    path = _owner_path(source, ref)
    row = _read_optional(source, path) if isinstance(path, str) else None
    if not isinstance(row, Mapping):
        return None
    if path == "state/player.json" or str(path).startswith("state/char/"):
        return row
    if str(path).startswith("state/person/") and str(row.get("schema", "")) in {"sab_character", "person-lite", "sword-materialized-person"}:
        return row
    return None


def _person_location(person: Mapping[str, Any]) -> str | None:
    value = person.get("current_location") or person.get("location") or person.get("location_ref")
    return str(value) if isinstance(value, str) and value else None


def _alive(person: Mapping[str, Any]) -> bool:
    status = str(person.get("life_status", person.get("status", "active"))).lower()
    return status not in {"dead", "deceased"}


def court_profile(source: Any, state_ref: str) -> dict[str, Any] | None:
    raw = _read_optional(source, _INDEX_PATH)
    courts = raw.get("courts") if isinstance(raw, Mapping) else None
    row = courts.get(state_ref) if isinstance(courts, Mapping) else None
    return copy.deepcopy(dict(row)) if isinstance(row, Mapping) else None


def court_session_projection(
    source: Any,
    *,
    state_ref: str,
    venue_ref: str,
    additional_candidate_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Return bounded court cast routing revalidated against exact person state.

    ``additional_candidate_refs`` lets a specific proceeding add lawful exact
    participants such as campaign commanders without changing the standing court
    candidate index. Presence still requires exact co-location.
    """
    profile = court_profile(source, state_ref) or {}
    candidate_rows = profile.get("candidate_rows") if isinstance(profile.get("candidate_rows"), list) else []
    roles: dict[str, str] = {}
    refs: list[str] = []
    for row in candidate_rows:
        if not isinstance(row, Mapping):
            continue
        ref = row.get("person_ref")
        if not isinstance(ref, str) or not ref:
            raise ValueError("court attendance candidate is malformed")
        if _person(source, ref) is None:
            raise ValueError(f"court attendance candidate unresolved: {ref}")
        refs.append(ref)
        role = row.get("court_role")
        if isinstance(role, str) and role:
            roles[ref] = role
    for ref in additional_candidate_refs or []:
        if not isinstance(ref, str) or not ref:
            raise ValueError("additional court candidate is malformed")
        if _person(source, ref) is None:
            raise ValueError(f"additional court candidate unresolved: {ref}")
        refs.append(ref)
    refs = list(dict.fromkeys(refs))

    present: list[str] = []
    absent: list[str] = []
    unavailable: list[str] = []
    for ref in refs:
        person = _person(source, ref)
        if not isinstance(person, Mapping) or not _alive(person):
            unavailable.append(ref)
            continue
        if _person_location(person) == venue_ref:
            present.append(ref)
        else:
            absent.append(ref)

    return {
        "state_ref": state_ref,
        "venue_ref": venue_ref,
        "forum_kind": str(profile.get("forum_kind") or "royal_court"),
        "sovereign_ref": profile.get("sovereign_ref"),
        "candidate_person_refs": refs,
        "court_role_by_person_ref": roles,
        "present_person_refs": present,
        "absent_person_refs": absent,
        "unavailable_person_refs": unavailable,
        "rule": (
            "Court roster rows are routing candidates only. Exact person owners "
            "determine life state and physical presence; attendance never creates "
            "office, consent, allegiance, or authority."
        ),
    }


__all__ = ["court_profile", "court_session_projection"]
