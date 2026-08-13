"""Player-facing grouped military actions that must consume elapsed time once.

The base engine keeps single-formation commands exact and composable. This
production planner adds only the narrow grouped semantics needed when one player
order applies to several controlled formations in parallel, or when the player
travels in one column with exact controlled escorts. It does not create a second
military authority: all formations, logistics, commanders, locations, and time
remain owned by the existing exact campaign records.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.engine import _clamp
from sword_runtime.production_living_world import ProductionLivingWorldSwordPlanner

_MAX_GROUP_FORMATIONS = 128


def _exact_group_refs(payload: Mapping[str, Any]) -> list[str]:
    raw = payload.get("formation_refs")
    if raw is None:
        return []
    if not isinstance(raw, list) or not 1 <= len(raw) <= _MAX_GROUP_FORMATIONS:
        raise ValueError("formation_refs must contain 1..128 exact formation refs")
    refs: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value or len(value) > 160:
            raise ValueError("formation_refs contains an invalid exact ref")
        refs.append(value)
    if len(refs) != len(set(refs)):
        raise ValueError("formation_refs must be unique")
    return refs


class PlayerGroupActionPlanner(ProductionLivingWorldSwordPlanner):
    """Hosted planner extension for causally parallel player military actions."""

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._validate_command_semantics(command, payload)
        refs = _exact_group_refs(payload)
        if command.command_type == "formation_mobilize":
            has_single = isinstance(payload.get("formation_ref"), str) and bool(payload.get("formation_ref"))
            if bool(refs) == has_single:
                raise ValueError("formation_mobilize requires exactly one of formation_ref or formation_refs")
        elif command.command_type == "travel" and refs:
            # Escort movement is one physical column with the player, not a set
            # of separately elapsed formation moves.
            if len(refs) > _MAX_GROUP_FORMATIONS:
                raise ValueError("too many escort formations")

    def _authorize_command(self, command: Any, payload: Mapping[str, Any]) -> None:
        refs = _exact_group_refs(payload)
        if command.command_type == "formation_mobilize" and refs:
            if command.actor_id == self.INTERNAL_ACTOR:
                return
            for ref in refs:
                self._require_formation_authority(command.actor_id, ref)
            return
        super()._authorize_command(command, payload)
        if command.command_type == "travel" and refs and command.actor_id != self.INTERNAL_ACTOR:
            for ref in refs:
                self._require_formation_authority(command.actor_id, ref)

    def _dispatch_group_mobilize(self, command: Any, refs: list[str]) -> dict[str, Any]:
        loaded: list[tuple[str, dict[str, Any]]] = []
        for ref in refs:
            path, formation0 = self._load_formation(ref)
            formation = copy.deepcopy(formation0)
            if bool(formation.get("mobilized", False)):
                raise ValueError(f"formation is already mobilized: {ref}")
            loaded.append((path, formation))

        # The companies muster concurrently under their existing commanders.
        # Four hours is the existing formation-mobilization duration, paid once
        # for the parallel order rather than once per serialized API write.
        world_time, metrics = self._advance_seconds(4 * 3600)
        for path, formation in loaded:
            formation["mobilized"] = True
            formation["status"] = "mobilized"
            formation["mobilized_at"] = world_time
            self.put(path, formation)
        self._write_meta(command, world_time)
        result = self._result(
            formation_refs=refs,
            formation_count=len(refs),
            status="mobilized",
            duration_hours=4,
            world_time=world_time,
        )
        result.update(metrics)
        return result

    def _dispatch_escorted_travel(
        self,
        command: Any,
        payload: Mapping[str, Any],
        refs: list[str],
    ) -> dict[str, Any]:
        player = copy.deepcopy(self.read("state/player.json"))
        origin = str(player.get("location", ""))
        destination = str(payload["destination_ref"])
        mode = str(payload.get("mode", "foot"))
        if mode not in {"foot", "horse"}:
            raise ValueError("personal travel mode must be foot or horse")

        # Use the route graph rather than exact single-edge lookup. This is
        # important for nested Tang Manor locations, which lawfully connect to
        # Kanyou through the existing manor-capital bridge in _route_travel_hours.
        player_hours = self._route_travel_hours(origin, destination, modes=(mode,))
        loaded: list[tuple[str, str, dict[str, Any], int, int, int, Any, Any]] = []
        column_hours = player_hours

        for ref in refs:
            path, formation0 = self._load_formation(ref)
            formation = copy.deepcopy(formation0)
            if not bool(formation.get("mobilized", False)):
                raise ValueError(f"escort formation is not mobilized: {ref}")
            if str(formation.get("location_ref", "")) != origin:
                raise ValueError("escorted travel requires player and all formations to be co-located")
            hours = self._route_travel_hours(origin, destination, modes=("formation",))
            column_hours = max(column_hours, hours)
            commander_ref = formation.get("commander_ref")
            commander_path = None
            commander = None
            if commander_ref:
                commander_path, commander = self._validate_person_location_for_formation(
                    str(commander_ref), formation
                )
            loaded.append((ref, path, formation, hours, 0, 0, commander_path, commander))

        # Recompute carried requirements at the slowest column duration so no
        # formation gets free forage merely because another element sets pace.
        prepared: list[tuple[str, str, dict[str, Any], int, int, Any, Any]] = []
        for ref, path, formation, _hours, _food, _fodder, commander_path, commander in loaded:
            personnel = max(0, int(formation.get("personnel", 0)))
            mounts = sum(max(0, int(v)) for v in formation.get("mounts", {}).values())
            food_need = max(0, int(math.ceil(personnel * 0.8 * column_hours / 24.0)))
            fodder_need = max(0, int(math.ceil(mounts * 4.0 * column_hours / 24.0)))
            logistics = formation.setdefault("logistics", {})
            food_short = max(0, food_need - int(logistics.get("food_kg", 0)))
            fodder_short = max(0, fodder_need - int(logistics.get("fodder_kg", 0)))
            if food_short or fodder_short:
                depot_path, depot = self._material_depot(formation)
                if str(depot.get("location_ref", "")) != origin:
                    raise ValueError("escort lacks carried supply and has no co-located material depot")
                stocks = depot.setdefault("stocks", {})
                if int(stocks.get("grain_kg", 0)) < food_short:
                    raise ValueError("material depot lacks minimum grain for escorted travel")
                if int(stocks.get("fodder_kg", 0)) < fodder_short:
                    raise ValueError("material depot lacks minimum fodder for escorted travel")
                stocks["grain_kg"] = int(stocks.get("grain_kg", 0)) - food_short
                stocks["fodder_kg"] = int(stocks.get("fodder_kg", 0)) - fodder_short
                logistics["food_kg"] = int(logistics.get("food_kg", 0)) + food_short
                logistics["fodder_kg"] = int(logistics.get("fodder_kg", 0)) + fodder_short
                self.put(depot_path, depot)
            prepared.append(
                (ref, path, formation, food_need, fodder_need, commander_path, commander)
            )

        current = self._world_time()
        world_time = str(current.add_seconds(column_hours * 3600))
        metrics = self._advance_runtime(world_time)

        player["location"] = destination
        self.put("state/player.json", player)
        for ref, path, formation, food_need, fodder_need, commander_path, commander in prepared:
            logistics = formation.setdefault("logistics", {})
            logistics["food_kg"] = int(logistics.get("food_kg", 0)) - food_need
            logistics["fodder_kg"] = int(logistics.get("fodder_kg", 0)) - fodder_need
            formation["location_ref"] = destination
            formation["status"] = "deployed"
            formation["fatigue"] = _clamp(
                int(formation.get("fatigue", 0)) + max(1, column_hours // 12)
            )
            formation["last_moved_at"] = world_time
            self._index_formation_location(ref, origin, destination)
            self.put(path, formation)
            if commander is not None and commander_path is not None:
                self._set_person_location(commander, destination)
                self.put(commander_path, commander)

        self._write_meta(command, world_time)
        result = self._result(
            origin=origin,
            destination=destination,
            formation_refs=refs,
            formation_count=len(refs),
            route_ref="derived_route_graph",
            duration_hours=column_hours,
            mode=mode,
            world_time=world_time,
        )
        result.update(metrics)
        return result

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        refs = _exact_group_refs(payload)
        if command.command_type == "formation_mobilize" and refs:
            return self._dispatch_group_mobilize(command, refs)
        if command.command_type == "travel" and refs:
            return self._dispatch_escorted_travel(command, payload, refs)
        return super()._dispatch(command, payload)


__all__ = ["PlayerGroupActionPlanner"]
