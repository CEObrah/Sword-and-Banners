"""Integrity overlay for the final command-depth lifecycle.

This mixin owns no campaign state. It closes lifecycle and conservation edge cases
around ``WarfareDepthMixin``:

* secondary formation staff/support are released before a merge deletes owners;
* mercenary command/support duty is carved from existing company headcount;
* materialized officers embedded inside formation fighting strength are not counted
  a second time by top-level force conservation; and
* House Tang / Sword Manor command representation is inherited force-wide,
  while Qin uses the same standard only when Tang Wei lawfully holds command.
"""
from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.warfare_depth import WarfareDepthMixin


_SCOPED_OWNER_FORCES = frozenset({"force_house_tang", "force_sword_manor"})
_QIN_FORCE = "force_state_qin"
_WEI_REF = "char_tang_wei"
_MISSING = object()


def _formation_in_scoped_standard(formation: Mapping[str, Any]) -> str:
    owner_force = str(formation.get("owner_force_ref", ""))
    if owner_force in _SCOPED_OWNER_FORCES:
        return "house_or_sword_institution_wide"
    if owner_force == _QIN_FORCE and str(formation.get("command_authority", "")) == _WEI_REF:
        return "wei_assigned_qin"
    return ""


def _normalize_scoped_explicit_profile(
    formation: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Apply institutional representation invariants to an explicit profile.

    Explicit organizational geometry remains authoritative. This only fills the
    combined unit-command representation marker when the scoped policy already
    declares both formal billets full characters, avoiding an aggregate fallback
    from an omitted combined-representation marker.
    """
    if not _formation_in_scoped_standard(formation):
        return profile
    normalized = copy.deepcopy(dict(profile))
    unit = normalized.get("external_unit_command")
    if not isinstance(unit, MutableMapping):
        return normalized
    commander_rep = str(unit.get("commander_representation", ""))
    deputy_rep = str(unit.get("deputy_representation", ""))
    if commander_rep == "full_character" and deputy_rep == "full_character":
        unit.setdefault("representation", "full_character_unit_command")
    return normalized


def _synthesized_scoped_formation_profile(formation: Mapping[str, Any]) -> dict[str, Any]:
    """Return the institutional default command profile for one scoped formation.

    This is representation policy only. It does not materialize a body, grant a
    command, or change manpower. Existing exact formation/force owners remain the
    authority for commander assignment and personnel conservation.
    """
    owner_force = str(formation.get("owner_force_ref", ""))
    scope = _formation_in_scoped_standard(formation)
    if not scope:
        return {}

    personnel = max(0, int(formation.get("personnel", 0) or 0))
    internal: list[dict[str, Any]] = []
    for scale, representation in ((1000, "person_lite"), (500, "person_lite"), (100, "aggregate")):
        # The persistent formation itself owns the top-level unit command. Do not
        # duplicate that commander as an internal commander at the same scale.
        if personnel <= scale:
            continue
        count = (personnel + scale - 1) // scale
        internal.append(
            {
                "scale": scale,
                "count": count,
                "representation": representation,
                "deputy_policy": "normally_none",
                "loadout_ref": "loadout_house_guard",
            }
        )

    return {
        "label": "Institution-scoped formation command standard",
        "fighting_establishment": personnel,
        "scope": scope,
        "external_unit_command": {
            "commander_billets": 1 if personnel else 0,
            "deputy_billets": 1 if personnel else 0,
            "commander_representation": "full_character",
            "deputy_representation": "full_character",
            "source_force_ref": owner_force,
            "source_role": "command_personnel",
            "representation": "full_character_unit_command",
            "outside_fighting_establishment": True,
            "loadout_ref": "loadout_house_champion",
        },
        "internal_hierarchy": internal,
        "hierarchy_rule": (
            "House Tang and Sword Manor inherit full-character persistent unit commander/deputy "
            "plus person-lite 1,000/500 internal command institution-wide. Qin inherits the same "
            "standard only while Tang Wei lawfully holds command authority. 100-man and below "
            "remain aggregate unless separately salient."
        ),
    }


def resolve_scoped_formation_profile(
    formation: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Resolve explicit geometry first, normalized by the scoped institution rule."""
    profiles = rules.get("formation_profiles", {}) if isinstance(rules, Mapping) else {}
    ref = str(formation.get("formation_ref", ""))
    explicit = profiles.get(ref) if isinstance(profiles, Mapping) else None
    if isinstance(explicit, Mapping):
        return _normalize_scoped_explicit_profile(formation, explicit)
    return _synthesized_scoped_formation_profile(formation)


class _ScopedFormationProfiles(Mapping[str, Any]):
    """Lazy profile adapter so all production WarfareDepth calls share one scope rule."""

    def __init__(self, planner: Any, explicit: Mapping[str, Any]) -> None:
        self._planner = planner
        self._explicit = explicit

    def __iter__(self) -> Iterator[str]:
        return iter(self._explicit)

    def __len__(self) -> int:
        return len(self._explicit)

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def get(self, key: object, default: Any = None) -> Any:
        if not isinstance(key, str) or not key:
            return default
        explicit = self._explicit.get(key)
        try:
            _path, formation = self._planner._load_formation(key)
        except (KeyError, ValueError, FileNotFoundError):
            return explicit if isinstance(explicit, Mapping) else default
        if not isinstance(formation, Mapping):
            return explicit if isinstance(explicit, Mapping) else default
        if isinstance(explicit, Mapping):
            return _normalize_scoped_explicit_profile(formation, explicit)
        scoped = _synthesized_scoped_formation_profile(formation)
        return scoped if scoped else default


class WarfareDepthIntegrityMixin:
    """Production integrity hooks layered immediately above WarfareDepthMixin."""

    def _warfare_depth_rules(self) -> Mapping[str, Any]:
        """Overlay lazy institutional formation profiles onto static warfare rules."""
        cached = getattr(self, "_warfare_depth_integrity_rules_cache", None)
        if isinstance(cached, Mapping):
            return cached
        base = super()._warfare_depth_rules()
        rules = copy.deepcopy(dict(base))
        explicit = base.get("formation_profiles", {}) if isinstance(base, Mapping) else {}
        if not isinstance(explicit, Mapping):
            explicit = {}
        rules["formation_profiles"] = _ScopedFormationProfiles(self, explicit)
        self._warfare_depth_integrity_rules_cache = rules
        return rules

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

        class _ConservedForceView:
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

        super(WarfareDepthMixin, self)._validate_invariants(_ConservedForceView(overlay), paths)

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


__all__ = ["WarfareDepthIntegrityMixin", "resolve_scoped_formation_profile"]
