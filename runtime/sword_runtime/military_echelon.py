"""Hierarchy-aware military presentation helpers.

Persistent formations are mechanical manpower/combat owners and can represent
very different strengths across states.  Command groups are the organizational
hierarchy.  Campaign-facing projections must compare peer echelons rather than
flattening Tang Wei's 500-person tactical leaves beside enemy aggregate field
bodies.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _read(source: Any, path: str) -> Any:
    if hasattr(source, "read"):
        return source.read(path)
    if hasattr(source, "read_json"):
        return source.read_json(path)
    raise TypeError("unsupported repository reader")


def _owner_path(source: Any, ref: str) -> str:
    if hasattr(source, "owner_path"):
        return str(source.owner_path(ref))
    idx = _read(source, "state/index/owner-index.json")
    owners = idx.get("owners", {}) if isinstance(idx, Mapping) else {}
    path = owners.get(ref) if isinstance(owners, Mapping) else None
    if not isinstance(path, str) or not path:
        raise KeyError(ref)
    return path


def _read_group(source: Any, ref: str) -> Mapping[str, Any] | None:
    try:
        row = _read(source, f"state/cmd/command-groups/{ref}.json")
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _read_formation(source: Any, ref: str) -> Mapping[str, Any] | None:
    try:
        row = _read(source, _owner_path(source, ref))
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None
    return row if isinstance(row, Mapping) else None


def _person_name(source: Any, ref: object) -> str | None:
    if not isinstance(ref, str) or not ref:
        return None
    try:
        person = _read(source, _owner_path(source, ref))
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None
    if not isinstance(person, Mapping):
        return None
    value = person.get("name") or person.get("display_name")
    return str(value) if isinstance(value, str) and value else None


def descendant_leaf_refs(source: Any, group_ref: str, *, _seen: set[str] | None = None) -> set[str]:
    """Return exact formation leaves beneath a command group from the live tree."""
    seen = set() if _seen is None else set(_seen)
    if group_ref in seen:
        raise ValueError("command hierarchy contains a cycle")
    seen.add(group_ref)
    group = _read_group(source, group_ref)
    if group is None:
        return set()
    out: set[str] = set()
    units = group.get("units", []) if isinstance(group.get("units"), list) else []
    for unit in units:
        if not isinstance(unit, Mapping):
            continue
        ref = unit.get("ref")
        kind = unit.get("kind")
        if not isinstance(ref, str) or not ref:
            continue
        if kind == "formation":
            out.add(ref)
        elif kind == "nested_army":
            out.update(descendant_leaf_refs(source, ref, _seen=seen))
    return out


def _leaf_strength(source: Any, refs: set[str]) -> tuple[int, list[str]]:
    total = 0
    locations: set[str] = set()
    for ref in sorted(refs):
        row = _read_formation(source, ref)
        if row is None:
            continue
        total += max(0, int(row.get("personnel", 0) or 0))
        loc = row.get("location_ref")
        if isinstance(loc, str) and loc:
            locations.add(loc)
    return total, sorted(locations)


def operation_echelon_summary(source: Any, operation: Mapping[str, Any]) -> dict[str, Any]:
    """Return a peer-echelons campaign view for one operation.

    ``tactical_formation_count`` remains available as internal/detail accounting,
    but it is explicitly not a peer-level army count.  If no command hierarchy is
    available, each aggregate formation owner is presented as a field body rather
    than pretending its internal substructure is known.
    """
    opposing = {str(x) for x in operation.get("opposing_formation_refs", []) if isinstance(x, str)}
    active_refs = [
        str(x) for x in operation.get("formation_refs", [])
        if isinstance(x, str) and str(x) not in opposing
    ] if isinstance(operation.get("formation_refs"), list) else []
    active_set = set(active_refs)
    primary: list[dict[str, Any]] = []
    root_ref = operation.get("command_group_ref")
    root = _read_group(source, str(root_ref)) if isinstance(root_ref, str) and root_ref else None

    if root is not None:
        units = root.get("units", []) if isinstance(root.get("units"), list) else []
        for unit in units:
            if not isinstance(unit, Mapping):
                continue
            kind = str(unit.get("kind") or "")
            ref = str(unit.get("ref") or "")
            if not ref or kind not in {"formation", "nested_army"}:
                continue
            leaves = ({ref} if kind == "formation" else descendant_leaf_refs(source, ref)) & active_set
            if not leaves:
                continue
            strength, locations = _leaf_strength(source, leaves)
            if kind == "nested_army":
                child = _read_group(source, ref) or {}
                name = str(child.get("display_name") or child.get("name") or ref)
                commander_ref = child.get("commander_ref")
            else:
                formation = _read_formation(source, ref) or {}
                name = str(formation.get("name") or formation.get("display_name") or ref)
                commander_ref = formation.get("commander_ref")
            primary.append({
                "command_ref": ref,
                "kind": kind,
                "name": name,
                "strength": strength,
                "tactical_leaf_count": len(leaves),
                "commander_ref": commander_ref if isinstance(commander_ref, str) else None,
                "commander_name": _person_name(source, commander_ref),
                "location_refs": locations,
            })

    representation = "primary_commands"
    if not primary:
        representation = "aggregate_field_bodies"
        for ref in active_refs:
            formation = _read_formation(source, ref)
            if formation is None:
                continue
            loc = formation.get("location_ref")
            commander_ref = formation.get("commander_ref")
            primary.append({
                "command_ref": ref,
                "kind": "formation",
                "name": str(formation.get("name") or formation.get("display_name") or ref),
                "strength": max(0, int(formation.get("personnel", 0) or 0)),
                "tactical_leaf_count": None,
                "commander_ref": commander_ref if isinstance(commander_ref, str) else None,
                "commander_name": _person_name(source, commander_ref),
                "location_refs": [loc] if isinstance(loc, str) and loc else [],
            })

    primary.sort(key=lambda row: (-int(row.get("strength", 0) or 0), str(row.get("command_ref") or "")))
    return {
        "representation": representation,
        "primary_command_count": len(primary),
        "primary_commands": primary,
        "tactical_formation_count": len(active_refs),
        "comparison_rule": "Campaign comparisons use peer primary commands/field bodies. Tactical leaf formations remain subordinate mechanics and are not peer army counts.",
    }


__all__ = ["descendant_leaf_refs", "operation_echelon_summary"]
