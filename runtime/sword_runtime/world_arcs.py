"""Causal world-arc pressure and report propagation.

The existing arc registry remains campaign-scale pressure authority. Active arcs
receive autonomous causal reviews without creating a second plot database or
forcing future historical outcomes. Reviews may establish only abstract arc
initiatives from exact saved actors and their saved goals. Domain consequences
such as formation movement, treasury spending, office changes, injuries, and
territory remain owned by their existing subsystems.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.sim.calendar import CampaignTime

ARC_REGISTRY_PATH = "state/arc/kingdom-arcs.json"
RUNTIME_PATH = "state/runtime.json"
EVENT_OWNER_REF = "events_messages_and_movement"
WORLD_ARC_REVIEW_SECONDS = 48 * 3600
WORLD_ARC_REPORT_RETRY_SECONDS = 12 * 3600
WORLD_ARC_REPORT_MAX_ATTEMPTS = 4
_RECENT_INITIATIVE_REFS = 16
_ALLOWED_DRIVER_PREFIXES = ("char_", "state_", "house_", "faction_", "inst_", "process_")
_SAFE_TEXT = re.compile(r"[^a-z0-9]+")
_EXPLICIT_REF = re.compile(r"\b(?:char|state|house|faction|inst|process)_[a-z0-9_]+\b")


def _slug(value: object) -> str:
    return _SAFE_TEXT.sub(" ", str(value).lower()).strip()


def _active_status(value: object) -> bool:
    return str(value or "").strip().lower().startswith("active")


def _route_ids(arc_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(arc_ref.encode("utf-8")).hexdigest()[:20]
    return f"host_world_arc_{digest}", f"event_world_arc_review_{digest}"


def _report_route_ids(arc_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(("report|" + arc_ref).encode("utf-8")).hexdigest()[:20]
    return f"host_world_arc_report_{digest}", f"event_world_arc_report_{digest}"


def _arc_document(planner: Any) -> dict[str, Any]:
    document = copy.deepcopy(planner.read(ARC_REGISTRY_PATH))
    if not isinstance(document, dict) or document.get("schema") != "arc-registry":
        raise ValueError("world arc registry is invalid")
    if not isinstance(document.get("records"), list):
        raise ValueError("world arc registry records are invalid")
    return document


def _record_index(document: Mapping[str, Any], arc_ref: str) -> tuple[int, dict[str, Any]]:
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError("world arc registry records are invalid")
    for index, raw in enumerate(records):
        if isinstance(raw, dict) and raw.get("record_id") == arc_ref:
            return index, raw
    raise ValueError("world arc host lost its exact arc record")


def _active_arc_refs(document: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for raw in document.get("records", []):
        if not isinstance(raw, Mapping):
            continue
        record_id = raw.get("record_id")
        facts = raw.get("facts")
        if (
            isinstance(record_id, str)
            and record_id.startswith("arc_")
            and isinstance(facts, Mapping)
            and _active_status(facts.get("status"))
        ):
            refs.append(record_id)
    return sorted(set(refs))


def sync_world_arc_routes(planner: Any, runtime: dict[str, Any]) -> None:
    """Register all active arcs on the temporal frontier.

    Active records that existed before this scheduler are caught up at the
    current instant rather than backdated. Dormant/resolved records have their
    prior route suspended. No fixed arc-count ceiling is imposed.
    """
    document = _arc_document(planner)
    active = set(_active_arc_refs(document))
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    current = CampaignTime.parse(str(runtime["world_time"]))
    event_by_id = {
        str(event.get("event_id")): event
        for event in events
        if isinstance(event, dict) and isinstance(event.get("event_id"), str)
    }

    for host in list(hosts.values()):
        if not isinstance(host, dict) or host.get("kind") != "world_arc":
            continue
        arc_ref = host.get("arc_ref")
        if not isinstance(arc_ref, str) or arc_ref in active:
            continue
        host["next_due"] = None
        host["safe_through"] = str(current)
        event = event_by_id.get(str(host.get("event_id")))
        if isinstance(event, dict):
            event["suspended"] = True

    for arc_ref in sorted(active):
        host_id, event_id = _route_ids(arc_ref)
        host = hosts.get(host_id)
        if not isinstance(host, dict):
            host = {
                "host_id": host_id,
                "kind": "world_arc",
                "owner_ref": "kingdom_arcs",
                "arc_ref": arc_ref,
                "event_id": event_id,
                "recurrence_seconds": WORLD_ARC_REVIEW_SECONDS,
                "next_due": str(current),
                "resolved_through": str(current.add_seconds(-1)),
                "safe_through": str(current.add_seconds(-1)),
            }
            hosts[host_id] = host
        elif host.get("next_due") is None:
            host["recurrence_seconds"] = WORLD_ARC_REVIEW_SECONDS
            host["next_due"] = str(current)
            host["safe_through"] = str(current.add_seconds(-1))
        event = event_by_id.get(event_id)
        if not isinstance(event, dict):
            event = {
                "event_id": event_id,
                "kind": "world_arc_review",
                "priority": 70,
                "target_host": host_id,
                "due_at": str(host["next_due"]),
            }
            events.append(event)
            event_by_id[event_id] = event
        else:
            event.update({
                "kind": "world_arc_review",
                "priority": int(event.get("priority", 70)),
                "target_host": host_id,
                "due_at": str(host["next_due"]),
            })
            event.pop("suspended", None)


def _owner_index(planner: Any) -> Mapping[str, str]:
    index = planner.read("state/index/owner-index-gold.json")
    owners = index.get("owners") if isinstance(index, Mapping) else None
    if not isinstance(owners, Mapping):
        raise ValueError("owner index is invalid")
    return {
        str(key): str(value)
        for key, value in owners.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _record_text(record: Mapping[str, Any]) -> str:
    pieces = [str(record.get("record_id", "")), str(record.get("label", ""))]
    facts = record.get("facts")
    if isinstance(facts, Mapping):
        for key in (
            "actors", "owner", "owners", "current_basis", "information_path",
            "visibility_to_tang_wei", "possible_results", "stage", "status",
        ):
            value = facts.get(key)
            if isinstance(value, str):
                pieces.append(value)
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                pieces.extend(str(item) for item in value)
    return " ".join(pieces)


def _resolve_driver_refs(planner: Any, record: Mapping[str, Any]) -> list[str]:
    owners = _owner_index(planner)
    text = _record_text(record)
    normalized = " " + _slug(text) + " "
    resolved: set[str] = set()
    for explicit in _EXPLICIT_REF.findall(text.lower()):
        if explicit in owners:
            resolved.add(explicit)

    candidates = [ref for ref in owners if ref.startswith(_ALLOWED_DRIVER_PREFIXES)]
    candidates.sort(key=lambda ref: (-len(ref), ref))
    for ref in candidates:
        label = ref
        for prefix in _ALLOWED_DRIVER_PREFIXES:
            if label.startswith(prefix):
                label = label[len(prefix):]
                break
        words = _slug(label.replace("_", " "))
        if len(words) >= 3 and f" {words} " in normalized:
            resolved.add(ref)
    return sorted(resolved)


def _owner_record(planner: Any, owner_ref: str) -> Mapping[str, Any] | None:
    try:
        record = planner.read(planner.owner_path(owner_ref))
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None
    return record if isinstance(record, Mapping) else None


def _owner_active(record: Mapping[str, Any]) -> bool:
    life = str(record.get("life_status", record.get("status", "active"))).lower()
    health = str(record.get("health", record.get("health_status", "healthy"))).lower()
    return life not in {"dead", "deceased", "destroyed", "dissolved"} and health != "dead"


def _goal_strings(record: Mapping[str, Any]) -> list[str]:
    goals: list[str] = []
    goal_state = record.get("goal_state")
    if isinstance(goal_state, Mapping):
        for key in ("current_goals", "long_term_goals", "institutional_duties"):
            raw = goal_state.get(key)
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                goals.extend(str(item).strip() for item in raw if isinstance(item, str) and item.strip())
    for key in ("strategic_goals", "goals", "objectives", "priorities", "agenda"):
        raw = record.get(key)
        if isinstance(raw, str) and raw.strip():
            goals.append(raw.strip())
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            goals.extend(str(item).strip() for item in raw if isinstance(item, str) and item.strip())
        elif isinstance(raw, Mapping):
            goals.extend(
                value.strip()
                for value in raw.values()
                if isinstance(value, str) and value.strip()
            )
    return list(dict.fromkeys(goals))


def _capability_score(record: Mapping[str, Any]) -> int:
    skills = record.get("skills")
    if isinstance(skills, Mapping):
        relevant = [
            skills.get(name)
            for name in (
                "Strategy", "Intrigue", "Diplomacy", "Governance",
                "Intelligence Operations", "Leadership", "Logistics",
                "Formation Command", "Mass Combat", "Trade",
            )
        ]
        values = [
            int(value) for value in relevant
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if values:
            return max(10, min(100, int(round(max(values) / 2))))
    admin = record.get("administrative_capacity")
    if isinstance(admin, (int, float)) and not isinstance(admin, bool):
        return max(10, min(100, int(admin)))
    influence = record.get("influence")
    if isinstance(influence, (int, float)) and not isinstance(influence, bool):
        return max(10, min(100, int(influence)))
    return 50


def _actor_state(owner_ref: str, record: Mapping[str, Any]) -> str | None:
    if owner_ref.startswith("state_"):
        return owner_ref.replace("state_", "", 1)
    raw = record.get("state")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower().replace("state_", "")
    return None


def _initial_momentum(record: Mapping[str, Any]) -> int:
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    stage = str(facts.get("stage", "")).lower()
    if any(token in stage for token in ("active_operation", "crisis", "battle", "mobilizing")):
        return 3
    if any(token in stage for token in ("organizing", "advocacy", "intrigue", "developing")):
        return 2
    return 1


def _pressure_stage(momentum: int) -> str:
    if momentum <= 0:
        return "contained"
    if momentum <= 2:
        return "developing"
    if momentum <= 4:
        return "material"
    return "acute"


def _initiative_kind(record: Mapping[str, Any]) -> str:
    text = _slug(_record_text(record))
    if any(token in text for token in ("campaign", "army", "military", "border", "invasion", "operation", "siege")):
        return "strategic_initiative"
    if any(token in text for token in ("succession", "court", "palace", "royal", "faction", "intrigue")):
        return "political_initiative"
    return "world_initiative"


def _visibility(record: Mapping[str, Any]) -> tuple[str, str | None]:
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    status = str(facts.get("status", "")).lower()
    explicit = str(facts.get("visibility_to_tang_wei", "")).lower()
    route = facts.get("information_path")
    route_text = route.strip() if isinstance(route, str) and route.strip() else None
    if "none" in explicit or "hidden" in status:
        return "hidden", route_text
    if any(token in explicit for token in ("direct", "family", "delivered")):
        return "direct", route_text or explicit
    if route_text is not None or any(token in explicit for token in ("public", "rumor", "indirect", "report")):
        return "discoverable", route_text or explicit
    return "hidden", route_text


def _event_owner(planner: Any) -> tuple[str, dict[str, Any]]:
    path = planner.owner_path(EVENT_OWNER_REF)
    owner = copy.deepcopy(planner.read(path))
    if owner.get("schema") != "event-registry" or owner.get("owner_id") != EVENT_OWNER_REF:
        raise ValueError("world arc event routing lost its exact event owner")
    if not isinstance(owner.setdefault("causal_events", {}), dict):
        raise ValueError("world arc event owner causal_events is invalid")
    return path, owner


def _initiative_result(
    planner: Any,
    arc_ref: str,
    at: str,
    review_count: int,
    actor_ref: str,
    actor_score: int,
    target_ref: str | None,
    target_score: int,
) -> tuple[str, int, int]:
    meta = planner.read("state/meta.json")
    seed = (
        f"{meta.get('world_seed')}|{arc_ref}|{at}|{review_count}|"
        f"{actor_ref}|{target_ref or 'none'}"
    )
    roll = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
    chance = max(15, min(85, 50 + (actor_score - target_score) // 4))
    if roll < chance:
        return "gains_ground", 1, roll
    if roll >= min(100, chance + 25):
        return "checked", -1, roll
    return "inconclusive", 0, roll


def _schedule_report_route(
    planner: Any,
    *,
    arc_ref: str,
    source_event_ref: str,
    at: str,
    route: str,
    origin_state: str | None,
    pressure_stage: str,
    visibility: str,
) -> None:
    runtime = copy.deepcopy(planner.read(RUNTIME_PATH))
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = _report_route_ids(arc_ref)
    existing = hosts.get(host_id)
    if isinstance(existing, dict) and existing.get("next_due") is not None:
        return
    due = CampaignTime.parse(at).add_seconds(WORLD_ARC_REPORT_RETRY_SECONDS)
    hosts[host_id] = {
        "host_id": host_id,
        "kind": "world_arc_report",
        "owner_ref": "kingdom_arcs",
        "arc_ref": arc_ref,
        "source_event_ref": source_event_ref,
        "event_id": event_id,
        "route": route,
        "origin_state": origin_state,
        "pressure_stage": pressure_stage,
        "visibility": visibility,
        "attempts": 0,
        "max_attempts": WORLD_ARC_REPORT_MAX_ATTEMPTS,
        "recurrence_seconds": WORLD_ARC_REPORT_RETRY_SECONDS,
        "next_due": str(due),
        "resolved_through": at,
        "safe_through": str(due.add_seconds(-1)),
    }
    found = next(
        (event for event in events if isinstance(event, dict) and event.get("event_id") == event_id),
        None,
    )
    if found is None:
        events.append({
            "event_id": event_id,
            "kind": "world_arc_report",
            "priority": 75,
            "target_host": host_id,
            "due_at": str(due),
        })
    else:
        found.update({
            "kind": "world_arc_report",
            "priority": 75,
            "target_host": host_id,
            "due_at": str(due),
        })
        found.pop("suspended", None)
    planner.put(RUNTIME_PATH, runtime)


def settle_world_arc_review(planner: Any, host: Mapping[str, Any], at: str) -> None:
    """Settle one autonomous review of one exact active arc."""
    arc_ref = host.get("arc_ref")
    if not isinstance(arc_ref, str):
        raise ValueError("world arc host is invalid")
    document = _arc_document(planner)
    index, record = _record_index(document, arc_ref)
    facts = record.get("facts")
    if not isinstance(facts, dict) or not _active_status(facts.get("status")):
        return

    runtime_state = record.setdefault("runtime", {})
    if not isinstance(runtime_state, dict):
        raise ValueError("world arc runtime state is invalid")
    review_count = int(runtime_state.get("review_count", 0)) + 1
    initiative_count = int(runtime_state.get("initiative_count", 0))
    momentum = int(runtime_state.get("pressure_momentum", _initial_momentum(record)))

    driver_refs = _resolve_driver_refs(planner, record)
    drivers: list[tuple[str, Mapping[str, Any], list[str], int]] = []
    for ref in driver_refs:
        owner = _owner_record(planner, ref)
        if owner is None or not _owner_active(owner):
            continue
        goals = _goal_strings(owner)
        if goals:
            drivers.append((ref, owner, goals, _capability_score(owner)))

    event_ref: str | None = None
    if drivers:
        drivers.sort(key=lambda row: row[0])
        selector_seed = f"{arc_ref}|{at}|{review_count}|actor"
        actor_index = int(hashlib.sha256(selector_seed.encode("utf-8")).hexdigest()[:8], 16) % len(drivers)
        actor_ref, actor_owner, actor_goals, actor_score = drivers[actor_index]
        goal_seed = f"{arc_ref}|{at}|{review_count}|{actor_ref}|goal"
        goal_index = int(hashlib.sha256(goal_seed.encode("utf-8")).hexdigest()[:8], 16) % len(actor_goals)
        goal = actor_goals[goal_index]
        opposition = [row for row in drivers if row[0] != actor_ref]
        target_ref: str | None = None
        target_score = 50
        if opposition:
            target_index = int(hashlib.sha256((selector_seed + "|target").encode("utf-8")).hexdigest()[:8], 16) % len(opposition)
            target_ref, _target_owner, _target_goals, target_score = opposition[target_index]

        result, delta, roll = _initiative_result(
            planner, arc_ref, at, review_count, actor_ref, actor_score, target_ref, target_score
        )
        momentum = max(0, min(6, momentum + delta))
        initiative_count += 1
        pressure_stage = _pressure_stage(momentum)
        digest = hashlib.sha256(
            f"{arc_ref}|{review_count}|{at}|{actor_ref}|{target_ref}|{goal}".encode("utf-8")
        ).hexdigest()[:20]
        event_ref = f"event_world_arc_{digest}"
        visibility, route = _visibility(record)
        origin_state = _actor_state(actor_ref, actor_owner)

        owner_path, event_owner = _event_owner(planner)
        causal = event_owner["causal_events"]
        if event_ref not in causal:
            causal[event_ref] = {
                "event_ref": event_ref,
                "kind": "world_arc_activity",
                "status": "triggered",
                "due_at": at,
                "triggered_at": at,
                "arc_ref": arc_ref,
                "actor_ref": actor_ref,
                "target_ref": target_ref,
                "initiative_kind": _initiative_kind(record),
                "basis_goal": goal[:500],
                "result": result,
                "pressure_stage": pressure_stage,
                "visibility_class": visibility,
                "summary": (
                    f"{arc_ref}: {actor_ref} acts toward a saved objective inside the active arc; "
                    f"the bounded initiative resolves as {result}."
                ),
                "provenance": {
                    "kind": "world_arc_causal_review",
                    "arc_owner_ref": "kingdom_arcs",
                    "review_count": review_count,
                    "deterministic_roll": roll,
                },
            }
            event_owner.setdefault("runtime", {})["last_settled_at"] = at
            planner.put(owner_path, event_owner)

        recent = runtime_state.setdefault("recent_initiative_refs", [])
        if not isinstance(recent, list):
            recent = []
            runtime_state["recent_initiative_refs"] = recent
        if event_ref in recent:
            recent.remove(event_ref)
        recent.append(event_ref)
        del recent[:-_RECENT_INITIATIVE_REFS]

        if visibility in {"discoverable", "direct"} and route:
            _schedule_report_route(
                planner,
                arc_ref=arc_ref,
                source_event_ref=event_ref,
                at=at,
                route=route,
                origin_state=origin_state,
                pressure_stage=pressure_stage,
                visibility=visibility,
            )
    else:
        momentum = max(0, momentum - 1)

    runtime_state.update({
        "review_count": review_count,
        "initiative_count": initiative_count,
        "pressure_momentum": momentum,
        "pressure_stage": _pressure_stage(momentum),
        "last_reviewed_at": at,
        "last_initiative_ref": event_ref,
        "driver_refs": driver_refs,
    })
    document["records"][index] = record
    document.setdefault("runtime", {})["last_settled_at"] = at
    planner.put(ARC_REGISTRY_PATH, document)


def _location_record(planner: Any, location_ref: str) -> Mapping[str, Any] | None:
    if location_ref.startswith("loc_tang_manor_"):
        return {
            "ref": location_ref,
            "state": "qin",
            "kind": "estate",
            "functions": ["politics", "information", "house"],
        }
    world = planner.read("game/data/world/locations.json")
    for raw in world.get("locations", []) if isinstance(world, Mapping) else []:
        if isinstance(raw, Mapping) and raw.get("ref") == location_ref:
            return raw
    return None


def _route_functions(route: str) -> set[str]:
    text = route.lower()
    required: set[str] = set()
    if any(token in text for token in ("merchant", "price", "market", "trade")):
        required.add("market")
    if any(token in text for token in ("court", "politic", "palace", "official")):
        required.add("politics")
    if any(token in text for token in ("military", "dispatch", "troop", "scout")):
        required.update({"military", "information"})
    if any(token in text for token in ("report", "rumor", "intelligence", "message", "family", "house", "direct")):
        required.add("information")
    return required or {"information"}


def _public_report_summary(record: Mapping[str, Any], source_event: Mapping[str, Any], route: str) -> str:
    facts = record.get("facts") if isinstance(record.get("facts"), Mapping) else {}
    basis = str(facts.get("current_basis", record.get("label", record.get("record_id", "world development"))))
    result = str(source_event.get("result", "inconclusive"))
    if result == "gains_ground":
        direction = "The underlying pressure appears to be strengthening."
    elif result == "checked":
        direction = "The latest move appears to have met resistance."
    else:
        direction = "The latest reports do not yet show a decisive shift."
    return f"Reports reaching Tang Wei through {route} concern {basis}. {direction}"


def settle_world_arc_report(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    """Attempt one lawful player-facing propagation of an arc initiative."""
    arc_ref = host.get("arc_ref")
    source_event_ref = host.get("source_event_ref")
    route = host.get("route")
    if not isinstance(arc_ref, str) or not isinstance(source_event_ref, str) or not isinstance(route, str):
        raise ValueError("world arc report host is invalid")

    document = _arc_document(planner)
    _index, record = _record_index(document, arc_ref)
    owner_path, event_owner = _event_owner(planner)
    source = event_owner["causal_events"].get(source_event_ref)
    if not isinstance(source, Mapping) or source.get("status") != "triggered":
        raise ValueError("world arc report lost its source event")

    runtime = copy.deepcopy(planner.read(RUNTIME_PATH))
    runtime_host = runtime.get("hosts", {}).get(host.get("host_id"))
    if not isinstance(runtime_host, dict):
        raise ValueError("world arc report lost its scheduler host")
    attempts = int(runtime_host.get("attempts", 0)) + 1
    runtime_host["attempts"] = attempts

    player = planner.read("state/player.json")
    location_ref = str(player.get("location", player.get("current_location", "")))
    location = _location_record(planner, location_ref)
    location_state = str(location.get("state", "")).lower() if isinstance(location, Mapping) else ""
    functions = {
        str(value)
        for value in (location.get("functions", []) if isinstance(location, Mapping) else [])
        if isinstance(value, str)
    }
    origin_state = str(host.get("origin_state") or "").lower()
    visibility = str(host.get("visibility") or "discoverable")
    channel_fit = bool(functions & _route_functions(route))
    state_fit = (
        not origin_state
        or origin_state == location_state
        or "merchant" in route.lower()
        or "rumor" in route.lower()
    )

    seed = f"{source_event_ref}|{attempts}|{location_ref}|{route}"
    roll = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
    exposure_chance = 100 if visibility == "direct" else 70
    delivered = channel_fit and state_fit and roll < exposure_chance

    if delivered:
        report_ref = f"{source_event_ref}.report"
        if report_ref not in event_owner["causal_events"]:
            summary = _public_report_summary(record, source, route)
            event_owner["causal_events"][report_ref] = {
                "event_ref": report_ref,
                "kind": "world_arc_report",
                "status": "triggered",
                "due_at": at,
                "triggered_at": at,
                "arc_ref": arc_ref,
                "source_event_ref": source_event_ref,
                "summary": summary,
                "delivery": {
                    "target_ref": "char_tang_wei",
                    "location_ref": location_ref,
                    "route": route,
                },
                "provenance": {
                    "kind": "world_arc_information_propagation",
                    "exposure_roll": roll,
                    "exposure_chance": exposure_chance,
                },
            }
            event_owner.setdefault("runtime", {})["last_settled_at"] = at
            planner.put(owner_path, event_owner)
        runtime_host["recurrence_seconds"] = 0
        planner.put(RUNTIME_PATH, runtime)
        if str(host.get("pressure_stage")) == "acute" and visibility == "direct":
            summary = event_owner["causal_events"][report_ref]["summary"]
            return {
                "wake_ref": f"wake.world_arc.{hashlib.sha256(report_ref.encode('utf-8')).hexdigest()[:20]}",
                "kind": "campaign_event",
                "at": at,
                "campaign_event_ref": report_ref,
                "reason": summary,
            }
        return None

    if attempts >= int(runtime_host.get("max_attempts", WORLD_ARC_REPORT_MAX_ATTEMPTS)):
        runtime_host["recurrence_seconds"] = 0
    planner.put(RUNTIME_PATH, runtime)
    return None


__all__ = [
    "ARC_REGISTRY_PATH",
    "EVENT_OWNER_REF",
    "WORLD_ARC_REPORT_MAX_ATTEMPTS",
    "WORLD_ARC_REPORT_RETRY_SECONDS",
    "WORLD_ARC_REVIEW_SECONDS",
    "settle_world_arc_report",
    "settle_world_arc_review",
    "sync_world_arc_routes",
]
