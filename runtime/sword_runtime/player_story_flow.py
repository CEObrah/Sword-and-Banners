"""Causal player-story throughput for the persistent Tang Wei campaign.

The world simulation already owns institutional state, formations, operations,
House development, family people, and chronology.  This module does not invent
those facts.  It joins exact current facts that should naturally produce a
player-facing opportunity or message, persists that handoff in the causal event
owner, and lets the GM stage the human scene from that bounded envelope.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import role_count
from sword_runtime.history_store import recent_history_events
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_PLAYER_PATH = "state/player.json"
_QIN_PATH = "state/states/qin.json"
_OPERATIONS_INDEX = "state/operations/index.json"
_SWORD_FORCE = "state/forces/sword-manor.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_MANOR_POPULATION = "state/population/tang-manor.json"
_SWORD_PROGRESSION = "state/prog/sword-manor-progression.json"

_STORY_HOST_ID = "host_player_story_flow_tang_wei"
_STORY_EVENT_ID = "event_player_story_flow_tang_wei_review"
_STORY_REVIEW_SECONDS = 7 * 86400
_STORY_PRIORITY = 70
_HISTORY_WINDOW = 512

_QUALIFICATION_EVENT_REF = "event_ouki_preliminary_review_disposition_001"
_NORTHERN_WEI_ARC = "arc_ryo_fui_northern_wei_campaign"

_FAMILY_ROTATION = (
    ("char_tang_ling", "Tang Ling", "asks you to come to the family hall for a House and Sword Manor review when you are free"),
    ("char_tang_zhu", "Tang Zhu", "asks you to come to the family hall to discuss House military readiness and your own command prospects"),
    ("char_tang_kai", "Tang Kai", "sends a note asking when his elder brother will come see him at the family hall"),
)


def _story_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def _event_owner_write(planner: Any, event_ref: str, row: Mapping[str, Any], at: str) -> str:
    existing = get_causal_event(planner, event_ref)
    if isinstance(existing, Mapping):
        return event_ref
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = copy.deepcopy(dict(row))
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return event_ref


def _player_delivery(planner: Any) -> dict[str, Any]:
    player = planner.read(_PLAYER_PATH)
    location = player.get("location") if isinstance(player, Mapping) else None
    return {
        "target_ref": "char_tang_wei",
        "location_ref": str(location or "loc_tang_manor_training_ground"),
        "route": "ordinary House or Qin courier delivery",
    }


def _command_candidate_score(player: Mapping[str, Any]) -> int:
    attrs = player.get("attributes", {}) if isinstance(player.get("attributes"), Mapping) else {}
    skills = player.get("skills", {}) if isinstance(player.get("skills"), Mapping) else {}
    attr_keys = ("Intelligence", "Awareness", "Composure")
    skill_keys = (
        "Strategy", "Tactics", "Leadership", "Logistics", "Formation Command",
        "Governance", "Intelligence Operations",
    )
    attr_values = [float(attrs[key]) for key in attr_keys if isinstance(attrs.get(key), (int, float)) and not isinstance(attrs.get(key), bool)]
    skill_values = [float(skills[key]) for key in skill_keys if isinstance(skills.get(key), (int, float)) and not isinstance(skills.get(key), bool)]
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
    if not isinstance(player, Mapping):
        return False
    return _command_candidate_score(player) >= 650


def _pending_offer_refs(player: Mapping[str, Any]) -> list[str]:
    career = player.get("career_state", {}) if isinstance(player.get("career_state"), Mapping) else {}
    values = career.get("pending_qin_command_offer_refs", []) if isinstance(career, Mapping) else []
    return [str(value) for value in values if isinstance(value, str) and value]


def _find_qin_command_vacancy(planner: Any) -> dict[str, Any] | None:
    state = planner.read(_QIN_PATH)
    administration = state.get("military_administration", {}) if isinstance(state, Mapping) else {}
    if max(0, int(administration.get("commander_vacancy_count", 0))) <= 0:
        return None
    index = planner.read(_OPERATIONS_INDEX)
    rows: list[tuple[int, str, str, str, Mapping[str, Any]]] = []
    for operation_ref, operation_path in sorted(index.get("operations", {}).items()) if isinstance(index, Mapping) else ():
        if not isinstance(operation_path, str):
            continue
        operation = planner.read_optional(operation_path)
        if not isinstance(operation, Mapping) or str(operation.get("status", "")) not in {"active", "mobilizing", "advancing", "engaged"}:
            continue
        if str(operation.get("administrative_authority", "")) != "state_qin":
            continue
        arc_ref = str(operation.get("arc_ref", ""))
        priority = 0 if arc_ref == _NORTHERN_WEI_ARC else 1
        for formation_ref in operation.get("formation_refs", []) if isinstance(operation.get("formation_refs"), list) else ():
            if not isinstance(formation_ref, str):
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
            rows.append((priority, str(operation_ref), formation_ref, formation_path, formation))
    if not rows:
        return None
    priority, operation_ref, formation_ref, formation_path, formation = sorted(rows, key=lambda row: (row[0], row[1], row[2]))[0]
    operation_path = str(index.get("operations", {}).get(operation_ref))
    operation = planner.read(operation_path)
    return {
        "operation_ref": operation_ref,
        "operation_path": operation_path,
        "arc_ref": str(operation.get("arc_ref", "")),
        "formation_ref": formation_ref,
        "formation_path": formation_path,
        "formation_name": str(formation.get("name", formation_ref)),
        "personnel": int(formation.get("personnel", 0)),
        "location_ref": str(formation.get("location_ref", "")),
    }


def _offer_event_ref(vacancy: Mapping[str, Any]) -> str:
    return "event_story_qin_command_offer_" + _story_digest(
        {"operation_ref": vacancy["operation_ref"], "formation_ref": vacancy["formation_ref"]}
    )


def _decision_event_ref(offer_ref: str) -> str:
    return f"{offer_ref}.decision"


def _career_offer(planner: Any, at: str) -> str | None:
    if not _qualified_for_qin_field_consideration(planner):
        return None
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    if _pending_offer_refs(player):
        return None
    vacancy = _find_qin_command_vacancy(planner)
    if vacancy is None:
        return None
    offer_ref = _offer_event_ref(vacancy)
    if isinstance(get_causal_event(planner, offer_ref), Mapping):
        return None
    score = _command_candidate_score(player)
    summary = (
        f"A sealed Qin Military Bureau dispatch reaches Tang Wei. His completed command review is being acted on because Qin now has a real field-command vacancy. "
        f"The Bureau offers him command of {vacancy['formation_name']}, an existing {vacancy['personnel']}-man Qin formation attached to the active northern Wei operation. "
        "This is an offer, not an automatic appointment: no command authority, state office, troop custody, deployment order, or allegiance changes unless Tang Wei accepts. "
        "The formation remains Qin property and the operation remains under Qin institutional authority."
    )
    _event_owner_write(planner, offer_ref, {
        "event_ref": offer_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "inst_qin_military_bureau",
        "target_ref": "char_tang_wei",
        "basis_goal": "Fill a verified Qin field-command vacancy from an already-qualified candidate",
        "process_kind": "qin_field_command_offer",
        "process_stage": "offer_pending",
        "source_event_ref": _QUALIFICATION_EVENT_REF,
        "summary": summary[:4000],
        "delivery": _player_delivery(planner),
        "appointment_offer": {
            **copy.deepcopy(dict(vacancy)),
            "candidate_ref": "char_tang_wei",
            "candidate_score": score,
            "state_ref": "state_qin",
            "institution_ref": "inst_qin_military_bureau",
        },
        "provenance": {
            "kind": "causal_runtime_opportunity_join",
            "qualification_ref": _QUALIFICATION_EVENT_REF,
            "vacancy_owner_ref": vacancy["formation_ref"],
            "operation_ref": vacancy["operation_ref"],
        },
    }, at)
    career = player.setdefault("career_state", {})
    pending = career.setdefault("pending_qin_command_offer_refs", [])
    pending.append(offer_ref)
    career["pending_qin_command_offer_refs"] = list(dict.fromkeys(str(value) for value in pending if value))[-8:]
    planner.put(_PLAYER_PATH, player)
    return offer_ref


def _house_digest_event(planner: Any, at: str) -> str | None:
    sword = planner.read(_SWORD_FORCE)
    manor = planner.read(_MANOR_POPULATION)
    progression = planner.read(_SWORD_PROGRESSION)
    house = planner.read(_HOUSE_PATH)
    roles = ("trainee", "junior_disciple", "general_disciple", "senior_disciple", "officer", "mounted_scout")
    authorized = sword.get("authorized_by_role", {}) if isinstance(sword, Mapping) else {}
    counts = {role: role_count(sword, role) for role in roles}
    caps = {role: max(0, int(authorized.get(role, 0))) for role in roles}
    sword_cfg = manor.get("sword_manor", {}) if isinstance(manor, Mapping) and isinstance(manor.get("sword_manor"), Mapping) else {}
    prog_runtime = progression.get("runtime", {}) if isinstance(progression, Mapping) and isinstance(progression.get("runtime"), Mapping) else {}
    programs = house.get("administrative_programs", {}) if isinstance(house, Mapping) and isinstance(house.get("administrative_programs"), Mapping) else {}
    great = programs.get("great_bow_guard", {}) if isinstance(programs, Mapping) and isinstance(programs.get("great_bow_guard"), Mapping) else {}
    signature = {
        "counts": counts,
        "caps": caps,
        "reviews": int(prog_runtime.get("completed_monthly_reviews", 0)),
        "housing": int(sword_cfg.get("trainee_housing_capacity", 0)),
        "intake": int(sword_cfg.get("monthly_intake_capacity", 0)),
        "great": {
            "status": great.get("status"),
            "phase": great.get("recruitment_phase"),
            "applicants": int(great.get("applicants_registered", 0)),
            "screened": int(great.get("screened_candidates", 0)),
            "rejected": int(great.get("rejected_candidates", 0)),
            "accepted": int(great.get("accepted_fighters", 0)),
            "training_hours": int(round(float(great.get("verified_training_hours_per_candidate", 0) or 0))),
        },
    }
    event_ref = "event_story_house_digest_" + _story_digest(signature)
    if isinstance(get_causal_event(planner, event_ref), Mapping):
        return None
    role_text = ", ".join(f"{role.replace('_', ' ')} {counts[role]}/{caps[role]}" for role in roles)
    full = [role for role in roles if caps[role] > 0 and counts[role] >= caps[role]]
    if len(full) == len([role for role in roles if caps[role] > 0]):
        bottleneck = "All current Sword Manor establishments are at their authorized ceilings, so new intake and upward promotions are capacity-bottlenecked until authorization expands or billets open."
    else:
        vacancies = [f"{role.replace('_', ' ')} {max(0, caps[role] - counts[role])}" for role in roles if caps[role] > counts[role]]
        bottleneck = "Current establishment vacancies: " + ", ".join(vacancies) + "."
    great_text = (
        f"Great Bow Guard: phase {great.get('recruitment_phase', great.get('status', 'not opened'))}, "
        f"{int(great.get('applicants_registered', 0))} applicants, {int(great.get('screened_candidates', 0))} screened, "
        f"{int(great.get('rejected_candidates', 0))} rejected, {int(great.get('accepted_fighters', 0))} accepted fighters"
    )
    hours = int(round(float(great.get("verified_training_hours_per_candidate", 0) or 0)))
    if hours:
        great_text += f", {hours} verified training hours per remaining candidate"
    summary = (
        f"Tang Ling sends Tang Wei the current House development ledger. Sword Manor has completed {signature['reviews']} monthly development closes. "
        f"Current establishments: {role_text}. Trainee housing is {signature['housing']} and normal monthly intake capacity is {signature['intake']}. "
        f"{bottleneck} {great_text}. This is a status report from exact House records; it does not create recruits, promotions, or equipment by narration."
    )
    return _event_owner_write(planner, event_ref, {
        "event_ref": event_ref,
        "kind": "message",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "char_tang_ling",
        "target_ref": "char_tang_wei",
        "process_kind": "house_development_digest",
        "process_stage": "delivered",
        "summary": summary[:4000],
        "delivery": _player_delivery(planner),
        "provenance": {"kind": "causal_runtime_house_digest", "signature": _story_digest(signature)},
    }, at)


def _family_invitation_event(planner: Any, at: str) -> str | None:
    date = at.split("T", 1)[0]
    bucket = date.rsplit("-", 1)[0]
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
    return _event_owner_write(planner, event_ref, {
        "event_ref": event_ref,
        "kind": "message",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": person_ref,
        "target_ref": "char_tang_wei",
        "process_kind": "family_initiative",
        "process_stage": "invitation_delivered",
        "summary": summary[:4000],
        "delivery": _player_delivery(planner),
        "provenance": {"kind": "causal_runtime_family_initiative", "calendar_bucket": bucket},
    }, at)


def settle_player_story_review(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    created: list[str] = []
    for builder in (_career_offer, _house_digest_event, _family_invitation_event):
        ref = builder(planner, at)
        if isinstance(ref, str):
            created.append(ref)
    if not created:
        return None
    first = get_causal_event(planner, created[0])
    reason = str(first.get("summary", "A new player-facing development has arrived.")) if isinstance(first, Mapping) else "A new player-facing development has arrived."
    digest = hashlib.sha256(f"{'|'.join(created)}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.player_story.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": created[0],
        "reason": reason,
        "story_event_refs": created,
    }


def _appointment_decision_ids(offer_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"appointment-decision|{offer_ref}".encode("utf-8")).hexdigest()[:20]
    return f"host_story_appointment_reply_{digest}", f"event_story_appointment_reply_{digest}"


def _sync_appointment_replies(planner: Any, runtime: dict[str, Any]) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    now = CampaignTime.parse(str(runtime["world_time"]))
    for event in reversed(recent_history_events(planner, _HISTORY_WINDOW)):
        if not isinstance(event, Mapping):
            continue
        attempt = parse_interaction_attempt_summary(event.get("summary"))
        if not isinstance(attempt, Mapping) or attempt.get("actor_id") != "char_tang_wei":
            continue
        if attempt.get("action") not in {"proceed", "comply", "decline"}:
            continue
        offer_ref = attempt.get("process_ref") or attempt.get("target_ref")
        if not isinstance(offer_ref, str) or not offer_ref.startswith("event_story_qin_command_offer_"):
            continue
        offer = get_causal_event(planner, offer_ref)
        if not isinstance(offer, Mapping) or offer.get("process_kind") != "qin_field_command_offer":
            continue
        decision_ref = _decision_event_ref(offer_ref)
        if isinstance(get_causal_event(planner, decision_ref), Mapping):
            continue
        host_id, event_id = _appointment_decision_ids(offer_ref)
        requested_at = event.get("at")
        if not isinstance(requested_at, str):
            continue
        due_raw = CampaignTime.parse(requested_at).add_seconds(3600)
        due = due_raw if due_raw > now else now
        row = {
            "host_id": host_id,
            "kind": "story_appointment_reply",
            "owner_ref": "inst_qin_military_bureau",
            "offer_ref": offer_ref,
            "decision_event_ref": decision_ref,
            "player_action": str(attempt.get("action")),
            "request_id": str(attempt.get("request_id", "")),
            "recurrence_seconds": 0,
            "next_due": str(due),
            "resolved_through": str(now if now < due else due.add_seconds(-1)),
            "safe_through": str(due.add_seconds(-1)),
        }
        hosts[host_id] = row
        existing = next((item for item in events if isinstance(item, dict) and item.get("event_id") == event_id), None)
        if isinstance(existing, dict):
            existing.update({"kind": "story_appointment_reply", "priority": 45, "target_host": host_id, "due_at": str(due)})
        else:
            events.append({"event_id": event_id, "kind": "story_appointment_reply", "priority": 45, "target_host": host_id, "due_at": str(due)})
        return


def _remove_pending_offer(planner: Any, offer_ref: str) -> dict[str, Any]:
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    career = player.setdefault("career_state", {})
    pending = career.setdefault("pending_qin_command_offer_refs", [])
    career["pending_qin_command_offer_refs"] = [str(value) for value in pending if str(value) != offer_ref]
    return player


def settle_appointment_reply(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    offer_ref = str(host.get("offer_ref", ""))
    decision_ref = str(host.get("decision_event_ref", _decision_event_ref(offer_ref)))
    if isinstance(get_causal_event(planner, decision_ref), Mapping):
        return None
    offer = get_causal_event(planner, offer_ref)
    if not isinstance(offer, Mapping) or offer.get("process_kind") != "qin_field_command_offer":
        raise ValueError("Qin appointment reply lost its exact offer")
    details = offer.get("appointment_offer") if isinstance(offer.get("appointment_offer"), Mapping) else None
    if not isinstance(details, Mapping):
        raise ValueError("Qin appointment offer lacks its exact vacancy envelope")
    action = str(host.get("player_action", ""))
    player = _remove_pending_offer(planner, offer_ref)
    if action == "decline":
        summary = (
            "The Qin Military Bureau receives Tang Wei's refusal and closes this command offer. "
            "No Qin rank, command authority, troop custody, deployment obligation, or allegiance change is created."
        )
        planner.put(_PLAYER_PATH, player)
    elif action in {"proceed", "comply"}:
        formation_ref = str(details.get("formation_ref", ""))
        operation_ref = str(details.get("operation_ref", ""))
        formation_path = planner.owner_path(formation_ref)
        formation = copy.deepcopy(planner.read(formation_path))
        operation_path = planner.read(_OPERATIONS_INDEX).get("operations", {}).get(operation_ref)
        operation = planner.read(operation_path) if isinstance(operation_path, str) else None
        still_open = (
            isinstance(operation, Mapping)
            and str(operation.get("status", "")) in {"active", "mobilizing", "advancing", "engaged"}
            and formation.get("commander_ref") in {None, ""}
            and str(formation.get("administrative_owner", "")) == "state_qin"
            and formation_ref in operation.get("formation_refs", [])
        )
        if not still_open:
            summary = (
                "The Qin Military Bureau receives Tang Wei's acceptance, but the exact command vacancy no longer exists when the reply is processed. "
                "The offer therefore lapses without creating rank, command authority, troop custody, or deployment obligation."
            )
            planner.put(_PLAYER_PATH, player)
        else:
            formation["commander_ref"] = "char_tang_wei"
            formation["command_authority"] = "char_tang_wei"
            formation["command_assigned_at"] = at
            formation["command_assignment_source_ref"] = offer_ref
            planner.put(formation_path, formation)

            appointment = {
                "kind": "qin_field_command",
                "office": f"field_command:{formation_ref}",
                "state_ref": "state_qin",
                "formation_ref": formation_ref,
                "operation_ref": operation_ref,
                "appointed_at": at,
                "source_event_ref": offer_ref,
                "status": "active",
            }
            career = player.setdefault("career_state", {})
            appointments = career.setdefault("appointments", [])
            if not any(isinstance(row, Mapping) and row.get("office") == appointment["office"] and row.get("status") == "active" for row in appointments):
                appointments.append(appointment)
            career["appointments"] = appointments[-32:]
            player["authority"] = (
                f"House Tang heir; patron and commander of Tang Wei Personal Retinue; Qin field commander of {formation.get('name', formation_ref)}"
            )
            planner.put(_PLAYER_PATH, player)

            qin = copy.deepcopy(planner.read(_QIN_PATH))
            qin.setdefault("appointments", {})[appointment["office"]] = {
                "person_ref": "char_tang_wei",
                "formation_ref": formation_ref,
                "operation_ref": operation_ref,
                "appointed_at": at,
                "source_event_ref": offer_ref,
                "status": "active",
            }
            administration = qin.setdefault("military_administration", {})
            administration["commander_vacancy_count"] = max(0, int(administration.get("commander_vacancy_count", 0)) - 1)
            administration["last_commander_assignment_at"] = at
            planner.put(_QIN_PATH, qin)
            summary = (
                f"The Qin Military Bureau receives Tang Wei's acceptance and confirms his appointment to field command of {formation.get('name', formation_ref)}, "
                f"an existing {int(formation.get('personnel', 0))}-man Qin formation in {operation_ref}. Command authority over that formation transfers to Tang Wei now. "
                "Administrative ownership remains Qin's, the operation remains a Qin operation, and this appointment does not by itself choose a march route, battle plan, sovereign allegiance, or permanent strategy for Tang Wei."
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
        "process_stage": "accepted" if action in {"proceed", "comply"} and "confirms his appointment" in summary else ("declined" if action == "decline" else "lapsed"),
        "source_event_ref": offer_ref,
        "summary": summary[:4000],
        "delivery": _player_delivery(planner),
        "provenance": {"kind": "causal_runtime_institutional_decision", "offer_ref": offer_ref, "request_id": host.get("request_id")},
    }, at)
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

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        sync_player_story_flow(self, runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        kind = host.get("kind")
        if kind == "player_story_review":
            wake = settle_player_story_review(self, host, due_text)
            if isinstance(wake, dict):
                wake["target_host"] = self._active_host_id
                wake["event_id"] = self._active_event_id
            self._pending_wake_created = wake
            return
        if kind == "story_appointment_reply":
            wake = settle_appointment_reply(self, host, due_text)
            if isinstance(wake, dict):
                wake["target_host"] = self._active_host_id
                wake["event_id"] = self._active_event_id
            self._pending_wake_created = wake
            return
        super()._run_due_host(host, due_text)


__all__ = [
    "PlayerStoryFlowMixin",
    "settle_appointment_reply",
    "settle_player_story_review",
    "sync_player_story_flow",
]
