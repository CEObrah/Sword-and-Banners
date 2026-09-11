"""Deterministic 100-person battlefield sustainment rotations.

A formation's logistics ledger is the conserved physical stock carried with the
formation. During battle, missile ammunition is split into a carried frontline
load and an HQ/baggage reserve. Reserve ammunition reaches shooters only through
a bounded forward-carrier detail when the line is stable enough or through a
100-person command element rotating rearward to service itself and return.

A rearward rotation can also replace battle-broken protective equipment from
complete spare outfitting sets, draw remount horses already carried in the field
HQ reserve, and gain bounded rest. These are temporary duties only; they never
materialize new formations or soldiers and never create supply.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

RULES_PATH = "game/data/mechanics/battlefield-sustainment.json"


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _integer_proportional(total: int, weights: Mapping[str, int]) -> dict[str, int]:
    """Allocate an integer total proportionally with deterministic remainders."""
    total = max(0, int(total))
    clean = {str(k): max(0, int(v)) for k, v in weights.items() if int(v) > 0}
    weight_total = sum(clean.values())
    if total <= 0 or weight_total <= 0:
        return {key: 0 for key in clean}
    target = min(total, weight_total)
    raw = {key: target * weight / weight_total for key, weight in clean.items()}
    out = {key: min(clean[key], int(math.floor(value))) for key, value in raw.items()}
    remainder = target - sum(out.values())
    order = sorted(clean, key=lambda key: (-(raw[key] - math.floor(raw[key])), key))
    while remainder > 0:
        progressed = False
        for key in order:
            if out[key] >= clean[key]:
                continue
            out[key] += 1
            remainder -= 1
            progressed = True
            if remainder <= 0:
                break
        if not progressed:
            break
    return out


def _ammo_profiles(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    targets: dict[str, int] = {}
    personnel: dict[str, int] = {}
    role_capacity: dict[str, dict[str, int]] = {}
    for row in rows:
        resource = str(row.get("ammunition_resource") or "")
        role = str(row.get("role") or "")
        count = max(0, int(row.get("count", 0) or 0))
        carried = max(0, int(row.get("carried_ammunition", 0) or 0))
        if not resource or not role or count <= 0 or carried <= 0:
            continue
        targets[resource] = targets.get(resource, 0) + count * carried
        personnel[resource] = personnel.get(resource, 0) + count
        by_role = role_capacity.setdefault(resource, {})
        by_role[role] = by_role.get(role, 0) + count * carried
    return targets, personnel, role_capacity


def initialize_battle_sustainment(
    formation: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    initial_shields: Mapping[str, int],
    initial_armor: Mapping[str, int],
) -> dict[str, Any]:
    """Create transient battle-HQ state without duplicating physical stock."""
    logistics = formation.get("logistics", {}) if isinstance(formation.get("logistics"), Mapping) else {}
    targets, resource_personnel, role_capacity = _ammo_profiles(rows)
    frontline: dict[str, int] = {}
    hq: dict[str, int] = {}
    for resource, target in targets.items():
        total = max(0, int(logistics.get(resource, 0) or 0))
        frontline[resource] = min(total, target)
        hq[resource] = max(0, total - frontline[resource])
    personnel = max(0, int(formation.get("personnel", 0) or 0))
    spares = formation.get("spare_outfitting_sets", {}) if isinstance(formation.get("spare_outfitting_sets"), Mapping) else {}
    remounts = max(0, int(logistics.get("remount_horses", 0) or 0))
    return {
        "command_scale_personnel": 100,
        "hundreds_total": int(math.ceil(personnel / 100.0)) if personnel else 0,
        "frontline_ammunition": dict(frontline),
        "hq_ammunition": dict(hq),
        "initial_frontline_ammunition": dict(frontline),
        "initial_hq_ammunition": dict(hq),
        "frontline_load_target": targets,
        "resource_personnel": resource_personnel,
        "resource_role_capacity": role_capacity,
        "initial_shields_by_role": {str(k): max(0, int(v)) for k, v in initial_shields.items()},
        "initial_armor_by_role": {str(k): max(0, int(v)) for k, v in initial_armor.items()},
        "spare_outfitting_available": {str(k): max(0, int(v)) for k, v in spares.items()},
        "spare_outfitting_consumed": {},
        "remount_horses_available": remounts,
        "remount_horses_issued": 0,
        "rest_person_hours": 0.0,
        "pending_absence_by_role": {},
    }


def consume_frontline_ammunition(state: MutableMapping[str, Any], plan: Mapping[str, Any]) -> None:
    frontline = state.setdefault("frontline_ammunition", {})
    if not isinstance(frontline, MutableMapping):
        raise ValueError("battle sustainment frontline ammunition is invalid")
    consumed = plan.get("consumed_by_resource", {}) if isinstance(plan.get("consumed_by_resource"), Mapping) else {}
    for resource, amount in consumed.items():
        resource = str(resource)
        used = max(0, int(amount or 0))
        current = max(0, int(frontline.get(resource, 0) or 0))
        if used > current:
            raise ValueError(f"battle ammunition overdraw: {resource} used {used}, frontline held {current}")
        frontline[resource] = current - used


def _scale_row(row: Mapping[str, Any], new_count: int) -> dict[str, Any]:
    out = dict(row)
    old = max(0, int(row.get("count", 0) or 0))
    new_count = max(0, min(old, int(new_count)))
    out["count"] = new_count
    if old <= 0 or new_count == old:
        return out
    ratio = new_count / old
    for field in ("shield_units", "armor_units", "mounted_units", "mount_required_units"):
        if field in out:
            out[field] = round(max(0.0, _num(out.get(field))) * ratio, 6)
    return out


def apply_role_absence(rows: Sequence[Mapping[str, Any]], absence_by_role: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Reduce phase participation for 100-person groups servicing at HQ.

    Multiple cohort rows of one role are reduced proportionally so a rotation does
    not arbitrarily remove only the strongest or weakest cohort.
    """
    grouped: dict[str, list[int]] = {}
    out = [dict(row) for row in rows]
    for idx, row in enumerate(rows):
        grouped.setdefault(str(row.get("role") or ""), []).append(idx)
    for role, indices in grouped.items():
        absence = max(0, int(absence_by_role.get(role, 0) or 0))
        total = sum(max(0, int(rows[i].get("count", 0) or 0)) for i in indices)
        if absence <= 0 or total <= 0:
            continue
        keep_total = max(0, total - min(total, absence))
        weights = {str(i): max(0, int(rows[i].get("count", 0) or 0)) for i in indices}
        kept = _integer_proportional(keep_total, weights)
        for i in indices:
            out[i] = _scale_row(rows[i], kept.get(str(i), 0))
    return [row for row in out if int(row.get("count", 0) or 0) > 0]


