from __future__ import annotations

import copy
import json
import subprocess

from sword_runtime.battle_sustainment import (
    apply_role_absence,
    consume_frontline_ammunition,
    fatigue_gain_after_rotations,
    initialize_battle_sustainment,
    plan_hundred_sustainment_rotation,
)


def _rules(campaign):
    return json.loads((campaign / "game/data/mechanics/battlefield-sustainment.json").read_text())


def _formation(*, role: str, personnel: int = 1000, arrows: int = 0, bolts: int = 0, remounts: int = 0, fatigue: int = 20, spares: int = 0):
    return {
        "formation_ref": "formation_sustainment_test",
        "personnel": personnel,
        "authorized_strength": personnel,
        "composition": {role: personnel},
        "training_progress": 90,
        "cohesion": 90,
        "morale": 90,
        "readiness": 90,
        "fatigue": fatigue,
        "logistics": {
            "war_arrows": arrows,
            "war_bolts": bolts,
            "remount_horses": remounts,
        },
        "spare_outfitting_sets": {"standard_role_sets": spares},
    }


def _archer_rows(count: int = 1000, carried: int = 30):
    return [{
        "role": "archer",
        "count": count,
        "ammunition_resource": "war_arrows",
        "carried_ammunition": carried,
        "mount_required_units": 0,
    }]


def _cavalry_rows(count: int = 1000):
    return [{
        "role": "cavalry",
        "count": count,
        "carried_ammunition": 0,
        "mount_required_units": count,
    }]


def _high_command():
    return {
        "internal_100_command_score": 120,
        "internal_100_person_lite_coverage": 1.0,
        "acting_command_score": 120,
        "unit_staffing_ratio": 1.0,
    }


def _low_command():
    return {
        "internal_100_command_score": 0,
        "internal_100_person_lite_coverage": 0.0,
        "acting_command_score": 0,
        "unit_staffing_ratio": 0.5,
    }


def test_archers_have_one_frontline_load_and_hq_stock_is_not_magical(campaign):
    formation = _formation(role="archer", arrows=60_000)
    rows = _archer_rows()
    state = initialize_battle_sustainment(formation, rows, initial_shields={}, initial_armor={})

    # 1,000 archers x 30 arrows = one carried frontline load. The other 30,000
    # remain physically at the formation field HQ/baggage reserve.
    assert state["frontline_ammunition"]["war_arrows"] == 30_000
    assert state["hq_ammunition"]["war_arrows"] == 30_000

    consume_frontline_ammunition(state, {"consumed_by_resource": {"war_arrows": 30_000}})
    assert state["frontline_ammunition"]["war_arrows"] == 0

    no_hq = copy.deepcopy(state)
    no_hq["hq_ammunition"]["war_arrows"] = 0
    result = plan_hundred_sustainment_rotation(
        no_hq,
        formation,
        rows,
        command_effects=_high_command(),
        current_shields={},
        current_armor={},
        current_mounts=0,
        breached_sectors=0,
        next_phase_hours=2.0,
        rules=_rules(campaign),
    )
    assert result["rotation_personnel"] == 0
    assert result["reason"] == "no_physical_resupply_or_recovery_need"
    assert no_hq["frontline_ammunition"]["war_arrows"] == 0


