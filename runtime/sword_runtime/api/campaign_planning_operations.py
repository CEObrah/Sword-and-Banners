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

_INTERACTION_ATTEMPT_LEDGER_PATH = "state/index/interaction-attempts.json"


class CampaignPlanningAwareOperations(WarfareCampaignOperations):
    """Expose current safe campaign planning beside immutable briefing history."""

    def _stabilize_same_time_attempt_order(self, context: dict[str, Any]) -> None:
        """Prefer persisted ledger order to hash order for public recent attempts.

        Interaction attempts consume zero campaign time, so multiple attempts may
        share one timestamp. The lower-level bounded reader uses event identity as
        a deterministic tie-breaker, but a hash is not causal chronology. The
        routing ledger already preserves insertion order within its retained
        unresolved/recent buckets; use that bounded order for the public hot list
        without changing the persisted ledger or claiming a world outcome.
        """
        attempts = context.get("recent_interaction_attempts")
        if not isinstance(attempts, list) or len(attempts) < 2:
            return
        try:
            ledger = self.store.read_json(_INTERACTION_ATTEMPT_LEDGER_PATH)
        except (FileNotFoundError, KeyError, ValueError):
            return
        raw_rows = ledger.get("attempts") if isinstance(ledger, Mapping) else None
        if not isinstance(raw_rows, list):
            return
        positions = {
            str(row.get("event_id")): index
            for index, row in enumerate(raw_rows)
            if isinstance(row, Mapping) and isinstance(row.get("event_id"), str)
        }
        if not positions:
            return
        context["recent_interaction_attempts"] = sorted(
            attempts,
            key=lambda row: positions.get(str(row.get("event_id")), -1)
            if isinstance(row, Mapping) else -1,
            reverse=True,
        )

    def play_context(self) -> dict[str, Any]:
        context = super().play_context()
        self._stabilize_same_time_attempt_order(context)
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
