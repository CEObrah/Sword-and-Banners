"""Chronology-owned subsistence for authoritative persistent formations.

Every canonical persistent formation is a material consumer regardless of whether
its current owner or commander is the player, a House, or a state. Temporary
operation/battle arrangements are never fed separately because they do not own
manpower.

Ordinary elapsed chronology consumes the registered food/fodder rates. Carried
stores are used first. Only a formation's existing material-depot authority may
cover a shortfall, and only when that depot is physically co-located; stock is
never minted or pulled remotely.

Travel and formation movement already consume exact route-time rations. The
subsistence clock therefore settles any stationary gap up to departure, defers
scheduler writes while the movement command owns stale formation copies, then
marks the reached time as explicitly covered. The next scheduler settlement
starts from that exact arrival time instead of charging the movement interval a
second time.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_OWNER_INDEX_PATH = "state/index/owner-index.json"
_RULES_PATH = "game/data/mechanics/logistics.json"
_HOST_ID = "host_player_formation_subsistence"
_EVENT_ID = "event_player_formation_subsistence_daily"
_HOST_KIND = "player_formation_subsistence"
_CADENCE_SECONDS = 24 * 3600
_PRIORITY = 20
_MOVEMENT_COMMANDS = frozenset({"travel", "formation_move"})
_FORMATION_PAYLOAD_KEYS = (
    "formation_ref",
    "formation_refs",
    "escort_formation_refs",
    "attacker_formation_refs",
    "defender_formation_refs",
    "garrison_formation_refs",
)


def _policy(planner: Any) -> Mapping[str, Any]:
    rules = planner.read(_RULES_PATH)
    policy = rules.get("military_field_supply_policy") if isinstance(rules, Mapping) else None
    if not isinstance(policy, Mapping):
        raise ValueError("military field supply policy is missing")
    food = policy.get("food_kg_per_person_day")
    fodder = policy.get("fodder_kg_per_mount_day")
    if (
        isinstance(food, bool)
        or not isinstance(food, (int, float))
        or float(food) <= 0
        or isinstance(fodder, bool)
        or not isinstance(fodder, (int, float))
        or float(fodder) < 0
    ):
        raise ValueError("military field supply policy has invalid subsistence rates")
    return policy


def _eligible_persistent_formation(formation: Mapping[str, Any]) -> bool:
    """Return whether one canonical formation is a live material consumer."""
    if bool(formation.get("temporary", False)):
        return False
    if max(0, int(formation.get("personnel", 0))) <= 0:
        return False
    if str(formation.get("status", "")).lower() in {"destroyed", "dissolved", "disbanded"}:
        return False
    return True


def _formation_refs(planner: Any) -> list[str]:
    """Enumerate canonical persistent formations, never operation arrangements."""
    index = planner.read(_OWNER_INDEX_PATH)
    owners = index.get("owners") if isinstance(index, Mapping) else None
    if not isinstance(owners, Mapping):
        raise ValueError("owner index is invalid")
    refs: list[str] = []
    for ref, route in owners.items():
        if (
            isinstance(ref, str)
            and ref.startswith("formation_")
            and isinstance(route, str)
            and route.split("#", 1)[0].startswith("state/formations/")
        ):
            refs.append(ref)
    return sorted(set(refs))


def _command_formation_refs(payload: Mapping[str, Any]) -> set[str]:
    refs: set[str] = set()
    for key in _FORMATION_PAYLOAD_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("formation_"):
            refs.add(value)
        elif isinstance(value, list):
            refs.update(
                str(item)
                for item in value
                if isinstance(item, str) and item.startswith("formation_")
            )
    return refs


def _parse_optional_time(value: Any) -> CampaignTime | None:
    if not isinstance(value, str):
        return None
    try:
        return CampaignTime.parse(value)
    except ValueError:
        return None


def _unsettled_seconds(
    formation: Mapping[str, Any],
    end_text: str,
    *,
    fallback_start_text: str,
    maximum_seconds: int | None = None,
) -> int:
    """Return exact elapsed seconds not yet covered by formation subsistence."""
    end = CampaignTime.parse(end_text)
    start = CampaignTime.parse(fallback_start_text)

    subsistence = formation.get("subsistence")
    if isinstance(subsistence, Mapping):
        settled = _parse_optional_time(subsistence.get("last_settled_at"))
        if settled is not None and settled > start:
            start = settled

    created = _parse_optional_time(formation.get("created_at"))
    if created is not None and created > start:
        start = created

    if start >= end:
        return 0
    seconds = max(0, int(start.seconds_until(end)))
    if maximum_seconds is not None:
        seconds = min(maximum_seconds, seconds)
    return seconds


def _interval_seconds(formation: Mapping[str, Any], due_text: str) -> int:
    due = CampaignTime.parse(due_text)
    fallback = str(due.add_seconds(-_CADENCE_SECONDS))
    return _unsettled_seconds(
        formation,
        due_text,
        fallback_start_text=fallback,
        maximum_seconds=_CADENCE_SECONDS,
    )


def _co_located_material_depot(planner: Any, formation: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    try:
        path, raw = planner._material_depot(formation)
    except (FileNotFoundError, KeyError, ValueError):
        return None
    if not isinstance(path, str) or not isinstance(raw, Mapping):
        return None
    depot = copy.deepcopy(dict(raw))
    if str(depot.get("location_ref", "")) != str(formation.get("location_ref", "")):
        return None
    stocks = depot.get("stocks")
    if not isinstance(stocks, dict):
        return None
    return path, depot


def _mount_count(formation: Mapping[str, Any]) -> int:
    mounts = formation.get("mounts", {})
    if isinstance(mounts, Mapping):
        return sum(max(0, int(value)) for value in mounts.values())
    if isinstance(mounts, bool):
        return 0
    if isinstance(mounts, (int, float)):
        return max(0, int(mounts))
    return 0


def _consume_one(planner: Any, formation_ref: str, *, seconds: int, at: str) -> dict[str, Any] | None:
    if seconds <= 0:
        return None
    path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(path))
    if not isinstance(formation, Mapping) or not _eligible_persistent_formation(formation):
        return None
    formation = dict(formation)
    policy = _policy(planner)
    personnel = max(0, int(formation.get("personnel", 0)))
    mounts = _mount_count(formation)
    days = float(seconds) / 86400.0
    food_need = max(0, int(math.ceil(personnel * float(policy["food_kg_per_person_day"]) * days)))
    fodder_need = max(0, int(math.ceil(mounts * float(policy["fodder_kg_per_mount_day"]) * days)))

    logistics = formation.setdefault("logistics", {})
    if not isinstance(logistics, dict):
        raise ValueError(f"formation logistics are invalid: {formation_ref}")
    carried_food = min(food_need, max(0, int(logistics.get("food_kg", 0))))
    carried_fodder = min(fodder_need, max(0, int(logistics.get("fodder_kg", 0))))
    logistics["food_kg"] = max(0, int(logistics.get("food_kg", 0)) - carried_food)
    logistics["fodder_kg"] = max(0, int(logistics.get("fodder_kg", 0)) - carried_fodder)
    food_short = food_need - carried_food
    fodder_short = fodder_need - carried_fodder

    depot_food = 0
    depot_fodder = 0
    depot_ref: str | None = None
    depot_info = _co_located_material_depot(planner, formation) if food_short or fodder_short else None
    if depot_info is not None:
        depot_path, depot = depot_info
        stocks = depot["stocks"]
        available_food = max(0, int(stocks.get("grain_kg", 0)))
        available_fodder = max(0, int(stocks.get("fodder_kg", 0)))
        depot_food = min(food_short, available_food)
        depot_fodder = min(fodder_short, available_fodder)
        stocks["grain_kg"] = available_food - depot_food
        stocks["fodder_kg"] = available_fodder - depot_fodder
        food_short -= depot_food
        fodder_short -= depot_fodder
        if depot_food or depot_fodder:
            depot_ref = str(depot.get("owner_id", depot_path))
            planner.put(depot_path, depot)

    subsistence = formation.setdefault("subsistence", {})
    if not isinstance(subsistence, dict):
        raise ValueError(f"formation subsistence state is invalid: {formation_ref}")
    subsistence.update({
        "last_settled_at": at,
        "last_interval_seconds": int(seconds),
        "food_required_kg": food_need,
        "food_from_carried_kg": carried_food,
        "food_from_depot_kg": depot_food,
        "food_shortfall_kg": max(0, food_short),
        "fodder_required_kg": fodder_need,
        "fodder_from_carried_kg": carried_fodder,
        "fodder_from_depot_kg": depot_fodder,
        "fodder_shortfall_kg": max(0, fodder_short),
        "source_depot_ref": depot_ref,
        "status": "shortage" if food_short or fodder_short else "sustained",
    })
    planner.put(path, formation)
    return {
        "formation_ref": formation_ref,
        "seconds": int(seconds),
        "food_required_kg": food_need,
        "food_shortfall_kg": max(0, food_short),
        "fodder_required_kg": fodder_need,
        "fodder_shortfall_kg": max(0, fodder_short),
    }


def _mark_explicitly_covered(planner: Any, formation_ref: str, *, at: str, seconds: int) -> None:
    """Advance the clock without consuming again; movement already paid the interval."""
    path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(path))
    if not isinstance(formation, Mapping) or not _eligible_persistent_formation(formation):
        return
    formation = dict(formation)
    subsistence = formation.setdefault("subsistence", {})
    if not isinstance(subsistence, dict):
        raise ValueError(f"formation subsistence state is invalid: {formation_ref}")
    subsistence["last_settled_at"] = at
    subsistence["last_explicit_coverage_seconds"] = max(0, int(seconds))
    subsistence["last_explicit_coverage_kind"] = "movement_route_rations"
    planner.put(path, formation)


def settle_player_formation_subsistence(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any]:
    """Settle one scheduler interval for every canonical persistent formation."""
    deferred = set(getattr(planner, "_subsistence_deferred_refs", set()))
    explicitly_covered = set(getattr(planner, "_subsistence_explicit_covered_refs", set()))
    deferred_seconds = getattr(planner, "_subsistence_deferred_seconds", None)
    if not isinstance(deferred_seconds, dict):
        deferred_seconds = {}
        planner._subsistence_deferred_seconds = deferred_seconds

    settled: list[dict[str, Any]] = []
    skipped_covered: list[str] = []
    for formation_ref in _formation_refs(planner):
        path = planner.owner_path(formation_ref)
        formation = planner.read(path)
        if not isinstance(formation, Mapping) or not _eligible_persistent_formation(formation):
            continue
        seconds = _interval_seconds(formation, at)
        if seconds <= 0:
            continue
        if formation_ref in explicitly_covered:
            skipped_covered.append(formation_ref)
            continue
        if formation_ref in deferred:
            deferred_seconds[formation_ref] = int(deferred_seconds.get(formation_ref, 0)) + seconds
            continue
        row = _consume_one(planner, formation_ref, seconds=seconds, at=at)
        if isinstance(row, dict):
            settled.append(row)
    return {
        "settled_count": len(settled),
        "deferred_count": len(deferred_seconds),
        "explicitly_covered_count": len(skipped_covered),
        "food_shortage_count": sum(1 for row in settled if int(row.get("food_shortfall_kg", 0)) > 0),
        "fodder_shortage_count": sum(1 for row in settled if int(row.get("fodder_shortfall_kg", 0)) > 0),
    }


def sync_player_formation_subsistence_host(planner: Any, runtime: dict[str, Any]) -> None:
    """Register the universal persistent-formation ration host once."""
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    now_text = runtime.get("world_time")
    if not isinstance(now_text, str):
        raise ValueError("runtime world_time is invalid")
    now = CampaignTime.parse(now_text)
    host = hosts.get(_HOST_ID)
    if host is None:
        due = now.add_seconds(_CADENCE_SECONDS)
        host = {
            "host_id": _HOST_ID,
            "kind": _HOST_KIND,
            "owner_ref": "runtime_persistent_formation_subsistence",
            "recurrence_seconds": _CADENCE_SECONDS,
            "resolved_through": now_text,
            "next_due": str(due),
            "safe_through": str(due.add_seconds(-1)),
        }
        hosts[_HOST_ID] = host
    elif not isinstance(host, dict) or str(host.get("kind", "")) != _HOST_KIND:
        raise ValueError("formation subsistence host is invalid")

    matching = [row for row in events if isinstance(row, Mapping) and row.get("target_host") == _HOST_ID]
    if len(matching) > 1:
        raise ValueError("formation subsistence host has duplicate events")
    if not matching:
        events.append({
            "event_id": _EVENT_ID,
            "kind": _HOST_KIND,
            "priority": _PRIORITY,
            "target_host": _HOST_ID,
            "due_at": str(host["next_due"]),
        })
    else:
        event = matching[0]
        if not isinstance(event, dict):
            raise ValueError("formation subsistence event is invalid")
        event["event_id"] = _EVENT_ID
        event["kind"] = _HOST_KIND
        event["priority"] = _PRIORITY
        event["due_at"] = str(host["next_due"])
        event.pop("suspended", None)


class FormationSubsistenceFlowMixin:
    """Add automatic subsistence to all persistent military formations."""

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        if getattr(self, "_central_scheduler_reconciliation_active", False):
            return super()._advance_runtime(target_text)
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        sync_player_formation_subsistence_host(self, runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if str(host.get("kind", "")) == _HOST_KIND:
            settle_player_formation_subsistence(self, host, due_text)
            self._pending_wake_created = None
            return
        return super()._run_due_host(host, due_text)

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        previous_deferred = getattr(self, "_subsistence_deferred_refs", set())
        previous_covered = getattr(self, "_subsistence_explicit_covered_refs", set())
        previous_seconds = getattr(self, "_subsistence_deferred_seconds", {})
        refs = _command_formation_refs(payload)
        movement = command.command_type in _MOVEMENT_COMMANDS

        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        sync_player_formation_subsistence_host(self, runtime)
        start_text = str(runtime.get("world_time"))
        host = runtime["hosts"][_HOST_ID]
        fallback_start = str(host.get("resolved_through", start_text))
        self.put(_RUNTIME_PATH, runtime)

        # Settle the partial stationary interval before command-local formation
        # copies are allowed to exist. This makes a later movement interval an
        # exact coverage boundary instead of a whole-day exemption.
        for formation_ref in sorted(refs):
            path = self.owner_path(formation_ref)
            formation = self.read(path)
            if not isinstance(formation, Mapping) or not _eligible_persistent_formation(formation):
                continue
            seconds = _unsettled_seconds(
                formation,
                start_text,
                fallback_start_text=fallback_start,
            )
            if seconds > 0:
                _consume_one(self, formation_ref, seconds=seconds, at=start_text)

        self._subsistence_deferred_refs = set(refs)
        self._subsistence_explicit_covered_refs = set(refs) if movement else set()
        self._subsistence_deferred_seconds = {}
        try:
            result = super()._dispatch(command, payload)
            reached = str(self.read(_RUNTIME_PATH).get("world_time"))
            elapsed = max(
                0,
                int(CampaignTime.parse(start_text).seconds_until(CampaignTime.parse(reached))),
            )
            for formation_ref in sorted(refs):
                if movement:
                    _mark_explicitly_covered(
                        self,
                        formation_ref,
                        at=reached,
                        seconds=elapsed,
                    )
                elif elapsed > 0:
                    _consume_one(
                        self,
                        formation_ref,
                        seconds=elapsed,
                        at=reached,
                    )
            return result
        finally:
            self._subsistence_deferred_refs = previous_deferred
            self._subsistence_explicit_covered_refs = previous_covered
            self._subsistence_deferred_seconds = previous_seconds


__all__ = [
    "FormationSubsistenceFlowMixin",
    "settle_player_formation_subsistence",
    "sync_player_formation_subsistence_host",
]
