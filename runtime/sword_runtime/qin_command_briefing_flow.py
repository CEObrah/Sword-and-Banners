"""Durable pre-assumption Qin field-command briefing lifecycle.

A confirmed field-command appointee may request the exact current order of battle,
command establishment and logistics before physically assuming command. Single-unit
appointments remain supported, while registered multi-formation detachments are
briefed as one higher command without collapsing their persistent unit owners.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.military_supply import evaluate_military_supply
from sword_runtime.qin_detachment_command import appointment_formation_refs, assume_registered_qin_detachment_command
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.warfare_depth import build_formation_command_structure

_RUNTIME_PATH = "state/runtime.json"
_PLAYER_PATH = "state/player.json"
_QIN_PATH = "state/states/qin.json"
_RULES_PATH = "game/data/mechanics/warfare-organization.json"
_HISTORY_WINDOW = 512
_PRIORITY = 44


def _event_owner_write(planner: Any, event_ref: str, row: Mapping[str, Any], at: str) -> str:
    existing = get_causal_event(planner, event_ref)
    if isinstance(existing, Mapping):
        return event_ref
    payload = copy.deepcopy(dict(row))
    payload["provenance"] = {
        "kind": "causal_runtime_settlement",
        "source_owner_ref": "inst_qin_military_bureau",
        "work_ref": event_ref,
        "late_catch_up": False,
    }
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = payload
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)
    return event_ref


def _appointment_for_process(player: Mapping[str, Any], process_ref: str) -> Mapping[str, Any] | None:
    career = player.get("career_state", {}) if isinstance(player.get("career_state"), Mapping) else {}
    appointments = career.get("appointments", []) if isinstance(career, Mapping) else []
    for row in appointments if isinstance(appointments, list) else ():
        if not isinstance(row, Mapping) or row.get("kind") != "qin_field_command":
            continue
        if str(row.get("status", "")) not in {"awaiting_assumption", "active"}:
            continue
        offer_ref = str(row.get("source_event_ref", ""))
        if process_ref in {offer_ref, f"{offer_ref}.decision", str(row.get("office", ""))}:
            return row
    return None


def _briefing_ids(attempt_ref: str, formation_refs: list[str]) -> tuple[str, str, str]:
    digest = hashlib.sha256(
        f"qin-command-briefing|{attempt_ref}|{'|'.join(formation_refs)}".encode("utf-8")
    ).hexdigest()[:20]
    return (
        f"host_qin_command_briefing_{digest}",
        f"event_qin_command_briefing_due_{digest}",
        f"event_qin_command_briefing_{digest}",
    )


def sync_qin_command_briefings(planner: Any, runtime: dict[str, Any]) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    now = CampaignTime.parse(str(runtime["world_time"]))
    player = planner.read(_PLAYER_PATH)
    attempts, _ = recent_interaction_attempts(planner, "char_tang_wei", limit=_HISTORY_WINDOW)
    for attempt in reversed(attempts):
        if attempt.get("action") not in {"ask", "request", "report"}:
            continue
        process_ref = attempt.get("process_ref") or attempt.get("target_ref")
        if not isinstance(process_ref, str):
            continue
        appointment = _appointment_for_process(player, process_ref)
        if not isinstance(appointment, Mapping):
            continue
        formation_refs = appointment_formation_refs(appointment)
        if not formation_refs:
            continue
        attempt_ref = interaction_attempt_ref(attempt)
        host_id, scheduler_event_id, response_ref = _briefing_ids(attempt_ref, formation_refs)
        if isinstance(get_causal_event(planner, response_ref), Mapping) or host_id in hosts:
            continue
        requested_at = attempt.get("at")
        if not isinstance(requested_at, str):
            continue
        due_raw = CampaignTime.parse(requested_at).add_seconds(3600)
        due = due_raw if due_raw > now else now
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "qin_command_briefing_reply",
            "owner_ref": "inst_qin_military_bureau",
            "formation_ref": formation_refs[0],
            "formation_refs": formation_refs,
            "office": str(appointment.get("office", "")),
            "attempt_ref": attempt_ref,
            "response_event_ref": response_ref,
            "player_statement": str(attempt.get("player_statement", ""))[:2000],
            "recurrence_seconds": 0,
            "next_due": str(due),
            "resolved_through": str(now if now < due else due.add_seconds(-1)),
            "safe_through": str(due.add_seconds(-1)),
        }
        events.append({
            "event_id": scheduler_event_id,
            "kind": "qin_command_briefing_reply",
            "priority": _PRIORITY,
            "target_host": host_id,
            "due_at": str(due),
        })
        return


def _hierarchy_text(structure: Mapping[str, Any]) -> str:
    rows = structure.get("internal_hierarchy", [])
    parts = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, Mapping):
            parts.append(f"{int(row.get('count', 0))} x {int(row.get('scale', 0))}-man commanders")
    return ", ".join(parts) or "no internal command hierarchy registered"


def _person_label(planner: Any, person_ref: Any, fallback: str) -> str:
    if not isinstance(person_ref, str) or not person_ref:
        return fallback
    try:
        person = planner.read(planner.owner_path(person_ref))
    except (KeyError, ValueError, FileNotFoundError):
        return fallback
    if isinstance(person, Mapping):
        return str(person.get("name", fallback))
    return fallback


def _logistics_snapshot(planner: Any, formation: Mapping[str, Any]) -> dict[str, Any]:
    logistics = formation.get("logistics", {}) if isinstance(formation.get("logistics"), Mapping) else {}
    supply = evaluate_military_supply(planner, formation)
    return {
        "strategic_supply": str(supply.get("condition", "adequate")),
        "supply_score_milli": int(supply.get("score_milli", 0) or 0),
        "war_arrows": int(logistics.get("war_arrows", 0)),
        "war_bolts": int(logistics.get("war_bolts", 0)),
    }


def _actual_attached(structure: Mapping[str, Any]) -> int:
    fighting = int(structure.get("fighting_establishment", 0))
    unit = structure.get("unit_command", {}) if isinstance(structure.get("unit_command"), Mapping) else {}
    named = int(unit.get("named_billets_present", 0))
    aggregate = int(unit.get("allocated_aggregate_bodies", 0))
    return fighting + named + aggregate


def _detachment_summary(planner: Any, formations: list[Mapping[str, Any]], structures: dict[str, Mapping[str, Any]]) -> tuple[str, dict[str, int]]:
    fighting = sum(int(structures[str(f["formation_ref"])].get("fighting_establishment", 0)) for f in formations)
    senior = sum(int(structures[str(f["formation_ref"])].get("unit_command", {}).get("target_bodies", 0)) for f in formations)
    attached_target = fighting + senior
    attached_actual = sum(_actual_attached(structures[str(f["formation_ref"])]) for f in formations)
    unit_rows: list[str] = []
    for formation in formations:
        ref = str(formation["formation_ref"])
        structure = structures[ref]
        commander = _person_label(planner, formation.get("commander_ref"), "commander unfilled")
        logistics = _logistics_snapshot(planner, formation)
        unit_rows.append(
            f"{formation.get('name', ref)}: {int(formation.get('personnel', 0))} fighting; {commander}; "
            f"internal {_hierarchy_text(structure)}; "
            f"readiness {int(formation.get('readiness', 0))}, morale {int(formation.get('morale', 0))}, cohesion {int(formation.get('cohesion', 0))}, training {int(formation.get('training_progress', 0))}; "
            f"strategic supply {logistics['strategic_supply']} ({logistics['supply_score_milli']}/1000); arrows {logistics['war_arrows']}; bolts {logistics['war_bolts']}."
        )
    header = (
        f"The Qin Military Bureau sends Tang Wei the current pre-assumption order of battle for his registered field command. "
        f"It contains {len(formations)} persistent Qin Units with {fighting} fighting troops. Each Unit has one top commander outside fighting strength: {senior} billets total. "
        f"Authorized attached headcount including Unit command is {attached_target}; current conserved attached headcount is {attached_actual}. "
        "Internal echelon commanders remain soldiers already counted inside each Unit's fighting strength. Routine staff, messenger, supply and medical functions have no separate mandatory headcount quota. "
    )
    footer = (
        "The units remain separate casualty, equipment, fatigue, cohesion, ammunition and mount owners. Strategic supply is derived from their current physical situation rather than stored ration inventory. This briefing transfers no command authority; Tang Wei assumes the higher detachment command only by reporting to the registered location."
    )
    return (header + " ".join(unit_rows) + " " + footer)[:4000], {
        "persistent_unit_slots": len(formations),
        "fighting_establishment_total": fighting,
        "unit_command_bodies_total": senior,
        "fully_staffed_attached_personnel": attached_target,
        "current_attached_personnel": attached_actual,
    }


def settle_qin_command_briefing(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    response_ref = str(host.get("response_event_ref", ""))
    if not response_ref or isinstance(get_causal_event(planner, response_ref), Mapping):
        return None
    raw_refs = host.get("formation_refs")
    formation_refs = [str(ref) for ref in raw_refs if isinstance(ref, str) and ref] if isinstance(raw_refs, list) else []
    lead = str(host.get("formation_ref", ""))
    if lead and lead not in formation_refs:
        formation_refs.insert(0, lead)
    formation_refs = list(dict.fromkeys(formation_refs))
    if not formation_refs:
        return None

    formations: list[dict[str, Any]] = []
    structures: dict[str, Mapping[str, Any]] = {}
    for formation_ref in formation_refs:
        formation_path = planner.owner_path(formation_ref)
        formation = copy.deepcopy(planner.read(formation_path))
        if not isinstance(formation, Mapping) or str(formation.get("administrative_owner", "")) != "state_qin":
            raise ValueError("Qin command briefing lost an exact Qin formation")
        structure = build_formation_command_structure(formation, planner.read(_RULES_PATH))
        formation["command_structure"] = copy.deepcopy(structure)
        planner.put(formation_path, formation)
        formations.append(formation)
        structures[formation_ref] = structure

    player = copy.deepcopy(planner.read(_PLAYER_PATH))
    office = str(host.get("office", ""))
    appointment = None
    rows = player.setdefault("career_state", {}).setdefault("appointments", [])
    for row in rows:
        if isinstance(row, dict) and row.get("office") == office and str(row.get("status", "")) in {"awaiting_assumption", "active"}:
            appointment = row
            break
    if appointment is None:
        raise ValueError("Qin command briefing lost Tang Wei's current appointment")

    summary, totals = _detachment_summary(planner, formations, structures)
    logistics_by_ref = {str(f["formation_ref"]): _logistics_snapshot(f) for f in formations}
    appointment["briefed_at"] = at
    appointment["briefing_event_ref"] = response_ref
    appointment["formation_refs"] = formation_refs
    appointment["command_structure_status"] = "multi_formation_command_establishment_registered"
    appointment["staffing_request_status"] = "conserved_named_command_and_support_registered_or_shortfall_explicit"
    appointment["briefed_command_structure"] = copy.deepcopy(dict(structures[formation_refs[0]]))
    appointment["briefed_formation_structures"] = copy.deepcopy(structures)
    appointment["briefed_detachment_totals"] = copy.deepcopy(totals)
    appointment["briefed_logistics"] = copy.deepcopy(logistics_by_ref[formation_refs[0]])
    appointment["briefed_logistics_by_formation"] = copy.deepcopy(logistics_by_ref)
    planner.put(_PLAYER_PATH, player)

    qin = copy.deepcopy(planner.read(_QIN_PATH))
    qin_appointment = qin.setdefault("appointments", {}).get(office)
    if isinstance(qin_appointment, MutableMapping):
        qin_appointment["briefed_at"] = at
        qin_appointment["briefing_event_ref"] = response_ref
        qin_appointment["formation_refs"] = formation_refs
        qin_appointment["command_structure_status"] = "multi_formation_command_establishment_registered"
        qin_appointment["staffing_request_status"] = "conserved_named_command_and_support_registered_or_shortfall_explicit"
        qin_appointment["briefed_command_structure"] = copy.deepcopy(dict(structures[formation_refs[0]]))
        qin_appointment["briefed_formation_structures"] = copy.deepcopy(structures)
        qin_appointment["briefed_detachment_totals"] = copy.deepcopy(totals)
        qin_appointment["briefed_logistics_by_formation"] = copy.deepcopy(logistics_by_ref)
        planner.put(_QIN_PATH, qin)

    _event_owner_write(planner, response_ref, {
        "event_ref": response_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "inst_qin_military_bureau",
        "target_ref": "char_tang_wei",
        "basis_goal": "Provide exact current multi-formation fighting strength, command establishment, support and stores before assumption",
        "process_kind": "qin_field_command_briefing",
        "process_stage": "briefing_delivered_multi_formation_establishment",
        "summary": summary,
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": str(planner.read(_PLAYER_PATH).get("location", "")),
            "route": "Qin Military Bureau sealed detachment command ledger",
        },
    }, at)
    digest = hashlib.sha256(f"{response_ref}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.qin.command_briefing.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": response_ref,
        "formation_ref": formation_refs[0],
        "formation_refs": formation_refs,
        "reason": summary,
    }


class QinCommandBriefingFlowMixin:
    """Route exact post-appointment briefing requests and detachment assumption."""

    # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = ["QinCommandBriefingFlowMixin", "settle_qin_command_briefing", "sync_qin_command_briefings"]
