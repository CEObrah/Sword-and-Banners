"""Narrow House field-preparation routing to explicit current campaign requests.

The first field-preparation matcher was too broad: any old family interaction that
mentioned two military-preparation terms could be retroactively promoted into a
new House response. This gate replaces only that scanner while preserving the
settlement callback and all already-persisted House consequences.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.house_field_preparation_flow import (
    HouseFieldPreparationFlowMixin,
    _PARENTS,
    _PRIORITY,
    _RUNTIME_PATH,
    _field_prep_ids,
)
from sword_runtime.sim.calendar import CampaignTime

_HISTORY_WINDOW = 128


def _is_explicit_field_preparation_attempt(attempt: Mapping[str, Any]) -> bool:
    if attempt.get("actor_id") != "char_tang_wei" or attempt.get("action") not in {"ask", "request", "report"}:
        return False
    if str(attempt.get("target_ref", "")) not in _PARENTS:
        return False
    statement = str(attempt.get("player_statement", "")).lower()
    has_kai = "kai" in statement
    has_guard = "house guard" in statement or "guard contingent" in statement
    has_champions = "champion" in statement
    has_all_personal_forces = any(
        phrase in statement
        for phrase in (
            "all my troops",
            "all of my troops",
            "my troops",
            "all my forces",
            "all of my forces",
            "personal force",
            "personal forces",
        )
    )
    has_formation_scope = (has_guard and has_champions) or has_all_personal_forces
    has_equipment = any(
        term in statement
        for term in (
            "equipment",
            "armor",
            "armour",
            "weapons",
            "bows",
            "shields",
            "tack",
            "arrows",
        )
    )
    has_preparation = any(
        term in statement
        for term in (
            "prepare",
            "preparation",
            "campaign",
            "battlefield",
            "field service",
            "departure",
            "going to war",
        )
    )
    return all((has_kai, has_formation_scope, has_equipment, has_preparation))


def sync_explicit_house_field_preparation(planner: Any, runtime: dict[str, Any]) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    now = CampaignTime.parse(str(runtime["world_time"]))
    attempts, _ = recent_interaction_attempts(planner, "char_tang_wei", limit=_HISTORY_WINDOW)
    for attempt in reversed(attempts):
        if not _is_explicit_field_preparation_attempt(attempt):
            continue
        attempt_ref = interaction_attempt_ref(attempt)
        host_id, scheduler_event_id, response_ref = _field_prep_ids(attempt_ref)
        if isinstance(get_causal_event(planner, response_ref), Mapping) or host_id in hosts:
            continue
        requested_at = attempt.get("at")
        if not isinstance(requested_at, str):
            continue
        due_raw = CampaignTime.parse(requested_at).add_seconds(3600)
        due = due_raw if due_raw > now else now
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "house_field_preparation_reply",
            "owner_ref": "house_tang",
            "attempt_ref": attempt_ref,
            "response_event_ref": response_ref,
            "request_parent_ref": str(attempt.get("target_ref", "")),
            "player_statement": str(attempt.get("player_statement", ""))[:2000],
            "recurrence_seconds": 0,
            "next_due": str(due),
            "resolved_through": str(now if now < due else due.add_seconds(-1)),
            "safe_through": str(due.add_seconds(-1)),
        }
        events.append({
            "event_id": scheduler_event_id,
            "kind": "house_field_preparation_reply",
            "priority": _PRIORITY,
            "target_host": host_id,
            "due_at": str(due),
        })
        return


class ExplicitHouseFieldPreparationFlowMixin(HouseFieldPreparationFlowMixin):
    """Use the strict scanner while retaining the existing settlement callback."""


__all__ = [
    "ExplicitHouseFieldPreparationFlowMixin",
    "sync_explicit_house_field_preparation",
]
