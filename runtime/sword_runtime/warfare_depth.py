"""Persistent combined-arms and conserved command-depth integration.

Normal persistent formations store fighting establishment in ``personnel``.
Internal command nodes are assignments over bodies already counted in that
fighting strength. State, House, private and personal formations therefore share
one command model without creating another manpower authority.

Mercenary owners are different: their saved ``headcount`` is total company
personnel and their troop pools already include support. Their command/support
projection is carved from that conserved total and never adds bodies by default.

Officer representation is sparse. Generic billets remain aggregate until exact
saved relevance, exceptional performance or provenance-backed high potential
requires an individual person owner.
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


def _generic_hierarchy(
    personnel: int,
    levels: Any,
    *,
    representation: str,
) -> list[dict[str, Any]]:
    n = max(0, int(personnel))
    rows: list[dict[str, Any]] = []
    if not isinstance(levels, list):
        return rows
    for raw_scale in levels:
        scale = int(raw_scale)
        if scale <= 0 or n < scale:
            continue
        full = n // scale
        tail = n % scale
        count = full + (1 if tail else 0)
        rows.append({
            "scale": scale,
            "count": count,
            "full_elements": full,
            "partial_tail_personnel": tail,
            "representation": representation,
            "deputy_policy": "optional_useful" if scale >= 2000 else ("optional" if scale >= 1000 else "normally_none"),
            "inside_fighting_establishment": True,
        })
    return rows


def build_formation_command_structure(formation: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    cfg = rules.get("formation_command_structure", {}) if isinstance(rules, Mapping) else {}
    policy = rules.get("officer_representation_policy", {}) if isinstance(rules, Mapping) else {}
    n = max(0, int(formation.get("personnel", 0)))
    profile = _profile_for(formation, rules)
    internal = profile.get("internal_hierarchy", []) if isinstance(profile, Mapping) else []
    if not isinstance(internal, list) or not internal:
        levels = cfg.get("generic_internal_levels", [2000, 1000, 500, 100]) if isinstance(cfg, Mapping) else [2000, 1000, 500, 100]
        representation = str(cfg.get("generic_representation", policy.get("default_representation", "aggregate"))) if isinstance(cfg, Mapping) else "aggregate"
        hierarchy = _generic_hierarchy(n, levels, representation=representation)
    else:
        hierarchy = []
        for row in internal:
            if not isinstance(row, Mapping):
                continue
            scale = max(1, int(row.get("scale", 1)))
            count = max(0, int(row.get("count", 0)))
            full = min(count, n // scale) if n else 0
            tail = n % scale if count > full else 0
            hierarchy.append({
                "scale": scale,
                "count": count,
                "full_elements": full,
                "partial_tail_personnel": tail,
                "representation": str(row.get("representation", policy.get("default_representation", "aggregate"))),
                "deputy_policy": str(row.get("deputy_policy", "normally_none")),
                "inside_fighting_establishment": True,
            })
    internal_commanders = sum(max(0, int(row.get("count", 0))) for row in hierarchy)

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
    allocated_support_raw = formation.get("attached_support_by_role", {})
    allocated_support = {
        str(role): max(0, int(count))
        for role, count in allocated_support_raw.items()
    } if isinstance(allocated_support_raw, Mapping) else {}
    allocated_support_total = sum(allocated_support.values())

    commander_ref = formation.get("commander_ref")
    deputy_ref = formation.get("deputy_ref")
    minimum = max(1, int(cfg.get("minimum_aggregate_staffed_personnel", 500))) if isinstance(cfg, Mapping) else 500
    exact_commander = isinstance(commander_ref, str) and bool(commander_ref)
    exact_deputy = isinstance(deputy_ref, str) and bool(deputy_ref)
    default_representation = str(generic_unit.get("default_representation", policy.get("default_representation", "aggregate")))
    return {
        "projection_kind": "formation_command_structure_v3",
        "accounting_mode": "fighting_establishment_plus_external_attachments",
        "fighting_establishment": n,
        "persistent_unit_slots": 1 if n else 0,
        "attached_personnel_target": n + external_command_bodies + support_total,
        "personnel_conservation_rule": "internal commanders occupy conserved fighting-establishment bodies; unit command and support require separately conserved attached bodies and never create phantom manpower",
        "representation_policy": "aggregate_by_default_materialize_only_on_saved_relevance_or_exceptional_evidence",
        "unit_command": {
            "commander_billets": commander_billets,
            "deputy_billets": deputy_billets,
            "outside_fighting_establishment": True,
            "source_force_ref": unit_command.get("source_force_ref", formation.get("owner_force_ref")),
            "source_role": unit_command.get("source_role", generic_unit.get("source_role", "command_personnel")),
            "representation": unit_command.get("representation", default_representation),
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
            "allocated_by_role": allocated_support,
            "allocated_total": allocated_support_total,
            "shortfall_by_role": {
                role: max(0, target - int(allocated_support.get(role, 0)))
                for role, target in support_targets.items()
            },
            "function_map": copy.deepcopy(support.get("function_map", cfg.get("external_support_function_map", {}))) if isinstance(cfg, Mapping) else copy.deepcopy(support.get("function_map", {})),
        },
        "staffing_status": "named_unit_command" if exact_commander else ("aggregate_staffed" if n >= minimum else "small_unit_internal_leadership"),
        "subordinate_registry_kind": "internal_command_assignments",
        "subordinate_registry_rule": "internal command nodes guide scale-bounded command, succession and temporary battlefield subdivision; they are not independent formations or casualty owners unless lawfully detached",
    }


def build_mercenary_command_structure(company: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    """Project command depth from one conserved mercenary-company owner.

    Mercenary ``headcount`` is total company manpower. Support and command remain
    inside that total unless an exact external attachment is separately saved.
    This function is pure and never materializes an officer or changes headcount.
    """
    accounting = rules.get("accounting_modes", {}).get("mercenary_company", {}) if isinstance(rules, Mapping) else {}
    cfg = rules.get("mercenary_command_structure", {}) if isinstance(rules, Mapping) else {}
    policy = rules.get("officer_representation_policy", {}) if isinstance(rules, Mapping) else {}
    total = max(0, int(company.get("headcount", 0)))
    tokens = {
        str(token).strip().lower()
        for token in accounting.get("non_fighting_role_tokens", [])
        if str(token).strip()
    } if isinstance(accounting, Mapping) else set()
    troop_pools = company.get("troop_pools", [])
    pool_total = 0
    non_fighting = 0
    non_fighting_by_role: dict[str, int] = {}
    if isinstance(troop_pools, list):
        for row in troop_pools:
            if not isinstance(row, Mapping):
                continue
            count = max(0, int(row.get("count", 0)))
            pool_total += count
            role = str(row.get("role", row.get("troop_type", "unclassified")))
            descriptors = " ".join(str(row.get(key, "")) for key in ("role", "troop_type", "specialty")).lower()
            if any(token in descriptors for token in tokens):
                non_fighting += count
                non_fighting_by_role[role] = int(non_fighting_by_role.get(role, 0)) + count
    non_fighting = min(total, non_fighting)
    fighting = max(0, total - non_fighting)

    levels = cfg.get("generic_internal_levels", [2000, 1000, 500, 100]) if isinstance(cfg, Mapping) else [2000, 1000, 500, 100]
    representation = str(cfg.get("generic_representation", policy.get("default_representation", "aggregate"))) if isinstance(cfg, Mapping) else "aggregate"
    hierarchy = _generic_hierarchy(fighting, levels, representation=representation)
    internal_commanders = sum(int(row.get("count", 0)) for row in hierarchy)

    unit_cfg = cfg.get("unit_command", {}) if isinstance(cfg, Mapping) else {}
    commander_billets = max(0, int(unit_cfg.get("commander_billets_per_company", 1 if total else 0))) if isinstance(unit_cfg, Mapping) else (1 if total else 0)
    deputy_billets = max(0, int(unit_cfg.get("deputy_billets_per_company", 1 if total else 0))) if isinstance(unit_cfg, Mapping) else (1 if total else 0)
    command_target = commander_billets + deputy_billets
    support_per = cfg.get("support_target_per_500_fighters", {}) if isinstance(cfg, Mapping) else {}
    support_targets = _support_targets(fighting, {"per_500": support_per})
    support_target = sum(support_targets.values())
    non_fighting_target = command_target + support_target
    shortfall = max(0, non_fighting_target - non_fighting)
    target_fighting_if_rebalanced = max(0, total - max(non_fighting, non_fighting_target))

    return {
        "projection_kind": "mercenary_command_structure_v1",
        "accounting_mode": "total_company_headcount_includes_command_and_support",
        "company_headcount": total,
        "troop_pool_headcount": pool_total,
        "pool_headcount_delta": total - pool_total,
        "fighting_establishment": fighting,
        "fighting_establishment_if_target_staffed": target_fighting_if_rebalanced,
        "existing_non_fighting_personnel": non_fighting,
        "existing_non_fighting_by_role": non_fighting_by_role,
        "persistent_unit_slots": 1 if total else 0,
        "attached_personnel_target": total,
        "attached_personnel_delta": 0,
        "personnel_conservation_rule": "mercenary command and support are carved from existing company headcount by default; projection adds zero bodies",
        "representation_policy": "aggregate_by_default_materialize_only_on_saved_relevance_or_exceptional_evidence",
        "unit_command": {
            "commander_billets": commander_billets,
            "deputy_billets": deputy_billets,
            "inside_total_headcount": True,
            "representation": unit_cfg.get("default_representation", representation) if isinstance(unit_cfg, Mapping) else representation,
        },
        "internal_hierarchy": hierarchy,
        "internal_commander_assignments": internal_commanders,
        "internal_commanders_inside_fighting_establishment": internal_commanders,
        "support": {
            "inside_total_headcount": True,
            "targets_by_role": support_targets,
            "target_total": support_target,
            "combined_command_and_support_target": non_fighting_target,
            "existing_non_fighting_personnel": non_fighting,
            "staffing_shortfall": shortfall,
        },
        "subordinate_registry_kind": "aggregate_internal_command_assignments",
    }


class WarfareDepthMixin:
    """Add combined-arms operations and universal conserved command depth."""

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
        if formation.get("command_structure") != desired:
            formation["command_structure"] = desired
            self.put(path, formation)
        return desired

    def _ensure_force_command_structures(self, force_ref: str) -> None:
        try:
            force = self.read(self.owner_path(force_ref))
        except (KeyError, ValueError, FileNotFoundError):
            return
        allocated = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
        if not isinstance(allocated, Mapping):
            return
        for formation_ref in sorted(str(ref) for ref in allocated):
            try:
                self._ensure_formation_command_structure(formation_ref)
            except (KeyError, ValueError, FileNotFoundError):
                continue

    def _ensure_mercenary_command_structure(self, mercenary_ref: str) -> Mapping[str, Any]:
        path = self.owner_path(mercenary_ref)
        company0 = self.read(path)
        if not isinstance(company0, Mapping) or str(company0.get("schema", "")) != "mercenary":
            raise ValueError("mercenary command projection requires an exact mercenary owner")
        company = copy.deepcopy(company0)
        desired = build_mercenary_command_structure(company, self._warfare_depth_rules())
        if company.get("command_structure") != desired:
            company["command_structure"] = desired
            self.put(path, company)
        return desired

    @staticmethod
    def _objective_role_bonus(role: str, objective_text: str) -> int:
        normalized = "missile_infantry" if role in {"missile_crossbow", "archer"} else role
        return LivingWorldSwordPlanner._objective_role_bonus(normalized, objective_text)

    def _formation_score(self, formation_ref: str, formation: Mapping[str, Any], objective_text: str, memory: dict[str, Any], reserved: set[str]) -> int:
        commander_ref = formation.get("commander_ref")
        if isinstance(commander_ref, str) and commander_ref:
            return super()._formation_score(formation_ref, formation, objective_text, memory, reserved)
        structure = build_formation_command_structure(formation, self._warfare_depth_rules())
        if structure.get("staffing_status") != "aggregate_staffed":
            return super()._formation_score(formation_ref, formation, objective_text, memory, reserved)
        if formation_ref in reserved:
            return -(10**9)
        base = LivingWorldSwordPlanner._formation_score(self, formation_ref, formation, objective_text, memory, reserved)
        hierarchy = structure.get("internal_hierarchy", [])
        internal = sum(max(0, int(row.get("count", 0))) for row in hierarchy if isinstance(row, Mapping)) if isinstance(hierarchy, list) else 0
        external_support = structure.get("external_support", {})
        allocated_support = int(external_support.get("allocated_total", 0)) if isinstance(external_support, Mapping) else 0
        return base + min(120, 25 + internal // 2 + allocated_support // 8)

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
        self._ensure_force_command_structures(f"force_state_{state}")

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
            selected = self._select_formations(state, objective, memory_view, reserved=used, count=desired)
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

    def _autonomy_house(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_house(host, occurrences, at)
        try:
            house = self.read(self.owner_path(str(host["owner_ref"])))
        except (KeyError, ValueError, FileNotFoundError):
            return
        force_ref = house.get("military_force_ref") if isinstance(house, Mapping) else None
        if isinstance(force_ref, str) and force_ref:
            self._ensure_force_command_structures(force_ref)

    def _autonomy_mercenary(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_mercenary(host, occurrences, at)
        try:
            self._ensure_mercenary_command_structure(str(host["owner_ref"]))
        except (KeyError, ValueError, FileNotFoundError):
            return

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)
        if host.get("kind") == "great_bow_guard_field_readiness":
            try:
                self._ensure_formation_command_structure("formation_tang_wei_great_bow_guard_first")
            except ValueError:
                pass

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        result = super()._dispatch(command, payload)
        refs: set[str] = set()
        if command.command_type == "formation_create":
            ref = result.get("formation_ref") if isinstance(result, Mapping) else None
            if isinstance(ref, str) and ref:
                refs.add(ref)
        elif command.command_type == "formation_reconstitute":
            ref = payload.get("formation_ref")
            if isinstance(ref, str) and ref:
                refs.add(ref)
        elif command.command_type == "formation_split":
            for key in ("formation_ref", "new_formation_ref"):
                ref = payload.get(key)
                if isinstance(ref, str) and ref:
                    refs.add(ref)
        elif command.command_type == "formation_merge":
            if isinstance(result, Mapping):
                ref = result.get("formation_ref")
                if isinstance(ref, str) and ref:
                    refs.add(ref)
            for ref in payload.get("formation_refs", []) if isinstance(payload.get("formation_refs"), list) else []:
                if isinstance(ref, str) and ref:
                    refs.add(ref)
        elif command.command_type == "battle_resolve":
            for key in ("attacker_formation_refs", "defender_formation_refs"):
                for ref in payload.get(key, []) if isinstance(payload.get(key), list) else []:
                    if isinstance(ref, str) and ref:
                        refs.add(ref)
        for ref in sorted(refs):
            try:
                self._ensure_formation_command_structure(ref)
            except (KeyError, ValueError, FileNotFoundError):
                continue
        return result


__all__ = ["WarfareDepthMixin", "build_formation_command_structure", "build_mercenary_command_structure"]
