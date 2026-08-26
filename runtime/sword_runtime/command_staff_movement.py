"""Reconcile exact formation and command-group staff when controlled formations move.

The formation owner remains command-role authority. Named commanders and command-group
staff remain separate exact owners, so movement must not leave those person records
silently behind. Player escorted travel treats a selected formation as including its
saved exact top command establishment. A zero-body command group moves only when its
whole descendant formation tree moves, and only co-located attached headquarters
personnel move with it. Detached staff are never teleported.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_briefing import reconcile_campaign_arrival


class CommandStaffMovementMixin:
    """Keep exact command personnel aligned with physically moved command owners."""

    def _movement_formation_refs(self, command: Any, payload: Mapping[str, Any]) -> list[str]:
        if command.command_type == "formation_move":
            ref = payload.get("formation_ref")
            return [str(ref)] if isinstance(ref, str) and ref else []
        if command.command_type == "command_group_action" and str(payload.get("action", "")) == "move_army":
            from sword_runtime.command_units import FORMATION, unit_entries
            root = payload.get("command_group_ref")
            if not isinstance(root, str) or not root:
                return []
            allowed: set[str] | None = None
            operation_ref = payload.get("operation_ref")
            if isinstance(operation_ref, str) and operation_ref:
                index = self.read("state/operations/index.json")
                op_path = index.get("operations", {}).get(operation_ref) if isinstance(index, Mapping) else None
                operation = self.read(str(op_path)) if isinstance(op_path, str) else None
                if isinstance(operation, Mapping):
                    allowed = {str(x) for x in operation.get("formation_refs", []) if isinstance(x, str) and x}
            refs: list[str] = []
            stack: list[str] = [root]
            seen: set[str] = set()
            while stack:
                group_ref = stack.pop()
                if group_ref in seen:
                    raise ValueError("command hierarchy contains a cycle")
                seen.add(group_ref)
                doc = self.read(f"state/cmd/command-groups/{group_ref}.json")
                children: list[str] = []
                for row in unit_entries(doc):
                    if row["kind"] == FORMATION:
                        ref = str(row["ref"])
                        if allowed is None or ref in allowed:
                            refs.append(ref)
                    else:
                        children.append(str(row["ref"]))
                stack.extend(reversed(children))
            return refs
        if command.command_type == "travel":
            refs = payload.get("formation_refs")
            if isinstance(refs, list):
                return [str(ref) for ref in refs if isinstance(ref, str) and ref]
        return []

    @staticmethod
    def _formal_command_refs(formation: Mapping[str, Any]) -> list[str]:
        """Return the one external top-command ref, excluding embedded ranks."""
        value = formation.get("commander_ref")
        return [value] if isinstance(value, str) and value else []

    @staticmethod
    def _command_group_person_refs(group: Mapping[str, Any]) -> list[str]:
        """Return exact people physically attached to a zero-body headquarters.

        Authority refs are deliberately excluded: institutional authority is not a
        physical headquarters attachment. Commander, direct staff, assigned role
        holders, and declared successors are physical people when co-located.
        """
        refs: list[str] = []
        commander = group.get("commander_ref")
        if isinstance(commander, str) and commander:
            refs.append(commander)
        direct = group.get("direct_person_refs", [])
        if isinstance(direct, list):
            refs.extend(str(ref) for ref in direct if isinstance(ref, str) and ref)
        roles = group.get("role_assignments", {})
        if isinstance(roles, Mapping):
            refs.extend(str(ref) for ref in roles if isinstance(ref, str) and ref)
        successors = group.get("successor_refs", [])
        if isinstance(successors, list):
            refs.extend(str(ref) for ref in successors if isinstance(ref, str) and ref)
        return list(dict.fromkeys(refs))

    def _command_staff_snapshots(self, refs: list[str]) -> list[tuple[str, str, str, str]]:
        rows: list[tuple[str, str, str, str]] = []
        for formation_ref in refs:
            _formation_path, formation = self._load_formation(formation_ref)
            origin = str(formation.get("location_ref", ""))
            for person_ref in self._formal_command_refs(formation):
                try:
                    path = self.owner_path(person_ref)
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                rows.append((formation_ref, person_ref, path, origin))
        return rows

    def _muster_escorted_command_staff(
        self,
        command: Any,
        payload: Mapping[str, Any],
        snapshots: list[tuple[str, str, str, str]],
    ) -> dict[str, Any]:
        """Physically reunite assigned exact staff before one escorted player march."""
        if command.command_type != "travel" or not payload.get("formation_refs"):
            return {"hours": 0, "refs": []}

        player = self.read("state/player.json")
        origin = str(player.get("location", ""))
        if not origin:
            return {"hours": 0, "refs": []}

        planned: dict[str, dict[str, Any]] = {}
        muster_hours = 0
        for formation_ref, person_ref, path, formation_origin in snapshots:
            if formation_origin != origin:
                continue

            existing = planned.get(person_ref)
            if existing is not None:
                if existing["formation_ref"] != formation_ref:
                    raise ValueError("exact command staff cannot muster to multiple escorted formations")
                continue

            person0 = self.read(path)
            if not isinstance(person0, Mapping):
                continue
            person = copy.deepcopy(dict(person0))
            current_location = self._person_location(person)
            if current_location == formation_origin:
                continue
            if not isinstance(current_location, str) or not current_location:
                continue

            hours = int(
                self._route_travel_hours(
                    current_location,
                    formation_origin,
                    modes=("foot",),
                )
            )
            if hours <= 0:
                raise ValueError("detached command staff muster requires positive physical travel time")
            muster_hours = max(muster_hours, hours)
            planned[person_ref] = {
                "formation_ref": formation_ref,
                "path": path,
                "start_location": current_location,
                "destination": formation_origin,
            }

        if not planned:
            return {"hours": 0, "refs": []}

        target = str(self._world_time().add_seconds(muster_hours * 3600))
        self._advance_runtime(target)

        mustered: list[str] = []
        for person_ref, row in planned.items():
            person0 = self.read(str(row["path"]))
            if not isinstance(person0, Mapping):
                raise ValueError("assigned command staff owner disappeared during muster")
            person = copy.deepcopy(dict(person0))
            current_location = self._person_location(person)
            destination = str(row["destination"])
            if current_location == destination:
                pass
            elif current_location == row["start_location"]:
                self._set_person_location(person, destination)
            else:
                raise ValueError("assigned command staff location changed during muster")
            person["current_formation_id"] = str(row["formation_ref"])
            self.put(str(row["path"]), person)
            mustered.append(person_ref)

        return {"hours": muster_hours, "refs": sorted(mustered)}

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

    def _reconcile_group_people(
        self,
        group: Mapping[str, Any],
        origin: str,
        destination: str,
    ) -> list[str]:
        """Move only exact headquarters people who were physically with the group."""
        if not origin or origin == destination:
            return []
        reconciled: list[str] = []
        for person_ref in self._command_group_person_refs(group):
            try:
                path = self.owner_path(person_ref)
                person0 = self.read(path)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if not isinstance(person0, Mapping):
                continue
            person = copy.deepcopy(dict(person0))
            current_location = self._person_location(person)
            if current_location == destination:
                reconciled.append(person_ref)
                continue
            if current_location != origin:
                continue
            self._set_person_location(person, destination)
            self.put(path, person)
            reconciled.append(person_ref)
        return reconciled

    def _reconcile_command_group_locations(
        self,
        refs: list[str],
        destination: str,
        *,
        staff_reconciled: list[str] | None = None,
    ) -> list[str]:
        """Move zero-body command owners only when their whole formation tree moved.

        Formation owners are physical authority. Command groups own no bodies, so a
        grouped travel command must not leave their saved headquarters location behind
        after every descendant formation has reached the same destination. Partial
        detachment movement deliberately leaves the parent group and its personnel in
        place. When a group does move, only attached exact people who were co-located
        at its old headquarters move with it; detached people are never teleported.
        """
        if not refs or not destination:
            return []
        try:
            index = self.read("state/cmd/command-groups/index.json")
        except (KeyError, ValueError, FileNotFoundError):
            return []
        primary = index.get("primary_formation_group", {}) if isinstance(index, Mapping) else {}
        if not isinstance(primary, Mapping):
            return []

        candidates: set[str] = set()
        for formation_ref in refs:
            current = primary.get(formation_ref)
            seen: set[str] = set()
            while isinstance(current, str) and current and current not in seen:
                seen.add(current)
                candidates.add(current)
                try:
                    group = self.read(f"state/cmd/command-groups/{current}.json")
                except (KeyError, ValueError, FileNotFoundError):
                    break
                parent = group.get("parent_command_group_ref") if isinstance(group, Mapping) else None
                current = parent if isinstance(parent, str) and parent else None

        from sword_runtime.command_units import recursive_refs

        changed: list[str] = []

        def depth(group_ref: str) -> int:
            n = 0
            current = group_ref
            seen: set[str] = set()
            while current not in seen:
                seen.add(current)
                try:
                    group = self.read(f"state/cmd/command-groups/{current}.json")
                except (KeyError, ValueError, FileNotFoundError):
                    break
                parent = group.get("parent_command_group_ref") if isinstance(group, Mapping) else None
                if not isinstance(parent, str) or not parent:
                    break
                n += 1
                current = parent
            return n

        for group_ref in sorted(candidates, key=lambda ref: (-depth(ref), ref)):
            path = f"state/cmd/command-groups/{group_ref}.json"
            try:
                group0 = self.read(path)
                descendant_refs, _command_refs = recursive_refs(
                    lambda ref: self.read(f"state/cmd/command-groups/{ref}.json"),
                    group_ref,
                )
            except (KeyError, ValueError, FileNotFoundError):
                continue
            formation_refs = sorted(str(ref) for ref in descendant_refs)
            if not formation_refs:
                continue
            all_here = True
            for formation_ref in formation_refs:
                try:
                    _formation_path, formation = self._load_formation(formation_ref)
                except (KeyError, ValueError, FileNotFoundError):
                    all_here = False
                    break
                if str(formation.get("location_ref", "")) != destination:
                    all_here = False
                    break
            if not all_here:
                continue
            origin = str(group0.get("location", ""))
            if origin == destination:
                continue
            reconciled_people = self._reconcile_group_people(group0, origin, destination)
            if staff_reconciled is not None:
                staff_reconciled.extend(reconciled_people)
            group = copy.deepcopy(dict(group0))
            group["location"] = destination
            group["updated_at"] = str(self._world_time())
            self.put(path, group)
            changed.append(group_ref)
        return changed

    def _reconcile_campaign_arrivals_after_movement(
        self,
        refs: list[str],
        destination: str,
    ) -> list[dict[str, Any]]:
        """Close exact campaign movement phases whose saved arrival condition is now true.

        The operations index is routing only. Each candidate exact operation remains
        authority, and ``reconcile_campaign_arrival`` revalidates the complete saved
        participant set before changing phase or delivering a field report. This means
        the final straggler may complete staging, while partial movement cannot.
        """
        if not refs or not destination:
            return []
        try:
            index = self.read("state/operations/index.json")
        except (KeyError, ValueError, FileNotFoundError):
            return []
        routes = index.get("operations", {}) if isinstance(index, Mapping) else {}
        if not isinstance(routes, Mapping):
            return []
        moved = set(refs)
        reports: list[dict[str, Any]] = []
        for operation_ref, path in sorted(routes.items()):
            if not isinstance(operation_ref, str) or not operation_ref or not isinstance(path, str) or not path:
                continue
            try:
                operation = self.read(path)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if not isinstance(operation, Mapping):
                continue
            participants = {
                str(ref)
                for ref in operation.get("formation_refs", [])
                if isinstance(ref, str) and ref
            }
            if not moved.intersection(participants):
                continue
            orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
            last_ref = str(operation.get("last_operational_order_ref", ""))
            order: Mapping[str, Any] | None = None
            for row in reversed(orders):
                if not isinstance(row, Mapping):
                    continue
                if last_ref and str(row.get("order_ref", "")) != last_ref:
                    continue
                order = row
                break
            if not isinstance(order, Mapping):
                continue
            packet = order.get("mission_packet") if isinstance(order.get("mission_packet"), Mapping) else None
            if not isinstance(packet, Mapping):
                continue
            if str(packet.get("destination_ref", "")) != destination:
                continue
            if str(packet.get("phase_status", "")) == "completed":
                continue
            report = reconcile_campaign_arrival(
                self,
                operation_ref,
                destination_ref=destination,
                at=str(self._world_time()),
                unit_duties=[],
            )
            if report is not None:
                reports.append({
                    "operation_ref": operation_ref,
                    "phase": report.get("phase"),
                    "information_ref": report.get("information_ref"),
                })
        return reports

    def _autonomy_move_formation_step(self, formation_ref: str, destination: str, at: str) -> dict[str, Any]:
        """Move every co-located full formal command-establishment person once."""
        try:
            _path, formation_before = self._load_formation(formation_ref)
            origin = str(formation_before.get("location_ref", ""))
            snapshots = self._command_staff_snapshots([formation_ref])
        except (KeyError, ValueError, FileNotFoundError):
            return super()._autonomy_move_formation_step(formation_ref, destination, at)

        result = super()._autonomy_move_formation_step(formation_ref, destination, at)
        try:
            _after_path, formation_after = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return result
        reached = str(formation_after.get("location_ref", origin))
        if reached == origin:
            return result

        reconciled = self._reconcile_moved_command_staff(snapshots, reached)
        if reconciled:
            out = dict(result)
            out["command_staff_reconciled"] = sorted(set(reconciled))
            result = out
        reports = self._reconcile_campaign_arrivals_after_movement([formation_ref], reached)
        if reports:
            out = dict(result)
            out["campaign_arrival_reports"] = reports
            result = out
        return result

    def _command_layer_command_staff_movement(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        refs = self._movement_formation_refs(command, payload)
        if not refs:
            return next_dispatch()

        snapshots = self._command_staff_snapshots(refs)
        muster = self._muster_escorted_command_staff(command, payload, snapshots)
        result = next_dispatch()
        destination = payload.get("destination_ref")
        if command.command_type == "command_group_action" and str(payload.get("action", "")) == "move_army":
            destination = payload.get("location_ref")
        if isinstance(destination, str) and destination:
            reconciled = self._reconcile_moved_command_staff(snapshots, destination)
            if reconciled:
                result = dict(result)
                result["command_staff_reconciled"] = sorted(set(reconciled))
            group_staff: list[str] = []
            moved_groups = self._reconcile_command_group_locations(
                refs,
                destination,
                staff_reconciled=group_staff,
            )
            if moved_groups:
                result = dict(result)
                result["command_groups_reconciled"] = sorted(set(moved_groups))
            if group_staff:
                result = dict(result)
                result["command_group_staff_reconciled"] = sorted(set(group_staff))
            reports = self._reconcile_campaign_arrivals_after_movement(refs, destination)
            if reports:
                result = dict(result)
                result["campaign_arrival_reports"] = reports

        muster_hours = int(muster.get("hours", 0) or 0)
        mustered_refs = [str(ref) for ref in muster.get("refs", []) if isinstance(ref, str)]
        if muster_hours or mustered_refs:
            result = dict(result)
            result["command_staff_muster_hours"] = muster_hours
            result["command_staff_mustered"] = sorted(set(mustered_refs))
            duration = result.get("duration_hours")
            if isinstance(duration, int) and not isinstance(duration, bool):
                result["column_duration_hours"] = duration
                result["duration_hours"] = duration + muster_hours
        return result
