"""Routed offscreen named-person development for production living-world play.

Named people retain their annual person hosts for mortality, family, and other
life-course settlement. Routine standing activity uses one bounded recurring
scheduler host over an explicit routed-person list. The router discovers only
exact people already represented by the scheduler's person-host registry; it
never scans character directories and never gives the player autonomous training.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.campaign_event_planner import CampaignEventPlayerGroupActionPlanner
from sword_runtime.development import settle_skill_training
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_ACTIVITY_ROUTING_VERSION = 1
_ACTIVITY_HOST_ID = "host_named_person_activity"
_ACTIVITY_EVENT_ID = "event_host_named_person_activity_review"
_ACTIVITY_CADENCE_SECONDS = 30 * 86400
_ACTIVITY_VERIFIED_HOURS = 48
_ACTIVITY_HISTORY_LIMIT = 24
_ACTIVITY_FATIGUE_BLOCK = 80
_MAX_ROUTED_PEOPLE = 4096
_ELIGIBLE_HEALTH = frozenset({"healthy", "fit", "stable"})


class ActivityCampaignEventPlanner(CampaignEventPlayerGroupActionPlanner):
    """Production planner with bounded exact-person standing-activity catch-up."""

    @staticmethod
    def _activity_focuses(person: Mapping[str, Any], contract: Mapping[str, Any]) -> list[str]:
        value = contract.get("focus")
        if isinstance(value, str):
            candidates = [part.strip() for part in value.split(",")]
        elif isinstance(value, list):
            candidates = [str(part).strip() for part in value]
        else:
            candidates = []
        skills = person.get("skills")
        if not isinstance(skills, Mapping):
            return []
        seen: set[str] = set()
        focuses: list[str] = []
        for focus in candidates:
            if focus and focus in skills and focus not in seen:
                seen.add(focus)
                focuses.append(focus)
        return focuses

    def _ensure_activity_routes(self) -> None:
        """Register newly scheduler-known standing-activity people exactly once.

        The scheduler host registry is already the bounded causal routing surface.
        We inspect only unclassified person hosts, then remember the classification
        on that exact host. This makes future materialized people discoverable
        without repeatedly loading every named-person document.
        """
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        if len(hosts) > 100_000:
            raise ValueError("runtime causal host registry exceeds bounded routing limit")

        now_text = str(runtime.get("world_time"))
        now = CampaignTime.parse(now_text)
        newly_routed: list[str] = []
        classified = 0

        for host_id, host in sorted(hosts.items()):
            if not isinstance(host_id, str) or not isinstance(host, dict) or host.get("kind") != "person":
                continue
            route_state = host.get("activity_route")
            if isinstance(route_state, Mapping) and int(route_state.get("version", 0)) >= _ACTIVITY_ROUTING_VERSION:
                continue
            person_ref = host.get("owner_ref")
            if not isinstance(person_ref, str):
                raise ValueError("person causal host lost exact owner_ref")
            classified += 1
            status = "inactive"
            if person_ref != self.PLAYER_ACTOR:
                try:
                    person_path, person = self._exact_person(person_ref, active=False)
                except ValueError:
                    person = None
                if isinstance(person, dict):
                    contract = person.get("activity_contract")
                    if (
                        isinstance(contract, Mapping)
                        and contract.get("autonomous_enabled") is not False
                        and self._activity_focuses(person, contract)
                    ):
                        activity = person.setdefault("autonomous_activity_state", {})
                        if not isinstance(activity, dict):
                            raise ValueError("exact person autonomous_activity_state is invalid")
                        activity.setdefault("version", _ACTIVITY_ROUTING_VERSION)
                        activity.setdefault("enabled", True)
                        activity.setdefault("routed_at", now_text)
                        activity.setdefault("cadence_seconds", _ACTIVITY_CADENCE_SECONDS)
                        activity.setdefault("verified_hours_per_cycle", _ACTIVITY_VERIFIED_HOURS)
                        activity.setdefault("focus_cursor", 0)
                        activity.setdefault("next_due", str(now.add_seconds(_ACTIVITY_CADENCE_SECONDS)))
                        activity.setdefault(
                            "verification_rule",
                            "fixed structured causal cycles verify routine standing activity prospectively; planned_opportunity prose is capacity context only and is never converted into training hours",
                        )
                        self.put(person_path, person)
                        newly_routed.append(person_ref)
                        status = "routed"
            host["activity_route"] = {
                "version": _ACTIVITY_ROUTING_VERSION,
                "status": status,
                "classified_at": now_text,
            }

        activity_host = hosts.get(_ACTIVITY_HOST_ID)
        if newly_routed and activity_host is None:
            first_due = now.add_seconds(_ACTIVITY_CADENCE_SECONDS)
            activity_host = {
                "kind": "person_activity",
                "owner_ref": "runtime_named_person_activity",
                "next_due": str(first_due),
                "recurrence_seconds": _ACTIVITY_CADENCE_SECONDS,
                "resolved_through": now_text,
                "safe_through": str(first_due.add_seconds(-1)),
                "routed_person_refs": [],
            }
            hosts[_ACTIVITY_HOST_ID] = activity_host
            events.append({
                "due_at": str(first_due),
                "event_id": _ACTIVITY_EVENT_ID,
                "kind": "person_activity_review",
                "priority": 96,
                "target_host": _ACTIVITY_HOST_ID,
            })
        if activity_host is not None:
            if not isinstance(activity_host, dict):
                raise ValueError("named-person activity host is invalid")
            refs = activity_host.setdefault("routed_person_refs", [])
            if not isinstance(refs, list):
                raise ValueError("named-person activity route list is invalid")
            for person_ref in newly_routed:
                if person_ref not in refs:
                    refs.append(person_ref)
            refs[:] = sorted(set(str(ref) for ref in refs if isinstance(ref, str)))
            if len(refs) > _MAX_ROUTED_PEOPLE:
                raise ValueError("named-person activity routing exceeds bounded exact-person limit")

        routing = runtime.setdefault("person_activity_routing", {})
        if not isinstance(routing, dict):
            raise ValueError("person_activity_routing is invalid")
        routing.update({
            "version": _ACTIVITY_ROUTING_VERSION,
            "last_route_scan_at": now_text,
            "routed_count": len(activity_host.get("routed_person_refs", [])) if isinstance(activity_host, dict) else 0,
            "rule": "only scheduler-known exact people with explicit standing activity contracts are routed; no character-directory scan and no player autonomous training",
        })
        metrics = runtime.setdefault("metrics", {})
        if newly_routed:
            metrics["person_activity_route_registrations"] = int(metrics.get("person_activity_route_registrations", 0)) + len(newly_routed)
        metrics["person_activity_route_classifications"] = int(metrics.get("person_activity_route_classifications", 0)) + classified
        self.put(_RUNTIME_PATH, runtime)

    @staticmethod
    def _activity_skip_reason(person: Mapping[str, Any], contract: Mapping[str, Any]) -> str | None:
        life = str(person.get("life_status", person.get("status", "active"))).lower()
        if life in {"dead", "deceased"}:
            return "dead"
        if contract.get("autonomous_enabled") is False:
            return "contract_disabled"
        custody = person.get("custody_state")
        if isinstance(custody, Mapping) and str(custody.get("status", "")).lower() == "captured":
            return "captured"
        health = str(person.get("health", person.get("health_status", "healthy"))).lower()
        if health not in _ELIGIBLE_HEALTH:
            return "health_unavailable"
        try:
            fatigue = int(person.get("fatigue", 0))
        except (TypeError, ValueError):
            fatigue = 0
        if fatigue >= _ACTIVITY_FATIGUE_BLOCK:
            return "fatigue_unavailable"
        return None

    def _settle_activity_host(self, host: Mapping[str, Any], due_text: str) -> None:
        refs = host.get("routed_person_refs")
        if not isinstance(refs, list):
            raise ValueError("named-person activity host lost routed_person_refs")
        if len(refs) > _MAX_ROUTED_PEOPLE:
            raise ValueError("named-person activity routing exceeds bounded exact-person limit")
        due = CampaignTime.parse(due_text)
        training = self.read("game/data/mechanics/training.json")
        for person_ref in refs:
            if not isinstance(person_ref, str) or person_ref == self.PLAYER_ACTOR:
                continue
            try:
                person_path, person = self._exact_person(person_ref, active=False)
            except ValueError:
                continue
            contract = person.get("activity_contract")
            if not isinstance(contract, Mapping):
                continue
            focuses = self._activity_focuses(person, contract)
            if not focuses:
                continue
            activity = person.setdefault("autonomous_activity_state", {})
            if not isinstance(activity, dict):
                raise ValueError("exact person autonomous_activity_state is invalid")
            next_due_text = activity.get("next_due")
            if not isinstance(next_due_text, str):
                routed_at = CampaignTime.parse(str(activity.get("routed_at", due_text)))
                next_due = routed_at.add_seconds(_ACTIVITY_CADENCE_SECONDS)
            else:
                next_due = CampaignTime.parse(next_due_text)
            cursor = max(0, int(activity.get("focus_cursor", 0)))
            processed = 0
            changed = False
            while next_due <= due:
                processed += 1
                if processed > 64:
                    raise ValueError("named-person activity catch-up exceeds bounded per-review cycle limit")
                focus = focuses[cursor % len(focuses)]
                cursor += 1
                reason = self._activity_skip_reason(person, contract)
                cycle_at = str(next_due)
                if reason is None:
                    development = settle_skill_training(person, focus, _ACTIVITY_VERIFIED_HOURS, next_due, training)
                    person.setdefault("autonomous_development_history", []).append({
                        "at": cycle_at,
                        "focus": focus,
                        "hours": _ACTIVITY_VERIFIED_HOURS,
                        "development": development,
                        "verification_basis": "structured_causal_activity_cycle_v1",
                        "planned_opportunity_hours_used": False,
                    })
                    person["autonomous_development_history"] = person["autonomous_development_history"][-_ACTIVITY_HISTORY_LIMIT:]
                    activity["completed_cycles"] = int(activity.get("completed_cycles", 0)) + 1
                    activity["last_completed_at"] = cycle_at
                    activity.pop("last_skip_reason", None)
                else:
                    activity["skipped_cycles"] = int(activity.get("skipped_cycles", 0)) + 1
                    activity["last_skip_reason"] = reason
                    activity["last_skipped_at"] = cycle_at
                    if reason == "dead":
                        activity["enabled"] = False
                activity["reviewed_cycles"] = int(activity.get("reviewed_cycles", 0)) + 1
                activity["last_cycle_at"] = cycle_at
                next_due = next_due.add_seconds(_ACTIVITY_CADENCE_SECONDS)
                changed = True
                if reason == "dead":
                    break
            if changed:
                activity.update({
                    "version": _ACTIVITY_ROUTING_VERSION,
                    "cadence_seconds": _ACTIVITY_CADENCE_SECONDS,
                    "verified_hours_per_cycle": _ACTIVITY_VERIFIED_HOURS,
                    "focus_cursor": cursor,
                    "next_due": str(next_due),
                    "resolved_through": due_text,
                })
                self.put(person_path, person)

    def _autonomy_person(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Keep base life-course logic but suppress its legacy annual training shortcut."""
        person_ref = str(host.get("owner_ref", ""))
        if not person_ref or person_ref == self.PLAYER_ACTOR:
            super()._autonomy_person(host, occurrences, at)
            return
        try:
            person_path, person = self._exact_person(person_ref, active=False)
        except ValueError:
            super()._autonomy_person(host, occurrences, at)
            return
        contract = person.get("activity_contract")
        if not isinstance(contract, Mapping):
            super()._autonomy_person(host, occurrences, at)
            return
        original_contract = copy.deepcopy(contract)
        guarded = copy.deepcopy(person)
        guarded_contract = guarded.setdefault("activity_contract", {})
        existing_rule = str(guarded_contract.get("growth_rule", "")).strip()
        guard_rule = "not automatic progress; routed standing activity owns routine development"
        guarded_contract["growth_rule"] = f"{existing_rule}; {guard_rule}" if existing_rule else guard_rule
        self.put(person_path, guarded)
        super()._autonomy_person(host, occurrences, at)
        after = copy.deepcopy(self.read(person_path))
        after["activity_contract"] = original_contract
        self.put(person_path, after)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == "person_activity":
            self._settle_activity_host(host, due_text)
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        self._ensure_activity_routes()
        return super()._advance_runtime(target_text)


__all__ = ["ActivityCampaignEventPlanner"]
