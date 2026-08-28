"""Causal routing for named-person access through an active campaign command.

A player-facing ``seek_contact`` attempt proves only that Tang Wei tried to reach
one named commander. This module gives that attempt a lawful receiving path
through the active campaign command's coordination authority without pretending
that the named commander is physically present, personally received the request,
or answered it.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import get_causal_event_from_reader
from sword_runtime.contact_request_flow import _response_ref
from sword_runtime.sim.calendar import CampaignTime

_RULES_PATH = "game/data/mechanics/campaign-command.json"
_HISTORY_WINDOW = 256


def _digest(contact_ref: str) -> str:
    return hashlib.sha256(f"campaign-command-contact|{contact_ref}".encode("utf-8")).hexdigest()[:20]


def _request_ids(contact_ref: str) -> tuple[str, str]:
    token = _digest(contact_ref)
    return f"host_campaign_command_contact_{token}", f"event_campaign_command_contact_{token}"


def _read_owner_ref(planner: Any, owner_ref: str) -> Mapping[str, Any] | None:
    try:
        path = planner.owner_path(owner_ref)
    except (KeyError, ValueError):
        return None
    try:
        value = planner.read(path)
    except (FileNotFoundError, KeyError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _campaign_command_delay_seconds(planner: Any) -> int:
    rules = planner.read(_RULES_PATH)
    cycle_rules = rules.get("campaign_command_cycle") if isinstance(rules, Mapping) else None
    minutes = cycle_rules.get("named_superior_contact_delay_minutes") if isinstance(cycle_rules, Mapping) else None
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise ValueError("campaign command named-superior contact delay is invalid")
    return minutes * 60


def _campaign_command_route_for_attempt(planner: Any, attempt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Resolve one exact named-superior contact attempt to its receiving staff.

    The route deliberately terminates at the campaign coordination authority.
    It never establishes the target commander's physical presence or personal
    response; those remain separate causal facts.
    """
    if attempt.get("actor_id") != "char_tang_wei" or attempt.get("action") != "seek_contact":
        return None
    process_ref = attempt.get("process_ref")
    target_ref = attempt.get("target_ref")
    if not isinstance(process_ref, str) or not process_ref or not isinstance(target_ref, str) or not target_ref.startswith("char_"):
        return None

    cycle = _read_owner_ref(planner, process_ref)
    if not isinstance(cycle, Mapping) or cycle.get("kind") != "campaign_command_cycle":
        return None
    if cycle.get("status") != "campaign_command_active":
        return None

    participants = cycle.get("participant_commander_refs")
    if not isinstance(participants, list):
        raise ValueError("campaign command cycle participant registry is invalid")
    participant_refs = {str(value) for value in participants if isinstance(value, str)}
    if "char_tang_wei" not in participant_refs:
        return None

    superior_refs = {
        str(value)
        for value in (cycle.get("supreme_commander_ref"), cycle.get("superior_command_ref"))
        if isinstance(value, str) and value
    }
    if target_ref not in superior_refs or target_ref not in participant_refs:
        return None

    venue_ref = cycle.get("venue_ref")
    institution_ref = cycle.get("coordination_authority_ref")
    if not isinstance(venue_ref, str) or not venue_ref or not isinstance(institution_ref, str) or not institution_ref:
        raise ValueError("campaign command cycle lacks venue or coordination authority")

    player = planner.read("state/player.json")
    if not isinstance(player, Mapping) or player.get("location") != venue_ref:
        return None

    target = _read_owner_ref(planner, target_ref)
    target_name = target.get("name") if isinstance(target, Mapping) else None
    if not isinstance(target_name, str) or not target_name.strip():
        target_name = target_ref

    return {
        "route_ref": f"{process_ref}.named_superior_contact.{target_ref}",
        "route_domain": "campaign_command_contact",
        "campaign_command_cycle_ref": process_ref,
        "institution_ref": institution_ref,
        "target_person_ref": target_ref,
        "target_person_name": target_name,
        "delay_seconds": _campaign_command_delay_seconds(planner),
        "receiving_role": "campaign command receiving staff",
        "delivery_route": "active campaign-command receiving channel",
        "audience_summary": (
            f"Campaign command staff receive Tang Wei's effort to reach {target_name} and open the current "
            f"receiving channel for that business. This establishes contact with the receiving staff only; "
            f"{target_name} has not yet received Tang Wei in person or answered him."
        ),
    }


class CampaignCommandContactFlowMixin:
    """Make named-superior seek attempts causally reachable on the next wait."""

    def _sync_campaign_command_contact_routes(self, runtime: dict[str, Any]) -> int:
        current_text = runtime.get("world_time")
        hosts = runtime.get("hosts")
        if not isinstance(current_text, str) or not isinstance(hosts, dict):
            raise ValueError("runtime causal queue is invalid")
        current = CampaignTime.parse(current_text)
        attempts, _ = recent_interaction_attempts(self, "char_tang_wei", limit=_HISTORY_WINDOW)
        scheduled = 0
        for attempt in attempts:
            requested_at = attempt.get("at")
            if not isinstance(requested_at, str):
                continue
            route = _campaign_command_route_for_attempt(self, attempt)
            if route is None:
                continue
            contact_ref = interaction_attempt_ref(attempt)
            if get_causal_event_from_reader(self, _response_ref(contact_ref)) is not None:
                continue
            host_id, event_id = _request_ids(contact_ref)
            if host_id in hosts:
                continue
            due_from_request = CampaignTime.parse(requested_at).add_seconds(int(route["delay_seconds"]))
            due = max(current.add_seconds(1), due_from_request)
            self._schedule_one_shot(
                runtime,
                host_id=host_id,
                event_id=event_id,
                kind="contact_request",
                priority=45,
                due=due,
                row={
                    "owner_ref": route["institution_ref"],
                    "contact_ref": contact_ref,
                    "source_event_id": attempt.get("event_id"),
                    "source_process_ref": route["campaign_command_cycle_ref"],
                    "route_ref": route["route_ref"],
                    "route_domain": route["route_domain"],
                    "institution_ref": route["institution_ref"],
                    "receiving_role": route["receiving_role"],
                    "requested_person_ref": route["target_person_ref"],
                    "requested_person_name": route["target_person_name"],
                    "audience_summary": route["audience_summary"],
                    "delivery_route": route["delivery_route"],
                    "resolved_through": str(current if current < due else due.add_seconds(-1)),
                },
            )
            scheduled += 1
        return scheduled


__all__ = ["CampaignCommandContactFlowMixin", "_campaign_command_route_for_attempt", "_request_ids"]
