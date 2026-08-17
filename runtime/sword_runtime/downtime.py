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

from sword_runtime.development import settle_skill_training
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_rates import verified_activity_hours_per_cycle

_RUNTIME_PATH = "state/runtime.json"
_EVENT_PATH = "state/event/events-messages-and-movement.json"
_PROFILES_PATH = "game/data/mil/recruitment-cohort-profiles.json"
_PLAYER_FACING_EVENT_KINDS = frozenset(
    {"institutional_response", "petition_response", "message", "audience_response", "world_arc_report"}
)
_ACTIVITY_POLICY_KEYS = frozenset(
    {"player_standing_training", "formation_refs", "household_standing_person_refs"}
)
_WEEK_SECONDS = 7 * 86400


class DowntimeAdvanceMixin:
    """Add bounded player-event waits and concurrent standing training."""

    _downtime_stop_on_player_event = False

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

    def _player_facing_event_refs(self) -> set[str]:
        owner = self.read(_EVENT_PATH)
        causal = owner.get("causal_events") if isinstance(owner, Mapping) else None
        if not isinstance(causal, Mapping):
            return set()
        return {
            str(event_ref)
            for event_ref, event in causal.items()
            if isinstance(event_ref, str)
            and isinstance(event, Mapping)
            and event.get("status") == "triggered"
            and str(event.get("kind", "")) in _PLAYER_FACING_EVENT_KINDS
        }

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

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        if not self._downtime_stop_on_player_event:
            return super()._advance_runtime(target_text)

        target = CampaignTime.parse(target_text)
        total: dict[str, Any] = {
            "hosts_woken": 0,
            "events_processed": 0,
            "battlefield_reports": [],
            "battlefield_reviews": 0,
        }
        for _ in range(4096):
            current = CampaignTime.parse(str(self.read(_RUNTIME_PATH)["world_time"]))
            if current >= target:
                return total
            step = self._next_scheduler_boundary(current, target)
            before = self._player_facing_event_refs()
            metrics = super()._advance_runtime(str(step))
            self._merge_time_metrics(total, metrics)
            actual = CampaignTime.parse(str(self.read(_RUNTIME_PATH)["world_time"]))
            if metrics.get("interrupted"):
                total.update(
                    {
                        key: value
                        for key, value in metrics.items()
                        if key not in {"hosts_woken", "events_processed", "battlefield_reports", "battlefield_reviews"}
                    }
                )
                return total
            new_refs = sorted(self._player_facing_event_refs() - before)
            if new_refs:
                total.update(
                    {
                        "interrupted": True,
                        "wake_required": False,
                        "interrupt_reason": "player_facing_event",
                        "player_facing_event_boundary": True,
                        "player_facing_event_refs": new_refs,
                    }
                )
                return total
            if actual >= target:
                return total
            if actual < step:
                raise ValueError("downtime scheduler failed to reach its selected boundary")
        raise ValueError("event-bounded downtime exceeded the causal boundary limit")

    @staticmethod
    def _focuses(person: Mapping[str, Any], contract: Mapping[str, Any]) -> list[str]:
        value = contract.get("focus")
        candidates = [part.strip() for part in str(value).split(",")] if isinstance(value, str) else []
        skills = person.get("skills") if isinstance(person.get("skills"), Mapping) else {}
        return [focus for focus in candidates if focus and focus in skills]

    def _settle_player_training(self, start: CampaignTime, end: CampaignTime, request_id: str) -> dict[str, Any]:
        player = deepcopy(self.read("state/player.json"))
        contract = player.get("activity_contract") if isinstance(player.get("activity_contract"), Mapping) else {}
        weekly = float(contract.get("verified_hours_per_7d", 0.0) or 0.0)
        if weekly <= 0:
            return {"status": "not_configured", "settled_hours": 0}
        focuses = self._focuses(player, contract)
        if not focuses:
            return {"status": "no_trainable_focus", "settled_hours": 0}
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
        cursor = max(0, int(ds.get("standing_training_focus_cursor", 0)))
        results: list[dict[str, Any]] = []
        n = len(focuses)
        for index, focus in enumerate(focuses):
            offset = (index - (cursor % n)) % n
            hours = 0 if offset >= whole else 1 + (whole - 1 - offset) // n
            if hours <= 0:
                continue
            results.append(settle_skill_training(player, focus, hours, end, training))
        ds["standing_training_focus_cursor"] = cursor + whole
        ds["standing_training_last_settled_at"] = str(end)
        history = player.setdefault("training_history", [])
        history.append(
            {
                "started_at": str(start),
                "completed_at": str(end),
                "mode": "standing_downtime",
                "hours": whole,
                "request_id": request_id,
                "development": results,
            }
        )
        player["training_history"] = history[-64:]
        self.put("state/player.json", player)
        return {
            "status": "settled",
            "settled_hours": whole,
            "credit_hours": ds["standing_training_time_credit_hours"],
            "focus_results": results,
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
            if str(force.get("owner_id")) in {"force_house_tang", "institution_sword_manor"}
            else "regular_army"
        )
        regimen = profiles.get("training_regimens", {}).get(regimen_name, {})
        weekly = float(regimen.get("deliberate_hours_per_7d", 0.0) or 0.0)
        elapsed = max(0, start.seconds_until(end))
        credit = float(formation.get("standing_training_time_credit_hours", 0.0)) + weekly * elapsed / _WEEK_SECONDS
        whole = max(0, int(credit))
        formation["standing_training_time_credit_hours"] = round(credit - whole, 6)
        if whole <= 0:
            formation["standing_training_last_accrued_at"] = str(end)
            self.put(path, formation)
            return {
                "formation_ref": formation_ref,
                "status": "accrued",
                "settled_hours": 0,
                "credit_hours": formation["standing_training_time_credit_hours"],
            }

        formation["training_progress"] = min(100, int(formation.get("training_progress", 0)) + max(1, whole // 4))
        formation["cohesion"] = min(100, int(formation.get("cohesion", 50)) + max(1, whole // 4))
        formation["readiness"] = min(100, int(formation.get("readiness", 50)) + max(0, whole // 6))
        formation["fatigue"] = min(100, int(formation.get("fatigue", 0)) + max(1, whole // 5))
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
        history = settled.setdefault("standing_training_history", [])
        history.append(
            {
                "started_at": str(start),
                "completed_at": str(end),
                "hours": whole,
                "request_id": request_id,
            }
        )
        settled["standing_training_history"] = history[-32:]
        self.put(path, settled)
        return {
            "formation_ref": formation_ref,
            "status": "settled",
            "settled_hours": whole,
            "credit_hours": settled["standing_training_time_credit_hours"],
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
            "request_id": request_id,
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

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type != "advance_time":
            return super()._dispatch(command, payload)
        policy = self._policy(payload)
        start = CampaignTime.parse(str(self.read(_RUNTIME_PATH)["world_time"]))
        previous = self._downtime_stop_on_player_event
        self._downtime_stop_on_player_event = bool(payload.get("stop_on_player_event", False))
        try:
            result = super()._dispatch(command, payload)
        finally:
            self._downtime_stop_on_player_event = previous
        end = CampaignTime.parse(str(self.read(_RUNTIME_PATH)["world_time"]))
        if policy and end >= start:
            updated = dict(result)
            updated["downtime_activity"] = self._settle_downtime_policy(
                start,
                end,
                policy,
                str(command.request_id),
            )
            return updated
        return result


__all__ = ["DowntimeAdvanceMixin"]
