"""Reconcile exact formation command staff when controlled formations move.

The formation owner remains command-role authority. Named commander/deputy
characters remain separate exact people, so movement must not leave their person
records silently behind when they are physically with the formation. Detached
staff are never teleported: only staff already at the formation origin (or
already at the destination) are reconciled.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


class CommandStaffMovementMixin:
    """Keep exact commander/deputy person state aligned with formation movement."""

    @staticmethod
    def _movement_formation_refs(command: Any, payload: Mapping[str, Any]) -> list[str]:
        if command.command_type == "formation_move":
            ref = payload.get("formation_ref")
            return [str(ref)] if isinstance(ref, str) and ref else []
        if command.command_type == "travel":
            refs = payload.get("formation_refs")
            if isinstance(refs, list):
                return [str(ref) for ref in refs if isinstance(ref, str) and ref]
        return []

    def _command_staff_snapshots(self, refs: list[str]) -> list[tuple[str, str, str, str]]:
        owners = self.read("state/index/owner-index.json").get("owners", {})
        rows: list[tuple[str, str, str, str]] = []
        for formation_ref in refs:
            _formation_path, formation = self._load_formation(formation_ref)
            origin = str(formation.get("location_ref", ""))
            for field in ("commander_ref", "deputy_ref"):
                person_ref = formation.get(field)
                if not isinstance(person_ref, str) or not person_ref.startswith("char_"):
                    continue
                path = owners.get(person_ref) if isinstance(owners, Mapping) else None
                if not isinstance(path, str):
                    continue
                rows.append((formation_ref, person_ref, path, origin))
        return rows

    def _reconcile_moved_command_staff(
        self,
        snapshots: list[tuple[str, str, str, str]],
        destination: str,
    ) -> list[str]:
        reconciled: list[str] = []
        seen: set[tuple[str, str]] = set()
        for formation_ref, person_ref, path, origin in snapshots:
            key = (formation_ref, person_ref)
            if key in seen:
                continue
            seen.add(key)
            person0 = self.read(path)
            if not isinstance(person0, Mapping):
                continue
            person = copy.deepcopy(dict(person0))
            current_location = self._person_location(person)
            changed = False
            # A registered staff member at the departing formation travels with
            # it. A person elsewhere is detached and must never be teleported.
            if current_location == origin:
                self._set_person_location(person, destination)
                changed = True
            if current_location in {origin, destination}:
                if person.get("current_formation_id") != formation_ref:
                    person["current_formation_id"] = formation_ref
                    changed = True
            if changed:
                self.put(path, person)
            # The inner movement reducer may already have moved a commander. A
            # command-staff reconciliation receipt reports every exact staff member
            # confirmed aligned with the moved formation, not only records this
            # outer adapter happened to rewrite.
            if current_location in {origin, destination}:
                reconciled.append(person_ref)
        return reconciled

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        refs = self._movement_formation_refs(command, payload)
        if not refs:
            return super()._dispatch(command, payload)

        snapshots = self._command_staff_snapshots(refs)
        result = super()._dispatch(command, payload)
        destination = payload.get("destination_ref")
        if isinstance(destination, str) and destination:
            reconciled = self._reconcile_moved_command_staff(snapshots, destination)
            if reconciled:
                result = dict(result)
                result["command_staff_reconciled"] = sorted(set(reconciled))
        return result


__all__ = ["CommandStaffMovementMixin"]
