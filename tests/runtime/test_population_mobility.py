from __future__ import annotations

import copy

from sword_runtime.population_mobility import TRANSIT_STRATUM
from sword_runtime.production_planner import ProductionCampaignPlanner


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _civilian(row):
    return int(row.get("civilian_population", 0))


def test_same_owner_migration_is_in_transit_without_changing_population_total(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    before = copy.deepcopy(planner.read("state/population/jo.json"))
    before_origin = _civilian(before["local_population"]["sites"]["loc_jo_mountain_region"])
    before_dest = _civilian(before["local_population"]["sites"]["loc_jo_city"])
    cohort = planner._queue_population_move(
        source_population_path="state/population/jo.json",
        destination_population_path="state/population/jo.json",
        origin_site_ref="loc_jo_mountain_region",
        destination_site_ref="loc_jo_city",
        count=100,
        departed_at=at,
        basis="test internal household move",
    )
    assert cohort and cohort["count"] == 100
    travelling = planner.read("state/population/jo.json")
    assert travelling["population_total"] == before["population_total"]
    assert travelling["strata"][TRANSIT_STRATUM] == 100
    assert _civilian(travelling["local_population"]["sites"]["loc_jo_mountain_region"]) == before_origin - 100
    assert _civilian(travelling["local_population"]["sites"]["loc_jo_city"]) == before_dest

    planner._settle_population_mobility_arrival({"cohort_ref": cohort["migration_ref"]}, cohort["arrives_at"])
    arrived = planner.read("state/population/jo.json")
    assert arrived["population_total"] == before["population_total"]
    assert TRANSIT_STRATUM not in arrived["strata"]
    assert _civilian(arrived["local_population"]["sites"]["loc_jo_city"]) == before_dest + 100
    assert sum(int(v) for v in arrived["strata"].values()) == arrived["population_total"]
    registry = planner.read("state/mobility/population-transit.json")
    assert cohort["migration_ref"] not in registry["cohorts"]
    assert "settled_receipts" not in registry


def test_cross_owner_migration_transfers_population_only_on_arrival(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    jo_before = copy.deepcopy(planner.read("state/population/jo.json"))
    wei_before = copy.deepcopy(planner.read("state/population/wei.json"))
    world_before = jo_before["population_total"] + wei_before["population_total"]
    cohort = planner._queue_population_move(
        source_population_path="state/population/jo.json",
        destination_population_path="state/population/wei.json",
        origin_site_ref="loc_jo_mountain_region",
        destination_site_ref="loc_wei_regional_03",
        count=100,
        departed_at=at,
        basis="test cross-border household move",
    )
    assert cohort and cohort["count"] == 100
    jo_transit = planner.read("state/population/jo.json")
    assert jo_transit["population_total"] == jo_before["population_total"]
    assert jo_transit["strata"][TRANSIT_STRATUM] == 100
    assert planner.read("state/population/wei.json")["population_total"] == wei_before["population_total"]

    planner._settle_population_mobility_arrival({"cohort_ref": cohort["migration_ref"]}, cohort["arrives_at"])
    jo_after = planner.read("state/population/jo.json")
    wei_after = planner.read("state/population/wei.json")
    assert jo_after["population_total"] == jo_before["population_total"] - 100
    assert wei_after["population_total"] == wei_before["population_total"] + 100
    assert jo_after["population_total"] + wei_after["population_total"] == world_before
    assert sum(int(v) for v in jo_after["strata"].values()) == jo_after["population_total"]
    assert sum(int(v) for v in wei_after["strata"].values()) == wei_after["population_total"]
    registry = planner.read("state/mobility/population-transit.json")
    assert cohort["migration_ref"] not in registry["cohorts"]
    assert "settled_receipts" not in registry


def test_autonomous_jo_households_follow_real_city_headroom(campaign) -> None:
    planner = _planner(campaign)
    paths = planner._population_owner_paths_for_mobility()
    assert "state/population/jo.json" in paths
    assert "state/population/tang-manor.json" not in paths
    # Newly registered exact population owners are discovered without a duplicated
    # hot-state registry.
    assert "state/population/northern_steppe.json" in paths
    at = str(planner._world_time())
    before = copy.deepcopy(planner.read("state/population/jo.json"))
    planner._autonomy_population_mobility({"owner_ref": "population_mobility"}, 1, at)
    owner = planner.read("state/mobility/population-transit.json")
    active = [row for row in owner["cohorts"].values() if row.get("status") == "in_transit"]
    assert active
    jo_move = next(row for row in active if row["origin_site_ref"] == "loc_jo_mountain_region")
    assert jo_move["destination_site_ref"] == "loc_jo_city"
    after_departure = planner.read("state/population/jo.json")
    assert after_departure["population_total"] == before["population_total"]
    assert after_departure["strata"][TRANSIT_STRATUM] == jo_move["count"]


def test_tang_manor_private_civilian_owner_tracks_departure(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    qin_before = copy.deepcopy(planner.read("state/population/qin.json"))
    tang_before = copy.deepcopy(planner.read("state/population/tang-manor.json"))
    cohort = planner._queue_population_move(
        source_population_path="state/population/qin.json",
        destination_population_path="state/population/qin.json",
        origin_site_ref="loc_tang_manor",
        destination_site_ref="loc_kanyou",
        count=50,
        departed_at=at,
        basis="test Tang Manor household departure",
    )
    assert cohort and cohort["count"] == 50
    assert planner.read("state/population/qin.json")["population_total"] == qin_before["population_total"]
    tang_departed = planner.read("state/population/tang-manor.json")
    assert tang_departed["population_total"] == tang_before["population_total"] - 50
    assert sum(int(v) for v in tang_departed["strata"].values()) == tang_departed["population_total"]
