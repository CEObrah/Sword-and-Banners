"""Chronology-owned subsistence for Tang Wei-controlled persistent formations.

Travel already consumes the exact food/fodder needed for its movement interval.
This lifecycle fills the missing stationary-time side: one daily scheduler host
consumes registered rations for persistent formations under Tang Wei's command
or House Tang ownership. Carried stores are used first. Only a formation's
existing material-depot authority may cover a shortfall, and only when that
depot is physically co-located; stock is never minted or pulled remotely.

Some player commands load a formation before advancing chronology and write it
again afterwards. To keep scheduler writes from being overwritten by those
command-local copies, the host defers settlement for such command targets and
applies the owed interval after the command finishes. Strategic movement is
separately marked as already covered because those commands consume their own
route-time rations explicitly.
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
_PLAYER_REF = "char_tang_wei"
_TANG_FORCE_REFS = frozenset({"force_house_tang", "force_tang_wei_personal", "force_sword_manor"})
_TANG_ADMIN_REFS = frozenset({"house_tang", "char_tang_wei"})
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


def _managed_formation(planner: Any, formation: Mapping[str, Any]) -> bool:
    if max(0, int(formation.get("personnel", 0))) <= 0:
        return False
    if str(formation.get("status", "")).lower() in {"destroyed", "dissolved", "disbanded"}:
        return False
    player_ref = str(getattr(planner, "PLAYER_ACTOR", _PLAYER_REF))
    return (
        str(formation.get("command_authority", "")) == player_ref
        or str(formation.get("administrative_owner", "")) in _TANG_ADMIN_REFS
        or str(formation.get("owner_force_ref", "")) in _TANG_FORCE_REFS
    )


def _formation_refs(planner: Any) -> list[str]:
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


def _interval_seconds(formation: Mapping[str, Any], due_text: str) -> int:
    due = CampaignTime.parse(due_text)
    start = due.add_seconds(-_CADENCE_SECONDS)
    created_text = formation.get("created_at")
    if isinstance(created_text, str):
        try:
            created = CampaignTime.parse(created_text)
        except ValueError:
            created = None
        if created is not None and created > start:
            start = created
    if start >= due:
        return 0
    return max(0, min(_CADENCE_SECONDS, int(start.seconds_until(due))))


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


def _consume_one(planner: Any, formation_ref: str, *, seconds: int, at: str) -> dict[str, Any] | None:
    if seconds <= 0:
        return None
    path = planner.owner_path(formation_ref)
    formation = copy.deepcopy(planner.read(path))
    if not isinstance(formation, Mapping) or not _managed_formation(planner, formation):
        return None
    formation = dict(formation)
    policy = _policy(planner)
    personnel = max(0, int(formation.get("personnel", 0)))
    mounts = sum(max(0, int(value)) for value in (formation.get("mounts", {}) or {}).values())
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


def settle_player_formation_subsistence(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any]:
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
        if not isinstance(formation, Mapping) or not _managed_formation(planner, formation):
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
            "owner_ref": "runtime_player_formation_subsistence",
            "recurrence_seconds": _CADENCE_SECONDS,
            "resolved_through": now_text,
            "next_due": str(due),
            "safe_through": str(due.add_seconds(-1)),
        }
        hosts[_HOST_ID] = host
    elif not isinstance(host, dict) or str(host.get("kind", "")) != _HOST_KIND:
        raise ValueError("player formation subsistence host is invalid")

    matching = [row for row in events if isinstance(row, Mapping) and row.get("target_host") == _HOST_ID]
    if len(matching) > 1:
        raise ValueError("player formation subsistence host has duplicate events")
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
            raise ValueError("player formation subsistence event is invalid")
        event["event_id"] = _EVENT_ID
        event["kind"] = _HOST_KIND
        event["priority"] = _PRIORITY
        event["due_at"] = str(host["next_due"])
        event.pop("suspended", None)


class FormationSubsistenceFlowMixin:
    """Add automatic daily subsistence to hosted Tang Wei military chronology."""

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
        self._subsistence_deferred_refs = set(refs)
        self._subsistence_explicit_covered_refs = set(refs) if command.command_type in _MOVEMENT_COMMANDS else set()
        self._subsistence_deferred_seconds = {}
        try:
            result = super()._dispatch(command, payload)
            reached = str(self.read(_RUNTIME_PATH).get("world_time"))
            for formation_ref, seconds in sorted(self._subsistence_deferred_seconds.items()):
                if formation_ref in self._subsistence_explicit_covered_refs:
                    continue
                _consume_one(self, formation_ref, seconds=int(seconds), at=reached)
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
