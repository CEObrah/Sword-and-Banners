from __future__ import annotations

from sword_runtime.unit_establishment import freeze_establishment_composition
import copy


def test_state_reconstitution_uses_only_existing_local_force_reserve(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    planner = ProductionCampaignPlanner(campaign)
    path = "state/formations/qin-kankoku-central-gate.json"
    formation = copy.deepcopy(planner.read(path))
    force_path = "state/forces/state-qin.json"
    force = copy.deepcopy(planner.read(force_path))
    role = next(iter(formation["composition"]))
    location = formation["location_ref"]
    available = min(int(force["available_by_role"].get(role, 0)), int(force["available_by_location"].get(location, {}).get(role, 0)))
    if available < 3:
        return
    # Mirror the real casualty path: freeze the pre-loss role establishment before
    # changing composition, then return the same three live bodies to reserve.
    freeze_establishment_composition(formation)
    # Simulate an already-settled understrength formation by returning three live
    # bodies to its exact force reserve. This is not a casualty generator.
    formation["composition"][role] -= 3
    formation["personnel"] -= 3
    force["allocated_to_formations"][formation["formation_ref"]]["composition"][role] -= 3
    force["allocated_to_formations"][formation["formation_ref"]]["personnel"] -= 3
    force["available_by_role"][role] += 3
    force["available_by_location"][location][role] += 3

    # Move the exact same three cohort bodies out of the formation slice and
    # back into that cohort's physical local reserve. Top-level force counters
    # are only projections of this ledger and may not be edited alone.
    moved = 0
    formation_cohorts = {row["cohort_id"]: row for row in formation.get("cohort_composition", []) if row.get("count", 0) > 0}
    for cohort in force.get("cohort_ledger", {}).get("cohorts", {}).values():
        if cohort.get("role") != role:
            continue
        allocated = int(cohort.get("allocated_by_formation", {}).get(formation["formation_ref"], 0))
        if allocated <= 0:
            continue
        take = min(3 - moved, allocated)
        cohort["allocated_by_formation"][formation["formation_ref"]] = allocated - take
        cohort.setdefault("reserve_by_location", {})[location] = int(cohort.get("reserve_by_location", {}).get(location, 0)) + take
        row = formation_cohorts.get(cohort["cohort_id"])
        assert row is not None
        row["count"] = int(row["count"]) - take
        moved += take
        if moved == 3:
            break
    assert moved == 3
    formation["cohort_composition"] = [row for row in formation.get("cohort_composition", []) if int(row.get("count", 0)) > 0]
    planner.put(path, formation); planner.put(force_path, force)
    result = planner._reconstitute_force_from_local_reserve(force_path, planner.read("state/meta.json")["time"])
    after = planner.read(path)
    assert result["assigned"] >= 3
    assert formation["personnel"] < after["personnel"] <= after["authorized_strength"]
    assert after["officer_cadre"]["rank_inventory"] == formation["officer_cadre"]["rank_inventory"]
    assert "command_structure" not in after


def test_exact_unit_commander_is_outside_fighting_establishment_and_does_not_consume_replacement_billets(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    path = "state/formations/house-tang-infantry-01.json"
    force_path = "state/forces/house-tang.json"
    formation = copy.deepcopy(planner.read(path))
    force = copy.deepcopy(planner.read(force_path))
    role = "house_infantry"
    location = formation["location_ref"]
    formation_ref = formation["formation_ref"]
    commander_ref = formation["commander_ref"]

    assert formation["authorized_strength"] == 5000
    assert formation["personnel"] == 4990
    assert formation["establishment_composition"] == {role: 5000}
    assert force["materialized_people"][commander_ref]["personnel"] == 1
    assert formation_ref not in force.get("external_personnel_allocations", {})

    # Return one current fighter to reserve at this exact location. Existing
    # historical understrength remains; only this physically local body can be
    # reconstituted. The exact named commander remains outside fighting strength.
    cohort_id = next(row["cohort_id"] for row in formation["cohort_composition"] if row.get("count", 0) > 0)
    cohort = force["cohort_ledger"]["cohorts"][cohort_id]
    assert cohort["role"] == role
    formation["composition"][role] -= 1
    formation["personnel"] -= 1
    force["allocated_to_formations"][formation_ref]["composition"][role] -= 1
    force["allocated_to_formations"][formation_ref]["personnel"] -= 1
    cohort["allocated_by_formation"][formation_ref] -= 1
    cohort.setdefault("reserve_by_location", {})[location] = int(cohort.get("reserve_by_location", {}).get(location, 0)) + 1
    force["available_by_role"][role] += 1
    force.setdefault("available_by_location", {}).setdefault(location, {})[role] = int(force.get("available_by_location", {}).get(location, {}).get(role, 0)) + 1
    for row in formation["cohort_composition"]:
        if row.get("cohort_id") == cohort_id:
            row["count"] -= 1
            break

    planner.put(path, formation)
    planner.put(force_path, force)
    result = planner._reconstitute_force_from_local_reserve(force_path, planner.read("state/meta.json")["time"])
    after = planner.read(path)
    after_force = planner.read(force_path)

    assert result["assigned"] >= 1
    assert after["personnel"] >= 4990
    assert after["personnel"] <= after["authorized_strength"]
    assert after_force["materialized_people"][commander_ref]["personnel"] == 1
    assert formation_ref not in after_force.get("external_personnel_allocations", {})
    assert after["establishment_composition"] == {role: 5000}
