"""Current recursive operational unit model.

A parent command sees one ordered list of direct Units.  Each Unit is either a
persistent mixed-role formation or an intact nested army command.  The parent
army commander and authorized staff command those Units; each fighting Unit
commander owns that Unit's top echelon, so the Unit may contain only strictly
smaller internal command echelons. Example: a 1,000-man Unit has one top
commander, then subordinate 500/100 commands as organization requires, never an
extra same-tier internal 1,000 commander.  Nested army contents never count as additional parent direct
slots and are never flattened merely for presentation.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any

FORMATION = "formation"
NESTED_ARMY = "nested_army"
UNIT_KINDS = {FORMATION, NESTED_ARMY}


def unit_entries(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = group.get("units", [])
    if not isinstance(raw, list):
        raise ValueError("command group units must be an ordered array")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise ValueError("command group unit entry must be an object")
        ref = item.get("ref")
        kind = item.get("kind")
        if not isinstance(ref, str) or not ref:
            raise ValueError("command group unit ref is invalid")
        if kind not in UNIT_KINDS:
            raise ValueError("command group unit kind is invalid")
        if ref in seen:
            raise ValueError("command group may not contain the same direct unit twice")
        seen.add(ref)
        rows.append({"slot": idx, "kind": str(kind), "ref": ref})
    return rows


def formation_refs(group: Mapping[str, Any]) -> list[str]:
    return [row["ref"] for row in unit_entries(group) if row["kind"] == FORMATION]


def nested_army_refs(group: Mapping[str, Any]) -> list[str]:
    return [row["ref"] for row in unit_entries(group) if row["kind"] == NESTED_ARMY]


def append_unit(group: dict[str, Any], *, kind: str, ref: str) -> None:
    if kind not in UNIT_KINDS:
        raise ValueError("invalid direct unit kind")
    rows = unit_entries(group)
    if any(row["ref"] == ref for row in rows):
        return
    group["units"] = [{"kind": row["kind"], "ref": row["ref"]} for row in rows] + [{"kind": kind, "ref": ref}]


def remove_unit(group: dict[str, Any], ref: str) -> None:
    rows = unit_entries(group)
    group["units"] = [{"kind": row["kind"], "ref": row["ref"]} for row in rows if row["ref"] != ref]


def replace_unit(group: dict[str, Any], old_ref: str, *, kind: str, ref: str) -> None:
    if kind not in UNIT_KINDS:
        raise ValueError("invalid direct unit kind")
    rows = unit_entries(group)
    found = False
    out: list[dict[str, str]] = []
    for row in rows:
        if row["ref"] == old_ref:
            out.append({"kind": kind, "ref": ref})
            found = True
        else:
            out.append({"kind": row["kind"], "ref": row["ref"]})
    if not found:
        raise ValueError("direct unit is not assigned to this parent command")
    if len({row["ref"] for row in out}) != len(out):
        raise ValueError("replacement would duplicate a direct unit")
    group["units"] = out


def move_unit(group: dict[str, Any], ref: str, slot: int) -> None:
    rows = [{"kind": row["kind"], "ref": row["ref"]} for row in unit_entries(group)]
    if slot < 1 or slot > max(1, len(rows)):
        raise ValueError("unit slot is outside the current direct OOB")
    current = next((i for i, row in enumerate(rows) if row["ref"] == ref), None)
    if current is None:
        raise ValueError("direct unit is not assigned to this command")
    row = rows.pop(current)
    rows.insert(slot - 1, row)
    group["units"] = rows


def recursive_refs(read_group, group_ref: str) -> tuple[set[str], set[str]]:
    """Return descendant formation refs and command refs without flattening ownership."""
    formations: set[str] = set()
    commands: set[str] = set()
    stack = [group_ref]
    while stack:
        ref = stack.pop()
        if ref in commands:
            raise ValueError("command hierarchy contains a cycle")
        commands.add(ref)
        doc = read_group(ref)
        for row in unit_entries(doc):
            if row["kind"] == FORMATION:
                formations.add(row["ref"])
            else:
                stack.append(row["ref"])
    return formations, commands


def validated_primary_group_ref(index: Mapping[str, Any], read_group, formation_ref: str) -> str | None:
    """Resolve a routing-index primary group only when exact hierarchy agrees.

    ``primary_formation_group`` is authority:false discovery state.  A stale
    mapping must never grant command authority, move staff, change reporting
    latency, or attribute a formation to the wrong commander.  Re-read the
    routed group's exact subtree and fail closed unless the formation is really
    one of its descendant Units.
    """
    mapping = index.get("primary_formation_group") if isinstance(index, Mapping) else None
    group_ref = mapping.get(formation_ref) if isinstance(mapping, Mapping) else None
    if not isinstance(group_ref, str) or not group_ref:
        return None
    try:
        formations, _commands = recursive_refs(read_group, group_ref)
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None
    return group_ref if str(formation_ref) in formations else None


def authoritative_group_ref_for_formation(
    index: Mapping[str, Any], read_group, formation_ref: str, formation: Mapping[str, Any]
) -> str | None:
    """Resolve exact formation command membership without index authority.

    The formation's saved ``higher_command_ref`` is the first discovery route;
    ``primary_formation_group`` is only a fallback accelerator.  Either route is
    accepted only when the exact command-group subtree actually contains the
    formation.  Thus a missing index cannot suppress a real command relation and
    a stale index cannot manufacture one.
    """
    candidates: list[str] = []
    higher = formation.get("higher_command_ref") if isinstance(formation, Mapping) else None
    if isinstance(higher, str) and higher:
        candidates.append(higher)
    mapping = index.get("primary_formation_group") if isinstance(index, Mapping) else None
    routed = mapping.get(formation_ref) if isinstance(mapping, Mapping) else None
    if isinstance(routed, str) and routed and routed not in candidates:
        candidates.append(routed)
    for group_ref in candidates:
        try:
            formations, _commands = recursive_refs(read_group, group_ref)
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            continue
        if str(formation_ref) in formations:
            return group_ref
    return None