def test_resupply_uses_forward_carriers_when_safe_and_hundred_rotation_when_command_is_weak(campaign):
    formation = _formation(role="archer", arrows=60_000)
    rows = _archer_rows()
    rules = _rules(campaign)

    high = initialize_battle_sustainment(formation, rows, initial_shields={}, initial_armor={})
    low = copy.deepcopy(high)
    for state in (high, low):
        consume_frontline_ammunition(state, {"consumed_by_resource": {"war_arrows": 30_000}})

    high_result = plan_hundred_sustainment_rotation(
        high,
        formation,
        rows,
        command_effects=_high_command(),
        current_shields={},
        current_armor={},
        current_mounts=0,
        breached_sectors=0,
        next_phase_hours=2.0,
        rules=rules,
    )
    low_result = plan_hundred_sustainment_rotation(
        low,
        formation,
        rows,
        command_effects=_low_command(),
        current_shields={},
        current_armor={},
        current_mounts=0,
        breached_sectors=0,
        next_phase_hours=2.0,
        rules=rules,
    )

    assert high_result["command_scale_personnel"] == 100
    assert high_result["mode"] == "forward_carrier_delivery"
    assert high_result["rotation_personnel"] == 0
    assert 0 < high_result["carrier_personnel"] < 100
    assert high_result["rejoin_mode"] == "carriers_return_to_parent_hundred_after_delivery"

    assert low_result["mode"] == "hundred_rotation"
    assert low_result["rotation_personnel"] >= 100
    assert low_result["rotation_personnel"] % 100 == 0
    assert low_result["carrier_personnel"] == 0
    assert high_result["ammunition_moved_from_hq"]["war_arrows"] > low_result["ammunition_moved_from_hq"]["war_arrows"] > 0
    assert high["frontline_ammunition"]["war_arrows"] + high["hq_ammunition"]["war_arrows"] == 30_000
    assert low["frontline_ammunition"]["war_arrows"] + low["hq_ammunition"]["war_arrows"] == 30_000

    high_participating = apply_role_absence(rows, high_result["effective_absence_next_phase_by_role"])
    low_participating = apply_role_absence(rows, low_result["effective_absence_next_phase_by_role"])
    assert 0 < low_participating[0]["count"] < high_participating[0]["count"] < rows[0]["count"]


def test_hq_rotation_can_draw_only_real_spare_shields_and_remount_horses(campaign):
    rules = _rules(campaign)

    infantry = _formation(role="line_infantry", spares=40)
    infantry_rows = [{"role": "line_infantry", "count": 1000, "carried_ammunition": 0, "mount_required_units": 0}]
    infantry_state = initialize_battle_sustainment(
        infantry,
        infantry_rows,
        initial_shields={"line_infantry": 1000},
        initial_armor={"line_infantry": 1000},
    )
    infantry_result = plan_hundred_sustainment_rotation(
        infantry_state,
        infantry,
        infantry_rows,
        command_effects=_high_command(),
        current_shields={"line_infantry": 900},
        current_armor={"line_infantry": 1000},
        current_mounts=0,
        breached_sectors=0,
        next_phase_hours=2.0,
        rules=rules,
    )
    assert infantry_result["shield_replacements_by_role"]["line_infantry"] == 40
    assert infantry_result["outfitting_sets_consumed"]["standard_role_sets"] == 40
    assert infantry_state["spare_outfitting_available"]["standard_role_sets"] == 0

    cavalry = _formation(role="cavalry", remounts=80)
    cavalry_rows = _cavalry_rows()
    cavalry_state = initialize_battle_sustainment(cavalry, cavalry_rows, initial_shields={}, initial_armor={})
    cavalry_result = plan_hundred_sustainment_rotation(
        cavalry_state,
        cavalry,
        cavalry_rows,
        command_effects=_high_command(),
        current_shields={},
        current_armor={},
        current_mounts=900,
        breached_sectors=0,
        next_phase_hours=2.0,
        rules=rules,
    )
    assert cavalry_result["remount_horses_issued"] == 80
    assert cavalry_state["remount_horses_available"] == 0


def test_reserve_recovery_is_bounded_and_cannot_erase_battle_fatigue(campaign):
    rules = _rules(campaign)
    formation = _formation(role="line_infantry", fatigue=85)
    rows = [{"role": "line_infantry", "count": 1000, "carried_ammunition": 0, "mount_required_units": 0}]
    state = initialize_battle_sustainment(formation, rows, initial_shields={}, initial_armor={})

    result = plan_hundred_sustainment_rotation(
        state,
        formation,
        rows,
        command_effects=_high_command(),
        current_shields={},
        current_armor={},
        current_mounts=0,
        breached_sectors=0,
        next_phase_hours=2.0,
        rules=rules,
    )
    assert result["needs"]["fatigue"] is True
    assert result["rest_person_hours"] > 0
    assert result["rejoin_mode"] == "held_rearward_then_rejoin_when_commander_calls"

    reduced = fatigue_gain_after_rotations(
        15,
        personnel=1000,
        battle_hours=3.0,
        rest_person_hours=state["rest_person_hours"],
        rules=rules,
    )
    assert rules["minimum_battle_fatigue_gain"] <= reduced < 15