def _command_control_milli(formation: Mapping[str, Any], command_effects: Mapping[str, Any]) -> int:
    training = _clamp(_num(formation.get("training_progress", 20), 20), 0, 160)
    cohesion = _clamp(_num(formation.get("cohesion", 50), 50), 0, 160)
    organizational = 0.45 * training + 0.55 * cohesion
    internal = max(0.0, _num(command_effects.get("internal_100_command_score", 0)))
    coverage = _clamp(_num(command_effects.get("internal_100_person_lite_coverage", 0)), 0, 1)
    acting = max(0.0, _num(command_effects.get("acting_command_score", 0)))
    local = organizational if internal <= 0 else organizational * (1.0 - coverage) + internal * coverage
    if acting > 0:
        local = local * 0.72 + acting * 0.28
    staffing = _clamp(_num(command_effects.get("unit_staffing_ratio", 1.0), 1.0), 0.35, 1.0)
    normalized = _clamp(local / 110.0, 0.2, 1.25) * staffing
    return int(round(_clamp(normalized, 0.15, 1.25) * 1000))


def _role_profiles(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    profiles: dict[str, dict[str, int]] = {}
    for row in rows:
        role = str(row.get("role") or "")
        count = max(0, int(row.get("count", 0) or 0))
        if not role or count <= 0:
            continue
        p = profiles.setdefault(role, {"count": 0, "mounted_required": 0})
        p["count"] += count
        p["mounted_required"] += max(0, int(round(_num(row.get("mount_required_units", 0)))))
    return profiles


def _spare_key_for_role(role: str) -> str:
    return "crossbow_role_sets" if "crossbow" in role.lower() else "standard_role_sets"


def plan_hundred_sustainment_rotation(
    state: MutableMapping[str, Any],
    formation: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    command_effects: Mapping[str, Any],
    current_shields: Mapping[str, int],
    current_armor: Mapping[str, int],
    current_mounts: int,
    breached_sectors: int,
    next_phase_hours: float,
    rules: Mapping[str, Any],
) -> dict[str, Any]:
    """Plan and settle one between-phase 100-person HQ rotation.

    The function moves only stock already present in the transient HQ reserve.
    Its output tells the battle resolver which damaged equipment/remounts become
    serviceable and how many role-equivalent bodies are absent while doing so.
    """
    personnel = max(0, int(formation.get("personnel", 0) or 0))
    if personnel <= 0 or next_phase_hours <= 0:
        return {"duty": "sustainment_rotation", "rotation_personnel": 0, "reason": "no_following_contact_phase"}

    hundred = max(1, int(rules.get("command_scale_personnel", 100) or 100))
    profiles = _role_profiles(rows)
    if not profiles:
        return {"duty": "sustainment_rotation", "rotation_personnel": 0, "reason": "no_eligible_personnel"}

    control_milli = _command_control_milli(formation, command_effects)
    control = control_milli / 1000.0
    base_fraction = _clamp(_num(rules.get("base_rotation_fraction", 0.10), 0.10), 0.02, 0.40)
    control_fraction = max(0.0, _num(rules.get("control_rotation_fraction", 0.20), 0.20)) * _clamp(control, 0, 1.25)
    breach_penalty = _clamp(_num(rules.get("breach_rotation_penalty_per_sector", 0.18), 0.18), 0, 0.35) * max(0, int(breached_sectors))
    duty = formation.get("current_unit_duty", {}) if isinstance(formation.get("current_unit_duty"), Mapping) else {}
    reserve_bonus = _clamp(_num(rules.get("reserve_relief_rotation_bonus", 0.08), 0.08), 0, 0.20) if str(duty.get("duty_id", duty.get("duty", ""))) == "reserve_relief" else 0.0
    fraction = _clamp(base_fraction + control_fraction + reserve_bonus - breach_penalty, 0.05, _num(rules.get("maximum_rotation_fraction", 0.36), 0.36))
    capacity_people = max(hundred, int(math.floor(personnel * fraction / hundred)) * hundred) if personnel >= hundred else personnel
    minimum_front = int(math.ceil(personnel * _clamp(_num(rules.get("minimum_frontline_fraction", 0.55), 0.55), 0.25, 0.90)))
    capacity_people = min(capacity_people, max(0, personnel - minimum_front))
    initial_shields = state.get("initial_shields_by_role", {}) if isinstance(state.get("initial_shields_by_role"), Mapping) else {}
    initial_armor = state.get("initial_armor_by_role", {}) if isinstance(state.get("initial_armor_by_role"), Mapping) else {}
    role_need: dict[str, int] = {role: 0 for role in profiles}
    role_priority: dict[str, float] = {role: 0.0 for role in profiles}
    needs = {"ammunition": False, "outfitting": False, "remount": False, "fatigue": False}

    frontline = state.get("frontline_ammunition", {}) if isinstance(state.get("frontline_ammunition"), Mapping) else {}
    hq = state.get("hq_ammunition", {}) if isinstance(state.get("hq_ammunition"), Mapping) else {}
    targets = state.get("frontline_load_target", {}) if isinstance(state.get("frontline_load_target"), Mapping) else {}
    role_capacity = state.get("resource_role_capacity", {}) if isinstance(state.get("resource_role_capacity"), Mapping) else {}
    for resource, target_raw in targets.items():
        target = max(0, int(target_raw or 0))
        missing = max(0, target - max(0, int(frontline.get(resource, 0) or 0)))
        movable = min(missing, max(0, int(hq.get(resource, 0) or 0)))
        capacities = role_capacity.get(resource, {}) if isinstance(role_capacity.get(resource), Mapping) else {}
        total_capacity = sum(max(0, int(v)) for v in capacities.values())
        if movable <= 0 or total_capacity <= 0:
            continue
        needs["ammunition"] = True
        for role, cap in capacities.items():
            role = str(role)
            count = profiles.get(role, {}).get("count", 0)
            if count <= 0:
                continue
            cap = max(0, int(cap))
            average_carried = cap / max(1, count)
            share = movable * cap / max(1, total_capacity)
            people_needed = min(count, int(math.ceil(share / max(1.0, average_carried))))
            role_need[role] = max(role_need.get(role, 0), people_needed)
            role_priority[role] = max(role_priority.get(role, 0.0), 4.0 + movable / max(1, target))

    for role, p in profiles.items():
        shield_short = max(0, int(initial_shields.get(role, 0) or 0) - max(0, int(current_shields.get(role, 0) or 0)))
        armor_short = max(0, int(initial_armor.get(role, 0) or 0) - max(0, int(current_armor.get(role, 0) or 0)))
        shortage = max(shield_short, armor_short)
        spare_key = _spare_key_for_role(role)
        spares = state.get("spare_outfitting_available", {}) if isinstance(state.get("spare_outfitting_available"), Mapping) else {}
        if shortage > 0 and max(0, int(spares.get(spare_key, 0) or 0)) > 0:
            needs["outfitting"] = True
            role_need[role] = max(role_need.get(role, 0), min(p["count"], shortage))
            role_priority[role] = max(role_priority.get(role, 0.0), 3.0 + shortage / max(1, p["count"]))

    mounted_roles = {role: p["mounted_required"] for role, p in profiles.items() if p.get("mounted_required", 0) > 0}
    mount_target = sum(mounted_roles.values())
    mount_deficit = max(0, mount_target - max(0, int(current_mounts)))
    remounts_available = max(0, int(state.get("remount_horses_available", 0) or 0))
    if mount_deficit > 0 and remounts_available > 0 and mounted_roles:
        needs["remount"] = True
        allocation = _integer_proportional(min(mount_deficit, remounts_available), mounted_roles)
        for role, amount in allocation.items():
            role_need[role] = max(role_need.get(role, 0), min(profiles[role]["count"], amount))
            role_priority[role] = max(role_priority.get(role, 0.0), 3.5 + mount_deficit / max(1, mount_target))

    fatigue = max(0.0, _num(formation.get("fatigue", 0), 0))
    fatigue_trigger = _clamp(_num(rules.get("fatigue_rotation_trigger", 55), 55), 0, 95)
    if fatigue >= fatigue_trigger and int(breached_sectors) <= int(rules.get("fatigue_rotation_max_breached_sectors", 1) or 1):
        needs["fatigue"] = True
        desired = max(hundred, int(math.ceil(personnel * _clamp(_num(rules.get("fatigue_rotation_fraction", 0.12), 0.12), 0.05, 0.30) / hundred)) * hundred)
        allocation = _integer_proportional(min(desired, personnel), {role: p["count"] for role, p in profiles.items()})
        for role, amount in allocation.items():
            role_need[role] = max(role_need.get(role, 0), amount)
            role_priority[role] = max(role_priority.get(role, 0.0), 1.0 + fatigue / 100.0)

    if not any(needs.values()):
        return {"duty": "sustainment_rotation", "rotation_personnel": 0, "reason": "no_physical_resupply_or_recovery_need", "command_control_milli": control_milli}

    # Ammunition alone does not justify marching an entire hundred to the baggage
    # if its commander has a secure rear route. Detail a few conserved bodies from
    # each affected hundred as temporary carriers, then return them to their parent
    # element. Equipment repair, remounting, and meaningful rest still require the
    # full-hundred rotation below.
    forward = rules.get("forward_ammunition", {}) if isinstance(rules.get("forward_ammunition"), Mapping) else {}
    forward_allowed = bool(
        forward.get("enabled") is True
        and needs["ammunition"]
        and not needs["outfitting"]
        and not needs["remount"]
        and not needs["fatigue"]
        and control_milli >= int(forward.get("minimum_command_control_milli", 650) or 650)
        and int(breached_sectors) <= int(forward.get("maximum_breached_sectors", 0) or 0)
    )
    if forward_allowed:
        carriers_per_hundred = max(1, int(forward.get("carriers_per_hundred", 8) or 8))
        load_multiplier = max(1.0, _num(forward.get("load_multiplier_per_carrier", 4.0), 4.0))
        carrier_by_role: dict[str, int] = {}
        for role, p in profiles.items():
            if role_need.get(role, 0) <= 0:
                continue
            blocks = max(1, int(math.ceil(p["count"] / max(1, hundred))))
            carrier_by_role[role] = min(p["count"], blocks * carriers_per_hundred)

        forward_moved: dict[str, int] = {}
        frontline_mut = state.setdefault("frontline_ammunition", {})
        hq_mut = state.setdefault("hq_ammunition", {})
        for resource, target_raw in targets.items():
            target = max(0, int(target_raw or 0))
            current = max(0, int(frontline_mut.get(resource, 0) or 0))
            missing = max(0, target - current)
            available = max(0, int(hq_mut.get(resource, 0) or 0))
            capacities = role_capacity.get(resource, {}) if isinstance(role_capacity.get(resource), Mapping) else {}
            delivery_capacity = 0
            for role, carriers in carrier_by_role.items():
                role_count = profiles[role]["count"]
                full_capacity = max(0, int(capacities.get(role, 0) or 0))
                if role_count > 0 and full_capacity > 0:
                    average_load = full_capacity / max(1, role_count)
                    delivery_capacity += int(math.floor(carriers * average_load * load_multiplier))
            moved = min(missing, available, delivery_capacity)
            if moved > 0:
                frontline_mut[resource] = current + moved
                hq_mut[resource] = available - moved
                forward_moved[str(resource)] = moved

        if forward_moved:
            turnaround = min(
                float(next_phase_hours),
                max(0.05, _num(forward.get("turnaround_hours", 0.30), 0.30)),
            )
            absence_fraction = _clamp(turnaround / max(0.001, float(next_phase_hours)), 0.0, 1.0)
            absence_by_role = {
                role: min(carriers, max(1, int(round(carriers * absence_fraction))))
                for role, carriers in carrier_by_role.items()
                if carriers > 0
            }
            state["pending_absence_by_role"] = absence_by_role
            result = {
                "duty": "sustainment_rotation",
                "mode": "forward_carrier_delivery",
                "command_scale_personnel": hundred,
                "command_control_milli": control_milli,
                "rotation_capacity_personnel": capacity_people,
                "rotation_personnel": 0,
                "carrier_personnel": sum(carrier_by_role.values()),
                "carrier_by_role": carrier_by_role,
                "effective_absence_next_phase_by_role": absence_by_role,
                "turnaround_hours": round(turnaround, 4),
                "rejoin_mode": "carriers_return_to_parent_hundred_after_delivery",
                "needs": needs,
                "ammunition_moved_from_hq": forward_moved,
                "shield_replacements_by_role": {},
                "armor_replacements_by_role": {},
                "outfitting_sets_consumed": {},
                "remount_horses_issued": 0,
                "rest_person_hours": 0.0,
                "frontline_ammunition_after": {str(k): max(0, int(v)) for k, v in frontline_mut.items()},
                "hq_ammunition_after": {str(k): max(0, int(v)) for k, v in hq_mut.items()},
            }
            return result

    if capacity_people <= 0:
        return {"duty": "sustainment_rotation", "rotation_personnel": 0, "reason": "line_cannot_release_a_hundred", "command_control_milli": control_milli}

    # A 100-person commander moves a whole command element for routine rearward
    # service. The final undersized element may be smaller only when the formation
    # itself has fewer than 100 people remaining.
    rotation_by_role: dict[str, int] = {}
    remaining = capacity_people
    for role in sorted(profiles, key=lambda r: (-role_priority.get(r, 0.0), r)):
        need = max(0, int(role_need.get(role, 0)))
        if need <= 0 or remaining <= 0:
            continue
        role_count = profiles[role]["count"]
        block = min(role_count, max(hundred, int(math.ceil(need / hundred)) * hundred))
        take = min(block, remaining)
        if take < hundred and personnel >= hundred:
            continue
        rotation_by_role[role] = take
        remaining -= take
    rotation_people = sum(rotation_by_role.values())
    if rotation_people <= 0:
        return {"duty": "sustainment_rotation", "rotation_personnel": 0, "reason": "command_capacity_below_required_hundred", "command_control_milli": control_milli}

    ammunition_moved: dict[str, int] = {}
    frontline_mut = state.setdefault("frontline_ammunition", {})
    hq_mut = state.setdefault("hq_ammunition", {})
    for resource, target_raw in targets.items():
        target = max(0, int(target_raw or 0))
        current = max(0, int(frontline_mut.get(resource, 0) or 0))
        missing = max(0, target - current)
        available = max(0, int(hq_mut.get(resource, 0) or 0))
        capacities = role_capacity.get(resource, {}) if isinstance(role_capacity.get(resource), Mapping) else {}
        service_capacity = 0
        for role, rotated in rotation_by_role.items():
            role_total = profiles[role]["count"]
            full_capacity = max(0, int(capacities.get(role, 0) or 0))
            if role_total > 0 and full_capacity > 0:
                service_capacity += int(math.floor(full_capacity * rotated / role_total))
        moved = min(missing, available, service_capacity)
        if moved > 0:
            frontline_mut[resource] = current + moved
            hq_mut[resource] = available - moved
            ammunition_moved[str(resource)] = moved

    spare_available = state.setdefault("spare_outfitting_available", {})
    spare_consumed = state.setdefault("spare_outfitting_consumed", {})
    shield_replacements: dict[str, int] = {}
    armor_replacements: dict[str, int] = {}
    outfitting_used: dict[str, int] = {}
    for role, rotated in rotation_by_role.items():
        shield_short = max(0, int(initial_shields.get(role, 0) or 0) - max(0, int(current_shields.get(role, 0) or 0)))
        armor_short = max(0, int(initial_armor.get(role, 0) or 0) - max(0, int(current_armor.get(role, 0) or 0)))
        need_sets = min(rotated, max(shield_short, armor_short))
        if need_sets <= 0:
            continue
        key = _spare_key_for_role(role)
        available = max(0, int(spare_available.get(key, 0) or 0))
        used = min(available, need_sets)
        if used <= 0:
            continue
        spare_available[key] = available - used
        spare_consumed[key] = max(0, int(spare_consumed.get(key, 0) or 0)) + used
        outfitting_used[key] = outfitting_used.get(key, 0) + used
        shield_replacements[role] = min(shield_short, used)
        armor_replacements[role] = min(armor_short, used)

    selected_mounted = sum(min(rotation_by_role.get(role, 0), profiles[role]["mounted_required"]) for role in mounted_roles)
    remounts_issued = min(mount_deficit, remounts_available, selected_mounted)
    if remounts_issued > 0:
        state["remount_horses_available"] = remounts_available - remounts_issued
        state["remount_horses_issued"] = max(0, int(state.get("remount_horses_issued", 0) or 0)) + remounts_issued

    service = rules.get("turnaround_hours", {}) if isinstance(rules.get("turnaround_hours"), Mapping) else {}
    service_hours = 0.0
    if ammunition_moved:
        service_hours = max(service_hours, max(0.0, _num(service.get("ammunition", 0.45), 0.45)))
    if outfitting_used:
        service_hours = max(service_hours, max(0.0, _num(service.get("outfitting", 0.70), 0.70)))
    if remounts_issued:
        service_hours = max(service_hours, max(0.0, _num(service.get("remount", 0.90), 0.90)))
    if needs["fatigue"]:
        service_hours = max(service_hours, max(0.0, _num(service.get("fatigue_recovery", 1.10), 1.10)))
    service_hours = min(float(next_phase_hours), max(0.10, service_hours))

    # Under heavy pressure, commanders return serviced hundreds as soon as they
    # are useful. With a stable line and high fatigue, they may deliberately keep
    # them rearward for a longer recovery window.
    hold_for_rest = bool(needs["fatigue"] and int(breached_sectors) == 0 and control_milli >= int(rules.get("hold_for_rest_min_control_milli", 700) or 700))
    if hold_for_rest:
        service_hours = min(float(next_phase_hours), max(service_hours, float(next_phase_hours) * _clamp(_num(rules.get("rest_hold_phase_fraction", 0.55), 0.55), 0.25, 0.85)))
        rejoin_mode = "held_rearward_then_rejoin_when_commander_calls"
    else:
        rejoin_mode = "rejoin_after_service"
    absence_fraction = _clamp(service_hours / max(0.001, float(next_phase_hours)), 0.0, 1.0)
    absence_by_role = {role: min(rotated, max(1, int(round(rotated * absence_fraction)))) for role, rotated in rotation_by_role.items() if rotated > 0}
    state["pending_absence_by_role"] = absence_by_role
    rest_credit_factor = _clamp(_num(rules.get("rearward_rest_credit_fraction", 0.60), 0.60), 0.0, 1.0)
    rest_person_hours = rotation_people * service_hours * rest_credit_factor
    state["rest_person_hours"] = float(state.get("rest_person_hours", 0.0) or 0.0) + rest_person_hours

    result = {
        "duty": "sustainment_rotation",
        "mode": "hundred_rotation",
        "command_scale_personnel": hundred,
        "command_control_milli": control_milli,
        "rotation_capacity_personnel": capacity_people,
        "rotation_personnel": rotation_people,
        "carrier_personnel": 0,
        "carrier_by_role": {},
        "rotation_by_role": rotation_by_role,
        "effective_absence_next_phase_by_role": absence_by_role,
        "turnaround_hours": round(service_hours, 4),
        "rejoin_mode": rejoin_mode,
        "needs": needs,
        "ammunition_moved_from_hq": ammunition_moved,
        "shield_replacements_by_role": shield_replacements,
        "armor_replacements_by_role": armor_replacements,
        "outfitting_sets_consumed": outfitting_used,
        "remount_horses_issued": remounts_issued,
        "rest_person_hours": round(rest_person_hours, 3),
        "frontline_ammunition_after": {str(k): max(0, int(v)) for k, v in frontline_mut.items()},
        "hq_ammunition_after": {str(k): max(0, int(v)) for k, v in hq_mut.items()},
    }
    return result


def fatigue_gain_after_rotations(
    base_gain: int,
    *,
    personnel: int,
    battle_hours: float,
    rest_person_hours: float,
    rules: Mapping[str, Any],
) -> int:
    base = max(0, int(base_gain))
    if base <= 0 or personnel <= 0 or battle_hours <= 0 or rest_person_hours <= 0:
        return base
    share = _clamp(float(rest_person_hours) / max(1.0, float(personnel) * float(battle_hours)), 0.0, 1.0)
    max_reduction_fraction = _clamp(_num(rules.get("maximum_battle_fatigue_reduction_fraction", 0.55), 0.55), 0.0, 0.85)
    reduction = int(round(base * min(max_reduction_fraction, share)))
    minimum = max(0, int(rules.get("minimum_battle_fatigue_gain", 5) or 5))
    return max(minimum, base - reduction)


__all__ = [
    "RULES_PATH",
    "initialize_battle_sustainment",
    "consume_frontline_ammunition",
    "apply_role_absence",
    "plan_hundred_sustainment_rotation",
    "fatigue_gain_after_rotations",
]
