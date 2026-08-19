"""Current player-facing warfare operations."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.api.input_guidance import INPUT_GUIDANCE_POLICY
from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS

_MILITARY_ALLEGIANCE_COMMAND = "military_allegiance_action"
_COMMAND_PERSONNEL_INDEX_PATH = "state/cmd/command-personnel.json"
_COMMAND_SERVICE_FIELDS = (
    "name", "life_status", "role", "rank", "authority", "affiliation",
    "current_formation_id", "current_location", "location", "location_ref",
    "health_status", "health", "fatigue", "attributes", "aptitude", "skills",
    "specializations", "equipment_loadout_id",
)
_MILITARY_ALLEGIANCE_GUIDANCE = {
    "action": {"allowed_values": ["rebel", "defect", "mutiny", "defy_state_order", "desert"]},
    "formation_refs": {
        "type": "array", "minimum_items": 1, "maximum_items": 64,
        "rule": "use distinct exact formations currently under the acting commander's authority; this is a resolution payload bound, never a world-size cap",
    },
    "proposed_commander_ref": {"rule": "optional exact proposed commander; gameplay defaults to the player and cannot nominate another person's voluntary rebellion, defection, or desertion"},
    "claimant_ref": {"rule": "optional exact political claimant or legal authority relevant to legitimacy; it does not itself grant recognition"},
    "basis_ref": {"rule": "optional exact saved information/evidence claim already available to the actor"},
    "outcome_rule": "contested execute-only resolution; formations and named officers resolve independently through saved state allegiance, professional duty, formation identity, commander bonds, legitimacy, disaffection, command hierarchy, and deterministic crisis pressure",
    "ownership_rule": "personal following, desertion, defection, or mutiny never silently transfers administrative ownership, equipment title, or state sovereignty",
}


class WarfareCampaignOperations(EquipmentAwareCampaignOperations):
    """Stable warfare surface with bounded exact command-person reads."""

    def person_sheet(self, person_id: str) -> dict[str, Any]:
        if person_id.startswith("char_"):
            context = super().play_context()
            permitted = context.get("permitted_person_ids", [])
            if isinstance(permitted, list) and person_id in permitted:
                index = self.store.read_json(_COMMAND_PERSONNEL_INDEX_PATH)
                records = index.get("record_index", {}) if isinstance(index, Mapping) else {}
                path = records.get(person_id) if isinstance(records, Mapping) else None
                if isinstance(path, str) and path.startswith("state/char/"):
                    person = self.store.read_json(path)
                    if isinstance(person, Mapping) and str(person.get("schema", "")) == "sab_character":
                        projected = {"person_id": person_id, "representation": "full_character"}
                        projected.update({key: person.get(key) for key in _COMMAND_SERVICE_FIELDS if key in person})
                        projected.setdefault("life_status", "active")
                        return {
                            "visibility": "player_visible_command_service_sheet",
                            "person": projected,
                            "scope": "Command-relevant service capability only. Private motives, relationships, hidden knowledge, and unrelated personal state remain excluded.",
                        }
        return super().person_sheet(person_id)

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
        return context

    def get_command_contract(self, command_type: str) -> dict[str, Any]:
        if command_type != _MILITARY_ALLEGIANCE_COMMAND:
            return super().get_command_contract(command_type)
        runtime = self.runtime.store.read_json("state/runtime.json")
        wake = runtime.get("pending_wake") if isinstance(runtime, Mapping) else None
        available = not isinstance(wake, Mapping)
        scope = "normal" if available else "pending_wake_response"
        return {
            "command_type": command_type,
            "accepted_payload_keys": sorted(COMMAND_PAYLOAD_KEYS[command_type]),
            "input_guidance": dict(_MILITARY_ALLEGIANCE_GUIDANCE),
            "contested_preview_policy": "outcome_hidden_until_execute",
            "availability": {"available": available, "scope": scope},
            "input_guidance_policy": INPUT_GUIDANCE_POLICY,
        }


__all__ = ["WarfareCampaignOperations"]