def test_reserve_relief_duty_increases_safe_rotation_capacity(campaign):
    rules = _rules(campaign)
    rows = _archer_rows()
    ordinary = _formation(role="archer", arrows=60_000)
    reserve = copy.deepcopy(ordinary)
    reserve["current_unit_duty"] = {"phase": "battle", "duty_id": "reserve_relief"}

    ordinary_state = initialize_battle_sustainment(ordinary, rows, initial_shields={}, initial_armor={})
    reserve_state = initialize_battle_sustainment(reserve, rows, initial_shields={}, initial_armor={})
    for state in (ordinary_state, reserve_state):
        consume_frontline_ammunition(state, {"consumed_by_resource": {"war_arrows": 30_000}})

    command = {
        "internal_100_command_score": 40,
        "internal_100_person_lite_coverage": 1.0,
        "acting_command_score": 40,
        "unit_staffing_ratio": 0.8,
    }
    normal_result = plan_hundred_sustainment_rotation(
        ordinary_state, ordinary, rows, command_effects=command,
        current_shields={}, current_armor={}, current_mounts=0,
        breached_sectors=0, next_phase_hours=2.0, rules=rules,
    )
    reserve_result = plan_hundred_sustainment_rotation(
        reserve_state, reserve, rows, command_effects=command,
        current_shields={}, current_armor={}, current_mounts=0,
        breached_sectors=0, next_phase_hours=2.0, rules=rules,
    )

    assert reserve_result["rotation_capacity_personnel"] > normal_result["rotation_capacity_personnel"]
    assert reserve_result["rotation_personnel"] >= normal_result["rotation_personnel"]


def test_sustainment_duty_is_internal_to_the_100_person_command_layer(campaign):
    registry = json.loads((campaign / "game/data/mechanics/unit-duties.json").read_text())
    duty = registry["duties"]["sustainment_rotation"]
    assert duty["internal_only"] is True
    assert duty["command_scale_personnel"] == 100
    assert "sustainment_rotation" in registry["internal_duties_by_phase"]["battle"]
    # It is not a whole-formation assignment competing with fix/hold, maneuver,
    # screening, or the actual operational reserve role.
    assert "sustainment_rotation" not in registry["phases"]["battle"]


def test_strategic_resupply_transfers_only_conserved_depot_remounts(campaign):
    from conftest import execute_internal

    depot_path = campaign / "state/depots/qin.json"
    depot = json.loads(depot_path.read_text())
    depot.setdefault("mounts", {})["horse"] = 25
    depot_path.write_text(json.dumps(depot, indent=2) + "\n")
    subprocess.run(["git", "-C", str(campaign), "add", str(depot_path.relative_to(campaign))], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "stage physical remount reserve"], check=True)

    formation_ref = "formation_qin_reserve_infantry_02"
    owner_index = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    formation_path = campaign / owner_index[formation_ref]
    before = json.loads(formation_path.read_text())
    before_carried = int(before.get("logistics", {}).get("remount_horses", 0) or 0)

    execute_internal(campaign, "resupply", {"formation_ref": formation_ref, "remount_horses": 12})
    after = json.loads(formation_path.read_text())
    depot_after = json.loads(depot_path.read_text())
    assert int(after["logistics"]["remount_horses"]) == before_carried + 12
    assert int(depot_after["mounts"]["horse"]) == 13

    # The remaining physical stock is authoritative; a request for more fails
    # rather than creating horses at the formation.
    try:
        execute_internal(campaign, "resupply", {"formation_ref": formation_ref, "remount_horses": 14})
    except ValueError as exc:
        assert "depot lacks exact requested remount_horses" in str(exc)
    else:
        raise AssertionError("remount overdraw should fail closed")
