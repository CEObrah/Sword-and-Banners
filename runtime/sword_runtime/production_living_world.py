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
from sword_runtime.development import resolve_exceptional_skill_breakthrough, skill_category
from sword_runtime.living_world import OPERATIONAL_MEMORY_PATH
from sword_runtime.history_store import recent_history_events


_ACTIVE_OPERATION_STATES = frozenset({"planned", "mobilizing", "active", "engaged", "occupied"})
_HISTORY_EVENTS_PATH = "state/history/events/index.json"
_EXPECTED_BREAKTHROUGH_BLOCKERS = frozenset({
    "exceptional progression evidence depth is insufficient",
    "exceptional progression lacks enough unused exact-person evidence",
    "exceptional progression evidence lacks contextual novelty",
    "exceptional progression consolidation is insufficient",
    "exceptional progression cooldown is active",
})


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

    @staticmethod
    def _breakthrough_event_relevant(focus: str, event: Mapping[str, Any]) -> bool:
        """Require domain-relevant saved experience before exceptional growth."""
        kind = str(event.get("kind", "")).lower()
        if not kind:
            return False
        martial = ("combat", "battle", "siege", "duel", "assault", "skirmish", "pursuit", "withdraw")
        command = martial + ("operation", "campaign", "command", "formation", "territorial")
        if skill_category(focus) == "physical_or_martial_skill":
            return any(token in kind for token in martial)
        if focus in {"Formation Command", "Leadership", "Logistics", "Mass Combat", "Strategy", "Tactics"}:
            return any(token in kind for token in command)
        if focus in {"Governance", "Law"}:
            return any(token in kind for token in ("govern", "law", "institution", "appointment", "career", "project", "territorial"))
        if focus in {"Diplomacy", "Intrigue", "Trade", "Intelligence Operations"}:
            return any(token in kind for token in ("diplom", "intelligence", "information", "negoti", "contract", "trade", "market", "relationship", "reputation", "state"))
        if focus == "Engineering":
            return any(token in kind for token in ("engineer", "fortification", "siege", "project", "construction", "repair"))
        if focus == "Medicine":
            return any(token in kind for token in ("health", "injury", "recovery", "medicine", "medical"))
        if focus == "Training":
            return any(token in kind for token in ("training", "doctrine", "formation", "instruction"))
        return any(token in kind for token in ("project", "institution", "career", "information", "operation"))

    def _breakthrough_evidence_candidates(self, focus: str) -> list[Mapping[str, Any]]:
        """Return a bounded deterministic set of persisted, relevant world events."""
        rows = recent_history_events(self, 512)
        return [event for event in rows if self._breakthrough_event_relevant(focus, event)]

    def _resolve_training_breakthrough_if_ready(
        self,
        *,
        focus: str,
        training_result: Mapping[str, Any],
    ) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
        """Consolidate already-earned exact-person evidence after deliberate training.

        Ordinary training remains authoritative through the routine ceiling. Once
        the staged player is at or above that ceiling, a training session may
        consolidate one exceptional point only from server-discovered persisted
        evidence. Missing evidence, novelty, consolidation, or cooldown is a normal
        no-breakthrough outcome. Malformed progression state still fails closed.
        """
        player = self.read("state/player.json")
        if not isinstance(player, dict):
            raise ValueError("player progression owner is invalid")
        skills = player.get("skills")
        if not isinstance(skills, Mapping) or focus not in skills:
            raise ValueError("player progression target is invalid")
        routine = training_result.get("routine_training_ceiling")
        current = skills.get(focus)
        if (
            isinstance(routine, bool)
            or not isinstance(routine, int)
            or isinstance(current, bool)
            or not isinstance(current, int)
            or current < routine
        ):
            return dict(training_result), None
        evidence = self._breakthrough_evidence_candidates(focus)
        if not evidence:
            return dict(training_result), None
        training = self.read("game/data/mechanics/training.json")
        try:
            breakthrough = resolve_exceptional_skill_breakthrough(
                player,
                focus,
                evidence,
                self._world_time(),
                training,
            )
        except ValueError as exc:
            if str(exc) in _EXPECTED_BREAKTHROUGH_BLOCKERS:
                return dict(training_result), None
            raise
        self.put("state/player.json", player)
        updated = dict(training_result)
        updated["skill_score"] = int(breakthrough["ending_value"])
        updated["exceptional_breakthrough_point"] = 1
        updated["exceptional_breakthrough"] = {
            "starting_value": int(breakthrough["starting_value"]),
            "ending_value": int(breakthrough["ending_value"]),
            "evidence_count": len(breakthrough["evidence_event_refs"]),
            "distinct_contexts": int(breakthrough["distinct_contexts"]),
            "consolidation_units": float(breakthrough["consolidation_units"]),
        }
        history = player.get("training_history")
        if isinstance(history, list) and history and isinstance(history[-1], dict):
            history[-1]["development"] = copy.deepcopy(updated)
        return updated, breakthrough

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = super()._dispatch(command, payload)
        if command.command_type != "individual_training":
            return result
        focus = str(payload.get("focus", "Training"))
        development = result.get("development") if isinstance(result, Mapping) else None
        if not isinstance(development, Mapping):
            return result
        updated_development, breakthrough = self._resolve_training_breakthrough_if_ready(
            focus=focus,
            training_result=development,
        )
        if breakthrough is None:
            return result
        updated = dict(result)
        updated["development"] = updated_development
        updated["exceptional_breakthrough"] = updated_development["exceptional_breakthrough"]
        return updated

    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_state(host, occurrences, at)
        state = self._state_key(str(host["owner_ref"]))
        operation_index_path = "state/operations/index.json"
        operation_index = self.read(operation_index_path)
        operations = operation_index.get("operations") if isinstance(operation_index, Mapping) else None
        if not isinstance(operations, Mapping):
            raise ValueError("operation index is invalid")

        own_prefix = f"operation_auto_{state}_"
        own_response = f"operation_auto_{state}_border_response"
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
            if operation_ref == own_response or operation_ref.startswith(own_prefix):
                own_active.append((operation_ref, path))
                continue
            used.update(str(ref) for ref in refs if isinstance(ref, str) and ref)

        memory_view = self.read_optional(OPERATIONAL_MEMORY_PATH)
        scoring_memory = (
            memory_view
            if isinstance(memory_view, dict)
            else {"state_memory": {}, "formation_memory": {}}
        )
        cancelled: list[str] = []
        for operation_ref, path in own_active:
            operation = copy.deepcopy(self.read(path))
            refs = [str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str) and ref]
            keep: list[str] = []
            kept_formations: list[Mapping[str, Any]] = []
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
                    scoring_memory,
                    used,
                ) <= -(10**8):
                    continue
                keep.append(formation_ref)
                kept_formations.append(formation)
                used.add(formation_ref)

            old_status = str(operation.get("status", "planned"))
            if not keep:
                operation["formation_refs"] = []
                operation["status"] = "cancelled"
                operation["updated_at"] = at
                cancelled.append(operation_ref)
                operations.pop(operation_ref, None)
                operation_index["terminal_operation_count"] = int(operation_index.get("terminal_operation_count", 0)) + 1
                recent = operation_index.setdefault("recent_terminal_refs", [])
                recent.append({"operation_ref": operation_ref, "status": "cancelled", "at": at})
                del recent[:-64]
            else:
                operation["formation_refs"] = keep
                locations = {str(formation.get("location_ref", "")) for formation in kept_formations}
                exact_location = str(operation.get("location_ref", ""))
                physically_active = (
                    len(locations) == 1
                    and exact_location in locations
                    and all(bool(formation.get("mobilized", False)) for formation in kept_formations)
                )
                if old_status in {"planned", "mobilizing", "active"}:
                    operation["status"] = "active" if physically_active else "mobilizing"
                elif not physically_active:
                    # Engaged/occupied state has stronger semantics than a
                    # background readiness review may lawfully rewrite. Fail
                    # closed rather than silently regressing a live operation.
                    raise ValueError("autonomous operation lost exact active-state prerequisites")

            if operation.get("status") != old_status:
                history = operation.setdefault("status_history", [])
                if not isinstance(history, list):
                    raise ValueError("operation status history is invalid")
                history.append({"from": old_status, "status": operation["status"], "at": at})
                del history[:-32]
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
        injected_compat_field = False
        if isinstance(event, dict):
            location_ref = event.get("location_ref")
            if (
                isinstance(location_ref, str)
                and location_ref
                and not isinstance(event.get("battlefield_ref"), str)
            ):
                # CausalLivingWorldSwordPlanner uses this semantic
                # input battlefield_ref. The interstate reducer actually owns
                # the exact field as location_ref. Adapt only for the duration
                # of provenance derivation and do not persist a duplicate field.
                event["battlefield_ref"] = location_ref
                injected_compat_field = True
        try:
            super()._record_interstate_battle_memory(event, at)
        finally:
            if injected_compat_field and isinstance(event, dict):
                event.pop("battlefield_ref", None)


__all__ = ["ProductionLivingWorldSwordPlanner"]
