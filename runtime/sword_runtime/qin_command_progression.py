"""Qin field-command progression and probationary detachment handling.

The generic player-story flow identifies real Qin vacancies. This layer constrains
those opportunities by demonstrated command scale so an exceptional but unproven
candidate is not handed an army solely because a large vacancy exists. Oversized
vacancies become probationary detached commands backed by conserved formation
manpower. The parent formation remains Qin property and is split only when an
accepted appointee physically reports to assume the command.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import ensure_formation_composition, partition_formation_slices, validate_cohort_ledger
from sword_runtime.development import age_years
from sword_runtime.player_story_flow import (
    _ACTIVE_OPERATION_STATES,
    _BASE_PLAYER_AUTHORITY,
    _OPERATIONS_INDEX,
    _PLAYER_PATH,
    _QIN_PATH,
    _command_candidate_score,
    _decision_event_ref,
    _event_owner_write,
    _player_delivery,
    _pop_pending_offer,
)
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_RULES_PATH = "game/data/mechanics/career-progression.json"
_OFFER_KIND = "qin_probationary_detachment_command"


def _rules(planner: Any) -> Mapping[str, Any]:
    document = planner.read(_RULES_PATH)
    rules = document.get("qin_field_command", {}) if isinstance(document, Mapping) else {}
    if not isinstance(rules, Mapping):
        raise ValueError("Qin field-command progression rules are invalid")
    return rules


def _career_state(player: Mapping[str, Any]) -> Mapping[str, Any]:
    value = player.get("career_state", {})
    return value if isinstance(value, Mapping) else {}


def _command_scale_ceiling(planner: Any, at: str) -> int:
    player = planner.read(_PLAYER_PATH)
    if not isinstance(player, Mapping):
        return 0
    rules = _rules(planner)
    score = _command_candidate_score(player)
    career = _career_state(player)
    verified = max(0, int(career.get("verified_qin_field_command_personnel", 0) or 0))
    exception = max(0, int(career.get("qin_command_scale_exception_personnel", 0) or 0))
    adult_age = max(1, int(rules.get("adult_age", 18)))
    age = age_years(player, CampaignTime.parse(at))

    if verified <= 0:
        ceiling = max(1, int(rules.get("first_command_ceiling_personnel", 1000)))
        if age < adult_age:
            ceiling = min(ceiling, max(1, int(rules.get("juvenile_first_command_ceiling_personnel", ceiling))))
        exceptional_score = max(0, int(rules.get("exceptional_candidate_score", 850)))
        if score >= exceptional_score:
            multiplier = max(1.0, float(rules.get("exceptional_first_command_multiplier", 1.5)))
            ceiling = max(ceiling, int(round(ceiling * multiplier)))
    else:
        multiplier = max(1.0, float(rules.get("progression_multiplier", 3.0)))
        step = max(1, int(rules.get("minimum_progression_step_personnel", 500)))
        ceiling = max(verified + step, int(round(verified * multiplier)))
        if age < adult_age:
            ceiling = min(ceiling, max(verified, int(rules.get("juvenile_progression_ceiling_personnel", 5000))))
        ceiling = min(ceiling, max(1, int(rules.get("maximum_normal_command_ceiling_personnel", 10000))))
    return max(ceiling, exception)


def _detachment_ref(offer_ref: str, parent_ref: str) -> str:
    digest = hashlib.sha256(f"qin-probationary-detachment|{offer_ref}|{parent_ref}".encode("utf-8")).hexdigest()[:12]
    stem = parent_ref.removeprefix("formation_")[:72]
    return f"formation_{stem}_wei_detachment_{digest}"


def _offer_details(player: Mapping[str, Any], offer_ref: str) -> Mapping[str, Any] | None:
    career = _career_state(player)
    offers = career.get("pending_qin_command_offers", {})
    value = offers.get(offer_ref) if isinstance(offers, Mapping) else None
    return value if isinstance(value, Mapping) else None


def _rewrite_offer_event(planner: Any, offer_ref: str, details: Mapping[str, Any], at: str) -> str:
    event = get_causal_event(planner, offer_ref)
    if not isinstance(event, Mapping):
        raise ValueError("Qin command-scale normalization lost its causal offer")
    parent_name = str(details.get("parent_formation_name", details.get("formation_name", "Qin parent formation")))
    parent_personnel = max(0, int(details.get("parent_personnel", 0)))
    personnel = max(0, int(details.get("personnel", 0)))
    location_ref = str(details.get("location_ref", ""))
    summary = (
        "A sealed Qin Military Bureau dispatch reaches Tang Wei. His command review is strong enough for field service, but the Bureau does not place an entire major field formation under a first-time Qin commander merely because that vacancy exists. "
        f"Instead, Qin offers Tang Wei probationary command of a {personnel}-man detachment to be drawn from {parent_name}, an existing {parent_personnel}-man Qin formation in the active northern Wei operation. "
        f"If he accepts, he must report to {location_ref}; only then will the detachment be physically separated from the parent formation and placed under his command. "
        "The appointment is a real field command and a route to larger responsibility, but it remains subordinate to Qin's broader operation. No command authority, troop custody, march order, or allegiance changes unless Tang Wei accepts and reports."
    )
    _path, owner = read_causal_event_owner(planner)
    current = owner.get("causal_events", {}).get(offer_ref)
    if not isinstance(current, MutableMapping):
        raise ValueError("Qin command-scale normalization lost the mutable causal offer")
    updated = copy.deepcopy(owner)
    row = updated["causal_events"][offer_ref]
    row["basis_goal"] = "Match a qualified candidate to a credible probationary Qin field command"
    row["summary"] = summary[:4000]
    row["process_stage"] = "offer_pending"
    row.setdefault("provenance", {})["command_scale_policy"] = "demonstrated_service_ceiling"
    row["provenance"]["command_scale_normalized_at"] = at
    write_causal_event_owner(planner, updated)
    return summary[:4000]


def normalize_pending_qin_command_offers(
    planner: Any,
    at: str,
    runtime: dict[str, Any] | None = None,
) -> list[str]:
    """Downgrade oversized direct offers into conserved probationary detachments."""
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    career = player.setdefault("career_state", {})
    refs = career.get("pending_qin_command_offer_refs", [])
    offers = career.get("pending_qin_command_offers", {})
    if not isinstance(refs, list) or not isinstance(offers, dict):
        return []
    ceiling = _command_scale_ceiling(planner, at)
    minimum_detachment = max(1, int(_rules(planner).get("minimum_probationary_detachment_personnel", 500)))
    changed: list[str] = []
    summaries: dict[str, str] = {}

    for offer_ref in [str(value) for value in refs if isinstance(value, str) and value]:
        details = offers.get(offer_ref)
        if not isinstance(details, dict):
            continue
        if details.get("offer_kind") == _OFFER_KIND:
            continue
        offered_personnel = max(0, int(details.get("personnel", 0) or 0))
        if offered_personnel <= 0 or offered_personnel <= ceiling:
            details["offer_kind"] = "qin_direct_field_command"
            details["command_scale_ceiling_personnel"] = ceiling
            continue
        parent_ref = str(details.get("formation_ref", ""))
        if not parent_ref:
            continue
        parent_name = str(details.get("formation_name", parent_ref))
        target = min(offered_personnel - 1, max(minimum_detachment, ceiling))
        if target <= 0:
            continue
        child_ref = _detachment_ref(offer_ref, parent_ref)
        details.update({
            "offer_kind": _OFFER_KIND,
            "parent_formation_ref": parent_ref,
            "parent_formation_name": parent_name,
            "parent_personnel": offered_personnel,
            "formation_ref": child_ref,
            "formation_name": f"{parent_name} Probationary Detachment",
            "personnel": target,
            "command_scale_ceiling_personnel": ceiling,
            "detachment_materializes_on_assumption": True,
        })
        summaries[offer_ref] = _rewrite_offer_event(planner, offer_ref, details, at)
        changed.append(offer_ref)

    if changed:
        career["pending_qin_command_offers"] = offers
        career["last_command_scale_review_at"] = at
        planner.put(_PLAYER_PATH, player)
    if runtime is not None and isinstance(runtime.get("pending_wake"), dict):
        pending = runtime["pending_wake"]
        ref = str(pending.get("campaign_event_ref", ""))
        if ref in summaries:
            pending["reason"] = summaries[ref]
    return changed


def _wake_for_event(planner: Any, event_ref: str, at: str, prefix: str) -> dict[str, Any]:
    event = get_causal_event(planner, event_ref)
    if not isinstance(event, Mapping):
        raise ValueError("Qin command progression lost its player-facing event")
    digest = hashlib.sha256(f"{event_ref}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.player_story.{prefix}.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": event_ref,
        "reason": str(event.get("summary", "A Qin field-command development has arrived."))[:4000],
    }


def settle_probationary_appointment_reply(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    offer_ref = str(host.get("offer_ref", ""))
    decision_ref = str(host.get("decision_event_ref", _decision_event_ref(offer_ref)))
    if isinstance(get_causal_event(planner, decision_ref), Mapping):
        return None
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    details = _offer_details(player, offer_ref)
    if not isinstance(details, Mapping) or details.get("offer_kind") != _OFFER_KIND:
        return None
    details = _pop_pending_offer(player, offer_ref)
    if not isinstance(details, Mapping):
        raise ValueError("Qin probationary appointment lost its exact pending offer")

    action = str(host.get("player_action", ""))
    child_ref = str(details.get("formation_ref", ""))
    parent_ref = str(details.get("parent_formation_ref", ""))
    operation_ref = str(details.get("operation_ref", ""))
    personnel = max(0, int(details.get("personnel", 0)))
    stage = "declined"

    if action == "decline":
        career = player.setdefault("career_state", {})
        declined = career.setdefault("declined_qin_command_formation_refs", [])
        if parent_ref and parent_ref not in declined:
            declined.append(parent_ref)
        career["declined_qin_command_formation_refs"] = [str(value) for value in declined if value][-32:]
        planner.put(_PLAYER_PATH, player)
        summary = (
            "The Qin Military Bureau receives Tang Wei's refusal and closes this probationary command offer. "
            "No Qin rank, command authority, troop custody, deployment obligation, or allegiance change is created."
        )
    elif action in {"proceed", "comply"}:
        parent_path = planner.owner_path(parent_ref)
        parent = planner.read(parent_path)
        operation_path = planner.read(_OPERATIONS_INDEX).get("operations", {}).get(operation_ref)
        operation = planner.read(operation_path) if isinstance(operation_path, str) else None
        still_open = (
            isinstance(parent, Mapping)
            and isinstance(operation, Mapping)
            and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
            and str(parent.get("administrative_owner", "")) == "state_qin"
            and parent_ref in operation.get("formation_refs", [])
            and int(parent.get("personnel", 0)) > personnel > 0
            and planner.read_optional(f"state/formations/{child_ref.removeprefix('formation_').replace('_', '-')}.json") is None
        )
        if not still_open:
            stage = "lapsed"
            planner.put(_PLAYER_PATH, player)
            summary = (
                "The Qin Military Bureau receives Tang Wei's acceptance, but the exact parent formation or operation can no longer support the promised probationary detachment. "
                "The offer lapses without creating rank, command authority, troop custody, or deployment obligation."
            )
        else:
            office = f"field_command:{child_ref}"
            prior_authority = str(player.get("authority", _BASE_PLAYER_AUTHORITY))
            appointment = {
                "kind": "qin_field_command",
                "offer_kind": _OFFER_KIND,
                "office": office,
                "state_ref": "state_qin",
                "formation_ref": child_ref,
                "formation_name": str(details.get("formation_name", child_ref)),
                "parent_formation_ref": parent_ref,
                "operation_ref": operation_ref,
                "personnel": personnel,
                "appointed_at": at,
                "source_event_ref": offer_ref,
                "report_to_location_ref": str(parent.get("location_ref", "")),
                "prior_authority": prior_authority,
                "status": "awaiting_assumption",
            }
            career = player.setdefault("career_state", {})
            appointments = career.setdefault("appointments", [])
            appointments.append(appointment)
            career["appointments"] = appointments[-32:]
            player["authority"] = (
                f"House Tang heir; patron and commander of Tang Wei Personal Retinue; Qin probationary field-command appointee to {appointment['formation_name']}, awaiting assumption"
            )
            planner.put(_PLAYER_PATH, player)

            qin = copy.deepcopy(planner.read(_QIN_PATH))
            qin.setdefault("appointments", {})[office] = {
                "person_ref": "char_tang_wei",
                "offer_kind": _OFFER_KIND,
                "formation_ref": child_ref,
                "parent_formation_ref": parent_ref,
                "operation_ref": operation_ref,
                "personnel": personnel,
                "appointed_at": at,
                "source_event_ref": offer_ref,
                "report_to_location_ref": str(parent.get("location_ref", "")),
                "status": "awaiting_assumption",
            }
            qin.setdefault("military_administration", {})["last_commander_appointment_at"] = at
            planner.put(_QIN_PATH, qin)
            stage = "accepted_awaiting_assumption"
            summary = (
                f"The Qin Military Bureau receives Tang Wei's acceptance and reserves for him probationary command of a {personnel}-man detachment from {details.get('parent_formation_name', parent_ref)}. "
                f"He must report to {parent.get('location_ref')} before the detachment is physically split from its parent and command authority transfers. "
                "The larger parent formation remains under Qin authority, and acceptance does not choose a march route, battle plan, allegiance change, or permanent strategy."
            )
    else:
        raise ValueError("Qin probationary appointment reply has unsupported player action")

    _event_owner_write(planner, decision_ref, {
        "event_ref": decision_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "inst_qin_military_bureau",
        "target_ref": "char_tang_wei",
        "basis_goal": "Resolve Tang Wei's answer to a scale-matched Qin probationary field-command offer",
        "process_kind": "qin_field_command_offer",
        "process_stage": stage,
        "source_event_ref": offer_ref,
        "summary": summary[:4000],
        "delivery": _player_delivery(planner, "Qin Military Bureau sealed reply"),
    }, at, source_owner_ref="inst_qin_military_bureau")
    return _wake_for_event(planner, decision_ref, at, "appointment")


def _materialize_detachment(planner: Any, appointment: Mapping[str, Any], at: str) -> tuple[str, dict[str, Any]]:
    parent_ref = str(appointment.get("parent_formation_ref", ""))
    child_ref = str(appointment.get("formation_ref", ""))
    n = max(0, int(appointment.get("personnel", 0)))
    parent_path, parent0 = planner._load_formation(parent_ref)
    original = copy.deepcopy(parent0)
    parent = copy.deepcopy(parent0)
    total = int(parent.get("personnel", 0))
    if n <= 0 or n >= total:
        raise ValueError("Qin probationary detachment has invalid personnel")
    if str(parent.get("administrative_owner", "")) != "state_qin":
        raise ValueError("Qin probationary detachment lost Qin administrative ownership")

    parent["personnel"] = total - n
    parent_comp, child_comp = planner._partition_counts(original.get("composition", {}), n, total)
    parent["composition"] = parent_comp
    child = copy.deepcopy(original)
    child["formation_ref"] = child_ref
    child["name"] = str(appointment.get("formation_name", child_ref))
    child["personnel"] = n
    child["composition"] = child_comp
    child["commander_ref"] = None
    child["deputy_ref"] = None
    child["status"] = "detached_pending_commander"
    parent["logistics"], child["logistics"] = planner._partition_material(original.get("logistics", {}), n, total)
    parent["mounts"], child["mounts"] = planner._partition_material(original.get("mounts", {}), n, total)
    parent_eq, child_eq = planner._partition_material(planner._equipment_units(original), n, total)
    planner._set_equipment_units(parent, parent_eq)
    planner._set_equipment_units(child, child_eq)

    child_path = f"state/formations/{child_ref.removeprefix('formation_').replace('_', '-')}.json"
    force_path = planner.owner_path(parent["owner_force_ref"])
    force = planner._ct_force(force_path)
    ensure_formation_composition(force, parent, at=at)
    original["cohort_composition"] = copy.deepcopy(parent.get("cohort_composition", []))
    parent_role = next(iter(parent["composition"]))
    child_role = next(iter(child["composition"]))
    force["allocated_to_formations"][parent_ref] = {"personnel": parent["personnel"], "role": parent_role}
    force["allocated_to_formations"][child_ref] = {"personnel": n, "role": child_role}
    parent["cohort_composition"] = copy.deepcopy(original.get("cohort_composition", []))
    child["cohort_composition"] = []
    partition_formation_slices(force, parent, child, n)
    validate_cohort_ledger(force)

    planner.put(force_path, force)
    planner.put(parent_path, parent)
    planner.put(child_path, child)
    planner._register_owner(child_ref, child_path)
    planner._index_formation_location(child_ref, None, str(child.get("location_ref", "")))
    return child_path, child


def assume_probationary_qin_command(planner: Any, at: str) -> str | None:
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    career = player.setdefault("career_state", {})
    appointments = career.get("appointments", [])
    if not isinstance(appointments, list):
        return None
    operation_index = planner.read(_OPERATIONS_INDEX)

    for appointment in appointments:
        if not isinstance(appointment, dict):
            continue
        if appointment.get("offer_kind") != _OFFER_KIND or appointment.get("status") != "awaiting_assumption":
            continue
        parent_ref = str(appointment.get("parent_formation_ref", ""))
        child_ref = str(appointment.get("formation_ref", ""))
        operation_ref = str(appointment.get("operation_ref", ""))
        offer_ref = str(appointment.get("source_event_ref", ""))
        parent_path = planner.owner_path(parent_ref)
        parent = planner.read(parent_path)
        operation_path = operation_index.get("operations", {}).get(operation_ref) if isinstance(operation_index, Mapping) else None
        operation = copy.deepcopy(planner.read(operation_path)) if isinstance(operation_path, str) else None
        still_open = (
            isinstance(parent, Mapping)
            and isinstance(operation, Mapping)
            and str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES
            and str(parent.get("administrative_owner", "")) == "state_qin"
            and parent_ref in operation.get("formation_refs", [])
            and int(parent.get("personnel", 0)) > int(appointment.get("personnel", 0)) > 0
        )
        if not still_open:
            appointment["status"] = "lapsed_before_assumption"
            appointment["lapsed_at"] = at
            player["authority"] = str(appointment.get("prior_authority", _BASE_PLAYER_AUTHORITY))
            planner.put(_PLAYER_PATH, player)
            qin = copy.deepcopy(planner.read(_QIN_PATH))
            qin_row = qin.setdefault("appointments", {}).get(str(appointment.get("office", "")))
            if isinstance(qin_row, dict):
                qin_row["status"] = "lapsed_before_assumption"
                qin_row["lapsed_at"] = at
            planner.put(_QIN_PATH, qin)
            event_ref = f"event_story_qin_command_lapsed_{hashlib.sha256((offer_ref + child_ref).encode()).hexdigest()[:20]}"
            summary = (
                "A Qin Military Bureau courier reports that the probationary field-command appointment can no longer be assumed because its exact parent formation or operation ceased to support the promised detachment. "
                "No formation command authority or troop custody transfers."
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
        if str(player.get("location", "")) != str(parent.get("location_ref", "")):
            continue

        child_path, child = _materialize_detachment(planner, appointment, at)
        child = copy.deepcopy(child)
        child["commander_ref"] = "char_tang_wei"
        child["command_authority"] = "char_tang_wei"
        child["status"] = str(parent.get("status", "formed"))
        child["command_last_changed_at"] = at
        child["command_assignment_source_ref"] = offer_ref
        planner.put(child_path, child)
        planner._assign_commander_index("char_tang_wei", child_ref)

        operation_refs = operation.setdefault("formation_refs", [])
        if child_ref not in operation_refs:
            operation_refs.append(child_ref)
        operation["formation_refs"] = list(dict.fromkeys(str(value) for value in operation_refs if value))
        planner.put(str(operation_path), operation)

        appointment["status"] = "active"
        appointment["assumed_at"] = at
        career["largest_assumed_qin_field_command_personnel"] = max(
            int(career.get("largest_assumed_qin_field_command_personnel", 0) or 0),
            int(appointment.get("personnel", 0)),
        )
        player["authority"] = (
            f"House Tang heir; patron and commander of Tang Wei Personal Retinue; Qin probationary field commander of {child.get('name', child_ref)}"
        )
        planner.put(_PLAYER_PATH, player)

        qin = copy.deepcopy(planner.read(_QIN_PATH))
        qin_row = qin.setdefault("appointments", {}).get(str(appointment.get("office", "")))
        if isinstance(qin_row, dict):
            qin_row["status"] = "active"
            qin_row["assumed_at"] = at
        qin.setdefault("military_administration", {})["last_probationary_command_assumed_at"] = at
        planner.put(_QIN_PATH, qin)

        event_ref = f"event_story_qin_command_assumed_{hashlib.sha256((child_ref + offer_ref).encode()).hexdigest()[:20]}"
        summary = (
            f"Tang Wei reports to {child.get('location_ref')} and formally assumes the probationary Qin field command he accepted. "
            f"A conserved {int(child.get('personnel', 0))}-man detachment is physically separated from {appointment.get('parent_formation_ref')} and placed under his command. "
            "The parent formation and the detachment both remain Qin property inside the existing operation; the appointment does not itself choose a march route, battle plan, sovereign allegiance, or permanent strategy."
        )
        return _event_owner_write(planner, event_ref, {
            "event_ref": event_ref,
            "kind": "institutional_response",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": "inst_qin_military_bureau",
            "target_ref": "char_tang_wei",
            "basis_goal": "Assume an already-accepted probationary Qin field command at the exact parent formation location",
            "process_kind": "qin_field_command_offer",
            "process_stage": "command_assumed",
            "source_event_ref": offer_ref,
            "summary": summary[:4000],
            "delivery": _player_delivery(planner, "Qin probationary field-command assumption record"),
        }, at, source_owner_ref="inst_qin_military_bureau")
    return None


def close_finished_probationary_service(planner: Any, at: str) -> str | None:
    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    career = player.setdefault("career_state", {})
    appointments = career.get("appointments", [])
    if not isinstance(appointments, list):
        return None
    index = planner.read(_OPERATIONS_INDEX)
    for appointment in appointments:
        if not isinstance(appointment, dict):
            continue
        if appointment.get("offer_kind") != _OFFER_KIND or appointment.get("status") != "active":
            continue
        operation_ref = str(appointment.get("operation_ref", ""))
        operation_path = index.get("operations", {}).get(operation_ref) if isinstance(index, Mapping) else None
        operation = planner.read(operation_path) if isinstance(operation_path, str) else None
        if not isinstance(operation, Mapping) or str(operation.get("status", "")) in _ACTIVE_OPERATION_STATES:
            continue
        appointment["status"] = "completed_service"
        appointment["completed_at"] = at
        personnel = max(0, int(appointment.get("personnel", 0)))
        career["verified_qin_field_command_personnel"] = max(
            int(career.get("verified_qin_field_command_personnel", 0) or 0), personnel
        )
        career["last_verified_qin_field_service_at"] = at
        player["authority"] = str(appointment.get("prior_authority", _BASE_PLAYER_AUTHORITY))
        planner.put(_PLAYER_PATH, player)
        qin = copy.deepcopy(planner.read(_QIN_PATH))
        qin_row = qin.setdefault("appointments", {}).get(str(appointment.get("office", "")))
        if isinstance(qin_row, dict):
            qin_row["status"] = "completed_service"
            qin_row["completed_at"] = at
        planner.put(_QIN_PATH, qin)
        event_ref = f"event_story_qin_command_service_{hashlib.sha256((str(appointment.get('office')) + at).encode()).hexdigest()[:20]}"
        summary = (
            f"Qin closes Tang Wei's probationary field-command tour after the attached operation leaves active service. The Bureau records verified command responsibility for {personnel} soldiers. "
            "That service now counts toward the scale of future Qin field-command consideration; it does not guarantee promotion or a particular next appointment."
        )
        return _event_owner_write(planner, event_ref, {
            "event_ref": event_ref,
            "kind": "institutional_response",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": "inst_qin_military_bureau",
            "target_ref": "char_tang_wei",
            "process_kind": "qin_field_command_service_review",
            "process_stage": "completed_service",
            "source_event_ref": str(appointment.get("source_event_ref", "")),
            "summary": summary[:4000],
            "delivery": _player_delivery(planner, "Qin Military Bureau service record"),
        }, at, source_owner_ref="inst_qin_military_bureau")
    return None


class QinCommandProgressionMixin:
    """Apply command-scale realism around the generic player-story career route."""

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        changed = normalize_pending_qin_command_offers(self, str(runtime["world_time"]), runtime)
        if changed:
            self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        kind = str(host.get("kind", ""))
        if kind == "story_appointment_reply":
            offer_ref = str(host.get("offer_ref", ""))
            player = self.read(_PLAYER_PATH)
            details = _offer_details(player, offer_ref) if isinstance(player, Mapping) else None
            if isinstance(details, Mapping) and details.get("offer_kind") == _OFFER_KIND:
                wake = settle_probationary_appointment_reply(self, host, due_text)
                if isinstance(wake, dict):
                    wake["target_host"] = self._active_host_id
                    wake["event_id"] = self._active_event_id
                self._pending_wake_created = wake
                return

        if kind == "player_story_review":
            completed_ref = close_finished_probationary_service(self, due_text)
            assumed_ref = assume_probationary_qin_command(self, due_text)
            super()._run_due_host(host, due_text)
            changed = normalize_pending_qin_command_offers(self, due_text)
            if changed and isinstance(self._pending_wake_created, dict):
                ref = str(self._pending_wake_created.get("campaign_event_ref", ""))
                if ref in changed:
                    event = get_causal_event(self, ref)
                    if isinstance(event, Mapping):
                        self._pending_wake_created["reason"] = str(event.get("summary", self._pending_wake_created.get("reason", "")))
            event_ref = assumed_ref or completed_ref
            if isinstance(event_ref, str):
                wake = _wake_for_event(self, event_ref, due_text, "command")
                wake["target_host"] = self._active_host_id
                wake["event_id"] = self._active_event_id
                self._pending_wake_created = wake
            return

        super()._run_due_host(host, due_text)


__all__ = [
    "QinCommandProgressionMixin",
    "assume_probationary_qin_command",
    "close_finished_probationary_service",
    "normalize_pending_qin_command_offers",
    "settle_probationary_appointment_reply",
]
