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


def ensure_officer_cadre(formation: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    structure = formation.setdefault("command_structure", {})
    if not isinstance(structure, MutableMapping):
        structure = {}
        formation["command_structure"] = structure
    raw = structure.get("officer_cadre")
    if isinstance(raw, MutableMapping):
        cadre = raw
    else:
        inventory = {key: 0 for key in RANK_KEY.values()}
        for row in _summary(structure.get("internal_hierarchy")):
            scale = int(row.get("scale", 0) or 0)
            if scale in RANK_KEY:
                inventory[RANK_KEY[scale]] = max(0, int(row.get("count", 0) or 0))
        if not any(inventory.values()):
            inventory = _target_billets(formation)
        cadre = {
            "representation": "aggregate_by_default",
            "rank_inventory": inventory,
            "active_billets": dict(inventory),
            "cadre_reserve": {key: 0 for key in inventory},
            "vacant_billets": {key: 0 for key in inventory},
            "materialized_refs_by_rank": {key: [] for key in inventory},
            "promotion_training_hours": 0,
            "promotion_history": [],
            "rule": "Rank survives casualties. Reorganization changes billets, not earned rank. Aggregate officers have no individual sheet until causally materialized.",
        }
        structure["officer_cadre"] = cadre
    for field in ("rank_inventory", "active_billets", "cadre_reserve", "vacant_billets", "materialized_refs_by_rank"):
        value = cadre.setdefault(field, {})
        if not isinstance(value, MutableMapping):
            value = {}
            cadre[field] = value
        for key in RANK_KEY.values():
            if field == "materialized_refs_by_rank":
                if not isinstance(value.get(key), list):
                    value[key] = []
            else:
                value[key] = max(0, int(value.get(key, 0) or 0))
    cadre["promotion_training_hours"] = max(0, int(cadre.get("promotion_training_hours", 0) or 0))
    if not isinstance(cadre.get("promotion_history"), list):
        cadre["promotion_history"] = []
    return cadre


def reorganize_officer_cadre(formation: MutableMapping[str, Any], *, at: str | None = None, reason: str = "strength_reorganization") -> dict[str, Any]:
    cadre = ensure_officer_cadre(formation)
    inventory = cadre["rank_inventory"]
    targets = _target_billets(formation)
    changes: dict[str, Any] = {}
    for rank in RANK_KEY.values():
        total = max(0, int(inventory.get(rank, 0)))
        active = min(total, int(targets.get(rank, 0)))
        reserve = max(0, total - active)
        vacant = max(0, int(targets.get(rank, 0)) - active)
        before = (int(cadre["active_billets"].get(rank, 0)), int(cadre["cadre_reserve"].get(rank, 0)), int(cadre["vacant_billets"].get(rank, 0)))
        after = (active, reserve, vacant)
        cadre["active_billets"][rank] = active
        cadre["cadre_reserve"][rank] = reserve
        cadre["vacant_billets"][rank] = vacant
        if before != after:
            changes[rank] = {"before": before, "after": after}
    if at:
        cadre["last_reorganized_at"] = at
        cadre["last_reorganization_reason"] = reason
    return changes


def remove_internal_rank_body(formation: MutableMapping[str, Any], rank: str) -> None:
    """Move one ranked officer body out of the counted formation establishment."""
    cadre = ensure_officer_cadre(formation)
    if rank not in RANK_KEY.values():
        return
    if int(cadre["rank_inventory"].get(rank, 0)) <= 0:
        raise ValueError(f"formation has no aggregate {rank} body available")
    cadre["rank_inventory"][rank] = int(cadre["rank_inventory"].get(rank, 0)) - 1
    # Preserve the truth that the appointment left the internal cadre; the next
    # reorganization determines which surviving officers are active vs reserve.
    reorganize_officer_cadre(formation, reason="officer_promoted_out_of_fighting_establishment")


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
        vacancies = cadre["vacant_billets"]
        inv = cadre["rank_inventory"]
        if int(vacancies.get("1000_commander", 0)) > 0 and int(inv.get("500_commander", 0)) > 0:
            inv["500_commander"] -= 1; inv["1000_commander"] += 1; promoted["1000_commander"] += 1
        elif int(vacancies.get("500_commander", 0)) > 0 and int(inv.get("100_commander", 0)) > 0:
            inv["100_commander"] -= 1; inv["500_commander"] += 1; promoted["500_commander"] += 1
        elif int(vacancies.get("100_commander", 0)) > 0:
            # A qualified existing rank-and-file/NCO body is promoted into the
            # 100-command grade. It remains one of the already-counted personnel.
            inv["100_commander"] += 1; promoted["100_commander"] += 1
        else:
            break
        reorganize_officer_cadre(formation, reason="aggregate_officer_promotion")
    if any(promoted.values()):
        cadre.setdefault("promotion_history", []).append({"at": at, "promoted": {k: v for k, v in promoted.items() if v}, "source": "verified_formation_training"})
    return promoted


def officer_cadre_summary(formation: Mapping[str, Any]) -> dict[str, Any]:
    # Read-only copy suitable for API projection.
    temp = dict(formation)
    structure = dict(formation.get("command_structure", {})) if isinstance(formation.get("command_structure"), Mapping) else {}
    temp["command_structure"] = structure
    cadre = ensure_officer_cadre(temp)
    return {
        "rank_inventory": dict(cadre["rank_inventory"]),
        "active_billets": dict(cadre["active_billets"]),
        "cadre_reserve": dict(cadre["cadre_reserve"]),
        "vacant_billets": dict(cadre["vacant_billets"]),
        "materialized_refs_by_rank": {k: list(v) for k, v in cadre["materialized_refs_by_rank"].items()},
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
    child_structure = child.setdefault("command_structure", {})
    if not isinstance(child_structure, MutableMapping):
        child_structure = {}; child["command_structure"] = child_structure
    child_structure["officer_cadre"] = {
        "representation": "aggregate_by_default",
        "rank_inventory": child_inventory,
        "active_billets": dict(child_inventory),
        "cadre_reserve": {rank: 0 for rank in child_inventory},
        "vacant_billets": {rank: 0 for rank in child_inventory},
        "materialized_refs_by_rank": {rank: [] for rank in child_inventory},
        "promotion_training_hours": 0,
        "promotion_history": [],
        "rule": "Partitioned from the parent formation's already-conserved officer ranks; no officer bodies were created.",
    }
    reorganize_officer_cadre(parent, reason="formation_split")
    reorganize_officer_cadre(child, reason="formation_split")


def merge_officer_cadres(primary: MutableMapping[str, Any], members: list[Mapping[str, Any]]) -> None:
    """Merge durable officer ranks; excess officers become cadre reserve, never vanish."""
    p = ensure_officer_cadre(primary)
    for member in members:
        temp = dict(member)
        temp["command_structure"] = dict(member.get("command_structure", {})) if isinstance(member.get("command_structure"), Mapping) else {}
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
        rank = {
            "grade": grade,
            "durable": True,
            "source": source,
            "rule": "Only an explicit promotion/demotion/career decision changes grade; casualty strength and billet changes do not.",
        }
        person["military_rank"] = rank
    rank.setdefault("grade", str(person.get("rank") or inferred_grade or "not_formally_recorded"))
    rank["durable"] = True
    rank.setdefault("rule", "Only an explicit promotion/demotion/career decision changes grade; casualty strength and billet changes do not.")
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
