from __future__ import annotations

import json
from pathlib import Path

from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.environment import environment_snapshot, route_travel_factor_milli
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.geography import shortest_path
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.store import RepositoryStore


def test_environment_is_deterministic_and_time_evolving(campaign: Path) -> None:
    meta = json.loads((campaign / "state/meta.json").read_text())
    store = RepositoryStore(campaign)
    now = environment_snapshot(store, world_time=meta["time"], location_ref="loc_kanyou")
    same = environment_snapshot(store, world_time=meta["time"], location_ref="loc_kanyou")
    assert now == same
    assert now["authority_contract"] == "runtime/contracts/environment.json"
    assert "source" not in now
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
    assert env["terrain"]["tags"]
    assert "weather_mechanical_effects" in env
    # Weather remains independently inspectable even though the final mechanical
    # effects deliberately combine weather with the canonical ground layer.
    assert set(env["weather_mechanical_effects"]) <= set(env["mechanical_effects"])


def test_production_route_hours_consume_environment(campaign: Path) -> None:
    import math
    planner = ProductionCampaignPlanner(campaign)
    base = int(shortest_path(planner.read, "loc_kanyou", "loc_kankoku_pass", modes=("horse", "foot"))["duration_hours"])
    factor = route_travel_factor_milli(
        planner,
        world_time=str(planner.read("state/runtime.json")["world_time"]),
        origin_ref="loc_kanyou",
        destination_ref="loc_kankoku_pass",
        base_hours=base,
    )
    adjusted = planner._route_travel_hours("loc_kanyou", "loc_kankoku_pass")
    assert factor >= 1000
    assert adjusted == max(1, int(math.ceil(base * factor / 1000.0)))


def test_player_context_exposes_only_current_environment(campaign: Path) -> None:
    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-environment-context")
    context = EquipmentAwareCampaignOperations(runtime).play_context()
    env = context["environment"]
    assert env["location_ref"] == context["player"]["location"]
    assert env["authority_contract"] == "runtime/contracts/environment.json"
    assert "source" not in env
    assert "other_locations" not in env


def test_civil_seasonality_and_market_transport_consume_environment(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    rules = planner._civil_rules()
    assert "derived_environment_seasonality" not in rules
    now = str(planner.read("state/runtime.json")["world_time"])
    planner._settle_private_production("qin", 1, now)
    private = planner.read("state/economy/private/qin.json")
    kanyou = private["local_regions"]["regions"]["loc_kanyou"]
    assert kanyou["production_runtime"]["last_food_close"]["produced_grain_kg"] > 0
    snapshot = planner._environment_snapshot("loc_kanyou")
    assert int(snapshot["mechanical_effects"]["agriculture_output_milli"]) in {850, 1020, 1080, 1120}
    assert int(snapshot["mechanical_effects"]["forage_availability_milli"]) > 0
    conditions = planner._market_transport_conditions("qin", "loc_kanyou")
    assert 0.0 <= conditions["route_factor"] <= 1.0
    assert conditions["environment"]["market_transport_milli"] <= 1000
