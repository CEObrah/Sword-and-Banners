#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from sword_runtime.cohort_personnel import validate_cohort_ledger

HOUSE = ROOT / "state/forces/house-tang.json"

# Provenance reconstructed from the supplied 2026-08-25 checkpoint. These are
# the 165 internal 1,000/500 person-lite officer bodies that belonged to home
# formations. Five additional old materialized bodies belonged to the retired
# Tang Champions field formation and were handled by the Tang Wei phase-2
# rebaseline, so they are intentionally absent here.
REAGGREGATE = {
    "formation_house_tang_cavalry_01": ("cohort_force_house_tang_guardian_cavalry_standing", 6),
    "formation_house_tang_cavalry_02": ("cohort_force_house_tang_guardian_cavalry_standing", 6),
    "formation_house_tang_cavalry_03": ("cohort_force_house_tang_guardian_cavalry_standing", 6),
    "formation_house_tang_cavalry_04": ("cohort_force_house_tang_guardian_cavalry_standing", 6),
    "formation_house_tang_cavalry_elite_01": ("cohort_force_house_tang_tang_champion_standing", 3),
    "formation_house_tang_cavalry_elite_03": ("cohort_force_house_tang_tang_champion_standing", 3),
    "formation_house_tang_cavalry_elite_04": ("cohort_force_house_tang_tang_champion_standing", 1),
    "formation_house_tang_infantry_01": ("cohort_force_house_tang_house_guard_standing", 15),
    "formation_house_tang_infantry_02": ("cohort_force_house_tang_house_guard_standing", 15),
    "formation_house_tang_infantry_03": ("cohort_force_house_tang_house_guard_standing", 15),
    "formation_house_tang_inner_walls_general_01": ("cohort_force_sword_manor_general_disciple_standing", 10),
    "formation_house_tang_inner_walls_junior_01": ("cohort_force_sword_manor_junior_disciple_standing", 15),
    "formation_house_tang_inner_walls_senior_01": ("cohort_force_sword_manor_senior_disciple_standing", 4),
    "formation_house_tang_inner_walls_trainee_01": ("cohort_force_sword_manor_trainee_standing", 15),
    "formation_house_tang_inner_walls_trainee_02": ("cohort_force_sword_manor_trainee_standing", 15),
    "formation_house_tang_inner_walls_trainee_03": ("cohort_force_sword_manor_trainee_standing", 15),
    "formation_house_tang_inner_walls_trainee_04": ("cohort_force_sword_manor_trainee_standing", 15),
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def formation_paths():
    out = {}
    for path in (ROOT / "state/formations").glob("*.json"):
        row = load(path)
        ref = row.get("formation_ref")
        if isinstance(ref, str):
            out[ref] = (path, row)
    return out


def char_path(person_ref: str) -> Path | None:
    if person_ref == "char_tang_wei":
        return ROOT / "state/player.json"
    for path in (ROOT / "state/char").glob("*.json"):
        row = load(path)
        if row.get("owner_id") == person_ref or row.get("id") == person_ref:
            return path
    return None


def reserve_location(cohort: dict) -> str:
    origin = cohort.get("origin") if isinstance(cohort.get("origin"), dict) else {}
    source = origin.get("source_location_ref")
    if isinstance(source, str) and source:
        return source
    reserve = cohort.get("reserve_by_location") if isinstance(cohort.get("reserve_by_location"), dict) else {}
    if reserve:
        return sorted(reserve)[0]
    return "loc_tang_manor_garrison_yard"


def add_slice(formation: dict, cohort_id: str, count: int) -> None:
    rows = formation.setdefault("cohort_composition", [])
    for row in rows:
        if isinstance(row, dict) and row.get("cohort_id") == cohort_id:
            row["count"] = int(row.get("count", 0)) + count
            break
    else:
        rows.append({"cohort_id": cohort_id, "count": count})
    formation["cohort_composition"] = sorted(
        [row for row in rows if isinstance(row, dict) and int(row.get("count", 0)) > 0],
        key=lambda row: str(row.get("cohort_id", "")),
    )


def recompute(force: dict) -> None:
    reserve = defaultdict(int)
    by_location = defaultdict(lambda: defaultdict(int))
    allocated = defaultdict(int)
    composition = defaultdict(lambda: defaultdict(int))
    external = defaultdict(lambda: defaultdict(int))
    for cohort in force["cohort_ledger"]["cohorts"].values():
        role = str(cohort.get("role", "unknown"))
        for loc, raw in cohort.get("reserve_by_location", {}).items():
            n = int(raw)
            if n:
                reserve[role] += n
                by_location[str(loc)][role] += n
        for ref, raw in cohort.get("allocated_by_formation", {}).items():
            n = int(raw)
            if n:
                allocated[str(ref)] += n
                composition[str(ref)][role] += n
        for ref, raw in cohort.get("allocated_external_by_formation", {}).items():
            n = int(raw)
            if n:
                external[str(ref)][role] += n
    for assignment in force.get("materialized_assignments", {}).values():
        if not isinstance(assignment, dict) or not assignment.get("formation_ref"):
            continue
        ref = str(assignment["formation_ref"])
        n = max(1, int(assignment.get("personnel", 1)))
        role = str(assignment.get("role", "unknown"))
        allocated[ref] += n
        composition[ref][role] += n
    force["available_by_role"] = dict(sorted(reserve.items()))
    force["available_by_location"] = {
        loc: dict(sorted(row.items())) for loc, row in sorted(by_location.items()) if sum(row.values())
    }
    force["allocated_to_formations"] = {
        ref: {"personnel": allocated[ref], "composition": dict(sorted(composition[ref].items()))}
        for ref in sorted(allocated)
    }
    force["external_personnel_allocations"] = {
        ref: dict(sorted(row.items())) for ref, row in sorted(external.items()) if sum(row.values())
    }


def main() -> None:
    force = load(HOUSE)
    cohorts = force["cohort_ledger"]["cohorts"]
    forms = formation_paths()

    # Step 1: each home formation already has a named exact commander. The old
    # aggregate external Unit-command body is therefore the body that should be
    # represented by that exact commander. Return the second reserve body that
    # the intermediate recovery mistakenly consumed, and consume the original
    # external slot without returning it to reserve.
    converted = 0
    ext_top = force.get("external_personnel_allocations", {})
    for formation_ref, roles in list(ext_top.items()):
        if formation_ref not in forms or not isinstance(roles, dict):
            continue
        _fp, formation = forms[formation_ref]
        if formation.get("owner_force_ref") != "force_house_tang":
            continue
        commander = formation.get("commander_ref")
        if not isinstance(commander, str) or not commander:
            continue
        total = sum(max(0, int(v)) for v in roles.values())
        if total != 1:
            raise RuntimeError(f"{formation_ref}: expected exactly one legacy external Unit-command body, got {roles}")

        ext_candidates = []
        for cid, cohort in cohorts.items():
            held = int(cohort.get("allocated_external_by_formation", {}).get(formation_ref, 0))
            if held > 0:
                ext_candidates.append((cid, cohort, held))
        if len(ext_candidates) != 1 or ext_candidates[0][2] != 1:
            raise RuntimeError(f"{formation_ref}: external command provenance is not singular: {[(x[0], x[2]) for x in ext_candidates]}")
        ext_cid, ext_cohort, _ = ext_candidates[0]

        mat = force.get("materialized_people", {}).get(commander)
        if not isinstance(mat, dict) or int(mat.get("personnel", 1)) != 1:
            raise RuntimeError(f"{formation_ref}: named commander {commander} lacks one materialized House body")
        wrong_cid = str(mat.get("source_cohort_ref", ""))
        wrong_cohort = cohorts.get(wrong_cid)
        if not isinstance(wrong_cohort, dict):
            raise RuntimeError(f"{formation_ref}: commander {commander} has unknown materialized source {wrong_cid}")

        # Return the mistakenly consumed second body to the exact cohort/location
        # from which the recovery selected it.
        wrong_loc = reserve_location(wrong_cohort)
        wrong_reserve = wrong_cohort.setdefault("reserve_by_location", {})
        wrong_reserve[wrong_loc] = int(wrong_reserve.get(wrong_loc, 0)) + 1

        # Consume the pre-existing external command slot as the exact commander.
        ext_alloc = ext_cohort.setdefault("allocated_external_by_formation", {})
        if int(ext_alloc.get(formation_ref, 0)) != 1:
            raise RuntimeError(f"{formation_ref}: external source changed during repair")
        ext_alloc.pop(formation_ref, None)
        mat["source_cohort_ref"] = ext_cid
        mat["source_mode"] = "materialized_existing_external_command_slot"

        cp = char_path(commander)
        if cp is None:
            raise RuntimeError(f"{formation_ref}: commander sheet missing for {commander}")
        person = load(cp)
        provenance = person.setdefault("materialization_provenance", {})
        if isinstance(provenance, dict):
            provenance["source_cohort_ref"] = ext_cid
            provenance["source_role"] = str(ext_cohort.get("role", mat.get("role", "unknown")))
            provenance["source_mode"] = "materialized_existing_external_command_slot"
        save(cp, person)
        converted += 1

    if converted != 44:
        raise RuntimeError(f"expected 44 House home exact-command conversions, repaired {converted}")

    # Step 2: restore the 165 pre-collapse internal officers to the exact renamed
    # home formations and exact source cohorts recorded in the supplied checkpoint.
    restored = 0
    backfilled = 0
    for formation_ref, (cid, expected) in REAGGREGATE.items():
        fp, formation = forms[formation_ref]
        current_slices = sum(
            int(row.get("count", 0)) for row in formation.get("cohort_composition", []) if isinstance(row, dict)
        )
        gap = int(formation.get("personnel", 0)) - current_slices
        if gap == 0:
            continue  # idempotent rerun after successful repair
        if gap != expected:
            raise RuntimeError(f"{formation_ref}: expected historical internal-officer gap {expected}, found {gap}")
        cohort = cohorts.get(cid)
        if not isinstance(cohort, dict):
            raise RuntimeError(f"{formation_ref}: missing provenance cohort {cid}")
        reserves = cohort.setdefault("reserve_by_location", {})
        need = expected
        direct = 0
        # Restore every still-reserved historical body from its exact provenance
        # cohort first. A small remainder can be absent because some of those old
        # officers were lawfully promoted into new higher command billets.
        for loc in sorted(list(reserves), key=lambda loc: (loc != reserve_location(cohort), loc)):
            held = int(reserves.get(loc, 0))
            if held <= 0 or need <= 0:
                continue
            take = min(held, need)
            reserves[loc] = held - take
            if reserves[loc] == 0:
                reserves.pop(loc, None)
            need -= take
            direct += take
        if direct:
            alloc = cohort.setdefault("allocated_by_formation", {})
            alloc[formation_ref] = int(alloc.get(formation_ref, 0)) + direct
            add_slice(formation, cid, direct)

        # Vacancies left specifically by promoted old officers are backfilled from
        # another already-conserved reserve cohort of the same legal troop species.
        # Do not steal from another historical officer cohort that still has its
        # own reaggregation obligation.
        if need:
            role = str(cohort.get("role", ""))
            protected = {source_cid for source_cid, _n in REAGGREGATE.values()}
            candidates = []
            for fallback_cid, fallback in cohorts.items():
                if fallback_cid in protected or str(fallback.get("role", "")) != role:
                    continue
                available = sum(max(0, int(v)) for v in fallback.get("reserve_by_location", {}).values())
                if available:
                    same_region = reserve_location(fallback).startswith("loc_tang_manor")
                    candidates.append((0 if same_region else 1, -available, fallback_cid, fallback))
            for _region, _neg_available, fallback_cid, fallback in sorted(candidates):
                if need <= 0:
                    break
                fallback_reserve = fallback.setdefault("reserve_by_location", {})
                for loc in sorted(list(fallback_reserve), key=lambda loc: (loc != reserve_location(fallback), loc)):
                    held = int(fallback_reserve.get(loc, 0))
                    if held <= 0 or need <= 0:
                        continue
                    take = min(held, need)
                    fallback_reserve[loc] = held - take
                    if fallback_reserve[loc] == 0:
                        fallback_reserve.pop(loc, None)
                    fallback.setdefault("allocated_by_formation", {})[formation_ref] = int(fallback.setdefault("allocated_by_formation", {}).get(formation_ref, 0)) + take
                    add_slice(formation, fallback_cid, take)
                    need -= take
                    backfilled += take
            if need:
                raise RuntimeError(f"{formation_ref}: same-role House reserve lacks {need} backfill bodies")
        save(fp, formation)
        restored += expected

    if restored not in {0, 165}:
        raise RuntimeError(f"partial internal-officer repair: {restored}/165")

    recompute(force)
    validate_cohort_ledger(force)

    # Every current House formation must now have an exact anonymous-cohort slice
    # for every fighting body; exact top commanders are outside fighting strength.
    forms = formation_paths()
    mismatches = []
    for ref, (_fp, formation) in forms.items():
        if formation.get("owner_force_ref") != "force_house_tang":
            continue
        represented = sum(
            int(row.get("count", 0)) for row in formation.get("cohort_composition", []) if isinstance(row, dict)
        )
        inside = sum(
            max(1, int(a.get("personnel", 1)))
            for a in force.get("materialized_assignments", {}).values()
            if isinstance(a, dict) and a.get("formation_ref") == ref
        )
        if represented + inside != int(formation.get("personnel", 0)):
            mismatches.append((ref, represented, inside, int(formation.get("personnel", 0))))
    if mismatches:
        raise RuntimeError(f"House formation cohort mismatch after repair: {mismatches}")
    if force.get("external_personnel_allocations"):
        raise RuntimeError("House exact formation commanders still have aggregate external command duplicates")

    save(HOUSE, force)
    print(f"converted duplicate aggregate House command slots into exact commanders: {converted}")
    print(f"restored/backfilled internal fighting slots: {restored} (same-role reserve backfills after officer promotion: {backfilled})")
    print("house reserve", sum(int(v) for v in force.get("available_by_role", {}).values()))
    print("house fighting allocations", sum(int(v.get("personnel", 0)) for v in force.get("allocated_to_formations", {}).values()))
    print("house materialized exact bodies", sum(int(v.get("personnel", 1)) if isinstance(v, dict) else int(v) for v in force.get("materialized_people", {}).values()))
    print("house external aggregate command bodies", sum(sum(int(x) for x in row.values()) for row in force.get("external_personnel_allocations", {}).values()))


if __name__ == "__main__":
    main()
