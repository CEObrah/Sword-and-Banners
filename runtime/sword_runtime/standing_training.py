"""Standing-training credit accrual and deterministic settlement.

Time advancement owns chronology. This module owns the reconciliation of
training time earned during an explicit downtime window. It never accepts
caller-supplied hours or focuses: Tang Wei's saved standing plan and a controlled
formation's registered regimen determine accrual and settlement.

The normal downtime path consumes each targeted formation's whole earned credit
inside the same advance_time transaction and leaves only fractional credit banked.
The standalone settlement command remains available for already-existing credits
and recovery workflows without advancing time.

Exact autonomous NPCs remain outside player training authority. House Tang people
named in a downtime activity policy accrue evidence under their own saved activity
contracts through the existing downtime helper; this module never settles their
skills from a player command.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sword_runtime.cohort_personnel import ensure_formation_composition, cohort_merged_skill_means
from sword_runtime.engine import _clamp
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_session import standing_recovery_result
from sword_runtime.training_instructors import exact_person_drill_access, instructor_contexts_for_program
from sword_runtime.training_facilities import training_environment
from sword_runtime.stat_access import merged_skill_map
from sword_runtime.training_programs import (
    formation_training_ref_for_role,
    REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH,
    drill_record,
    program_record,
    resolve_program_ref,
    settle_exact_program,
)

_RUNTIME_PATH = "state/runtime.json"
_SESSION_RULES_PATH = "game/data/mechanics/training-session.json"
_WEEK_SECONDS = 7 * 86400


class StandingTrainingSettlementMixin:
    """Accrue downtime credits and consume whole earned credit deterministically."""

    # ------------------------------------------------------------------
    # Command admission
    # ------------------------------------------------------------------

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._validate_command_semantics(command, payload)
        if command.command_type != "standing_training_settle":
            return
        target_ref = payload.get("target_ref")
        if not isinstance(target_ref, str) or not target_ref:
            raise ValueError("standing_training_settle requires target_ref")
        if target_ref != self.PLAYER_ACTOR and not target_ref.startswith("formation_"):
            raise ValueError("standing training target must be Tang Wei or an exact formation")

    def _authorize_command(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._authorize_command(command, payload)
        if command.command_type != "standing_training_settle":
            return
        target_ref = str(payload["target_ref"])
        if target_ref == self.PLAYER_ACTOR:
            return
        self._require_formation_authority(command.actor_id, target_ref)

    # ------------------------------------------------------------------
    # Downtime accrual and same-command settlement
    # ------------------------------------------------------------------

    @staticmethod
    def _parsed_credit_window_start(
        owner: Mapping[str, Any],
    ) -> CampaignTime | None:
        value = owner.get("standing_training_credit_window_start")
        if not isinstance(value, str) or not value:
            return None
        try:
            return CampaignTime.parse(value)
        except (TypeError, ValueError):
            return None

    def _expire_orphan_standing_credit(
        self,
        owner: dict[str, Any],
        *,
        new_window_start: CampaignTime,
    ) -> float:
        """Expire credit that has no lawful recovery-window provenance.

        Standing credit is evidence of deliberate time inside a dated downtime
        window, not timeless XP. Legacy positive credit without a parseable start
        cannot safely be combined with a new interval: doing so previously made
        settlement fall back to the current timestamp and converted ordinary
        rested training into zero-time overload.
        """
        credit = float(owner.get("standing_training_time_credit_hours", 0.0) or 0.0)
        if credit <= 1e-9:
            return 0.0
        parsed = self._parsed_credit_window_start(owner)
        if parsed is not None and parsed <= new_window_start:
            return 0.0
        owner["standing_training_time_credit_hours"] = 0.0
        owner.pop("standing_training_credit_window_start", None)
        owner.pop("standing_training_credit_window_end", None)
        owner.pop("standing_training_recovery_through", None)
        return credit

    def _accrue_player_standing_credit(
        self,
        start: CampaignTime,
        end: CampaignTime,
        request_id: str,
    ) -> dict[str, Any]:
        player = deepcopy(self.read("state/player.json"))
        contract = player.get("activity_contract") if isinstance(player.get("activity_contract"), Mapping) else {}
        weekly = float(contract.get("verified_hours_per_7d", 0.0) or 0.0)
        if weekly <= 0:
            return {"status": "not_configured", "accrued_hours": 0.0}
        elapsed = max(0, start.seconds_until(end))
        accrued = weekly * elapsed / _WEEK_SECONDS
        ds = player.setdefault("development_state", {})
        expired_orphan = self._expire_orphan_standing_credit(ds, new_window_start=start)
        before = float(ds.get("standing_training_time_credit_hours", 0.0) or 0.0)
        after = before + accrued
        ds["standing_training_time_credit_hours"] = round(after, 6)
        if before <= 1e-9:
            ds["standing_training_credit_window_start"] = str(start)
            ds.pop("standing_training_recovery_through", None)
        ds["standing_training_credit_window_end"] = str(end)
        self.put("state/player.json", player)
        result = {
            "status": "accrued",
            "accrued_hours": round(accrued, 6),
            "credit_hours": round(after, 6),
        }
        if expired_orphan > 1e-9:
            result["expired_orphan_credit_hours"] = round(expired_orphan, 6)
        return result

    def _formation_weekly_training_rate(self, formation: Mapping[str, Any]) -> float:
        force_path = self.owner_path(str(formation["owner_force_ref"]))
        force = self.read(force_path)
        profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
        regimen_name = (
            "house_tang_max_sustainable"
            if str(force.get("owner_id")) in {"force_house_tang"}
            else "regular_army"
        )
        regimen = profiles.get("training_regimens", {}).get(regimen_name, {})
        return float(regimen.get("deliberate_hours_per_7d", 0.0) or 0.0)

    def _accrue_formation_standing_credit(
        self,
        formation_ref: str,
        start: CampaignTime,
        end: CampaignTime,
        request_id: str,
    ) -> dict[str, Any]:
        path, raw = self._load_formation(formation_ref)
        formation = deepcopy(raw)
        weekly = self._formation_weekly_training_rate(formation)
        if weekly <= 0:
            return {"formation_ref": formation_ref, "status": "not_configured", "accrued_hours": 0.0}
        elapsed = max(0, start.seconds_until(end))
        accrued = weekly * elapsed / _WEEK_SECONDS
        expired_orphan = self._expire_orphan_standing_credit(formation, new_window_start=start)
        before = float(formation.get("standing_training_time_credit_hours", 0.0) or 0.0)
        after = before + accrued
        formation["standing_training_time_credit_hours"] = round(after, 6)
        if before <= 1e-9:
            formation["standing_training_credit_window_start"] = str(start)
            formation.pop("standing_training_recovery_through", None)
        formation["standing_training_credit_window_end"] = str(end)
        self.put(path, formation)
        result = {
            "formation_ref": formation_ref,
            "status": "accrued",
            "accrued_hours": round(accrued, 6),
            "credit_hours": round(after, 6),
        }
        if expired_orphan > 1e-9:
            result["expired_orphan_credit_hours"] = round(expired_orphan, 6)
        return result

    @staticmethod
    def _compact_formation_auto_settlement(settled: Mapping[str, Any]) -> dict[str, Any]:
        """Return bounded user-facing settlement data for one formation."""
        keys = (
            "target_ref",
            "consumed_hours",
            "remaining_credit_hours",
            "training_progress",
            "cohesion",
            "readiness",
            "fatigue",
            "recovery",
        )
        return {key: settled[key] for key in keys if key in settled}

    def _settle_downtime_policy(
        self,
        start: CampaignTime,
        end: CampaignTime,
        policy: Mapping[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        """Accrue and reconcile explicit standing training in one time command.

        The player's activity policy already declares which controlled formations
        train during this interval. Whole server-owned formation credits are
        therefore deterministic consequences of the same advance_time intent and
        are consumed before that transaction returns. Only fractional credit is
        left banked. A separate standing_training_settle command remains available
        for pre-existing or manually deferred credit.
        """
        result: dict[str, Any] = {"elapsed_seconds": max(0, start.seconds_until(end))}
        if policy.get("player_standing_training") is True:
            result["player"] = self._accrue_player_standing_credit(start, end, request_id)
            player_now = self.read("state/player.json")
            contract_now = player_now.get("activity_contract") if isinstance(player_now, Mapping) else None
            if isinstance(contract_now, Mapping) and contract_now.get("auto_settle_standing_training") is True:
                credit = float(player_now.get("development_state", {}).get("standing_training_time_credit_hours", 0.0) or 0.0)
                if credit >= 1.0:
                    result["player_auto_settlement"] = self._consume_player_standing_credit(end, request_id + ":auto")
        formations: list[dict[str, Any]] = []
        for formation_ref in policy.get("formation_refs", []):
            ref = str(formation_ref)
            accrued = self._accrue_formation_standing_credit(ref, start, end, request_id)
            entry = dict(accrued)
            if accrued.get("status") == "accrued":
                _path, formation_now = self._load_formation(ref)
                credit = float(formation_now.get("standing_training_time_credit_hours", 0.0) or 0.0)
                if credit >= 1.0:
                    settled = self._consume_formation_standing_credit(
                        ref,
                        end,
                        request_id + ":auto",
                    )
                    compact = self._compact_formation_auto_settlement(settled)
                    entry["auto_settlement"] = compact
                    entry["credit_hours"] = float(compact.get("remaining_credit_hours", 0.0) or 0.0)
            formations.append(entry)
        if formations:
            result["formations"] = formations
        people: list[dict[str, Any]] = []
        for person_ref in policy.get("household_standing_person_refs", []):
            people.append(
                self._accrue_household_person_activity(str(person_ref), start, end, request_id)
            )
        if people:
            result["household_people"] = people
        result["settlement_rule"] = "auto_settle_whole_credits_during_time_advance"
        return result

    # ------------------------------------------------------------------
    # Zero-time credit consumption
    # ------------------------------------------------------------------

    @staticmethod
    def _credit_window_start(owner: Mapping[str, Any], current_text: str) -> str:
        value = owner.get("standing_training_credit_window_start")
        if isinstance(value, str) and value:
            try:
                parsed = CampaignTime.parse(value)
                current = CampaignTime.parse(current_text)
            except (TypeError, ValueError):
                pass
            else:
                if parsed <= current:
                    return value
        raise ValueError(
            "standing training credit has no valid recovery window; accrue a new downtime interval before settlement"
        )

    def _standing_recovery(
        self,
        owner: Mapping[str, Any],
        *,
        fatigue: int,
        current: CampaignTime,
        completed_hours: float,
        training: Mapping[str, Any],
        session_rules: Mapping[str, Any],
    ) -> dict[str, Any]:
        current_text = str(current)
        start_text = owner.get("standing_training_recovery_through")
        if not isinstance(start_text, str) or not start_text:
            start_text = self._credit_window_start(owner, current_text)
        start = CampaignTime.parse(start_text)
        if start > current:
            start = current
        normal_weekly = float(
            training.get("time_budget", {}).get("deliberate_training_hours_per_7d_normal_max", 48.0) or 0.0
        )
        return standing_recovery_result(
            fatigue=fatigue,
            started_at=start,
            completed_at=current,
            completed_deliberate_hours=completed_hours,
            normal_deliberate_hours_per_7d=normal_weekly,
            session_rules=session_rules,
        )

    def _consume_player_standing_credit(self, current: CampaignTime, request_id: str) -> dict[str, Any]:
        player = deepcopy(self.read("state/player.json"))
        ds = player.setdefault("development_state", {})
        credit = float(ds.get("standing_training_time_credit_hours", 0.0) or 0.0)
        whole = max(0, int(credit + 1e-9))
        if whole < 1:
            raise ValueError("insufficient standing training credit")
        contract = player.get("activity_contract") if isinstance(player.get("activity_contract"), Mapping) else {}
        training = self.read("game/data/mechanics/training.json")
        session_rules = self.read(_SESSION_RULES_PATH)
        profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
        regimens = profiles.get("training_regimens", {}) if isinstance(profiles, Mapping) else {}
        regimen = regimens.get(str(contract.get("training_regimen_ref", "regular_army")), {}) if isinstance(regimens, Mapping) else {}
        if not isinstance(regimen, Mapping):
            regimen = {}
        registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
        explicit_program = str(contract.get("training_program_ref", "") or "")
        program_ref = resolve_program_ref(
            registry, person=player, explicit_program_ref=explicit_program or None
        )
        raw_training_start = ds.get("standing_training_credit_window_start")
        if isinstance(raw_training_start, str) and raw_training_start:
            parsed_training_start = CampaignTime.parse(raw_training_start)
            training_window_start = (
                str(parsed_training_start)
                if parsed_training_start < current
                else str(current.add_seconds(-whole * 3600))
            )
        else:
            training_window_start = str(current.add_seconds(-whole * 3600))
        player_location = ""
        if hasattr(self, "_person_location"):
            player_location = str(self._person_location(player) or "")
        environment = training_environment(self, location_ref=player_location, simultaneous_trainees=1) if player_location else {"facility_grade": "none", "capacity_factor": 0.0}
        training_evidence = f"standing_player_training:{request_id}"
        instructor_contexts = instructor_contexts_for_program(
            self, registry=registry, training_rules=training, program_ref=program_ref,
            trainee_skills=merged_skill_map(player),
            student_count=1, location_ref=player_location, trainee_ref=self.PLAYER_ACTOR,
            scheduled_hours=float(whole), window_start=training_window_start, window_end=str(current),
            evidence_ref=training_evidence, reserve_duty=True,
        )
        drill_access = exact_person_drill_access(self, registry=registry, program_ref=program_ref, person=player)
        development = settle_exact_program(
            player, registry=registry, program_ref=program_ref, hours=whole, at=current,
            training_rules=training, session_rules=session_rules,
            facility_grade=str(environment.get("facility_grade", "none")),
            equipment_grade=str(regimen.get("equipment_grade", "adequate")),
            recovery_grade=str(regimen.get("recovery_grade", "adequate")),
            feedback_grade=str(regimen.get("feedback_grade", "ordinary")),
            cursor_key="standing_deterministic_training_cursor",
            instructor_context_by_drill=instructor_contexts,
            drill_access=drill_access,
            time_window_start=training_window_start, time_window_end=str(current),
            time_evidence_ref=training_evidence,
        )
        consumed = max(0, int(development.get("verified_hours", whole) or 0))
        recovery = self._standing_recovery(
            ds, fatigue=int(player.get("fatigue", 0) or 0), current=current,
            completed_hours=float(consumed), training=training, session_rules=session_rules,
        )
        player["fatigue"] = int(recovery["fatigue_after"])
        remainder = max(0.0, credit - consumed)
        ds = player.setdefault("development_state", {})
        ds["standing_training_time_credit_hours"] = round(remainder, 6)
        ds["standing_training_last_settled_at"] = str(current)
        ds["standing_training_recovery_through"] = str(current)
        if remainder <= 1e-9:
            ds.pop("standing_training_credit_window_start", None)
            ds.pop("standing_training_credit_window_end", None)
            ds.pop("standing_training_recovery_through", None)
        self.put("state/player.json", player)
        return {
            "target_ref": self.PLAYER_ACTOR, "consumed_hours": consumed,
            "remaining_credit_hours": round(remainder, 6), "fatigue": int(player.get("fatigue", 0)),
            "recovery": recovery, "program_ref": program_ref, "development": development,
        }

    def _formation_capability_snapshot(self, formation_ref: str) -> dict[str, Any]:
        """Project trained cohort means and banked EDU for one controlled formation."""

        _path, raw = self._load_formation(formation_ref)
        formation = deepcopy(raw)
        force_path = self.owner_path(str(formation["owner_force_ref"]))
        force = deepcopy(self.read(force_path))
        if hasattr(self, "_seed_standing_force_capability"):
            self._seed_standing_force_capability(force)
        ensure_formation_composition(force, formation)

        ledger = force.get("cohort_ledger", {})
        cohorts = ledger.get("cohorts", {}) if isinstance(ledger, Mapping) else {}
        registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)

        aggregate_represented = 0
        person_lite_represented = 0
        verified_training_total = 0.0
        verified_training_count = 0
        sums: dict[str, dict[str, float]] = {
            "attribute_means": {},
            "attribute_edu_banks": {},
            "skill_means": {},
            "skill_edu_banks": {},
        }
        counts: dict[str, dict[str, int]] = {key: {} for key in sums}

        for item in formation.get("cohort_composition", []):
            if not isinstance(item, Mapping):
                continue
            count = max(0, int(item.get("count", 0)))
            cohort = cohorts.get(str(item.get("cohort_id"))) if isinstance(cohorts, Mapping) else None
            if count <= 0 or not isinstance(cohort, Mapping):
                continue
            aggregate_represented += count
            verified_training_total += float(cohort.get("verified_training_hours_per_person", 0.0) or 0.0) * count
            verified_training_count += count
            role = str(cohort.get("role") or next(iter(formation.get("composition", {})), "line_infantry"))
            program_ref = resolve_program_ref(
                registry, role=role, training_ref=str(formation.get("training_ref", "") or "")
            )
            skill_names: list[str] = []
            attribute_names: list[str] = []
            seen_skills: set[str] = set(); seen_attributes: set[str] = set()
            for program_row in program_record(registry, program_ref).get("rotation", []):
                if not isinstance(program_row, Mapping):
                    continue
                drill = drill_record(registry, str(program_row.get("drill_ref", "")))
                for name in drill.get("skills", []):
                    text = str(name)
                    if text not in seen_skills:
                        seen_skills.add(text); skill_names.append(text)
                for name in drill.get("attributes", []):
                    text = str(name)
                    if text not in seen_attributes:
                        seen_attributes.add(text); attribute_names.append(text)
            for mean_key, bank_key, names in (
                ("attribute_means", "attribute_edu_banks", attribute_names),
                ("skill_means", "skill_edu_banks", skill_names),
            ):
                means = cohort_merged_skill_means(cohort) if mean_key == "skill_means" else (cohort.get(mean_key, {}) if isinstance(cohort.get(mean_key), Mapping) else {})
                banks = cohort.get(bank_key, {}) if isinstance(cohort.get(bank_key), Mapping) else {}
                for name in names:
                    if name in means:
                        sums[mean_key][name] = sums[mean_key].get(name, 0.0) + float(means[name]) * count
                        counts[mean_key][name] = counts[mean_key].get(name, 0) + count
                    if name in banks:
                        sums[bank_key][name] = sums[bank_key].get(name, 0.0) + float(banks[name]) * count
                        counts[bank_key][name] = counts[bank_key].get(name, 0) + count

        # Materialized internal person-lite commanders are conserved fighting
        # bodies removed from the aggregate cohort slice. Include them in the
        # same capability snapshot without counting the external Unit commander
        # or external staff officer. This keeps a 500 establishment represented as 495 aggregate
        # Champions + 5 person-lite 100-commanders = 500 fighters.
        if hasattr(self, "_ct_command_refs"):
            lite_refs, _exact_refs = self._ct_command_refs(formation)
            internal_refs = {
                ref: role for ref, role in lite_refs.items()
                if str(role).startswith("internal_")
            }
            if internal_refs:
                index = self.read("state/cmd/command-personnel.json")
                record_index = index.get("record_index", {}) if isinstance(index, Mapping) else {}
                for person_ref, role_label in sorted(internal_refs.items()):
                    route = record_index.get(person_ref) if isinstance(record_index, Mapping) else None
                    if not isinstance(route, str) or not route:
                        continue
                    try:
                        person = self.read(route)
                    except Exception:
                        continue
                    if not isinstance(person, Mapping) or str(person.get("schema", "")) != "person-lite":
                        continue
                    assignment = person.get("command_assignment", {}) if isinstance(person.get("command_assignment"), Mapping) else {}
                    if str(assignment.get("formation_ref", "")) != formation_ref:
                        continue
                    if bool(assignment.get("external_to_fighting_strength", False)):
                        continue
                    person_lite_represented += 1
                    dev = person.get("development_state", {}) if isinstance(person.get("development_state"), Mapping) else {}
                    verified_training_total += float(dev.get("verified_training_hours", 0.0) or 0.0)
                    verified_training_count += 1
                    stats = person.get("stats", {}) if isinstance(person.get("stats"), Mapping) else {}
                    skills = merged_skill_map(person)
                    attrs = stats.get("attributes", {}) if isinstance(stats.get("attributes"), Mapping) else {}
                    skill_banks = dev.get("skill_edu_banks", {}) if isinstance(dev.get("skill_edu_banks"), Mapping) else {}
                    attr_banks = dev.get("attribute_edu_banks", {}) if isinstance(dev.get("attribute_edu_banks"), Mapping) else {}
                    program_ref = resolve_program_ref(
                        registry, role="command_personnel",
                        training_ref=str(formation.get("training_ref", "") or ""), person=person,
                    )
                    skill_names: set[str] = set()
                    attribute_names: set[str] = set()
                    for program_row in program_record(registry, program_ref).get("rotation", []):
                        if not isinstance(program_row, Mapping):
                            continue
                        drill = drill_record(registry, str(program_row.get("drill_ref", "")))
                        skill_names.update(str(name) for name in drill.get("skills", []))
                        attribute_names.update(str(name) for name in drill.get("attributes", []))
                    for mean_key, bank_key, source, banks, names in (
                        ("skill_means", "skill_edu_banks", skills, skill_banks, skill_names),
                        ("attribute_means", "attribute_edu_banks", attrs, attr_banks, attribute_names),
                    ):
                        for name in names:
                            if name in source:
                                sums[mean_key][name] = sums[mean_key].get(name, 0.0) + float(source[name])
                                counts[mean_key][name] = counts[mean_key].get(name, 0) + 1
                            if name in banks:
                                sums[bank_key][name] = sums[bank_key].get(name, 0.0) + float(banks[name])
                                counts[bank_key][name] = counts[bank_key].get(name, 0) + 1

        def averaged(key: str) -> dict[str, float]:
            return {
                name: round(total / counts[key][name], 3)
                for name, total in sorted(sums[key].items())
                if counts[key].get(name, 0) > 0
            }

        represented = aggregate_represented + person_lite_represented
        return {
            "aggregate_represented_personnel": aggregate_represented,
            "person_lite_represented_personnel": person_lite_represented,
            "total_represented_personnel": represented,
            "represented_personnel": represented,
            "verified_training_hours_per_person": round(
                verified_training_total / verified_training_count, 3
            ) if verified_training_count else 0.0,
            "trained_attribute_means": averaged("attribute_means"),
            "trained_skill_means": averaged("skill_means"),
            "attribute_edu_banks": averaged("attribute_edu_banks"),
            "skill_edu_banks": averaged("skill_edu_banks"),
        }

    @staticmethod
    def _capability_development_delta(
        before: Mapping[str, Any],
        after: Mapping[str, Any],
    ) -> dict[str, Any]:
        def changed(key: str) -> dict[str, float]:
            old = before.get(key, {}) if isinstance(before.get(key), Mapping) else {}
            new = after.get(key, {}) if isinstance(after.get(key), Mapping) else {}
            result: dict[str, float] = {}
            for name, value in sorted(new.items()):
                delta = float(value) - float(old.get(name, value))
                if abs(delta) > 1e-9:
                    result[str(name)] = round(delta, 3)
            return result

        return {
            "model": "cohort_means_with_banked_edu",
            "aggregate_represented_personnel": int(after.get("aggregate_represented_personnel", 0) or 0),
            "person_lite_represented_personnel": int(after.get("person_lite_represented_personnel", 0) or 0),
            "total_represented_personnel": int(after.get("total_represented_personnel", after.get("represented_personnel", 0)) or 0),
            "represented_personnel": int(after.get("represented_personnel", 0) or 0),
            "verified_training_hours_per_person": float(
                after.get("verified_training_hours_per_person", 0.0) or 0.0
            ),
            "trained_attribute_means": dict(after.get("trained_attribute_means", {})),
            "trained_skill_means": dict(after.get("trained_skill_means", {})),
            "attribute_mean_changes": changed("trained_attribute_means"),
            "skill_mean_changes": changed("trained_skill_means"),
            "attribute_edu_banks": dict(after.get("attribute_edu_banks", {})),
            "skill_edu_banks": dict(after.get("skill_edu_banks", {})),
        }

    def _consume_formation_standing_credit(
        self,
        formation_ref: str,
        current: CampaignTime,
        request_id: str,
    ) -> dict[str, Any]:
        path, raw = self._load_formation(formation_ref)
        formation = deepcopy(raw)
        credit = float(formation.get("standing_training_time_credit_hours", 0.0) or 0.0)
        whole = max(0, int(credit + 1e-9))
        if whole < 1:
            raise ValueError("insufficient formation standing training credit")
        training = self.read("game/data/mechanics/training.json")
        session_rules = self.read(_SESSION_RULES_PATH)
        capability_before = self._formation_capability_snapshot(formation_ref)
        recovery = self._standing_recovery(
            formation,
            fatigue=int(formation.get("fatigue", 0) or 0),
            current=current,
            completed_hours=float(whole),
            training=training,
            session_rules=session_rules,
        )
        formation["fatigue"] = int(recovery["fatigue_after"])
        if formation.get("training_progress") is None:
            formation["training_progress"] = 0
        if formation.get("verified_training_hours") is None:
            formation["verified_training_hours"] = 0
        formation["training_progress"] = _clamp(
            int(formation.get("training_progress", 0)) + max(1, whole // 4)
        )
        formation["cohesion"] = _clamp(
            int(formation.get("cohesion", 50)) + max(1, whole // 4)
        )
        formation["readiness"] = _clamp(
            int(formation.get("readiness", 50)) + max(0, whole // 6)
        )
        formation["verified_training_hours"] = int(formation.get("verified_training_hours", 0)) + whole
        formation["last_training_at"] = str(current)
        formation["last_training"] = {"completed_at": str(current), "hours": whole}
        formation["standing_training_recovery_through"] = str(current)
        self.put(path, formation)
        if hasattr(self, "_ct_train_formation"):
            self._ct_train_formation(
                formation_ref,
                float(whole),
                f"standing_training_settle:{request_id}:{formation_ref}",
            )
        capability_after = self._formation_capability_snapshot(formation_ref)
        settled = deepcopy(self.read(path))
        remainder = max(0.0, credit - whole)
        settled["standing_training_time_credit_hours"] = round(remainder, 6)
        settled["standing_training_last_settled_at"] = str(current)
        settled["standing_training_recovery_through"] = str(current)
        if remainder <= 1e-9:
            settled.pop("standing_training_credit_window_start", None)
            settled.pop("standing_training_credit_window_end", None)
            settled.pop("standing_training_recovery_through", None)
        self.put(path, settled)
        return {
            "target_ref": formation_ref,
            "consumed_hours": whole,
            "remaining_credit_hours": round(remainder, 6),
            "training_progress": int(settled.get("training_progress", 0)),
            "cohesion": int(settled.get("cohesion", 0)),
            "readiness": int(settled.get("readiness", 0)),
            "fatigue": int(settled.get("fatigue", 0)),
            "recovery": recovery,
            "capability_development": self._capability_development_delta(
                capability_before,
                capability_after,
            ),
        }

    def _command_layer_standing_training(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        if command.command_type != "standing_training_settle":
            return next_dispatch()
        current_text = str(self.read(_RUNTIME_PATH)["world_time"])
        current = CampaignTime.parse(current_text)
        target_ref = str(payload["target_ref"])
        if target_ref == self.PLAYER_ACTOR:
            result = self._consume_player_standing_credit(current, command.semantic_digest[:24])
        else:
            result = self._consume_formation_standing_credit(
                target_ref,
                current,
                command.semantic_digest[:24],
            )
        self._write_meta(command, current_text)
        return self._result(
            world_time=current_text,
            elapsed_seconds=0,
            standing_training=result,
        )


__all__ = ["StandingTrainingSettlementMixin"]
