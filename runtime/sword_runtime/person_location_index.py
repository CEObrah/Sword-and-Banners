"""Bounded routing projection for exact named-person physical location.

The index owns no person state. It is maintained whenever an individually
represented person owner is written so systems such as outbreaks can review
only named people who are materially present at a site instead of globally
scanning the cast.  Representation (full character vs. person-lite) must not
change whether the same conserved body is exposed to physical site effects.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

INDEX_PATH = "state/index/person-location-index.json"
PERSON_SCHEMAS = frozenset({"sab_character", "sword-materialized-person", "person-lite"})


def person_location(person: Mapping[str, Any]) -> str | None:
    for key in ("location", "current_location"):
        value = person.get(key)
        if isinstance(value, str) and value.startswith("loc_"):
            return value
    return None


def _blank() -> dict[str, Any]:
    return {
        "schema": "generic-object",
        "authority": False,
        "person_location": {},
        "by_location": {},
    }


def sync_person_location(planner: Any, *, person_ref: str, person: Mapping[str, Any]) -> None:
    ref = str(person_ref or "")
    if not ref:
        return
    schema = str(person.get("schema", ""))
    if not (ref.startswith("char_") or schema in PERSON_SCHEMAS):
        return
    index = copy.deepcopy(planner.read_optional(INDEX_PATH) or _blank())
    person_locations = index.setdefault("person_location", {})
    by_location = index.setdefault("by_location", {})
    prior = person_locations.get(ref)
    current = person_location(person)
    if isinstance(prior, str) and prior in by_location:
        by_location[prior] = [x for x in by_location.get(prior, []) if str(x) != ref]
        if not by_location[prior]:
            by_location.pop(prior, None)
    if current:
        person_locations[ref] = current
        rows = [str(x) for x in by_location.get(current, []) if isinstance(x, str)]
        if ref not in rows:
            rows.append(ref)
        by_location[current] = sorted(set(rows))
    else:
        person_locations.pop(ref, None)
    planner.put(INDEX_PATH, index)


def remove_person_location(planner: Any, person_ref: str) -> None:
    ref = str(person_ref or "")
    index = copy.deepcopy(planner.read_optional(INDEX_PATH) or _blank())
    person_locations = index.setdefault("person_location", {})
    by_location = index.setdefault("by_location", {})
    prior = person_locations.pop(ref, None)
    if isinstance(prior, str) and prior in by_location:
        by_location[prior] = [x for x in by_location.get(prior, []) if str(x) != ref]
        if not by_location[prior]:
            by_location.pop(prior, None)
    planner.put(INDEX_PATH, index)


def person_refs_at_locations(planner: Any, location_refs: set[str]) -> list[str]:
    index = planner.read_optional(INDEX_PATH) or _blank()
    by_location = index.get("by_location", {}) if isinstance(index, Mapping) else {}
    out: set[str] = set()
    for loc in sorted(str(x) for x in location_refs if isinstance(x, str)):
        rows = by_location.get(loc, []) if isinstance(by_location, Mapping) else []
        out.update(str(x) for x in rows if isinstance(x, str) and str(x))
    return sorted(out)


__all__ = ["INDEX_PATH", "person_location", "sync_person_location", "remove_person_location", "person_refs_at_locations"]
