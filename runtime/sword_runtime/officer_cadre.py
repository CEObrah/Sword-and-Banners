"""Compact durable officer-rank/cadre mechanics for persistent formations.

Most officers remain aggregate.  Rank is durable career state; billet is the
current job; commanded headcount is a third, independent fact.  Casualties may
shrink a formation without silently demoting surviving officers.  Explicit
reorganization moves surplus officers into an attached cadre reserve so they
remain available for rebuilding without producing thousands of individual
records.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any
import hashlib

from sword_runtime.unit_establishment import (
    authorized_strength_for,
    classify_formation,
    formation_class_for,
    hierarchy_counts,
)

RANK_SCALES = (1000, 500, 100)
RANK_KEY = {1000: "1000_commander", 500: "500_commander", 100: "100_commander"}


def _summary(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [dict(row) for row in raw if isinstance(row, Mapping)]
    if isinstance(raw, Mapping):
        summary = raw.get("summary", [])
        if isinstance(summary, list) and summary:
            return [dict(row) for row in summary if isinstance(row, Mapping)]
        by_role = raw.get("by_role", {})
        counts: dict[int, int] = {}
        if isinstance(by_role, Mapping):
            for role_row in by_role.values():
                if not isinstance(role_row, Mapping):
                    continue
                for scale, key in ((1000, "commanders_1000"), (500, "commanders_500"), (100, "commanders_100")):
                    count = max(0, int(role_row.get(key, 0) or 0))
                    if count:
                        counts[scale] = counts.get(scale, 0) + count
        return [{"scale": scale, "count": count} for scale, count in sorted(counts.items(), reverse=True)]
    return []


def _target_billets(formation: Mapping[str, Any]) -> dict[str, int]:
    """Return authorized internal billets from durable Unit establishment.

    The Unit commander and deputy own the Unit echelon itself and therefore do
    not appear here.  Internal 1,000/500/100 billets are generated only at
    standard echelons strictly smaller than the authorized Unit.  Current
    surviving manpower never rewrites this establishment after casualties.
    """
    current = max(0, int(formation.get("personnel", 0) or 0))
    klass = formation_class_for(formation, personnel=current, explicit=formation.get("formation_class"))
    authorized = authorized_strength_for(formation, personnel=current, formation_class=klass)
    counts = hierarchy_counts(authorized_strength=authorized, formation_class=klass)
    return {RANK_KEY[scale]: max(0, int(counts.get(scale, 0))) for scale in RANK_SCALES}


def _derived_cadre_allocations(formation: Mapping[str, Any], cadre: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    inventory = cadre.get("rank_inventory", {}) if isinstance(cadre, Mapping) else {}
    targets = _target_billets(formation)
    active: dict[str, int] = {}
    reserve: dict[str, int] = {}
    vacant: dict[str, int] = {}
    for rank in RANK_KEY.values():
        total = max(0, int(inventory.get(rank, 0) or 0)) if isinstance(inventory, Mapping) else 0
        target = max(0, int(targets.get(rank, 0)))
        active[rank] = min(total, target)
        reserve[rank] = max(0, total - active[rank])
        vacant[rank] = max(0, target - active[rank])
    return {"active_billets": active, "cadre_reserve": reserve, "vacant_billets": vacant}


def ensure_officer_cadre(formation: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Return the compact durable officer cadre owner for one formation.

    Command topology, active allocations and vacancies are projections of the
    authorized establishment plus current durable rank inventory.  Only facts
    that survive a re-projection live in hot formation state.
    """
    raw = formation.get("officer_cadre")
    if isinstance(raw, MutableMapping):
        cadre = raw
    else:
        prior_structure = formation.get("command_structure") if isinstance(formation.get("command_structure"), Mapping) else {}
        prior = prior_structure.get("officer_cadre") if isinstance(prior_structure, Mapping) else None
        if isinstance(prior, Mapping):
            inventory = {key: max(0, int(prior.get("rank_inventory", {}).get(key, 0) or 0)) for key in RANK_KEY.values()} if isinstance(prior.get("rank_inventory"), Mapping) else {key: 0 for key in RANK_KEY.values()}
            materialized = {key: list(prior.get("materialized_refs_by_rank", {}).get(key, [])) for key in RANK_KEY.values()} if isinstance(prior.get("materialized_refs_by_rank"), Mapping) else {key: [] for key in RANK_KEY.values()}
            promotion_hours = max(0, int(prior.get("promotion_training_hours", 0) or 0))
        else:
            inventory = {key: 0 for key in RANK_KEY.values()}
            for row in _summary(prior_structure.get("internal_hierarchy") if isinstance(prior_structure, Mapping) else None):
                scale = int(row.get("scale", 0) or 0)
                if scale in RANK_KEY:
                    inventory[RANK_KEY[scale]] = max(0, int(row.get("count", 0) or 0))
            if not any(inventory.values()):
                inventory = _target_billets(formation)
            materialized = {key: [] for key in RANK_KEY.values()}
            promotion_hours = 0
        cadre = {
            "rank_inventory": inventory,
            "materialized_refs_by_rank": materialized,
        }
        if promotion_hours:
            cadre["promotion_training_hours"] = promotion_hours
        formation["officer_cadre"] = cadre
    inventory = cadre.setdefault("rank_inventory", {})
    if not isinstance(inventory, MutableMapping):
        inventory = {}; cadre["rank_inventory"] = inventory
    materialized = cadre.setdefault("materialized_refs_by_rank", {})
    if not isinstance(materialized, MutableMapping):
        materialized = {}; cadre["materialized_refs_by_rank"] = materialized
    for key in RANK_KEY.values():
        inventory[key] = max(0, int(inventory.get(key, 0) or 0))
        refs = materialized.get(key)
        materialized[key] = sorted({str(ref) for ref in refs if isinstance(ref, str) and ref}) if isinstance(refs, list) else []
    hours = max(0, int(cadre.get("promotion_training_hours", 0) or 0))
    if hours:
        cadre["promotion_training_hours"] = hours
    else:
        cadre.pop("promotion_training_hours", None)
    # Remove stale projection fields if an earlier writer supplied them.
    for key in ("active_billets", "cadre_reserve", "vacant_billets"):
        cadre.pop(key, None)
    return cadre


