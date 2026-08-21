"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
Persistent player routines are resolved here from saved Runtime state so callers
need only declare changes/overrides; they do not have to replay standing policy on
every time-advance command. Global NPC/House/state/force/world activity remains
owned by the ordinary causal scheduler beneath the planner.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner


class ProductionCampaignPlanner(_BaseProductionCampaignPlanner):
    """Hosted planner with Runtime-owned persistent player activity defaults."""

    def _policy(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve explicit downtime overrides over Tang Wei's saved routine.

        ``activity_policy`` remains useful for temporary overrides and explicit
        formation/household activity.  Omission no longer means that a persisted
        automatic Tang Wei routine disappears for that interval.
        """
        policy = super()._policy(payload)
        if "player_standing_training" in policy:
            return policy

        player = self.read("state/player.json")
        contract = (
            player.get("activity_contract")
            if isinstance(player, Mapping) and isinstance(player.get("activity_contract"), Mapping)
            else {}
        )
        if contract.get("auto_settle_standing_training") is True:
            policy["player_standing_training"] = True
        return policy


__all__ = ["ProductionCampaignPlanner"]
