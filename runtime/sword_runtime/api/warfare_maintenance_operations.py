"""Military-career warfare command surface.

Legacy one-time House/warfare repair tooling was retired by the clean campaign
baseline. This surface now exposes only ordinary supported warfare commands.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.api.input_guidance import INPUT_GUIDANCE_POLICY
from sword_runtime.api.maintenance_operations import QinCommandMaintenanceOperations
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS

_MILITARY_ALLEGIANCE_COMMAND = "military_allegiance_action"
_MILITARY_ALLEGIANCE_GUIDANCE = {
    "action": {"allowed_values": ["rebel", "defect", "mutiny", "defy_state_order", "desert"]},
    "formation_refs": {
        "type": "array",
        "minimum_items": 1,
        "maximum_items": 64,
        "rule": "use distinct exact formations currently under the acting commander's authority; this is a resolution payload bound, never a world-size cap",
    },
    "proposed_commander_ref": {
        "rule": "optional exact proposed commander; gameplay defaults to the player and cannot nominate another person's voluntary rebellion, defection, or desertion"
    },
    "claimant_ref": {
        "rule": "optional exact political claimant or legal authority relevant to legitimacy; it does not itself grant recognition"
    },
    "basis_ref": {
        "rule": "optional exact saved information/evidence claim already available to the actor"
    },
    "outcome_rule": (
        "contested execute-only resolution; formations and named officers resolve independently through saved state allegiance, "
        "professional duty, formation identity, commander bonds, legitimacy, disaffection, command hierarchy, and deterministic crisis pressure"
    ),
    "ownership_rule": "personal following, desertion, defection, or mutiny never silently transfers administrative ownership, equipment title, or state sovereignty",
}


class WarfareHouseMaintenanceOperations(QinCommandMaintenanceOperations):
    """Existing stable surface plus one registered multi-owner repair and allegiance action."""

    def play_context(self) -> dict[str, Any]:
        context = super().play_context()
        commands = context.setdefault("commands", {})
        command_types = dict(commands.get("command_types", {}))
        command_types[_MILITARY_ALLEGIANCE_COMMAND] = {
            "accepted_payload_keys": sorted(COMMAND_PAYLOAD_KEYS[_MILITARY_ALLEGIANCE_COMMAND]),
            "input_guidance": dict(_MILITARY_ALLEGIANCE_GUIDANCE),
            "contested_preview_policy": "outcome_hidden_until_execute",
        }
        commands["command_types"] = command_types
        commands["supported_command_types"] = sorted(command_types)
        wake = context.get("pending_wake")
        if isinstance(wake, dict) and wake.get("kind") == "campaign_event":
            responses = sorted(set(wake.get("response_command_types", [])) | {_MILITARY_ALLEGIANCE_COMMAND})
            wake["response_command_types"] = responses
            if commands.get("availability_scope") == "campaign_event_response":
                commands["temporarily_available_command_types"] = responses
        return context

    def get_command_contract(self, command_type: str) -> dict[str, Any]:
        if command_type != _MILITARY_ALLEGIANCE_COMMAND:
            return super().get_command_contract(command_type)
        runtime = self.runtime.store.read_json("state/runtime.json")
        wake = runtime.get("pending_wake") if isinstance(runtime, Mapping) else None
        available = not isinstance(wake, Mapping) or wake.get("kind") == "campaign_event"
        scope = "campaign_event_response" if isinstance(wake, Mapping) and wake.get("kind") == "campaign_event" else ("normal" if available else "pending_wake_response")
        return {
            "command_type": command_type,
            "accepted_payload_keys": sorted(COMMAND_PAYLOAD_KEYS[command_type]),
            "input_guidance": dict(_MILITARY_ALLEGIANCE_GUIDANCE),
            "contested_preview_policy": "outcome_hidden_until_execute",
            "availability": {"available": available, "scope": scope},
            "input_guidance_policy": INPUT_GUIDANCE_POLICY,
        }


__all__ = ["WarfareHouseMaintenanceOperations"]
