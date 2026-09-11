"""Player-safe standing-training command surface.

The command never accepts hours or focuses. It can target only Tang Wei or an
exact controlled formation, and the production planner consumes only already
persisted whole-hour standing-training credit.
"""
from __future__ import annotations

from collections.abc import Mapping

from sword_runtime.api.command_staff_routing_operations import RoutedCommandStaffAwareCampaignOperations


class StandingTrainingCampaignOperations(RoutedCommandStaffAwareCampaignOperations):
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
                "focus_rule": (
                    "caller-supplied focuses are forbidden. Saved formation training_ref, troop role and officer billet "
                    "resolve one finite registered deterministic program. Fixed drill weights and registered skill/attribute "
                    "targets own gains; current stats and narration never choose future development."
                ),
                "officer_chain_rule": (
                    "Internal person-lite 1,000/500 officers are reclassified fighting-establishment bodies, so the same formation drill window "
                    "develops them persistently. Full-character commanders and deputies keep their own autonomous activity/training contracts "
                    "and therefore do not receive a duplicate copy of the formation settlement. Tang Wei's development remains controlled by his saved personal standing plan."
                ),
                "time_rule": "settlement advances no campaign time",
                "npc_rule": (
                    "This command cannot target an autonomous NPC directly. Exact NPC training settles only through that person's saved autonomous activity owner."
                ),
            },
            "contested_preview_policy": "deterministic_server_owned_credit_only",
        }
        commands["command_types"] = command_types
        commands["supported_command_types"] = sorted(command_types)
        return context


__all__ = ["StandingTrainingCampaignOperations"]
