"""Synchronize person-lite/full officer billets with compact formation cadre state.

Rank is never derived from troop count. This module updates only current billet
and commanded span after casualties, reconstitution, split/merge, or command
succession. Aggregate officers remain sheetless.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.officer_cadre import ensure_person_military_rank, officer_cadre_summary


def _rank_scale(person: Mapping[str, Any]) -> int:
    rank = person.get("military_rank") if isinstance(person.get("military_rank"), Mapping) else {}
    grade = str(rank.get("grade") or person.get("rank") or "")
    for scale in (1000, 500, 100):
        if str(scale) in grade:
            return scale
    assignment = person.get("command_assignment") if isinstance(person.get("command_assignment"), Mapping) else {}
    return max(0, int(assignment.get("scale", 0) or 0))


def sync_materialized_officer_billets(runtime: Any, formation: dict[str, Any]) -> None:
    cadre = officer_cadre_summary(formation)
    personnel = max(0, int(formation.get("personnel", 0)))
    top = [(formation.get("commander_ref"), "formation_commander")]
    for ref, billet in top:
        if not isinstance(ref, str) or not ref:
            continue
        try:
            path, person0 = runtime.owner(ref)
        except (ValueError, KeyError, FileNotFoundError):
            continue
        person = dict(person0)
        ensure_person_military_rank(person)
        assignment = dict(person.get("command_assignment", {})) if isinstance(person.get("command_assignment"), Mapping) else {}
        assignment.update({"formation_ref": formation.get("formation_ref"), "billet": billet, "current_command_span": personnel, "external_to_fighting_strength": True})
        person["command_assignment"] = assignment
        career = person.setdefault("career_state", {})
        career["current_billet"] = billet
        career["current_command_span"] = personnel
        military = person.setdefault("military_command", {})
        if isinstance(military, dict):
            military["formation_scope"] = formation.get("formation_ref")
            military["external_to_fighting_strength"] = True
            # This is the live commanded span, not the durable rank grade.
            # Casualties can reduce a 500-established formation below 500, so
            # retaining the pre-casualty numeric label would split the exact
            # billet projection from the formation's conserved personnel.
            military["level"] = f"{personnel}_commander"

        # Generated external commanders historically carried a numeric command
        # label in both role and career metadata.  When their formation grew, the
        # assignment span changed but those duplicate labels did not.  Refresh
        # only that narrow numeric-label shape so named titles remain untouched.
        formation_name = str(formation.get("name") or formation.get("formation_ref") or "formation")
        current_role = str(person.get("role", ""))
        current_office = str(career.get("office_or_command", ""))
        if current_role.split("-man Commander, ", 1)[0].isdigit() and "-man Commander, " in current_role:
            person["role"] = f"{personnel}-man Commander, {formation_name}"
        if current_office.split("-man Commander, ", 1)[0].isdigit() and "-man Commander, " in current_office:
            career["office_or_command"] = f"{personnel}-man Commander, {formation_name}"
        runtime.put(path, person)

    refs = formation.get("embedded_person_refs", [])
    refs = [str(ref) for ref in refs if isinstance(ref, str)] if isinstance(refs, list) else []
    by_scale: dict[int, list[tuple[str, str, dict[str, Any]]]] = {1000: [], 500: [], 100: []}
    for ref in refs:
        try:
            path, person0 = runtime.owner(ref)
        except (ValueError, KeyError, FileNotFoundError):
            continue
        person = dict(person0)
        scale = _rank_scale(person)
        if scale in by_scale:
            by_scale[scale].append((ref, path, person))
    for scale, rows in by_scale.items():
        rows.sort(key=lambda x: x[0])
        rank_key = f"{scale}_commander"
        active_n = min(len(rows), max(0, int(cadre.get("active_billets", {}).get(rank_key, 0))))
        remaining = personnel
        for i, (ref, path, person) in enumerate(rows):
            ensure_person_military_rank(person, inferred_grade=rank_key)
            assignment = dict(person.get("command_assignment", {})) if isinstance(person.get("command_assignment"), Mapping) else {}
            if i < active_n:
                span = min(scale, max(0, remaining))
                remaining = max(0, remaining - span)
                billet = f"internal_{scale}_command"
            else:
                span = 0
                billet = "formation_officer_cadre_reserve"
            assignment.update({"formation_ref": formation.get("formation_ref"), "scale": scale, "billet": billet, "current_command_span": span, "external_to_fighting_strength": False})
            person["command_assignment"] = assignment
            career = person.setdefault("career_state", {})
            career["current_billet"] = billet
            career["current_command_span"] = span
            runtime.put(path, person)
