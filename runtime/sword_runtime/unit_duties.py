"""Deterministic standing Unit duty assignment.

A duty is a temporary mission for an existing direct Unit, never a troop type.
The parent command selects eligible Units; the Unit's existing 1,000/500/100
chain handles routine internal allocation. This module is intentionally generic
so player and NPC armies use the same suitability calculation.
"""
from __future__ import annotations

from itertools import permutations
from typing import Any, Mapping, Sequence

from sword_runtime.stat_access import merged_skill_map


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _person_skill(person: Mapping[str, Any] | None, key: str) -> float:
    if not isinstance(person, Mapping):
        return 0.0
    skills = merged_skill_map(person)
    if key in skills:
        return _number(skills.get(key))
    stats = person.get("stats") if isinstance(person.get("stats"), Mapping) else {}
    attrs = stats.get("attributes") if isinstance(stats.get("attributes"), Mapping) else None
    if not isinstance(attrs, Mapping):
        attrs = person.get("attributes") if isinstance(person.get("attributes"), Mapping) else {}
    return _number(attrs.get(key))


def _leadership_score(
    commander: Mapping[str, Any] | None,
    weights: Mapping[str, Any],
) -> float:
    """Score the Unit's one top commander for duty suitability."""
    if not isinstance(commander, Mapping):
        return 0.0
    return sum(_person_skill(commander, str(key)) * _number(weight) for key, weight in weights.items())

def _composition_affinity(
    formation: Mapping[str, Any],
    duty: Mapping[str, Any],
    role_tags: Mapping[str, Any],
) -> float:
    composition = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
    total = max(1, sum(max(0, int(_number(v))) for v in composition.values()))
    affinity = duty.get("role_affinity") if isinstance(duty.get("role_affinity"), Mapping) else {}
    value = 0.0
    for role, raw_count in composition.items():
        count = max(0, int(_number(raw_count)))
        if count <= 0:
            continue
        tags = role_tags.get(str(role), []) if isinstance(role_tags, Mapping) else []
        role_score = _number(affinity.get(str(role)))
        for tag in tags if isinstance(tags, list) else []:
            role_score += _number(affinity.get(str(tag)))
        value += (count / total) * role_score
    return value


def unit_duty_suitability(
    formation: Mapping[str, Any],
    commander: Mapping[str, Any] | None,
    duty: Mapping[str, Any],
    role_tags: Mapping[str, Any],
) -> float:
    """Return deterministic suitability without creating or reserving manpower."""
    skill_weights = duty.get("skill_weights") if isinstance(duty.get("skill_weights"), Mapping) else {}
    leadership = _leadership_score(commander, skill_weights)
    composition = _composition_affinity(formation, duty, role_tags)
    readiness = _number(formation.get("readiness"), 100.0)
    cohesion = _number(formation.get("cohesion"), 100.0)
    morale = _number(formation.get("morale"), 100.0)
    fatigue = max(0.0, _number(formation.get("fatigue"), 0.0))
    condition = 0.08 * readiness + 0.05 * cohesion + 0.03 * morale - 0.10 * fatigue
    personnel = max(0, int(_number(formation.get("personnel"))))
    authorized = max(1, int(_number(formation.get("authorized_strength"), personnel or 1)))
    strength_factor = min(1.0, personnel / authorized)
    return round((leadership + composition + condition) * (0.70 + 0.30 * strength_factor), 6)


