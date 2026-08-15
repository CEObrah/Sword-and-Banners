"""Player-safe standing-training command surface.

The command never accepts hours or focuses. It can target only Tang Wei or an
exact controlled formation, and the production planner consumes only already
persisted whole-hour standing-training credit.
"""
from __future__ import annotations

from collections.abc import Mapping

from sword_runtime.api.command_staff_operations import CommandStaffAwareCampaignOperations


class StandingTrainingCampaignOperations(CommandStaffAwareCampaignOperations):
    """Expose zero-time reconciliation of server-owned standing-training credit."""

    def play_context(self):
        context = super().play_context()
        commands = context.setdefault("commands", {})
        command_types = dict(commands.get("command_types", {}))
        command_types["standing_training_settle"] = {
            "accepted_payload_keys": ["target_ref"],
            "input_guidance": {
                "target_ref": {
                    "rule": (
                        "use Tang Wei's exact player_id or one exact controlled formation_ref; "
                        "the runtime consumes only already-earned whole-hour standing-training credit"
                    )
                },
                "hours_rule": "caller-supplied hours are forbidden",
                "focus_rule": "caller-supplied focuses are forbidden; saved standing plans and registered formation regimens remain authoritative",
                "time_rule": "settlement advances no campaign time",
                "npc_rule": "exact autonomous NPC training cannot be settled by this player command",
            },
            "contested_preview_policy": "deterministic_server_owned_credit_only",
        }
        commands["command_types"] = command_types
        commands["supported_command_types"] = sorted(command_types)
        return context


__all__ = ["StandingTrainingCampaignOperations"]