def reorganize_officer_cadre(formation: MutableMapping[str, Any], *, at: str | None = None, reason: str = "strength_reorganization") -> dict[str, Any]:
    """Re-project billet occupancy without persisting derived allocations."""
    cadre = ensure_officer_cadre(formation)
    return _derived_cadre_allocations(formation, cadre)


def register_materialized_rank(formation: MutableMapping[str, Any], person_ref: str, rank: str) -> None:
    cadre = ensure_officer_cadre(formation)
    if rank not in RANK_KEY.values():
        return
    refs = cadre["materialized_refs_by_rank"].setdefault(rank, [])
    if person_ref not in refs:
        refs.append(person_ref)
        refs.sort()


def unregister_materialized_rank(formation: MutableMapping[str, Any], person_ref: str) -> None:
    cadre = ensure_officer_cadre(formation)
    for refs in cadre["materialized_refs_by_rank"].values():
        if isinstance(refs, list) and person_ref in refs:
            refs[:] = [ref for ref in refs if ref != person_ref]


def remove_internal_rank_body(
    formation: MutableMapping[str, Any],
    rank: str,
    *,
    person_ref: str | None = None,
) -> None:
    """Move one durable internal officer body out of a formation cadre.

    This is used when an embedded officer becomes an external formation-level or
    army-level command body.  The person remains conserved by the owning force,
    but no longer occupies the formation's fighting-strength allocation or its
    internal rank inventory.  Materialization is representation-only, so this
    must decrement exactly one existing aggregate rank body rather than creating
    or deleting a second person.
    """
    cadre = ensure_officer_cadre(formation)
    if rank not in RANK_KEY.values():
        raise ValueError(f"unsupported internal officer rank: {rank}")
    inventory = cadre["rank_inventory"]
    held = max(0, int(inventory.get(rank, 0) or 0))
    if held <= 0:
        raise ValueError(f"formation has no conserved {rank} body to externalize")
    inventory[rank] = held - 1
    if person_ref:
        refs = cadre["materialized_refs_by_rank"].get(rank, [])
        if isinstance(refs, list):
            refs[:] = [ref for ref in refs if ref != person_ref]
    reorganize_officer_cadre(formation, reason="internal_officer_externalized")