def eligible_direct_formations(
    group: Mapping[str, Any],
    formations_by_ref: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    """Filter direct formation Units using doctrine-owned force/owner eligibility.

    This is how Tang Wei can restrict standing duties to Qin-assigned Units while
    keeping House Guard and Tang Champions outside the general duty pool.
    """
    eligible_force_refs = {str(x) for x in policy.get("eligible_force_refs", []) if isinstance(x, str)}
    eligible_admin = {str(x) for x in policy.get("eligible_administrative_owners", []) if isinstance(x, str)}
    excluded = {str(x) for x in policy.get("excluded_formation_refs", []) if isinstance(x, str)}
    out: list[tuple[str, Mapping[str, Any]]] = []
    for row in group.get("units", []) if isinstance(group.get("units"), list) else []:
        if not isinstance(row, Mapping) or row.get("kind") != "formation":
            continue
        ref = str(row.get("ref", ""))
        if not ref or ref in excluded:
            continue
        formation = formations_by_ref.get(ref)
        if not isinstance(formation, Mapping):
            continue
        if str(formation.get("formation_class", "")) != "unit":
            continue
        if eligible_force_refs and str(formation.get("owner_force_ref", "")) not in eligible_force_refs:
            continue
        if eligible_admin and str(formation.get("administrative_owner", "")) not in eligible_admin:
            continue
        out.append((ref, formation))
    return sorted(out, key=lambda item: item[0])


def assign_phase_duties(
    *,
    phase: str,
    group: Mapping[str, Any],
    formations_by_ref: Mapping[str, Mapping[str, Any]],
    people_by_ref: Mapping[str, Mapping[str, Any]],
    doctrine: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Assign one standing duty to every eligible direct Unit.

    When there are fewer Units than available duties, the solver chooses the
    globally best subset/permutation exactly.  When an army has more Units than
    duty classes, it first covers every duty with the best distinct Unit/duty
    pairing and then assigns every remaining Unit to its best lawful duty.  This
    keeps large armies bounded while ensuring no direct Unit disappears merely
    because a phase exposes only four duty categories.
    """
    policy = doctrine.get("unit_duty_policy") if isinstance(doctrine.get("unit_duty_policy"), Mapping) else {}
    units = eligible_direct_formations(group, formations_by_ref, policy)
    phase_map = registry.get("phases") if isinstance(registry.get("phases"), Mapping) else {}
    duty_ids = phase_map.get(str(phase), []) if isinstance(phase_map.get(str(phase), []), list) else []
    duties = registry.get("duties") if isinstance(registry.get("duties"), Mapping) else {}
    role_tags = registry.get("role_tags") if isinstance(registry.get("role_tags"), Mapping) else {}
    if not units or not duty_ids:
        return []
    duty_ids = [str(x) for x in duty_ids if str(x) in duties]
    if not duty_ids:
        return []

    score_map: dict[tuple[str, str], float] = {}
    for ref, formation in units:
        commander_ref = str(formation.get("commander_ref", ""))
        for duty_id in duty_ids:
            score_map[(ref, duty_id)] = unit_duty_suitability(
                formation, people_by_ref.get(commander_ref), duties[duty_id], role_tags,
            )

    assigned: dict[str, str] = {}
    if len(units) <= len(duty_ids):
        best_score: float | None = None
        best_key: tuple[str, ...] | None = None
        best_assignment: dict[str, str] = {}
        for duty_order in permutations(duty_ids, len(units)):
            total = sum(score_map[(ref, duty_id)] for (ref, _formation), duty_id in zip(units, duty_order))
            tie_key = tuple(f"{ref}:{duty_id}" for (ref, _formation), duty_id in zip(units, duty_order))
            if best_score is None or total > best_score + 1e-9 or (abs(total-best_score) <= 1e-9 and (best_key is None or tie_key < best_key)):
                best_score, best_key = total, tie_key
                best_assignment = {ref: duty_id for (ref, _formation), duty_id in zip(units, duty_order)}
        assigned = best_assignment
    else:
        # Cover every duty once using distinct Units with a bounded global-pair
        # greedy pass.  This is O(units*duties^2), not a permutation of a large
        # army, and therefore remains safe for hundreds of Units.
        unit_refs = [ref for ref, _ in units]
        uncovered = set(duty_ids)
        unassigned = set(unit_refs)
        while uncovered and unassigned:
            candidates = [
                (score_map[(ref, duty_id)], ref, duty_id)
                for ref in unassigned for duty_id in uncovered
            ]
            _score, ref, duty_id = sorted(candidates, key=lambda row: (-row[0], row[1], row[2]))[0]
            assigned[ref] = duty_id
            unassigned.remove(ref)
            uncovered.remove(duty_id)
        for ref, _formation in units:
            if ref in assigned:
                continue
            ranked = sorted(duty_ids, key=lambda duty_id: (-score_map[(ref, duty_id)], duty_id))
            assigned[ref] = ranked[0]

    rows: list[dict[str, Any]] = []
    by_ref = {ref: formation for ref, formation in units}
    for ref in sorted(assigned):
        formation = by_ref[ref]
        duty_id = assigned[ref]
        commander_ref = str(formation.get("commander_ref", ""))
        rows.append({
            "formation_ref": ref,
            "duty_id": duty_id,
            "duty_label": duties[duty_id].get("label", duty_id),
            "suitability": score_map[(ref, duty_id)],
            "commander_ref": commander_ref or None,
        })
    return rows


__all__ = [
    "assign_phase_duties",
    "eligible_direct_formations",
    "unit_duty_suitability",
]
