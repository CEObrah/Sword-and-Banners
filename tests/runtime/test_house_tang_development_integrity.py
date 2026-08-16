from __future__ import annotations

import copy

from sword_runtime.cohort_personnel import role_count
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def test_integrity_sync_preserves_baseline_and_scales_with_trainees(campaign) -> None:
    planner = _planner(campaign)
    planner._sync_sword_manor_derived_state()
    sword = planner.read("state/forces/sword-manor.json")
    treasury = planner.read("state/treasury/treasury-house-tang.json")
    trainees = role_count(sword, "trainee")
    assert trainees == 5000
    assert sword["authorized_strength"] == sum(int(v) for v in sword["authorized_by_role"].values())
    assert treasury["monthly_flow_components"]["cash"]["sword_manor_trainee_program_expense_silver"] == 200000
    assert treasury["monthly_flow_components"]["food"]["trainee_population_requirement_kg"] == 240000
    assert treasury["stable_monthly_flows"]["expense_silver"] == 878000
    assert treasury["stable_monthly_flows"]["food_net_change_kg"] == 29952
