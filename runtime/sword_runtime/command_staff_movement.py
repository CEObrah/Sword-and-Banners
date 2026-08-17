"""Reconcile exact formation command staff when controlled formations move.

The formation owner remains command-role authority. Named commander/deputy people
remain separate exact owners, so movement must not leave their person records
silently behind when they are physically with the formation. Detached staff are
never teleported: only staff already at the formation origin (or already at the
destination) are reconciled.
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
                if not isinstance(person_ref, str) or not person_ref:
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
            if current_location == origin:
                self._set_person_location(person, destination)
                changed = True
            if current_location in {origin, destination}:
                if person.get("current_formation_id") != formation_ref:
                    person["current_formation_id"] = formation_ref
                    changed = True
            if changed:
                self.put(path, person)
            if current_location in {origin, destination}:
                reconciled.append(person_ref)
        return reconciled

    def _autonomy_move_formation_step(self, formation_ref: str, destination: str, at: str) -> dict[str, Any]:
        """Extend autonomous formation movement to exact deputies as well as commanders."""

        try:
            _path, formation_before = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return super()._autonomy_move_formation_step(formation_ref, destination, at)
        origin = str(formation_before.get("location_ref", ""))
        deputy_ref = formation_before.get("deputy_ref")
        deputy_path = None
        deputy_origin = None
        if isinstance(deputy_ref, str) and deputy_ref:
            owners = self.read("state/index/owner-index.json").get("owners", {})
            path = owners.get(deputy_ref) if isinstance(owners, Mapping) else None
            if isinstance(path, str):
                deputy_path = path
                deputy = self.read(path)
                if isinstance(deputy, Mapping):
                    deputy_origin = self._person_location(deputy)

        result = super()._autonomy_move_formation_step(formation_ref, destination, at)
        if not deputy_path or not isinstance(deputy_ref, str):
            return result
        try:
            formation_path, formation_after0 = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return result
        formation_after = copy.deepcopy(formation_after0)
        reached = str(formation_after.get("location_ref", origin))
        if reached == origin:
            return result

        person0 = self.read(deputy_path)
        if not isinstance(person0, Mapping):
            return result
        person = copy.deepcopy(dict(person0))
        changed_person = False
        changed_formation = False
        if deputy_origin == origin:
            self._set_person_location(person, reached)
            person["current_formation_id"] = formation_ref
            changed_person = True
        elif deputy_origin == reached:
            if person.get("current_formation_id") != formation_ref:
                person["current_formation_id"] = formation_ref
                changed_person = True
        else:
            if formation_after.get("deputy_ref") == deputy_ref:
                formation_after["deputy_ref"] = None
                formation_after["deputy_detached_at"] = at
                changed_formation = True
        if changed_person:
            self.put(deputy_path, person)
        if changed_formation:
            self.put(formation_path, formation_after)
        if changed_person:
            out = dict(result)
            out["deputy_reconciled"] = deputy_ref
            return out
        return result

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
