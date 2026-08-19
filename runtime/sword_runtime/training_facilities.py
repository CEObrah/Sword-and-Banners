"""Deterministic physical training-site access.

Registered drill ``facility_tag`` values are mechanical requirements, not prose.
This module resolves those tags against the trainee's saved physical location and
its containing location chain. Portable field setups remain possible for ordinary
martial/command drills, while specialist infrastructure (artillery, engineering,
medical, household/estate work) requires matching physical site evidence.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

LOCATIONS_PATH = "game/data/world/locations.json"

# These can be established in ordinary physical open space by a present formation
# or individual without materializing a permanent building. Facility *quality* is
# still owned by the regimen passed to the EDU law.
_PORTABLE_FIELD_TAGS = {
    "field_terrain",
    "training_ground",
    "maneuver_ground",
    "command_ground",
    "staff_room",
    "riding_ground",
    "riding_range",
    "range",
    "signal_ground",
}

# Specialist tags require explicit function/site evidence somewhere in the saved
# containment chain. They are intentionally not satisfied by a generic field camp.
_SPECIALIST_REQUIREMENTS: dict[str, tuple[set[str], set[str]]] = {
    "engineering_yard": ({"engineering"}, set()),
    "artillery_range": ({"artillery"}, set()),
    "medical_training": ({"medical", "training"}, set()),
    "household_classroom": (set(), {"household", "house", "academy"}),
    "audience_hall": (set(), {"household", "house", "politics", "academy"}),
    "estate_routes": (set(), {"estate"}),
}

# Shared institutional resources proven by a specialist facility. Ordinary weapons,
# shields, mounts, arrows and bolts remain conserved loadout/supervised resources.
_SHARED_RESOURCES_BY_TAG: dict[str, set[str]] = {
    "engineering_yard": {"engineering_tools"},
    "artillery_range": {"artillery"},
    "signal_ground": {"signals"},
}


def _location_rows(runtime: Any) -> dict[str, Mapping[str, Any]]:
    try:
        doc = runtime.read(LOCATIONS_PATH)
    except Exception:
        return {}
    rows = doc.get("locations", []) if isinstance(doc, Mapping) else []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return {}
    return {
        str(row.get("ref")): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("ref"), str) and row.get("ref")
    }


def _location_chain_rows(runtime: Any, location_ref: str) -> list[Mapping[str, Any]]:
    rows = _location_rows(runtime)
    current = str(location_ref or "")
    if not current or current not in rows:
        return []
    out: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    while current in rows and current not in seen:
        seen.add(current)
        row = rows[current]
        out.append(row)
        parent = row.get("parent_ref")
        if not isinstance(parent, str) or not parent.startswith("loc_"):
            break
        current = parent
    return out


def _explicit_tags(chain: Sequence[Mapping[str, Any]]) -> set[str]:
    out: set[str] = set()
    for row in chain:
        raw = row.get("training_facility_tags", [])
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            out.update(str(value) for value in raw if str(value))
    return out


def training_facility_access(runtime: Any, *, location_ref: str, facility_tag: str) -> float:
    """Return 1/0 physical access for one registered drill facility tag.

    Missing location evidence fails closed. Ordinary field-compatible tags can be
    established at any real mapped physical location. Specialist tags require an
    explicit matching location function/kind or an explicit facility tag in the
    current location's containment chain.
    """
    tag = str(facility_tag or "").strip()
    if not tag:
        return 1.0
    chain = _location_chain_rows(runtime, str(location_ref or ""))
    if not chain:
        return 0.0
    if tag in _explicit_tags(chain):
        return 1.0
    if tag in _PORTABLE_FIELD_TAGS:
        return 1.0

    required_functions, allowed_kinds = _SPECIALIST_REQUIREMENTS.get(tag, (set(), set()))
    for row in chain:
        functions = {
            str(value)
            for value in row.get("functions", [])
            if isinstance(row.get("functions"), Sequence) and not isinstance(row.get("functions"), (str, bytes, bytearray))
        }
        kind = str(row.get("kind", ""))
        if required_functions and required_functions.issubset(functions):
            return 1.0
        if allowed_kinds and (kind in allowed_kinds or bool(functions & allowed_kinds)):
            return 1.0
    return 0.0


def program_facility_access(
    runtime: Any,
    *,
    registry: Mapping[str, Any],
    program_ref: str,
    location_ref: str,
) -> dict[str, float]:
    """Resolve the facility gate for every drill in a registered program."""
    programs = registry.get("programs", {}) if isinstance(registry, Mapping) else {}
    drills = registry.get("drills", {}) if isinstance(registry, Mapping) else {}
    program = programs.get(program_ref, {}) if isinstance(programs, Mapping) else {}
    rotation = program.get("rotation", []) if isinstance(program, Mapping) else []
    out: dict[str, float] = {}
    if not isinstance(rotation, Sequence) or isinstance(rotation, (str, bytes, bytearray)):
        return out
    for row in rotation:
        if not isinstance(row, Mapping):
            continue
        dref = str(row.get("drill_ref", ""))
        drill = drills.get(dref, {}) if isinstance(drills, Mapping) else {}
        facility_tag = str(drill.get("facility_tag", "")) if isinstance(drill, Mapping) else ""
        out[dref] = training_facility_access(runtime, location_ref=location_ref, facility_tag=facility_tag)
    return out


def shared_training_resources(runtime: Any, *, location_ref: str) -> set[str]:
    """Return only specialist shared resources proven by the physical training site."""
    chain = _location_chain_rows(runtime, str(location_ref or ""))
    if not chain:
        return set()
    explicit = _explicit_tags(chain)
    resources: set[str] = set()
    for tag, provided in _SHARED_RESOURCES_BY_TAG.items():
        if tag in explicit or training_facility_access(runtime, location_ref=location_ref, facility_tag=tag) > 0:
            resources.update(provided)
    return resources


__all__ = [
    "LOCATIONS_PATH",
    "program_facility_access",
    "shared_training_resources",
    "training_facility_access",
]
