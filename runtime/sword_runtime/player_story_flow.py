"""Causal player-story throughput for the persistent Tang Wei campaign.

The world simulation owns institutions, formations, operations, House development,
family people, and chronology. This module joins exact current facts that should
naturally produce a player-facing opportunity or message. The causal event remains
a strict delivery envelope; structured career truth stays in exact mutable owners.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import conserved_establishment_role_count
from sword_runtime.campaign_communications import (
    command_endpoint_location,
    command_message_route,
    ensure_player_message_delivery,
    player_command_location,
)
from sword_runtime.household_request_flow import _house_tang_force_status
from sword_runtime.operation_routing import exact_operation_record, iter_exact_operation_records
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.stat_access import merged_skill_map

_RUNTIME_PATH = "state/runtime.json"
_PLAYER_PATH = "state/player.json"
_QIN_PATH = "state/states/qin.json"
_OPERATIONS_INDEX = "state/operations/index.json"
_HOUSE_FORCE = "state/forces/house-tang.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_MANOR_POPULATION = "state/population/tang-manor.json"
_INFRASTRUCTURE_PATH = "state/infrastructure/settlements.json"
_HOUSE_HOME = "loc_tang_manor"

_STORY_HOST_ID = "host_player_story_flow_tang_wei"
_STORY_EVENT_ID = "event_player_story_flow_tang_wei_review"
_STORY_REVIEW_SECONDS = 7 * 86400
_QIN_OFFER_RESPONSE_SECONDS = 7 * 86400
_STORY_PRIORITY = 40
_HISTORY_WINDOW = 512

_QUALIFICATION_EVENT_REF = "event_ouki_preliminary_review_disposition_001"
_NORTHERN_WEI_ARC = "arc_ryo_fui_northern_wei_campaign"
_ACTIVE_OPERATION_STATES = frozenset({"active", "mobilizing", "advancing", "engaged"})
_BASE_PLAYER_AUTHORITY = "House Tang heir; patron and commander of Tang Wei Personal Retinue; no state office"

_FAMILY_ROTATION = (
    ("char_tang_ling", "Tang Ling", "asks you to come to the family hall for a House and Inner Walls review when you are free"),
    ("char_tang_zhu", "Tang Zhu", "asks you to come to the family hall to discuss House military readiness and your own command prospects"),
    ("char_tang_kai", "Tang Kai", "sends a note asking when his elder brother will come see him at the family hall"),
)


def _story_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def _event_owner_write(
    planner: Any,
    event_ref: str,
    row: Mapping[str, Any],
    at: str,
    *,
    source_owner_ref: str,
) -> str:
    existing = get_causal_event(planner, event_ref)
    if isinstance(existing, Mapping):
        return event_ref
    payload = copy.deepcopy(dict(row))
    payload["provenance"] = {
        "kind": "causal_runtime_settlement",
        "source_owner_ref": source_owner_ref,
        "work_ref": event_ref,
        "late_catch_up": False,
    }
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = payload
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return event_ref


def _player_delivery(planner: Any, route: str) -> dict[str, Any]:
    player = planner.read(_PLAYER_PATH)
    location = player.get("location") if isinstance(player, Mapping) else None
    return {
        "target_ref": "char_tang_wei",
        "location_ref": str(location or "loc_tang_manor_training_ground"),
        "route": route[:1000],
    }


def _update_causal_event(planner: Any, event_ref: str, updates: Mapping[str, Any], at: str) -> dict[str, Any]:
    _path, owner = read_causal_event_owner(planner)
    events = owner.get("causal_events")
    row = events.get(event_ref) if isinstance(events, dict) else None
    if not isinstance(row, Mapping):
        raise ValueError(f"player-story delivery lost causal event: {event_ref}")
    updated = copy.deepcopy(dict(row))
    updated.update(copy.deepcopy(dict(updates)))
    events[event_ref] = updated
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return updated


def _story_delivery_ids(event_ref: str) -> tuple[str, str]:
    token = hashlib.sha256(f"player-story-delivery|{event_ref}".encode("utf-8")).hexdigest()[:20]
    return f"host_player_story_delivery_{token}", f"event_player_story_delivery_{token}"


def _schedule_story_delivery_host(
    planner: Any, *, event_ref: str, at: str, actor_ref: str, delivery_kind: str,
    delivered_stage: str, delivered_summary: str, route_label: str,
    delivery_payload: Mapping[str, Any] | None = None,
    source_location_ref: str | None = None,
) -> str:
    origin = str(source_location_ref or command_endpoint_location(planner, actor_ref) or "")
    target = player_command_location(planner)
    if not origin or not target:
        raise ValueError("player-story message requires exact physical dispatch and delivery locations")
    route = command_message_route(planner.read, origin, target, round_trip=False)
    travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
    host = {
        "kind": "player_story_message_delivery",
        "owner_ref": actor_ref,
        "story_event_ref": event_ref,
        "delivery_kind": delivery_kind,
        "delivered_process_stage": delivered_stage,
        "delivered_summary": delivered_summary[:4000],
        "route_label": route_label[:1000],
        "source_location_ref": origin,
        "response_target_location_ref": target,
        "communication_travel_seconds": travel_seconds,
        "courier_route": copy.deepcopy(dict(route)),
        "delivery_payload": copy.deepcopy(dict(delivery_payload or {})),
        "recurrence_seconds": 0,
    }
    if travel_seconds <= 0:
        settle_player_story_message_delivery(planner, host, at)
        return event_ref

    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, scheduler_event_id = _story_delivery_ids(event_ref)
    due = CampaignTime.parse(at).add_seconds(travel_seconds)
    host.update({
        "host_id": host_id,
        "event_id": scheduler_event_id,
        "next_due": str(due),
        "resolved_through": str(CampaignTime.parse(at)),
        "safe_through": str(due.add_seconds(-1)),
    })
    hosts[host_id] = host
    existing = next((row for row in events if isinstance(row, dict) and row.get("event_id") == scheduler_event_id), None)
    route_row = {
        "event_id": scheduler_event_id,
        "kind": "player_story_message_delivery",
        "priority": 44,
        "target_host": host_id,
        "due_at": str(due),
    }
    if isinstance(existing, dict):
        existing.update(route_row)
        existing.pop("suspended", None)
    else:
        events.append(route_row)
    planner.put(_RUNTIME_PATH, runtime)
    return event_ref


def _dispatch_player_story_message(
    planner: Any, *, event_ref: str, at: str, actor_ref: str, source_owner_ref: str,
    event_kind: str, process_kind: str, transit_stage: str, delivered_stage: str,
    delivered_summary: str, route_label: str, basis_goal: str | None = None,
    source_event_ref: str | None = None, delivery_kind: str = "message",
    delivery_payload: Mapping[str, Any] | None = None,
    source_location_ref: str | None = None,
) -> str:
    existing = get_causal_event(planner, event_ref)
    if isinstance(existing, Mapping):
        return event_ref
    origin = str(source_location_ref or command_endpoint_location(planner, actor_ref) or "")
    target = player_command_location(planner)
    if not origin or not target:
        raise ValueError("player-story dispatch lacks exact physical endpoints")
    route = command_message_route(planner.read, origin, target, round_trip=False)
    travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
    due = CampaignTime.parse(at).add_seconds(travel_seconds)
    row: dict[str, Any] = {
        "event_ref": event_ref,
        "kind": event_kind,
        "status": "in_transit",
        "due_at": str(due),
        "dispatched_at": at,
        "actor_ref": actor_ref,
        "target_ref": "char_tang_wei",
        "process_kind": process_kind,
        "process_stage": transit_stage,
        "summary": f"{route_label} is in transit to Tang Wei."[:4000],
        "delivery": {
            "status": "in_transit",
            "target_ref": "char_tang_wei",
            "source_location_ref": origin,
            "location_ref": target,
            "route": route_label[:1000],
            "courier_route": copy.deepcopy(dict(route)),
        },
    }
    if basis_goal:
        row["basis_goal"] = basis_goal
    if source_event_ref:
        row["source_event_ref"] = source_event_ref
    _event_owner_write(planner, event_ref, row, at, source_owner_ref=source_owner_ref)
    return _schedule_story_delivery_host(
        planner, event_ref=event_ref, at=at, actor_ref=actor_ref,
        delivery_kind=delivery_kind, delivered_stage=delivered_stage,
        delivered_summary=delivered_summary, route_label=route_label,
        delivery_payload=delivery_payload, source_location_ref=origin,
    )


def _career_offer_summary(vacancy: Mapping[str, Any], expires_at: str) -> str:
    return (
        "A sealed Qin Military Bureau dispatch reaches Tang Wei. His completed command review is being acted on because Qin now has a real field-command vacancy. "
        f"The Bureau offers him appointment to command {vacancy['formation_name']}, an existing {vacancy['personnel']}-man Qin formation attached to an active Qin operation. "
        f"The formation is currently at {vacancy['location_ref']}; if Tang Wei accepts, he must report there before operational command is physically assumed. "
        f"The Bureau asks for an answer before {expires_at}; after that the wartime vacancy will no longer be held for an unanswered offer. "
        "This is an offer, not an automatic appointment: no command authority, troop custody, march order, or allegiance changes unless Tang Wei accepts. The formation remains Qin property and the operation remains under Qin institutional authority."
    )[:4000]


def settle_player_story_message_delivery(planner: Any, host: Mapping[str, Any], at: str) -> str | None:
    if not ensure_player_message_delivery(planner, host, at):
        return None
    event_ref = str(host.get("story_event_ref", ""))
    event = get_causal_event(planner, event_ref)
    if not isinstance(event, Mapping):
        raise ValueError("player-story delivery lost its exact dispatched event")
    if event.get("status") == "triggered":
        return event_ref
    delivery_kind = str(host.get("delivery_kind", "message"))
    stage = str(host.get("delivered_process_stage", event.get("process_stage", "delivered")))
    summary = str(host.get("delivered_summary", event.get("summary", "")))[:4000]
    extra_updates: dict[str, Any] = {}
    if delivery_kind == "qin_career_offer":
        payload = host.get("delivery_payload")
        vacancy = payload.get("vacancy") if isinstance(payload, Mapping) else None
        if not isinstance(vacancy, Mapping):
            raise ValueError("Qin career-offer courier lost the exact vacancy snapshot")
        player = copy.deepcopy(planner.read(_PLAYER_PATH))
        if _pending_offer_refs(player) or _qin_field_appointments(player):
            # The courier still arrives, but a newer durable command appointment or
            # offer means this stale dispatch cannot create a second live decision.
            stage = "offer_superseded_before_delivery"
            summary = (
                "A sealed Qin Military Bureau dispatch reaches Tang Wei, but the enclosed field-command offer has already been superseded by a newer live Qin command disposition. "
                "It creates no second appointment, troop custody, or obligation."
            )
        else:
            expires_at = str(CampaignTime.parse(at).add_seconds(_QIN_OFFER_RESPONSE_SECONDS))
            career = player.setdefault("career_state", {})
            pending_refs = career.setdefault("pending_qin_command_offer_refs", [])
            pending_refs.append(event_ref)
            career["pending_qin_command_offer_refs"] = list(dict.fromkeys(str(value) for value in pending_refs if value))[-8:]
            offers = career.setdefault("pending_qin_command_offers", {})
            offers[event_ref] = {**copy.deepcopy(dict(vacancy)), "offered_at": at, "expires_at": expires_at}
            planner.put(_PLAYER_PATH, player)
            stage = "offer_pending"
            summary = _career_offer_summary(vacancy, expires_at)
            extra_updates["expires_at"] = expires_at
    current = player_command_location(planner)
    delivery = copy.deepcopy(dict(event.get("delivery", {}))) if isinstance(event.get("delivery"), Mapping) else {}
    delivery.update({
        "status": "delivered",
        "target_ref": "char_tang_wei",
        "location_ref": str(current or host.get("response_target_location_ref", "")),
        "route": str(host.get("route_label", delivery.get("route", "")))[:1000],
    })
    updates = {
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "process_stage": stage,
        "summary": summary,
        "delivery": delivery,
        **extra_updates,
    }
    _update_causal_event(planner, event_ref, updates, at)
    if delivery_kind == "qin_career_offer" and stage == "offer_pending":
        # Scale-normalization is a domain rule applied only after the offer is
        # physically delivered and becomes a live player decision.
        from sword_runtime.qin_command_progression import normalize_new_qin_offers
        normalize_new_qin_offers(planner, at, {event_ref})
    return event_ref


def _command_candidate_score(player: Mapping[str, Any]) -> int:
    attrs = player.get("attributes", {}) if isinstance(player.get("attributes"), Mapping) else {}
    skills = merged_skill_map(player)
    attr_keys = ("Intelligence", "Awareness", "Composure")
    skill_keys = (
        "Strategy", "Tactics", "Leadership", "Logistics", "Formation Command",
        "Governance", "Intelligence Operations",
    )
    attr_values = [
        float(attrs[key]) for key in attr_keys
        if isinstance(attrs.get(key), (int, float)) and not isinstance(attrs.get(key), bool)
    ]
    skill_values = [
        float(skills[key]) for key in skill_keys
        if isinstance(skills.get(key), (int, float)) and not isinstance(skills.get(key), bool)
    ]
    if not attr_values or not skill_values:
        return 0
    raw = ((sum(attr_values) / len(attr_values)) * 2 + (sum(skill_values) / len(skill_values)) * 3) / 5
    return max(0, min(1000, int(round(raw * 5))))


def _qualified_for_qin_field_consideration(planner: Any) -> bool:
    review = get_causal_event(planner, _QUALIFICATION_EVENT_REF)
    if not isinstance(review, Mapping) or review.get("status") != "triggered":
        return False
    if str(review.get("process_stage", "")) != "preliminary_review_complete":
        return False
    player = planner.read(_PLAYER_PATH)
    return isinstance(player, Mapping) and _command_candidate_score(player) >= 650


def _career_state(player: Mapping[str, Any]) -> Mapping[str, Any]:
    value = player.get("career_state", {})
    return value if isinstance(value, Mapping) else {}


def _pending_offer_refs(player: Mapping[str, Any]) -> list[str]:
    values = _career_state(player).get("pending_qin_command_offer_refs", [])
    return [str(value) for value in values if isinstance(value, str) and value]


def _pending_offer_details(player: Mapping[str, Any], offer_ref: str) -> Mapping[str, Any] | None:
    offers = _career_state(player).get("pending_qin_command_offers", {})
    value = offers.get(offer_ref) if isinstance(offers, Mapping) else None
    return value if isinstance(value, Mapping) else None


def _declined_qin_formations(player: Mapping[str, Any]) -> set[str]:
    values = _career_state(player).get("declined_qin_command_formation_refs", [])
    return {str(value) for value in values if isinstance(value, str) and value}


def _closed_qin_offer_formations(player: Mapping[str, Any]) -> set[str]:
    """Formations whose exact command offer already received a terminal player-side outcome."""
    career = _career_state(player)
    lapsed = career.get("lapsed_qin_command_formation_refs", [])
    return _declined_qin_formations(player) | {
        str(value) for value in lapsed if isinstance(value, str) and value
    }


def _qin_field_appointments(player: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = _career_state(player).get("appointments", [])
    if not isinstance(rows, list):
        return []
    return [
        row for row in rows
        if isinstance(row, Mapping)
        and row.get("kind") == "qin_field_command"
        and str(row.get("status", "")) in {"awaiting_assumption", "active"}
    ]


def _operation_arc_ref(operation: Mapping[str, Any]) -> str:
    direct = operation.get("arc_ref")
    if isinstance(direct, str) and direct:
        return direct
    refs = operation.get("objective_refs", [])
    if isinstance(refs, list) and _NORTHERN_WEI_ARC in refs:
        return _NORTHERN_WEI_ARC
    return ""


def _find_qin_command_vacancy(planner: Any, excluded_formations: set[str]) -> dict[str, Any] | None:
    state = planner.read(_QIN_PATH)
    administration = state.get("military_administration", {}) if isinstance(state, Mapping) else {}
    if max(0, int(administration.get("commander_vacancy_count", 0))) <= 0:
        return None
    rows: list[tuple[int, str, str, str, str, Mapping[str, Any]]] = []
    for operation_ref, operation_path, operation in iter_exact_operation_records(planner):
        if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATES:
            continue
        if str(operation.get("administrative_authority", "")) != "state_qin":
            continue
        arc_ref = _operation_arc_ref(operation)
        priority = 0 if arc_ref == _NORTHERN_WEI_ARC else 1
        formation_refs = operation.get("formation_refs", [])
        for formation_ref in formation_refs if isinstance(formation_refs, list) else ():
            if not isinstance(formation_ref, str) or formation_ref in excluded_formations:
                continue
            try:
                formation_path = planner.owner_path(formation_ref)
                formation = planner.read(formation_path)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if not isinstance(formation, Mapping):
                continue
            if formation.get("commander_ref") not in {None, ""}:
                continue
            if str(formation.get("administrative_owner", "")) != "state_qin":
                continue
            if int(formation.get("personnel", 0)) <= 0:
                continue
            rows.append((priority, str(operation_ref), operation_path, formation_ref, formation_path, formation))
    if not rows:
        return None
    _priority, operation_ref, operation_path, formation_ref, formation_path, formation = sorted(rows, key=lambda row: (row[0], row[1], row[3]))[0]
    operation = planner.read(operation_path)
    return {
        "operation_ref": operation_ref,
        "arc_ref": _operation_arc_ref(operation),
        "formation_ref": formation_ref,
        "formation_name": str(formation.get("name", formation_ref)),
        "personnel": int(formation.get("personnel", 0)),
        "location_ref": str(formation.get("location_ref", "")),
        "candidate_score": _command_candidate_score(planner.read(_PLAYER_PATH)),
        "state_ref": "state_qin",
        "institution_ref": "inst_qin_military_bureau",
    }


def _offer_event_ref(vacancy: Mapping[str, Any]) -> str:
    return "event_story_qin_command_offer_" + _story_digest(
        {"operation_ref": vacancy["operation_ref"], "formation_ref": vacancy["formation_ref"]}
    )


def _decision_event_ref(offer_ref: str) -> str:
    return f"{offer_ref}.decision"


def _assumption_event_ref(formation_ref: str, offer_ref: str) -> str:
    return "event_story_qin_command_assumed_" + _story_digest(
        {"formation_ref": formation_ref, "offer_ref": offer_ref}
    )


def _career_offer_vacancy_still_open(planner: Any, details: Mapping[str, Any]) -> bool:
    formation_ref = str(details.get("formation_ref", ""))
    operation_ref = str(details.get("operation_ref", ""))
    if not formation_ref or not operation_ref:
        return False
    try:
        formation = planner.read(planner.owner_path(formation_ref))
    except (KeyError, ValueError, FileNotFoundError):
        return False
    resolved = exact_operation_record(planner, operation_ref)
    operation = resolved[1] if resolved is not None else None
    return bool(
        isinstance(operation, Mapping)
        and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
        and formation.get("commander_ref") in {None, ""}
        and str(formation.get("administrative_owner", "")) == "state_qin"
        and formation_ref in operation.get("formation_refs", [])
    )


def _offer_lapse_event_ref(offer_ref: str) -> str:
    return f"{offer_ref}.lapsed"


def _expire_pending_career_offers(planner: Any, at: str) -> list[str]:
    """Let Qin withdraw ignored or obsolete offers instead of waiting forever for Wei."""
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    career = player.setdefault("career_state", {})
    pending = career.setdefault("pending_qin_command_offer_refs", [])
    offers = career.setdefault("pending_qin_command_offers", {})
    if not isinstance(pending, list) or not isinstance(offers, dict):
        return []
    now = CampaignTime.parse(at)
    remaining: list[str] = []
    lapsed_formations = [
        str(value) for value in career.get("lapsed_qin_command_formation_refs", [])
        if isinstance(value, str) and value
    ]
    created: list[str] = []
    changed = False
    for raw_ref in pending:
        offer_ref = str(raw_ref)
        details = offers.get(offer_ref)
        if not isinstance(details, Mapping):
            changed = True
            continue
        offered_at = str(details.get("offered_at") or at)
        expires_at = str(details.get("expires_at") or CampaignTime.parse(offered_at).add_seconds(_QIN_OFFER_RESPONSE_SECONDS))
        expired = now >= CampaignTime.parse(expires_at)
        still_open = _career_offer_vacancy_still_open(planner, details)
        if not expired and still_open:
            remaining.append(offer_ref)
            continue
        changed = True
        offers.pop(offer_ref, None)
        formation_ref = str(details.get("formation_ref", ""))
        if formation_ref and formation_ref not in lapsed_formations:
            lapsed_formations.append(formation_ref)
        event_ref = _offer_lapse_event_ref(offer_ref)
        if isinstance(get_causal_event(planner, event_ref), Mapping):
            continue
        if expired:
            stage = "offer_lapsed_unanswered"
            summary = (
                "The Qin Military Bureau closes the field-command offer after its response window passes without Tang Wei accepting or declining. "
                "The institution does not hold an active wartime vacancy indefinitely for an unanswered offer; no rank, command authority, troop custody, or obligation is created."
            )
        else:
            stage = "offer_withdrawn_vacancy_closed"
            summary = (
                "A Qin Military Bureau courier reports that the field-command offer has been withdrawn because the exact vacancy or operation ceased to be available before Tang Wei answered. "
                "No rank, command authority, troop custody, or obligation is created."
            )
        _dispatch_player_story_message(
            planner, event_ref=event_ref, at=at, actor_ref="inst_qin_military_bureau",
            source_owner_ref="inst_qin_military_bureau", event_kind="institutional_response",
            process_kind="qin_field_command_offer", transit_stage=f"{stage}_notice_in_transit",
            delivered_stage=stage, delivered_summary=summary, route_label="Qin Military Bureau sealed courier",
            source_event_ref=offer_ref, delivery_kind="qin_offer_lapse_notice",
        )
        created.append(event_ref)
    if changed:
        career["pending_qin_command_offer_refs"] = remaining[-8:]
        career["pending_qin_command_offers"] = offers
        career["lapsed_qin_command_formation_refs"] = lapsed_formations[-32:]
        planner.put(_PLAYER_PATH, player)
    return created


def _career_offer(planner: Any, at: str) -> str | None:
    if not _qualified_for_qin_field_consideration(planner):
        return None
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    if _pending_offer_refs(player) or _qin_field_appointments(player):
        return None
    vacancy = _find_qin_command_vacancy(planner, _closed_qin_offer_formations(player))
    if vacancy is None:
        return None
    offer_ref = _offer_event_ref(vacancy)
    if isinstance(get_causal_event(planner, offer_ref), Mapping):
        return None
    return _dispatch_player_story_message(
        planner,
        event_ref=offer_ref,
        at=at,
        actor_ref="inst_qin_military_bureau",
        source_owner_ref="inst_qin_military_bureau",
        event_kind="institutional_response",
        process_kind="qin_field_command_offer",
        transit_stage="offer_in_transit",
        delivered_stage="offer_pending",
        delivered_summary="",
        route_label="Qin Military Bureau sealed courier",
        basis_goal="Fill a verified Qin field-command vacancy from an already-qualified candidate",
        source_event_ref=_QUALIFICATION_EVENT_REF,
        delivery_kind="qin_career_offer",
        delivery_payload={"vacancy": copy.deepcopy(dict(vacancy))},
    )

def _house_digest_event(planner: Any, at: str) -> str | None:
    force = planner.read(_HOUSE_FORCE)
    status = _house_tang_force_status(planner)
    roles = ("house_infantry", "house_cavalry")
    authorized = force.get("authorized_by_role", {}) if isinstance(force, Mapping) else {}
    counts = {role: conserved_establishment_role_count(force, role) for role in roles}
    caps = {role: max(0, int(authorized.get(role, 0))) for role in roles}
    closes = max(0, int(force.get("cohort_training_closes", 0) or 0)) if isinstance(force, Mapping) else 0
    signature = {"counts": counts, "caps": caps, "closes": closes, "intake": int(status.get("practical_intake_now", 0))}
    event_ref = "event_story_house_digest_" + _story_digest(signature)
    if isinstance(get_causal_event(planner, event_ref), Mapping):
        return None
    labels = {"house_infantry": "House Infantry", "house_cavalry": "House Cavalry"}
    strength_text = ", ".join(f"{counts[r]:,}/{caps[r]:,} {labels[r]}" for r in roles)
    vacancies = [f"{max(0, caps[r]-counts[r]):,} {labels[r]}" for r in roles if caps[r] > counts[r]]
    if vacancies:
        capacity_text = "Open places inside the current authorized formations: " + ", ".join(vacancies) + "."
    else:
        capacity_text = (
            "The current authorized formations are fully manned. "
            "That does not mean House Tang has reached its military growth ceiling. Further expansion can authorize additional formations, but the new bodies, equipment, training capacity, and cavalry remounts must still exist and be conserved."
        )
    summary = (
        f"Tang Ling sends Tang Wei the current House military ledger. The House force has completed {closes} monthly training cycle(s). "
        f"Current authorized strength: {strength_text}. {capacity_text} Immediate replacement intake into existing formations is {int(status.get('practical_intake_now', 0)):,}, "
        f"with assessment capacity of {int(status.get('physical_intake_throughput_30d', 0)):,} candidates per 30 days before equipment or remount limits. "
        "The report does not create soldiers; replacement and expansion still conserve population, equipment, mounts, and force structure."
    )
    return _dispatch_player_story_message(
        planner, event_ref=event_ref, at=at, actor_ref="char_tang_ling", source_owner_ref="house_tang",
        event_kind="message", process_kind="house_development_digest", transit_stage="report_in_transit",
        delivered_stage="delivered", delivered_summary=summary, route_label="House Tang direct report",
    )


def _player_on_active_field_duty(planner: Any) -> bool:
    """Return whether Wei is away from home under an exact active field operation."""
    player = planner.read(_PLAYER_PATH)
    if not isinstance(player, Mapping):
        return False
    location_ref = str(player.get("location") or "")
    if not location_ref or location_ref == _HOUSE_HOME:
        return False
    for _operation_ref, _operation_path, operation in iter_exact_operation_records(planner):
        if str(operation.get("status", "")) not in _ACTIVE_OPERATION_STATES:
            continue
        authorities = operation.get("administrative_authorities") if isinstance(operation.get("administrative_authorities"), list) else []
        participants = operation.get("participant_commander_refs") if isinstance(operation.get("participant_commander_refs"), list) else []
        player_is_participant = (
            operation.get("administrative_authority") == "char_tang_wei"
            or operation.get("assignment_authority_ref") == "char_tang_wei"
            or operation.get("commander_ref") == "char_tang_wei"
            or "char_tang_wei" in authorities
            or "char_tang_wei" in participants
        )
        if not player_is_participant:
            continue
        operation_location = operation.get("location_ref")
        if not isinstance(operation_location, str) or not operation_location or operation_location == location_ref:
            return True
    return False


def _family_invitation_event(planner: Any, at: str) -> str | None:
    # Family correspondence remains lawful while Wei is campaigning, but a
    # recurring invitation whose substance is "come to the family hall" should
    # not fire monthly while exact field duty has him away from Tang Manor.
    if _player_on_active_field_duty(planner):
        return None
    bucket = at.split("T", 1)[0].rsplit("-", 1)[0]
    index = int(hashlib.sha256(bucket.encode("utf-8")).hexdigest()[:8], 16) % len(_FAMILY_ROTATION)
    person_ref, name, invitation = _FAMILY_ROTATION[index]
    event_ref = "event_story_family_invitation_" + _story_digest({"bucket": bucket, "person_ref": person_ref})
    if isinstance(get_causal_event(planner, event_ref), Mapping):
        return None
    try:
        _path, person = planner._exact_person(person_ref, active=False)
    except (AttributeError, KeyError, ValueError, FileNotFoundError):
        return None
    life = str(person.get("life_status", person.get("status", "active"))).lower() if isinstance(person, Mapping) else ""
    if life in {"dead", "deceased"}:
        return None
    summary = (
        f"A household messenger brings a personal note from {name}. {name} {invitation}. "
        "It is an invitation rather than a command or automatic scene transition; Tang Wei may answer it, postpone it, or continue with other duties."
    )
    return _dispatch_player_story_message(
        planner, event_ref=event_ref, at=at, actor_ref=person_ref, source_owner_ref=person_ref,
        event_kind="message", process_kind="family_initiative", transit_stage="invitation_in_transit",
        delivered_stage="invitation_delivered", delivered_summary=summary, route_label="House Tang household messenger",
    )

def _appointment_row_mutable(player: dict[str, Any], office: str) -> dict[str, Any] | None:
    career = player.setdefault("career_state", {})
    rows = career.setdefault("appointments", [])
    if not isinstance(rows, list):
        career["appointments"] = []
        rows = career["appointments"]
    for row in rows:
        if isinstance(row, dict) and row.get("office") == office:
            return row
    return None


def _assume_pending_qin_command(planner: Any, at: str) -> str | None:
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    current_location = str(player.get("location", ""))
    pending = [row for row in _qin_field_appointments(player) if str(row.get("status", "")) == "awaiting_assumption"]
    if not pending:
        return None
    for pending_row in pending:
        formation_ref = str(pending_row.get("formation_ref", ""))
        operation_ref = str(pending_row.get("operation_ref", ""))
        offer_ref = str(pending_row.get("source_event_ref", ""))
        office = str(pending_row.get("office", f"field_command:{formation_ref}"))
        if not formation_ref or not operation_ref or not offer_ref:
            continue
        try:
            formation_path = planner.owner_path(formation_ref)
            formation = copy.deepcopy(planner.read(formation_path))
        except (KeyError, ValueError, FileNotFoundError):
            continue
        resolved_operation = exact_operation_record(planner, operation_ref)
        operation = resolved_operation[1] if resolved_operation is not None else None
        still_open = (
            isinstance(operation, Mapping)
            and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
            and formation.get("commander_ref") in {None, ""}
            and str(formation.get("administrative_owner", "")) == "state_qin"
            and formation_ref in operation.get("formation_refs", [])
        )
        if not still_open:
            event_ref = _assumption_event_ref(formation_ref, offer_ref)
            if isinstance(get_causal_event(planner, event_ref), Mapping):
                continue
            row = _appointment_row_mutable(player, office)
            if row is not None:
                row["status"] = "lapsed_before_assumption"
                row["lapsed_at"] = at
                player["authority"] = str(row.get("prior_authority", _BASE_PLAYER_AUTHORITY))
            qin = copy.deepcopy(planner.read(_QIN_PATH))
            qin_appointment = qin.setdefault("appointments", {}).get(office)
            if isinstance(qin_appointment, dict):
                qin_appointment["status"] = "lapsed_before_assumption"
                qin_appointment["lapsed_at"] = at
            planner.put(_PLAYER_PATH, player)
            planner.put(_QIN_PATH, qin)
            summary = (
                "A Qin Military Bureau courier reports that the field-command appointment could not be assumed because the exact vacancy or operation ceased to be available before Tang Wei reported in. "
                "No formation command authority or troop custody transfers from the lapsed appointment."
            )
            return _event_owner_write(planner, event_ref, {
                "event_ref": event_ref,
                "kind": "institutional_response",
                "status": "triggered",
                "due_at": at,
                "triggered_at": at,
                "actor_ref": "inst_qin_military_bureau",
                "target_ref": "char_tang_wei",
                "process_kind": "qin_field_command_offer",
                "process_stage": "lapsed_before_assumption",
                "source_event_ref": offer_ref,
                "summary": summary,
                "delivery": _player_delivery(planner, "Qin Military Bureau courier"),
            }, at, source_owner_ref="inst_qin_military_bureau")
        if current_location != str(formation.get("location_ref", "")):
            continue
        event_ref = _assumption_event_ref(formation_ref, offer_ref)
        if isinstance(get_causal_event(planner, event_ref), Mapping):
            continue
        planner._assign_commander_index("char_tang_wei", formation_ref)
        formation["commander_ref"] = "char_tang_wei"
        formation["command_authority"] = "char_tang_wei"
        formation["command_last_changed_at"] = at
        formation["command_assignment_source_ref"] = offer_ref
        planner.put(formation_path, formation)

        row = _appointment_row_mutable(player, office)
        if row is not None:
            row["status"] = "active"
            row["assumed_at"] = at
        player["authority"] = (
            f"House Tang heir; patron and commander of Tang Wei Personal Retinue; Qin field commander of {formation.get('name', formation_ref)}"
        )
        planner.put(_PLAYER_PATH, player)

        qin = copy.deepcopy(planner.read(_QIN_PATH))
        qin_appointment = qin.setdefault("appointments", {}).get(office)
        if isinstance(qin_appointment, dict):
            qin_appointment["status"] = "active"
            qin_appointment["assumed_at"] = at
        administration = qin.setdefault("military_administration", {})
        administration["commander_vacancy_count"] = max(0, int(administration.get("commander_vacancy_count", 0)) - 1)
        administration["last_commander_assignment_at"] = at
        planner.put(_QIN_PATH, qin)

        summary = (
            f"Tang Wei reports to {formation.get('location_ref')} and formally assumes the Qin field command already accepted. "
            f"Command authority over {formation.get('name', formation_ref)}, an existing {int(formation.get('personnel', 0))}-man Qin formation, is now active under Tang Wei. "
            "Administrative ownership remains Qin's, and the appointment does not itself choose a march route, battle plan, sovereign allegiance, or permanent strategy."
        )
        return _event_owner_write(planner, event_ref, {
            "event_ref": event_ref,
            "kind": "institutional_response",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": "inst_qin_military_bureau",
            "target_ref": "char_tang_wei",
            "basis_goal": "Assume an already-accepted Qin field command at the formation's exact location",
            "process_kind": "qin_field_command_offer",
            "process_stage": "command_assumed",
            "source_event_ref": offer_ref,
            "summary": summary[:4000],
            "delivery": _player_delivery(planner, "Qin field-command assumption record"),
        }, at, source_owner_ref="inst_qin_military_bureau")
    return None


def settle_player_story_review(planner: Any, host: Mapping[str, Any], at: str) -> None:
    """Compatibility entrypoint for one player-story review.

    The review itself is background administration. It may close expired exact
    decisions and dispatch physical messages, but it does not create a hard wake
    merely because a weekly review ran.
    """
    from sword_runtime.qin_command_progression import close_completed_service, normalize_new_qin_offers
    from sword_runtime.qin_command_assumption_flow import _close_unavailable_awaiting_appointments

    before = set(_pending_offer_refs(planner.read(_PLAYER_PATH)))
    lapsed_offers = _expire_pending_career_offers(planner, at)
    _close_unavailable_awaiting_appointments(planner, at)
    close_completed_service(planner, at)
    builders = [_house_digest_event, _family_invitation_event]
    if not lapsed_offers:
        builders.insert(0, _career_offer)
    for builder in builders:
        builder(planner, at)
    after = set(_pending_offer_refs(planner.read(_PLAYER_PATH)))
    normalize_new_qin_offers(planner, at, after - before)
    return None

def _appointment_decision_ids(offer_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"appointment-decision|{offer_ref}".encode("utf-8")).hexdigest()[:20]
    return f"host_story_appointment_reply_{digest}", f"event_story_appointment_reply_{digest}"


def _sync_appointment_replies(planner: Any, runtime: dict[str, Any]) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    now = CampaignTime.parse(str(runtime["world_time"]))
    attempts, _ = recent_interaction_attempts(planner, "char_tang_wei", limit=_HISTORY_WINDOW)
    for attempt in reversed(attempts):
        if attempt.get("action") not in {"proceed", "comply", "decline"}:
            continue
        offer_ref = attempt.get("process_ref") or attempt.get("target_ref")
        if not isinstance(offer_ref, str) or not offer_ref.startswith("event_story_qin_command_offer_"):
            continue
        offer = get_causal_event(planner, offer_ref)
        if not isinstance(offer, Mapping) or offer.get("process_kind") != "qin_field_command_offer":
            continue
        player = planner.read(_PLAYER_PATH)
        if _pending_offer_details(player, offer_ref) is None:
            continue
        decision_ref = _decision_event_ref(offer_ref)
        if isinstance(get_causal_event(planner, decision_ref), Mapping):
            continue
        host_id, event_id = _appointment_decision_ids(offer_ref)
        requested_at = attempt.get("at")
        if not isinstance(requested_at, str):
            continue
        origin_location = attempt.get("origin_location_ref")
        if not isinstance(origin_location, str) or not origin_location:
            origin_location = player_command_location(planner)
        bureau_location = command_endpoint_location(planner, "inst_qin_military_bureau")
        if not origin_location or not bureau_location:
            raise ValueError("Qin appointment reply lacks physical communication endpoints")
        route = command_message_route(planner.read, origin_location, bureau_location, round_trip=True)
        travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
        processing_seconds = 3600
        due_raw = CampaignTime.parse(requested_at).add_seconds(travel_seconds + processing_seconds)
        due = due_raw if due_raw > now else now
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "story_appointment_reply",
            "owner_ref": "inst_qin_military_bureau",
            "offer_ref": offer_ref,
            "decision_event_ref": decision_ref,
            "player_action": str(attempt.get("action")),
            "attempt_ref": interaction_attempt_ref(attempt),
            "request_origin_location_ref": origin_location,
            "bureau_location_ref": bureau_location,
            "response_target_location_ref": origin_location,
            "communication_travel_seconds": travel_seconds,
            "institution_processing_seconds": processing_seconds,
            "courier_route": copy.deepcopy(dict(route)),
            "communication_rule": "acceptance or refusal is not received until the Bureau channel physically carries it and the reply returns",
            "recurrence_seconds": 0,
            "next_due": str(due),
            "resolved_through": str(now if now < due else due.add_seconds(-1)),
            "safe_through": str(due.add_seconds(-1)),
        }
        existing = next((item for item in events if isinstance(item, dict) and item.get("event_id") == event_id), None)
        if isinstance(existing, dict):
            existing.update({"kind": "story_appointment_reply", "priority": 45, "target_host": host_id, "due_at": str(due)})
        else:
            events.append({"event_id": event_id, "kind": "story_appointment_reply", "priority": 45, "target_host": host_id, "due_at": str(due)})
        return


def _pop_pending_offer(player: dict[str, Any], offer_ref: str) -> Mapping[str, Any] | None:
    career = player.setdefault("career_state", {})
    pending = career.setdefault("pending_qin_command_offer_refs", [])
    career["pending_qin_command_offer_refs"] = [str(value) for value in pending if str(value) != offer_ref]
    offers = career.setdefault("pending_qin_command_offers", {})
    details = offers.pop(offer_ref, None) if isinstance(offers, dict) else None
    return details if isinstance(details, Mapping) else None


def settle_appointment_reply(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    if not ensure_player_message_delivery(planner, host, at):
        return None
    offer_ref = str(host.get("offer_ref", ""))
    decision_ref = str(host.get("decision_event_ref", _decision_event_ref(offer_ref)))
    if isinstance(get_causal_event(planner, decision_ref), Mapping):
        return None
    offer = get_causal_event(planner, offer_ref)
    if not isinstance(offer, Mapping) or offer.get("process_kind") != "qin_field_command_offer":
        raise ValueError("Qin appointment reply lost its exact offer")
    action = str(host.get("player_action", ""))
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    pending_details = _pending_offer_details(player, offer_ref)
    if isinstance(pending_details, Mapping) and pending_details.get("offer_kind") == "qin_probationary_detachment_command":
        # The public appointment reply entrypoint must route scale-matched offers
        # to their actual detachment authority too; callers should not need to
        # know which internal offer class the Bureau selected.
        from sword_runtime.qin_command_progression import settle_probationary_reply
        return settle_probationary_reply(planner, host, at)
    details = _pop_pending_offer(player, offer_ref)
    if not isinstance(details, Mapping):
        raise ValueError("Qin appointment reply lost its exact pending offer owner")
    formation_ref = str(details.get("formation_ref", ""))
    operation_ref = str(details.get("operation_ref", ""))
    stage = "declined"

    if action == "decline":
        career = player.setdefault("career_state", {})
        declined = career.setdefault("declined_qin_command_formation_refs", [])
        if formation_ref and formation_ref not in declined:
            declined.append(formation_ref)
        career["declined_qin_command_formation_refs"] = [str(value) for value in declined if value][-32:]
        planner.put(_PLAYER_PATH, player)
        summary = (
            "The Qin Military Bureau receives Tang Wei's refusal and closes this command offer. "
            "No Qin rank, command authority, troop custody, deployment obligation, or allegiance change is created."
        )
    elif action in {"proceed", "comply"}:
        formation_path = planner.owner_path(formation_ref)
        formation = planner.read(formation_path)
        resolved_operation = exact_operation_record(planner, operation_ref)
        operation = resolved_operation[1] if resolved_operation is not None else None
        still_open = (
            isinstance(operation, Mapping)
            and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
            and formation.get("commander_ref") in {None, ""}
            and str(formation.get("administrative_owner", "")) == "state_qin"
            and formation_ref in operation.get("formation_refs", [])
        )
        if not still_open:
            stage = "lapsed"
            planner.put(_PLAYER_PATH, player)
            summary = (
                "The Qin Military Bureau receives Tang Wei's acceptance, but the exact command vacancy no longer exists when the reply is processed. "
                "The offer therefore lapses without creating rank, command authority, troop custody, or deployment obligation."
            )
        else:
            office = f"field_command:{formation_ref}"
            prior_authority = str(player.get("authority", _BASE_PLAYER_AUTHORITY))
            appointment = {
                "kind": "qin_field_command",
                "office": office,
                "state_ref": "state_qin",
                "formation_ref": formation_ref,
                "operation_ref": operation_ref,
                "appointed_at": at,
                "source_event_ref": offer_ref,
                "report_to_location_ref": str(formation.get("location_ref", "")),
                "prior_authority": prior_authority,
                "status": "awaiting_assumption",
            }
            career = player.setdefault("career_state", {})
            appointments = career.setdefault("appointments", [])
            if not any(isinstance(row, Mapping) and row.get("office") == office and str(row.get("status", "")) in {"awaiting_assumption", "active"} for row in appointments):
                appointments.append(appointment)
            career["appointments"] = appointments[-32:]
            player["authority"] = (
                f"House Tang heir; patron and commander of Tang Wei Personal Retinue; Qin field-command appointee to {formation.get('name', formation_ref)}, awaiting assumption"
            )
            planner.put(_PLAYER_PATH, player)

            qin = copy.deepcopy(planner.read(_QIN_PATH))
            qin.setdefault("appointments", {})[office] = {
                "person_ref": "char_tang_wei",
                "formation_ref": formation_ref,
                "operation_ref": operation_ref,
                "appointed_at": at,
                "source_event_ref": offer_ref,
                "report_to_location_ref": str(formation.get("location_ref", "")),
                "status": "awaiting_assumption",
            }
            qin.setdefault("military_administration", {})["last_commander_appointment_at"] = at
            planner.put(_QIN_PATH, qin)
            stage = "accepted_awaiting_assumption"
            summary = (
                f"The Qin Military Bureau receives Tang Wei's acceptance and confirms his appointment to command {formation.get('name', formation_ref)}, an existing {int(formation.get('personnel', 0))}-man Qin formation. "
                f"The appointment is reserved to him, but the formation is at {formation.get('location_ref')}; Tang Wei must report there before commander identity and operational command authority are transferred. "
                "Administrative ownership remains Qin's, and acceptance does not choose a march route, battle plan, allegiance change, or permanent strategy."
            )
    else:
        raise ValueError("Qin appointment reply has unsupported player action")

    _event_owner_write(planner, decision_ref, {
        "event_ref": decision_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "inst_qin_military_bureau",
        "target_ref": "char_tang_wei",
        "basis_goal": "Resolve Tang Wei's answer to an exact Qin field-command offer",
        "process_kind": "qin_field_command_offer",
        "process_stage": stage,
        "source_event_ref": offer_ref,
        "summary": summary[:4000],
        "delivery": _player_delivery(planner, "Qin Military Bureau sealed reply"),
    }, at, source_owner_ref="inst_qin_military_bureau")
    digest = hashlib.sha256(f"{decision_ref}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.player_story.appointment.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": decision_ref,
        "reason": summary[:4000],
    }


def sync_player_story_flow(planner: Any, runtime: dict[str, Any]) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    now = CampaignTime.parse(str(runtime["world_time"]))
    host = hosts.get(_STORY_HOST_ID)
    if not isinstance(host, dict):
        host = {
            "host_id": _STORY_HOST_ID,
            "kind": "player_story_review",
            "owner_ref": "char_tang_wei",
            "recurrence_seconds": _STORY_REVIEW_SECONDS,
            "next_due": str(now),
            "resolved_through": str(now.add_seconds(-1)),
            "safe_through": str(now.add_seconds(-1)),
        }
        hosts[_STORY_HOST_ID] = host
    else:
        host["kind"] = "player_story_review"
        host["owner_ref"] = "char_tang_wei"
        host["recurrence_seconds"] = _STORY_REVIEW_SECONDS
        if host.get("next_due") is None:
            host["next_due"] = str(now)
            host["safe_through"] = str(now.add_seconds(-1))
    event = next((row for row in events if isinstance(row, dict) and row.get("event_id") == _STORY_EVENT_ID), None)
    if not isinstance(event, dict):
        events.append({"event_id": _STORY_EVENT_ID, "kind": "player_story_review", "priority": _STORY_PRIORITY, "target_host": _STORY_HOST_ID, "due_at": str(host["next_due"])})
    else:
        event.update({"kind": "player_story_review", "priority": _STORY_PRIORITY, "target_host": _STORY_HOST_ID, "due_at": str(host["next_due"])})
        event.pop("suspended", None)
    _sync_appointment_replies(planner, runtime)


class PlayerStoryFlowMixin:
    """Schedule and settle lawful player-facing opportunity/message throughput."""

    # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = [
    "PlayerStoryFlowMixin",
    "_decision_event_ref",
    "settle_appointment_reply",
    "settle_player_story_review",
    "sync_player_story_flow",
]
