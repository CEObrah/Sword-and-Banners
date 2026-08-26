"""Persistent operational battle day/contact lifecycle.

This domain turns an operational battlefield into a sequence of bounded contact
periods separated by real chronology.  It owns daylight/night posture and
bounded camp refit.  Exact casualties still belong to ``battle_resolve`` and
sector geometry/redeployment still belongs to ``battlefield``.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any, Sequence

from sword_runtime.environment import daylight_window, is_daylight, next_daylight_transition, next_sunrise_after
from sword_runtime.fatigue import RULES_PATH as FATIGUE_RULES_PATH, settle_formation_idle_fatigue
from sword_runtime.military_supply import active_mount_count
from sword_runtime.sim.calendar import CampaignTime

RULES_PATH = "game/data/mechanics/battle-lifecycle.json"


def _integer_proportional(total: int, weights: Mapping[str, int]) -> dict[str, int]:
    total = max(0, int(total))
    clean = {str(k): max(0, int(v)) for k, v in weights.items() if max(0, int(v)) > 0}
    if total <= 0 or not clean:
        return {key: 0 for key in clean}
    total = min(total, sum(clean.values()))
    weight_total = sum(clean.values())
    out: dict[str, int] = {}
    remainders: list[tuple[float, str]] = []
    assigned = 0
    for key in sorted(clean):
        exact = total * clean[key] / max(1, weight_total)
        base = min(clean[key], int(math.floor(exact)))
        out[key] = base
        assigned += base
        remainders.append((exact - base, key))
    for _fraction, key in sorted(remainders, key=lambda row: (-row[0], row[1])):
        if assigned >= total:
            break
        if out[key] < clean[key]:
            out[key] += 1
            assigned += 1
    if assigned < total:
        for key in sorted(clean):
            if assigned >= total:
                break
            add = min(clean[key] - out[key], total - assigned)
            out[key] += add
            assigned += add
    return out


class BattleLifecycleMixin:
    """Day/night/contact helpers consumed by the operational battlefield owner."""

    def _battle_lifecycle_rules(self) -> Mapping[str, Any]:
        rules = self.read(RULES_PATH)
        if not isinstance(rules, Mapping) or rules.get("schema") != "sword-battle-lifecycle":
            raise ValueError("battle lifecycle mechanics are invalid")
        return rules

    def _battle_lifecycle_initial_cycle(self, at: CampaignTime) -> dict[str, Any]:
        daylight = is_daylight(at)
        sunrise, sunset = daylight_window(at)
        return {
            "battle_day": 1 if daylight else 0,
            "posture": "day_operations" if daylight else "night_camp",
            "last_transition_at": str(at),
            "last_dawn_at": str(sunrise) if daylight else None,
            "last_dusk_at": None if at < sunset else str(sunset),
            "camped_formation_refs": [],
            "last_dawn_refit": [],
            "transition_tail": [],
        }

    def _battle_lifecycle_next_boundary(self, current: CampaignTime, target: CampaignTime) -> tuple[CampaignTime | None, dict[str, Any] | None]:
        if target <= current:
            return None, None
        due, kind = next_daylight_transition(current)
        if current < due <= target:
            return due, {"kind": f"battlefield_{kind}"}
        return None, None

    def _battle_lifecycle_contact_plan(
        self,
        battlefield: Mapping[str, Any],
        *,
        attacker_refs: Sequence[str],
        start: CampaignTime,
        base_battle_hours: float,
        operation_ref: str | None = None,
        battlefield_ref: str | None = None,
    ) -> dict[str, Any]:
        """Bound one operational battle command to a causal contact period."""
        rules = self._battle_lifecycle_rules()
        contact = rules.get("operational_contact")
        if not isinstance(contact, Mapping):
            raise ValueError("operational contact lifecycle mechanics are invalid")
        minimum_seconds = max(60, int(round(float(contact.get("minimum_organized_contact_minutes", 30)) * 60)))
        daylight = is_daylight(start)
        sunrise, sunset = daylight_window(start)
        assignments = battlefield.get("assignments")
        if not isinstance(assignments, Mapping):
            raise ValueError("operational battlefield assignments are invalid")

        boundary_kind: str | None = None
        if daylight:
            maximum_hours = max(0.25, float(contact.get("maximum_daylight_contact_hours", 2.0)))
            hard_end = min(start.add_seconds(max(1, int(round(maximum_hours * 3600)))), sunset)
            available_seconds = max(0, start.seconds_until(hard_end))
            if available_seconds < minimum_seconds:
                raise ValueError("operational battle contact rejected: too little daylight remains for a new organized contact period")
            light_mode = "daylight"
        else:
            aggressive = {str(value) for value in contact.get("night_aggressive_orders", ["attack", "breakthrough"]) if isinstance(value, str)}
            attacker_orders = []
            for formation_ref in attacker_refs:
                assignment = assignments.get(str(formation_ref))
                if not isinstance(assignment, Mapping):
                    raise ValueError("night contact attacker lacks an operational assignment")
                attacker_orders.append(str(assignment.get("order", "hold")))
            if not attacker_orders or any(order not in aggressive for order in attacker_orders):
                raise ValueError("organized night contact requires every attacking formation to carry a saved aggressive battlefield order")
            maximum_hours = max(0.25, float(contact.get("maximum_night_contact_hours", 1.0)))
            dawn = next_sunrise_after(start)
            hard_end = min(start.add_seconds(max(1, int(round(maximum_hours * 3600)))), dawn)
            available_seconds = max(0, start.seconds_until(hard_end))
            if available_seconds < minimum_seconds:
                raise ValueError("operational battle contact rejected: too little night remains before dawn for a new organized contact period")
            light_mode = "night"

        # The old battle-duration estimate remains a physical upper bound, but an
        # operational contact never consumes more than this one bounded period.
        base_seconds = max(1, int(round(max(0.001, float(base_battle_hours)) * 3600)))
        planned_end = min(hard_end, start.add_seconds(base_seconds))

        # Do not stride across a saved operational boundary. A reinforcement leg,
        # order, report, pressure threshold, dawn or dusk can therefore become real
        # before the next contact command is admitted.
        boundary_detail: dict[str, Any] | None = None
        if hasattr(self, "_battlefield_next_boundary_time"):
            if operation_ref and battlefield_ref:
                boundary, detail = self._battlefield_next_boundary_time(
                    start, planned_end, operation_ref=operation_ref, battlefield_ref=battlefield_ref
                )
            else:
                boundary, detail = self._battlefield_next_boundary_time(start, planned_end)
            if boundary is not None and start < boundary < planned_end:
                planned_end = boundary
                boundary_detail = copy.deepcopy(dict(detail or {}))
                boundary_kind = str(boundary_detail.get("kind", "operational_boundary"))

        # The central chronology authority can also expose already-registered
        # military/autonomy host boundaries. This is intentionally filtered by
        # battle mechanics so person/household maintenance does not fragment a
        # two-hour contact into meaningless scheduler ticks.
        scheduler_kinds = {
            str(kind)
            for kind in contact.get("scheduler_intervention_host_kinds", [])
            if isinstance(kind, str) and kind
        }
        if scheduler_kinds and hasattr(self, "_next_scheduler_event_boundary"):
            scheduler_boundary, scheduler_detail = self._next_scheduler_event_boundary(
                start, planned_end, host_kinds=scheduler_kinds
            )
            if scheduler_boundary is not None and start < scheduler_boundary < planned_end:
                planned_end = scheduler_boundary
                boundary_detail = copy.deepcopy(dict(scheduler_detail or {}))
                host_kind = str(boundary_detail.get("host_kind", "autonomy"))
                boundary_kind = f"scheduler:{host_kind}"

        duration_seconds = max(1, start.seconds_until(planned_end))
        reference_hours = max(0.25, float(contact.get("casualty_reference_hours", 6.0)))
        return {
            "operational_contact": True,
            "light_mode": light_mode,
            "started_at": str(start),
            "planned_end_at": str(planned_end),
            "duration_seconds": duration_seconds,
            "duration_hours": duration_seconds / 3600.0,
            "casualty_reference_hours": reference_hours,
            "casualty_duration_factor": min(1.0, duration_seconds / max(1.0, reference_hours * 3600.0)),
            "truncated_by_boundary": boundary_kind,
            "truncated_boundary_detail": boundary_detail,
            "sunrise_at": str(sunrise),
            "sunset_at": str(sunset),
        }

    def _battle_lifecycle_begin_contact(
        self,
        *,
        operation_ref: str,
        battlefield_ref: str,
        sector_ref: str,
        contact_ref: str,
        started_at: CampaignTime,
        ends_at: CampaignTime,
        light_mode: str,
        attacker_refs: Sequence[str],
        defender_refs: Sequence[str],
    ) -> dict[str, Any]:
        """Persist the exact contact window while shared chronology advances."""
        if ends_at <= started_at:
            raise ValueError("battle contact window must advance time")
        path, operation = self._battlefield_operation(operation_ref)
        battlefield = (operation.get("battlefields") or {}).get(battlefield_ref)
        if not isinstance(battlefield, dict) or battlefield.get("status") != "active":
            raise ValueError("operational battlefield is not active")
        if sector_ref not in (battlefield.get("sectors") or {}):
            raise ValueError("battle contact sector is invalid")
        existing = battlefield.get("active_contact")
        if isinstance(existing, Mapping):
            existing_end_text = existing.get("ends_at")
            if isinstance(existing_end_text, str) and CampaignTime.parse(existing_end_text) > started_at:
                raise ValueError("operational battlefield already has an overlapping active contact")
        row = {
            "contact_ref": str(contact_ref),
            "sector_ref": str(sector_ref),
            "started_at": str(started_at),
            "ends_at": str(ends_at),
            "light_mode": str(light_mode),
            "attacker_formation_refs": sorted(str(ref) for ref in attacker_refs),
            "defender_formation_refs": sorted(str(ref) for ref in defender_refs),
        }
        battlefield["active_contact"] = row
        battlefield["updated_at"] = str(started_at)
        self.put(path, operation)
        return copy.deepcopy(row)

    def _battle_lifecycle_clear_contact(
        self,
        *,
        operation_ref: str,
        battlefield_ref: str,
        contact_ref: str,
        at: CampaignTime,
    ) -> bool:
        """Clear a completed contact marker without erasing its bounded trace."""
        path, operation = self._battlefield_operation(operation_ref)
        battlefield = (operation.get("battlefields") or {}).get(battlefield_ref)
        if not isinstance(battlefield, dict):
            return False
        active = battlefield.get("active_contact")
        if not isinstance(active, Mapping) or active.get("contact_ref") != contact_ref:
            return False
        end_text = active.get("ends_at")
        if not isinstance(end_text, str) or CampaignTime.parse(end_text) > at:
            return False
        completed = copy.deepcopy(dict(active))
        completed["completed_at"] = str(at)
        battlefield["last_contact"] = completed
        battlefield.pop("active_contact", None)
        battlefield["updated_at"] = str(at)
        self.put(path, operation)
        return True

    @staticmethod
    def _battle_lifecycle_spare_key(role: str) -> str:
        return "crossbow_role_sets" if "crossbow" in str(role).lower() else "standard_role_sets"

    def _battle_lifecycle_dawn_refit_formation(self, formation_ref: str, *, at: CampaignTime) -> dict[str, Any]:
        path, raw = self._load_formation(formation_ref)
        formation = copy.deepcopy(raw)
        if not isinstance(formation, dict) or int(formation.get("personnel", 0) or 0) <= 0 or str(formation.get("status", "")) == "destroyed":
            return {"formation_ref": formation_ref, "status": "no_surviving_formation"}

        fatigue_rules = self.read(FATIGUE_RULES_PATH)
        fatigue = settle_formation_idle_fatigue(formation, current=at, rules=fatigue_rules)

        composition = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
        shields = self._shield_units(formation) if hasattr(self, "_shield_units") else {}
        armor = self._armor_units(formation) if hasattr(self, "_armor_units") else {}
        shield_conditions = formation.setdefault("shield_condition_by_role", {})
        armor_conditions = formation.setdefault("armor_condition_by_role", {})
        spare_sets = formation.setdefault("spare_outfitting_sets", {})
        if not isinstance(spare_sets, dict):
            raise ValueError(f"formation spare outfitting state is invalid: {formation_ref}")

        needs_by_key: dict[str, dict[str, int]] = {}
        role_needs: dict[str, tuple[int, int]] = {}
        for role, count_raw in composition.items():
            count = max(0, int(count_raw or 0))
            if count <= 0:
                continue
            use_shield = bool(self._combat_role_uses_shield(str(role))) if hasattr(self, "_combat_role_uses_shield") else False
            use_armor = bool(self._combat_role_uses_armor(str(role))) if hasattr(self, "_combat_role_uses_armor") else False
            shield_missing = max(0, count - max(0, int(shields.get(role, 0) or 0))) if use_shield else 0
            armor_missing = max(0, count - max(0, int(armor.get(role, 0) or 0))) if use_armor else 0
            need_sets = max(shield_missing, armor_missing)
            if need_sets <= 0:
                continue
            role_needs[str(role)] = (shield_missing, armor_missing)
            key = self._battle_lifecycle_spare_key(str(role))
            needs_by_key.setdefault(key, {})[str(role)] = need_sets

        sets_used: dict[str, int] = {}
        shield_replacements: dict[str, int] = {}
        armor_replacements: dict[str, int] = {}
        for key, role_weights in sorted(needs_by_key.items()):
            available = max(0, int(spare_sets.get(key, 0) or 0))
            total_need = sum(role_weights.values())
            allocations = _integer_proportional(min(available, total_need), role_weights)
            used_total = sum(allocations.values())
            if used_total <= 0:
                continue
            spare_sets[key] = available - used_total
            sets_used[key] = used_total
            for role, allocated in allocations.items():
                shield_missing, armor_missing = role_needs[role]
                add_shield = min(shield_missing, allocated)
                add_armor = min(armor_missing, allocated)
                if add_shield:
                    old = max(0, int(shields.get(role, 0) or 0))
                    prior = max(0.0, min(100.0, float(shield_conditions.get(role, 100.0) or 0.0)))
                    shields[role] = old + add_shield
                    shield_conditions[role] = round((old * prior + add_shield * 100.0) / max(1, old + add_shield), 3)
                    shield_replacements[role] = add_shield
                if add_armor:
                    old = max(0, int(armor.get(role, 0) or 0))
                    prior = max(0.0, min(100.0, float(armor_conditions.get(role, 100.0) or 0.0)))
                    armor[role] = old + add_armor
                    armor_conditions[role] = round((old * prior + add_armor * 100.0) / max(1, old + add_armor), 3)
                    armor_replacements[role] = add_armor

        if hasattr(self, "_set_shield_units"):
            self._set_shield_units(formation, shields)
        if hasattr(self, "_set_armor_units"):
            self._set_armor_units(formation, armor)

        mount_required = 0
        if hasattr(self, "_combat_prepare_formation") and hasattr(self, "_combat_cohort_snapshot"):
            # Use current conserved cohorts after casualties, never pre-battle establishment.
            _cpath, current_formation, force = self._combat_prepare_formation(formation_ref)
            # Preserve the refit/fatigue changes staged above while using the force
            # owner only to derive current mounted-role requirements.
            rows = self._combat_cohort_snapshot(formation, force)
            # Cohort rows exclude already-materialized officer/standout bodies.
            # Scale each role's physical mount ratio back to the full conserved
            # formation composition so named slots do not make a cavalry hundred
            # appear to need fewer horses at dawn.
            row_counts: dict[str, int] = {}
            row_mounts: dict[str, float] = {}
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                role = str(row.get("role", ""))
                count = max(0, int(row.get("count", 0) or 0))
                if not role or count <= 0:
                    continue
                row_counts[role] = row_counts.get(role, 0) + count
                row_mounts[role] = row_mounts.get(role, 0.0) + max(0.0, float(row.get("mount_required_units", 0) or 0))
            mount_required = 0
            for role, full_count_raw in composition.items():
                full_count = max(0, int(full_count_raw or 0))
                represented = row_counts.get(str(role), 0)
                if full_count <= 0 or represented <= 0:
                    continue
                ratio = row_mounts.get(str(role), 0.0) / represented
                mount_required += max(0, int(math.ceil(full_count * ratio)))
        active_mounts = active_mount_count(formation)
        logistics = formation.setdefault("logistics", {})
        if not isinstance(logistics, dict):
            raise ValueError(f"formation logistics are invalid: {formation_ref}")
        remount_available = max(0, int(logistics.get("remount_horses", 0) or 0))
        remount_issued = min(max(0, mount_required - active_mounts), remount_available)
        if remount_issued:
            mounts = formation.setdefault("mounts", {})
            if not isinstance(mounts, dict):
                mounts = {}
                formation["mounts"] = mounts
            mounts["horse"] = max(0, int(mounts.get("horse", 0) or 0)) + remount_issued
            logistics["remount_horses"] = remount_available - remount_issued

        self.put(path, formation)
        return {
            "formation_ref": formation_ref,
            "status": "refit",
            "fatigue_recovery_points": int(fatigue.get("recovery_points", 0) or 0),
            "outfitting_sets_consumed": sets_used,
            "shield_replacements_by_role": shield_replacements,
            "armor_replacements_by_role": armor_replacements,
            "remount_horses_issued": remount_issued,
            "ammunition_available": {
                resource: max(0, int(logistics.get(resource, 0) or 0))
                for resource in ("war_arrows", "war_bolts")
                if resource in logistics
            },
        }

    def _battle_lifecycle_transition(self, battlefield: dict[str, Any], *, at: CampaignTime) -> dict[str, Any] | None:
        """Apply an exact dawn/dusk posture transition at one scheduler boundary."""
        sunrise, sunset = daylight_window(at)
        if at != sunrise and at != sunset:
            return None
        cycle = battlefield.setdefault("day_cycle", self._battle_lifecycle_initial_cycle(at))
        if not isinstance(cycle, dict):
            raise ValueError("battlefield day_cycle is invalid")
        assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
        if at == sunset:
            if str(cycle.get("posture")) == "night_camp" and cycle.get("last_dusk_at") == str(at):
                return None
            camped = sorted(
                str(ref)
                for ref, assignment in assignments.items()
                if isinstance(ref, str)
                and isinstance(assignment, Mapping)
                and assignment.get("status") != "redeploying"
                and isinstance(assignment.get("sector_ref"), str)
            )
            cycle.update({
                "posture": "night_camp",
                "last_transition_at": str(at),
                "last_dusk_at": str(at),
                "camped_formation_refs": camped,
            })
            row = {"kind": "dusk_camp", "at": str(at), "battle_day": int(cycle.get("battle_day", 0) or 0), "camped_formation_refs": camped}
        else:
            if str(cycle.get("posture")) == "day_operations" and cycle.get("last_dawn_at") == str(at):
                return None
            overnight_camped = {
                str(ref) for ref in cycle.get("camped_formation_refs", []) if isinstance(ref, str)
            }
            cycle["battle_day"] = max(1, int(cycle.get("battle_day", 0) or 0) + 1)
            cycle.update({
                "posture": "day_operations",
                "last_transition_at": str(at),
                "last_dawn_at": str(at),
                "camped_formation_refs": [],
            })
            refits: list[dict[str, Any]] = []
            rules = self._battle_lifecycle_rules().get("night_camp")
            if isinstance(rules, Mapping) and rules.get("dawn_refit") is True:
                for formation_ref in sorted(overnight_camped):
                    assignment = assignments.get(formation_ref)
                    if not isinstance(assignment, Mapping):
                        continue
                    if assignment.get("status") == "redeploying" or not isinstance(assignment.get("sector_ref"), str):
                        continue
                    try:
                        refits.append(self._battle_lifecycle_dawn_refit_formation(formation_ref, at=at))
                    except (FileNotFoundError, KeyError, ValueError):
                        # Invalid exact ownership should not be silently repaired here.
                        raise
            cycle["last_dawn_refit"] = refits
            row = {
                "kind": "dawn_muster",
                "at": str(at),
                "battle_day": int(cycle["battle_day"]),
                "camped_overnight_formation_refs": sorted(overnight_camped),
                "formation_refits": refits,
            }
        tail = cycle.setdefault("transition_tail", [])
        if isinstance(tail, list):
            tail.append(copy.deepcopy(row))
            del tail[:-16]
        battlefield["updated_at"] = str(at)
        return row

    def _battle_lifecycle_sector_available_formations(self, battlefield: Mapping[str, Any], sector_ref: str) -> list[str]:
        assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
        out: list[str] = []
        for formation_ref, assignment in sorted(assignments.items()):
            if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
                continue
            if assignment.get("status") == "redeploying" or assignment.get("sector_ref") != sector_ref:
                continue
            try:
                _path, formation = self._load_formation(formation_ref)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            if int(formation.get("personnel", 0) or 0) > 0 and str(formation.get("status", "")) != "destroyed":
                out.append(formation_ref)
        return out

    def _battle_lifecycle_contact_status(
        self,
        *,
        operation_ref: str,
        battlefield_ref: str,
        sector_ref: str,
        attacker_refs: Sequence[str],
        defender_refs: Sequence[str],
        event_id: str,
    ) -> dict[str, Any]:
        _path, _operation, battlefield = self._battlefield_contact_reconciliation_owner(
            operation_ref=operation_ref,
            battlefield_ref=battlefield_ref,
            sector_ref=sector_ref,
            attacker_refs=attacker_refs,
            defender_refs=defender_refs,
            event_id=event_id,
        )
        assignments = battlefield.get("assignments", {})
        attacker_side = next(iter({assignments[ref]["side_ref"] for ref in attacker_refs}))
        defender_side = next(iter({assignments[ref]["side_ref"] for ref in defender_refs}))
        sector = battlefield.get("sectors", {}).get(sector_ref, {})
        pressure = sector.get("pressure_milli", {}) if isinstance(sector, Mapping) and isinstance(sector.get("pressure_milli"), Mapping) else {}
        _critical, collapse, _reset = self._battlefield_pressure_thresholds()
        local_collapsed_sides = sorted(side for side in (attacker_side, defender_side) if int(pressure.get(side, 0) or 0) >= collapse)

        available = self._battle_lifecycle_sector_available_formations(battlefield, sector_ref)
        available_by_side = {
            side: [ref for ref in available if isinstance(assignments.get(ref), Mapping) and assignments[ref].get("side_ref") == side]
            for side in (attacker_side, defender_side)
        }
        all_live_by_side = {attacker_side: [], defender_side: []}
        for formation_ref, assignment in assignments.items():
            if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping) or assignment.get("side_ref") not in all_live_by_side:
                continue
            try:
                _fpath, formation = self._load_formation(formation_ref)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            if int(formation.get("personnel", 0) or 0) > 0 and str(formation.get("status", "")) != "destroyed":
                all_live_by_side[str(assignment["side_ref"])].append(formation_ref)
        battle_continues = all(bool(all_live_by_side[side]) for side in all_live_by_side)
        return {
            "battle_day_number": int((battlefield.get("day_cycle") or {}).get("battle_day", 0) or 0) if isinstance(battlefield.get("day_cycle"), Mapping) else 0,
            "battlefield_posture": str((battlefield.get("day_cycle") or {}).get("posture", "day_operations")) if isinstance(battlefield.get("day_cycle"), Mapping) else "day_operations",
            "local_collapsed_side_refs": local_collapsed_sides,
            "contact_decisive": bool(local_collapsed_sides or not available_by_side[attacker_side] or not available_by_side[defender_side]),
            "battle_continues": bool(battle_continues),
            "sector_available_formation_refs": available,
            "sector_available_by_side": available_by_side,
            "battlefield_live_by_side": {side: sorted(refs) for side, refs in all_live_by_side.items()},
        }


__all__ = ["BattleLifecycleMixin", "RULES_PATH"]
