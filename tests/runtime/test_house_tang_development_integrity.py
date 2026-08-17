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


def test_integrity_sync_preserves_baseline_and_charges_sword_manor_once(campaign) -> None:
    planner = _planner(campaign)
    planner._sync_sword_manor_derived_state()
    sword = planner.read("state/forces/sword-manor.json")
    treasury = planner.read("state/treasury/treasury-house-tang.json")
    trainees = role_count(sword, "trainee")
    assert trainees == 19940  # 60 trainee officers are materialized from the same conserved bodies
    assert sword["headcount"] == 30000
    assert sum(role_count(sword, str(role)) for role in sword["authorized_by_role"]) + sum(int(v) for v in sword["materialized_people"].values()) == 30000
    assert sword["authorized_strength"] == sum(int(v) for v in sword["authorized_by_role"].values())
    assert "sword_manor_trainee_program_expense_silver" not in treasury["monthly_flow_components"]["cash"]
    assert "trainee_population_requirement_kg" not in treasury["monthly_flow_components"]["food"]
    assert treasury["monthly_flow_components"]["cash"]["sword_manor_core_expense_silver"] == sword["headcount"] * 40
    assert treasury["monthly_flow_components"]["food"]["sword_manor_requirement_kg"] == sword["headcount"] * 48
    assert treasury["stable_monthly_flows"]["expense_silver"] == sum(
        int(v) for v in treasury["monthly_flow_components"]["cash"].values()
    )

