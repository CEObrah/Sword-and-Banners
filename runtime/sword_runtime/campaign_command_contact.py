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
from sword_runtime.campaign_command_cycle import campaign_command_projection
from sword_runtime.campaign_communications import command_message_route, command_person_location
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

    operation_ref = cycle.get("operation_ref")
    projection = campaign_command_projection(planner, str(operation_ref)) if isinstance(operation_ref, str) and operation_ref else None
    local_posts = projection.get("local_field_command_posts", []) if isinstance(projection, Mapping) and isinstance(projection.get("local_field_command_posts"), list) else []
    local_commander_refs = {
        str(row.get("commander_ref")) for row in local_posts
        if isinstance(row, Mapping) and row.get("commander_physically_present") and isinstance(row.get("commander_ref"), str)
    }
    allowed_targets = {venue_ref}
    if isinstance(superior_ref, str) and superior_ref:
        allowed_targets.add(superior_ref)
    allowed_targets.update(str(ref) for ref in participants if isinstance(ref, str) and ref)
    allowed_targets.update(local_commander_refs)
    if target_ref not in allowed_targets:
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

    # A location-targeted headquarters request routes to the current superior;
    # a named target preserves the player's chosen commander instead of silently
    # rewriting the request to whichever famous principal is convenient.
    routed_target = superior_ref if target_ref == venue_ref else str(target_ref)
    target_location = command_person_location(planner, routed_target)
    representative_refs = sorted({
        str(row.get("commander_ref"))
        for row in local_posts
        if isinstance(row, Mapping)
        and row.get("commander_physically_present")
        and (
            routed_target in {str(x) for x in row.get("operation_principal_commander_refs", []) if isinstance(x, str)}
            or str(row.get("parent_command_commander_ref", "")) == routed_target
        )
        and isinstance(row.get("commander_ref"), str)
        and str(row.get("commander_ref")) != routed_target
    })
    routed = dict(cycle)
    routed["_contact_target_ref"] = routed_target
    routed["_contact_target_location_ref"] = target_location
    routed["_contact_target_is_colocated"] = bool(target_location and target_location == venue_ref)
    routed["_local_representative_refs"] = representative_refs
    return routed


def _pending_cycle_contact(
    planner: Any, hosts: Mapping[str, Any], cycle_ref: str,
    target_commander_ref: str | None = None, contact_ref: str | None = None,
) -> bool:
    """Return whether this exact interaction already has an unresolved callback.

    Idempotency is interaction-scoped. Two distinct player declarations remain
    separate causal work even when they name the same commander at the same
    instant; only replay/reconciliation of the same contact_ref dedupes.
    """
    for host in hosts.values():
        if not isinstance(host, Mapping):
            continue
        if host.get("kind") != "contact_request" or host.get("route_domain") != "campaign_command_contact":
            continue
        if host.get("campaign_command_cycle_ref") != cycle_ref:
            continue
        if isinstance(target_commander_ref, str) and target_commander_ref and host.get("target_commander_ref") != target_commander_ref:
            continue
        host_contact_ref = host.get("contact_ref")
        if not isinstance(host_contact_ref, str) or not host_contact_ref:
            continue
        if isinstance(contact_ref, str) and contact_ref and host_contact_ref != contact_ref:
            continue
        if get_causal_event_from_reader(planner, _response_ref(host_contact_ref)) is None:
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
            target_ref = str(cycle.get("_contact_target_ref") or cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref"))
            target_location = cycle.get("_contact_target_location_ref")
            # Distinct player declarations remain distinct messages. Only the
            # same persisted interaction may dedupe during reconciliation/retry.
            if _pending_cycle_contact(self, hosts, cycle_ref, target_ref, contact_ref):
                continue

            venue_ref = str(cycle.get("venue_ref") or "")
            representative_refs = [str(x) for x in cycle.get("_local_representative_refs", []) if isinstance(x, str)]
            travel_seconds = 0
            if isinstance(target_location, str) and target_location and venue_ref and target_location != venue_ref:
                try:
                    route = command_message_route(self.read, venue_ref, target_location, round_trip=True)
                    travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
                except (FileNotFoundError, KeyError, TypeError, ValueError):
                    # If exact geography cannot route the named command post, fail
                    # closed rather than manufacturing a fixed fifteen-minute reply.
                    continue
            total_delay = max(delay_seconds, travel_seconds + delay_seconds)
            due = max(current, CampaignTime.parse(requested_at).add_seconds(total_delay))
            host_id, event_id = _campaign_contact_ids(contact_ref)
            coordination_ref = str(cycle["coordination_authority_ref"])
            superior_ref = str(cycle.get("superior_command_ref") or cycle.get("supreme_commander_ref"))
            route_ref = f"campaign_command_contact.{_digest('route', cycle_ref + '|' + target_ref)}"
            representative_text = (
                " Local detached-command representatives available at Tang Wei's headquarters: " + ", ".join(representative_refs) + "."
                if representative_refs else ""
            )
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
                    "target_commander_ref": target_ref,
                    "target_commander_location_ref": target_location if isinstance(target_location, str) else None,
                    "local_representative_refs": representative_refs,
                    "communication_travel_seconds": travel_seconds,
                    "audience_summary": (
                        f"The campaign command channel has completed Tang Wei's contact exchange with {target_ref}. "
                        + ("A mounted courier had to travel to the named command post and return before this handoff became available. " if travel_seconds else "The named command post is reachable through the local headquarters channel. ")
                        + "This establishes headquarters receipt/access only; it does not establish face-to-face access to the named commander, "
                        + "a vanguard ruling, a new operational order, or any troop movement."
                        + representative_text
                    ),
                    "delivery_route": (
                        f"campaign headquarters courier channel: {venue_ref} -> {target_location} -> {venue_ref}"
                        if travel_seconds and isinstance(target_location, str)
                        else "campaign headquarters staff through the saved coordination authority at the command venue"
                    ),
                    "resolved_through": str(current if current < due else due.add_seconds(-1)),
                },
            )


__all__ = ["CampaignCommandContactMixin", "_campaign_cycle_for_attempt", "_pending_cycle_contact"]
