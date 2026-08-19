from __future__ import annotations
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
    assert after["personnel"] == after["establishment_personnel"]
    assert after["command_structure"]["officer_cadre"]["rank_inventory"] == formation["command_structure"]["officer_cadre"]["rank_inventory"]
