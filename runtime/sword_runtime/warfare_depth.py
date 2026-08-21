"""Persistent combined-arms and conserved command-depth integration.

Normal persistent formations store fighting establishment in ``personnel``.
Internal command nodes are assignments over bodies already counted in that
fighting strength. State, House, private, personal, polity and rebel formations
therefore share one command model without creating another manpower authority.

The persistent Unit commander and formal deputy sit outside fighting
establishment and remain exact/conserved people or lawful aggregate command
bodies. Internal 1,000/500/100 commanders are assignments held by bodies already
inside fighting establishment. Routine staff, signal, messenger, supply and
medical work has no mandatory manpower quota: its effectiveness is derived from
real command skill, communications, logistics, medical capability, material
resources, readiness, cohesion, terrain and conditions.

Mercenary owners keep their saved total company headcount. Existing explicit
non-fighting pools remain historical company composition, but the engine never
carves an additional fixed support quota out of fighting strength. Quarterly
mercenary reviews use the same aggregate diminishing-return development law as
other military cohorts.

Officer representation is sparse. Generic billets remain aggregate until exact
saved relevance, exceptional performance or provenance-backed high potential
requires an individual person owner.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import (
    ATTRIBUTE_ORDER,
    SKILL_ORDER,
    PROFESSIONAL_SKILL_SET,
    cohort_merged_skill_means,
    ensure_cohort_ledger,
    ensure_formation_composition,
    stable_fraction,
    validate_cohort_ledger,
)
from sword_runtime.living_world import LivingWorldSwordPlanner, OPERATIONAL_MEMORY_PATH
from sword_runtime.officer_cadre import officer_cadre_summary
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_programs import REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH, resolve_program_ref, settle_cohort_program
from sword_runtime.training_instructors import instructor_contexts_for_program
from sword_runtime.training_facilities import program_facility_access
from sword_runtime.unit_establishment import authorized_strength_for, classify_formation, formation_class_for, hierarchy_rows, hierarchy_topology

_RULES_PATH = "game/data/mechanics/warfare-organization.json"
_ACTIVE_REVIEW_STATES = frozenset({"planned", "mobilizing", "active"})
_MERCENARY_SCHEMAS = frozenset({"mercenary", "mercenary-company"})


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


def _clean_role_counts(raw: Any) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(role): max(0, int(count))
        for role, count in raw.items()
        if max(0, int(count)) > 0
    }


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
            "inside_fighting_establishment": True,
        })
    return rows


def build_formation_command_structure(formation: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    """Pure projection of one normal formation's command establishment.

    Unit-command targets and actual conserved command attachments are
    intentionally separate. Routine support functions have no headcount target
    and therefore cannot create staffing vacancies or phantom personnel.
    """
    cfg = rules.get("formation_command_structure", {}) if isinstance(rules, Mapping) else {}
    policy = rules.get("officer_representation_policy", {}) if isinstance(rules, Mapping) else {}
    n = max(0, int(formation.get("personnel", 0)))
    profile = _profile_for(formation, rules)

    # Internal command echelons come only from durable authorized establishment.
    # Current casualty strength never regenerates the tree. Saved/profile rows may
    # preserve representation/loadout metadata, but may not invent same-echelon or
    # larger subordinate billets.
    klass = formation_class_for(formation, personnel=n, explicit=formation.get("formation_class"))
    authorized = authorized_strength_for(formation, personnel=n, formation_class=klass)
    metadata_by_scale: dict[int, dict[str, Any]] = {}

    def _collect_meta(raw: Any) -> None:
        rows: list[Mapping[str, Any]] = []
        if isinstance(raw, list):
            rows = [row for row in raw if isinstance(row, Mapping)]
        elif isinstance(raw, Mapping):
            summary = raw.get("summary", [])
            if isinstance(summary, list):
                rows = [row for row in summary if isinstance(row, Mapping)]
        for row in rows:
            scale = max(0, int(row.get("scale", 0) or 0))
            if scale <= 0:
                continue
            meta = metadata_by_scale.setdefault(scale, {})
            for key in ("representation", "loadout_ref"):
                if key in row:
                    meta[key] = row[key]

    _collect_meta(profile.get("internal_hierarchy") if isinstance(profile, Mapping) else None)
    default_rep = str(cfg.get("generic_representation", policy.get("default_representation", "aggregate"))) if isinstance(cfg, Mapping) else "aggregate"
    hierarchy = hierarchy_rows(
        authorized_strength=authorized,
        current_personnel=n,
        formation_class=klass,
        representation_by_scale={scale: str(meta.get("representation", default_rep)) for scale, meta in metadata_by_scale.items()},
    )
    for row in hierarchy:
        meta = metadata_by_scale.get(int(row.get("scale", 0)), {})
        row["representation"] = str(meta.get("representation", row.get("representation", default_rep)))
        if meta.get("loadout_ref"):
            row["loadout_ref"] = str(meta["loadout_ref"])
    internal_output: Any = copy.deepcopy(hierarchy)
    internal_commanders = sum(max(0, int(row.get("count", 0))) for row in hierarchy)

    unit_command = profile.get("external_unit_command", {}) if isinstance(profile, Mapping) else {}
    if not isinstance(unit_command, Mapping):
        unit_command = {}
    generic_unit = cfg.get("unit_command", {}) if isinstance(cfg, Mapping) else {}
    if not isinstance(generic_unit, Mapping):
        generic_unit = {}
    commander_billets = max(0, int(unit_command.get("commander_billets", generic_unit.get("commander_billets_per_formation", 1 if n else 0))))
    deputy_billets = max(0, int(unit_command.get("deputy_billets", generic_unit.get("deputy_billets_per_formation", 1 if n else 0))))
    external_command_target = commander_billets + deputy_billets
    allocated_unit_command = _clean_role_counts(formation.get("attached_unit_command_by_role", {}))
    allocated_unit_command_total = sum(allocated_unit_command.values())

    commander_ref = formation.get("commander_ref")
    deputy_ref = formation.get("deputy_ref")
    exact_commander = isinstance(commander_ref, str) and bool(commander_ref)
    exact_deputy = isinstance(deputy_ref, str) and bool(deputy_ref)
    unit_cells = formation.get("unit_command_cells", [])
    cell_commander_refs: list[str] = []
    cell_deputy_refs: list[str] = []
    if isinstance(unit_cells, list):
        for cell in unit_cells:
            if not isinstance(cell, Mapping):
                continue
            cref = cell.get("commander_ref")
            dref = cell.get("deputy_ref")
            if isinstance(cref, str) and cref:
                cell_commander_refs.append(cref)
            if isinstance(dref, str) and dref:
                cell_deputy_refs.append(dref)
    exact_named_billets = min(
        external_command_target,
        int(exact_commander) + int(exact_deputy) + len(cell_commander_refs) + len(cell_deputy_refs),
    )
    effective_unit_staffed = min(external_command_target, exact_named_billets + allocated_unit_command_total)
    unit_shortfall = max(0, external_command_target - effective_unit_staffed)
    default_representation = str(generic_unit.get("default_representation", policy.get("default_representation", "aggregate")))
    if exact_commander:
        staffing = "named_unit_command"
    elif effective_unit_staffed >= max(1, commander_billets):
        staffing = "aggregate_unit_command"
    elif n > 0:
        staffing = "internal_leadership_only"
    else:
        staffing = "empty"
    actual_external = allocated_unit_command_total
    return {
        "projection_kind": "formation_command_structure_v4",
        "accounting_mode": "fighting_establishment_plus_unit_command",
        "fighting_establishment": n,
        "formation_class": klass,
        "authorized_strength": authorized,
        "establishment_topology": hierarchy_topology(authorized_strength=authorized, formation_class=klass),
        "persistent_unit_slots": 1 if n else 0,
        "attached_personnel_target": n + external_command_target,
        "attached_personnel_actual_from_force_allocations": n + actual_external,
        "external_attachment_target": external_command_target,
        "external_attachment_allocated": actual_external,
        "unit_command": {
            "commander_billets": commander_billets,
            "deputy_billets": deputy_billets,
            "target_bodies": external_command_target,
            "allocated_aggregate_by_role": allocated_unit_command,
            "allocated_aggregate_bodies": allocated_unit_command_total,
            "named_billets_present": exact_named_billets,
            "effective_billets_staffed": effective_unit_staffed,
            "staffing_shortfall": unit_shortfall,
            "outside_fighting_establishment": True,
            "source_force_ref": unit_command.get("source_force_ref", formation.get("owner_force_ref")),
            "source_role": unit_command.get("source_role", generic_unit.get("source_role", "command_personnel")),
            "representation": unit_command.get("representation", default_representation),
            "named_commander_ref": commander_ref if exact_commander else None,
            "named_deputy_ref": deputy_ref if exact_deputy else None,
            "unit_cell_commander_refs": cell_commander_refs,
            "unit_cell_deputy_refs": cell_deputy_refs,
        },
        "unit_command_cells": copy.deepcopy(unit_cells) if isinstance(unit_cells, list) else [],
        "internal_hierarchy": internal_output,
        "officer_cadre": officer_cadre_summary(formation),
        "internal_commander_assignments": internal_commanders,
        "internal_commanders_inside_fighting_establishment": internal_commanders,
        "staffing_status": staffing,
        "subordinate_registry_kind": "internal_command_assignments",
    }


def build_mercenary_command_structure(company: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    """Project command depth from one conserved mercenary-company owner."""
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

    levels = cfg.get("generic_internal_levels", [1000, 500, 100]) if isinstance(cfg, Mapping) else [1000, 500, 100]
    representation = str(cfg.get("generic_representation", policy.get("default_representation", "aggregate"))) if isinstance(cfg, Mapping) else "aggregate"
    hierarchy = _generic_hierarchy(fighting, levels, representation=representation)
    internal_commanders = sum(int(row.get("count", 0)) for row in hierarchy)

    unit_cfg = cfg.get("unit_command", {}) if isinstance(cfg, Mapping) else {}
    commander_billets = max(0, int(unit_cfg.get("commander_billets_per_company", 1 if total else 0))) if isinstance(unit_cfg, Mapping) else (1 if total else 0)
    deputy_billets = max(0, int(unit_cfg.get("deputy_billets_per_company", 1 if total else 0))) if isinstance(unit_cfg, Mapping) else (1 if total else 0)
    command_target = commander_billets + deputy_billets
    # No fixed support quota. Existing explicit non-fighting pools are preserved as
    # company composition, but routine support work does not create new vacancies
    # or force automatic reassignment from fighting pools.
    support_targets: dict[str, int] = {}
    support_target = 0
    non_fighting_target = command_target
    shortfall = max(0, command_target - non_fighting)
    target_fighting_if_rebalanced = fighting

    return {
        "projection_kind": "mercenary_command_structure",
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
        "unit_command": {
            "commander_billets": commander_billets,
            "deputy_billets": deputy_billets,
            "inside_total_headcount": True,
            "representation": unit_cfg.get("default_representation", representation) if isinstance(unit_cfg, Mapping) else representation,
        },
        "internal_hierarchy": hierarchy,
        "officer_cadre": {
            "representation": "aggregate",
            "inside_total_headcount": True,
            "unit_command_billets": command_target,
            "internal_commander_assignments": internal_commanders,
            "rank_inventory": {
                f"{int(row.get('scale', 0))}_commander": int(row.get("count", 0))
                for row in hierarchy
                if int(row.get("scale", 0)) > 0 and int(row.get("count", 0)) > 0
            },
        },
        "internal_commander_assignments": internal_commanders,
        "internal_commanders_inside_fighting_establishment": internal_commanders,
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

    @staticmethod
    def _external_allocations(force: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        value = force.setdefault("external_personnel_allocations", {})
        if not isinstance(value, MutableMapping):
            raise ValueError("force external personnel allocations must be an object")
        return value

    @staticmethod
    def _formation_external_roles(force: Mapping[str, Any], formation_ref: str) -> dict[str, int]:
        raw = force.get("external_personnel_allocations", {})
        row = raw.get(formation_ref, {}) if isinstance(raw, Mapping) else {}
        return _clean_role_counts(row)

    def _adjust_external_role_allocation(
        self,
        force: MutableMapping[str, Any],
        *,
        formation_ref: str,
        role: str,
        desired: int,
        location_ref: str,
    ) -> int:
        """Reconcile one source-force external role against real reserve bodies."""
        target = max(0, int(desired))
        allocations = self._external_allocations(force)
        row = allocations.setdefault(formation_ref, {})
        if not isinstance(row, MutableMapping):
            raise ValueError("formation external personnel allocation must be an object")
        current = max(0, int(row.get(role, 0)))
        ledger = ensure_cohort_ledger(force)
        cohorts = ledger.get("cohorts", {})
        if not isinstance(cohorts, MutableMapping):
            raise ValueError("force cohort ledger is invalid")
        roles = force.setdefault("available_by_role", {})
        by_location = force.setdefault("available_by_location", {})
        local = by_location.setdefault(location_ref, {})
        if not isinstance(roles, MutableMapping) or not isinstance(local, MutableMapping):
            raise ValueError("force reserve counters are invalid")

        if target > current:
            need = target - current
            available = min(max(0, int(roles.get(role, 0))), max(0, int(local.get(role, 0))))
            take_total = min(need, available)
            remaining = take_total
            candidates: list[tuple[str, MutableMapping[str, Any]]] = []
            for cid, cohort in cohorts.items():
                if not isinstance(cohort, MutableMapping) or str(cohort.get("role", "")) != role:
                    continue
                if int(cohort.get("reserve_by_location", {}).get(location_ref, 0)) > 0:
                    candidates.append((str(cid), cohort))
            candidates.sort(key=lambda item: (str(item[1].get("origin", {}).get("recruited_at") or ""), item[0]))
            for _cid, cohort in candidates:
                if remaining <= 0:
                    break
                reserve = cohort.setdefault("reserve_by_location", {})
                take = min(remaining, max(0, int(reserve.get(location_ref, 0))))
                if take <= 0:
                    continue
                reserve[location_ref] = int(reserve.get(location_ref, 0)) - take
                if reserve[location_ref] == 0:
                    reserve.pop(location_ref, None)
                ext = cohort.setdefault("allocated_external_by_formation", {})
                ext[formation_ref] = int(ext.get(formation_ref, 0)) + take
                remaining -= take
            if remaining:
                raise ValueError("external personnel allocation exceeded conserved cohort reserve")
            roles[role] = max(0, int(roles.get(role, 0)) - take_total)
            local[role] = max(0, int(local.get(role, 0)) - take_total)
            current += take_total
        elif target < current:
            release = current - target
            remaining = release
            candidates = []
            for cid, cohort in cohorts.items():
                if not isinstance(cohort, MutableMapping) or str(cohort.get("role", "")) != role:
                    continue
                held = int(cohort.get("allocated_external_by_formation", {}).get(formation_ref, 0))
                if held > 0:
                    candidates.append((str(cid), cohort))
            candidates.sort(key=lambda item: item[0], reverse=True)
            for _cid, cohort in candidates:
                if remaining <= 0:
                    break
                ext = cohort.setdefault("allocated_external_by_formation", {})
                held = max(0, int(ext.get(formation_ref, 0)))
                give = min(remaining, held)
                if give <= 0:
                    continue
                if held == give:
                    ext.pop(formation_ref, None)
                else:
                    ext[formation_ref] = held - give
                reserve = cohort.setdefault("reserve_by_location", {})
                reserve[location_ref] = int(reserve.get(location_ref, 0)) + give
                remaining -= give
            if remaining:
                raise ValueError("external personnel release exceeded conserved allocation")
            roles[role] = int(roles.get(role, 0)) + release
            local[role] = int(local.get(role, 0)) + release
            current -= release

        if current > 0:
            row[role] = current
        else:
            row.pop(role, None)
        if not row:
            allocations.pop(formation_ref, None)
        validate_cohort_ledger(force)
        return current

    def _kill_external_role_allocation(
        self,
        force: MutableMapping[str, Any],
        *,
        formation_ref: str,
        role: str,
        losses: int,
        evidence_ref: str,
    ) -> int:
        """Remove killed attached personnel from force headcount exactly once."""
        requested = max(0, int(losses))
        if requested <= 0:
            return 0
        allocations = self._external_allocations(force)
        row = allocations.get(formation_ref)
        if not isinstance(row, MutableMapping):
            return 0
        held_total = max(0, int(row.get(role, 0)))
        killed = min(requested, held_total)
        if killed <= 0:
            return 0
        ledger = ensure_cohort_ledger(force)
        cohorts = ledger.get("cohorts", {})
        if not isinstance(cohorts, MutableMapping):
            raise ValueError("force cohort ledger is invalid")
        remaining = killed
        candidates: list[tuple[str, MutableMapping[str, Any]]] = []
        for cid, cohort in cohorts.items():
            if not isinstance(cohort, MutableMapping) or str(cohort.get("role", "")) != role:
                continue
            if int(cohort.get("allocated_external_by_formation", {}).get(formation_ref, 0)) > 0:
                candidates.append((str(cid), cohort))
        candidates.sort(key=lambda item: item[0])
        for _cid, cohort in candidates:
            if remaining <= 0:
                break
            ext = cohort.setdefault("allocated_external_by_formation", {})
            held = max(0, int(ext.get(formation_ref, 0)))
            take = min(remaining, held)
            if take <= 0:
                continue
            if held == take:
                ext.pop(formation_ref, None)
            else:
                ext[formation_ref] = held - take
            cohort.setdefault("casualty_history", []).append({
                "ref": evidence_ref,
                "count": take,
                "kind": "external_formation_attachment",
                "formation_ref": formation_ref,
                "role": role,
            })
            cohort["casualty_history"] = cohort["casualty_history"][-24:]
            remaining -= take
        if remaining:
            raise ValueError("external personnel casualties exceeded cohort allocation")
        new_held = held_total - killed
        if new_held:
            row[role] = new_held
        else:
            row.pop(role, None)
        if not row:
            allocations.pop(formation_ref, None)
        force["headcount"] = max(0, int(force.get("headcount", 0)) - killed)
        validate_cohort_ledger(force)
        return killed

    def _promote_fighting_bodies_to_unit_command(
        self,
        force: MutableMapping[str, Any],
        formation: MutableMapping[str, Any],
        *,
        requested: int,
    ) -> dict[str, int]:
        """Reclassify conserved anonymous fighters into external Unit-command posts.

        This is a lawful establishment repair when a source force has no separate
        command-personnel reserve. The same bodies leave fighting strength and
        become external command attachments; force headcount never changes.
        Selection is deterministic and prefers the formation cohort with the
        strongest saved command profile.
        """
        need = max(0, int(requested))
        if need <= 0:
            return {}
        ref = str(formation.get("formation_ref", ""))
        if not ref:
            raise ValueError("formation command promotion requires formation_ref")
        ensure_formation_composition(force, formation)
        ledger = ensure_cohort_ledger(force)
        cohorts = ledger.get("cohorts", {})
        if not isinstance(cohorts, MutableMapping):
            raise ValueError("force cohort ledger is invalid")

        raw_slices = [dict(row) for row in formation.get("cohort_composition", []) if isinstance(row, Mapping)]
        candidates: list[tuple[float, str, int, str]] = []
        for row in raw_slices:
            cid = str(row.get("cohort_id", ""))
            count = max(0, int(row.get("count", 0)))
            cohort = cohorts.get(cid)
            if count <= 0 or not isinstance(cohort, MutableMapping):
                continue
            skills = cohort_merged_skill_means(cohort)
            score = (
                float(skills.get("Formation Command", 0)) * 0.40
                + float(skills.get("Leadership", 0)) * 0.30
                + float(skills.get("Tactics", 0)) * 0.20
                + float(skills.get("Strategy", 0)) * 0.10
            )
            candidates.append((-score, cid, count, str(cohort.get("role", "unknown"))))
        candidates.sort(key=lambda row: (row[0], row[1]))
        if sum(row[2] for row in candidates) < need:
            raise ValueError("formation lacks conserved anonymous bodies for Unit-command promotion")

        slice_counts = {str(row.get("cohort_id")): max(0, int(row.get("count", 0))) for row in raw_slices}
        moved_by_role: dict[str, int] = {}
        remaining = need
        allocations = self._external_allocations(force)
        ext_row = allocations.setdefault(ref, {})
        if not isinstance(ext_row, MutableMapping):
            raise ValueError("formation external personnel allocation must be an object")
        for _neg_score, cid, count, role in candidates:
            if remaining <= 0:
                break
            take = min(remaining, count)
            cohort = cohorts[cid]
            allocated = cohort.setdefault("allocated_by_formation", {})
            held = max(0, int(allocated.get(ref, 0)))
            if held < take:
                raise ValueError("Unit-command promotion exceeded conserved formation cohort")
            if held == take:
                allocated.pop(ref, None)
            else:
                allocated[ref] = held - take
            external = cohort.setdefault("allocated_external_by_formation", {})
            external[ref] = int(external.get(ref, 0)) + take
            slice_counts[cid] = max(0, slice_counts.get(cid, 0) - take)
            moved_by_role[role] = int(moved_by_role.get(role, 0)) + take
            ext_row[role] = int(ext_row.get(role, 0)) + take
            remaining -= take
        if remaining:
            raise ValueError("Unit-command promotion did not satisfy requested bodies")

        formation["cohort_composition"] = [
            {"cohort_id": cid, "count": count}
            for cid, count in sorted(slice_counts.items()) if count > 0
        ]
        composition = formation.setdefault("composition", {})
        if not isinstance(composition, MutableMapping):
            raise ValueError("formation composition is invalid")
        for role, count in moved_by_role.items():
            current = max(0, int(composition.get(role, 0)))
            if current < count:
                raise ValueError("Unit-command promotion exceeded formation role composition")
            new = current - count
            if new:
                composition[role] = new
            else:
                composition.pop(role, None)
        formation["personnel"] = max(0, int(formation.get("personnel", 0)) - need)

        force_alloc = force.setdefault("allocated_to_formations", {})
        frow = force_alloc.get(ref)
        if not isinstance(frow, MutableMapping):
            raise ValueError("force formation allocation is missing for Unit-command promotion")
        frow["personnel"] = max(0, int(frow.get("personnel", 0)) - need)
        # Force allocation rows have two lawful compact shapes: mixed-role rows
        # carry ``composition`` while homogeneous rows carry a single ``role``.
        # Both already conserve the same fighting bodies. Do not manufacture a
        # composition map for homogeneous rows merely to record the decrement.
        if isinstance(frow.get("composition"), MutableMapping):
            fcomp = frow["composition"]
            for role, count in moved_by_role.items():
                current = max(0, int(fcomp.get(role, 0)))
                if current < count:
                    raise ValueError("Unit-command promotion exceeded force role allocation")
                new = current - count
                if new:
                    fcomp[role] = new
                else:
                    fcomp.pop(role, None)
        else:
            homogeneous_role = str(frow.get("role", ""))
            if not homogeneous_role or any(role != homogeneous_role for role in moved_by_role):
                raise ValueError("Unit-command promotion mismatched homogeneous force allocation role")
        validate_cohort_ledger(force)
        return moved_by_role

    @staticmethod
    def _named_unit_command_count(formation: Mapping[str, Any], target: int) -> int:
        refs = {
            str(formation.get(key))
            for key in ("commander_ref", "deputy_ref")
            if isinstance(formation.get(key), str) and str(formation.get(key))
        }
        return min(max(0, int(target)), len(refs))

    def _reconcile_formation_external_personnel(self, formation_ref: str, *, refill: bool = True) -> Mapping[str, Any]:
        """Staff one formation from its exact source force without changing fighters."""
        path, formation0 = self._load_formation(formation_ref)
        formation = copy.deepcopy(formation0)
        structure = build_formation_command_structure(formation, self._warfare_depth_rules())
        unit = structure.get("unit_command", {}) if isinstance(structure, Mapping) else {}
        unit_source = str(unit.get("source_force_ref") or formation.get("owner_force_ref") or "") if isinstance(unit, Mapping) else ""
        if not unit_source:
            formation["attached_support_by_role"] = {}
            formation.pop("command_structure", None)
            self.put(path, formation)
            return structure
        try:
            force_path = self.owner_path(unit_source)
            force0 = self.read(force_path)
        except (KeyError, ValueError, FileNotFoundError):
            formation.pop("command_structure", None)
            self.put(path, formation)
            return structure
        if not isinstance(force0, Mapping):
            return structure
        force = copy.deepcopy(force0)
        location_ref = str(formation.get("location_ref", ""))
        if not location_ref:
            formation.pop("command_structure", None)
            self.put(path, formation)
            return structure

        unit_target = max(0, int(unit.get("target_bodies", 0))) if isinstance(unit, Mapping) else 0
        named = self._named_unit_command_count(formation, unit_target)
        aggregate_unit_need = max(0, unit_target - named)
        unit_role = str(unit.get("source_role", "command_personnel")) if isinstance(unit, Mapping) else "command_personnel"
        existing_roles = self._formation_external_roles(force, formation_ref)
        desired_by_role: dict[str, int] = {}
        remaining_target = aggregate_unit_need
        # Existing conserved command attachments stay valid even when their source
        # role is the formation role they were promoted from rather than a dedicated
        # command_personnel reserve.
        for role in sorted(existing_roles, key=lambda r: (r != unit_role, r)):
            keep = min(remaining_target, max(0, int(existing_roles.get(role, 0))))
            if keep:
                desired_by_role[role] = keep
                remaining_target -= keep
        if remaining_target > 0:
            desired_by_role[unit_role] = int(desired_by_role.get(unit_role, 0)) + remaining_target
        all_roles = sorted(set(existing_roles) | set(desired_by_role))
        actual_by_role: dict[str, int] = {}
        for role in all_roles:
            desired = int(desired_by_role.get(role, 0))
            if not refill and desired > int(existing_roles.get(role, 0)):
                desired = int(existing_roles.get(role, 0))
            actual_by_role[role] = self._adjust_external_role_allocation(
                force,
                formation_ref=formation_ref,
                role=role,
                desired=desired,
                location_ref=location_ref,
            )
        actual_by_role = {role: count for role, count in actual_by_role.items() if count > 0}

        command_actual = min(aggregate_unit_need, sum(actual_by_role.values()))
        if refill and command_actual < aggregate_unit_need:
            promoted = self._promote_fighting_bodies_to_unit_command(
                force, formation, requested=aggregate_unit_need - command_actual
            )
            if promoted:
                actual_by_role = self._formation_external_roles(force, formation_ref)
                command_actual = min(aggregate_unit_need, sum(actual_by_role.values()))
        formation["attached_unit_command_by_role"] = dict(actual_by_role) if command_actual else {}
        # Legacy support attachments are released by the all_roles reconciliation
        # above and never regenerated. Keep the old field empty for backward-
        # compatible reads while removing it as a manpower authority.
        formation["attached_support_by_role"] = {}
        formation["command_attachment_source_force_ref"] = unit_source
        formation.pop("command_structure", None)
        projection = build_formation_command_structure(formation, self._warfare_depth_rules())
        self.put(force_path, force)
        self.put(path, formation)
        return projection

    def _release_formation_external_personnel(self, formation_ref: str) -> None:
        try:
            path, formation0 = self._load_formation(formation_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return
        formation = copy.deepcopy(formation0)
        source_ref = str(formation.get("command_attachment_source_force_ref") or formation.get("owner_force_ref") or "")
        if not source_ref:
            return
        try:
            force_path = self.owner_path(source_ref)
            force = copy.deepcopy(self.read(force_path))
        except (KeyError, ValueError, FileNotFoundError):
            return
        location = str(formation.get("location_ref", ""))
        if not location:
            return
        existing = self._formation_external_roles(force, formation_ref)
        for role in sorted(existing):
            self._adjust_external_role_allocation(force, formation_ref=formation_ref, role=role, desired=0, location_ref=location)
        formation["attached_unit_command_by_role"] = {}
        formation["attached_support_by_role"] = {}
        formation.pop("command_structure", None)
        self.put(force_path, force)
        self.put(path, formation)

    def _ensure_formation_command_structure(self, formation_ref: str) -> Mapping[str, Any]:
        _path, formation = self._load_formation(formation_ref)
        return build_formation_command_structure(formation, self._warfare_depth_rules())

    def _ensure_force_command_structures(self, force_ref: str, *, refill: bool = True) -> None:
        try:
            force = self.read(self.owner_path(force_ref))
        except (KeyError, ValueError, FileNotFoundError):
            return
        allocated = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
        if not isinstance(allocated, Mapping):
            return
        for formation_ref in sorted(str(ref) for ref in allocated):
            try:
                self._reconcile_formation_external_personnel(formation_ref, refill=refill)
            except (KeyError, ValueError, FileNotFoundError):
                continue

    def _ensure_mercenary_command_structure(self, mercenary_ref: str) -> Mapping[str, Any]:
        path = self.owner_path(mercenary_ref)
        company0 = self.read(path)
        if not isinstance(company0, Mapping) or str(company0.get("schema", "")) not in _MERCENARY_SCHEMAS:
            raise ValueError("mercenary command projection requires an exact mercenary owner")
        company = copy.deepcopy(company0)
        desired = build_mercenary_command_structure(company, self._warfare_depth_rules())
        if company.get("command_structure") != desired:
            company["command_structure"] = desired
            self.put(path, company)
        return desired

    @staticmethod
    def _mercenary_age_mean(company: Mapping[str, Any], capability: Mapping[str, Any]) -> float:
        for source in (capability.get("body_distribution"), company.get("body_distribution")):
            if not isinstance(source, Mapping):
                continue
            direct = source.get("age_mean")
            if isinstance(direct, (int, float)) and not isinstance(direct, bool):
                return float(direct)
            bands = source.get("age_distribution_pct")
            if isinstance(bands, Mapping):
                mids = {"15_19": 17.0, "20_29": 24.5, "30_39": 34.5, "40_plus": 45.0}
                weighted = sum(max(0.0, float(bands.get(key, 0))) * mid for key, mid in mids.items())
                total = sum(max(0.0, float(bands.get(key, 0))) for key in mids)
                if total > 0:
                    return weighted / total
        return 28.0

    @staticmethod
    def _mercenary_focus(pool: Mapping[str, Any], cfg: Mapping[str, Any]) -> tuple[list[str], list[str]]:
        text = " ".join(str(pool.get(key, "")) for key in ("role", "troop_type", "specialty", "display")).lower()
        profiles = cfg.get("focus_profiles", []) if isinstance(cfg, Mapping) else []
        for row in profiles if isinstance(profiles, list) else []:
            if not isinstance(row, Mapping):
                continue
            tokens = [str(token).lower() for token in row.get("tokens", []) if str(token)]
            if any(token in text for token in tokens):
                return ([str(x) for x in row.get("skills", [])], [str(x) for x in row.get("attributes", [])])
        return ([str(x) for x in cfg.get("default_skills", [])], [str(x) for x in cfg.get("default_attributes", [])])

    def _settle_mercenary_training(self, mercenary_ref: str, occurrences: int, at: str) -> None:
        """Advance exact aggregate mercenary capability owners on quarterly review."""
        if occurrences <= 0:
            return
        path = self.owner_path(mercenary_ref)
        company0 = self.read(path)
        if not isinstance(company0, Mapping) or str(company0.get("schema", "")) not in _MERCENARY_SCHEMAS:
            return
        company = copy.deepcopy(company0)
        if str(company.get("status", "")).lower() in {"destroyed", "dissolved"}:
            return
        cfg = self._warfare_depth_rules().get("mercenary_training", {})
        if not isinstance(cfg, Mapping):
            return
        status_key = str(company.get("status", "available")).lower()
        hours_table = cfg.get("hours_per_review_by_status", {})
        per_review = max(0.0, float(hours_table.get(status_key, hours_table.get("available", 0))) if isinstance(hours_table, Mapping) else 0.0)
        deliberate = per_review * max(0, int(occurrences))
        exposure = deliberate * max(0.0, min(1.0, float(cfg.get("role_exposure_fraction", 0.35))))
        if deliberate <= 0 and exposure <= 0:
            return
        stat_registry = self.read("game/data/mechanics/stat-orders.json")
        stat_profile = stat_registry.get("profiles", {}).get("military_person", {}) if isinstance(stat_registry, Mapping) else {}
        attr_order = [str(x) for x in stat_profile.get("attribute_order", ATTRIBUTE_ORDER)] if isinstance(stat_profile, Mapping) else list(ATTRIBUTE_ORDER)
        skill_order = [str(x) for x in stat_profile.get("skill_order", SKILL_ORDER)] if isinstance(stat_profile, Mapping) else list(SKILL_ORDER)
        training_rules = self.read("game/data/mechanics/training.json")
        updated_pools: list[str] = []
        total_personnel = 0
        for pool in company.get("troop_pools", []) if isinstance(company.get("troop_pools"), list) else []:
            if not isinstance(pool, MutableMapping):
                continue
            capability0 = pool.get("capability")
            if not isinstance(capability0, Mapping):
                continue
            capability = copy.deepcopy(capability0)
            caps = capability.get("capabilities")
            if not isinstance(caps, MutableMapping):
                continue
            attr_values = caps.get("attribute_values", [])
            skill_values = caps.get("skill_values", [])
            professional_values = caps.get("professional_skill_values", {})
            if not isinstance(attr_values, list) or not isinstance(skill_values, list) or not isinstance(professional_values, Mapping):
                continue
            if len(skill_values) != len(skill_order):
                raise ValueError(f"mercenary capability skill vector must match current core skill order: {mercenary_ref}")
            attr_means = {name: float(attr_values[i]) for i, name in enumerate(attr_order) if i < len(attr_values)}
            skill_means = {name: float(skill_values[i]) for i, name in enumerate(skill_order)}
            professional_means = {
                str(name): float(value)
                for name, value in professional_values.items()
                if str(name) in PROFESSIONAL_SKILL_SET and float(value) != 0.0
            }
            aptitude = capability.get("aptitude_distribution", {})
            apt_mean = float(aptitude.get("mean", 100.0)) if isinstance(aptitude, Mapping) else 100.0
            cohort: dict[str, Any] = {
                "attribute_means": attr_means,
                "skill_means": skill_means,
                "professional_skill_means": professional_means,
                "aptitude_means": {
                    "physical_learning": apt_mean,
                    "tactical_learning": apt_mean,
                    "technical_learning": apt_mean,
                    "social_learning": apt_mean,
                    "academic_learning": apt_mean,
                },
                "age_distribution": {"mean": self._mercenary_age_mean(company, capability)},
                "skill_edu_banks": copy.deepcopy(capability.get("training_runtime", {}).get("skill_edu_banks", {})) if isinstance(capability.get("training_runtime"), Mapping) else {},
                "attribute_edu_banks": copy.deepcopy(capability.get("training_runtime", {}).get("attribute_edu_banks", {})) if isinstance(capability.get("training_runtime"), Mapping) else {},
                "verified_training_hours_per_person": float(capability.get("training_runtime", {}).get("verified_training_hours_per_person", 0.0)) if isinstance(capability.get("training_runtime"), Mapping) else 0.0,
                "verified_role_exposure_hours_per_person": float(capability.get("training_runtime", {}).get("verified_role_exposure_hours_per_person", 0.0)) if isinstance(capability.get("training_runtime"), Mapping) else 0.0,
                "last_training": copy.deepcopy(capability.get("training_runtime", {}).get("last_training", {})) if isinstance(capability.get("training_runtime"), Mapping) else {},
            }
            role_key = str(pool.get("role") or pool.get("troop_type") or "general_military")
            registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
            program_ref = resolve_program_ref(
                registry, role=role_key, training_ref=str(pool.get("training", "") or "")
            )
            pool_id = str(pool.get("pool_id") or pool.get("id") or "unknown_pool")
            evidence = f"mercenary_training:{mercenary_ref}:{pool_id}:{at}"
            review_end = CampaignTime.parse(str(at))
            review_start = review_end.add_days(-90 * max(1, int(occurrences)))
            company_location = str(company.get("location_ref", company.get("current_location", company.get("location", ""))) or "")
            instructor_contexts = instructor_contexts_for_program(
                self, registry=registry, training_rules=training_rules, program_ref=program_ref,
                trainee_skills=cohort_merged_skill_means(cohort),
                student_count=max(1, int(pool.get("count", 0) or 0)), location_ref=company_location,
                scheduled_hours=deliberate, window_start=str(review_start), window_end=str(review_end),
                evidence_ref=evidence, reserve_duty=True,
            )
            drill_access = program_facility_access(
                self, registry=registry, program_ref=program_ref, location_ref=company_location
            ) if company_location else None
            settle_cohort_program(
                cohort, registry=registry, program_ref=program_ref,
                deliberate_hours=deliberate, role_exposure_hours=exposure,
                training_rules=training_rules,
                facility_grade=str(cfg.get("facility_grade", "adequate")),
                equipment_grade=str(cfg.get("equipment_grade", "adequate")),
                recovery_grade=str(cfg.get("recovery_grade", "adequate")),
                evidence_ref=evidence, instructor_context_by_drill=instructor_contexts,
                drill_access=drill_access,
            )
            caps["attribute_values"] = [round(float(cohort["attribute_means"].get(name, attr_means.get(name, 0.0))), 3) for name in attr_order]
            caps["skill_values"] = [round(float(cohort["skill_means"].get(name, skill_means.get(name, 0.0))), 3) for name in skill_order]
            professional_after = cohort.get("professional_skill_means", {})
            if isinstance(professional_after, Mapping):
                sparse_professional = {
                    str(name): round(float(value), 3)
                    for name, value in professional_after.items()
                    if str(name) in PROFESSIONAL_SKILL_SET and float(value) != 0.0
                }
                if sparse_professional:
                    caps["professional_skill_values"] = sparse_professional
                else:
                    caps.pop("professional_skill_values", None)
            capability["training_runtime"] = {
                "last_review": at,
                "verified_training_hours_per_person": cohort["verified_training_hours_per_person"],
                "verified_role_exposure_hours_per_person": cohort["verified_role_exposure_hours_per_person"],
                "skill_edu_banks": cohort["skill_edu_banks"],
                "attribute_edu_banks": cohort["attribute_edu_banks"],
                "last_training": copy.deepcopy(cohort.get("last_training", {})),
                "program_ref": program_ref,
            }
            pool["capability"] = capability
            updated_pools.append(pool_id)
            total_personnel += max(0, int(pool.get("count", 0)))
        if not updated_pools:
            return
        familiarity_gain = max(0, int(cfg.get("doctrine_familiarity_gain_per_review", 0))) * max(0, int(occurrences))
        cap = max(0, int(cfg.get("doctrine_familiarity_cap", 100)))
        company["doctrine_familiarity"] = min(cap, max(0, int(company.get("doctrine_familiarity", 0))) + familiarity_gain)
        runtime = company.setdefault("training_runtime", {})
        runtime["completed_training_reviews"] = int(runtime.get("completed_training_reviews", 0)) + max(0, int(occurrences))
        runtime["last_review"] = at
        runtime["last_status_basis"] = status_key
        runtime["deliberate_hours_per_person"] = round(deliberate, 3)
        runtime["role_exposure_hours_per_person"] = round(exposure, 3)
        runtime["updated_pool_refs"] = updated_pools
        runtime["personnel_covered"] = total_personnel
        runtime["rule"] = "aggregate troop-pool capability advances under canonical diminishing-return training; no character or headcount is created"
        self.put(path, company)

    @staticmethod
    def _objective_role_bonus(role: str, objective_text: str) -> int:
        normalized = "missile_infantry" if role in {"missile_crossbow", "archer"} else role
        return LivingWorldSwordPlanner._objective_role_bonus(normalized, objective_text)

    def _formation_score(self, formation_ref: str, formation: Mapping[str, Any], objective_text: str, memory: dict[str, Any], reserved: set[str]) -> int:
        commander_ref = formation.get("commander_ref")
        if isinstance(commander_ref, str) and commander_ref:
            return super()._formation_score(formation_ref, formation, objective_text, memory, reserved)
        structure = build_formation_command_structure(formation, self._warfare_depth_rules())
        unit = structure.get("unit_command", {}) if isinstance(structure, Mapping) else {}
        if not isinstance(unit, Mapping) or int(unit.get("effective_billets_staffed", 0)) <= 0:
            return super()._formation_score(formation_ref, formation, objective_text, memory, reserved)
        if formation_ref in reserved:
            return -(10**9)
        base = LivingWorldSwordPlanner._formation_score(self, formation_ref, formation, objective_text, memory, reserved)
        hierarchy = structure.get("internal_hierarchy", [])
        internal = sum(max(0, int(row.get("count", 0))) for row in hierarchy if isinstance(row, Mapping)) if isinstance(hierarchy, list) else 0
        staffed = max(0, int(unit.get("effective_billets_staffed", 0)))
        # Routine support capability is already expressed by command, logistics,
        # medical, communications, supply and readiness mechanics. Do not add a
        # second flat headcount-derived support bonus here.
        return base + min(100, 20 + internal // 3 + 20 * staffed)

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
                "composition": self._formation_roles(formation),
                "dominant_role": self._formation_role(formation),
                "food_kg": max(0, int(logistics.get("food_kg", 0))),
                "fodder_kg": max(0, int(logistics.get("fodder_kg", 0))),
                "war_arrows": max(0, int(logistics.get("war_arrows", 0))),
                "war_bolts": max(0, int(logistics.get("war_bolts", 0))),
            }
        return snapshots

    def _advance_autonomous_state_operations(self, state: str, at: str) -> None:
        """Stage threat-response formations through real domestic route hops.

        State review owns peacetime response posture, not hostile invasion.  It may
        move a committed formation toward a known threat through land the state can
        lawfully use, consuming carried supply or an exact convoy. Once the next hop
        is foreign-controlled or the relation is already at war, the interstate war
        owner takes over offensive chronology so the same formation cannot receive
        two autonomous march steps in one review window.
        """
        op_index = self.read("state/operations/index.json")
        operations = op_index.get("operations", {}) if isinstance(op_index, Mapping) else {}
        if not isinstance(operations, Mapping):
            return
        territory = self.read("state/territory/control.json")
        sites = territory.get("sites", {}) if isinstance(territory, Mapping) else {}
        state_doc = self.read(f"state/states/{state}.json")
        diplomacy = state_doc.get("diplomacy", {}) if isinstance(state_doc, Mapping) else {}
        owner_ref = f"state_{state}"

        for operation_ref, path in sorted(operations.items()):
            if not isinstance(operation_ref, str) or not operation_ref.startswith(f"operation_auto_{state}_") or not isinstance(path, str):
                continue
            operation = copy.deepcopy(self.read(path))
            if str(operation.get("status", "")) not in {"planned", "mobilizing", "active"}:
                continue
            target = operation.get("target_location_ref")
            if not isinstance(target, str) or not target:
                continue
            target_site = sites.get(target, {}) if isinstance(sites, Mapping) else {}
            target_controller = str(target_site.get("controller", "")) if isinstance(target_site, Mapping) else ""
            target_relation = diplomacy.get(target_controller, {}) if isinstance(diplomacy, Mapping) and target_controller else {}
            if isinstance(target_relation, Mapping) and str(target_relation.get("status", "")) == "war":
                operation["movement_review"] = {"at": at, "status": "interstate_war_owner_active", "target_location_ref": target}
                self.put(path, operation)
                continue

            rows: list[dict[str, Any]] = []
            for formation_ref in [str(x) for x in operation.get("formation_refs", []) if isinstance(x, str) and x]:
                try:
                    _fp, formation = self._load_formation(formation_ref)
                except ValueError:
                    rows.append({"formation_ref": formation_ref, "status": "missing"})
                    continue
                origin = str(formation.get("location_ref", ""))
                if not origin:
                    rows.append({"formation_ref": formation_ref, "status": "no_location"})
                    continue
                if origin == target:
                    rows.append({"formation_ref": formation_ref, "status": "at_target", "location_ref": origin})
                    continue
                try:
                    next_hop, edge_hours = self._formation_route_next(origin, target, formation=None, at=at)
                except (ValueError, PermissionError):
                    rows.append({"formation_ref": formation_ref, "status": "no_route", "location_ref": origin})
                    continue
                next_site = sites.get(next_hop, {}) if isinstance(sites, Mapping) else {}
                next_controller = str(next_site.get("controller", "")) if isinstance(next_site, Mapping) else ""
                if next_controller and next_controller != owner_ref:
                    rows.append({
                        "formation_ref": formation_ref,
                        "status": "staged_at_frontier",
                        "location_ref": origin,
                        "blocked_foreign_next_hop": next_hop,
                        "foreign_controller_ref": next_controller,
                    })
                    continue
                try:
                    if hasattr(self, "_validate_formation_transit"):
                        self._validate_formation_transit(formation, next_hop, at)
                except PermissionError:
                    rows.append({"formation_ref": formation_ref, "status": "transit_denied", "location_ref": origin, "next_hop": next_hop})
                    continue

                supply = self._autonomy_sustain_march(formation_ref, next_hop, at, operation, "state_operation")
                ready = str(supply.get("status", "")) in {"not_needed", "sufficient", "convoy_received"}
                if ready:
                    move = self._autonomy_move_formation_step(formation_ref, next_hop, at)
                    rows.append({"formation_ref": formation_ref, "next_hop": next_hop, "edge_hours": edge_hours, "supply": dict(supply), "move": dict(move), "status": str(move.get("status", "moved"))})
                else:
                    rows.append({"formation_ref": formation_ref, "next_hop": next_hop, "edge_hours": edge_hours, "supply": dict(supply), "status": str(supply.get("status", "supply_blocked"))})

            current_locations: list[str] = []
            for formation_ref in [str(x) for x in operation.get("formation_refs", []) if isinstance(x, str) and x]:
                try:
                    _fp, live = self._load_formation(formation_ref)
                except ValueError:
                    continue
                loc = live.get("location_ref")
                if isinstance(loc, str) and loc:
                    current_locations.append(loc)
            operation["movement_review"] = {
                "at": at,
                "target_location_ref": target,
                "formation_results": rows,
                "rule": "autonomous threat response moves only through lawful route hops with physical supply; hostile advance is owned by interstate war chronology",
            }
            if current_locations and len(set(current_locations)) == 1:
                operation["location_ref"] = current_locations[0]
            operation["updated_at"] = at
            self.put(path, operation)

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
            self._advance_autonomous_state_operations(state, at)
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
        for op_ref, op_path in sorted(operations.items()):
            if not isinstance(op_ref, str) or not isinstance(op_path, str):
                continue
            operation = self.read(op_path)
            if str(operation.get("status", "")) not in {"planned", "mobilizing", "active", "engaged", "occupied"}:
                continue
            refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}
            if bool(operation.get("autonomous")) and op_ref.startswith(own_prefix):
                own.append((op_ref, op_path))
            else:
                foreign_used.update(refs)
        used = set(foreign_used)
        for _op_ref, op_path in own:
            operation = copy.deepcopy(self.read(op_path))
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
                    "selected_compositions": {
                        ref: self._formation_roles(self._load_formation(ref)[1]) for ref in selected
                    },
                    "rule": "persistent formations remain separate manpower/casualty owners; operation coordinates combined arms only",
                }
                supply = operation.setdefault("supply_plan", {})
                if isinstance(supply, MutableMapping):
                    supply["formation_logistics_at_review"] = self._operation_supply_snapshot(selected)
                operation["updated_at"] = at
                self.put(op_path, operation)
            used.update(selected)
        self._advance_autonomous_state_operations(state, at)

    def _autonomy_house(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_house(host, occurrences, at)
        try:
            house = self.read(self.owner_path(str(host["owner_ref"])))
        except (KeyError, ValueError, FileNotFoundError):
            return
        force_ref = house.get("military_force_ref") if isinstance(house, Mapping) else None
        if isinstance(force_ref, str) and force_ref:
            self._ensure_force_command_structures(force_ref)

    def _autonomy_polity(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_polity(host, occurrences, at)
        try:
            polity = self.read(self.owner_path(str(host["owner_ref"])))
        except (KeyError, ValueError, FileNotFoundError):
            return
        if not isinstance(polity, Mapping):
            return
        for key in ("military_force_ref", "force_ref"):
            force_ref = polity.get(key)
            if isinstance(force_ref, str) and force_ref:
                self._ensure_force_command_structures(force_ref)
                return

    def _autonomy_faction(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_faction(host, occurrences, at)
        try:
            faction = self.read(self.owner_path(str(host["owner_ref"])))
        except (KeyError, ValueError, FileNotFoundError):
            return
        if not isinstance(faction, Mapping):
            return
        force_ref = faction.get("force_ref")
        if isinstance(force_ref, str) and force_ref:
            self._ensure_force_command_structures(force_ref)

    def _settle_mercenary_reconstitution(self, mercenary_ref: str, occurrences: int, at: str) -> None:
        """Conserved quarterly reconstitution through the exact local mercenary market.

        Reservations remain bodies owned by ``merc.local.pool`` until their training
        matures. Completion transfers those same bodies into the company; treasury
        pays the registered recruitment/equipment package. No deficit creates people.
        """
        path = self.owner_path(mercenary_ref)
        company0 = self.read(path)
        if not isinstance(company0, Mapping) or str(company0.get("schema", "")) not in {"mercenary", "mercenary-company", "regional-mercenary-company"}:
            return
        company = copy.deepcopy(company0)
        count_key = "headcount" if "headcount" in company else "count"
        current = max(0, int(company.get(count_key, 0)))
        establishment = max(current, int(company.get("establishment_strength", current)))
        company["establishment_strength"] = establishment
        if current >= establishment or str(company.get("status", "")).lower() in {"destroyed", "dissolved"}:
            self.put(path, company); return
        local_path = self.owner_path("merc.local.pool")
        local = copy.deepcopy(self.read(local_path))
        reservations = local.setdefault("reconstitution_reservations", {})
        if not isinstance(reservations, dict):
            raise ValueError("mercenary local reconstitution reservations are invalid")
        now = CampaignTime.parse(at)
        # Mature already-reserved people first. They leave the local pool only here.
        matured = []
        for rid, row in sorted(reservations.items()):
            if not isinstance(row, Mapping) or str(row.get("company_ref")) != mercenary_ref:
                continue
            ready_at = row.get("ready_at")
            if isinstance(ready_at, str) and CampaignTime.parse(ready_at) <= now:
                matured.append((rid, dict(row)))
        for rid, row in matured:
            amount = min(max(0, int(row.get("count", 0))), max(0, establishment - current))
            if amount <= 0:
                reservations.pop(rid, None); continue
            loc = str(row.get("location_ref", ""))
            regional = local.setdefault("regional_distribution", {})
            if int(regional.get(loc, 0)) < amount or int(local.get("armed_total", 0)) < amount:
                raise ValueError("mercenary reconstitution reservation lost conserved local bodies")
            regional[loc] = int(regional.get(loc, 0)) - amount
            local["armed_total"] = int(local.get("armed_total", 0)) - amount
            local["reserved_reconstitution_total"] = max(0, int(local.get("reserved_reconstitution_total", 0)) - amount)
            breakdown = row.get("class_breakdown", {}) if isinstance(row.get("class_breakdown"), Mapping) else {}
            for cls in local.get("classes", []):
                if isinstance(cls, dict):
                    cls["count"] = max(0, int(cls.get("count", 0)) - int(breakdown.get(str(cls.get("role")), 0)))
            if count_key == "headcount" and isinstance(company.get("troop_pools"), list) and company["troop_pools"]:
                pools = company["troop_pools"]; weights = [max(0, int(p.get("count", 0))) for p in pools]; totalw = max(1, sum(weights)); raw = [amount*w/totalw for w in weights]; adds=[int(math.floor(x)) for x in raw]
                for i in sorted(range(len(raw)), key=lambda i: (-(raw[i]-adds[i]), i))[:amount-sum(adds)]: adds[i]+=1
                for pool, add in zip(pools, adds):
                    if add <= 0: continue
                    pool["count"] = int(pool.get("count", 0)) + add
                    if isinstance(pool.get("condition"), dict): pool["condition"]["fit"] = int(pool["condition"].get("fit", 0)) + add
                    cap0 = pool.get("capability")
                    if isinstance(cap0, Mapping):
                        cap = copy.deepcopy(cap0)
                        ex = cap.setdefault("experience_distribution", {})
                        ex["reconstituted"] = int(ex.get("reconstituted", 0)) + add
                        pool["capability"] = cap
            company[count_key] = current + amount; current += amount
            reservations.pop(rid, None)
        # Reserve a bounded next intake from the company's own market region.
        deficit = max(0, establishment - current)
        already = sum(max(0, int(row.get("count", 0))) for row in reservations.values() if isinstance(row, Mapping) and str(row.get("company_ref")) == mercenary_ref)
        deficit = max(0, deficit - already)
        if deficit > 0:
            loc = str(company.get("home_location_ref") or company.get("current_location_ref") or "")
            locations = self.read("game/data/world/locations.json").get("locations", [])
            by_ref = {str(x.get("ref")): x for x in locations if isinstance(x, Mapping)}
            row = by_ref.get(loc, {})
            region = str(row.get("region_ref") or (loc if row.get("kind") == "region" else ""))
            regional = local.setdefault("regional_distribution", {}); short = local.setdefault("short_notice_available_by_location", {})
            # Fall back to any market node only if the home region has no local pool.
            source_loc = region if int(short.get(region, 0)) > 0 else next((k for k,v in sorted(short.items()) if int(v) > 0), "")
            available = max(0, int(short.get(source_loc, 0)))
            rate = 0.03 if count_key == "headcount" else 0.05
            cap = max(25, int(math.ceil(establishment * rate))) * max(1, int(occurrences))
            reserve = min(deficit, available, cap)
            unit_cost = 22 if count_key == "headcount" else 16
            treasury = max(0, int(company.get("treasury_silver", 0)))
            reserve = min(reserve, treasury // unit_cost)
            if reserve > 0 and source_loc:
                # Reserve from local classes without removing bodies until graduation.
                class_breakdown: dict[str, int] = {}
                remaining = reserve
                preferred = ["veteran_band", "caravan_guard", "reconnaissance", "river_crew", "seasonal_contract"]
                class_rows = {str(x.get("role")): x for x in local.get("classes", []) if isinstance(x, dict)}
                for role in preferred:
                    if remaining <= 0: break
                    cls = class_rows.get(role); n = min(remaining, max(0, int(cls.get("count", 0))) if cls else 0)
                    if n: class_breakdown[role] = n; remaining -= n
                reserve -= remaining
                if reserve > 0:
                    rid = f"reconstitution:{mercenary_ref}:{at}"
                    ready = now.add_seconds(90 * 86400)
                    reservations[rid] = {"company_ref":mercenary_ref,"count":reserve,"location_ref":source_loc,"reserved_at":at,"ready_at":str(ready),"class_breakdown":class_breakdown,"paid_silver":reserve*unit_cost,"rule":"reservation remains owned/counting in local mercenary pool until completion"}
                    local["reserved_reconstitution_total"] = int(local.get("reserved_reconstitution_total", 0)) + reserve
                    short[source_loc] = max(0, int(short.get(source_loc, 0)) - reserve)
                    local["short_notice_available_total"] = max(0, int(local.get("short_notice_available_total", 0)) - reserve)
                    company["treasury_silver"] = treasury - reserve*unit_cost
                    local["cash_silver"] = int(local.get("cash_silver", 0)) + reserve*unit_cost
        company.setdefault("reconstitution_runtime", {})["last_review"] = at
        company["reconstitution_runtime"]["establishment_strength"] = establishment
        company["reconstitution_runtime"]["current_strength"] = current
        company["reconstitution_runtime"]["rule"] = "recover/recruit from finite local mercenary pool, pay for training/equipment, then transfer conserved bodies after 90 days"
        self.put(local_path, local); self.put(path, company)

    def _autonomy_mercenary(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_mercenary(host, occurrences, at)
        ref = str(host["owner_ref"])
        # Aggregate/accounting-only mercenary companies are labor-market records,
        # not persistent tactical formations. Their contracts and conserved bodies
        # still settle through the common mercenary resolver, but they must not pay
        # the cost of constructing command structures, training ledgers, and
        # reconstitution machinery that no live combat owner consumes.
        try:
            doc = self.read(self.owner_path(ref))
        except (KeyError, ValueError, FileNotFoundError):
            return
        if bool(doc.get("accounting_only")):
            if hasattr(self, "_aggregate_idle_regional_mercenary"):
                try:
                    self._aggregate_idle_regional_mercenary(ref, at)
                except (KeyError, ValueError, FileNotFoundError):
                    pass
            return
        try:
            self._settle_mercenary_reconstitution(ref, occurrences, at)
            self._settle_mercenary_training(ref, occurrences, at)
            self._ensure_mercenary_command_structure(ref)
            if hasattr(self, "_aggregate_idle_regional_mercenary"):
                self._aggregate_idle_regional_mercenary(ref, at)
        except (KeyError, ValueError, FileNotFoundError):
            return

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        super()._run_due_host(host, due_text)

    def _settle_attachment_casualties(self, before: Mapping[str, int], evidence_ref: str) -> None:
        cfg = self._warfare_depth_rules().get("command_casualty_exposure", {})
        if not isinstance(cfg, Mapping):
            return
        minimum = max(0.0, min(1.0, float(cfg.get("minimum_fighting_loss_fraction_before_aggregate_attachment_loss", 0.02))))
        for formation_ref, old_n in before.items():
            if old_n <= 0:
                continue
            try:
                formation_path, formation0 = self._load_formation(formation_ref)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            formation = copy.deepcopy(formation0)
            new_n = max(0, int(formation.get("personnel", 0)))
            fighting_losses = max(0, old_n - new_n)
            loss_fraction = fighting_losses / max(1, old_n)
            if fighting_losses <= 0 or loss_fraction < minimum:
                continue
            source_ref = str(formation.get("command_attachment_source_force_ref") or formation.get("owner_force_ref") or "")
            if not source_ref:
                continue
            try:
                force_path = self.owner_path(source_ref)
                force = copy.deepcopy(self.read(force_path))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            unit_roles = _clean_role_counts(formation.get("attached_unit_command_by_role", {}))
            losses_by_role: dict[str, int] = {}
            for role, count in unit_roles.items():
                exposure = max(0.0, float(cfg.get("unit_command", 0.2)))
                exact = count * loss_fraction * exposure
                lost = min(count, int(math.floor(exact)) + int(stable_fraction(evidence_ref, formation_ref, role, "unit") < exact - math.floor(exact)))
                if lost:
                    losses_by_role[role] = losses_by_role.get(role, 0) + lost
                    unit_roles[role] = count - lost
            for role, count in sorted(losses_by_role.items()):
                self._kill_external_role_allocation(force, formation_ref=formation_ref, role=role, losses=count, evidence_ref=evidence_ref)
            if not losses_by_role:
                continue
            formation["attached_unit_command_by_role"] = {k: v for k, v in unit_roles.items() if v > 0}
            formation["attached_support_by_role"] = {}
            formation.setdefault("command_attachment_casualty_history", []).append({
                "at": str(self.read("state/runtime.json").get("world_time", "")),
                "evidence_ref": evidence_ref,
                "fighting_losses": fighting_losses,
                "fighting_loss_fraction": round(loss_fraction, 6),
                "attachment_losses_by_role": losses_by_role,
                "rule": "separate conserved external personnel casualties; no automatic same-battle replacement",
            })
            formation["command_attachment_casualty_history"] = formation["command_attachment_casualty_history"][-16:]
            formation.pop("command_structure", None)
            self.put(force_path, force)
            self.put(formation_path, formation)

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "formation_dissolve":
            ref = payload.get("formation_ref")
            if isinstance(ref, str) and ref:
                self._release_formation_external_personnel(ref)

        battle_before: dict[str, int] = {}
        if command.command_type == "battle_resolve":
            for key in ("attacker_formation_refs", "defender_formation_refs"):
                for ref in payload.get(key, []) if isinstance(payload.get(key), list) else []:
                    if not isinstance(ref, str) or not ref:
                        continue
                    try:
                        battle_before[ref] = max(0, int(self._load_formation(ref)[1].get("personnel", 0)))
                    except (KeyError, ValueError, FileNotFoundError):
                        continue

        result = super()._dispatch(command, payload)
        if battle_before:
            evidence = str(result.get("battle_ref") or result.get("event_ref") or getattr(command, "request_id", "battle")) if isinstance(result, Mapping) else str(getattr(command, "request_id", "battle"))
            self._settle_attachment_casualties(battle_before, evidence)

        refs: set[str] = set()
        if command.command_type == "formation_create":
            ref = result.get("formation_ref") if isinstance(result, Mapping) else None
            if isinstance(ref, str) and ref:
                refs.add(ref)
        elif command.command_type in {"formation_reconstitute", "formation_move", "command_assign", "command_transfer"}:
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
            refs.update(battle_before)
        touched_groups: set[str] = set()
        group_index = self.read_optional("state/cmd/command-groups/index.json") or {}
        primary_groups = group_index.get("primary_formation_group", {}) if isinstance(group_index, Mapping) else {}
        for ref in sorted(refs):
            try:
                # Player-owned formation actions must not silently consume extra
                # reserve manpower beyond their declared command. Projection is
                # refreshed immediately; autonomous House/state/faction reviews
                # perform lawful establishment staffing later.
                self._ensure_formation_command_structure(ref)
                group_ref = primary_groups.get(ref) if isinstance(primary_groups, Mapping) else None
                if isinstance(group_ref, str):
                    touched_groups.add(group_ref)
            except (KeyError, ValueError, FileNotFoundError):
                continue
        if hasattr(self, "_refresh_command_group_organizational_chain"):
            review_at = str(result.get("world_time") or self.read("state/runtime.json").get("world_time")) if isinstance(result, Mapping) else str(self.read("state/runtime.json").get("world_time"))
            for group_ref in sorted(touched_groups):
                try:
                    self._refresh_command_group_organizational_chain(group_ref, review_at)
                except (KeyError, ValueError, FileNotFoundError):
                    continue
        return result

    def _validate_invariants(self, overlay: Any, paths: Any) -> None:
        """Validate exact force arithmetic while accounting for materialized assigned personnel."""
        class _CurrentForceValidationView:
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
                    if isinstance(assignment, Mapping) and str(assignment.get("formation_ref", ""))
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

        super()._validate_invariants(_CurrentForceValidationView(overlay), paths)
        for path in paths:
            if not str(path).startswith("state/forces/") or overlay.read_optional_bytes(path) is None:
                continue
            force = overlay.read_json(path)
            if not isinstance(force, Mapping):
                continue
            available = sum(max(0, int(v)) for v in force.get("available_by_role", {}).values()) if isinstance(force.get("available_by_role"), Mapping) else 0
            fighting = sum(int(v.get("personnel", 0)) if isinstance(v, Mapping) else int(v) for v in force.get("allocated_to_formations", {}).values()) if isinstance(force.get("allocated_to_formations"), Mapping) else 0
            external = 0
            raw_external = force.get("external_personnel_allocations", {})
            if isinstance(raw_external, Mapping):
                external = sum(max(0, int(count)) for roles in raw_external.values() if isinstance(roles, Mapping) for count in roles.values())
            assignments = force.get("materialized_assignments", {})
            assigned_refs = {
                str(person_ref)
                for person_ref, assignment in assignments.items()
                if isinstance(assignment, Mapping) and str(assignment.get("formation_ref", ""))
            } if isinstance(assignments, Mapping) else set()
            people = force.get("materialized_people", {})
            materialized = sum(
                int(value.get("personnel", 1)) if isinstance(value, Mapping) else int(value)
                for person_ref, value in people.items()
                if str(person_ref) not in assigned_refs
            ) if isinstance(people, Mapping) else 0
            if available + fighting + external + materialized != int(force.get("headcount", -1)):
                raise ValueError("force conservation including external personnel failed")
            validate_cohort_ledger(force)


__all__ = ["WarfareDepthMixin", "build_formation_command_structure", "build_mercenary_command_structure"]
