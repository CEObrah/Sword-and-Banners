from __future__ import annotations

from copy import deepcopy

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _write_orphan_formation_credit(
    planner: ProductionCampaignPlanner,
    *,
    credit: float,
    fatigue: int,
    stale_end: CampaignTime,
) -> None:
    path, raw = planner._load_formation("formation_tang_champions_first")
    formation = deepcopy(raw)
    formation["standing_training_time_credit_hours"] = credit
    formation.pop("standing_training_credit_window_start", None)
    formation["standing_training_credit_window_end"] = str(stale_end)
    formation.pop("standing_training_recovery_through", None)
    formation["fatigue"] = fatigue
    formation["training_progress"] = None
    formation.pop("verified_training_hours", None)
    planner.put(path, formation)


def test_new_downtime_window_expires_orphan_credit_and_preserves_recovery(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    stale_end = start.add_seconds(-(5 * 30 * 24 * 3600))
    _write_orphan_formation_credit(
        planner,
        credit=0.761111,
        fatigue=82,
        stale_end=stale_end,
    )
    end = start.add_seconds(283500)  # 78.75 hours, the reproduced Tang Champions interval.

    accrual = planner._accrue_formation_standing_credit(
        "formation_tang_champions_first",
        start,
        end,
        "test-orphan-window-accrual",
    )

    assert accrual["expired_orphan_credit_hours"] == 0.761111
    assert accrual["accrued_hours"] == 22.5
    assert accrual["credit_hours"] == 22.5

    result = planner._consume_formation_standing_credit(
        "formation_tang_champions_first",
        end,
        "test-orphan-window-settlement",
    )

    assert result["consumed_hours"] == 22
    assert result["remaining_credit_hours"] == 0.5
    assert result["recovery"]["elapsed_recovery_hours"] == 78.75
    assert result["recovery"]["recovery_points"] == 26
    assert result["recovery"]["normal_deliberate_capacity_hours"] == 22.5
    assert result["recovery"]["excess_deliberate_hours"] == 0.0
    assert result["recovery"]["overload_fatigue_points"] == 0
    assert result["fatigue"] == 56


def test_direct_orphan_credit_settlement_fails_closed(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    current = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    _write_orphan_formation_credit(
        planner,
        credit=2.25,
        fatigue=40,
        stale_end=current.add_seconds(-86400),
    )

    try:
        planner._consume_formation_standing_credit(
            "formation_tang_champions_first",
            current,
            "test-direct-orphan-settlement",
        )
    except ValueError as exc:
        assert "valid recovery window" in str(exc)
    else:
        raise AssertionError("orphan standing credit must not fabricate a zero-time recovery window")
