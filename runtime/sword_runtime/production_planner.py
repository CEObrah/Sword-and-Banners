from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.activity_living_world import ActivityCampaignEventPlanner
from sword_runtime.civil_world import CivilWorldMixin
from sword_runtime.campaign_depth import CampaignDepthMixin
from sword_runtime.command_staff_movement import CommandStaffMovementMixin
from sword_runtime.contact_request_flow import ContactRequestFlowMixin
from sword_runtime.downtime import DowntimeAdvanceMixin
from sword_runtime.environment import EnvironmentMechanicsMixin
from sword_runtime.equipment_planner import EquipmentStateProjectionMixin
from sword_runtime.family_counsel import FamilyCounselMixin
from sword_runtime.force_cohort_living_world import ForceCohortLivingWorldMixin
from sword_runtime.great_bow_guard_combat import GreatBowGuardCombatProfileMixin
from sword_runtime.great_bow_guard_flow import GreatBowGuardFlowMixin
from sword_runtime.great_bow_guard_personal_integrity import GreatBowGuardPersonalIntegrityMixin
from sword_runtime.great_bow_guard_readiness_flow import GreatBowGuardReadinessFlowMixin
from sword_runtime.house_field_preparation_gate import ExplicitHouseFieldPreparationFlowMixin
from sword_runtime.house_tang_development_integrity import HouseTangDevelopmentIntegrityMixin
from sword_runtime.household_request_flow import HouseholdRequestFlowMixin
from sword_runtime.location_aware_formation_muster import LocationAwareFormationMusterMixin
from sword_runtime.qin_command_briefing_flow import QinCommandBriefingFlowMixin
from sword_runtime.qin_command_progression import QinCommandProgressionMixin
from sword_runtime.player_story_flow import PlayerStoryFlowMixin
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.standing_training import StandingTrainingSettlementMixin
from sword_runtime.training_session import settle_training_session

HOUSE_TANG_GARRISON_REF = "loc_tang_manor_garrison_yard"
HOUSE_TANG_GARRISON: dict[str, Any] = {
    "flavor_only": False,
    "fortified": True,
    "functions": ["house", "military", "movement", "supply", "stables", "training"],
    "kind": "garrison",
    "name": "House Tang Garrison and Muster Yard",
    "ref": HOUSE_TANG_GARRISON_REF,
    "state": "qin",
}


