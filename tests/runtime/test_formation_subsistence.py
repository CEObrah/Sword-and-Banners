from __future__ import annotations

import copy

from sword_runtime.formation_subsistence import (
    _consume_one,
    _interval_seconds,
    _unsettled_seconds,
    settle_player_formation_subsistence,
    sync_player_formation_subsistence_host,
)
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


HOUSE_GUARD = "formation_tang_wei_house_guard"
QIN_UNIT = "formation_qin_wei_unit_01"


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = planner.read("state/meta.json")
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def test_subsistence_host_registration_is_single_and_daily(campaign):
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_player_formation_subsistence_host(planner, runtime)
    sync_player_formation_subsistence_host(planner, runtime)

    hosts = [row for row in runtime["hosts"].values() if row.get("kind") == "player_formation_subsistence"]
    events = [row for row in runtime["events"] if row.get("target_host") == "host_player_formation_subsistence"]
    assert len(hosts) == 1
    assert hosts[0]["recurrence_seconds"] == 24 * 3600
    assert hosts[0]["owner_ref"] == "runtime_persistent_formation_subsistence"
    assert len(events) == 1
    assert events[0]["due_at"] == hosts[0]["next_due"]


def test_house_guard_consumes_registered_daily_carried_food(campaign):
    planner = _planner(campaign)
    path = planner.owner_path(HOUSE_GUARD)
    formation = copy.deepcopy(planner.read(path))
    formation["personnel"] = 3000
    formation.setdefault("mounts", {}).clear()
    formation.setdefault("logistics", {})["food_kg"] = 5000
    formation["logistics"]["fodder_kg"] = 0
    formation["command_authority"] = "char_tang_wei"
    formation.pop("temporary", None)
    planner.put(path, formation)

    at = str(planner.read("state/runtime.json")["world_time"])
    result = _consume_one(planner, HOUSE_GUARD, seconds=24 * 3600, at=at)
    after = planner.read(path)

    assert result["food_required_kg"] == 2400
    assert after["logistics"]["food_kg"] == 2600
    assert after["subsistence"]["food_from_carried_kg"] == 2400
    assert after["subsistence"]["food_shortfall_kg"] == 0


def test_qin_unit_under_wei_command_is_in_subsistence_scope(campaign):
    planner = _planner(campaign)
    path = planner.owner_path(QIN_UNIT)
    formation = copy.deepcopy(planner.read(path))
    formation["personnel"] = 2000
    formation.setdefault("mounts", {}).clear()
    formation.setdefault("logistics", {})["food_kg"] = 10000
    formation["logistics"]["fodder_kg"] = 0
    formation["administrative_owner"] = "state_qin"
    formation["command_authority"] = "char_tang_wei"
    formation.pop("temporary", None)
    planner.put(path, formation)

    at = str(planner.read("state/runtime.json")["world_time"])
    _consume_one(planner, QIN_UNIT, seconds=24 * 3600, at=at)
    after = planner.read(path)
    assert after["logistics"]["food_kg"] == 8400
    assert after["subsistence"]["food_required_kg"] == 1600


def test_state_owned_npc_commanded_formation_also_consumes_subsistence(campaign):
    planner = _planner(campaign)
    path = planner.owner_path(QIN_UNIT)
    formation = copy.deepcopy(planner.read(path))
    formation["personnel"] = 2000
    formation.setdefault("mounts", {}).clear()
    formation.setdefault("logistics", {})["food_kg"] = 10000
    formation["logistics"]["fodder_kg"] = 0
    formation["administrative_owner"] = "state_qin"
    formation["command_authority"] = "char_qin_border_general"
    formation.pop("temporary", None)
    planner.put(path, formation)

    at = str(planner.read("state/runtime.json")["world_time"])
    result = _consume_one(planner, QIN_UNIT, seconds=24 * 3600, at=at)
    after = planner.read(path)

    assert result["food_required_kg"] == 1600
    assert after["logistics"]["food_kg"] == 8400
    assert after["subsistence"]["status"] == "sustained"


def test_temporary_formation_arrangement_is_not_a_second_food_owner(campaign):
    planner = _planner(campaign)
    path = planner.owner_path(QIN_UNIT)
    formation = copy.deepcopy(planner.read(path))
    formation["personnel"] = 2000
    formation.setdefault("logistics", {})["food_kg"] = 10000
    formation["temporary"] = True
    planner.put(path, formation)

    at = str(planner.read("state/runtime.json")["world_time"])
    result = _consume_one(planner, QIN_UNIT, seconds=24 * 3600, at=at)
    after = planner.read(path)

    assert result is None
    assert after["logistics"]["food_kg"] == 10000


