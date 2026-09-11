"""Conserved post-battle formation replacement from exact force reserves.

Casualties reduce formation strength and may leave a veteran officer cadre.  This
mixin never regenerates bodies, ranks, mounts, or equipment.  Periodic state and
House reviews may move already-existing, physically local force reserves into an
understrength formation up to its saved establishment.  New recruits must first
enter the force through that force's lawful recruitment/training system.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import append_formation_slices, take_reserve_slices, validate_cohort_ledger
from sword_runtime.mount_custody import allocate_regional_horses_to_formation, issue_force_role_horses_to_formation
from sword_runtime.officer_cadre import reorganize_officer_cadre
from sword_runtime.officer_personnel import sync_materialized_officer_billets
from sword_runtime.support_tasks import FORBIDDEN_PERMANENT_SUPPORT_ROLES
from sword_runtime.unit_establishment import (
    authorized_strength_for,
    establishment_composition,
    formation_class_for,
    normalize_formation_establishment,
    represented_establishment_composition,
)

_HOUSE_FORCE_INDEX = "state/index/house-force-index.json"


class FormationReplacementMixin:
    def _house_force_paths(self, house_ref: str) -> list[str]:
        """Return exact forces still administratively owned by one House.

        ``house-force-index`` is authority:false discovery state.  Revalidate
        both the force's authoritative owner route and its saved
        ``administrative_owner`` before a House review is allowed to settle
        replacements through that force.
        """
        index = self.read_optional(_HOUSE_FORCE_INDEX)
        rows = index.get("house_force_paths", {}).get(str(house_ref), []) if isinstance(index, Mapping) else []
        candidate_paths = {str(value) for value in rows if isinstance(value, str) and value}
        # Missing routing entries may not erase an exact House-force relation.
        # House owners carry the bounded authoritative reverse pointers.
        try:
            house_path = self.owner_path(str(house_ref))
            house = self.read(house_path)
        except (FileNotFoundError, KeyError, ValueError):
            house = None
        force_refs: set[str] = set()
        if isinstance(house, Mapping):
            single = house.get("military_force_ref")
            if isinstance(single, str) and single:
                force_refs.add(single)
            many = house.get("military_force_refs")
            if isinstance(many, list):
                force_refs.update(str(ref) for ref in many if isinstance(ref, str) and ref)
        for force_ref in force_refs:
            try:
                candidate_paths.add(str(self.owner_path(force_ref)))
            except (FileNotFoundError, KeyError, ValueError):
                continue
        out: list[str] = []
        for value in sorted(candidate_paths):
            if not isinstance(value, str) or not value:
                continue
            force = self.read_optional(value)
            if not isinstance(force, Mapping) or str(force.get("administrative_owner", "")) != str(house_ref):
                continue
            force_ref = force.get("owner_id")
            if not isinstance(force_ref, str) or not force_ref:
                continue
            try:
                exact_path = str(self.owner_path(force_ref))
            except (FileNotFoundError, KeyError, ValueError):
                continue
            if exact_path == value:
                out.append(value)
        return sorted(set(out))

    def _formation_establishment(self, formation: MutableMapping[str, Any]) -> dict[str, int]:
        raw = formation.get("establishment_composition")
        if isinstance(raw, Mapping) and raw:
            return {str(k): max(0, int(v)) for k, v in raw.items() if int(v) >= 0}
        composition = represented_establishment_composition(formation)
        current = max(0, int(formation.get("personnel", 0) or 0))
        klass = formation_class_for(formation, personnel=current, explicit=formation.get("formation_class"))
        authorized = authorized_strength_for(formation, personnel=current, formation_class=klass)
        if sum(max(0, int(v)) for v in composition.values()) == authorized:
            return {str(k): max(0, int(v)) for k, v in composition.items()}
        establishment = establishment_composition(composition, authorized)
        formation["establishment_composition"] = copy.deepcopy(establishment)
        return establishment

    def _standing_army_mobilization_rules(self) -> Mapping[str, Any]:
        rules = self.read("game/data/mechanics/military-career.json")
        row = rules.get("standing_army_mobilization", {}) if isinstance(rules, Mapping) else {}
        return row if isinstance(row, Mapping) else {}

    def _commander_rank_grade(self, commander_ref: str) -> str:
        if not commander_ref:
            return "unranked"
        try:
            person = self.read(self.owner_path(commander_ref))
        except (FileNotFoundError, KeyError, ValueError):
            return "unranked"
        rank = person.get("military_rank", {}) if isinstance(person, Mapping) else {}
        return str(rank.get("grade", "unranked")) if isinstance(rank, Mapping) else "unranked"

    def _sync_field_army_commander_span(self, group_ref: str) -> None:
        """Keep a commander's service sheet aligned with the exact command group.

        This changes billet span only. Durable military rank is never promoted or
        demoted by reinforcement.
        """
        path = f"state/cmd/command-groups/{group_ref}.json"
        group = self.read_optional(path)
        if not isinstance(group, Mapping):
            return
        commander_ref = str(group.get("commander_ref", ""))
        if not commander_ref:
            return
        try:
            person_path = self.owner_path(commander_ref)
            person0 = self.read(person_path)
        except (FileNotFoundError, KeyError, ValueError):
            return
        if not isinstance(person0, Mapping):
            return
        person = copy.deepcopy(dict(person0))
        org = group.get("organizational_state", {}) if isinstance(group.get("organizational_state"), Mapping) else {}
        span = max(0, int(org.get("current_recursive_strength", 0) or 0))
        assignment = person.setdefault("command_assignment", {})
        if isinstance(assignment, MutableMapping) and str(assignment.get("command_group_ref", "")) == group_ref:
            assignment["current_command_span"] = span
        military = person.setdefault("military_command", {})
        if isinstance(military, MutableMapping) and str(military.get("formation_scope", "")) == group_ref:
            military["level"] = f"{span}_commander"
            parent_ref = group.get("parent_command_group_ref")
            if isinstance(parent_ref, str) and parent_ref:
                parent = self.read_optional(f"state/cmd/command-groups/{parent_ref}.json")
                higher = str(parent.get("commander_ref", "")) if isinstance(parent, Mapping) else ""
                if higher:
                    military["higher_commander_ref"] = higher
                else:
                    military.pop("higher_commander_ref", None)
            else:
                military.pop("higher_commander_ref", None)
        career = person.setdefault("career_state", {})
        if isinstance(career, MutableMapping) and str(assignment.get("command_group_ref", "")) == group_ref:
            career["current_command_span"] = span
        self.put(person_path, person)

    def _adopt_current_command_group_establishment(self, group_ref: str, *, at: str) -> None:
        """Make a lawful permanent reinforcement the new standing establishment."""
        path = f"state/cmd/command-groups/{group_ref}.json"
        group0 = self.read_optional(path)
        if not isinstance(group0, Mapping):
            return
        # First refresh current recursive truth from exact descendants.
        self._refresh_command_group_organizational_state(group_ref, at)
        group0 = self.read(path)
        group = copy.deepcopy(dict(group0))
        summary = self._command_group_organizational_summary(group_ref)
        org = group.setdefault("organizational_state", {})
        if not isinstance(org, MutableMapping):
            org = {}; group["organizational_state"] = org
        org["authorized_strength"] = max(0, int(summary.get("recursive_strength", 0) or 0))
        org["authorized_direct_unit_slots"] = max(1, int(summary.get("direct_unit_count", 0) or 0))
        org["baseline_unit_strengths"] = {
            str(row["ref"]): max(0, int(row.get("current_strength", 0) or 0))
            for row in summary.get("units", []) if isinstance(row, Mapping) and row.get("ref")
        }
        org["reorganization_need"] = "none"
        group["updated_at"] = at
        self.put(path, group)
        self._sync_field_army_commander_span(group_ref)

    def _standing_army_reinforcement_mix(
        self,
        *,
        force: Mapping[str, Any],
        formation: Mapping[str, Any],
        increment: int,
    ) -> dict[str, int]:
        """Return the lawful combined-arms mix for new standing-army personnel.

        A specialist seed formation remains intact as the army core, but permanent
        wartime growth does not clone that seed role indefinitely. The default mix
        is derived from the sovereign's *actual local active reserve* across roles
        the institution can physically issue. This keeps the policy generic,
        state-specific through conserved material state, and free of hard-coded
        named-general outcomes.
        """
        amount = max(0, int(increment))
        if amount <= 0:
            return {}
        location = str(formation.get("location_ref", ""))
        local = force.get("available_by_location", {}).get(location, {})
        if not isinstance(local, Mapping):
            return {}
        state_ref = str(formation.get("administrative_owner", ""))
        try:
            issue = self.read("game/data/mil/institutional-loadouts.json")
        except (FileNotFoundError, KeyError, ValueError):
            issue = {}
        institutions = issue.get("institutions", {}) if isinstance(issue, Mapping) else {}
        issued_roles = institutions.get(state_ref, {}) if isinstance(institutions, Mapping) else {}
        allowed_roles = {str(role) for role in issued_roles} if isinstance(issued_roles, Mapping) else set()
        if not allowed_roles:
            allowed_roles = {str(role) for role in local}
        equipment_local = force.get("available_equipment_by_location", {}).get(location, {})
        if not isinstance(equipment_local, Mapping):
            equipment_local = {}

        weights: dict[str, int] = {}
        for role in sorted(allowed_roles):
            if role in FORBIDDEN_PERMANENT_SUPPORT_ROLES or role in {"levy", "command_personnel"}:
                continue
            personnel = min(
                max(0, int(force.get("available_by_role", {}).get(role, 0) or 0)),
                max(0, int(local.get(role, 0) or 0)),
            )
            if personnel <= 0:
                continue
            # Use outfittable local bodies as the composition signal when an
            # equipment ledger exists. If no equipment ledger exists for the
            # force, personnel availability remains the material signal.
            if equipment_local:
                personnel = min(personnel, max(0, int(equipment_local.get(role, 0) or 0)))
            if personnel > 0:
                weights[role] = personnel
        total_weight = sum(weights.values())
        if total_weight <= 0:
            return {}

        # Hamilton allocation preserves the local reserve proportions exactly
        # enough for integer bodies without looping once per soldier. This is an
        # establishment target; actual assignment below still fails closed on
        # exact personnel/equipment shortages.
        raw = {role: amount * weight / total_weight for role, weight in weights.items()}
        desired = {role: int(value) for role, value in raw.items()}
        remainder = amount - sum(desired.values())
        if remainder > 0:
            order = sorted(weights, key=lambda role: (-(raw[role] - desired[role]), role))
            for role in order[:remainder]:
                desired[role] += 1
        return {role: count for role, count in desired.items() if count > 0}

    def _expand_formation_from_active_reserve(
        self,
        *,
        force: MutableMapping[str, Any],
        formation_ref: str,
        requested_increment: int,
        at: str,
        integration: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Permanently enlarge one existing formation from exact active reserve.

        The existing formation identity, cohort history and commander survive. The
        transfer consumes only real local force personnel/equipment/mounts. It
        never creates levy/support/engineer/command-support fighting roles.
        """
        formation_path, formation0 = self._load_formation(formation_ref)
        formation = copy.deepcopy(formation0)
        force_ref = str(force.get("owner_id", ""))
        if str(formation.get("owner_force_ref", "")) != force_ref:
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}}
        location = str(formation.get("location_ref", ""))
        current_n = max(0, int(formation.get("personnel", 0) or 0))
        increment = max(0, int(requested_increment))
        if increment <= 0 or current_n <= 0:
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}}
        current_comp = {
            str(role): max(0, int(count))
            for role, count in (formation.get("composition", {}) or {}).items()
            if max(0, int(count)) > 0 and str(role) not in FORBIDDEN_PERMANENT_SUPPORT_ROLES
        }
        if not current_comp:
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}}

        target_authorized = current_n + increment
        reinforcement_mix = self._standing_army_reinforcement_mix(
            force=force, formation=formation, increment=increment,
        )
        if not reinforcement_mix:
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}}
        target_comp = copy.deepcopy(current_comp)
        for role, count in reinforcement_mix.items():
            target_comp[role] = max(0, int(target_comp.get(role, 0))) + max(0, int(count))
        desired = copy.deepcopy(reinforcement_mix)
        local = force.get("available_by_location", {}).get(location, {})
        if not isinstance(local, Mapping):
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}}
        actual: dict[str, int] = {}
        for role, wanted in sorted(desired.items()):
            if role in FORBIDDEN_PERMANENT_SUPPORT_ROLES or wanted <= 0:
                continue
            available = min(
                max(0, int(force.get("available_by_role", {}).get(role, 0))),
                max(0, int(local.get(role, 0))),
            )
            equipment_local = force.get("available_equipment_by_location", {}).get(location, {})
            if isinstance(equipment_local, Mapping):
                available = min(available, max(0, int(equipment_local.get(role, 0) or 0)))
            if available > 0:
                actual[role] = min(wanted, available)
        moved = sum(actual.values())
        if moved <= 0:
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}}

        # Authorize the full requested establishment even if a specific role is
        # locally short. The current formation may remain understrength until a
        # later lawful replacement/reinforcement fills the exact deficit.
        formation["authorized_strength"] = target_authorized
        formation["establishment_composition"] = copy.deepcopy(target_comp)
        incoming_slices: list[dict[str, Any]] = []
        equipment = self._equipment_units(formation)
        shield_units = self._shield_units(formation)
        armor_units = self._armor_units(formation)
        for role, count in sorted(actual.items()):
            self._take_force_personnel(force, role, count, location)
            incoming_slices.extend(take_reserve_slices(
                force, role=role, count=count, location_ref=location,
                formation_ref=formation_ref, validate=False,
            ))
            gear = self._take_force_equipment(force, role, count, location)
            equipment[role] = max(0, int(equipment.get(role, 0))) + gear
            if gear > 0 and self._combat_role_uses_shield(role):
                shield_units[role] = max(0, int(shield_units.get(role, 0))) + gear
            if gear > 0 and self._combat_role_uses_armor(role):
                armor_units[role] = max(0, int(armor_units.get(role, 0))) + gear
            formation.setdefault("composition", {})[role] = int(formation.get("composition", {}).get(role, 0)) + count

        formation["personnel"] = current_n + moved
        self._set_equipment_units(formation, equipment)
        self._set_shield_units(formation, shield_units)
        self._set_armor_units(formation, armor_units)
        append_formation_slices(formation, incoming_slices)

        # Mounted reinforcement consumes real horses. Personnel may still be
        # under-horsed if the reserve is short; combat capability already reads
        # actual mount custody rather than trusting the role label.
        mount_path = self._mount_pool_path_for_formation(formation) if hasattr(self, "_mount_pool_path_for_formation") else None
        if mount_path:
            mount_pool = copy.deepcopy(self.read(mount_path))
            desired_horses = sum(
                self._role_horse_requirement(str(role), int(count))
                for role, count in formation.get("composition", {}).items()
            ) if hasattr(self, "_role_horse_requirement") else 0
            mounts = formation.setdefault("mounts", {})
            current_horses = max(0, int(mounts.get("horse", 0) or 0)) if isinstance(mounts, MutableMapping) else 0
            deficit = max(0, desired_horses - current_horses)
            issued = 0
            if deficit > 0:
                for role, count in sorted(actual.items()):
                    if deficit <= 0:
                        break
                    role_need = self._role_horse_requirement(str(role), int(count)) if hasattr(self, "_role_horse_requirement") else 0
                    role_need = min(deficit, role_need)
                    if role_need <= 0:
                        continue
                    from_role = issue_force_role_horses_to_formation(
                        mount_pool, location_ref=location, role=str(role), formation_ref=formation_ref, count=role_need,
                    )
                    from_region = 0
                    if from_role < role_need:
                        from_region = allocate_regional_horses_to_formation(
                            mount_pool, location_ref=location, formation_ref=formation_ref, count=role_need - from_role,
                        )
                    got = from_role + from_region
                    issued += got
                    deficit -= got
                if issued > 0 and isinstance(mounts, MutableMapping):
                    mounts["horse"] = current_horses + issued
                self.put(mount_path, mount_pool)

        new_n = max(1, int(formation.get("personnel", 0) or 0))
        for field, fallback in (("readiness", 55), ("morale", 65), ("cohesion", 35), ("training_progress", 45), ("fatigue", 0)):
            incoming_value = max(0, min(100, int(integration.get(field, fallback) or fallback)))
            old_value = max(0, min(100, int(formation0.get(field, incoming_value) or incoming_value)))
            formation[field] = max(0, min(100, int(round((old_value * current_n + incoming_value * moved) / new_n))))
        if moved >= current_n and str(formation.get("experience", "new")) in {"veteran", "hardened"}:
            formation["experience"] = "field_tested"
        normalize_formation_establishment(formation)
        reorganize_officer_cadre(formation, at=at, reason="standing_army_establishment_expansion")
        sync_materialized_officer_billets(self, formation)
        force.setdefault("allocated_to_formations", {})[formation_ref] = self._formation_allocation_record(formation)
        self.put(formation_path, formation)
        return {"formation_ref": formation_ref, "assigned": moved, "by_role": actual, "authorized_strength": target_authorized}

    def _sync_independent_formation_commander_span(self, formation_ref: str) -> None:
        try:
            _fp, formation = self._load_formation(formation_ref)
        except ValueError:
            return
        commander_ref = str(formation.get("commander_ref", ""))
        if not commander_ref:
            return
        try:
            person_path = self.owner_path(commander_ref)
            person0 = self.read(person_path)
        except (FileNotFoundError, KeyError, ValueError):
            return
        if not isinstance(person0, Mapping):
            return
        person = copy.deepcopy(dict(person0))
        span = max(0, int(formation.get("personnel", 0) or 0))
        assignment = person.setdefault("command_assignment", {})
        if isinstance(assignment, MutableMapping) and str(assignment.get("formation_ref", "")) == formation_ref and not assignment.get("command_group_ref"):
            assignment["current_command_span"] = span
        military = person.setdefault("military_command", {})
        if isinstance(military, MutableMapping) and str(military.get("formation_scope", "")) == formation_ref:
            military["level"] = f"{span}_commander"
        career = person.setdefault("career_state", {})
        if isinstance(career, MutableMapping) and str(assignment.get("formation_ref", "")) == formation_ref and not assignment.get("command_group_ref"):
            career["current_command_span"] = span
        self.put(person_path, person)

    def _reinforce_state_independent_formation_for_mobilization(
        self,
        formation_ref: str,
        *,
        state_ref: str,
        force_ref: str,
        at: str,
    ) -> dict[str, Any]:
        """Rank-guided permanent reinforcement for a real ungrouped state command."""
        try:
            _fp, formation = self._load_formation(formation_ref)
        except ValueError:
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}}
        if str(formation.get("owner_force_ref", "")) != force_ref or str(formation.get("administrative_owner", "")) != state_ref:
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}}
        commander_ref = str(formation.get("commander_ref", ""))
        if not commander_ref or commander_ref == str(getattr(self, "PLAYER_ACTOR", "char_tang_wei")):
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}}
        rules = self._standing_army_mobilization_rules()
        targets = rules.get("target_recursive_strength_by_rank", {}) if isinstance(rules.get("target_recursive_strength_by_rank"), Mapping) else {}
        integration = rules.get("integration_baseline", {}) if isinstance(rules.get("integration_baseline"), Mapping) else {}
        minimum_increment = max(100, int(rules.get("minimum_increment", 100) or 100))
        target = max(0, int(targets.get(self._commander_rank_grade(commander_ref), 0) or 0))
        current = max(0, int(formation.get("personnel", 0) or 0))
        if target <= current:
            self._sync_independent_formation_commander_span(formation_ref)
            return {"formation_ref": formation_ref, "assigned": 0, "by_role": {}, "authorized_strength": max(current, int(formation.get("authorized_strength", current) or current))}
        gap = ((target - current + minimum_increment - 1) // minimum_increment) * minimum_increment
        force_path = self.owner_path(force_ref)
        force = copy.deepcopy(self.read(force_path))
        before = sum(max(0, int(v)) for v in force.get("available_by_role", {}).values())
        result = self._expand_formation_from_active_reserve(
            force=force, formation_ref=formation_ref, requested_increment=gap, at=at, integration=integration,
        )
        if int(result.get("assigned", 0) or 0) > 0:
            validate_cohort_ledger(force)
            self.put(force_path, force)
            self._sync_independent_formation_commander_span(formation_ref)
        result["reserve_before"] = before
        result["reserve_after"] = sum(max(0, int(v)) for v in force.get("available_by_role", {}).values())
        return result

    def _reinforce_state_field_army_for_mobilization(
        self,
        group_ref: str,
        *,
        state_ref: str,
        force_ref: str,
        at: str,
    ) -> dict[str, Any]:
        """Grow one exact standing army using generic rank-guided state policy.

        Same-state nested field armies are handled first. Private/House nested
        armies remain intact and are counted in recursive strength but never draw
        sovereign reserve through this path.
        """
        rules = self._standing_army_mobilization_rules()
        targets = rules.get("target_recursive_strength_by_rank", {}) if isinstance(rules.get("target_recursive_strength_by_rank"), Mapping) else {}
        eligible_contexts = {str(x) for x in rules.get("eligible_contexts", []) if isinstance(x, str)}
        integration = rules.get("integration_baseline", {}) if isinstance(rules.get("integration_baseline"), Mapping) else {}
        minimum_increment = max(100, int(rules.get("minimum_increment", 100) or 100))
        state_ref = str(state_ref)
        force_path = self.owner_path(force_ref)
        force = copy.deepcopy(self.read(force_path))
        total_before = sum(max(0, int(v)) for v in force.get("available_by_role", {}).values())
        changed_groups: list[str] = []
        formation_rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        def visit(ref: str) -> None:
            if ref in seen:
                raise ValueError("command hierarchy contains a cycle")
            seen.add(ref)
            group = self.read_optional(f"state/cmd/command-groups/{ref}.json")
            if not isinstance(group, Mapping):
                return
            # Only the state's own field-army hierarchy receives state reserve.
            if str(group.get("authority_ref", "")) != state_ref or str(group.get("context", "")) not in eligible_contexts:
                return
            for unit in group.get("units", []) if isinstance(group.get("units"), list) else []:
                if not isinstance(unit, Mapping) or str(unit.get("kind", "")) != "nested_army":
                    continue
                child_ref = str(unit.get("ref", ""))
                child = self.read_optional(f"state/cmd/command-groups/{child_ref}.json")
                if isinstance(child, Mapping) and str(child.get("authority_ref", "")) == state_ref and str(child.get("context", "")) in eligible_contexts:
                    visit(child_ref)

            commander_ref = str(group.get("commander_ref", ""))
            if not commander_ref or commander_ref == str(getattr(self, "PLAYER_ACTOR", "char_tang_wei")):
                return
            grade = self._commander_rank_grade(commander_ref)
            target = max(0, int(targets.get(grade, 0) or 0))
            if target <= 0:
                return
            summary = self._command_group_organizational_summary(ref)
            current_recursive = max(0, int(summary.get("recursive_strength", 0) or 0))
            gap = max(0, target - current_recursive)
            if gap <= 0:
                self._adopt_current_command_group_establishment(ref, at=at)
                changed_groups.append(ref)
                return
            # Unit establishments use 100-man increments. Organic private child
            # strengths can make recursive totals non-round, so round only the
            # additional state fighting establishment upward.
            gap = ((gap + minimum_increment - 1) // minimum_increment) * minimum_increment
            direct_state_forms: list[tuple[int, str]] = []
            for unit in group.get("units", []) if isinstance(group.get("units"), list) else []:
                if not isinstance(unit, Mapping) or str(unit.get("kind", "")) != "formation":
                    continue
                formation_ref = str(unit.get("ref", ""))
                try:
                    _fp, formation = self._load_formation(formation_ref)
                except ValueError:
                    continue
                if str(formation.get("owner_force_ref", "")) != force_ref:
                    continue
                if str(formation.get("command_authority", "")) == str(getattr(self, "PLAYER_ACTOR", "char_tang_wei")):
                    continue
                direct_state_forms.append((max(0, int(formation.get("personnel", 0) or 0)), formation_ref))
            if not direct_state_forms:
                return
            direct_state_forms.sort(key=lambda row: (-row[0], row[1]))
            remaining = gap
            # Existing direct formations are the persistent army identity. Grow
            # the largest anchor first; additional direct formations remain intact.
            for _strength, formation_ref in direct_state_forms:
                if remaining <= 0:
                    break
                result = self._expand_formation_from_active_reserve(
                    force=force, formation_ref=formation_ref, requested_increment=remaining,
                    at=at, integration=integration,
                )
                assigned = max(0, int(result.get("assigned", 0) or 0))
                if assigned:
                    formation_rows.append(result)
                    remaining -= assigned
            self._adopt_current_command_group_establishment(ref, at=at)
            changed_groups.append(ref)

        visit(group_ref)
        if formation_rows:
            validate_cohort_ledger(force)
            self.put(force_path, force)
        # Child expansion changes every ancestor's recursive strength. Re-adopt
        # the root after the force write so its permanent establishment matches.
        for ref in reversed(changed_groups):
            self._adopt_current_command_group_establishment(ref, at=at)
        total_after = sum(max(0, int(v)) for v in force.get("available_by_role", {}).values()) if formation_rows else total_before
        return {
            "command_group_ref": group_ref,
            "assigned": sum(max(0, int(row.get("assigned", 0) or 0)) for row in formation_rows),
            "formations": formation_rows,
            "reserve_before": total_before,
            "reserve_after": total_after,
            "changed_command_group_refs": changed_groups,
        }

    def _reconstitute_force_from_local_reserve(self, force_path: str, at: str) -> dict[str, Any]:
        force = copy.deepcopy(self.read(force_path))
        if not isinstance(force.get("allocated_to_formations"), Mapping):
            return {"force_ref": force.get("owner_id"), "assigned": 0, "formations": []}
        owner_index = self.read("state/index/owner-index.json").get("owners", {})
        if not isinstance(owner_index, Mapping):
            raise ValueError("owner index is invalid")
        assigned_total = 0
        rows: list[dict[str, Any]] = []
        changed_force = False
        for formation_ref in sorted(force.get("allocated_to_formations", {})):
            route = owner_index.get(formation_ref)
            if not isinstance(route, str) or "#" in route:
                continue
            formation = copy.deepcopy(self.read(route))
            if str(formation.get("owner_force_ref")) != str(force.get("owner_id")):
                continue
            if str(formation.get("status", "")).lower() in {"destroyed", "dissolved"}:
                continue
            establishment = self._formation_establishment(formation)
            current = {str(k): max(0, int(v)) for k, v in (formation.get("composition", {}) or {}).items()}
            needs = {
                role: max(0, target - current.get(role, 0))
                for role, target in establishment.items()
            }
            if sum(needs.values()) <= 0:
                continue
            location = str(formation.get("location_ref", ""))
            local = force.get("available_by_location", {}).get(location, {})
            if not isinstance(local, Mapping):
                continue
            add: dict[str, int] = {}
            for role, need in needs.items():
                available = min(
                    max(0, int(force.get("available_by_role", {}).get(role, 0))),
                    max(0, int(local.get(role, 0))),
                )
                if available > 0 and need > 0:
                    add[role] = min(need, available)
            if not add:
                continue
            equipment = self._equipment_units(formation)
            shield_units = self._shield_units(formation)
            armor_units = self._armor_units(formation)
            incoming: list[dict[str, Any]] = []
            actual: dict[str, int] = {}
            for role, requested in sorted(add.items()):
                # Personnel and their cohort slices are exact authority. Equipment
                # shortage may leave some replacements temporarily under-equipped;
                # it never creates gear or blocks the body transfer itself.
                self._take_force_personnel(force, role, requested, location)
                incoming.extend(take_reserve_slices(
                    force, role=role, count=requested, location_ref=location,
                    formation_ref=formation_ref, validate=False,
                ))
                gear = self._take_force_equipment(force, role, requested, location)
                equipment[role] = int(equipment.get(role, 0)) + gear
                if gear > 0 and self._combat_role_uses_shield(role):
                    shield_units[role] = int(shield_units.get(role, 0)) + gear
                if gear > 0 and self._combat_role_uses_armor(role):
                    armor_units[role] = int(armor_units.get(role, 0)) + gear
                formation.setdefault("composition", {})[role] = int(formation.get("composition", {}).get(role, 0)) + requested
                actual[role] = requested
            moved = sum(actual.values())
            formation["personnel"] = int(formation.get("personnel", 0)) + moved
            self._set_equipment_units(formation, equipment)
            self._set_shield_units(formation, shield_units)
            self._set_armor_units(formation, armor_units)
            append_formation_slices(formation, incoming)

            # Mounted replacements consume real conserved horses. Prefer horses
            # already reserved to the promoted/replacement role, then use local
            # unassigned remounts. Personnel may still join under-horsed if the
            # physical pool is exhausted; no horse is invented to preserve a label.
            mount_path = self._mount_pool_path_for_formation(formation) if hasattr(self, "_mount_pool_path_for_formation") else None
            if mount_path:
                mount_pool = copy.deepcopy(self.read(mount_path))
                desired_horses = sum(
                    self._role_horse_requirement(str(role), int(count))
                    for role, count in formation.get("composition", {}).items()
                ) if hasattr(self, "_role_horse_requirement") else 0
                mounts = formation.setdefault("mounts", {})
                current_horses = max(0, int(mounts.get("horse", 0) or 0)) if isinstance(mounts, MutableMapping) else 0
                deficit = max(0, desired_horses - current_horses)
                issued = 0
                if deficit > 0:
                    for role, count in sorted(actual.items()):
                        if deficit <= 0:
                            break
                        role_need = self._role_horse_requirement(str(role), int(count)) if hasattr(self, "_role_horse_requirement") else 0
                        role_need = min(deficit, role_need)
                        if role_need <= 0:
                            continue
                        from_role = issue_force_role_horses_to_formation(
                            mount_pool, location_ref=location, role=str(role),
                            formation_ref=formation_ref, count=role_need,
                        )
                        from_region = 0
                        if from_role < role_need:
                            from_region = allocate_regional_horses_to_formation(
                                mount_pool, location_ref=location, formation_ref=formation_ref,
                                count=role_need - from_role,
                            )
                        got = from_role + from_region
                        issued += got
                        deficit -= got
                    if issued > 0 and isinstance(mounts, MutableMapping):
                        mounts["horse"] = current_horses + issued
                    self.put(mount_path, mount_pool)

            force.setdefault("allocated_to_formations", {})[formation_ref] = self._formation_allocation_record(formation)
            formation["last_reconstituted_at"] = at
            formation["last_reconstitution_by_role"] = actual
            reorganize_officer_cadre(formation, at=at, reason="post_battle_reconstitution")
            sync_materialized_officer_billets(self, formation)
            normalize_formation_establishment(formation)
            self.put(route, formation)
            rows.append({"formation_ref": formation_ref, "personnel": moved, "by_role": actual})
            assigned_total += moved
            changed_force = True
        if changed_force:
            validate_cohort_ledger(force)
            self.put(force_path, force)
        return {"force_ref": force.get("owner_id"), "assigned": assigned_total, "formations": rows}

    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_state(host, occurrences, at)
        state_ref = str(host.get("owner_ref", ""))
        state = state_ref.removeprefix("state_")
        path = f"state/forces/state-{state}.json"
        if state and self.read_optional(path) is not None:
            self._reconstitute_force_from_local_reserve(path, at)

    def _autonomy_house(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_house(host, occurrences, at)
        house_ref = str(host.get("owner_ref", ""))
        for path in self._house_force_paths(house_ref):
            self._reconstitute_force_from_local_reserve(path, at)
