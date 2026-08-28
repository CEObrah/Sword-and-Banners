"""Live read-only campaign-planning projection for API play context.

Historical briefing claims remain historical snapshots.  This adapter augments
current campaign-command views with the campaign planner's present player-safe
staff projection so campaigns created before later planning features were added
do not remain permanently starved of current objectives, hierarchy, routes, and
capacity constraints.

The overlay is read-only.  It does not rewrite the saved briefing, issue orders,
move formations, authorize hostile entry, transfer troop ownership, or advance
campaign time.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.warfare_operations import WarfareCampaignOperations
from sword_runtime.campaign_briefing import build_campaign_dossier


class CampaignPlanningAwareOperations(WarfareCampaignOperations):
    """Expose current safe campaign planning beside immutable briefing history."""

    def play_context(self) -> dict[str, Any]:
        context = super().play_context()
        planner = getattr(self.runtime, "planner", None)
        if planner is None:
            return context

        controlled = context.get("controlled_operations")
        if not isinstance(controlled, list):
            return context

        for operation in controlled:
            if not isinstance(operation, dict):
                continue
            operation_ref = operation.get("operation_ref")
            campaign_command = operation.get("campaign_command")
            if not isinstance(operation_ref, str) or not operation_ref:
                continue
            if not isinstance(campaign_command, dict):
                continue

            try:
                dossier = build_campaign_dossier(planner, operation_ref)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            planning = dossier.get("march_planning")
            if not isinstance(planning, Mapping):
                continue

            campaign_command["march_planning"] = copy.deepcopy(dict(planning))
            campaign_command["march_planning_projection"] = {
                "status": "current_read_only_projection",
                "historical_briefing_unchanged": True,
                "authority_rule": (
                    "current planning projection only; it does not rewrite the historical briefing, issue an order, move a formation, authorize hostile entry, transfer troop ownership, or advance campaign time"
                ),
            }

        return context


__all__ = ["CampaignPlanningAwareOperations"]
