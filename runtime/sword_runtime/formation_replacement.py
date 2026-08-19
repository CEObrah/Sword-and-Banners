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
from sword_runtime.officer_cadre import reorganize_officer_cadre
from sword_runtime.officer_personnel import sync_materialized_officer_billets

_HOUSE_FORCE_INDEX = "state/index/house-force-index.json"


class FormationReplacementMixin:
    def _formation_establishment(self, formation: MutableMapping[str, Any]) -> dict[str, int]:
        raw = formation.get("establishment_composition")
        if isinstance(raw, Mapping) and raw:
            return {str(k): max(0, int(v)) for k, v in raw.items() if int(v) >= 0}
        composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
        establishment = {str(k): max(0, int(v)) for k, v in composition.items()}
        formation["establishment_composition"] = copy.deepcopy(establishment)
        formation["establishment_personnel"] = sum(establishment.values())
        return establishment

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
            needs = {role: max(0, target - current.get(role, 0)) for role, target in establishment.items()}
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
            force.setdefault("allocated_to_formations", {})[formation_ref] = self._formation_allocation_record(formation)
            formation["last_reconstituted_at"] = at
            formation["last_reconstitution_by_role"] = actual
            formation["last_reconstitution_basis"] = "existing trained force reserve physically present at formation location"
            formation["replacement_rule"] = "No casualty is regenerated. Replacements are exact surviving/recruited force bodies; surviving officer grades persist and cadre is reused."
            reorganize_officer_cadre(formation, at=at, reason="post_battle_reconstitution")
            sync_materialized_officer_billets(self, formation)
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
        index = self.read_optional(_HOUSE_FORCE_INDEX)
        if not isinstance(index, Mapping):
            return
        for path in index.get("house_force_paths", {}).get(house_ref, []):
            if isinstance(path, str) and self.read_optional(path) is not None:
                self._reconstitute_force_from_local_reserve(path, at)
