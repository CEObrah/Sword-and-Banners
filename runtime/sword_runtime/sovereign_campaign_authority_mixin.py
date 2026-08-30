"""Production planner compatibility and lifecycle for sovereign campaign authority.

The persisted sovereign document is not rewritten merely because it is read. Reads
of core-state owners receive a bounded derived ``war_intents`` compatibility row
only when an exact state-issued active foreign campaign order already establishes
equivalent entry authority. Existing movement and campaign-law consumers can use
their normal sovereign checks without each inventing a special exception.

Before chronology advances, a campaign that completed friendly staging while this
authority was previously invisible is deterministically reopened into its next
lawful mission packet. This is not a second sovereign decision: it is lifecycle
reconciliation of the already-issued exact campaign order.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.operation_routing import iter_exact_operation_records

from sword_runtime.sovereign_campaign_authority import (
    hostile_entry_authorized,
    project_sovereign_document,
)


class SovereignCampaignAuthorityMixin:
    """Project and reconcile exact-order-derived foreign campaign authority."""

    @staticmethod
    def _state_ref_from_path(path: str) -> str | None:
        prefix = "state/states/"
        suffix = ".json"
        if not isinstance(path, str) or not path.startswith(prefix) or not path.endswith(suffix):
            return None
        key = path[len(prefix):-len(suffix)]
        if not key or "/" in key:
            return None
        return f"state_{key}"

    def read(self, path: str) -> Any:
        parent_read = super().read
        raw = parent_read(path)
        state_ref = self._state_ref_from_path(path)
        if state_ref is None or not isinstance(raw, Mapping):
            return raw
        # Pass the raw parent reader into the projection helper. Using self.read
        # here would recurse back through this mixin while the helper inspects
        # operations and the saved sovereign owner.
        return project_sovereign_document(parent_read, state_ref, raw)

    def read_optional(self, path: str) -> Any:
        try:
            return self.read(path)
        except (FileNotFoundError, KeyError):
            return None

    @staticmethod
    def _operation_target_state(operation: Mapping[str, Any], owner_ref: str) -> str | None:
        for ref in operation.get("objective_refs", []) if isinstance(operation.get("objective_refs"), list) else []:
            if isinstance(ref, str) and ref.startswith("state_") and ref != owner_ref:
                return ref
        orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
        for row in reversed(orders):
            if not isinstance(row, Mapping):
                continue
            for key in ("target_state_ref", "strategic_pressure_target_ref", "target_ref"):
                ref = row.get(key)
                if isinstance(ref, str) and ref.startswith("state_") and ref != owner_ref:
                    return ref
        return None

    def _reconcile_campaign_entry_authority(self) -> list[str]:
        """Refresh completed staging packets whose sovereign entry gate is now met.

        The mission-packet builder owns the transition from completed friendly
        staging to a newly actionable campaign-advance packet. Running it only at
        a chronology command boundary keeps reads mutation-free and makes the
        repair idempotent for old saves.
        """
        from sword_runtime.campaign_briefing import (
            build_campaign_dossier,
            ensure_actionable_mission_packet,
        )

        try:
            runtime = self.read("state/runtime.json")
        except (FileNotFoundError, KeyError, ValueError):
            return []
        at = runtime.get("world_time") if isinstance(runtime, Mapping) else None
        if not isinstance(at, str):
            return []

        refreshed: list[str] = []
        for operation_ref, _path, operation in iter_exact_operation_records(self):
            if str(operation.get("status", "")) not in {"planned", "mobilizing", "active", "advancing", "engaged", "occupied"}:
                continue
            waiting = (
                str(operation.get("campaign_phase", "")) == "awaiting_entry_authority"
                or str(operation.get("order_status", "")) == "awaiting_entry_authority"
            )
            orders = operation.get("operational_orders") if isinstance(operation.get("operational_orders"), list) else []
            latest = next((row for row in reversed(orders) if isinstance(row, Mapping)), None)
            if isinstance(latest, Mapping) and str(latest.get("status", "")) == "staged_awaiting_entry_authority":
                waiting = True
            if not waiting:
                continue
            owner_ref = str(
                operation.get("institutional_owner_ref")
                or operation.get("administrative_authority")
                or ""
            )
            if not owner_ref.startswith("state_"):
                continue
            target_ref = self._operation_target_state(operation, owner_ref)
            if not target_ref or not hostile_entry_authorized(self, owner_ref, target_ref):
                continue

            dossier = build_campaign_dossier(self, operation_ref)
            packet = ensure_actionable_mission_packet(self, operation_ref, dossier, at=at)
            if isinstance(packet, Mapping) and packet.get("hostile_entry_authorized") is True:
                refreshed.append(operation_ref)
        return refreshed

    def _prepare_scheduler_for_advance(self, target_text: str) -> None:
        # Resolve the legal campaign lifecycle before route/briefing/command-cycle
        # registration inspects the operation. The parent chronology method then
        # sees the new exact mission packet in the same atomic command.
        self._reconcile_campaign_entry_authority()
        super()._prepare_scheduler_for_advance(target_text)


__all__ = ["SovereignCampaignAuthorityMixin"]
