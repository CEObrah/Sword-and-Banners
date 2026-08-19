"""Deterministic current environment and its registered Sword mechanics."""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sword_runtime.sim.calendar import CampaignTime

CLIMATE_PATH = "game/data/world/environment-climates.json"
LOCATIONS_PATH = "game/data/world/locations.json"
META_PATH = "state/meta.json"
RUNTIME_PATH = "state/runtime.json"
BLOCK_HOURS = 6
SEASON = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
LIGHT = {"winter": (7, 17), "spring": (6, 19), "summer": (5, 20), "autumn": (6, 18)}
TEMP = ("freezing", "cold", "cool", "mild", "warm", "hot")
AGRICULTURE = {"winter": 850, "spring": 1020, "summer": 1080, "autumn": 1120}
FORAGE = {"winter": 760, "spring": 1060, "summer": 1030, "autumn": 1100}


def _read(reader: Any, path: str) -> Mapping[str, Any]:
    value = reader.read_json(path) if hasattr(reader, "read_json") else reader.read(path)
    if not isinstance(value, Mapping):
        raise ValueError(f"environment source {path} must be an object")
    return value


def _roll(seed: str, *parts: object) -> int:
    text = "\x00".join((seed, *(str(part) for part in parts)))
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big") % 10_000


def _pct(profile: Mapping[str, Any], field: str, season: str, default: int) -> int:
    table = profile.get(field)
    value = table.get(season) if isinstance(table, Mapping) else default
    return max(0, min(100, int(value) if isinstance(value, int) and not isinstance(value, bool) else default)) * 100


def _catalog(reader: Any) -> Mapping[str, Any]:
    data = _read(reader, CLIMATE_PATH)
    if data.get("schema") != "sword-environment-climate-catalog" or not isinstance(data.get("profiles"), Mapping):
        raise ValueError("invalid Sword environment climate catalog")
    return data


def _climate(reader: Any, location_ref: str) -> tuple[str, Mapping[str, Any]]:
    catalog = _catalog(reader)
    climate = "default"
    locations = _read(reader, LOCATIONS_PATH).get("locations", [])
    for row in locations if isinstance(locations, list) else []:
        if isinstance(row, Mapping) and row.get("ref") == location_ref and isinstance(row.get("state"), str):
            climate = str(row["state"])
            break
    else:
        prefixes = catalog.get("location_prefix_states", {})
        matches = [(p, s) for p, s in prefixes.items() if isinstance(p, str) and isinstance(s, str) and location_ref.startswith(p)] if isinstance(prefixes, Mapping) else []
        if matches:
            climate = max(matches, key=lambda item: len(item[0]))[1]
    profiles = catalog["profiles"]
    profile = profiles.get(climate, profiles.get("default"))
    if not isinstance(profile, Mapping):
        raise ValueError("environment climate profile missing")
    return climate, profile


def _seed(reader: Any) -> tuple[str, str]:
    meta = _read(reader, META_PATH)
    campaign_id = str(meta.get("campaign_id", ""))
    if not campaign_id:
        raise ValueError("campaign has no campaign_id")
    seed = meta.get("world_seed")
    if not isinstance(seed, str) or not seed:
        seed = "derived:" + hashlib.sha256(campaign_id.encode()).hexdigest()
    return campaign_id, seed


def _light(at: CampaignTime, season: str) -> str:
    sunrise, sunset = LIGHT[season]
    if at.hour < sunrise - 1 or at.hour >= sunset + 1:
        return "night"
    return "twilight" if at.hour < sunrise or at.hour >= sunset else "day"


