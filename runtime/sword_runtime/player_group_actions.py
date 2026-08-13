"""Player-facing grouped military actions that must consume elapsed time once.

The base engine keeps single-formation commands exact and composable. This
production planner adds only the narrow grouped semantics needed when one player
order applies to several controlled formations in parallel, or when the player
travels in one column with exact controlled escorts. It does not create a second
military authority: all formations, logistics, commanders, locations, and time
remain owned by the existing exact campaign records.

Doctrine and training-program assignment are command/administrative changes,
not physical drill. They therefore preserve the current campaign instant. Actual
formation training consumes the requested elapsed hours once even when several
controlled formations train concurrently under one grouped order. Exact named
participants may train inside that same block when they are lawfully commanded,
healthy, co-located, and supplied with exact saved skill focuses.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.development import settle_skill_training
from sword_runtime.engine import _clamp
from sword_runtime.production_living_world import ProductionLivingWorldSwordPlanner
from sword_runtime.sim.calendar import CampaignTime

_MAX_GROUP_FORMATIONS = 128
_MAX_TRAINING_PARTICIPANTS = 16
_MAX_TRAINING_FOCUSES = 12
_GROUPABLE_EXACT_ONE = frozenset({
    "formation_mobilize",
    "formation_doctrine_set",
    "formation_training_set",
    "formation_train",
})


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


def _bounded_exact_strings(payload: Mapping[str, Any], key: str, limit: int) -> list[str]:
    raw = payload.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list) or not 1 <= len(raw) <= limit:
        raise ValueError(f"{key} must contain 1..{limit} exact strings")
    values: list[str] = []
    for value in raw:
        if not isinstance(value, str) or not value or len(value) > 160:
            raise ValueError(f"{key} contains an invalid exact string")
        values.append(value)
    if len(values) != len(set(values)):
        raise ValueError(f"{key} must be unique")
    return values


class PlayerGroupActionPlanner(ProductionLivingWorldSwordPlanner):
    """Hosted planner extension for causally parallel player military actions."""

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._validate_command_semantics(command, payload)
        refs = _exact_group_refs(payload)
        if command.command_type in _GROUPABLE_EXACT_ONE:
            has_single = isinstance(payload.get("formation_ref"), str) and bool(payload.get("formation_ref"))
            if bool(refs) == has_single:
                raise ValueError(
                    f"{command.command_type} requires exactly one of formation_ref or formation_refs"
                )
        elif command.command_type == "travel" and refs:
            if len(refs) > _MAX_GROUP_FORMATIONS:
                raise ValueError("too many escort formations")

        if command.command_type == "formation_train":
            participants = _bounded_exact_strings(payload, "participant_refs", _MAX_TRAINING_PARTICIPANTS)
            focuses = _bounded_exact_strings(payload, "focuses", _MAX_TRAINING_FOCUSES)
            if bool(participants) != bool(focuses):
                raise ValueError("named formation-training participants require exact skill focuses and vice versa")

    def _authorize_command(self, command: Any, payload: Mapping[str, Any]) -> None:
        refs = _exact_group_refs(payload)
        if command.command_type in _GROUPABLE_EXACT_ONE and refs:
            if command.actor_id != self.INTERNAL_ACTOR:
                for ref in refs:
                    self._require_formation_authority(command.actor_id, ref)
        else:
            super()._authorize_command(command, payload)

        if command.command_type == "travel" and refs and command.actor_id != self.INTERNAL_ACTOR:
            for ref in refs:
                self._require_formation_authority(command.actor_id, ref)

        if command.command_type == "formation_train" and command.actor_id != self.INTERNAL_ACTOR:
            participants = _bounded_exact_strings(payload, "participant_refs", _MAX_TRAINING_PARTICIPANTS)
            if participants:
                target_refs = refs or [str(payload["formation_ref"])]
                anchor = target_refs[0]
                for person_ref in participants:
                    if person_ref == command.actor_id:
                        continue
                    self._require_commandable_person(command.actor_id, person_ref, anchor)

    def _dispatch_group_mobilize(self, command: Any, refs: list[str]) -> dict[str, Any]:
        loaded: list[tuple[str, dict[str, Any]]] = []
        for ref in refs:
            path, formation0 = self._load_formation(ref)
            formation = copy.deepcopy(formation0)
            if bool(formation.get("mobilized", False)):
                raise ValueError(f"formation is already mobilized: {ref}")
            loaded.append((path, formation))

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

    def _dispatch_group_doctrine_set(
        self,
        command: Any,
        payload: Mapping[str, Any],
        refs: list[str],
    ) -> dict[str, Any]:
        doctrine_ref = str(payload["doctrine_ref"])
        world_time = str(self._world_time())
        for ref in refs:
            path, formation0 = self._load_formation(ref)
            formation = copy.deepcopy(formation0)
            formation["doctrine_ref"] = doctrine_ref
            if "doctrine_behavior" in payload:
                formation["doctrine_behavior"] = copy.deepcopy(dict(payload["doctrine_behavior"]))
            formation["doctrine_last_reformed_at"] = world_time
            formation["doctrine_proficiency_rule"] = (
                "doctrine assignment consumes no drill time; proficiency and cohesion change only through verified training or combat"
            )
            self.put(path, formation)
        self._write_meta(command, world_time)
        return self._result(
            formation_refs=refs,
            formation_count=len(refs),
            doctrine_ref=doctrine_ref,
            duration_hours=0,
            world_time=world_time,
        )

    def _dispatch_group_training_set(
        self,
        command: Any,
        payload: Mapping[str, Any],
        refs: list[str],
    ) -> dict[str, Any]:
        training_ref = str(payload["training_ref"])
        world_time = str(self._world_time())
        for ref in refs:
            path, formation0 = self._load_formation(ref)
            formation = copy.deepcopy(formation0)
            formation["training_ref"] = training_ref
            formation["training_program_last_changed_at"] = world_time
            formation["training_program_proficiency_rule"] = (
                "program assignment consumes no drill time; development is earned only through verified formation training"
            )
            self.put(path, formation)
        self._write_meta(command, world_time)
        return self._result(
            formation_refs=refs,
            formation_count=len(refs),
            training_ref=training_ref,
            duration_hours=0,
            world_time=world_time,
        )

    def _dispatch_group_train(
        self,
        command: Any,
        payload: Mapping[str, Any],
        refs: list[str],
    ) -> dict[str, Any]:
        hours = int(payload.get("hours", 1))
        loaded: list[tuple[str, dict[str, Any]]] = []
        locations: set[str] = set()
        for ref in refs:
            path, formation0 = self._load_formation(ref)
            formation = copy.deepcopy(formation0)
            loaded.append((path, formation))
            locations.add(str(formation.get("location_ref", "")))
        if len(locations) != 1:
            raise ValueError("grouped formation training requires co-located formations")
        training_location = next(iter(locations))

        participant_refs = _bounded_exact_strings(payload, "participant_refs", _MAX_TRAINING_PARTICIPANTS)
        focuses = _bounded_exact_strings(payload, "focuses", _MAX_TRAINING_FOCUSES)
        participants: list[tuple[str, dict[str, Any]]] = []
        for person_ref in participant_refs:
            if person_ref == self.PLAYER_ACTOR:
                person_path = "state/player.json"
                person = copy.deepcopy(self.read(person_path))
            else:
                person_path, person0 = self._exact_person(person_ref)
                person = copy.deepcopy(person0)
            if self._person_health(person) not in {"healthy", "fit", "stable"}:
                raise ValueError(f"training participant is not fit for deliberate training: {person_ref}")
            if int(person.get("fatigue", 0)) > 70:
                raise ValueError(f"training participant is too fatigued: {person_ref}")
            if self._person_location(person) != training_location:
                raise ValueError("named formation-training participants must be co-located with the formations")
            missing = [focus for focus in focuses if focus not in person.get("skills", {})]
            if missing:
                raise ValueError(f"training participant lacks exact saved skill focus: {person_ref}: {missing[0]}")
            participants.append((person_path, person))

        world_time, metrics = self._advance_seconds(hours * 3600)
        for path, formation in loaded:
            formation["training_progress"] = _clamp(
                int(formation.get("training_progress", 0)) + max(1, hours // 3)
            )
            formation["cohesion"] = _clamp(
                int(formation.get("cohesion", 50)) + max(1, hours // 4)
            )
            formation["readiness"] = _clamp(
                int(formation.get("readiness", 50)) + max(0, hours // 6)
            )
            formation["fatigue"] = _clamp(
                int(formation.get("fatigue", 0)) + max(1, hours // 5)
            )
            formation["verified_training_hours"] = (
                int(formation.get("verified_training_hours", 0)) + hours
            )
            formation["last_training_at"] = world_time
            self.put(path, formation)

        person_development: dict[str, list[dict[str, Any]]] = {}
        if participants:
            training_rules = self.read("game/data/mechanics/training.json")
            completed_at = CampaignTime.parse(world_time)
            base_hours, remainder = divmod(hours, len(focuses))
            for person_path, person in participants:
                person_ref = str(person.get("owner_id", self.PLAYER_ACTOR if person_path == "state/player.json" else person_path))
                results: list[dict[str, Any]] = []
                for index, focus in enumerate(focuses):
                    focus_hours = base_hours + (1 if index < remainder else 0)
                    if focus_hours <= 0:
                        continue
                    results.append(settle_skill_training(person, focus, focus_hours, completed_at, training_rules))
                person["fatigue"] = _clamp(int(round(int(person.get("fatigue", 0)) + hours / 2.0)))
                self.put(person_path, person)
                person_development[person_ref] = results

        self._write_meta(command, world_time)
        result = self._result(
            formation_refs=refs,
            formation_count=len(refs),
            hours=hours,
            duration_hours=hours,
            world_time=world_time,
            participant_refs=participant_refs,
            focuses=focuses,
            person_development=person_development,
        )
        result.update(metrics)
        return result

    @staticmethod
    def _is_local_house_tang_move(origin: str, destination: str, hours: int) -> bool:
        if hours > 4:
            return False
        origin_local = origin == "loc_kanyou" or origin.startswith("loc_tang_manor_")
        destination_local = destination == "loc_kanyou" or destination.startswith("loc_tang_manor_")
        return origin_local and destination_local

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

        location = self._location_record(destination)
        if refs and destination.startswith("loc_tang_manor_"):
            functions = {str(value) for value in location.get("functions", [])}
            if not functions.intersection({"military", "training", "movement", "supply", "stables"}):
                raise ValueError("formation escorts require a House Tang military-capable destination, not a residential room")

        player_hours = self._route_travel_hours(origin, destination, modes=(mode,))
        loaded: list[tuple[str, str, dict[str, Any], int, Any, Any]] = []
        column_hours = player_hours

        for ref in refs:
            path, formation0 = self._load_formation(ref)
            formation = copy.deepcopy(formation0)
            if not bool(formation.get("mobilized", False)):
                raise ValueError(f"escort formation is not mobilized: {ref}")
            if str(formation.get("location_ref", "")) != origin:
                raise ValueError("escorted travel requires player and all formations to be co-located")
            formation_hours = self._route_travel_hours(origin, destination, modes=("formation",))
            column_hours = max(column_hours, formation_hours)
            commander_ref = formation.get("commander_ref")
            commander_path = None
            commander = None
            if commander_ref:
                commander_path, commander = self._validate_person_location_for_formation(
                    str(commander_ref), formation
                )
            loaded.append((ref, path, formation, formation_hours, commander_path, commander))

        supply_hours = 0 if self._is_local_house_tang_move(origin, destination, column_hours) else column_hours
        prepared: list[tuple[str, str, dict[str, Any], int, int, Any, Any]] = []
        for ref, path, formation, _formation_hours, commander_path, commander in loaded:
            personnel = max(0, int(formation.get("personnel", 0)))
            mounts = sum(max(0, int(v)) for v in formation.get("mounts", {}).values())
            food_need = max(0, int(math.ceil(personnel * 0.8 * supply_hours / 24.0)))
            fodder_need = max(0, int(math.ceil(mounts * 4.0 * supply_hours / 24.0)))
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
        if command.command_type == "formation_doctrine_set":
            target_refs = refs or [str(payload["formation_ref"])]
            return self._dispatch_group_doctrine_set(command, payload, target_refs)
        if command.command_type == "formation_training_set":
            target_refs = refs or [str(payload["formation_ref"])]
            return self._dispatch_group_training_set(command, payload, target_refs)
        if command.command_type == "formation_train":
            target_refs = refs or [str(payload["formation_ref"])]
            return self._dispatch_group_train(command, payload, target_refs)
        if command.command_type == "travel" and refs:
            return self._dispatch_escorted_travel(command, payload, refs)
        return super()._dispatch(command, payload)


__all__ = ["PlayerGroupActionPlanner"]
