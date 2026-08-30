"""House Tang family field-preparation response lifecycle.

Tang Wei may ask his parents to prepare his personal forces for campaign service,
report exact House reserves and supply capacity, and decide an age-appropriate
training disposition for Tang Kai. This module turns that request into durable
House work while keeping stock reports, procurement capacity and actual equipment
issue distinct.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_INVENTORY_PATH = "state/inv/inventories.json"
_DEPOT_PATH = "state/depots/house-tang.json"
_MOUNT_POOL_PATH = "state/mounts/house-tang.json"
_PLAYER_FORCE_PATH = "state/pforce/wei.json"
_KAI_PATH = "state/char/tang-kai.json"
_HISTORY_WINDOW = 512
_PRIORITY = 46
_PARENTS = frozenset({"char_tang_ling", "char_tang_zhu"})
_FIELD_TERMS = (
    "kai", "house guard", "champion", "armor", "armour", "horse armor",
    "equipment", "supply", "prepare", "manufactur", "campaign", "battlefield",
)



def _current_house_field_rows(planner: Any) -> list[tuple[str, Mapping[str, Any]]]:
    pforce = planner.read(_PLAYER_FORCE_PATH)
    refs = pforce.get("assigned_formations", []) if isinstance(pforce, Mapping) else []
    rows: list[tuple[str, Mapping[str, Any]]] = []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, str):
            continue
        try:
            _path, formation = planner._load_formation(ref)
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if str(formation.get("administrative_owner", "")) == "house_tang":
            rows.append((ref, formation))
    return sorted(rows, key=lambda item: item[0])

def _event_owner_write(planner: Any, event_ref: str, row: Mapping[str, Any], at: str) -> str:
    existing = get_causal_event(planner, event_ref)
    if isinstance(existing, Mapping):
        return event_ref
    payload = copy.deepcopy(dict(row))
    payload["provenance"] = {
        "kind": "causal_runtime_settlement",
        "source_owner_ref": "house_tang",
        "work_ref": event_ref,
        "late_catch_up": False,
    }
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = payload
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return event_ref


def _field_prep_ids(attempt_ref: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(f"house-field-preparation|{attempt_ref}".encode("utf-8")).hexdigest()[:20]
    return (
        f"host_house_field_preparation_{digest}",
        f"event_house_field_preparation_due_{digest}",
        f"event_house_field_preparation_{digest}",
    )


def _is_field_preparation_attempt(attempt: Mapping[str, Any]) -> bool:
    if attempt.get("actor_id") != "char_tang_wei" or attempt.get("action") not in {"ask", "request", "report"}:
        return False
    if str(attempt.get("target_ref", "")) not in _PARENTS:
        return False
    statement = str(attempt.get("player_statement", "")).lower()
    return sum(1 for term in _FIELD_TERMS if term in statement) >= 2


def sync_house_field_preparation(planner: Any, runtime: dict[str, Any]) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    now = CampaignTime.parse(str(runtime["world_time"]))
    attempts, _ = recent_interaction_attempts(planner, "char_tang_wei", limit=_HISTORY_WINDOW)
    for attempt in reversed(attempts):
        if not _is_field_preparation_attempt(attempt):
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


def _inventory_facts(inventory: Mapping[str, Any], record_id: str) -> Mapping[str, Any]:
    for row in inventory.get("records", []):
        if isinstance(row, Mapping) and row.get("record_id") == record_id:
            facts = row.get("facts")
            return facts if isinstance(facts, Mapping) else {}
    return {}


def _kai_age(kai: Mapping[str, Any], at: str) -> int:
    birth = str(kai.get("birth_date", ""))
    if "-BCE-" not in birth:
        return 0
    year_text, rest = birth.split("-BCE-", 1)
    parts = rest.split("-")
    current = CampaignTime.parse(at)
    birth_year = int(year_text)
    age = birth_year - current.bce_year
    birth_month = int(parts[0])
    birth_day = int(parts[1])
    if (current.month, current.day) < (birth_month, birth_day):
        age -= 1
    return max(0, age)


def settle_house_field_preparation(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    response_ref = str(host.get("response_event_ref", ""))
    if not response_ref or isinstance(get_causal_event(planner, response_ref), Mapping):
        return None

    inventory = planner.read(_INVENTORY_PATH)
    outfitting = _inventory_facts(inventory, "house_tang_outfitting_sets")
    depot = planner.read(_DEPOT_PATH)
    depot_stocks = depot.get("stocks", {}) if isinstance(depot, Mapping) else {}
    mount_pool = planner.read(_MOUNT_POOL_PATH)
    regional_mounts = mount_pool.get("regional_reserve", {}) if isinstance(mount_pool, Mapping) else {}
    depot_mounts = regional_mounts.get("loc_tang_manor_garrison_yard", {}) if isinstance(regional_mounts, Mapping) else {}
    treasury = planner.read(_TREASURY_PATH)
    house_rows = _current_house_field_rows(planner)
    if not house_rows:
        raise ValueError("Tang Wei has no current House-owned assigned field formations")
    house_count = sum(int(row.get("personnel", 0) or 0) for _ref, row in house_rows)
    house_arrows = sum(int(row.get("logistics", {}).get("war_arrows", 0) or 0) for _ref, row in house_rows if isinstance(row.get("logistics"), Mapping))
    house_refs = [ref for ref, _row in house_rows]

    kai = copy.deepcopy(planner.read(_KAI_PATH))
    age = _kai_age(kai, at)
    orders = kai.setdefault("goal_state", {}).setdefault("current_orders", [])
    home_order = (
        "Remain at Tang Manor under verified age-appropriate household training: language, memory, arithmetic, supervised play, riding familiarity, route observation, and safe Inner Walls observation. No live weapons, battle-contact drill, adult workload, or independent command training before saved age eligibility."
    )
    if home_order not in orders:
        orders.append(home_order)
    kai["goal_state"]["current_orders"] = orders[-16:]
    kai.setdefault("development_state", {})["current_training_disposition"] = "tang_manor_age_appropriate_verified_training"
    kai["development_state"]["training_disposition_set_at"] = at
    planner.put(_KAI_PATH, kai)

    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    programs = house.setdefault("administrative_programs", {})
    prep = programs.setdefault("wei_field_preparation", {})
    prep.update({
        "status": "staging_and_shortfall_review",
        "requested_at": at,
        "attempt_ref": str(host.get("attempt_ref", "")),
        "principal_ref": "char_tang_wei",
        "army_ref": "cmdgrp.tang_wei.field_army",
        "house_formation_refs": house_refs,
        "equipment_issue_status": "not_yet_issued_or_reserved_by_this_report",
    })
    planner.put(_HOUSE_PATH, house)

    summary = (
        f"Tang Ling and Tang Zhu answer Tang Wei's campaign-preparation request. They keep Tang Kai at Tang Manor for now: he is {age}, and his saved training contract permits rigorous age-appropriate learning, riding familiarity, route and camp observation, and safe Inner Walls exposure, but forbids live weapons, battle-contact drill and adult workload; protected battlefield service is not eligible until age 10. His home training order is now persisted and remains subject to the normal verified development clocks. "
        f"For Wei's current House contingent, the saved assignments contain {house_count} fighters across {len(house_refs)} formations. The unissued armory holds {int(outfitting.get('standard_role_sets_reserve', 0))} complete standard role-outfitting sets, {int(outfitting.get('crossbow_role_sets_reserve', 0))} crossbow-role sets and {int(outfitting.get('mounted_harness_sets_reserve', 0))} mounted harness sets. The protected strategic depot holds {int(depot_stocks.get('war_arrows', 0))} war arrows and {int(depot_mounts.get('horse', 0))} reserve horses. "
        f"Those House field formations currently hold {house_arrows} war arrows in total. Ordinary army ration and animal-feed inventories are not tracked; field support is derived from the campaign's current routes, territory and regional food condition. "
        "The parents order a field-preparation and shortfall review opened for Wei's departure. No monthly item factory is assumed: future replacement sets and repairs require real labor, material, silver and time, while ammunition and living mounts remain separate exact stock."
    )[:4000]

    _event_owner_write(planner, response_ref, {
        "event_ref": response_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "char_tang_ling",
        "target_ref": "char_tang_wei",
        "basis_goal": "Prepare Tang Wei's personal forces and household support for Qin field service without inventing stock, manufacturing or child training",
        "process_kind": "house_field_preparation",
        "process_stage": "staging_and_shortfall_review",
        "summary": summary,
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": str(planner.read("state/player.json").get("location", "")),
            "route": "House Tang family and quartermaster report",
        },
    }, at)
    digest = hashlib.sha256(f"{response_ref}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.house.field_preparation.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": response_ref,
        "reason": summary,
    }


class HouseFieldPreparationFlowMixin:
    """Route family campaign-preparation requests into an exact House response."""

    # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = ["HouseFieldPreparationFlowMixin", "settle_house_field_preparation", "sync_house_field_preparation"]