def test_short_carried_supply_may_draw_only_from_colocated_material_depot(campaign):
    planner = _planner(campaign)
    path = planner.owner_path(HOUSE_GUARD)
    formation = copy.deepcopy(planner.read(path))
    formation["personnel"] = 1000
    formation.setdefault("mounts", {}).clear()
    formation.setdefault("logistics", {})["food_kg"] = 200
    formation["logistics"]["fodder_kg"] = 0
    formation["command_authority"] = "char_tang_wei"
    formation["location_ref"] = "loc_qin_eastern_depot"
    formation.pop("temporary", None)
    planner.put(path, formation)

    depot_path = "state/depots/qin.json"
    depot = copy.deepcopy(planner.read(depot_path))
    depot["location_ref"] = "loc_qin_eastern_depot"
    depot.setdefault("stocks", {})["grain_kg"] = 5000
    planner.put(depot_path, depot)
    planner._material_depot = lambda _formation: (depot_path, copy.deepcopy(planner.read(depot_path)))

    at = str(planner.read("state/runtime.json")["world_time"])
    _consume_one(planner, HOUSE_GUARD, seconds=24 * 3600, at=at)
    after = planner.read(path)
    depot_after = planner.read(depot_path)

    assert after["logistics"]["food_kg"] == 0
    assert after["subsistence"]["food_required_kg"] == 800
    assert after["subsistence"]["food_from_carried_kg"] == 200
    assert after["subsistence"]["food_from_depot_kg"] == 600
    assert depot_after["stocks"]["grain_kg"] == 4400


def test_daily_interval_resumes_from_last_exact_settlement(campaign):
    planner = _planner(campaign)
    path = planner.owner_path(HOUSE_GUARD)
    formation = copy.deepcopy(planner.read(path))
    now = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    due = now.add_seconds(24 * 3600)
    formation["subsistence"] = {"last_settled_at": str(due.add_seconds(-6 * 3600))}

    assert _interval_seconds(formation, str(due)) == 6 * 3600


def test_partial_stationary_gap_can_be_settled_before_movement(campaign):
    planner = _planner(campaign)
    path = planner.owner_path(HOUSE_GUARD)
    formation = copy.deepcopy(planner.read(path))
    start = CampaignTime.parse(str(planner.read("state/runtime.json")["world_time"]))
    command_start = start.add_seconds(22 * 3600)

    assert _unsettled_seconds(
        formation,
        str(command_start),
        fallback_start_text=str(start),
    ) == 22 * 3600

    formation["subsistence"] = {"last_settled_at": str(start.add_seconds(10 * 3600))}
    assert _unsettled_seconds(
        formation,
        str(command_start),
        fallback_start_text=str(start),
    ) == 12 * 3600


def test_command_target_can_defer_daily_settlement_until_stale_copy_is_finished(campaign):
    planner = _planner(campaign)
    path = planner.owner_path(HOUSE_GUARD)
    formation = copy.deepcopy(planner.read(path))
    formation["personnel"] = 3000
    formation.setdefault("mounts", {}).clear()
    formation.setdefault("logistics", {})["food_kg"] = 5000
    formation["logistics"]["fodder_kg"] = 0
    formation["command_authority"] = "char_tang_wei"
    formation.pop("temporary", None)
    planner.put(path, formation)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_player_formation_subsistence_host(planner, runtime)
    host = runtime["hosts"]["host_player_formation_subsistence"]
    due = str(host["next_due"])
    planner._subsistence_deferred_refs = {HOUSE_GUARD}
    planner._subsistence_explicit_covered_refs = set()
    planner._subsistence_deferred_seconds = {}

    before = int(planner.read(path)["logistics"]["food_kg"])
    settle_player_formation_subsistence(planner, host, due)
    assert int(planner.read(path)["logistics"]["food_kg"]) == before
    assert planner._subsistence_deferred_seconds[HOUSE_GUARD] == 24 * 3600

    _consume_one(planner, HOUSE_GUARD, seconds=planner._subsistence_deferred_seconds[HOUSE_GUARD], at=due)
    assert int(planner.read(path)["logistics"]["food_kg"]) == before - 2400


def test_movement_covered_target_is_not_double_charged_by_daily_host(campaign):
    planner = _planner(campaign)
    path = planner.owner_path(HOUSE_GUARD)
    formation = copy.deepcopy(planner.read(path))
    formation["personnel"] = 3000
    formation.setdefault("mounts", {}).clear()
    formation.setdefault("logistics", {})["food_kg"] = 5000
    formation["logistics"]["fodder_kg"] = 0
    formation["command_authority"] = "char_tang_wei"
    formation.pop("temporary", None)
    planner.put(path, formation)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    sync_player_formation_subsistence_host(planner, runtime)
    host = runtime["hosts"]["host_player_formation_subsistence"]
    due = str(host["next_due"])
    planner._subsistence_deferred_refs = {HOUSE_GUARD}
    planner._subsistence_explicit_covered_refs = {HOUSE_GUARD}
    planner._subsistence_deferred_seconds = {}

    before = int(planner.read(path)["logistics"]["food_kg"])
    settle_player_formation_subsistence(planner, host, due)
    assert int(planner.read(path)["logistics"]["food_kg"]) == before
    assert HOUSE_GUARD not in planner._subsistence_deferred_seconds
