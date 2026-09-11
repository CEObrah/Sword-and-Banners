from __future__ import annotations

import json
import math
from pathlib import Path

from sword_runtime.environment import route_travel_factor_milli
from sword_runtime.geography import shortest_path
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.terrain import terrain_context_for_location, terrain_tags_for_label


def test_every_live_route_terrain_and_road_quality_is_registered(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    routes = planner.read("game/data/world/routes.json")["routes"]
    road = planner.read("game/data/mechanics/travel-geography.json")["road_quality_factors"]
    for row in routes:
        terrain_tags_for_label(planner, str(row.get("terrain", "default")))
        assert str(row.get("road_quality", "maintained")) in road


def test_authored_map_contains_real_woodland_and_wetland_ground(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    chu = terrain_context_for_location(planner, "loc_chu_regional_04")
    han = terrain_context_for_location(planner, "loc_han_regional_02")
    qi = terrain_context_for_location(planner, "loc_qi_regional_04")
    assert {"hills", "woodland"} <= set(chu["tags"])
    assert {"hills", "woodland"} <= set(han["tags"])
    assert "wetland" in qi["tags"]
    assert chu["mechanical_effects"]["chariot_mobility_milli"] < 1000
    assert qi["mechanical_effects"]["formation_mobility_milli"] < 1000


def test_route_geometry_charges_static_terrain_once_then_weather(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    origin, destination = "loc_han_regional_02", "loc_han_frontier_fort"
    base = int(shortest_path(planner.read, origin, destination, modes=("formation",))["duration_hours"])
    weather = route_travel_factor_milli(
        planner, world_time=str(planner.read("state/runtime.json")["world_time"]),
        origin_ref=origin, destination_ref=destination, base_hours=base,
    )
    actual = planner._find_route(origin, destination, mode="formation")
    assert int(actual["duration_hours"]) == max(1, int(math.ceil(base * weather / 1000.0)))


def test_mass_battle_and_operational_sector_consume_layered_terrain(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    formation_ref = "formation_han_mobile_screen"
    _fp, formation = planner._load_formation(formation_ref)
    force = planner.read(planner.owner_path(str(formation["owner_force_ref"])))
    wooded = terrain_context_for_location(planner, "loc_han_regional_02")["encoded"]
    wooded_snap = planner._formation_combat_snapshot(formation, force, terrain_kind=wooded)
    plain_snap = planner._formation_combat_snapshot(formation, force, terrain_kind="plain")
    assert wooded_snap["frontage_equivalent"] < plain_snap["frontage_equivalent"]
    sector = planner._battlefield_sector_terrain("loc_han_regional_02", "left")
    assert {"hills", "woodland"} <= set(sector["tags"])
    assert sector["mechanical_effects"]["mounted_mobility_milli"] < 1000
