"""Routed offscreen named-person development for production living-world play.

Named people retain their annual person hosts for mortality, family, and other
life-course settlement. Routine standing activity uses bounded recurring scheduler shards over explicit
routed-person lists so campaign scale never becomes a lifetime person ceiling. The router discovers only
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
from sword_runtime.training_rates import verified_activity_hours_per_cycle

_RUNTIME_PATH = "state/runtime.json"
_PROFILES_PATH = "game/data/mil/recruitment-cohort-profiles.json"
_ACTIVITY_ROUTING_VERSION = 2
_ACTIVITY_HOST_ID = "host_named_person_activity"
_ACTIVITY_EVENT_ID = "event_host_named_person_activity_review"
_ACTIVITY_CADENCE_SECONDS = 30 * 86400
_ACTIVITY_DEFAULT_VERIFIED_HOURS = 48
_ACTIVITY_HISTORY_LIMIT = 24
_ACTIVITY_FATIGUE_BLOCK = 80
_ACTIVITY_SHARD_SIZE = 512
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

    @staticmethod
    def _activity_shard_ids(index: int) -> tuple[str, str]:
        if index <= 0:
            return _ACTIVITY_HOST_ID, _ACTIVITY_EVENT_ID
        suffix = f"{index + 1:04d}"
        return f"{_ACTIVITY_HOST_ID}_{suffix}", f"{_ACTIVITY_EVENT_ID}_{suffix}"

    @classmethod
    def _activity_hosts(cls, hosts: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        rows: list[tuple[str, dict[str, Any]]] = []
        for host_id, host in hosts.items():
            if not isinstance(host_id, str) or not isinstance(host, dict):
                continue
            if host.get("kind") != "person_activity":
                continue
            if host_id != _ACTIVITY_HOST_ID and not host_id.startswith(_ACTIVITY_HOST_ID + "_"):
                continue
            rows.append((host_id, host))
        def key(row: tuple[str, dict[str, Any]]) -> tuple[int, str]:
            host_id = row[0]
            if host_id == _ACTIVITY_HOST_ID:
                return (0, host_id)
            tail = host_id.rsplit("_", 1)[-1]
            return (int(tail) if tail.isdigit() else 10**9, host_id)
        return sorted(rows, key=key)

    @classmethod
    def _ensure_activity_shard(
        cls,
        hosts: dict[str, Any],
        events: list[Any],
        *,
        index: int,
        now: CampaignTime,
        now_text: str,
    ) -> dict[str, Any]:
        host_id, event_id = cls._activity_shard_ids(index)
        host = hosts.get(host_id)
        if host is None:
            first_due = now.add_seconds(_ACTIVITY_CADENCE_SECONDS)
            host = {
                "kind": "person_activity",
                "owner_ref": "runtime_named_person_activity",
                "route_shard": index,
                "next_due": str(first_due),
                "recurrence_seconds": _ACTIVITY_CADENCE_SECONDS,
                "resolved_through": now_text,
                "safe_through": str(first_due.add_seconds(-1)),
                "routed_person_refs": [],
            }
            hosts[host_id] = host
            events.append({
                "due_at": str(first_due),
                "event_id": event_id,
                "kind": "person_activity_review",
                "priority": 96,
                "target_host": host_id,
            })
        if not isinstance(host, dict) or host.get("kind") != "person_activity":
            raise ValueError("named-person activity host is invalid")
        refs = host.setdefault("routed_person_refs", [])
        if not isinstance(refs, list):
            raise ValueError("named-person activity route list is invalid")
        if len(refs) > _ACTIVITY_SHARD_SIZE:
            raise ValueError("named-person activity shard exceeds its routing page size")
        return host

    def _ensure_activity_routes(self) -> None:
        """Register newly scheduler-known standing-activity people exactly once.

        The scheduler host registry is already the causal routing surface. Exact
        people are classified only from their existing person hosts. Activity
        routes are paged across deterministic scheduler shards instead of failing
        after a lifetime total of routed people.
        """
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")

        now_text = str(runtime.get("world_time"))
        now = CampaignTime.parse(now_text)
        profiles = self.read(_PROFILES_PATH)
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
                    focuses = self._activity_focuses(person, contract) if isinstance(contract, Mapping) else []
                    if (
                        isinstance(contract, Mapping)
                        and contract.get("autonomous_enabled") is not False
                        and focuses
                    ):
                        activity = person.setdefault("autonomous_activity_state", {})
                        if not isinstance(activity, dict):
                            raise ValueError("exact person autonomous_activity_state is invalid")
                        cadence = max(1, int(activity.get("cadence_seconds", _ACTIVITY_CADENCE_SECONDS)))
                        cycle_hours = verified_activity_hours_per_cycle(
                            person,
                            contract,
                            profiles,
                            cadence,
                            fallback_hours=_ACTIVITY_DEFAULT_VERIFIED_HOURS,
                        )
                        if cycle_hours > 0:
                            activity["version"] = _ACTIVITY_ROUTING_VERSION
                            activity.setdefault("enabled", True)
                            activity.setdefault("routed_at", now_text)
                            activity["cadence_seconds"] = cadence
                            activity["verified_hours_per_cycle"] = round(cycle_hours, 6)
                            activity.setdefault("focus_cursor", 0)
                            activity.setdefault("next_due", str(now.add_seconds(cadence)))
                            activity[
                                "verification_rule"
                            ] = "structured causal cycles derive standard House Tang adult hours from the canonical training regimen; planned_opportunity prose is capacity context only and is never converted into training hours"
                            self.put(person_path, person)
                            newly_routed.append(person_ref)
                            status = "routed"
            host["activity_route"] = {
                "version": _ACTIVITY_ROUTING_VERSION,
                "status": status,
                "classified_at": now_text,
            }

        shards = self._activity_hosts(hosts)
        existing_refs: set[str] = set()
        for _host_id, shard in shards:
            refs = shard.get("routed_person_refs")
            if not isinstance(refs, list):
                raise ValueError("named-person activity route list is invalid")
            if len(refs) > _ACTIVITY_SHARD_SIZE:
                raise ValueError("named-person activity shard exceeds its routing page size")
            existing_refs.update(str(ref) for ref in refs if isinstance(ref, str))

        for person_ref in sorted(set(newly_routed)):
            if person_ref in existing_refs:
                continue
            shards = self._activity_hosts(hosts)
            shard_index = 0
            if shards:
                last_id, last = shards[-1]
                refs = last.get("routed_person_refs", [])
                if len(refs) < _ACTIVITY_SHARD_SIZE:
                    target = last
                else:
                    shard_index = len(shards)
                    target = self._ensure_activity_shard(hosts, events, index=shard_index, now=now, now_text=now_text)
            else:
                target = self._ensure_activity_shard(hosts, events, index=0, now=now, now_text=now_text)
            refs = target.setdefault("routed_person_refs", [])
            refs.append(person_ref)
            refs[:] = sorted(set(str(ref) for ref in refs if isinstance(ref, str)))
            existing_refs.add(person_ref)

        shards = self._activity_hosts(hosts)
        routed_count = sum(len(shard.get("routed_person_refs", [])) for _host_id, shard in shards)
        routing = runtime.setdefault("person_activity_routing", {})
        if not isinstance(routing, dict):
            raise ValueError("person_activity_routing is invalid")
        routing.update({
            "version": _ACTIVITY_ROUTING_VERSION,
            "last_route_scan_at": now_text,
            "routed_count": routed_count,
            "route_shards": len(shards),
            "shard_size": _ACTIVITY_SHARD_SIZE,
            "rule": "only scheduler-known exact people with explicit eligible standing activity contracts are routed; House Tang adult standing-role rates derive from the canonical max-sustainable regimen; child household development is excluded from adult skill settlement; no character-directory scan and no player autonomous training",
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
        if len(refs) > _ACTIVITY_SHARD_SIZE:
            raise ValueError("named-person activity shard exceeds its routing page size")
        due = CampaignTime.parse(due_text)
        training = self.read("game/data/mechanics/training.json")
        profiles = self.read(_PROFILES_PATH)
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
            cadence = max(1, int(activity.get("cadence_seconds", _ACTIVITY_CADENCE_SECONDS)))
            cycle_hours = verified_activity_hours_per_cycle(
                person,
                contract,
                profiles,
                cadence,
                fallback_hours=_ACTIVITY_DEFAULT_VERIFIED_HOURS,
            )
            if cycle_hours <= 0:
                activity["version"] = _ACTIVITY_ROUTING_VERSION
                activity["verified_hours_per_cycle"] = 0.0
                activity["resolved_through"] = due_text
                self.put(person_path, person)
                continue
            settlement_hours = max(1, int(cycle_hours))
            next_due_text = activity.get("next_due")
            if not isinstance(next_due_text, str):
                routed_at = CampaignTime.parse(str(activity.get("routed_at", due_text)))
                next_due = routed_at.add_seconds(cadence)
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
                    development = settle_skill_training(person, focus, settlement_hours, next_due, training)
                    person.setdefault("autonomous_development_history", []).append({
                        "at": cycle_at,
                        "focus": focus,
                        "hours": settlement_hours,
                        "development": development,
                        "verification_basis": "structured_causal_activity_cycle_v2",
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
                next_due = next_due.add_seconds(cadence)
                changed = True
                if reason == "dead":
                    break
            if changed:
                activity.update({
                    "version": _ACTIVITY_ROUTING_VERSION,
                    "cadence_seconds": cadence,
                    "verified_hours_per_cycle": round(cycle_hours, 6),
                    "focus_cursor": cursor,
                    "next_due": str(next_due),
                    "resolved_through": due_text,
                })
                self.put(person_path, person)

    def _autonomy_person(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Keep base life-course logic while suppressing duplicate annual training settlement."""
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
