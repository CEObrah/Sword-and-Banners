"""Player-directed downtime settlement for production play.

This layer keeps ordinary chronology authoritative while allowing one advance_time
command to express two things that were previously lost in broad time skips:

* stop at the first newly delivered player-facing event; and
* settle already-authorized standing training during the time actually reached.

The caller may direct only Tang Wei and formations already under Tang Wei's saved
authority. Exact House Tang people may be named only to accrue their own existing
autonomous standing-activity contracts; the caller cannot choose their focus,
hours, willingness, or immediate skill result.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from sword_runtime.fatigue import RULES_PATH as FATIGUE_RULES_PATH, settle_formation_idle_fatigue
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_rates import verified_activity_hours_per_cycle
from sword_runtime.training_session import standing_recovery_result
from sword_runtime.training_programs import (
    REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH,
    resolve_program_ref, settle_exact_program,
)
from sword_runtime.training_instructors import exact_person_drill_access, instructor_contexts_for_program
from sword_runtime.training_facilities import training_environment
from sword_runtime.stat_access import merged_skill_map

_RUNTIME_PATH = "state/runtime.json"
_EVENT_PATH = "state/event/events-messages-and-movement.json"
_PROFILES_PATH = "game/data/mil/recruitment-cohort-profiles.json"
_SESSION_RULES_PATH = "game/data/mechanics/training-session.json"
# World-arc reports are informational campaign-event notices. The causal scheduler
# deliberately delivers them without persisting a blocking wake, so this wrapper
# must not turn them back into stop boundaries.
_PLAYER_FACING_EVENT_KINDS = frozenset(
    {
        "institutional_response", "petition_response", "message", "audience_response",
        "campaign_command_council", "campaign_command_superior_order", "campaign_command_after_action_review",
        "campaign_command_dawn_briefing", "campaign_command_evening_sitrep",
    }
)
_ACTIVITY_POLICY_KEYS = frozenset(
    {"player_standing_training", "formation_refs", "household_standing_person_refs"}
)
_WAIT_CRITERION_KEYS = frozenset({"event_kinds", "source_refs", "operation_refs", "classifications", "topic_terms"})
_WAIT_POLICY_KEYS = frozenset({*_WAIT_CRITERION_KEYS, "any_of"})
_SCENE_POLICIES = frozenset({"preserve_active_scene", "finish_active_scene", "leave_active_scene", "skip_to_conclusion"})
_WEEK_SECONDS = 7 * 86400


class DowntimeAdvanceMixin:
    """Add bounded player-event waits and concurrent standing training."""

    _downtime_stop_on_player_event = False
    _downtime_wait_policy: dict[str, Any] | None = None

    @staticmethod
    def _policy(payload: Mapping[str, Any]) -> dict[str, Any]:
        raw = payload.get("activity_policy")
        return dict(raw) if isinstance(raw, Mapping) else {}

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._validate_command_semantics(command, payload)
        if command.command_type != "advance_time":
            return
        stop = payload.get("stop_on_player_event", False)
        if not isinstance(stop, bool):
            raise ValueError("stop_on_player_event must be boolean")
        scene_policy = payload.get("scene_policy")
        if scene_policy is not None and (not isinstance(scene_policy, str) or scene_policy not in _SCENE_POLICIES):
            raise ValueError("scene_policy is unsupported")
        wait_raw = payload.get("wait_policy")
        if wait_raw is not None:
            self._normalize_wait_policy(wait_raw)
        raw = payload.get("activity_policy")
        if raw is None:
            return
        if not isinstance(raw, Mapping):
            raise ValueError("activity_policy must be an object")
        if not set(raw).issubset(_ACTIVITY_POLICY_KEYS):
            raise ValueError("activity_policy contains unsupported fields")
        if "player_standing_training" in raw and not isinstance(raw.get("player_standing_training"), bool):
            raise ValueError("activity_policy.player_standing_training must be boolean")
        for key in ("formation_refs", "household_standing_person_refs"):
            values = raw.get(key, [])
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
                raise ValueError(f"activity_policy.{key} must be an array")
            if len(values) > 128:
                raise ValueError(f"activity_policy.{key} exceeds bounded size")
            normalized = [str(value) for value in values]
            if any(not value for value in normalized) or len(set(normalized)) != len(normalized):
                raise ValueError(f"activity_policy.{key} must contain unique exact refs")

    def _authorize_command(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._authorize_command(command, payload)
        if command.command_type != "advance_time":
            return
        from sword_runtime.scene_sessions import active_scene_session
        active_scene = active_scene_session(self)
        if active_scene is not None and payload.get("scene_policy") is None:
            raise ValueError("advance_time across an active scene requires explicit scene_policy")
        policy = self._policy(payload)
        for formation_ref in policy.get("formation_refs", []):
            self._require_formation_authority(command.actor_id, str(formation_ref))
        for person_ref in policy.get("household_standing_person_refs", []):
            _path, person = self._exact_person(str(person_ref), active=False)
            contract = person.get("activity_contract") if isinstance(person.get("activity_contract"), Mapping) else {}
            if str(person.get("affiliation", "")) != "House Tang":
                raise PermissionError("downtime may settle only exact House Tang standing-person activity")
            if str(contract.get("mode", "")) != "standing_role_training" or contract.get("autonomous_enabled") is False:
                raise PermissionError("named person lacks an autonomous standing training contract")

    @staticmethod
    def _normalize_wait_clause(value: object) -> dict[str, list[str]]:
        if not isinstance(value, Mapping) or not value or set(value) - _WAIT_CRITERION_KEYS:
            raise ValueError("wait_policy clause contains unsupported fields")
        out: dict[str, list[str]] = {}
        for key in _WAIT_CRITERION_KEYS:
            values = value.get(key)
            if values is None:
                continue
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)) or not values:
                raise ValueError(f"wait_policy.{key} must be a non-empty array")
            if len(values) > 32:
                raise ValueError(f"wait_policy.{key} exceeds bounded size")
            normalized = [str(item).strip() for item in values]
            if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
                raise ValueError(f"wait_policy.{key} must contain unique non-empty values")
            out[key] = normalized
        if not out:
            raise ValueError("wait_policy clause requires at least one semantic stop criterion")
        return out

    @classmethod
    def _normalize_wait_policy(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, Mapping) or not value or set(value) - _WAIT_POLICY_KEYS:
            raise ValueError("wait_policy must be a non-empty object with supported fields")
        clauses: list[dict[str, list[str]]] = []
        top = {key: value[key] for key in _WAIT_CRITERION_KEYS if key in value}
        if top:
            clauses.append(cls._normalize_wait_clause(top))
        raw_any = value.get("any_of")
        if raw_any is not None:
            if not isinstance(raw_any, Sequence) or isinstance(raw_any, (str, bytes, bytearray)) or not raw_any:
                raise ValueError("wait_policy.any_of must be a non-empty array of criterion objects")
            if len(raw_any) > 16:
                raise ValueError("wait_policy.any_of exceeds bounded size")
            clauses.extend(cls._normalize_wait_clause(item) for item in raw_any)
        if not clauses:
            raise ValueError("wait_policy requires at least one semantic stop criterion")
        return {"any_of": clauses}

    @staticmethod
    def _event_matches_wait_clause(event_ref: str, event: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
        kind = str(event.get("kind", ""))
        requested_kinds = set(str(x) for x in policy.get("event_kinds", []))
        if requested_kinds and kind not in requested_kinds:
            return False

        source_values = {event_ref}
        for key in ("source_ref", "source_event_ref", "arc_ref", "campaign_command_cycle_ref"):
            value = event.get(key)
            if isinstance(value, str):
                source_values.add(value)
        requested_sources = set(str(x) for x in policy.get("source_refs", []))
        if requested_sources and not source_values.intersection(requested_sources):
            return False

        operation_values = {
            str(event.get(key)) for key in ("operation_ref", "mission_ref", "campaign_operation_ref")
            if isinstance(event.get(key), str)
        }
        requested_operations = set(str(x) for x in policy.get("operation_refs", []))
        if requested_operations and not operation_values.intersection(requested_operations):
            return False

        provenance = event.get("provenance") if isinstance(event.get("provenance"), Mapping) else {}
        classifications = {
            str(value) for value in (
                event.get("classification"), event.get("significance"), event.get("priority_class"),
                provenance.get("player_safe_evidence_kind"), provenance.get("kind"),
            ) if isinstance(value, str)
        }
        requested_classes = set(str(x) for x in policy.get("classifications", []))
        if requested_classes and not classifications.intersection(requested_classes):
            return False

        topic_terms = [str(x).casefold() for x in policy.get("topic_terms", [])]
        if topic_terms:
            topic_values: list[str] = []
            for key in ("topic", "summary"):
                value = event.get(key)
                if isinstance(value, str):
                    topic_values.append(value.casefold())
            for key in ("topics", "tags"):
                values = event.get(key)
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
                    topic_values.extend(str(x).casefold() for x in values)
            haystack = " ".join(topic_values)
            if not any(term in haystack for term in topic_terms):
                return False
        return True

    @classmethod
    def _event_matches_wait_policy(cls, event_ref: str, event: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
        normalized = policy if isinstance(policy.get("any_of"), list) else cls._normalize_wait_policy(policy)
        return any(
            isinstance(clause, Mapping) and cls._event_matches_wait_clause(event_ref, event, clause)
            for clause in normalized.get("any_of", [])
        )

    def _player_facing_event_refs(self) -> set[str]:
        owner = self.read(_EVENT_PATH)
        causal = owner.get("causal_events") if isinstance(owner, Mapping) else None
        if not isinstance(causal, Mapping):
            return set()
        policy = self._downtime_wait_policy if isinstance(self._downtime_wait_policy, Mapping) else None
        refs: set[str] = set()
        for event_ref, event in causal.items():
            if not isinstance(event_ref, str) or not isinstance(event, Mapping) or event.get("status") != "triggered":
                continue
            if policy is not None:
                if self._event_matches_wait_policy(event_ref, event, policy):
                    refs.add(event_ref)
            elif str(event.get("kind", "")) in _PLAYER_FACING_EVENT_KINDS:
                refs.add(event_ref)
        return refs

    def _next_scheduler_boundary(self, current: CampaignTime, target: CampaignTime) -> CampaignTime:
        runtime = self.read(_RUNTIME_PATH)
        hosts = runtime.get("hosts") if isinstance(runtime, Mapping) else None
        events = runtime.get("events") if isinstance(runtime, Mapping) else None
        if not isinstance(hosts, Mapping) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        due_values: list[CampaignTime] = []
        for event in events:
            if not isinstance(event, Mapping) or event.get("suspended") is True:
                continue
            host_id = event.get("target_host")
            host = hosts.get(host_id) if isinstance(host_id, str) else None
            due_text = event.get("due_at")
            if not isinstance(host, Mapping) or host.get("next_due") is None or not isinstance(due_text, str):
                continue
            due = CampaignTime.parse(due_text)
            if due < current or due > target:
                continue
            due_values.append(due)
        return min(due_values) if due_values else target

    @staticmethod
    def _merge_time_metrics(total: dict[str, Any], metrics: Mapping[str, Any]) -> None:
        total["hosts_woken"] = int(total.get("hosts_woken", 0)) + int(metrics.get("hosts_woken", 0))
        total["events_processed"] = int(total.get("events_processed", 0)) + int(metrics.get("events_processed", 0))
        total["battlefield_reviews"] = int(total.get("battlefield_reviews", 0)) + int(metrics.get("battlefield_reviews", 0))
        reports = total.setdefault("battlefield_reports", [])
        if isinstance(reports, list):
            reports.extend(row for row in metrics.get("battlefield_reports", []) if isinstance(row, Mapping))
        notices = total.setdefault("campaign_event_notices", [])
        if isinstance(notices, list):
            notices.extend(row for row in metrics.get("campaign_event_notices", []) if isinstance(row, Mapping))

    @staticmethod
    def _focuses(person: Mapping[str, Any], contract: Mapping[str, Any]) -> list[str]:
        value = contract.get("focus")
        candidates = [part.strip() for part in str(value).split(",")] if isinstance(value, str) else []
        skills = merged_skill_map(person)
        return [focus for focus in candidates if focus and focus in skills]

    def _settle_player_training(self, start: CampaignTime, end: CampaignTime, request_id: str) -> dict[str, Any]:
        """Legacy eager settlement, kept deterministic for non-production MROs.

        Production uses the standing-credit owner, but this path must not remain a
        caller-focus backdoor. Elapsed standing hours settle through Wei's saved
        registered program, physical access, instructor availability, and time ledger.
        """
        player = deepcopy(self.read("state/player.json"))
        contract = player.get("activity_contract") if isinstance(player.get("activity_contract"), Mapping) else {}
        weekly = float(contract.get("verified_hours_per_7d", 0.0) or 0.0)
        if weekly <= 0:
            return {"status": "not_configured", "settled_hours": 0}
        elapsed = max(0, start.seconds_until(end))
        ds = player.setdefault("development_state", {})
        credit = float(ds.get("standing_training_time_credit_hours", 0.0)) + weekly * elapsed / _WEEK_SECONDS
        whole = max(0, int(credit))
        ds["standing_training_time_credit_hours"] = round(credit - whole, 6)
        if whole <= 0:
            ds["standing_training_last_accrued_at"] = str(end)
            self.put("state/player.json", player)
            return {
                "status": "accrued",
                "settled_hours": 0,
                "credit_hours": ds["standing_training_time_credit_hours"],
            }

        training = self.read("game/data/mechanics/training.json")
        session_rules = self.read(_SESSION_RULES_PATH)
        registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
        explicit_program = str(contract.get("training_program_ref", "") or "")
        program_ref = resolve_program_ref(registry, person=player, explicit_program_ref=explicit_program or None)
        profiles = self.read(_PROFILES_PATH)
        regimens = profiles.get("training_regimens", {}) if isinstance(profiles, Mapping) else {}
        regimen = regimens.get(str(contract.get("training_regimen_ref", "regular_army")), {}) if isinstance(regimens, Mapping) else {}
        if not isinstance(regimen, Mapping):
            regimen = {}
        player_location = str(self._person_location(player) or "") if hasattr(self, "_person_location") else str(player.get("location", "") or "")
        environment = training_environment(self, location_ref=player_location, simultaneous_trainees=1) if player_location else {"facility_grade": "none", "capacity_factor": 0.0}
        evidence = f"downtime_player_training:{request_id}"
        contexts = instructor_contexts_for_program(
            self, registry=registry, training_rules=training, program_ref=program_ref,
            trainee_skills=merged_skill_map(player),
            student_count=1, location_ref=player_location, trainee_ref=getattr(self, "PLAYER_ACTOR", "char_tang_wei"),
            scheduled_hours=float(whole), window_start=str(start), window_end=str(end),
            evidence_ref=evidence, reserve_duty=True,
        )
        drill_access = exact_person_drill_access(self, registry=registry, program_ref=program_ref, person=player)
        development = settle_exact_program(
            player, registry=registry, program_ref=program_ref, hours=whole, at=end,
            training_rules=training, session_rules=session_rules,
            facility_grade=str(environment.get("facility_grade", "none")),
            equipment_grade=str(regimen.get("equipment_grade", "adequate")),
            recovery_grade=str(regimen.get("recovery_grade", "adequate")),
            feedback_grade=str(regimen.get("feedback_grade", "ordinary")),
            cursor_key="standing_downtime_deterministic_cursor",
            instructor_context_by_drill=contexts, drill_access=drill_access,
            time_window_start=str(start), time_window_end=str(end), time_evidence_ref=evidence,
        )
        settled = max(0, int(development.get("verified_hours", whole) or 0))
        ds = player.setdefault("development_state", {})
        ds["standing_training_time_credit_hours"] = round(max(0.0, credit - settled), 6)
        ds["standing_training_last_settled_at"] = str(end)
        last_training = ds.get("last_training") if isinstance(ds.get("last_training"), Mapping) else {}
        ds["last_training"] = {
            **dict(last_training),
            "started_at": str(start), "completed_at": str(end),
            "verified_hours": settled, "program_ref": program_ref,
        }
        self.put("state/player.json", player)
        return {
            "status": "settled",
            "settled_hours": settled,
            "credit_hours": ds["standing_training_time_credit_hours"],
            "program_ref": program_ref,
            "development": development,
        }

    def _settle_formation_training(
        self,
        formation_ref: str,
        start: CampaignTime,
        end: CampaignTime,
        request_id: str,
    ) -> dict[str, Any]:
        path, formation0 = self._load_formation(formation_ref)
        formation = deepcopy(formation0)
        force_path = self.owner_path(str(formation["owner_force_ref"]))
        force = self.read(force_path)
        profiles = self.read(_PROFILES_PATH)
        regimen_name = (
            "house_tang_max_sustainable"
            if str(force.get("owner_id")) in {"force_house_tang"}
            else "regular_army"
        )
        regimen = profiles.get("training_regimens", {}).get(regimen_name, {})
        weekly = float(regimen.get("deliberate_hours_per_7d", 0.0) or 0.0)
        elapsed = max(0, start.seconds_until(end))
        credit = float(formation.get("standing_training_time_credit_hours", 0.0)) + weekly * elapsed / _WEEK_SECONDS
        whole = max(0, int(credit))
        formation["standing_training_time_credit_hours"] = round(credit - whole, 6)
        fatigue_rules = self.read(FATIGUE_RULES_PATH)
        # Settle rest earned before this downtime window, then account for this
        # exact interval once. A no-training window is pure recovery; a standing
        # training window receives nightly recovery plus only registered overload.
        settle_formation_idle_fatigue(formation, current=start, rules=fatigue_rules)
        if whole <= 0:
            recovery = settle_formation_idle_fatigue(formation, current=end, rules=fatigue_rules)
            formation["standing_training_last_accrued_at"] = str(end)
            self.put(path, formation)
            return {
                "formation_ref": formation_ref,
                "status": "accrued",
                "settled_hours": 0,
                "credit_hours": formation["standing_training_time_credit_hours"],
                "fatigue_recovery": recovery,
            }

        training_rules = self.read("game/data/mechanics/training.json")
        session_rules = self.read(_SESSION_RULES_PATH)
        normal_weekly = float(training_rules.get("time_budget", {}).get("deliberate_training_hours_per_7d_normal_max", 48.0) or 0.0)
        recovery = standing_recovery_result(
            fatigue=int(formation.get("fatigue", 0) or 0),
            started_at=start,
            completed_at=end,
            completed_deliberate_hours=float(whole),
            normal_deliberate_hours_per_7d=normal_weekly,
            session_rules=session_rules,
        )
        formation["fatigue"] = int(recovery["fatigue_after"])
        formation["fatigue_recovery_through"] = str(end)
        formation["standing_training_recovery_through"] = str(end)
        formation["training_progress"] = min(100, int(formation.get("training_progress", 0)) + max(1, whole // 4))
        formation["cohesion"] = min(100, int(formation.get("cohesion", 50)) + max(1, whole // 4))
        formation["readiness"] = min(100, int(formation.get("readiness", 50)) + max(0, whole // 6))
        formation["verified_training_hours"] = int(formation.get("verified_training_hours", 0)) + whole
        formation["last_training_at"] = str(end)
        self.put(path, formation)
        if hasattr(self, "_ct_train_formation"):
            self._ct_train_formation(
                formation_ref,
                float(whole),
                f"downtime_training:{request_id}:{formation_ref}",
            )
        settled = deepcopy(self.read(path))
        settled["standing_training_time_credit_hours"] = round(credit - whole, 6)
        settled["last_training"] = {
            "started_at": str(start),
            "completed_at": str(end),
            "hours": whole,
        }
        self.put(path, settled)
        return {
            "formation_ref": formation_ref,
            "status": "settled",
            "settled_hours": whole,
            "credit_hours": settled["standing_training_time_credit_hours"],
            "fatigue_recovery": recovery,
        }

    def _accrue_household_person_activity(
        self,
        person_ref: str,
        start: CampaignTime,
        end: CampaignTime,
        request_id: str,
    ) -> dict[str, Any]:
        path, person0 = self._exact_person(person_ref, active=False)
        person = deepcopy(person0)
        contract = person.get("activity_contract") if isinstance(person.get("activity_contract"), Mapping) else {}
        activity = person.setdefault("autonomous_activity_state", {})
        cadence = max(1, int(activity.get("cadence_seconds", 30 * 86400)))
        cycle_hours = verified_activity_hours_per_cycle(
            person,
            contract,
            self.read(_PROFILES_PATH),
            cadence,
            fallback_hours=48.0,
        )
        if cycle_hours <= 0:
            raise PermissionError("named person does not have an adult standing-role training rate")
        activity["verified_hours_per_cycle"] = round(cycle_hours, 6)
        next_due_text = activity.get("next_due")
        cycle_start = start
        if isinstance(next_due_text, str):
            cycle_start = CampaignTime.parse(next_due_text).add_seconds(-cadence)
        prior_cycle = activity.get("interim_cycle_started_at")
        if prior_cycle != str(cycle_start):
            activity["interim_verified_activity_hours"] = 0.0
            activity["interim_cycle_started_at"] = str(cycle_start)
        eligible_start = max(start, cycle_start)
        eligible_seconds = max(0, eligible_start.seconds_until(end)) if end >= eligible_start else 0
        accrued = cycle_hours * eligible_seconds / cadence
        total = float(activity.get("interim_verified_activity_hours", 0.0)) + accrued
        activity["interim_verified_activity_hours"] = round(min(cycle_hours, total), 6)
        activity["interim_last_accrued_at"] = str(end)
        activity["interim_accrual_rule"] = (
            "progress evidence only; rate derives from the canonical regimen when applicable; exact skill settlement remains owned by the person's autonomous activity cycle"
        )
        self.put(path, person)
        return {
            "person_ref": person_ref,
            "status": "accrued_under_autonomous_contract",
            "verified_activity_hours_in_current_cycle": activity["interim_verified_activity_hours"],
            "skill_settlement_deferred_to_activity_host": True,
            "action_ref": request_id,
        }

    def _settle_downtime_policy(
        self,
        start: CampaignTime,
        end: CampaignTime,
        policy: Mapping[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"elapsed_seconds": max(0, start.seconds_until(end))}
        if policy.get("player_standing_training") is True:
            result["player"] = self._settle_player_training(start, end, request_id)
        formations = []
        for formation_ref in policy.get("formation_refs", []):
            formations.append(self._settle_formation_training(str(formation_ref), start, end, request_id))
        if formations:
            result["formations"] = formations
        people = []
        for person_ref in policy.get("household_standing_person_refs", []):
            people.append(self._accrue_household_person_activity(str(person_ref), start, end, request_id))
        if people:
            result["household_people"] = people
        return result

    def _command_layer_downtime(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        if command.command_type != "advance_time":
            return next_dispatch()
        policy = self._policy(payload)
        start = CampaignTime.parse(str(self.read(_RUNTIME_PATH)["world_time"]))
        scene_policy = payload.get("scene_policy")
        # A saved standing routine is campaign state, not a caller-side feature
        # flag. During ordinary broad downtime it accrues automatically unless
        # the caller explicitly pauses it or Wei is preserving an active scene.
        if "player_standing_training" not in policy and scene_policy != "preserve_active_scene":
            player = self.read("state/player.json")
            contract = player.get("activity_contract") if isinstance(player, Mapping) and isinstance(player.get("activity_contract"), Mapping) else {}
            if (
                isinstance(contract, Mapping)
                and float(contract.get("verified_hours_per_7d", 0.0) or 0.0) > 0
                and contract.get("autonomous_enabled") is not False
            ):
                policy["player_standing_training"] = True
        if scene_policy in {"finish_active_scene", "leave_active_scene", "skip_to_conclusion"}:
            from sword_runtime.scene_sessions import close_active_scene
            reason = {
                "finish_active_scene": "completed",
                "leave_active_scene": "player_left",
                "skip_to_conclusion": "skipped_to_conclusion",
            }[str(scene_policy)]
            close_active_scene(self, at=str(start), reason=reason)
        previous_stop = self._downtime_stop_on_player_event
        previous_wait = self._downtime_wait_policy
        raw_wait = payload.get("wait_policy")
        self._downtime_wait_policy = self._normalize_wait_policy(raw_wait) if isinstance(raw_wait, Mapping) else None
        self._downtime_stop_on_player_event = bool(payload.get("stop_on_player_event", False) or self._downtime_wait_policy)
        try:
            result = next_dispatch()
        finally:
            self._downtime_stop_on_player_event = previous_stop
            self._downtime_wait_policy = previous_wait
        end = CampaignTime.parse(str(self.read(_RUNTIME_PATH)["world_time"]))
        updated = dict(result)
        if raw_wait is not None:
            updated["semantic_wait_policy"] = deepcopy(self._normalize_wait_policy(raw_wait))
            notices = updated.get("campaign_event_notices")
            if isinstance(notices, list):
                updated["campaign_event_notices"] = [
                    row for row in notices
                    if isinstance(row, Mapping) and self._event_matches_wait_policy(
                        str(row.get("event_ref") or row.get("source_event_ref") or row.get("source_ref") or ""),
                        row, raw_wait,
                    )
                ]
        if scene_policy == "preserve_active_scene" and bool(updated.get("wake_required")):
            from sword_runtime.scene_sessions import close_active_scene
            closed = close_active_scene(self, at=str(end), reason="hard_interruption")
            if closed is not None:
                updated["scene_closed_for_hard_interruption"] = True
        if scene_policy is not None:
            updated["scene_policy"] = scene_policy
        if policy and end >= start:
            updated["downtime_activity"] = self._settle_downtime_policy(
                start, end, policy, command.semantic_digest[:24],
            )
        return updated



__all__ = ["DowntimeAdvanceMixin"]
