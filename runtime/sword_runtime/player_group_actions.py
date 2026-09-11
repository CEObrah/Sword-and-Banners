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
healthy and co-located. Their saved billet/role and the registered formation program determine gains.
"""
from __future__ import annotations
from sword_runtime.training_instructors import exact_person_drill_access, instructor_contexts_for_program
from sword_runtime.training_facilities import training_environment

import copy
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.engine import _clamp
from sword_runtime.military_supply import evaluate_military_supply
from sword_runtime.military_doctrine import doctrine_behavior
from sword_runtime.fatigue import (
    RULES_PATH as FATIGUE_RULES_PATH,
    settle_formation_idle_fatigue,
    settle_person_idle_fatigue,
    stamp_formation_activity_fatigue,
    stamp_person_activity_fatigue,
)
from sword_runtime.production_living_world import ProductionLivingWorldSwordPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_programs import formation_training_ref_for_role, REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH, resolve_program_ref, settle_exact_program
from sword_runtime.stat_access import merged_skill_map

_MAX_GROUP_FORMATIONS = 128
_MAX_TRAINING_PARTICIPANTS = 16
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
            _bounded_exact_strings(payload, "participant_refs", _MAX_TRAINING_PARTICIPANTS)
            if "focuses" in payload:
                raise ValueError("formation training focuses are registry-owned; assign a registered training_ref instead")

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
            formation["doctrine_behavior"] = doctrine_behavior(self.read, formation, explicit=payload.get("doctrine_behavior") if isinstance(payload.get("doctrine_behavior"), Mapping) else None)
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
        current = self._world_time()
        fatigue_rules = self.read(FATIGUE_RULES_PATH)
        loaded: list[tuple[str, dict[str, Any]]] = []
        locations: set[str] = set()
        for ref in refs:
            path, formation0 = self._load_formation(ref)
            formation = copy.deepcopy(formation0)
            settle_formation_idle_fatigue(formation, current=current, rules=fatigue_rules)
            loaded.append((path, formation))
            locations.add(str(formation.get("location_ref", "")))
        if len(locations) != 1:
            raise ValueError("grouped formation training requires co-located formations")
        training_location = next(iter(locations))

        participant_refs = _bounded_exact_strings(payload, "participant_refs", _MAX_TRAINING_PARTICIPANTS)
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
            settle_person_idle_fatigue(person, current=current, rules=fatigue_rules, state="ordinary")
            person_fatigue = person.get("health", {}).get("fatigue", person.get("fatigue", 0)) if isinstance(person.get("health"), Mapping) else person.get("fatigue", 0)
            if int(person_fatigue or 0) > 70:
                raise ValueError(f"training participant is too fatigued: {person_ref}")
            if self._person_location(person) != training_location:
                raise ValueError("named formation-training participants must be co-located with the formations")
            participants.append((person_path, person))

        world_time, metrics = self._advance_seconds(hours * 3600)
        completed_at = CampaignTime.parse(world_time)
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
            stamp_formation_activity_fatigue(
                formation,
                completed_at=completed_at,
                fatigue_gain=max(1, hours // 5),
                activity_kind="training",
            )
            formation["verified_training_hours"] = (
                int(formation.get("verified_training_hours", 0)) + hours
            )
            formation["last_training_at"] = world_time
            self.put(path, formation)
            if hasattr(self, "_ct_train_formation"):
                formation_ref = str(formation.get("formation_ref", ""))
                self._ct_train_formation(formation_ref, float(hours), f"formation_training:{command.semantic_digest[:24]}:{formation_ref}")

        person_development: dict[str, dict[str, Any]] = {}
        if participants:
            training_rules = self.read("game/data/mechanics/training.json")
            session_rules = self.read("game/data/mechanics/training-session.json")
            profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
            regimens = profiles.get("training_regimens", {}) if isinstance(profiles, Mapping) else {}
            registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
            by_ref = {str(f.get("formation_ref", "")): f for _p, f in loaded}
            default_formation = loaded[0][1] if len(loaded) == 1 else {}
            for person_path, person in participants:
                person_ref = str(person.get("owner_id", self.PLAYER_ACTOR if person_path == "state/player.json" else person_path))
                assignment = person.get("command_assignment") if isinstance(person.get("command_assignment"), Mapping) else {}
                assigned_ref = str(assignment.get("formation_ref", "") or "")
                anchor = by_ref.get(assigned_ref, default_formation)
                training_ref = str(anchor.get("training_ref", "") or "") if isinstance(anchor, Mapping) else ""
                composition = anchor.get("composition", {}) if isinstance(anchor, Mapping) and isinstance(anchor.get("composition"), Mapping) else {}
                role = str(max(composition.items(), key=lambda row: (int(row[1]), str(row[0])))[0]) if composition else None
                contract = person.get("activity_contract") if isinstance(person.get("activity_contract"), Mapping) else {}
                explicit_program = str(contract.get("training_program_ref", "") or "")
                program_ref = resolve_program_ref(
                    registry, role=role, training_ref=training_ref or None, person=person,
                    explicit_program_ref=explicit_program or None,
                )
                regimen_name = str(contract.get("training_regimen_ref", "") or "")
                if not regimen_name:
                    owner_force = str(anchor.get("owner_force_ref", "")) if isinstance(anchor, Mapping) else ""
                    regimen_name = "house_tang_max_sustainable" if owner_force in {"force_house_tang", "force_tang_wei_personal"} else "regular_army"
                regimen = regimens.get(regimen_name, {}) if isinstance(regimens, Mapping) else {}
                if not isinstance(regimen, Mapping):
                    regimen = {}
                environment = training_environment(self, location_ref=training_location, simultaneous_trainees=1) if training_location else {"facility_grade": "none", "capacity_factor": 0.0}
                participant_evidence = f"formation_participant_training:{command.semantic_digest[:24]}:{person_ref}"
                instructor_contexts = instructor_contexts_for_program(
                    self, registry=registry, training_rules=training_rules, program_ref=program_ref,
                    trainee_skills=merged_skill_map(person),
                    student_count=1, location_ref=training_location,
                    formation=anchor if isinstance(anchor, Mapping) else None, trainee_ref=person_ref,
                    scheduled_hours=float(hours), window_start=str(current), window_end=world_time,
                    evidence_ref=participant_evidence, reserve_duty=True,
                )
                drill_access = exact_person_drill_access(self, registry=registry, program_ref=program_ref, person=person)
                development = settle_exact_program(
                    person, registry=registry, program_ref=program_ref, hours=hours, at=completed_at,
                    training_rules=training_rules, session_rules=session_rules,
                    facility_grade=str(environment.get("facility_grade", "none")),
                    equipment_grade=str(regimen.get("equipment_grade", "adequate")),
                    recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                    feedback_grade=str(regimen.get("feedback_grade", "ordinary")),
                    cursor_key="formation_participant_training_cursor",
                    instructor_context_by_drill=instructor_contexts, drill_access=drill_access,
                    time_window_start=str(current), time_window_end=world_time,
                    time_evidence_ref=participant_evidence,
                )
                stamp_person_activity_fatigue(
                    person,
                    completed_at=completed_at,
                    fatigue_gain=max(1, int(round(hours / 2.0))),
                    activity_kind="training",
                )
                self.put(person_path, person)
                person_development[person_ref] = {"program_ref": program_ref, "development": development}

        self._write_meta(command, world_time)
        result = self._result(
            formation_refs=refs,
            formation_count=len(refs),
            hours=hours,
            duration_hours=hours,
            world_time=world_time,
            participant_refs=participant_refs,
            program_authority="registered_training_ref_and_saved_role",
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

        current = self._world_time()
        fatigue_rules = self.read(FATIGUE_RULES_PATH)
        settle_person_idle_fatigue(player, current=current, rules=fatigue_rules, state="ordinary")
        player_hours = self._route_travel_hours(origin, destination, modes=(mode,))
        loaded: list[tuple[str, str, dict[str, Any], int, Any, Any]] = []
        column_hours = player_hours

        for ref in refs:
            path, formation0 = self._load_formation(ref)
            formation = copy.deepcopy(formation0)
            settle_formation_idle_fatigue(formation, current=current, rules=fatigue_rules)
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
                settle_person_idle_fatigue(commander, current=current, rules=fatigue_rules, state="ordinary")
            loaded.append((ref, path, formation, formation_hours, commander_path, commander))

        prepared: list[tuple[str, str, dict[str, Any], Any, Any]] = []
        # Escorted formations carry their ordinary baggage with them. Strategic
        # supply affects march tempo but never creates or consumes ration inventory.
        for ref, path, formation, _formation_hours, commander_path, commander in loaded:
            supply = evaluate_military_supply(self, formation, at=str(current))
            movement_factor = max(0.25, float(supply.get("movement_factor", 1.0) or 1.0))
            adjusted_hours = max(_formation_hours, int(math.ceil(_formation_hours / movement_factor)))
            column_hours = max(column_hours, adjusted_hours)
            prepared.append((ref, path, formation, commander_path, commander))

        world_time = str(current.add_seconds(column_hours * 3600))
        metrics = self._advance_runtime(world_time)

        player["location"] = destination
        player["current_location"] = destination
        completed_at = CampaignTime.parse(world_time)
        stamp_person_activity_fatigue(
            player, completed_at=completed_at, fatigue_gain=max(1, column_hours // 12), activity_kind="travel"
        )
        self.put("state/player.json", player)
        for ref, path, formation, commander_path, commander in prepared:
            formation["location_ref"] = destination
            formation["status"] = "deployed"
            stamp_formation_activity_fatigue(
                formation,
                completed_at=completed_at,
                fatigue_gain=max(1, column_hours // 12),
                activity_kind="march",
            )
            formation["last_moved_at"] = world_time
            self._index_formation_location(ref, origin, destination)
            self.put(path, formation)
            if commander is not None and commander_path is not None:
                self._set_person_location(commander, destination)
                stamp_person_activity_fatigue(
                    commander, completed_at=completed_at, fatigue_gain=max(1, column_hours // 12), activity_kind="march"
                )
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

    def _command_layer_player_group_actions(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
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
        return next_dispatch()


__all__ = ["PlayerGroupActionPlanner"]
