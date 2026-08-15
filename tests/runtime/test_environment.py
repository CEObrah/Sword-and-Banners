from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.environment import environment_snapshot
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.store import RepositoryStore


def test_environment_is_deterministic_and_time_evolving(campaign: Path) -> None:
    meta = json.loads((campaign / "state/meta.json").read_text())
    store = RepositoryStore(campaign)
    now = environment_snapshot(store, world_time=meta["time"], location_ref="loc_kanyou")
    same = environment_snapshot(store, world_time=meta["time"], location_ref="loc_kanyou")
    assert now == same
    assert now["source"] == "derived_environment_authority"
    assert now["climate_ref"] == "qin"
    assert now["mechanical_effects"]["travel_time_milli"] >= 1000
    later_time = str(meta["time"])
    from sword_runtime.sim.calendar import CampaignTime
    later_time = str(CampaignTime.parse(later_time).add_hours(12))
    later = environment_snapshot(store, world_time=later_time, location_ref="loc_kanyou")
    assert later["weather_block_ref"] != now["weather_block_ref"]
    assert later["as_of"] != now["as_of"]


def test_environment_keeps_terrain_and_weather_distinct(campaign: Path) -> None:
    meta = json.loads((campaign / "state/meta.json").read_text())
    store = RepositoryStore(campaign)
    env = environment_snapshot(store, world_time=meta["time"], location_ref="loc_kankoku_pass")
    assert env["condition"] in {"clear", "overcast", "fog", "rain", "storm", "snow", "snowstorm"}
    assert env["ground"] in {"dry", "damp", "wet", "muddy", "snow", "ice"}
    assert "terrain" not in env


def test_production_route_hours_consume_environment(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    raw = planner.read("game/data/world/routes.json")["routes"]
    base = next(row["hours"] for row in raw if row["ref"] == "route_kanyou_kankoku")
    adjusted = planner._route_travel_hours("loc_kanyou", "loc_kankoku_pass")
    assert adjusted >= base
    assert adjusted <= int(base * 1.4 + 1)


def test_player_context_exposes_only_current_environment(campaign: Path) -> None:
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-environment-context")
    context = EquipmentAwareCampaignOperations(runtime).play_context()
    env = context["environment"]
    assert env["location_ref"] == context["player"]["location"]
    assert env["source"] == "derived_environment_authority"
    assert "other_locations" not in env


def test_civil_seasonality_and_market_transport_consume_environment(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    raw = planner.read("game/data/mechanics/civil-economy.json")
    rules = planner._civil_rules()
    marker = rules["derived_environment_seasonality"]
    factor = int(marker["agriculture_output_milli"])
    assert factor in {850, 1020, 1080, 1120}
    assert rules["monthly_output_per_worker"]["agricultural_grain_kg"] == raw["monthly_output_per_worker"]["agricultural_grain_kg"] * factor / 1000.0
    conditions = planner._market_transport_conditions("qin", "loc_kanyou")
    assert 0.0 <= conditions["route_factor"] <= 1.0
    assert conditions["environment"]["market_transport_milli"] <= 1000