def settle_aggregate_officer_losses(formation: MutableMapping[str, Any], *, before_personnel: int, casualties: int, seed: str, targeting_pressure: float = 0.0) -> dict[str, int]:
    """Classify part of already-settled troop casualties as aggregate officer deaths.

    This never adds casualties. It only updates the surviving aggregate rank
    inventory so veteran cadre can be remembered and rebuilt correctly.
    """
    before = max(0, int(before_personnel)); loss = max(0, min(before, int(casualties)))
    cadre = ensure_officer_cadre(formation)
    if before <= 0 or loss <= 0:
        reorganize_officer_cadre(formation, reason="post_battle_reorganization")
        return {rank: 0 for rank in RANK_KEY.values()}
    inventory = {rank: max(0, int(cadre["rank_inventory"].get(rank, 0))) for rank in RANK_KEY.values()}
    total_officers = sum(inventory.values())
    if total_officers <= 0:
        reorganize_officer_cadre(formation, reason="post_battle_reorganization")
        return {rank: 0 for rank in inventory}
    # Officers are neither magically immune nor guaranteed proportional losses.
    # Deterministic jitter keeps identical casualty fractions from always killing
    # the same rounded count while staying bounded by the already-settled deaths.
    frac = loss / max(1, before)
    raw_target = total_officers * frac
    # Named local interventions can concentrate some of the already-settled
    # casualties onto visible command bodies. This never creates extra deaths;
    # it only changes which existing aggregate casualties were officers.
    focused = max(0.0, float(targeting_pressure))
    if focused > 0.0:
        raw_target += min(focused * 0.35, total_officers * 0.20, loss * 0.20)
    hv = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    target = int(raw_target)
    if (raw_target - int(raw_target)) * 10000 > hv % 10000:
        target += 1
    target = max(0, min(loss, total_officers, target))
    if target <= 0:
        reorganize_officer_cadre(formation, reason="post_battle_reorganization")
        return {rank: 0 for rank in inventory}
    weighted = []
    for rank, count in inventory.items():
        share = count * target / max(1, total_officers)
        floor = min(count, int(share))
        weighted.append([rank, count, share, floor, share - floor])
    assigned = sum(row[3] for row in weighted)
    for row in sorted(weighted, key=lambda x: (-x[4], x[0])):
        if assigned >= target:
            break
        if row[3] < row[1]:
            row[3] += 1; assigned += 1
    deaths: dict[str, int] = {}
    for rank, count, _share, dead, _rem in weighted:
        dead = min(int(count), int(dead)); deaths[rank] = dead
        cadre["rank_inventory"][rank] = max(0, int(cadre["rank_inventory"].get(rank, 0)) - dead)
    reorganize_officer_cadre(formation, reason="post_battle_reorganization")
    return deaths


def develop_officer_cadre(formation: MutableMapping[str, Any], *, training_hours: int, at: str | None = None) -> dict[str, int]:
    """Use real training time to fill aggregate rank vacancies without new bodies.

    Promotion changes durable aggregate rank.  It reclassifies an already-counted
    formation body/officer, so formation personnel never changes.  Thresholds are
    intentionally slow and cumulative; a vacancy alone grants no rank.
    """
    cadre = ensure_officer_cadre(formation)
    cadre["promotion_training_hours"] = int(cadre.get("promotion_training_hours", 0)) + max(0, int(training_hours))
    hours = int(cadre["promotion_training_hours"])
    promoted = {rank: 0 for rank in RANK_KEY.values()}
    # One career promotion opportunity per 120 verified formation-training hours.
    opportunities = hours // 120
    if opportunities <= 0:
        return promoted
    cadre["promotion_training_hours"] = hours % 120
    reorganize_officer_cadre(formation, reason="pre_promotion_review")
    for _ in range(opportunities):
        vacancies = _derived_cadre_allocations(formation, cadre)["vacant_billets"]
        inv = cadre["rank_inventory"]
        materialized = cadre.get("materialized_refs_by_rank", {}) if isinstance(cadre.get("materialized_refs_by_rank"), Mapping) else {}
        unmaterialized_500 = max(0, int(inv.get("500_commander", 0)) - len(materialized.get("500_commander", [])))
        unmaterialized_100 = max(0, int(inv.get("100_commander", 0)) - len(materialized.get("100_commander", [])))
        if int(vacancies.get("1000_commander", 0)) > 0 and unmaterialized_500 > 0:
            inv["500_commander"] -= 1; inv["1000_commander"] += 1; promoted["1000_commander"] += 1
        elif int(vacancies.get("500_commander", 0)) > 0 and unmaterialized_100 > 0:
            inv["100_commander"] -= 1; inv["500_commander"] += 1; promoted["500_commander"] += 1
        elif int(vacancies.get("100_commander", 0)) > 0:
            # A qualified existing rank-and-file/NCO body is promoted into the
            # 100-command grade. It remains one of the already-counted personnel.
            inv["100_commander"] += 1; promoted["100_commander"] += 1
        else:
            break
        reorganize_officer_cadre(formation, reason="aggregate_officer_promotion")
    return promoted


