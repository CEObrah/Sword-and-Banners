"""Campaign-command contact routing for Tang Wei's active headquarters chain.

The generic institutional contact router resolves authored arc/location routes.  An
active campaign-command cycle is a different durable owner: it already records the
exact venue, coordinating authority, superior command, and player participation.
This mixin bridges only that lawful contact surface into the existing one-shot
contact scheduler.  It does not author orders, decisions, movement, or access to a
specific person's physical presence.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import get_causal_event_from_reader
from sword_runtime.contact_request_flow import _response_ref
from sword_runtime.sim.calendar import CampaignTime

_MECHANICS_PATH = "game/data/mechanics/campaign-command.json"
_HISTORY_WINDOW = 256
_PLAYER_REF = "char_tang_wei"
_CLOSED_STATUSES = {"closed", "completed", "cancelled", "inactive"}


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}|{value}".encode("utf-8")).hexdigest()[:20]


def _campaign_contact_ids(contact_ref: str) -> tuple[str, str]:
    digest = _digest("campaign-command-contact", contact_ref)
    return f"host_campaign_command_contact_{digest}", f"event_campaign_command_contact_{digest}"


def _campaign_command_mechanics(planner: Any) -> Mapping[str, Any]:
    raw = planner.read(_MECHANICS_PATH)
    section = raw.get("campaign_command_cycle") if isinstance(raw, Mapping) else None
    if not isinstance(section, Mapping):
        raise ValueError("campaign command mechanics are missing")
    return section


def _campaign_cycle_for_attempt(planner: Any, attempt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if attempt.get("actor_id") != _PLAYER_REF or attempt.get("action") != "seek_contact":
        return None
    process_ref = attempt.get("process_ref")
    if not isinstance(process_ref, str) or not process_ref.startswith("campaign_command_cycle."):
        return None
    try:
        path = planner.owner_path(process_ref)
    except (KeyError, FileNotFoundError, ValueError):
        return None
    cycle = planner.read_optional(path)
    if not isinstance(cycle, Mapping):
        return None
    if cycle.get("kind") != "campaign_command_cycle" or cycle.get("cycle_ref") != process_ref:
        return None
    if str(cycle.get("status", "")).lower() in _CLOSED_STATUSES:
        return None

    participants = cycle.get("participant_commander_refs")
    if not isinstance(participants, list) or _PLAYER_REF not in participants:
        return None

    venue_ref = cycle.get("venue_ref")
    target_ref = attempt.get("target_ref")
    superior_ref = cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref")
    if not isinstance(venue_ref, str) or not venue_ref:
        return None
    # The live interaction surface normally targets the headquarters location.
    # Supporting the exact saved superior ref as an alternate route does not
    # establish co-location; the resulting event is still a staff-channel handoff.
    if target_ref not in {venue_ref, superior_ref}:
        return None

    player = planner.read("state/player.json")
    player_location = player.get("location") if isinstance(player, Mapping) else None
    if player_location != venue_ref:
        return None

    coordination_ref = cycle.get("coordination_authority_ref")
    if not isinstance(coordination_ref, str) or not coordination_ref:
        return None
    if not isinstance(superior_ref, str) or not superior_ref:
        return None
    return cycle


def _pending_cycle_contact(planner: Any, hosts: Mapping[str, Any], cycle_ref: str) -> bool:
    """Return whether this command cycle already has an unresolved contact callback."""
    for host in hosts.values():
        if not isinstance(host, Mapping):
            continue
        if host.get("kind") != "contact_request" or host.get("route_domain") != "campaign_command_contact":
            continue
        if host.get("campaign_command_cycle_ref") != cycle_ref:
            continue
        contact_ref = host.get("contact_ref")
        if not isinstance(contact_ref, str) or not contact_ref:
            continue
        if get_causal_event_from_reader(planner, _response_ref(contact_ref)) is None:
            return True
    return False


class CampaignCommandContactMixin:
    """Add causal headquarters receiving for exact campaign-command contact attempts."""

    def _sync_contact_request_routes(self, runtime: dict[str, Any]) -> None:
        # Preserve all generic authored institutional routes first.
        super()._sync_contact_request_routes(runtime)

        current_text = runtime.get("world_time")
        hosts = runtime.get("hosts")
        if not isinstance(current_text, str) or not isinstance(hosts, dict):
            raise ValueError("runtime causal queue is invalid")
        current = CampaignTime.parse(current_text)

        mechanics = _campaign_command_mechanics(self)
        delay_minutes = mechanics.get("superior_contact_response_delay_minutes")
        if isinstance(delay_minutes, bool) or not isinstance(delay_minutes, int) or delay_minutes <= 0:
            raise ValueError("campaign superior contact delay is invalid")
        delay_seconds = delay_minutes * 60

        attempts, _ = recent_interaction_attempts(self, _PLAYER_REF, limit=_HISTORY_WINDOW)
        for attempt in attempts:
            cycle = _campaign_cycle_for_attempt(self, attempt)
            if cycle is None:
                continue
            cycle_ref = str(cycle["cycle_ref"])
            contact_ref = interaction_attempt_ref(attempt)
            requested_at = attempt.get("at")
            if not isinstance(contact_ref, str) or not contact_ref or not isinstance(requested_at, str):
                continue
            if get_causal_event_from_reader(self, _response_ref(contact_ref)) is not None:
                continue
            # Repeated zero-time presses before headquarters has processed the
            # first one are one unresolved command-channel contact, not a farm of
            # duplicate callbacks.
            if _pending_cycle_contact(self, hosts, cycle_ref):
                continue

            due = max(current, CampaignTime.parse(requested_at).add_seconds(delay_seconds))
            host_id, event_id = _campaign_contact_ids(contact_ref)
            coordination_ref = str(cycle["coordination_authority_ref"])
            superior_ref = str(cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref"))
            route_ref = f"campaign_command_contact.{_digest('route', cycle_ref + '|' + superior_ref)}"
            self._schedule_one_shot(
                runtime,
                host_id=host_id,
                event_id=event_id,
                kind="contact_request",
                priority=46,
                due=due,
                row={
                    "owner_ref": coordination_ref,
                    "contact_ref": contact_ref,
                    "source_event_id": attempt.get("event_id"),
                    "source_process_ref": cycle_ref,
                    "route_ref": route_ref,
                    "route_domain": "campaign_command_contact",
                    "institution_ref": coordination_ref,
                    "receiving_role": "campaign headquarters command staff",
                    "campaign_command_cycle_ref": cycle_ref,
                    "superior_command_ref": superior_ref,
                    "audience_summary": (
                        "Campaign headquarters has processed Tang Wei's contact attempt through the lawful command channel. "
                        "This establishes headquarters receipt/access only; it does not establish face-to-face access to the superior, "
                        "a vanguard ruling, a new operational order, or any troop movement."
                    ),
                    "delivery_route": "campaign headquarters staff through the saved coordination authority at the command venue",
                    "resolved_through": str(current if current < due else due.add_seconds(-1)),
                },
            )


__all__ = ["CampaignCommandContactMixin", "_campaign_cycle_for_attempt", "_pending_cycle_contact"]
