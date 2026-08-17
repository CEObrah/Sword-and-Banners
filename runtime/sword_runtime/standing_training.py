"""Standing-training credit accrual and zero-time settlement.

Time advancement owns chronology. This module owns only the reconciliation of
training time that has already been earned during an explicit downtime window.
It never accepts caller-supplied hours or focuses: Tang Wei's saved standing plan
and a controlled formation's registered regimen determine accrual, while this
semantic command consumes only server-owned whole-hour credit.

Exact autonomous NPCs remain outside player training authority. House Tang people
named in a downtime activity policy accrue evidence under their own saved activity
contracts through the existing downtime helper; this module never settles their
skills from a player command.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sword_runtime.cohort_personnel import ensure_formation_composition
from sword_runtime.engine import _clamp
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_session import settle_training_session, standing_recovery_result
from sword_runtime.smart_training import contract_skill_candidates, select_exact_focus

_RUNTIME_PATH = "state/runtime.json"
_SESSION_RULES_PATH = "game/data/mechanics/training-session.json"
_WEEK_SECONDS = 7 * 86400


class StandingTrainingSettlementMixin:
    """Accrue downtime credits, then consume them without advancing time."""

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
    # Downtime accrual only
    # ------------------------------------------------------------------

    @staticmethod
    def _append_bounded(rows: list[Any], row: Mapping[str, Any], limit: int) -> None:
        rows.append(dict(row))
        del rows[:-limit]

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
        before = float(ds.get("standing_training_time_credit_hours", 0.0) or 0.0)
        after = before + accrued
        ds["standing_training_time_credit_hours"] = round(after, 6)
        if before <= 1e-9:
            ds["standing_training_credit_window_start"] = str(start)
            ds.pop("standing_training_recovery_through", None)
        ds["standing_training_credit_window_end"] = str(end)
        history = ds.setdefault("standing_training_accrual_history", [])
        if not isinstance(history, list):
            raise ValueError("standing training accrual history is invalid")
        self._append_bounded(
            history,
            {
                "started_at": str(start),
                "completed_at": str(end),
                "elapsed_seconds": elapsed,
                "rate_hours_per_7d": weekly,
                "accrued_hours": round(accrued, 6),
                "request_id": request_id,
            },
            32,
        )
        self.put("state/player.json", player)
        return {
            "status": "accrued",
            "accrued_hours": round(accrued, 6),
            "credit_hours": round(after, 6),
        }

    def _formation_weekly_training_rate(self, formation: Mapping[str, Any]) -> float:
        force_path = self.owner_path(str(formation["owner_force_ref"]))
        force = self.read(force_path)
        profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
        regimen_name = (
            "house_tang_max_sustainable"
            if str(force.get("owner_id")) in {"force_house_tang", "institution_sword_manor"}
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
        before = float(formation.get("standing_training_time_credit_hours", 0.0) or 0.0)
        after = before + accrued
        formation["standing_training_time_credit_hours"] = round(after, 6)
        if before <= 1e-9:
            formation["standing_training_credit_window_start"] = str(start)
            formation.pop("standing_training_recovery_through", None)
        formation["standing_training_credit_window_end"] = str(end)
        history = formation.setdefault("standing_training_accrual_history", [])
        if not isinstance(history, list):
            raise ValueError("formation standing training accrual history is invalid")
        self._append_bounded(
            history,
            {
                "started_at": str(start),
                "completed_at": str(end),
                "elapsed_seconds": elapsed,
                "rate_hours_per_7d": weekly,
                "accrued_hours": round(accrued, 6),
                "request_id": request_id,
            },
            32,
        )
        self.put(path, formation)
        return {
            "formation_ref": formation_ref,
            "status": "accrued",
            "accrued_hours": round(accrued, 6),
            "credit_hours": round(after, 6),
        }

    def _settle_downtime_policy(
        self,
        start: CampaignTime,
        end: CampaignTime,
        policy: Mapping[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        """Override the older eager settlement with credit-only accrual.

        This keeps time advancement robust and makes training reconciliation a
        separate zero-time semantic write. The player's declared downtime intent
        is still preserved because the caller can immediately settle the returned
        server-owned credits after the event boundary is committed.
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
            formations.append(
                self._accrue_formation_standing_credit(str(formation_ref), start, end, request_id)
            )
        if formations:
            result["formations"] = formations
        people: list[dict[str, Any]] = []
        for person_ref in policy.get("household_standing_person_refs", []):
            people.append(
                self._accrue_household_person_activity(str(person_ref), start, end, request_id)
            )
        if people:
            result["household_people"] = people
        result["settlement_rule"] = "credits_only_during_time_advance"
        return result

    # ------------------------------------------------------------------
    # Zero-time credit consumption
    # ------------------------------------------------------------------

    @staticmethod
    def _credit_window_start(owner: Mapping[str, Any], current_text: str) -> str:
        value = owner.get("standing_training_credit_window_start")
        if isinstance(value, str) and value:
            return value
        provenance = owner.get("standing_training_repair_provenance")
        if isinstance(provenance, Mapping):
            interval_start = provenance.get("interval_start")
            if isinstance(interval_start, str) and interval_start:
                return interval_start
        return current_text

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
            training.get("time_budget", {}).get("deliberate_training_hours_per_7d_normal_max", 56.0) or 0.0
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
        focuses = contract_skill_candidates(player, contract)
        if not focuses:
            raise ValueError("standing training plan has no trainable focus")
        training = self.read("game/data/mechanics/training.json")
        session_rules = self.read(_SESSION_RULES_PATH)
        recovery = self._standing_recovery(
            ds,
            fatigue=int(player.get("fatigue", 0) or 0),
            current=current,
            completed_hours=float(whole),
            training=training,
            session_rules=session_rules,
        )
        player["fatigue"] = int(recovery["fatigue_after"])
        cursor = max(0, int(ds.get("standing_training_focus_cursor", 0)))
        results: list[dict[str, Any]] = []
        # Spend each settlement window across the weakest useful slice of the
        # standing plan. Re-ranking on the next window naturally shifts attention
        # once a lagging skill catches up.
        selected: list[str] = []
        probe_cursor = cursor
        for _ in range(min(6, len(focuses))):
            focus = select_exact_focus(player, contract, probe_cursor)
            probe_cursor += 1
            if focus and focus not in selected:
                selected.append(focus)
        if not selected:
            selected = focuses[:1]
        count = len(selected)
        for index, focus in enumerate(selected):
            hours = whole // count + (1 if index < (whole % count) else 0)
            if hours <= 0:
                continue
            results.append(settle_training_session(player, focus, hours, current, training, session_rules))
        remainder = max(0.0, credit - whole)
        ds = player.setdefault("development_state", {})
        ds["standing_training_time_credit_hours"] = round(remainder, 6)
        ds["standing_training_focus_cursor"] = cursor + whole
        ds["standing_training_last_settled_at"] = str(current)
        ds["standing_training_recovery_through"] = str(current)
        started_at = self._credit_window_start(ds, str(current))
        history = player.setdefault("training_history", [])
        if not isinstance(history, list):
            raise ValueError("player training history is invalid")
        history.append(
            {
                "started_at": started_at,
                "completed_at": str(current),
                "mode": "standing_downtime",
                "hours": whole,
                "request_id": request_id,
                "development": results,
                "recovery": recovery,
            }
        )
        player["training_history"] = history[-64:]
        if remainder <= 1e-9:
            ds.pop("standing_training_credit_window_start", None)
            ds.pop("standing_training_credit_window_end", None)
            ds.pop("standing_training_recovery_through", None)
        self.put("state/player.json", player)
        return {
            "target_ref": self.PLAYER_ACTOR,
            "consumed_hours": whole,
            "remaining_credit_hours": round(remainder, 6),
            "fatigue": int(player.get("fatigue", 0)),
            "recovery": recovery,
            "focus_results": results,
        }

    def _formation_capability_snapshot(self, formation_ref: str) -> dict[str, Any]:
        """Project trained cohort means and banked EDU for one controlled formation."""

        _path, raw = self._load_formation(formation_ref)
        formation = deepcopy(raw)
        force_path = self.owner_path(str(formation["owner_force_ref"]))
        force = deepcopy(self.read(force_path))
        if hasattr(self, "_seed_force_baselines"):
            self._seed_force_baselines(force)
        ensure_formation_composition(force, formation)

        ledger = force.get("cohort_ledger", {})
        cohorts = ledger.get("cohorts", {}) if isinstance(ledger, Mapping) else {}
        profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
        role_profiles = profiles.get("role_training_profiles", {}) if isinstance(profiles, Mapping) else {}
        if not isinstance(role_profiles, Mapping):
            role_profiles = {}

        represented = 0
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
            represented += count
            verified_training_total += float(cohort.get("verified_training_hours_per_person", 0.0) or 0.0) * count
            verified_training_count += count
            role = str(cohort.get("role") or next(iter(formation.get("composition", {})), "line_infantry"))
            focus = role_profiles.get(role, {}) if isinstance(role_profiles, Mapping) else {}
            skill_names = [str(x) for x in focus.get("skills", [])] if isinstance(focus, Mapping) else []
            attribute_names = [str(x) for x in focus.get("attributes", [])] if isinstance(focus, Mapping) else []
            for mean_key, bank_key, names in (
                ("attribute_means", "attribute_edu_banks", attribute_names),
                ("skill_means", "skill_edu_banks", skill_names),
            ):
                means = cohort.get(mean_key, {}) if isinstance(cohort.get(mean_key), Mapping) else {}
                banks = cohort.get(bank_key, {}) if isinstance(cohort.get(bank_key), Mapping) else {}
                for name in names:
                    if name in means:
                        sums[mean_key][name] = sums[mean_key].get(name, 0.0) + float(means[name]) * count
                        counts[mean_key][name] = counts[mean_key].get(name, 0) + count
                    if name in banks:
                        sums[bank_key][name] = sums[bank_key].get(name, 0.0) + float(banks[name]) * count
                        counts[bank_key][name] = counts[bank_key].get(name, 0) + count

        def averaged(key: str) -> dict[str, float]:
            return {
                name: round(total / counts[key][name], 3)
                for name, total in sorted(sums[key].items())
                if counts[key].get(name, 0) > 0
            }

        return {
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
        started_at = self._credit_window_start(settled, str(current))
        history = settled.setdefault("standing_training_history", [])
        if not isinstance(history, list):
            raise ValueError("formation standing training history is invalid")
        self._append_bounded(
            history,
            {
                "started_at": started_at,
                "completed_at": str(current),
                "hours": whole,
                "request_id": request_id,
                "recovery": recovery,
            },
            32,
        )
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

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type != "standing_training_settle":
            return super()._dispatch(command, payload)
        current_text = str(self.read(_RUNTIME_PATH)["world_time"])
        current = CampaignTime.parse(current_text)
        target_ref = str(payload["target_ref"])
        if target_ref == self.PLAYER_ACTOR:
            result = self._consume_player_standing_credit(current, str(command.request_id))
        else:
            result = self._consume_formation_standing_credit(
                target_ref,
                current,
                str(command.request_id),
            )
        self._write_meta(command, current_text)
        return self._result(
            world_time=current_text,
            elapsed_seconds=0,
            standing_training=result,
        )


__all__ = ["StandingTrainingSettlementMixin"]
