"""Integrity overlay for the final command-depth lifecycle.

This mixin owns no campaign state. It closes lifecycle and conservation edge cases
around ``WarfareDepthMixin``:

* secondary formation staff/support are released before a merge deletes owners;
* mercenary command/support duty is carved from existing company headcount; and
* materialized officers embedded inside formation fighting strength are not counted
  a second time by top-level force conservation.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.warfare_depth import WarfareDepthMixin


class WarfareDepthIntegrityMixin:
    """Production integrity hooks layered immediately above WarfareDepthMixin."""

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "formation_merge":
            refs = payload.get("formation_refs", [])
            if isinstance(refs, list):
                for ref in refs[1:]:
                    if isinstance(ref, str) and ref:
                        self._release_formation_external_personnel(ref)
        return super()._dispatch(command, payload)

    def _ensure_mercenary_command_structure(self, mercenary_ref: str) -> Mapping[str, Any]:
        """Carve aggregate command/support duty from existing company headcount."""
        base = super()._ensure_mercenary_command_structure(mercenary_ref)
        path = self.owner_path(mercenary_ref)
        company0 = self.read(path)
        if not isinstance(company0, Mapping):
            return base
        company = copy.deepcopy(company0)
        structure = copy.deepcopy(dict(base))
        total = max(0, int(structure.get("company_headcount", company.get("headcount", 0))))
        explicit_non_fighting = max(0, int(structure.get("existing_non_fighting_personnel", 0)))
        unit = structure.get("unit_command", {})
        support = structure.get("support", {})
        if not isinstance(unit, MutableMapping) or not isinstance(support, MutableMapping):
            return base

        commander_billets = max(0, int(unit.get("commander_billets", 0)))
        deputy_billets = max(0, int(unit.get("deputy_billets", 0)))
        command_target = commander_billets + deputy_billets

        rules = self._warfare_depth_rules()
        cfg = rules.get("mercenary_command_structure", {}) if isinstance(rules, Mapping) else {}
        per_500 = cfg.get("support_target_per_500_fighters", {}) if isinstance(cfg, Mapping) else {}
        support_per_block = (
            sum(max(0, int(value)) for value in per_500.values())
            if isinstance(per_500, Mapping)
            else 0
        )

        fighting = max(0, total - explicit_non_fighting)
        assigned = explicit_non_fighting
        support_target = 0
        for _ in range(8):
            blocks = (fighting + 499) // 500 if fighting else 0
            support_target = blocks * support_per_block
            combined_target = command_target + support_target
            new_assigned = min(total, max(explicit_non_fighting, combined_target))
            new_fighting = max(0, total - new_assigned)
            if new_assigned == assigned and new_fighting == fighting:
                break
            assigned = new_assigned
            fighting = new_fighting

        combined_target = command_target + support_target
        reassigned = max(0, assigned - explicit_non_fighting)
        command_staffed = min(command_target, assigned)
        support_staffed = min(support_target, max(0, assigned - command_staffed))
        shortfall = max(0, combined_target - assigned)

        unit["aggregate_billets_staffed"] = command_staffed
        unit["effective_billets_staffed"] = command_staffed
        unit["staffing_shortfall"] = max(0, command_target - command_staffed)
        unit["staffing_basis"] = "inside conserved company headcount"
        support["target_total"] = support_target
        support["combined_command_and_support_target"] = combined_target
        support["assigned_support_personnel"] = support_staffed
        support["assigned_non_fighting_personnel"] = assigned
        support["aggregate_reassignment_from_combat_pools"] = reassigned
        support["staffing_shortfall"] = shortfall

        structure["assigned_non_fighting_personnel"] = assigned
        structure["aggregate_reassignment_from_combat_pools"] = reassigned
        structure["fighting_establishment"] = fighting
        structure["fighting_establishment_if_target_staffed"] = fighting
        structure["personnel_conservation_rule"] = (
            "company headcount is unchanged; explicit support pools plus aggregate "
            "command/support duty assignments are subtracted before fighting strength"
        )
        structure["internal_command_support_assignment"] = {
            "explicit_non_fighting_personnel": explicit_non_fighting,
            "aggregate_reassigned_from_combat_pools": reassigned,
            "assigned_non_fighting_personnel": assigned,
            "command_target": command_target,
            "support_target": support_target,
            "combined_target": combined_target,
            "staffing_shortfall": shortfall,
            "rule": "aggregate duty assignment inside existing company headcount; zero new bodies",
        }
        company["internal_command_support_assignment"] = copy.deepcopy(
            structure["internal_command_support_assignment"]
        )
        company["command_structure"] = structure
        self.put(path, company)
        return structure

    def _validate_invariants(self, overlay: Any, paths: Any) -> None:
        """Validate external personnel and materialized formation slots exactly once."""

        class _LegacyForceView:
            def __init__(self, inner: Any) -> None:
                self.inner = inner

            def read_optional_bytes(self, path: str) -> Any:
                return self.inner.read_optional_bytes(path)

            def read_json(self, path: str) -> Any:
                value = self.inner.read_json(path)
                if not path.startswith("state/forces/") or not isinstance(value, Mapping):
                    return value
                external = value.get("external_personnel_allocations", {})
                assignments = value.get("materialized_assignments", {})
                assigned_refs = {
                    str(person_ref)
                    for person_ref, assignment in assignments.items()
                    if isinstance(assignments, Mapping)
                    and isinstance(assignment, Mapping)
                    and str(assignment.get("formation_ref", ""))
                } if isinstance(assignments, Mapping) else set()
                if (not isinstance(external, Mapping) or not external) and not assigned_refs:
                    return value
                adapted = copy.deepcopy(value)
                people = adapted.get("materialized_people", {})
                if isinstance(people, MutableMapping):
                    for person_ref in assigned_refs:
                        people.pop(person_ref, None)
                if isinstance(external, Mapping) and external:
                    roles = adapted.setdefault("available_by_role", {})
                    locations = adapted.setdefault("available_by_location", {})
                    default_location = str(adapted.get("source_location_ref", ""))
                    if not default_location:
                        default_location = next(iter(locations), "validation_external_allocation")
                    local = locations.setdefault(default_location, {})
                    for by_role in external.values():
                        if not isinstance(by_role, Mapping):
                            continue
                        for role, raw_count in by_role.items():
                            count = max(0, int(raw_count))
                            roles[str(role)] = int(roles.get(str(role), 0)) + count
                            local[str(role)] = int(local.get(str(role), 0)) + count
                return adapted

        super(WarfareDepthMixin, self)._validate_invariants(_LegacyForceView(overlay), paths)

        for path in paths:
            if not str(path).startswith("state/forces/") or overlay.read_optional_bytes(path) is None:
                continue
            force = overlay.read_json(path)
            if not isinstance(force, Mapping):
                continue
            available = sum(max(0, int(v)) for v in force.get("available_by_role", {}).values()) if isinstance(force.get("available_by_role"), Mapping) else 0
            fighting = sum(int(v.get("personnel", 0)) if isinstance(v, Mapping) else int(v) for v in force.get("allocated_to_formations", {}).values()) if isinstance(force.get("allocated_to_formations"), Mapping) else 0
            raw_external = force.get("external_personnel_allocations", {})
            external = sum(
                max(0, int(count))
                for roles in raw_external.values()
                if isinstance(raw_external, Mapping) and isinstance(roles, Mapping)
                for count in roles.values()
            ) if isinstance(raw_external, Mapping) else 0
            assignments = force.get("materialized_assignments", {})
            assigned_refs = {
                str(person_ref)
                for person_ref, assignment in assignments.items()
                if isinstance(assignment, Mapping) and str(assignment.get("formation_ref", ""))
            } if isinstance(assignments, Mapping) else set()
            people = force.get("materialized_people", {})
            materialized_unassigned = sum(
                int(value.get("personnel", 1)) if isinstance(value, Mapping) else int(value)
                for person_ref, value in people.items()
                if str(person_ref) not in assigned_refs
            ) if isinstance(people, Mapping) else 0
            if available + fighting + external + materialized_unassigned != int(force.get("headcount", -1)):
                raise ValueError("force conservation including external personnel failed")
            validate_cohort_ledger(force)


__all__ = ["WarfareDepthIntegrityMixin"]
