"""Bounded player-facing vitality projections and meaningful continuation.

This module owns no campaign truth. It wraps stable player operations with
presentation-only scene/opportunity projections and a surface command that
translates deterministically into the existing authoritative ``advance_time``.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.api.stable_operations import StableCampaignOperations
from sword_runtime.commands import CommandEnvelope

_MAX_SCENE_PEOPLE = 24
_MAX_OPPORTUNITIES = 12
_DEFAULT_CONTINUATION_HOURS = 720
_MAX_CONTINUATION_HOURS = 876000
_CONTINUATION_KEYS = frozenset({"hours", "target_time"})
_DURABLE_STATE_CATEGORIES = (
    "mechanical outcomes",
    "new knowledge or disclosures",
    "relationship changes",
    "money or resources",
    "injury or recovery",
    "authority or office",
    "commitments or promises",
    "operation or mission state",
    "persistent travel or location changes",
    "named staffing or security facts",
)


def _clean_refs(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _person_location(record: Mapping[str, Any]) -> str | None:
    for key in ("current_location", "current_location_id", "location_ref", "location_id", "location"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    deployment = record.get("deployment")
    if isinstance(deployment, Mapping):
        for key in ("current_location", "current_location_id", "location_ref", "location_id", "location"):
            value = deployment.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def build_scene_vitality(context: Mapping[str, Any], store: Any) -> dict[str, Any]:
    """Project cast semantics from already permitted exact people only."""
    campaign = context.get("campaign") if isinstance(context.get("campaign"), Mapping) else {}
    player = context.get("player") if isinstance(context.get("player"), Mapping) else {}
    scene = context.get("scene") if isinstance(context.get("scene"), Mapping) else {}
    player_id = campaign.get("player_id")
    location = player.get("location") or scene.get("location_id") or scene.get("location")

    upstream = context.get("scene_cast")
    if not isinstance(upstream, Mapping):
        upstream = scene.get("scene_cast") if isinstance(scene.get("scene_cast"), Mapping) else {}
    permitted = {
        ref for ref in _clean_refs(context.get("permitted_person_ids"))
        if ref != player_id
    }
    present_all = [ref for ref in _clean_refs(upstream.get("present_people")) if ref in permitted]
    visible_all = [ref for ref in _clean_refs(upstream.get("visible_people")) if ref in permitted]
    immediate = set(present_all) | set(visible_all)

    owners_doc = store.read_json("state/index/owner-index-gold.json")
    owners = owners_doc.get("owners") if isinstance(owners_doc, Mapping) else {}
    nearby_all: list[str] = []
    if isinstance(location, str) and isinstance(owners, Mapping):
        for person_ref in sorted(permitted - immediate):
            path = owners.get(person_ref)
            if not isinstance(path, str) or not person_ref.startswith("char_"):
                continue
            try:
                record = store.read_json(path)
            except (FileNotFoundError, ValueError):
                continue
            if isinstance(record, Mapping) and _person_location(record) == location:
                nearby_all.append(person_ref)

    occupied = immediate | set(nearby_all)
    referenced_all = sorted(permitted - occupied)
    candidates = list(dict.fromkeys(present_all + visible_all + nearby_all + referenced_all))[:16]
    cast = {
        "present_people": present_all[:_MAX_SCENE_PEOPLE],
        "visible_people": visible_all[:_MAX_SCENE_PEOPLE],
        "nearby_people": nearby_all[:_MAX_SCENE_PEOPLE],
        "referenced_people": referenced_all[:_MAX_SCENE_PEOPLE],
        "present_count": len(present_all),
        "visible_count": len(visible_all),
        "nearby_count": len(nearby_all),
        "referenced_count": len(referenced_all),
        "present_truncated": len(present_all) > _MAX_SCENE_PEOPLE,
        "visible_truncated": len(visible_all) > _MAX_SCENE_PEOPLE,
        "nearby_truncated": len(nearby_all) > _MAX_SCENE_PEOPLE,
        "referenced_truncated": len(referenced_all) > _MAX_SCENE_PEOPLE,
        "semantics": {
            "present_people": "Immediate-scene presence only when an upstream typed runtime projection already established it.",
            "visible_people": "Immediate visibility only when an upstream typed runtime projection already established it.",
            "nearby_people": "Exact permitted people at the player's current site; not automatically in the room or conversation.",
            "referenced_people": "Permitted relevant people not proven present or site-local by this projection.",
        },
    }
    vitality = {
        "ephemeral_motion_allowed": True,
        "nearby_entry_exit_may_be_ephemeral": True,
        "ordinary_background_roles_may_be_ephemeral": True,
        "interaction_candidate_ids": candidates,
        "scope": (
            "The GM may add reversible nonpersistent background activity, incidental local movement, brief greetings, "
            "routine work, and ordinary conversation openings that fit confirmed place, time, and cast. These details "
            "must not settle durable campaign facts."
        ),
        "durable_state_requires_runtime": list(_DURABLE_STATE_CATEGORIES),
    }
    return {"scene_cast": cast, "scene_vitality": vitality}


def build_player_opportunities(context: Mapping[str, Any]) -> dict[str, Any]:
    """Project already-triggered player-visible handles into playable cues."""
    handles = context.get("interaction_handles") if isinstance(context.get("interaction_handles"), list) else []
    attempts = context.get("recent_interaction_attempts") if isinstance(context.get("recent_interaction_attempts"), list) else []
    addressed: set[str] = set()
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            continue
        for key in ("target_ref", "process_ref"):
            ref = attempt.get(key)
            if isinstance(ref, str) and ref:
                addressed.add(ref)

    rows: list[dict[str, Any]] = []
    for handle in handles:
        if not isinstance(handle, Mapping):
            continue
        interaction_ref = handle.get("interaction_ref")
        source_kind = handle.get("kind")
        if not isinstance(interaction_ref, str) or not interaction_ref or not isinstance(source_kind, str):
            continue
        if interaction_ref in addressed:
            continue
        if source_kind == "world_arc_report":
            opportunity_kind = "strategic_report"
        elif source_kind in {"institutional_response", "petition_response", "audience_response"}:
            opportunity_kind = "institutional_followup"
        elif source_kind == "message":
            opportunity_kind = "message_or_contact"
        else:
            opportunity_kind = "player_facing_development"
        rows.append({
            "opportunity_ref": f"opportunity:{interaction_ref}",
            "interaction_ref": interaction_ref,
            "kind": opportunity_kind,
            "source_kind": source_kind,
            "triggered_at": handle.get("triggered_at"),
            "summary": handle.get("summary"),
            "player_facing": True,
            "authority": False,
            "response_rule": "Inspect the exact interaction_ref before a consequential response when details materially matter.",
        })

    source_count = context.get("interaction_handles_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int):
        source_count = len(handles)
    visible = rows[:_MAX_OPPORTUNITIES]
    return {
        "opportunities": visible,
        "opportunities_count": len(rows),
        "opportunities_source_count": source_count,
        "opportunities_truncated": len(rows) > len(visible) or bool(context.get("interaction_handles_truncated")),
    }


def translate_continuation_command(command: CommandEnvelope) -> CommandEnvelope:
    """Translate one deterministic surface intent into authoritative advance_time."""
    if command.command_type != "advance_until_event":
        return command
    payload = dict(command.payload)
    if not set(payload) <= _CONTINUATION_KEYS:
        raise ValueError("advance_until_event contains unsupported caller fields")
    hours = payload.get("hours")
    target_time = payload.get("target_time")
    if hours is not None and target_time is not None:
        raise ValueError("advance_until_event accepts at most one of hours or target_time")
    if hours is None and target_time is None:
        payload["hours"] = _DEFAULT_CONTINUATION_HOURS
    elif hours is not None:
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= _MAX_CONTINUATION_HOURS:
            raise ValueError("advance_until_event hours is invalid")
    elif not isinstance(target_time, str):
        raise ValueError("advance_until_event target_time is invalid")
    return CommandEnvelope(
        campaign_id=command.campaign_id,
        request_id=command.request_id,
        actor_id=command.actor_id,
        command_type="advance_time",
        expected_revision=command.expected_revision,
        submitted_at=command.submitted_at,
        payload=payload,
        mode=command.mode,
    )


class VitalityCampaignOperations(StableCampaignOperations):
    """Stable operations plus scene vitality, opportunities, and continuation."""

    def play_context(self):
        context = super().play_context()
        vitality = build_scene_vitality(context, self.store)
        scene = context.get("scene")
        if isinstance(scene, dict):
            scene["scene_cast"] = vitality["scene_cast"]
            scene["scene_vitality"] = vitality["scene_vitality"]
        context["scene_cast"] = vitality["scene_cast"]
        context["scene_vitality"] = vitality["scene_vitality"]
        context.update(build_player_opportunities(context))
        context.setdefault("limits", {})["meaningful_continuation"] = True
        context["limits"]["player_facing_opportunity_projection"] = True

        commands = context.setdefault("commands", {})
        command_types = dict(commands.get("command_types", {}))
        command_types["advance_until_event"] = {
            "accepted_payload_keys": ["hours", "target_time"],
            "input_guidance": {
                "rule": "provide at most one of hours or target_time; omit both for a bounded 30-day continuation horizon",
                "hours": {"type": "integer", "minimum": 1, "maximum": _MAX_CONTINUATION_HOURS, "default": _DEFAULT_CONTINUATION_HOURS},
                "target_time": {"type": "campaign_time", "rule": "must satisfy the same authoritative horizon rules as advance_time"},
                "stop_rule": "The causal runtime stops broad time advancement when a player-facing report/contact or protected decision is delivered; otherwise the requested horizon is reached.",
            },
            "contested_preview_policy": "outcome_hidden_until_execute",
        }
        commands["command_types"] = command_types
        commands["supported_command_types"] = sorted(command_types)

        temporary = commands.get("temporarily_available_command_types")
        if isinstance(temporary, list) and "advance_time" in temporary and "advance_until_event" not in temporary:
            temporary.append("advance_until_event")
            temporary.sort()
        wake = context.get("pending_wake")
        if isinstance(wake, dict) and isinstance(wake.get("response_command_types"), list):
            response = wake["response_command_types"]
            if "advance_time" in response and "advance_until_event" not in response:
                response.append("advance_until_event")
                response.sort()
        return context

    def _translate_surface_command(self, command: CommandEnvelope) -> CommandEnvelope:
        if command.command_type == "advance_until_event":
            return translate_continuation_command(command)
        return super()._translate_surface_command(command)

    def preview_command(self, command):
        preview = super().preview_command(command)
        if command.command_type == "advance_until_event":
            preview = dict(preview)
            preview["surface_command_type"] = "advance_until_event"
            preview["continuation_status"] = "stop_on_player_facing_runtime_wake_or_horizon"
        return preview

    def lookup_command_receipt(self, command: CommandEnvelope):
        receipt = super().lookup_command_receipt(command)
        if receipt is not None and command.command_type == "advance_until_event":
            receipt = dict(receipt)
            receipt["surface_command_type"] = "advance_until_event"
        return receipt

    def execute_command(self, command):
        receipt = super().execute_command(command)
        if command.command_type == "advance_until_event":
            receipt = dict(receipt)
            receipt["surface_command_type"] = "advance_until_event"
        return receipt


__all__ = [
    "VitalityCampaignOperations",
    "build_player_opportunities",
    "build_scene_vitality",
    "translate_continuation_command",
]