class ProductionCampaignPlanner(
    GreatBowGuardCombatProfileMixin,
    CampaignDepthMixin,
    EnvironmentMechanicsMixin,
    CommandStaffMovementMixin,
    StandingTrainingSettlementMixin,
    DowntimeAdvanceMixin,
    EquipmentStateProjectionMixin,
    CivilWorldMixin,
    FamilyCounselMixin,
    GreatBowGuardReadinessFlowMixin,
    ExplicitHouseFieldPreparationFlowMixin,
    LocationAwareFormationMusterMixin,
    HouseholdRequestFlowMixin,
    ContactRequestFlowMixin,
    QinCommandProgressionMixin,
    QinCommandBriefingFlowMixin,
    PlayerStoryFlowMixin,
    GreatBowGuardPersonalIntegrityMixin,
    GreatBowGuardFlowMixin,
    HouseTangDevelopmentIntegrityMixin,
    ForceCohortLivingWorldMixin,
    ActivityCampaignEventPlanner,
):
    """Production campaign planner with generic force cohorts and House Tang development."""

    _interruptible_personal_travel = False

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        # standing_training_settle is a production surface extension rather than
        # a baseline engine command. Admit exactly its closed payload here before
        # the base command registry can reject the unknown semantic type.
        if command.command_type == "standing_training_settle":
            if set(payload) != {"target_ref"}:
                raise ValueError("standing_training_settle accepts only target_ref")
            target_ref = payload.get("target_ref")
            if not isinstance(target_ref, str) or not target_ref or len(target_ref) > 160:
                raise ValueError("standing_training_settle target_ref is invalid")
            if target_ref != self.PLAYER_ACTOR and not target_ref.startswith("formation_"):
                raise ValueError("standing training target must be Tang Wei or an exact formation")
            return
        super()._validate_command_semantics(command, payload)

    def _location_record(self, location_ref: str) -> Mapping[str, Any]:
        if location_ref == HOUSE_TANG_GARRISON_REF:
            return HOUSE_TANG_GARRISON
        return super()._location_record(location_ref)

    def _route_travel_hours(self, origin: str, destination: str, *, modes: tuple[str, ...] = ("horse", "foot")) -> int:
        if origin == destination:
            return 0
        local = lambda ref: ref == "loc_kanyou" or ref.startswith("loc_tang_manor_")
        if local(origin) and local(destination):
            base_hours = 1
        else:
            base_hours = super()._route_travel_hours(origin, destination, modes=modes)
        return self._environment_adjusted_route_hours(origin, destination, int(base_hours))

    def _find_route(self, origin: str, destination: str, *, mode: str | None = None) -> Mapping[str, Any]:
        """Honor the production local-route graph for ordinary personal movement.

        The base reducer historically asks for one exact route edge. House Tang
        interiors and the garrison are registered production locations connected
        by the local route graph instead, so a lawful walk between them must not
        fail merely because no duplicate room-to-room edge exists in routes.json.
        Exact authored edges remain preferred; only foot/horse movement inside the
        Kanyou/Tang-manor local envelope falls back to the derived graph.
        """

        try:
            return super()._find_route(origin, destination, mode=mode)
        except ValueError:
            local = lambda ref: ref == "loc_kanyou" or ref.startswith("loc_tang_manor_")
            if mode not in {"foot", "horse"} or not (local(origin) and local(destination)):
                raise
            duration = self._route_travel_hours(origin, destination, modes=(str(mode),))
            return {
                "ref": "derived_route_graph",
                "a": origin,
                "b": destination,
                "modes": [str(mode)],
                "duration_hours": duration,
            }

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        """Let personal travel persist a real wake instead of previewing it forever."""

        if self._interruptible_personal_travel and self._active_command_type == "travel":
            previous = self._active_command_type
            self._active_command_type = "advance_time"
            try:
                return super()._advance_runtime(target_text)
            finally:
                self._active_command_type = previous
        return super()._advance_runtime(target_text)

    def _dispatch_event_bounded_advance(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Commit an event-bounded wait at the scheduler's actual reached time."""

        runtime_before = self.read("state/runtime.json")
        start = CampaignTime.parse(str(runtime_before["world_time"]))
        if "target_time" in payload:
            requested = CampaignTime.parse(str(payload["target_time"]))
        else:
            requested = start.add_hours(int(payload["hours"]))
        policy = self._policy(payload)

        previous_active = self._active_command_type
        previous_event = self._active_event_id
        previous_host = self._active_host_id
        previous_pending = self._pending_wake_created
        previous_stop = self._downtime_stop_on_player_event
        self._active_command_type = "advance_time"
        self._downtime_stop_on_player_event = True
        try:
            metrics = self._advance_runtime(str(requested))
        finally:
            self._downtime_stop_on_player_event = previous_stop
            self._active_command_type = previous_active
            self._active_event_id = previous_event
            self._active_host_id = previous_host
            self._pending_wake_created = previous_pending

        actual = CampaignTime.parse(str(self.read("state/runtime.json")["world_time"]))
        self._write_meta(command, str(actual))
        result = dict(metrics)
        result["world_time"] = str(actual)
        result["requested_time"] = str(requested)
        result["interrupted"] = bool(result.get("interrupted", False))
        if policy:
            result["downtime_activity"] = self._settle_downtime_policy(
                start,
                actual,
                policy,
                str(command.request_id),
            )
        return self._result(**result)

    def _settle_formation_training(
        self,
        formation_ref: str,
        start: CampaignTime,
        end: CampaignTime,
        request_id: str,
    ) -> dict[str, Any]:
        """Normalize legacy null counters before the generic downtime reducer."""

        path, formation = self._load_formation(formation_ref)
        if formation.get("training_progress") is None or formation.get("verified_training_hours") is None:
            normalized = copy.deepcopy(formation)
            if normalized.get("training_progress") is None:
                normalized["training_progress"] = 0
            if normalized.get("verified_training_hours") is None:
                normalized["verified_training_hours"] = 0
            self.put(path, normalized)
        return super()._settle_formation_training(formation_ref, start, end, request_id)

    def _dispatch_individual_training(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Production exact-person training with skill and attribute development."""

        player = copy.deepcopy(self.read("state/player.json"))
        hours = int(payload.get("hours", 1))
        focus = str(payload.get("focus", "Training"))
        if self._person_health(player) != "healthy":
            raise ValueError("injured player requires recovery before deliberate training")
        if int(player.get("fatigue", 0)) > 70:
            raise ValueError("player is too fatigued for deliberate training")
        if focus not in player.get("skills", {}):
            raise ValueError("training focus must name an exact saved skill")
        current = self._world_time()
        target_time = current.add_seconds(hours * 3600)
        target = str(target_time)
        metrics = self._advance_runtime(target)
        training = self.read("game/data/mechanics/training.json")
        session_rules = self.read("game/data/mechanics/training-session.json")
        development = settle_training_session(player, focus, hours, target_time, training, session_rules)
        player["fatigue"] = max(0, min(100, int(round(float(player.get("fatigue", 0) or 0) + hours / 2.0))))
        player.setdefault("training_history", []).append(
            {
                "started_at": str(current),
                "completed_at": target,
                "focus": focus,
                "hours": hours,
                "development": development,
            }
        )
        self.put("state/player.json", player)
        self._write_meta(command, target)
        return self._result(focus=focus, hours=hours, world_time=target, development=development, **metrics)

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "advance_time" and bool(payload.get("stop_on_player_event", False)):
            return self._dispatch_event_bounded_advance(command, payload)
        if command.command_type == "individual_training":
            return self._dispatch_individual_training(command, payload)

        personal_travel = command.command_type == "travel" and not payload.get("formation_refs")
        if not personal_travel:
            return super()._dispatch(command, payload)

        runtime_before = self.read("state/runtime.json")
        if isinstance(runtime_before.get("pending_wake"), Mapping):
            return super()._dispatch(command, payload)

        player_before = copy.deepcopy(self.read("state/player.json"))
        manifest_before = copy.deepcopy(self.read("state/player-detail/equipment-manifest.json"))
        previous_flag = self._interruptible_personal_travel
        self._interruptible_personal_travel = True
        try:
            result = super()._dispatch(command, payload)
        finally:
            self._interruptible_personal_travel = previous_flag

        if not (bool(result.get("interrupted")) and bool(result.get("wake_required"))):
            result["travel_completed"] = True
            return result

        runtime_after = self.read("state/runtime.json")
        actual_time = str(runtime_after["world_time"])
        requested_arrival = str(result.get("world_time", actual_time))
        result["requested_arrival_time"] = requested_arrival
        result["interrupted_at"] = actual_time

        if CampaignTime.parse(actual_time) >= CampaignTime.parse(requested_arrival):
            result["world_time"] = actual_time
            result["travel_completed"] = True
            return result

        self.put("state/player.json", player_before)
        self.put("state/player-detail/equipment-manifest.json", manifest_before)
        self._write_meta(command, actual_time)

        result["world_time"] = actual_time
        result["travel_completed"] = False
        result["current_location"] = str(player_before.get("location", ""))
        return result


__all__ = ["HOUSE_TANG_GARRISON", "HOUSE_TANG_GARRISON_REF", "ProductionCampaignPlanner"]
