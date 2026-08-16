"""Integrity overlay for the final command-depth lifecycle.

This mixin owns no campaign state. It closes two composition edge cases around
``WarfareDepthMixin``:

* secondary formation staff/support are released before a merge deletes their
  formation owners, preventing orphaned external personnel allocations; and
* mercenary companies assign enough of their already-conserved total headcount
  to company command/support before reporting fighting establishment. This is an
  aggregate duty assignment, not new manpower and not mass person materialization.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping, MutableMapping
from typing import Any


class WarfareDepthIntegrityMixin:
    """Production integrity hooks layered immediately above WarfareDepthMixin."""

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "formation_merge":
            refs = payload.get("formation_refs", [])
            if isinstance(refs, list):
                # The baseline merge reducer deletes refs[1:] after folding their
                # fighting cohorts into the primary. Return only their separate
                # external staff/support first; the primary keeps its attachments.
                for ref in refs[1:]:
                    if isinstance(ref, str) and ref:
                        self._release_formation_external_personnel(ref)
        return super()._dispatch(command, payload)

    def _ensure_mercenary_command_structure(self, mercenary_ref: str) -> Mapping[str, Any]:
        """Carve aggregate command/support duty from existing company headcount.

        Explicit support troop pools remain exactly what they are. If they are
        insufficient for the generic command/support establishment, the remaining
        billets are aggregate duty assignments from otherwise fighting company
        bodies. No troop pool, person record or headcount is created.
        """
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

        # Solve the small circularity between support target and resulting fighting
        # establishment. The deterministic fixed point converges in at most a few
        # iterations because only 500-person block boundaries can change.
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


__all__ = ["WarfareDepthIntegrityMixin"]