def officer_cadre_summary(formation: Mapping[str, Any]) -> dict[str, Any]:
    # Read-only projection suitable for command/combat/API consumers.
    temp = dict(formation)
    if isinstance(formation.get("officer_cadre"), Mapping):
        temp["officer_cadre"] = {k: (dict(v) if isinstance(v, Mapping) else v) for k, v in formation["officer_cadre"].items()}
    cadre = ensure_officer_cadre(temp)
    allocations = _derived_cadre_allocations(temp, cadre)
    return {
        "rank_inventory": dict(cadre["rank_inventory"]),
        "active_billets": dict(allocations["active_billets"]),
        "cadre_reserve": dict(allocations["cadre_reserve"]),
        "vacant_billets": dict(allocations["vacant_billets"]),
        "materialized_refs_by_rank": {k: list(v) for k, v in cadre["materialized_refs_by_rank"].items()},
        "promotion_training_hours": max(0, int(cadre.get("promotion_training_hours", 0) or 0)),
    }


def partition_officer_cadre(parent: MutableMapping[str, Any], child: MutableMapping[str, Any], *, child_personnel: int, total_personnel: int) -> None:
    """Partition durable aggregate officer ranks during a lawful formation split."""
    p_cadre = ensure_officer_cadre(parent)
    total = max(1, int(total_personnel)); moved = max(0, min(total, int(child_personnel)))
    child_inventory: dict[str, int] = {}
    for rank in RANK_KEY.values():
        count = max(0, int(p_cadre["rank_inventory"].get(rank, 0)))
        child_count = min(count, int(round(count * moved / total)))
        child_inventory[rank] = child_count
        p_cadre["rank_inventory"][rank] = count - child_count
    child["officer_cadre"] = {
        "rank_inventory": child_inventory,
        "materialized_refs_by_rank": {rank: [] for rank in child_inventory},
    }
    reorganize_officer_cadre(parent, reason="formation_split")
    reorganize_officer_cadre(child, reason="formation_split")


def merge_officer_cadres(primary: MutableMapping[str, Any], members: list[Mapping[str, Any]]) -> None:
    """Merge durable officer ranks; excess officers become cadre reserve, never vanish."""
    p = ensure_officer_cadre(primary)
    for member in members:
        temp = dict(member)
        if isinstance(member.get("officer_cadre"), Mapping):
            temp["officer_cadre"] = dict(member.get("officer_cadre", {}))
        m = ensure_officer_cadre(temp)
        for rank in RANK_KEY.values():
            p["rank_inventory"][rank] = int(p["rank_inventory"].get(rank, 0)) + int(m["rank_inventory"].get(rank, 0))
            refs = p["materialized_refs_by_rank"].setdefault(rank, [])
            for ref in m["materialized_refs_by_rank"].get(rank, []):
                if ref not in refs:
                    refs.append(ref)
            refs.sort()
    reorganize_officer_cadre(primary, reason="formation_merge")


def ensure_person_military_rank(person: MutableMapping[str, Any], *, inferred_grade: str | None = None, source: str = "saved_baseline") -> MutableMapping[str, Any]:
    """Ensure an individually represented military person has durable rank state."""
    raw = person.get("military_rank")
    if isinstance(raw, MutableMapping):
        rank = raw
    else:
        grade = str(person.get("rank") or inferred_grade or "not_formally_recorded")
        rank = {"grade": grade, "durable": True}
        person["military_rank"] = rank
    rank.setdefault("grade", str(person.get("rank") or inferred_grade or "not_formally_recorded"))
    rank["durable"] = True
    return rank


def set_person_billet(person: MutableMapping[str, Any], *, billet: str, command_ref: str | None = None, formation_ref: str | None = None, current_span: int | None = None, external_to_fighting_strength: bool | None = None) -> None:
    ensure_person_military_rank(person)
    career = person.setdefault("career_state", {})
    if isinstance(career, MutableMapping):
        career["current_billet"] = billet
    assignment = person.setdefault("command_assignment", {})
    if not isinstance(assignment, MutableMapping):
        assignment = {}; person["command_assignment"] = assignment
    assignment["billet"] = billet
    if command_ref is not None: assignment["command_group_ref"] = command_ref
    if formation_ref is not None: assignment["formation_ref"] = formation_ref
    if current_span is not None: assignment["current_command_span"] = max(0, int(current_span))
    if external_to_fighting_strength is not None: assignment["external_to_fighting_strength"] = bool(external_to_fighting_strength)
