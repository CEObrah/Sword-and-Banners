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

from sword_runtime.development import settle_skill_training
from sword_runtime.engine import _clamp
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
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

    def _consume_player_standing_credit(self, current: CampaignTime, request_id: str) -> dict[str, Any]:
        player = deepcopy(self.read("state/player.json"))
        ds = player.setdefault("development_state", {})
        credit = float(ds.get("standing_training_time_credit_hours", 0.0) or 0.0)
        whole = max(0, int(credit + 1e-9))
        if whole < 1:
            raise ValueError("insufficient standing training credit")
        contract = player.get("activity_contract") if isinstance(player.get("activity_contract"), Mapping) else {}
        focuses = self._focuses(player, contract)
        if not focuses:
            raise ValueError("standing training plan has no trainable focus")
        training = self.read("game/data/mechanics/training.json")
        cursor = max(0, int(ds.get("standing_training_focus_cursor", 0)))
        results: list[dict[str, Any]] = []
        count = len(focuses)
        for index, focus in enumerate(focuses):
            offset = (index - (cursor % count)) % count
            hours = 0 if offset >= whole else 1 + (whole - 1 - offset) // count
            if hours <= 0:
                continue
            results.append(settle_skill_training(player, focus, hours, current, training))
        remainder = max(0.0, credit - whole)
        ds = player.setdefault("development_state", {})
        ds["standing_training_time_credit_hours"] = round(remainder, 6)
        ds["standing_training_focus_cursor"] = cursor + whole
        ds["standing_training_last_settled_at"] = str(current)
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
            }
        )
        player["training_history"] = history[-64:]
        if remainder <= 1e-9:
            ds.pop("standing_training_credit_window_start", None)
            ds.pop("standing_training_credit_window_end", None)
        self.put("state/player.json", player)
        return {
            "target_ref": self.PLAYER_ACTOR,
            "consumed_hours": whole,
            "remaining_credit_hours": round(remainder, 6),
            "focus_results": results,
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
        formation["fatigue"] = _clamp(
            int(formation.get("fatigue", 0)) + max(1, whole // 5)
        )
        formation["verified_training_hours"] = int(formation.get("verified_training_hours", 0)) + whole
        formation["last_training_at"] = str(current)
        self.put(path, formation)
        if hasattr(self, "_ct_train_formation"):
            self._ct_train_formation(
                formation_ref,
                float(whole),
                f"standing_training_settle:{request_id}:{formation_ref}",
            )
        settled = deepcopy(self.read(path))
        remainder = max(0.0, credit - whole)
        settled["standing_training_time_credit_hours"] = round(remainder, 6)
        settled["standing_training_last_settled_at"] = str(current)
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
            },
            32,
        )
        if remainder <= 1e-9:
            settled.pop("standing_training_credit_window_start", None)
            settled.pop("standing_training_credit_window_end", None)
        self.put(path, settled)
        return {
            "target_ref": formation_ref,
            "consumed_hours": whole,
            "remaining_credit_hours": round(remainder, 6),
            "training_progress": int(settled.get("training_progress", 0)),
            "cohesion": int(settled.get("cohesion", 0)),
            "readiness": int(settled.get("readiness", 0)),
            "fatigue": int(settled.get("fatigue", 0)),
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
