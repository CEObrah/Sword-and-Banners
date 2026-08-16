"""Durable pre-assumption Qin field-command briefing lifecycle.

A confirmed field-command appointee may request the exact current order of battle,
command structure and logistics before physically assuming the formation. The
briefing reads the existing formation owner and records deficiencies honestly. It
does not transfer command authority, create subunits, invent officers or refill
stores by narration.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.history_store import recent_history_events
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_PLAYER_PATH = "state/player.json"
_QIN_PATH = "state/states/qin.json"
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


def _briefing_ids(request_id: str, formation_ref: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(f"qin-command-briefing|{request_id}|{formation_ref}".encode("utf-8")).hexdigest()[:20]
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
    for history in reversed(recent_history_events(planner, _HISTORY_WINDOW)):
        if not isinstance(history, Mapping):
            continue
        attempt = parse_interaction_attempt_summary(history.get("summary"))
        if not isinstance(attempt, Mapping) or attempt.get("actor_id") != "char_tang_wei":
            continue
        if attempt.get("action") not in {"ask", "request", "report"}:
            continue
        process_ref = attempt.get("process_ref") or attempt.get("target_ref")
        if not isinstance(process_ref, str):
            continue
        appointment = _appointment_for_process(player, process_ref)
        if not isinstance(appointment, Mapping):
            continue
        formation_ref = str(appointment.get("formation_ref", ""))
        request_id = str(attempt.get("request_id", ""))
        if not formation_ref or not request_id:
            continue
        host_id, scheduler_event_id, response_ref = _briefing_ids(request_id, formation_ref)
        if isinstance(get_causal_event(planner, response_ref), Mapping) or host_id in hosts:
            continue
        requested_at = history.get("at")
        if not isinstance(requested_at, str):
            continue
        due_raw = CampaignTime.parse(requested_at).add_seconds(3600)
        due = due_raw if due_raw > now else now
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "qin_command_briefing_reply",
            "owner_ref": "inst_qin_military_bureau",
            "formation_ref": formation_ref,
            "office": str(appointment.get("office", "")),
            "request_id": request_id,
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


def _formation_briefing_summary(formation: Mapping[str, Any]) -> str:
    composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
    comp_text = ", ".join(f"{str(role).replace('_', ' ')} {int(count)}" for role, count in sorted(composition.items())) or "no registered composition"
    logistics = formation.get("logistics", {}) if isinstance(formation.get("logistics"), Mapping) else {}
    mounts = formation.get("mounts", {}) if isinstance(formation.get("mounts"), Mapping) else {}
    mount_text = ", ".join(f"{key} {int(value)}" for key, value in sorted(mounts.items())) or "none registered"
    completeness = formation.get("equipment_completeness", "unknown")
    return (
        f"The Qin Military Bureau sends Tang Wei the current pre-assumption command ledger for {formation.get('name', formation.get('formation_ref'))}. "
        f"Strength: {int(formation.get('personnel', 0))}. Composition: {comp_text}. Readiness {int(formation.get('readiness', 0))}, morale {int(formation.get('morale', 0))}, cohesion {int(formation.get('cohesion', 0))}, training progress {int(formation.get('training_progress', 0))}, fatigue {int(formation.get('fatigue', 0))}, experience {formation.get('experience', 'unknown')}. "
        f"Equipment completeness is {completeness}; the formation owner currently registers mounts as {mount_text}. Current stores: food {int(logistics.get('food_kg', 0))} kg, fodder {int(logistics.get('fodder_kg', 0))} kg, war arrows {int(logistics.get('war_arrows', 0))}, war bolts {int(logistics.get('war_bolts', 0))}. "
        "The current formation record contains no subordinate formation registry, no deputy commander, and no named subordinate commander or officer billets. Qin therefore cannot truthfully provide names or smaller-unit commanders that are not registered. Tang Wei's request to establish qualified subordinate command and deputy coverage is recorded as a command-readiness requirement, not treated as already completed. "
        "This briefing transfers no troop custody or command authority; Tang Wei still assumes the formation only by reporting to its exact location."
    )[:4000]


def settle_qin_command_briefing(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    response_ref = str(host.get("response_event_ref", ""))
    if not response_ref or isinstance(get_causal_event(planner, response_ref), Mapping):
        return None
    formation_ref = str(host.get("formation_ref", ""))
    formation_path = planner.owner_path(formation_ref)
    formation = planner.read(formation_path)
    if not isinstance(formation, Mapping) or str(formation.get("administrative_owner", "")) != "state_qin":
        raise ValueError("Qin command briefing lost its exact Qin formation")
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

    summary = _formation_briefing_summary(formation)
    appointment["briefed_at"] = at
    appointment["briefing_event_ref"] = response_ref
    appointment["command_structure_status"] = "subordinate_registry_absent_staffing_requested"
    appointment["staffing_request_status"] = "required_before_tactical_employment"
    appointment["briefed_logistics"] = {
        "food_kg": int(formation.get("logistics", {}).get("food_kg", 0)) if isinstance(formation.get("logistics"), Mapping) else 0,
        "fodder_kg": int(formation.get("logistics", {}).get("fodder_kg", 0)) if isinstance(formation.get("logistics"), Mapping) else 0,
        "war_arrows": int(formation.get("logistics", {}).get("war_arrows", 0)) if isinstance(formation.get("logistics"), Mapping) else 0,
        "war_bolts": int(formation.get("logistics", {}).get("war_bolts", 0)) if isinstance(formation.get("logistics"), Mapping) else 0,
    }
    planner.put(_PLAYER_PATH, player)

    qin = copy.deepcopy(planner.read(_QIN_PATH))
    qin_appointment = qin.setdefault("appointments", {}).get(office)
    if isinstance(qin_appointment, MutableMapping):
        qin_appointment["briefed_at"] = at
        qin_appointment["briefing_event_ref"] = response_ref
        qin_appointment["command_structure_status"] = "subordinate_registry_absent_staffing_requested"
        qin_appointment["staffing_request_status"] = "required_before_tactical_employment"
        planner.put(_QIN_PATH, qin)

    _event_owner_write(planner, response_ref, {
        "event_ref": response_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "inst_qin_military_bureau",
        "target_ref": "char_tang_wei",
        "basis_goal": "Provide the exact current order of battle, stores and command-readiness deficiencies for an appointed formation before assumption",
        "process_kind": "qin_field_command_briefing",
        "process_stage": "briefing_delivered_staffing_requirement_open",
        "formation_ref": formation_ref,
        "summary": summary,
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": str(planner.read(_PLAYER_PATH).get("location", "")),
            "route": "Qin Military Bureau sealed command ledger",
        },
    }, at)
    digest = hashlib.sha256(f"{response_ref}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.qin.command_briefing.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": response_ref,
        "formation_ref": formation_ref,
        "reason": summary,
    }


class QinCommandBriefingFlowMixin:
    """Route exact post-appointment briefing requests into Qin chronology."""

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        sync_qin_command_briefings(self, runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") != "qin_command_briefing_reply":
            return super()._run_due_host(host, due_text)
        wake = settle_qin_command_briefing(self, host, due_text)
        if isinstance(wake, dict):
            wake["target_host"] = self._active_host_id
            wake["event_id"] = self._active_event_id
        self._pending_wake_created = wake


__all__ = ["QinCommandBriefingFlowMixin", "settle_qin_command_briefing", "sync_qin_command_briefings"]
