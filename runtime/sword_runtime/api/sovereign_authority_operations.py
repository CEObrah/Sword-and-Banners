"""Player-safe projection of sovereign campaign-entry authority.

This layer corrects stale staging language without mutating campaign state during a
read.  Exact operations and orders remain authority.  When the same exact sovereign
campaign order already establishes lawful hostile entry, the player surface must not
continue advertising a second nonexistent war/entry authorization gate.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Optional

from sword_runtime.api.campaign_planning_operations import CampaignPlanningAwareOperations
from sword_runtime.api.operations import OperationError
from sword_runtime.deployment_attestation import deployment_attestation
from sword_runtime.sovereign_campaign_authority import operation_entry_projection


class SovereignAuthorityAwareOperations(CampaignPlanningAwareOperations):
    """Keep bounded operation and deployment handoffs aligned with exact authority."""

    def _controlled_operation_views(self, controlled_refs: set[str]) -> list[dict[str, Any]]:
        views = super()._controlled_operation_views(controlled_refs)
        try:
            operation_index = self.store.read_json("state/operations/index.json")
        except (FileNotFoundError, ValueError):
            return views
        paths = operation_index.get("operations", {}) if isinstance(operation_index, Mapping) else {}
        for view in views:
            operation_ref = view.get("operation_ref")
            path = paths.get(operation_ref) if isinstance(paths, Mapping) else None
            if not isinstance(path, str):
                continue
            try:
                operation = self.store.read_json(path)
            except (FileNotFoundError, ValueError):
                continue
            if not isinstance(operation, Mapping):
                continue
            campaign_context = view.get("campaign_context") if isinstance(view.get("campaign_context"), Mapping) else None
            authority = operation_entry_projection(self.runtime.planner, operation, campaign_context)
            if not isinstance(authority, Mapping) or authority.get("authorized") is not True:
                continue

            # Do not falsify the saved historical packet.  Surface the effective
            # legal state beside it and correct only fields whose old value claimed
            # that hostile entry itself was forbidden.  A separate exact march or
            # tactical order may still be required by the campaign command chain.
            view["entry_status"] = "authorized"
            view["entry_authority"] = copy.deepcopy(dict(authority))
            if str(view.get("campaign_phase", "")) == "awaiting_entry_authority":
                view["campaign_phase"] = "awaiting_march_orders"
                view["campaign_phase_projection_only"] = True
            if str(view.get("order_status", "")) == "awaiting_entry_authority":
                view["order_status"] = "awaiting_march_orders"
                view["order_status_projection_only"] = True

            context = copy.deepcopy(dict(campaign_context)) if isinstance(campaign_context, Mapping) else {}
            area = context.get("operational_area") if isinstance(context.get("operational_area"), Mapping) else {}
            area = copy.deepcopy(dict(area))
            area["hostile_entry_authorized"] = True
            area["entry_status"] = "authorized"
            area["entry_authority_basis"] = authority.get("basis")
            context["operational_area"] = area
            view["campaign_context"] = context

            current_order = view.get("current_operational_order")
            if isinstance(current_order, Mapping):
                current_order = copy.deepcopy(dict(current_order))
                packet = current_order.get("mission_packet")
                if isinstance(packet, Mapping):
                    packet = copy.deepcopy(dict(packet))
                    packet["hostile_entry_authorized"] = True
                    packet["entry_status"] = "authorized"
                    packet["entry_authority_basis"] = authority.get("basis")
                    current_order["mission_packet"] = packet
                current_order["effective_entry_authority"] = copy.deepcopy(dict(authority))
                if str(current_order.get("status", "")) == "staged_awaiting_entry_authority":
                    current_order["historical_staging_status"] = current_order.get("status")
                    current_order["status"] = "completed_staging_entry_now_authorized"
                    current_order["status_projection_only"] = True
                view["current_operational_order"] = current_order

            campaign_command = view.get("campaign_command")
            if isinstance(campaign_command, Mapping):
                campaign_command = copy.deepcopy(dict(campaign_command))
                campaign_command["entry_authority"] = copy.deepcopy(dict(authority))
                campaign_command["stale_entry_hold_rule"] = (
                    "Any older directive whose only blocker is missing war/entry authority is no longer a current legal-entry block. "
                    "Exact march sequence, command assignment, and tactical orders remain separate authorities."
                )
                view["campaign_command"] = campaign_command
        return views

    def play_context(self) -> dict[str, Any]:
        context = super().play_context()
        authorized = [
            row for row in context.get("controlled_operations", [])
            if isinstance(row, Mapping)
            and isinstance(row.get("entry_authority"), Mapping)
            and row["entry_authority"].get("authorized") is True
        ]
        if authorized:
            guidance = context.setdefault("narration_guidance", {})
            guidance["campaign_entry_authority"] = (
                "When a controlled operation exposes entry_authority.authorized=true, do not narrate a need for another war declaration or hostile-entry authorization. "
                "Older staging packets/directives may be historical remnants of the prior gate. A distinct march, formation assignment, tactical order, ceasefire, treaty, or war-termination decision must still come from its own authority."
            )
        return context

    def ooc_audit(self, focus: Optional[str] = None, observations: Optional[list[str]] = None) -> dict[str, Any]:
        result = super().ooc_audit(focus, observations)
        result["deployment"] = deployment_attestation(self.runtime.root)
        return result

    def execute_command(self, command):
        try:
            return super().execute_command(command)
        except OperationError as exc:
            # An old service discovers a deploy-relevant main revision during
            # remote-durability preflight before it can mutate campaign truth.
            # Translate that specific operational condition into actionable UX
            # rather than making a healthy campaign look generically broken.
            if exc.code == "transaction_remote_durability_failed":
                attestation = deployment_attestation(self.runtime.root)
                if attestation.get("deployment_required") is True:
                    raise OperationError(503, "deployment_required") from exc
            raise


__all__ = ["SovereignAuthorityAwareOperations"]
