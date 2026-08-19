from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _write_player_credit(
    planner: ProductionCampaignPlanner,
    credit: float,
    *,
    started_at: CampaignTime | None = None,
) -> None:
    player = deepcopy(planner.read("state/player.json"))
    contract = player.setdefault("activity_contract", {})
    contract["verified_hours_per_7d"] = 42
    state = player.setdefault("development_state", {})
    state["standing_training_time_credit_hours"] = credit
    current = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    state["standing_training_credit_window_start"] = str(started_at or current)
    state.pop("standing_training_recovery_through", None)
    planner.put("state/player.json", player)


def _write_formation_credit(
    planner: ProductionCampaignPlanner,
    credit: float,
    *,
    started_at: CampaignTime | None = None,
    fatigue: int | None = None,
) -> None:
    path, raw = planner._load_formation("formation_tang_champions_first")
    formation = deepcopy(raw)
    current = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    formation["standing_training_time_credit_hours"] = credit
    formation["standing_training_credit_window_start"] = str(started_at or current)
    formation.pop("standing_training_recovery_through", None)
    formation["training_progress"] = None
    formation.pop("verified_training_hours", None)
    if fatigue is not None:
        formation["fatigue"] = fatigue
    planner.put(path, formation)


def test_surface_semantics_admit_only_exact_target_ref(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    command = SimpleNamespace(command_type="standing_training_settle")
    planner._validate_command_semantics(command, {"target_ref": "char_tang_wei"})

    try:
        planner._validate_command_semantics(command, {"target_ref": "char_tang_wei", "hours": 4})
    except ValueError as exc:
        assert "only target_ref" in str(exc)
    else:
        raise AssertionError("caller-supplied hours must be rejected")


def test_downtime_policy_auto_settles_whole_player_training_credit(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    _write_player_credit(planner, 0.0)
    _write_formation_credit(planner, 0.0)
    player_before = deepcopy(planner.read("state/player.json"))
    _path, formation_before = planner._load_formation("formation_tang_champions_first")
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    end = start.add_hours(8)

    result = planner._settle_downtime_policy(
        start,
        end,
        {
            "player_standing_training": True,
            "formation_refs": ["formation_tang_champions_first"],
            "household_standing_person_refs": [],
        },
        "test-credit-only-accrual",
    )

    player_after = planner.read("state/player.json")
    _path, formation_after = planner._load_formation("formation_tang_champions_first")
    assert result["settlement_rule"] == "credits_only_during_time_advance"
    assert player_after["skills"] == player_before["skills"]
    # Wei's requested permanent standing plan now consumes whole earned hours
    # automatically; fractional credit remains and EDU banks preserve sub-point progress.
    assert result["player"]["accrued_hours"] == 2.0
    assert result["player_auto_settlement"]["consumed_hours"] == 2
    assert player_after["development_state"]["standing_training_time_credit_hours"] == 0.0
    assert player_after["development_state"]["settled_training_hours"] == player_before["development_state"]["settled_training_hours"] + 2
    assert formation_after.get("training_progress") is None
    assert formation_after["standing_training_time_credit_hours"] > 2.6
    assert formation_after.get("cohesion") == formation_before.get("cohesion")


def test_player_credit_settlement_consumes_whole_hours_without_time(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    _write_player_credit(planner, 1.570833)
    current_text = str(planner.read("state/runtime.json")["world_time"])
    current = CampaignTime.parse(current_text)
    before = deepcopy(planner.read("state/player.json"))

    result = planner._consume_player_standing_credit(current, "test-player-standing-settle")
    after = planner.read("state/player.json")

    assert result["consumed_hours"] == 1
    assert result["remaining_credit_hours"] == 0.570833
    assert after["skills"]["Formation Command"] == before["skills"]["Formation Command"]
    assert after["development_state"]["settled_training_hours"] == int(before.get("development_state", {}).get("settled_training_hours", 0)) + 1
    assert after["development_state"]["skill_edu_banks"]["Formation Command"] > 0
    assert result["focus_results"][0]["attribute_development"]
    assert after["development_state"]["attribute_edu_banks"]
    assert str(planner.read("state/runtime.json")["world_time"]) == current_text


def test_formation_credit_settlement_consumes_whole_hours_without_time(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    _write_formation_credit(planner, 2.094444)
    current_text = str(planner.read("state/runtime.json")["world_time"])
    current = CampaignTime.parse(current_text)
    _path, before = planner._load_formation("formation_tang_champions_first")

    result = planner._consume_formation_standing_credit(
        "formation_tang_champions_first",
        current,
        "test-formation-standing-settle",
    )
    _path, after = planner._load_formation("formation_tang_champions_first")

    assert result["consumed_hours"] == 2
    assert result["remaining_credit_hours"] == 0.094444
    assert int(after["training_progress"]) == 1
    assert int(after["cohesion"]) == min(100, int(before["cohesion"]) + 1)
    assert int(after["readiness"]) == int(before["readiness"])
    assert int(after["fatigue"]) == min(100, int(before["fatigue"]) + 1)
    assert int(after["verified_training_hours"]) == 2
    capability = result["capability_development"]
    assert capability["model"] == "cohort_means_with_banked_edu"
    assert capability["represented_personnel"] == 500
    assert capability["verified_training_hours_per_person"] >= 2.0
    assert "Sword" in capability["trained_skill_means"]
    assert "Strength" in capability["trained_attribute_means"]
    assert capability["skill_mean_changes"] or capability["skill_edu_banks"]
    assert capability["attribute_mean_changes"] or capability["attribute_edu_banks"]
    assert str(planner.read("state/runtime.json")["world_time"]) == current_text


def test_multiday_sustainable_training_nets_nightly_recovery(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    current = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    started = current.add_hours(-11 * 24)
    _write_formation_credit(planner, 88.761111, started_at=started, fatigue=62)

    result = planner._consume_formation_standing_credit(
        "formation_tang_champions_first",
        current,
        "test-multiday-standing-recovery",
    )
    _path, after = planner._load_formation("formation_tang_champions_first")

    assert result["consumed_hours"] == 88
    assert result["recovery"]["normal_deliberate_capacity_hours"] == 88.0
    assert result["recovery"]["excess_deliberate_hours"] == 0.0
    assert result["recovery"]["recovery_points"] == 88
    assert int(after["fatigue"]) == 0


def test_standing_recovery_cursor_prevents_double_recovery(campaign):
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    current = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    started = current.add_hours(-11 * 24)
    _write_formation_credit(planner, 88.761111, started_at=started, fatigue=100)

    first = planner._consume_formation_standing_credit(
        "formation_tang_champions_first",
        current,
        "test-recovery-cursor-first",
    )
    assert first["fatigue"] == 12

    end = current.add_hours(24)
    planner._accrue_formation_standing_credit(
        "formation_tang_champions_first",
        current,
        end,
        "test-recovery-cursor-accrual",
    )
    second = planner._consume_formation_standing_credit(
        "formation_tang_champions_first",
        end,
        "test-recovery-cursor-second",
    )
    assert second["recovery"]["elapsed_recovery_hours"] == 24.0
    assert second["recovery"]["recovery_points"] == 8
    assert second["fatigue"] == 4
