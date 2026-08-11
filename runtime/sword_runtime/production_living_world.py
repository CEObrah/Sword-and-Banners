"""Final production-only living-world normalizations.

Keep these corrections above the reusable causal planner so the historical
battle reducer remains authoritative while the hosted runtime exposes exact
saved locations and respects existing formation commitments as hard eligibility
constraints.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from sword_runtime.causal_living_world import CausalLivingWorldSwordPlanner
from sword_runtime.living_world import OPERATIONAL_MEMORY_PATH


_ACTIVE_OPERATION_STATES = frozenset({"planned", "mobilizing", "active", "engaged", "occupied"})


class ProductionLivingWorldSwordPlanner(CausalLivingWorldSwordPlanner):
    """Hosted Sword planner with exact provenance and assignment integrity."""

    def _formation_score(
        self,
        formation_ref: str,
        formation: Mapping[str, Any],
        objective_text: str,
        memory: dict[str, Any],
        reserved: set[str],
    ) -> int:
        # Existing active operation commitments are hard custody/availability
        # facts, not a soft preference. A very strong formation must never win
        # its way through a penalty and become double-assigned.
        if formation_ref in reserved:
            return -(10**9)
        # Standing troops without an exact available commander are real assets,
        # but they are not autonomous deployment-ready formations. Do not invent
        # a replacement general or let raw troop quality erase command custody.
        commander_ref = formation.get("commander_ref")
        if not isinstance(commander_ref, str) or not commander_ref:
            return -(10**9)
        try:
            self._validate_person_location_for_formation(commander_ref, formation)
        except (KeyError, ValueError):
            return -(10**9)
        return super()._formation_score(
            formation_ref,
            formation,
            objective_text,
            memory,
            reserved,
        )

    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_state(host, occurrences, at)
        state = self._state_key(str(host["owner_ref"]))
        operation_index_path = "state/operations/index.json"
        operation_index = self.read(operation_index_path)
        operations = operation_index.get("operations") if isinstance(operation_index, Mapping) else None
        if not isinstance(operations, Mapping):
            raise ValueError("operation index is invalid")

        own_prefix = f"operation_auto_{state}_"
        own_legacy = f"operation_auto_{state}_border_response"
        used: set[str] = set()
        own_active: list[tuple[str, str]] = []

        # Manual commitments and other states' autonomous operations win the
        # custody conflict. They are existing exact commitments, not soft
        # preferences available for this state's reassignment.
        for operation_ref, path in sorted(operations.items()):
            if not isinstance(operation_ref, str) or not isinstance(path, str):
                raise ValueError("operation index is invalid")
            operation = self.read(path)
            if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATES:
                continue
            refs = operation.get("formation_refs")
            if not isinstance(refs, list):
                raise ValueError("active operation has invalid formation_refs")
            if operation_ref == own_legacy or operation_ref.startswith(own_prefix):
                own_active.append((operation_ref, path))
                continue
            used.update(str(ref) for ref in refs if isinstance(ref, str) and ref)

        cancelled: list[str] = []
        for operation_ref, path in own_active:
            operation = copy.deepcopy(self.read(path))
            refs = [str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref]
            keep: list[str] = []
            for formation_ref in refs:
                if formation_ref in used:
                    continue
                try:
                    _formation_path, formation = self._load_formation(formation_ref)
                except ValueError:
                    continue
                if self._formation_score(
                    formation_ref,
                    formation,
                    str(operation.get("objective", "operation")),
                    self.read_optional(OPERATIONAL_MEMORY_PATH)
                    if isinstance(self.read_optional(OPERATIONAL_MEMORY_PATH), dict)
                    else {"state_memory": {}, "formation_memory": {}},
                    used,
                ) <= -(10**8):
                    continue
                keep.append(formation_ref)
                used.add(formation_ref)
            if keep == refs:
                continue
            if keep:
                operation["formation_refs"] = keep
            else:
                operation["formation_refs"] = []
                operation["status"] = "cancelled"
                cancelled.append(operation_ref)
            self.put(path, operation)

        if cancelled:
            memory = self.read_optional(OPERATIONAL_MEMORY_PATH)
            if isinstance(memory, Mapping):
                memory_copy = copy.deepcopy(dict(memory))
                state_memory = memory_copy.get("state_memory", {}).get(state)
                if isinstance(state_memory, dict):
                    state_memory["active_operation_refs"] = [
                        ref
                        for ref in state_memory.get("active_operation_refs", [])
                        if ref not in cancelled
                    ]
                    completed = state_memory.setdefault("completed_operation_refs", [])
                    if not isinstance(completed, list):
                        raise ValueError("state operational memory is invalid")
                    for ref in cancelled:
                        self._bounded_append(completed, ref, 32)
                    self.put(OPERATIONAL_MEMORY_PATH, memory_copy)

    def _record_interstate_battle_memory(self, event: Mapping[str, Any], at: str) -> None:
        injected_legacy_field = False
        if isinstance(event, dict):
            location_ref = event.get("location_ref")
            if (
                isinstance(location_ref, str)
                and location_ref
                and not isinstance(event.get("battlefield_ref"), str)
            ):
                # CausalLivingWorldSwordPlanner historically named this semantic
                # input battlefield_ref. The interstate reducer actually owns
                # the exact field as location_ref. Bridge only for the duration
                # of provenance derivation and do not persist a duplicate field.
                event["battlefield_ref"] = location_ref
                injected_legacy_field = True
        try:
            super()._record_interstate_battle_memory(event, at)
        finally:
            if injected_legacy_field and isinstance(event, dict):
                event.pop("battlefield_ref", None)


__all__ = ["ProductionLivingWorldSwordPlanner"]
