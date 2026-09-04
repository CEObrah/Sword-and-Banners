from __future__ import annotations
from sword_runtime.training_instructors import exact_person_drill_access, instructor_contexts_for_program
from sword_runtime.training_facilities import training_environment

import copy
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.activity_living_world import ActivityCampaignEventPlanner
from sword_runtime.formation_replacement import FormationReplacementMixin
from sword_runtime.military_nested_career import MilitaryNestedCareerMixin
from sword_runtime.civil_world import CivilWorldMixin
from sword_runtime.campaign_depth import CampaignDepthMixin
from sword_runtime.army_organization import ArmyOrganizationMixin
from sword_runtime.command_staff_movement import CommandStaffMovementMixin
from sword_runtime.contact_request_flow import ContactRequestFlowMixin
from sword_runtime.departure_preparation import (
    CommandStaffMusterChronologyMixin,
    HouseFieldDeparturePreflightMixin,
)
from sword_runtime.downtime import DowntimeAdvanceMixin
from sword_runtime.environment import EnvironmentMechanicsMixin
from sword_runtime.equipment_planner import EquipmentStateProjectionMixin
from sword_runtime.family_counsel import FamilyCounselMixin
from sword_runtime.family_autonomy import FamilyAutonomyMixin
from sword_runtime.force_cohort_living_world import ForceCohortLivingWorldMixin
from sword_runtime.house_field_preparation_gate import ExplicitHouseFieldPreparationFlowMixin
from sword_runtime.house_field_preparation_issue import HouseFieldPreparationIssueMixin
from sword_runtime.house_field_preparation_outfitting import HouseFieldPreparationOutfittingProjectionMixin
from sword_runtime.house_tang_development_integrity import HouseTangDevelopmentIntegrityMixin
from sword_runtime.household_request_flow import HouseholdRequestFlowMixin
from sword_runtime.formation_armory_issue import FormationArmoryIssueMixin
from sword_runtime.qin_command_assumption_flow import QinCommandAssumptionFlowMixin
from sword_runtime.qin_command_briefing_flow import QinCommandBriefingFlowMixin
from sword_runtime.qin_command_progression import QinCommandProgressionMixin
from sword_runtime.player_story_flow import PlayerStoryFlowMixin
from sword_runtime.population_mobility import PopulationMobilityMixin
from sword_runtime.political_depth import PoliticalDepthMixin
from sword_runtime.political_ecology import PoliticalEcologyMixin
from sword_runtime.house_emergence import HouseEmergenceMixin
from sword_runtime.court_rewards import CourtRewardMixin
from sword_runtime.chariot_platforms import ChariotPlatformMixin
from sword_runtime.prisoner_system import PrisonerSystemMixin
from sword_runtime.settlement_civic_depth import SettlementCivicDepthMixin
from sword_runtime.independent_organizations import IndependentOrganizationMixin
from sword_runtime.fortified_site_runtime import FortifiedSiteRuntimeMixin
from sword_runtime.fatigue import RULES_PATH as FATIGUE_RULES_PATH, settle_person_idle_fatigue, stamp_person_activity_fatigue
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_programs import (
    REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH,
    resolve_program_ref,
    registered_focus_drill_ref,
    settle_exact_registered_focus,
    settle_person_lite_program,
)
from sword_runtime.standing_training import StandingTrainingSettlementMixin
from sword_runtime.strategic_crossings import StrategicCrossingStateMixin
from sword_runtime.warfare_depth import WarfareDepthMixin
from sword_runtime.warfare_depth_integrity import WarfareDepthIntegrityMixin
from sword_runtime.stat_access import merged_skill_map

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
_COMMAND_PERSON_INDEX_PATH = "state/cmd/command-personnel.json"

