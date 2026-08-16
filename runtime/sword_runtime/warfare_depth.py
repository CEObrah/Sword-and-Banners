"""Persistent combined-arms and formation command-depth integration.

A formation remains one conserved manpower owner.  Its internal officer/echelon
record describes command functions inside those already-counted bodies and never
creates extra soldiers.  State operations remain coordination owners only; they
may combine several persistent formations but never merge their casualty or
manpower authority.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.living_world import LivingWorldSwordPlanner, OPERATIONAL_MEMORY_PATH

_RULES_PATH = "game/data/mechanics/warfare-organization.json"
_ACTIVE_REVIEW_STATES = frozenset({"planned", "mobilizing", "active"})


def build_formation_command_structure(formation: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    cfg = rules.get("formation_command_structure", {}) if isinstance(rules, Mapping) else {}
    n = max(0, int(formation.get("personnel", 0)))
    century = max(1, int(cfg.get("century_size", 100)))
    company = max(century, int(cfg.get("company_size", 500)))
    wing = max(company, int(cfg.get("wing_size", 2000)))
    staff_per = max(0, int(cfg.get("staff_billets_per_500", 2)))
    signal_per = max(0, int(cfg.get("signal_billets_per_500", 2)))
    logistics_per = max(0, int(cfg.get("logistics_billets_per_500", 3)))
    blocks = max(1, (n + company - 1) // company) if n else 0
    minimum = max(1, int(cfg.get("minimum_aggregate_staffed_personnel", 500)))
    commander_ref = formation.get("commander_ref")
    exact_commander = isinstance(commander_ref, str) and bool(commander_ref)
    return {
        "schema": "formation-command-structure.v1",
        "personnel_basis": n,
        "personnel_conservation_rule": "all internal billets are included in formation personnel; this record adds zero bodies",
        "century_elements": (n + century - 1) // century if n else 0,
        "company_elements": (n + company - 1) // company if n else 0,
        "wing_elements": (n + wing - 1) // wing if n else 0,
        "deputy_billets": int(cfg.get("deputy_billets", 1)) if n >= company else 0,
        "staff_billets": blocks * staff_per,
        "signal_billets": blocks * signal_per,
        "logistics_billets": blocks * logistics_per,
        "named_commander_ref": commander_ref if exact_commander else None,
        "staffing_status": "named_commander_staffed" if exact_commander else ("aggregate_staffed" if n >= minimum else "small_unit_internal_leadership"),
        "subordinate_registry_kind": "aggregate_internal_echelons",
        "subordinate_registry_rule": "internal echelons guide command span and later detachment/materialization; they are not independent casualty owners until explicitly split into persistent formations",
    }


class WarfareDepthMixin:
    """Add combined-arms state operations and non-fictitious aggregate staffs."""

    def _warfare_depth_rules(self) -> Mapping[str, Any]:
        cached = getattr(self, "_warfare_depth_rules_cache", None)
        if isinstance(cached, Mapping):
            return cached
        value = self.read(_RULES_PATH)
        self._warfare_depth_rules_cache = value
        return value

    def _ensure_formation_command_structure(self, formation_ref: str) -> Mapping[str, Any]:
        path, formation0 = self._load_formation(formation_ref)
        formation = copy.deepcopy(formation0)
        desired = build_formation_command_structure(formation, self._warfare_depth_rules())
        existing = formation.get("command_structure")
        if existing != desired:
            formation["command_structure"] = desired
            self.put(path, formation)
        return desired

    @staticmethod
    def _objective_role_bonus(role: str, objective_text: str) -> int:
        normalized = "missile_infantry" if role in {"missile_crossbow", "archer"} else role
        return LivingWorldSwordPlanner._objective_role_bonus(normalized, objective_text)

    def _formation_score(
        self,
        formation_ref: str,
        formation: Mapping[str, Any],
        objective_text: str,
        memory: dict[str, Any],
        reserved: set[str],
    ) -> int:
        commander_ref = formation.get("commander_ref")
        if isinstance(commander_ref, str) and commander_ref:
            return super()._formation_score(formation_ref, formation, objective_text, memory, reserved)
        structure = formation.get("command_structure")
        if not isinstance(structure, Mapping) or structure.get("staffing_status") != "aggregate_staffed":
            return super()._formation_score(formation_ref, formation, objective_text, memory, reserved)
        if formation_ref in reserved:
            return -(10**9)
        # The generic scorer already evaluates readiness, morale, cohesion, role,
        # logistics and history.  Aggregate staffed formations receive a modest
        # command-depth credit rather than a fictional named-general skill score.
        base = LivingWorldSwordPlanner._formation_score(
            self, formation_ref, formation, objective_text, memory, reserved
        )
        staff = max(0, int(structure.get("staff_billets", 0)))
        signal = max(0, int(structure.get("signal_billets", 0)))
        return base + min(120, 30 + staff + signal)

    def _desired_operation_formation_count(self, severity: int) -> int:
        cfg = self._warfare_depth_rules().get("operation_depth", {})
        rows = cfg.get("formation_count_by_threat", []) if isinstance(cfg, Mapping) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            if severity >= int(row.get("minimum_severity", 101)):
                return max(1, int(row.get("formation_count", 2)))
        return 1

    def _operation_supply_snapshot(self, refs: list[str]) -> dict[str, Any]:
        snapshots: dict[str, Any] = {}
        for ref in refs:
            try:
                _path, formation = self._load_formation(ref)
            except ValueError:
                continue
            logistics = formation.get("logistics", {}) if isinstance(formation.get("logistics"), Mapping) else {}
            snapshots[ref] = {
                "personnel": max(0, int(formation.get("personnel", 0))),
                "location_ref": formation.get("location_ref"),
                "role": self._formation_role(formation),
                "food_kg": max(0, int(logistics.get("food_kg", 0))),
                "fodder_kg": max(0, int(logistics.get("fodder_kg", 0))),
                "war_arrows": max(0, int(logistics.get("war_arrows", 0))),
                "war_bolts": max(0, int(logistics.get("war_bolts", 0))),
            }
        return snapshots

    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_state(host, occurrences, at)
        state = self._state_key(str(host["owner_ref"]))
        force = self.read(f"state/forces/state-{state}.json")
        allocated = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
        for formation_ref in sorted(str(ref) for ref in allocated) if isinstance(allocated, Mapping) else []:
            try:
                self._ensure_formation_command_structure(formation_ref)
            except ValueError:
                continue

        state_doc = self.read(f"state/states/{state}.json")
        threats = state_doc.get("known_threats", {}) if isinstance(state_doc, Mapping) else {}
        threat_rows = [
            (str(ref), value, self._threat_severity(value))
            for ref, value in threats.items()
        ] if isinstance(threats, Mapping) else []
        max_severity = max((row[2] for row in threat_rows), default=0)
        desired = self._desired_operation_formation_count(max_severity)
        if desired <= 1:
            return

        op_index = copy.deepcopy(self.read("state/operations/index.json"))
        operations = op_index.get("operations", {}) if isinstance(op_index, MutableMapping) else {}
        if not isinstance(operations, MutableMapping):
            raise ValueError("operation index is invalid")
        memory = self.read_optional(OPERATIONAL_MEMORY_PATH)
        memory_view = memory if isinstance(memory, dict) else {"state_memory": {}, "formation_memory": {}}

        foreign_used: set[str] = set()
        own: list[tuple[str, str]] = []
        own_prefix = f"operation_auto_{state}_"
        for op_ref, path in sorted(operations.items()):
            if not isinstance(op_ref, str) or not isinstance(path, str):
                continue
            operation = self.read(path)
            if str(operation.get("status", "")) not in {"planned", "mobilizing", "active", "engaged", "occupied"}:
                continue
            refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}
            if bool(operation.get("autonomous")) and op_ref.startswith(own_prefix):
                own.append((op_ref, path))
            else:
                foreign_used.update(refs)

        used = set(foreign_used)
        for op_ref, path in own:
            operation = copy.deepcopy(self.read(path))
            if str(operation.get("status", "")) not in _ACTIVE_REVIEW_STATES:
                used.update(str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str))
                continue
            objective = str(operation.get("objective", "respond to known border threat"))
            selected = self._select_formations(
                state,
                objective,
                memory_view,
                reserved=used,
                count=desired,
            )
            if not selected:
                used.update(str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str))
                continue
            old = [str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)]
            if old != selected:
                operation["formation_refs"] = selected
                operation["combined_arms_review"] = {
                    "at": at,
                    "threat_severity": max_severity,
                    "requested_formation_count": desired,
                    "selected_roles": [self._formation_role(self._load_formation(ref)[1]) for ref in selected],
                    "rule": "persistent formations remain separate manpower/casualty owners; operation coordinates combined arms only",
                }
                supply = operation.setdefault("supply_plan", {})
                if isinstance(supply, MutableMapping):
                    supply["formation_logistics_at_review"] = self._operation_supply_snapshot(selected)
                operation["updated_at"] = at
                self.put(path, operation)
            used.update(selected)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        if host.get("kind") == "great_bow_guard_field_readiness":
            try:
                self._ensure_formation_command_structure("formation_tang_wei_great_bow_guard_first")
            except ValueError:
                pass

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = super()._dispatch(command, payload)
        if command.command_type == "formation_create":
            ref = result.get("formation_ref") if isinstance(result, Mapping) else None
            if isinstance(ref, str) and ref:
                self._ensure_formation_command_structure(ref)
        return result


__all__ = ["WarfareDepthMixin", "build_formation_command_structure"]
