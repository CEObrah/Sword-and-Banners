"""Physical strategic river-crossing state and movement constraints.

Static river/bridge/ferry geometry belongs to game/data/world/routes.json.  This
module combines that cold blueprint with one compact mutable state owner.  It
never creates population, troops, wagons, or supplies.  Crossing damage changes
capacity and travel time; it does not cap how large an army may exist.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any, Callable

CROSSING_STATE_PATH = "state/geography/strategic-crossings.json"
CROSSING_MECHANICS_PATH = "game/data/mechanics/strategic-crossings.json"


def _read_optional(read: Callable[[str], Mapping[str, Any]], path: str) -> Mapping[str, Any]:
    try:
        value = read(path)
    except (FileNotFoundError, KeyError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _state_row(read: Callable[[str], Mapping[str, Any]], route_ref: str) -> Mapping[str, Any]:
    doc = _read_optional(read, CROSSING_STATE_PATH)
    rows = doc.get("crossings", {}) if isinstance(doc, Mapping) else {}
    row = rows.get(str(route_ref), {}) if isinstance(rows, Mapping) else {}
    return row if isinstance(row, Mapping) else {}


def crossing_operational_profile(read: Callable[[str], Mapping[str, Any]], route: Mapping[str, Any]) -> dict[str, Any] | None:
    static = route.get("water_crossing")
    if not isinstance(static, Mapping):
        return None
    mechanics = _read_optional(read, CROSSING_MECHANICS_PATH)
    state = _state_row(read, str(route.get("ref", "")))
    stage = str(state.get("water_stage", "normal"))
    stage_cfg = (mechanics.get("water_stage_factors", {}) or {}).get(stage, {}) if isinstance(mechanics, Mapping) else {}
    if not isinstance(stage_cfg, Mapping):
        stage_cfg = {}
    throughput_factor = max(0.0, float(stage_cfg.get("throughput", 1.0)))
    ferry_factor = max(0.0, float(stage_cfg.get("ferry", throughput_factor)))

    bridge_condition = max(0.0, min(100.0, float(state.get("bridge_condition_percent", 100.0))))
    bridge_open = bridge_condition > 0.0 and bool(state.get("bridge_open", True))
    bridge_width = max(0.0, float(static.get("bridge_width_m", 0.0)))
    bridge_load = max(0.0, float(static.get("bridge_load_capacity_tonnes", 0.0)))
    bridge_cfg = mechanics.get("bridge", {}) if isinstance(mechanics.get("bridge"), Mapping) else {}
    cond_exponent = max(0.1, float(bridge_cfg.get("condition_capacity_exponent", 1.0)))
    condition_factor = (bridge_condition / 100.0) ** cond_exponent if bridge_open else 0.0
    bridge_troops = int(math.floor(bridge_width * float(bridge_cfg.get("troops_per_m_width_per_day", 6500.0)) * condition_factor * throughput_factor)) if bridge_open else 0
    wagon_mass = max(0.1, float((mechanics.get("vehicle_assumptions", {}) or {}).get("wagon_equivalent_loaded_tonnes", 1.8)))
    bridge_wagons = 0
    if bridge_open and bridge_load >= wagon_mass:
        bridge_wagons = int(math.floor(bridge_width * float(bridge_cfg.get("wagons_per_m_width_per_day", 220.0)) * condition_factor * throughput_factor))

    ferry_cfg = mechanics.get("ferry", {}) if isinstance(mechanics.get("ferry"), Mapping) else {}
    installed_boats = max(0, int(static.get("ferry_boats", 0)))
    serviceable_boats = max(0, min(installed_boats, int(state.get("serviceable_ferry_boats", installed_boats))))
    payload = max(0.0, float(static.get("ferry_payload_tonnes_each", 0.0)))
    cycle_minutes = max(1.0, float(static.get("ferry_cycle_minutes", ferry_cfg.get("default_cycle_minutes", 36.0))))
    operating_hours = max(0.0, float(ferry_cfg.get("operating_hours_per_day", 16.0)))
    efficiency = max(0.0, min(1.0, float(ferry_cfg.get("loading_efficiency", 0.55))))
    cycles = operating_hours * 60.0 / cycle_minutes
    people_per_tonne = max(0.0, float(ferry_cfg.get("equipped_people_per_tonne", 15.0)))
    ferry_troops = int(math.floor(serviceable_boats * payload * people_per_tonne * cycles * efficiency * ferry_factor))
    wagons_per_boat = int(math.floor(payload / wagon_mass)) if payload >= wagon_mass else 0
    ferry_wagons = int(math.floor(serviceable_boats * wagons_per_boat * cycles * efficiency * ferry_factor))

    ford_open = bool(state.get("ford_open", False))
    ford_low = bool(static.get("ford_available_low_stage", False))
    ford_normal = bool(static.get("ford_available_normal_stage", False))
    ford_allowed = ford_open and ((stage == "low" and ford_low) or (stage == "normal" and ford_normal))
    ford_cfg = mechanics.get("ford", {}) if isinstance(mechanics.get("ford"), Mapping) else {}
    ford_troops = int(ford_cfg.get("daily_troop_throughput", 0)) if ford_allowed else 0
    ford_wagons = int(ford_cfg.get("daily_wagon_throughput", 0)) if ford_allowed else 0

    troop_capacity = max(0, bridge_troops + ferry_troops + ford_troops)
    wagon_capacity = max(0, bridge_wagons + ferry_wagons + ford_wagons)
    bridge_delay = max(0.0, float(bridge_cfg.get("base_delay_hours", 0.5))) if bridge_troops > 0 else 0.0
    ferry_delay = max(0.0, float(ferry_cfg.get("base_delay_hours", 1.5))) if ferry_troops > 0 else 0.0
    ford_delay = max(0.0, float(ford_cfg.get("base_delay_hours", 1.0))) if ford_troops > 0 else 0.0
    if bridge_troops > 0:
        light_delay = bridge_delay
        convoy_delay = bridge_delay if bridge_wagons > 0 else ferry_delay
    elif ferry_troops > 0:
        light_delay = ferry_delay
        convoy_delay = ferry_delay if ferry_wagons > 0 else None
    elif ford_troops > 0:
        light_delay = ford_delay
        convoy_delay = ford_delay if ford_wagons > 0 else math.inf
    else:
        light_delay = None
        convoy_delay = None

    return {
        "route_ref": str(route.get("ref", "")),
        "crossing_type": str(static.get("crossing_type", "water_crossing")),
        "river_width_m": float(static.get("river_width_m", 0.0)),
        "normal_depth_m": float(static.get("normal_depth_m", 0.0)),
        "normal_current_m_per_s": float(static.get("normal_current_m_per_s", 0.0)),
        "water_stage": stage,
        "bridge_condition_percent": round(bridge_condition, 3),
        "bridge_open": bridge_open,
        "serviceable_ferry_boats": serviceable_boats,
        "ford_open": ford_allowed,
        "daily_troop_throughput": troop_capacity,
        "daily_wagon_throughput": wagon_capacity,
        "light_crossing_delay_hours": light_delay,
        "convoy_crossing_delay_hours": convoy_delay,
        "available_methods": [name for name, n in (("bridge", bridge_troops), ("ferry", ferry_troops), ("ford", ford_troops)) if n > 0],
        "rule": "crossing throughput is a physical bottleneck, never a cap on army existence; excess traffic crosses in additional waves/time",
    }


def crossing_mode_is_usable(read: Callable[[str], Mapping[str, Any]], route: Mapping[str, Any], mode: str) -> bool:
    profile = crossing_operational_profile(read, route)
    if profile is None:
        return True
    if str(mode) == "convoy":
        delay = profile.get("convoy_crossing_delay_hours")
        return int(profile["daily_wagon_throughput"]) > 0 and isinstance(delay, (int, float)) and math.isfinite(float(delay))
    delay = profile.get("light_crossing_delay_hours")
    return int(profile["daily_troop_throughput"]) > 0 and isinstance(delay, (int, float)) and math.isfinite(float(delay))


def crossing_delay_hours(read: Callable[[str], Mapping[str, Any]], route: Mapping[str, Any], mode: str) -> float:
    profile = crossing_operational_profile(read, route)
    if profile is None:
        return 0.0
    delay = profile.get("convoy_crossing_delay_hours") if str(mode) == "convoy" else profile.get("light_crossing_delay_hours")
    if not isinstance(delay, (int, float)) or not math.isfinite(float(delay)):
        raise ValueError(f"route crossing is unusable for movement mode {mode}")
    return float(delay)


class StrategicCrossingStateMixin:
    """Internal causal mutations for bridge/ferry/ford state.

    Player actions such as sabotage or engineering should reach this through a
    lawful operation/siege/state consequence.  The low-level command is internal
    so callers cannot directly author infrastructure damage.
    """

    def _crossing_route(self, route_ref: str) -> Mapping[str, Any]:
        doc = self.read("game/data/world/routes.json")
        for row in list(doc.get("routes", [])) + list(doc.get("local_routes", [])):
            if isinstance(row, Mapping) and str(row.get("ref")) == str(route_ref):
                if not isinstance(row.get("water_crossing"), Mapping):
                    raise ValueError("route has no strategic water crossing")
                return row
        raise ValueError("unknown strategic route crossing")

    def _mutate_crossing(self, payload: Mapping[str, Any], at: str) -> dict[str, Any]:
        route_ref = str(payload["route_ref"])
        route = self._crossing_route(route_ref)
        static = route["water_crossing"]
        doc = copy.deepcopy(self.read(CROSSING_STATE_PATH))
        rows = doc.setdefault("crossings", {})
        row = rows.get(route_ref)
        if not isinstance(row, dict):
            raise ValueError("strategic crossing is not materialized in mutable baseline state")
        action = str(payload["action"])
        if action == "set_water_stage":
            stage = str(payload["water_stage"])
            if stage not in {"low", "normal", "high", "flood"}:
                raise ValueError("unsupported water stage")
            row["water_stage"] = stage
            if row.get("ford_open") and not ((stage == "low" and static.get("ford_available_low_stage")) or (stage == "normal" and static.get("ford_available_normal_stage"))):
                row["ford_open"] = False
        elif action in {"damage_bridge", "repair_bridge"}:
            amount = max(1, min(100, int(payload.get("amount", 1))))
            current = max(0, min(100, int(row.get("bridge_condition_percent", 100))))
            row["bridge_condition_percent"] = max(0, current - amount) if action == "damage_bridge" else min(100, current + amount)
            row["bridge_open"] = int(row["bridge_condition_percent"]) > 0
            row["last_bridge_change_at"] = at
        elif action in {"damage_ferries", "restore_ferries"}:
            qty = max(1, int(payload.get("quantity", 1)))
            installed = max(0, int(static.get("ferry_boats", 0)))
            current = max(0, min(installed, int(row.get("serviceable_ferry_boats", installed))))
            row["serviceable_ferry_boats"] = max(0, current - qty) if action == "damage_ferries" else min(installed, current + qty)
            row["last_ferry_change_at"] = at
        elif action == "open_ford":
            stage = str(row.get("water_stage", "normal"))
            allowed = (stage == "low" and bool(static.get("ford_available_low_stage"))) or (stage == "normal" and bool(static.get("ford_available_normal_stage")))
            if not allowed:
                raise ValueError("ford is not physically usable at the current water stage")
            row["ford_open"] = True
            row["last_ford_change_at"] = at
        elif action == "close_ford":
            row["ford_open"] = False
            row["last_ford_change_at"] = at
        else:
            raise ValueError("unsupported strategic crossing action")
        row["last_changed_at"] = at
        self.put(CROSSING_STATE_PATH, doc)
        return {"route_ref": route_ref, "action": action, "crossing": crossing_operational_profile(self.read, route)}

    def _command_layer_strategic_crossings(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        if command.command_type == "strategic_crossing_action":
            if str(command.actor_id) != str(self.INTERNAL_ACTOR):
                raise PermissionError("strategic crossing mutation is an internal causal consequence")
            at = str(self._world_time())
            result = self._mutate_crossing(payload, at)
            world_time, metrics = self._advance_seconds(3600)
            self._write_meta(command, world_time)
            return self._result(world_time=world_time, **result, **metrics)
        return next_dispatch()