class ProductionCampaignPlanner(
    ChariotPlatformMixin,
    CourtRewardMixin,
    HouseEmergenceMixin,
    PoliticalEcologyMixin,
    WarfareDepthIntegrityMixin,
    WarfareDepthMixin,
    ArmyOrganizationMixin,
    PrisonerSystemMixin,
    CampaignDepthMixin,
    EnvironmentMechanicsMixin,
    HouseFieldDeparturePreflightMixin,
    CommandStaffMusterChronologyMixin,
    CommandStaffMovementMixin,
    StandingTrainingSettlementMixin,
    DowntimeAdvanceMixin,
    EquipmentStateProjectionMixin,
    MilitaryNestedCareerMixin,
    FormationReplacementMixin,
    PopulationMobilityMixin,
    FortifiedSiteRuntimeMixin,
    StrategicCrossingStateMixin,
    IndependentOrganizationMixin,
    SettlementCivicDepthMixin,
    PoliticalDepthMixin,
    FamilyAutonomyMixin,
    CivilWorldMixin,
    FamilyCounselMixin,
    HouseFieldPreparationOutfittingProjectionMixin,
    HouseFieldPreparationIssueMixin,
    ExplicitHouseFieldPreparationFlowMixin,
    FormationArmoryIssueMixin,
    HouseholdRequestFlowMixin,
    ContactRequestFlowMixin,
    QinCommandAssumptionFlowMixin,
    QinCommandProgressionMixin,
    QinCommandBriefingFlowMixin,
    PlayerStoryFlowMixin,
    HouseTangDevelopmentIntegrityMixin,
    ForceCohortLivingWorldMixin,
    ActivityCampaignEventPlanner,
):
    """Production campaign planner with generic force cohorts and House Tang development."""

    _interruptible_personal_travel = False

    # ------------------------------------------------------------------
    # Person-lite command development
    # ------------------------------------------------------------------

    def _fc_train(self, force: dict[str, Any], regimen: str, months: float, ref: str) -> None:
        """Advance cohorts and their already-materialized person-lite officers once.

        Person-lite records are the exact individual authority. Training never
        creates a parallel command-person projection. Missing routes are state
        integrity defects and are handled by the materialization/write path.
        """
        super()._fc_train(force, regimen, months, ref)

    def _fc_train_person_lites(
        self,
        force: Mapping[str, Any],
        regimen: str,
        months: float,
        ref: str,
        *,
        ref_prefix: str | None = None,
    ) -> int:
        return super()._fc_train_person_lites(force, regimen, months, ref, ref_prefix=ref_prefix)

    def _fc_train_person_lites_extra(
        self,
        force: Mapping[str, Any],
        *,
        target_regimen: str,
        baseline_regimen: str,
        months: float,
        ref: str,
        ref_prefix: str | None = None,
        command_only: bool = False,
    ) -> int:
        return super()._fc_train_person_lites_extra(
            force,
            target_regimen=target_regimen,
            baseline_regimen=baseline_regimen,
            months=months,
            ref=ref,
            ref_prefix=ref_prefix,
            command_only=command_only,
        )

    def _ct_train_person_lite_officers(
        self,
        force: dict[str, Any],
        formation: dict[str, Any],
        *,
        formation_ref: str,
        hours: float,
        evidence: str,
        training_rules: Mapping[str, Any],
        regimen: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Settle formation drill on the authoritative person-lite records.

        The command-person index is routing only. It resolves one exact logical
        officer record, including JSON-pointer shards, and creates no second
        person representation.
        """
        lite_refs, _exact_refs = self._ct_command_refs(formation)
        eligible = {
            ref: role
            for ref, role in lite_refs.items()
            if role in {"internal_1000_commander", "internal_500_commander", "internal_100_commander"}
        }
        if not eligible or hours <= 0:
            return []
        index = self.read(_COMMAND_PERSON_INDEX_PATH)
        record_index = index.get("record_index", {}) if isinstance(index, Mapping) else {}
        results: list[dict[str, Any]] = []
        current = CampaignTime.parse(str(self.read("state/runtime.json").get("world_time")))
        window_start = current.add_seconds(-max(0, int(round(float(hours) * 3600.0))))
        environment = training_environment(self, location_ref=str(formation.get("location_ref", "")), simultaneous_trainees=max(1, len(eligible)))
        for person_ref, role_label in sorted(eligible.items()):
            path = record_index.get(person_ref) if isinstance(record_index, Mapping) else None
            if not isinstance(path, str) or not path:
                results.append({"person_ref": person_ref, "role": role_label, "trained": False, "reason": "missing_person_lite_route"})
                continue
            record = copy.deepcopy(self.read(path))
            registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
            program_ref = resolve_program_ref(
                registry, role="command_personnel",
                training_ref=str(formation.get("training_ref", "") or ""), person=record,
            )
            officer_evidence = f"{evidence}:officer:{person_ref}"
            trainee_skills = merged_skill_map(record)
            instructor_contexts = instructor_contexts_for_program(
                self, registry=registry, training_rules=training_rules, program_ref=program_ref,
                trainee_skills=trainee_skills if isinstance(trainee_skills, Mapping) else {},
                student_count=1, location_ref=str(formation.get("location_ref", "")),
                formation=formation, trainee_ref=person_ref,
                scheduled_hours=float(hours), window_start=str(window_start), window_end=str(current),
                evidence_ref=officer_evidence, reserve_duty=True,
            )
            drill_access = exact_person_drill_access(self, registry=registry, program_ref=program_ref, person=record)
            result = settle_person_lite_program(
                record, registry=registry, program_ref=program_ref,
                deliberate_hours=float(hours), role_exposure_hours=0.0,
                training_rules=training_rules,
                facility_grade=str(environment.get("facility_grade", "none")),
                equipment_grade=str(regimen.get("equipment_grade", "adequate")),
                recovery_grade=str(regimen.get("recovery_grade", "adequate")),
                evidence_ref=officer_evidence,
                instructor_context_by_drill=instructor_contexts, drill_access=drill_access,
                time_window_start=str(window_start), time_window_end=str(current),
            )
            if result.get("trained"):
                dev = record.setdefault("development_state", {})
                last_training = dev.get("last_training") if isinstance(dev.get("last_training"), Mapping) else {}
                dev["last_training"] = {**dict(last_training), "formation_ref": formation_ref}
                self.put(path, record)
            results.append({"person_ref": person_ref, "role": role_label, **result})
        return results

    def _ct_train_exact_command_staff(
        self,
        formation: Mapping[str, Any],
        *,
        formation_ref: str,
        hours: float,
        evidence: str,
        training_rules: Mapping[str, Any],
        regimen: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Do not double-settle exact NPC training through formation standing credit.

        Full-character commanders and deputies keep their own saved autonomous
        activity/training contracts. Formation standing settlement directly owns
        only the fighting cohort and internal person-lite officers whose bodies
        were reclassified out of that cohort. Returning an empty result here
        prevents the same elapsed drill window from being paid twice.
        """
        return []

    # ------------------------------------------------------------------
    # Command admission and ordinary production behavior
    # ------------------------------------------------------------------

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
        # Tang Manor facilities are now ordinary authoritative world locations.
        return super()._location_record(location_ref)

    def _route_travel_hours(self, origin: str, destination: str, *, modes: tuple[str, ...] = ("horse", "foot")) -> int:
        if origin == destination:
            return 0
        base_hours = super()._route_travel_hours(origin, destination, modes=modes)
        return self._environment_adjusted_route_hours(origin, destination, int(base_hours))

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
                command.semantic_digest[:24],
            )
        return self._result(**result)

    def _settle_formation_training(
        self,
        formation_ref: str,
        start: CampaignTime,
        end: CampaignTime,
        request_id: str,
    ) -> dict[str, Any]:
        """Ensure current formation training counters exist before downtime settlement."""

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
        """Production exact-person training through a registered drill only.

        ``focus`` is a player intent. It may choose only a skill already present in
        Wei's saved deterministic program; the runtime chooses the registered drill,
        equipment gate, instructor, attribute stimulus, EDU law and time accounting.
        """

        player = copy.deepcopy(self.read("state/player.json"))
        hours = int(payload.get("hours", 1))
        focus = str(payload.get("focus", "Athletics"))
        if self._person_health(player) != "healthy":
            raise ValueError("injured player requires recovery before deliberate training")
        current = self._world_time()
        training = self.read("game/data/mechanics/training.json")
        settle_person_idle_fatigue(player, current=current, rules=self.read(FATIGUE_RULES_PATH), state="ordinary")
        player_fatigue = player.get("health", {}).get("fatigue", player.get("fatigue", 0)) if isinstance(player.get("health"), Mapping) else player.get("fatigue", 0)
        if int(player_fatigue or 0) > 70:
            raise ValueError("player is too fatigued for deliberate training")
        if focus not in merged_skill_map(player):
            raise ValueError("training focus must name an exact saved skill")

        registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
        contract = player.get("activity_contract") if isinstance(player.get("activity_contract"), Mapping) else {}
        explicit_program = str(contract.get("training_program_ref", "") or "")
        program_ref = resolve_program_ref(registry, person=player, explicit_program_ref=explicit_program or None)
        drill_ref = registered_focus_drill_ref(registry, program_ref, focus)
        profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
        regimens = profiles.get("training_regimens", {}) if isinstance(profiles, Mapping) else {}
        regimen = regimens.get(str(contract.get("training_regimen_ref", "regular_army")), {}) if isinstance(regimens, Mapping) else {}
        if not isinstance(regimen, Mapping):
            regimen = {}
        target_time = current.add_seconds(hours * 3600)
        target = str(target_time)
        player_location = str(self._person_location(player) or "")
        environment = training_environment(self, location_ref=player_location, simultaneous_trainees=1) if player_location else {"facility_grade": "none", "capacity_factor": 0.0}
        evidence = f"individual_training:{command.semantic_digest[:24]}"
        instructor_contexts = instructor_contexts_for_program(
            self, registry=registry, training_rules=training, program_ref=program_ref,
            trainee_skills=merged_skill_map(player),
            student_count=1, location_ref=player_location, trainee_ref=self.PLAYER_ACTOR,
            scheduled_hours=float(hours), window_start=str(current), window_end=target,
            evidence_ref=evidence, reserve_duty=True, focus_drill_ref=drill_ref,
        )
        drill_access = exact_person_drill_access(self, registry=registry, program_ref=program_ref, person=player)
        metrics = self._advance_runtime(target)
        session_rules = self.read("game/data/mechanics/training-session.json")
        development = settle_exact_registered_focus(
            player, registry=registry, program_ref=program_ref, focus_skill=focus, hours=hours,
            at=target_time, training_rules=training, session_rules=session_rules,
            facility_grade=str(environment.get("facility_grade", "none")),
            equipment_grade=str(regimen.get("equipment_grade", "adequate")),
            recovery_grade=str(regimen.get("recovery_grade", "adequate")),
            feedback_grade=str(regimen.get("feedback_grade", "ordinary")),
            instructor_context_by_drill=instructor_contexts, drill_access=drill_access,
            time_window_start=str(current), time_window_end=target, time_evidence_ref=evidence,
        )
        verified = max(0, int(development.get("verified_hours", hours) or 0))
        if verified > 0:
            stamp_person_activity_fatigue(player, completed_at=target_time, fatigue_gain=max(1, int(round(verified / 2.0))), activity_kind="training")
        dev = player.setdefault("development_state", {})
        last_training = dev.get("last_training") if isinstance(dev.get("last_training"), Mapping) else {}
        dev["last_training"] = {
            **dict(last_training),
            "started_at": str(current), "completed_at": target, "focus": focus,
            "verified_hours": verified, "program_ref": program_ref, "drill_ref": drill_ref,
        }
        self.put("state/player.json", player)
        self._write_meta(command, target)
        return self._result(
            focus=focus, hours=hours, verified_training_hours=verified,
            program_ref=program_ref, drill_ref=drill_ref, world_time=target, development=development, **metrics
        )

    def _command_layer_production_planner(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        if command.command_type == "advance_time" and bool(payload.get("stop_on_player_event", False)):
            return self._dispatch_event_bounded_advance(command, payload)
        if command.command_type == "individual_training":
            return self._dispatch_individual_training(command, payload)
        personal_travel = command.command_type == "travel" and not payload.get("formation_refs")
        if not personal_travel:
            return next_dispatch()

        runtime_before = self.read("state/runtime.json")
        if isinstance(runtime_before.get("pending_wake"), Mapping):
            return next_dispatch()

        player_before = copy.deepcopy(self.read("state/player.json"))
        manifest_before = copy.deepcopy(self.read("state/player-detail/equipment-manifest.json"))
        previous_flag = self._interruptible_personal_travel
        self._interruptible_personal_travel = True
        try:
            result = next_dispatch()
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

        # Preserve physically completed route progress instead of rewinding Wei
        # to the departure room merely because chronology hit a hard wake.
        # The route graph is discrete, so an interruption inside an edge remains
        # anchored at that edge's last completed node; completed edges are never
        # undone. This keeps elapsed world time and physical progress causally
        # consistent without inventing free-form coordinates between saved nodes.
        start_time = CampaignTime.parse(str(runtime_before["world_time"]))
        reached_time = CampaignTime.parse(actual_time)
        elapsed_seconds = max(0, start_time.seconds_until(reached_time))
        origin_ref = str(player_before.get("location") or player_before.get("current_location") or "")
        destination_ref = str(command.payload.get("destination_ref") or "")
        mode = str(command.payload.get("mode") or "foot")
        reached_node = origin_ref
        reached_node_index = 0
        try:
            route = self._find_route(origin_ref, destination_ref, mode=mode)
            path = [str(x) for x in route.get("path", []) if isinstance(x, str)]
            edge_hours = [max(0, int(x)) for x in route.get("edge_hours", [])]
            base_total = max(0, int(route.get("duration_hours", 0) or 0))
            scaled_total = max(0, int(result.get("duration_hours", base_total) or 0))
            if path and len(path) == len(edge_hours) + 1 and base_total > 0 and scaled_total > 0:
                cumulative_base = 0
                for index, hours in enumerate(edge_hours):
                    cumulative_base += hours
                    node_due_seconds = int(math.ceil((cumulative_base / base_total) * scaled_total * 3600.0))
                    if elapsed_seconds < node_due_seconds:
                        break
                    reached_node_index = index + 1
                    reached_node = path[reached_node_index]
        except (KeyError, TypeError, ValueError):
            # Route validation already succeeded in the underlying travel command.
            # If a later projection unexpectedly cannot be reconstructed, fail
            # conservatively at the departure node rather than moving forward.
            reached_node = origin_ref
            reached_node_index = 0

        restored_player = copy.deepcopy(player_before)
        restored_player["location"] = reached_node
        restored_player["current_location"] = reached_node
        settle_person_idle_fatigue(restored_player, current=start_time, rules=self.read(FATIGUE_RULES_PATH), state="ordinary")
        completed_hours = elapsed_seconds // 3600
        if completed_hours > 0:
            stamp_person_activity_fatigue(
                restored_player,
                completed_at=reached_time,
                fatigue_gain=max(1, int(completed_hours) // 12),
                activity_kind="travel",
            )
        self.put("state/player.json", restored_player)
        self.put("state/player-detail/equipment-manifest.json", manifest_before)
        self._write_meta(command, actual_time)

        result["world_time"] = actual_time
        result["travel_completed"] = False
        result["current_location"] = reached_node
        result["route_progress_node_index"] = reached_node_index
        result["elapsed_travel_seconds"] = elapsed_seconds
        result["route_progress_rule"] = "completed_route_nodes_persist; in-edge progress remains at the last completed saved node"
        return result


__all__ = ["HOUSE_TANG_GARRISON", "HOUSE_TANG_GARRISON_REF", "ProductionCampaignPlanner"]
