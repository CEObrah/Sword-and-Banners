"""Persistent combined-arms and formation command-depth integration.

A formation remains one persistent fighting-establishment owner. Internal command
nodes are assignments over soldiers already counted in that fighting strength.
Unit command and explicitly attached support may sit outside fighting strength,
but every such body must still come from a conserved force role.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.living_world import LivingWorldSwordPlanner, OPERATIONAL_MEMORY_PATH

_RULES_PATH = "game/data/mechanics/warfare-organization.json"
_ACTIVE_REVIEW_STATES = frozenset({"planned", "mobilizing", "active"})


def _profile_for(formation: Mapping[str, Any], rules: Mapping[str, Any]) -> Mapping[str, Any]:
    profiles = rules.get("formation_profiles", {}) if isinstance(rules, Mapping) else {}
    ref = str(formation.get("formation_ref", ""))
    profile = profiles.get(ref) if isinstance(profiles, Mapping) else None
    return profile if isinstance(profile, Mapping) else {}


def _support_targets(personnel: int, support: Mapping[str, Any]) -> dict[str, int]:
    per = support.get("per_500", {}) if isinstance(support, Mapping) else {}
    blocks = (max(0, int(personnel)) + 499) // 500 if personnel else 0
    return {
        str(role): blocks * max(0, int(count))
        for role, count in per.items()
        if int(count) > 0
    } if isinstance(per, Mapping) else {}


def build_formation_command_structure(formation: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    cfg = rules.get("formation_command_structure", {}) if isinstance(rules, Mapping) else {}
    n = max(0, int(formation.get("personnel", 0)))
    profile = _profile_for(formation, rules)
    internal = profile.get("internal_hierarchy", []) if isinstance(profile, Mapping) else []
    if not isinstance(internal, list) or not internal:
        levels = cfg.get("generic_internal_levels", [2000, 1000, 500, 100]) if isinstance(cfg, Mapping) else [2000, 1000, 500, 100]
        internal = [
            {"scale": int(scale), "count": (n + int(scale) - 1) // int(scale) if n else 0, "representation": "aggregate_until_relevant"}
            for scale in levels if int(scale) > 0 and n >= int(scale)
        ]
    hierarchy = []
    internal_commanders = 0
    for row in internal:
        if not isinstance(row, Mapping):
            continue
        scale = max(1, int(row.get("scale", 1)))
        count = max(0, int(row.get("count", 0)))
        hierarchy.append({
            "scale": scale,
            "count": count,
            "representation": str(row.get("representation", "aggregate_until_relevant")),
            "deputy_policy": str(row.get("deputy_policy", "normally_none")),
            "inside_fighting_establishment": True,
        })
        internal_commanders += count

    unit_command = profile.get("external_unit_command", {}) if isinstance(profile, Mapping) else {}
    if not isinstance(unit_command, Mapping):
        unit_command = {}
    generic_unit = cfg.get("unit_command", {}) if isinstance(cfg, Mapping) else {}
    if not isinstance(generic_unit, Mapping):
        generic_unit = {}
    commander_billets = max(0, int(unit_command.get("commander_billets", generic_unit.get("commander_billets_per_formation", 1 if n else 0))))
    deputy_billets = max(0, int(unit_command.get("deputy_billets", generic_unit.get("deputy_billets_per_formation", 1 if n else 0))))
    external_command_bodies = commander_billets + deputy_billets

    support = profile.get("external_support", {}) if isinstance(profile, Mapping) else {}
    if not isinstance(support, Mapping) or not support:
        per_500 = cfg.get("external_support_per_500", {}) if isinstance(cfg, Mapping) else {}
        support = {"per_500": per_500, "outside_fighting_establishment": True}
    support_targets = _support_targets(n, support)
    support_total = sum(support_targets.values())

    commander_ref = formation.get("commander_ref")
    deputy_ref = formation.get("deputy_ref")
    minimum = max(1, int(cfg.get("minimum_aggregate_staffed_personnel", 500))) if isinstance(cfg, Mapping) else 500
    exact_commander = isinstance(commander_ref, str) and bool(commander_ref)
    exact_deputy = isinstance(deputy_ref, str) and bool(deputy_ref)
    return {
        "schema": "formation-command-structure.v2",
        "fighting_establishment": n,
        "persistent_unit_slots": 1 if n else 0,
        "attached_personnel_target": n + external_command_bodies + support_total,
        "personnel_conservation_rule": "internal commanders occupy conserved fighting-establishment bodies; unit command and support are separately conserved attached bodies and never create phantom manpower",
        "unit_command": {
            "commander_billets": commander_billets,
            "deputy_billets": deputy_billets,
            "outside_fighting_establishment": True,
            "source_force_ref": unit_command.get("source_force_ref", formation.get("owner_force_ref")),
            "source_role": unit_command.get("source_role", generic_unit.get("source_role", "command_personnel")),
            "representation": unit_command.get("representation", "full_character"),
            "named_commander_ref": commander_ref if exact_commander else None,
            "named_deputy_ref": deputy_ref if exact_deputy else None,
        },
        "internal_hierarchy": hierarchy,
        "internal_commander_assignments": internal_commanders,
        "internal_commanders_inside_fighting_establishment": internal_commanders,
        "external_support": {
            "outside_fighting_establishment": bool(support.get("outside_fighting_establishment", True)),
            "source_force_ref": support.get("source_force_ref", formation.get("owner_force_ref")),
            "targets_by_role": support_targets,
            "target_total": support_total,
            "function_map": copy.deepcopy(support.get("function_map", cfg.get("external_support_function_map", {}))) if isinstance(cfg, Mapping) else copy.deepcopy(support.get("function_map", {})),
        },
        "staffing_status": "named_unit_command" if exact_commander else ("aggregate_staffed" if n >= minimum else "small_unit_internal_leadership"),
        "subordinate_registry_kind": "internal_command_assignments",
        "subordinate_registry_rule": "internal command nodes guide scale-bounded command, succession and temporary battlefield subdivision; they are not independent formations or casualty owners unless lawfully detached",
    }


class WarfareDepthMixin:
    """Add combined-arms state operations and conserved scale-aware command depth."""

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

    def _formation_score(self, formation_ref: str, formation: Mapping[str, Any], objective_text: str, memory: dict[str, Any], reserved: set[str]) -> int:
        commander_ref = formation.get("commander_ref")
        if isinstance(commander_ref, str) and commander_ref:
            return super()._formation_score(formation_ref, formation, objective_text, memory, reserved)
        structure = formation.get("command_structure")
        if not isinstance(structure, Mapping) or structure.get("staffing_status") != "aggregate_staffed":
            return super()._formation_score(formation_ref, formation, objective_text, memory, reserved)
        if formation_ref in reserved:
            return -(10**9)
        base = LivingWorldSwordPlanner._formation_score(self, formation_ref, formation, objective_text, memory, reserved)
        hierarchy = structure.get("internal_hierarchy", [])
        internal = sum(max(0, int(row.get("count", 0))) for row in hierarchy if isinstance(row, Mapping)) if isinstance(hierarchy, list) else 0
        support = int(structure.get("external_support", {}).get("target_total", 0)) if isinstance(structure.get("external_support"), Mapping) else 0
        return base + min(120, 25 + internal // 2 + support // 8)

    def _desired_operation_formation_count(self, severity: int) -> int:
        cfg = self._warfare_depth_rules().get("operation_depth", {})
        rows = cfg.get("formation_count_by_threat", []) if isinstance(cfg, Mapping) else []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, Mapping) and severity >= int(row.get("minimum_severity", 101)):
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
        threat_rows = [(str(ref), value, self._threat_severity(value)) for ref, value in threats.items()] if isinstance(threats, Mapping) else []
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
            if bool(operation.get("autonomous")) and op_ref.startswith(own_prefix): own.append((op_ref, path))
            else: foreign_used.update(refs)
        used = set(foreign_used)
        for op_ref, path in own:
            operation = copy.deepcopy(self.read(path))
            if str(operation.get("status", "")) not in _ACTIVE_REVIEW_STATES:
                used.update(str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)); continue
            objective = str(operation.get("objective", "respond to known border threat"))
            selected = self._select_formations(state, objective, memory_view, reserved=used, count=desired)
            if not selected:
                used.update(str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)); continue
            old = [str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)]
            if old != selected:
                operation["formation_refs"] = selected
                operation["combined_arms_review"] = {"at": at, "threat_severity": max_severity, "requested_formation_count": desired, "selected_roles": [self._formation_role(self._load_formation(ref)[1]) for ref in selected], "rule": "persistent formations remain separate manpower/casualty owners; operation coordinates combined arms only"}
                supply = operation.setdefault("supply_plan", {})
                if isinstance(supply, MutableMapping): supply["formation_logistics_at_review"] = self._operation_supply_snapshot(selected)
                operation["updated_at"] = at; self.put(path, operation)
            used.update(selected)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        if host.get("kind") == "great_bow_guard_field_readiness":
            try: self._ensure_formation_command_structure("formation_tang_wei_great_bow_guard_first")
            except ValueError: pass

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = super()._dispatch(command, payload)
        if command.command_type == "formation_create":
            ref = result.get("formation_ref") if isinstance(result, Mapping) else None
            if isinstance(ref, str) and ref: self._ensure_formation_command_structure(ref)
        return result


__all__ = ["WarfareDepthMixin", "build_formation_command_structure"]