def _core(at: CampaignTime, seed: str, climate: str, profile: Mapping[str, Any]) -> dict[str, Any]:
    season = SEASON[at.month]
    key = (at.bce_year, at.month, at.day, at.hour // BLOCK_HOURS)
    table = profile.get("temperature_index_by_season", {})
    base = table.get(season, 0) if isinstance(table, Mapping) else 0
    index = max(-2, min(3, int(base) if isinstance(base, int) and not isinstance(base, bool) else 0))
    index = max(-2, min(3, index + (_roll(seed, climate, *key, "temperature") % 3) - 1))
    temperature = TEMP[index + 2]
    storm = _roll(seed, climate, *key, "storm") < _pct(profile, "storm_chance_pct", season, 4)
    precip = _roll(seed, climate, *key, "precipitation") < _pct(profile, "precipitation_chance_pct", season, 20)
    fog = _roll(seed, climate, *key, "fog") < _pct(profile, "fog_chance_pct", season, 6)
    cloudy = _roll(seed, climate, *key, "cloud") < _pct(profile, "cloud_chance_pct", season, 45)
    frozen = temperature in {"freezing", "cold"}
    if storm:
        condition, precipitation = ("snowstorm", "heavy_snow") if frozen else ("storm", "heavy_rain")
    elif precip:
        condition, precipitation = ("snow", "snow") if frozen else ("rain", "rain")
    elif fog:
        condition, precipitation = "fog", "none"
    else:
        condition, precipitation = ("overcast" if cloudy else "clear"), "none"
    bias = profile.get("wind_bias", 0)
    bias = int(bias) if isinstance(bias, int) and not isinstance(bias, bool) else 0
    wind_roll = _roll(seed, climate, *key, "wind") + max(-20, min(30, bias)) * 100
    wind = "strong" if storm else "calm" if wind_roll < 2000 else "light" if wind_roll < 6500 else "moderate" if wind_roll < 9000 else "strong"
    return {"season": season, "condition": condition, "precipitation": precipitation, "wind": wind, "temperature_band": temperature}


def _effects(core: Mapping[str, Any], light: str, prior: str) -> tuple[str, str, dict[str, int]]:
    condition, temperature, wind = str(core["condition"]), str(core["temperature_band"]), str(core["wind"])
    if condition in {"snow", "snowstorm"} or prior in {"snow", "snowstorm"}:
        ground = "snow"
    elif temperature == "freezing" and prior in {"rain", "storm"}:
        ground = "ice"
    elif condition in {"rain", "storm"} and prior in {"rain", "storm"}:
        ground = "muddy"
    elif condition in {"rain", "storm"}:
        ground = "wet"
    elif prior in {"rain", "storm"}:
        ground = "damp"
    else:
        ground = "dry"
    visible = {"clear": 1000, "overcast": 960, "fog": 620, "rain": 850, "storm": 650, "snow": 800, "snowstorm": 560}[condition]
    visible = max(450, min(1000, visible * {"day": 1000, "twilight": 880, "night": 720}[light] // 1000))
    visibility = "good" if visible >= 900 else "reduced" if visible >= 725 else "poor" if visible >= 575 else "severe"
    weather = {"clear": 1000, "overcast": 1000, "fog": 1060, "rain": 1080, "storm": 1180, "snow": 1120, "snowstorm": 1260}[condition]
    ground_drag = {"dry": 1000, "damp": 1010, "wet": 1040, "muddy": 1120, "snow": 1100, "ice": 1160}[ground]
    travel = min(1400, weather * ground_drag // 1000)
    ranged = {"clear": 1000, "overcast": 990, "fog": 900, "rain": 930, "storm": 840, "snow": 920, "snowstorm": 820}[condition]
    ranged = max(760, min(1000, ranged * max(850, visible) // 1000 - (50 if wind == "strong" else 0)))
    formation = {"dry": 1000, "damp": 995, "wet": 975, "muddy": 930, "snow": 940, "ice": 900}[ground]
    mounted = {"dry": 1000, "damp": 990, "wet": 965, "muddy": 885, "snow": 900, "ice": 840}[ground]
    if condition in {"storm", "snowstorm"}:
        formation, mounted = formation * 960 // 1000, mounted * 940 // 1000
    forage = FORAGE[str(core["season"])] * (900 if condition in {"storm", "snowstorm"} else 960 if condition in {"rain", "snow"} else 1000) // 1000
    fire = 500 if condition in {"storm", "snowstorm"} else 650 if condition in {"rain", "snow"} else 1250 if wind == "strong" else 1100 if wind == "moderate" else 1000
    hazard = (90 if ground == "ice" else 0) + (130 if condition == "snowstorm" else 100 if condition == "storm" else 0)
    return ground, visibility, {
        "travel_time_milli": travel,
        "visibility_milli": visible,
        "ranged_effectiveness_milli": ranged,
        "formation_mobility_milli": max(820, formation),
        "mounted_mobility_milli": max(780, mounted),
        "market_transport_milli": max(720, min(1000, 1_000_000 // max(1000, travel))),
        "forage_availability_milli": max(600, min(1150, forage)),
        "agriculture_output_milli": AGRICULTURE[str(core["season"])],
        "fire_spread_milli": fire,
        "hazard_milli": min(300, hazard),
    }


def environment_snapshot(reader: Any, *, world_time: str, location_ref: str) -> dict[str, Any]:
    at = CampaignTime.parse(world_time)
    campaign_id, seed = _seed(reader)
    climate, profile = _climate(reader, location_ref)
    core = _core(at, seed, climate, profile)
    prior = _core(at.add_hours(-BLOCK_HOURS), seed, climate, profile)
    light = _light(at, str(core["season"]))
    ground, visibility, effects = _effects(core, light, str(prior["condition"]))
    block_start = CampaignTime(at.sort_year, at.month, at.day, (at.hour // BLOCK_HOURS) * BLOCK_HOURS, 0, 0, at.offset)
    weather_next = block_start.add_hours(BLOCK_HOURS)
    sunrise, sunset = LIGHT[str(core["season"])]
    candidates = [CampaignTime(at.sort_year, at.month, at.day, h, 0, 0, at.offset) for h in sorted({sunrise - 1, sunrise, sunset, min(23, sunset + 1)}) if h >= 0]
    light_next = next((value for value in candidates if value > at), None)
    if light_next is None:
        tomorrow = CampaignTime(at.sort_year, at.month, at.day, 0, 0, 0, at.offset).add_days(1)
        light_next = CampaignTime(tomorrow.sort_year, tomorrow.month, tomorrow.day, max(0, LIGHT[SEASON[tomorrow.month]][0] - 1), 0, 0, tomorrow.offset)
    ref = hashlib.sha256(f"{campaign_id}\x00{seed}\x00{climate}\x00{block_start}".encode()).hexdigest()[:16]
    return {
        "source": "derived_environment_authority", "authority_contract": "runtime/contracts/environment.json",
        "as_of": str(at), "location_ref": location_ref, "climate_ref": climate, "season": core["season"], "light": light,
        "condition": core["condition"], "precipitation": core["precipitation"], "wind": core["wind"], "temperature_band": core["temperature_band"],
        "visibility": visibility, "ground": ground, "weather_block_ref": f"env.{ref}", "next_transition_after": str(min(weather_next, light_next)),
        "mechanical_effects": effects,
        "scope": "Derived from campaign time + world seed + static climate. Mutable hazards and institutional schedules remain owned elsewhere.",
    }


def route_travel_factor_milli(reader: Any, *, world_time: str, origin_ref: str, destination_ref: str, base_hours: int) -> int:
    start = environment_snapshot(reader, world_time=world_time, location_ref=origin_ref)
    midpoint = CampaignTime.parse(world_time).add_seconds(max(0, int(base_hours)) * 1800)
    end = environment_snapshot(reader, world_time=str(midpoint), location_ref=destination_ref)
    return max(850, min(1400, (int(start["mechanical_effects"]["travel_time_milli"]) + int(end["mechanical_effects"]["travel_time_milli"]) + 1) // 2))


class EnvironmentMechanicsMixin:
    """Integrate derived conditions into existing Sword mechanics without state writes."""

    def _environment_world_time(self) -> str:
        if hasattr(self, "_world_time"):
            try:
                return str(self._world_time())
            except (TypeError, ValueError, FileNotFoundError):
                pass
        runtime = self.read(RUNTIME_PATH)
        value = runtime.get("world_time") if isinstance(runtime, Mapping) else None
        if isinstance(value, str) and value:
            return value
        value = self.read(META_PATH).get("time")
        if not isinstance(value, str) or not value:
            raise ValueError("campaign has no authoritative world time")
        return value

    def _environment_snapshot(self, location_ref: str, *, world_time: str | None = None) -> dict[str, Any]:
        return environment_snapshot(self, world_time=world_time or self._environment_world_time(), location_ref=location_ref)

    def _environment_adjusted_route_hours(self, origin: str, destination: str, base_hours: int) -> int:
        if base_hours <= 1:
            return max(1, int(base_hours))
        factor = route_travel_factor_milli(self, world_time=self._environment_world_time(), origin_ref=origin, destination_ref=destination, base_hours=base_hours)
        return max(1, int(math.ceil(base_hours * factor / 1000.0)))

    def _find_route(self, origin: str, destination: str, *, mode: str | None = None) -> Mapping[str, Any]:
        route = dict(super()._find_route(origin, destination, mode=mode))
        base = int(route.get("duration_hours", route.get("hours", 1)))
        adjusted = self._environment_adjusted_route_hours(origin, destination, base)
        route.update({"hours": adjusted, "duration_hours": adjusted, "environment_adjusted": adjusted != base})
        return route

    def _formation_route_next(self, origin: str, destination: str, *, formation: Mapping[str, Any] | None = None, at: str | None = None) -> tuple[str, int]:
        next_ref, base = super()._formation_route_next(origin, destination, formation=formation, at=at)
        factor = route_travel_factor_milli(self, world_time=str(at) if at else self._environment_world_time(), origin_ref=origin, destination_ref=next_ref, base_hours=int(base))
        return next_ref, max(1, int(math.ceil(int(base) * factor / 1000.0)))

    def _formation_combat_snapshot(self, formation: Mapping[str, Any], force: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        snapshot = dict(super()._formation_combat_snapshot(formation, force, **kwargs))
        location = formation.get("location_ref")
        if not isinstance(location, str) or not location:
            return snapshot
        env = self._environment_snapshot(location); effects = env["mechanical_effects"]
        snapshot["frontage_equivalent"] = max(1.0, float(snapshot.get("frontage_equivalent", 1.0)) * int(effects["formation_mobility_milli"]) / 1000.0)
        snapshot["ranged_factor"] = max(0.65, float(snapshot.get("ranged_factor", 1.0)) * int(effects["ranged_effectiveness_milli"]) / 1000.0)
        snapshot["mount_factor"] = max(0.65, float(snapshot.get("mount_factor", 1.0)) * int(effects["mounted_mobility_milli"]) / 1000.0)
        hero_factor = float(snapshot.get("hero_disruption_factor", 1.0))
        if hero_factor > 1.0:
            mobility = max(0.35, int(effects["formation_mobility_milli"]) / 1000.0)
            snapshot["hero_disruption_factor"] = 1.0 + (hero_factor - 1.0) * mobility
        snapshot["environment"] = {key: env[key] for key in ("weather_block_ref", "condition", "light", "visibility", "ground")}
        snapshot["environment"]["mechanical_effects"] = deepcopy(effects)
        return snapshot

    def _civil_rules(self) -> Mapping[str, Any]:
        rules = deepcopy(super()._civil_rules()); rates = rules.get("monthly_output_per_worker")
        if not isinstance(rates, Mapping):
            return rules
        season = SEASON[CampaignTime.parse(self._environment_world_time()).month]; factor = AGRICULTURE[season]; updated = dict(rates)
        for key in ("agricultural_grain_kg", "agricultural_fodder_kg", "agricultural_horse_stock"):
            value = updated.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                updated[key] = float(value) * factor / 1000.0
        rules["monthly_output_per_worker"] = updated
        rules["derived_environment_seasonality"] = {"season": season, "agriculture_output_milli": factor, "authority_contract": "runtime/contracts/environment.json"}
        return rules

    def _market_transport_conditions(self, state: str, market_location_ref: str) -> dict[str, Any]:
        result = dict(super()._market_transport_conditions(state, market_location_ref)); env = self._environment_snapshot(market_location_ref); effects = env["mechanical_effects"]
        result["route_factor"] = round(max(0.0, min(1.0, float(result.get("route_factor", 1.0)) * int(effects["market_transport_milli"]) / 1000.0)), 4)
        result["environment"] = {"weather_block_ref": env["weather_block_ref"], "season": env["season"], "condition": env["condition"], "ground": env["ground"], "market_transport_milli": int(effects["market_transport_milli"]), "forage_availability_milli": int(effects["forage_availability_milli"]), "agriculture_output_milli": int(effects["agriculture_output_milli"])}
        return result


__all__ = ["CLIMATE_PATH", "EnvironmentMechanicsMixin", "environment_snapshot", "route_travel_factor_milli"]
