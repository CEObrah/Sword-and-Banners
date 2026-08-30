"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
from collections.abc import Mapping

from sword_runtime.campaign_command_contact import CampaignCommandContactMixin
from sword_runtime.campaign_command_requests import CampaignCommandRequestMixin
from sword_runtime.campaign_follow_on_order import materialize_reconciled_campaign_follow_on_orders
from sword_runtime.geography import shortest_path
from sword_runtime.message_reply_flow import MessageReplyFlowMixin
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin
from sword_runtime.qin_operational_order_guard import QinOperationalOrderGuardMixin
from sword_runtime.reconnaissance import MilitaryReconnaissanceMixin, RECON_HOST_KIND
from sword_runtime.sovereign_campaign_authority_mixin import SovereignCampaignAuthorityMixin
from sword_runtime.time_integration import ProductionTimeIntegrationMixin


class ProductionCampaignPlanner(
    ProductionTimeIntegrationMixin,
    MilitaryReconnaissanceMixin,
    SovereignCampaignAuthorityMixin,
    QinCommandSupportFlowMixin,
    QinOperationalOrderGuardMixin,
    CampaignCommandRequestMixin,
    MessageReplyFlowMixin,
    CampaignCommandContactMixin,
    _BaseProductionCampaignPlanner,
):
    """Hosted planner with causal field support, command/message handoffs, order guarding, and derived strategic supply."""

    def _prepare_scheduler_for_advance(self, target_text: str) -> None:
        # Keep ProductionTimeIntegrationMixin first in the hosted MRO. Campaign
        # authority reconciliation is a pre-chronology lifecycle repair, not an
        # alternate chronology owner, so perform it explicitly before delegating
        # to the single production time-integration implementation. Follow-on
        # order materialization therefore precedes command-request review so a
        # superior response can report the exact current order rather than a stale
        # staging projection.
        refreshed = self._reconcile_campaign_entry_authority()
        materialize_reconciled_campaign_follow_on_orders(self, refreshed)
        super()._prepare_scheduler_for_advance(target_text)

    def _route_travel_hours(
        self,
        origin_ref: str,
        destination_ref: str,
        *,
        modes: tuple[str, ...] | None = None,
    ) -> int:
        """Keep the existing route-helper contract while supporting recon couriers.

        Existing military-career callers pass their exact movement modes. The
        reconnaissance lifecycle is the only caller that omits modes and therefore
        receives the authored courier graph. This avoids changing any existing
        personnel-transfer route semantics.
        """
        route_modes = modes if modes is not None else ("courier",)
        route = shortest_path(self.read, origin_ref, destination_ref, modes=route_modes)
        return int(route["duration_hours"])

    def _deliver_recon_report(
        self,
        process_path: str,
        process: dict[str, object],
        at: str,
        *,
        source_location_ref: str,
        target_location_ref: str,
    ) -> None:
        """Complete the generic information-delivery contract for recon reports."""
        travel_hours = (
            0
            if source_location_ref == target_location_ref
            else self._route_travel_hours(
                source_location_ref,
                target_location_ref,
                modes=("courier",),
            )
        )
        MilitaryReconnaissanceMixin._deliver_recon_report(
            self,
            process_path,
            process,
            at,
            source_location_ref=source_location_ref,
            target_location_ref=target_location_ref,
        )
        information_ref = process.get("report_information_ref")
        if not isinstance(information_ref, str) or not information_ref:
            raise ValueError("military reconnaissance delivery lost its information ref")
        info_index = self.read("state/information/index.json")
        info_path = info_index.get("claims", {}).get(information_ref) if isinstance(info_index, Mapping) else None
        if not isinstance(info_path, str):
            raise ValueError("military reconnaissance delivery lost its information owner")
        info = dict(self.read(info_path))
        deliveries = info.get("deliveries")
        if not isinstance(deliveries, list) or not deliveries or not isinstance(deliveries[-1], dict):
            raise ValueError("military reconnaissance delivery record is missing")
        deliveries[-1]["travel_hours"] = int(travel_hours)
        self.put(info_path, info)

    def _run_due_host(self, host: Mapping[str, object], due_text: str) -> None:
        """Extend the hosted due-host hook without creating a second time loop."""
        if str(host.get("kind", "")) == RECON_HOST_KIND:
            self._settle_military_reconnaissance_host(host, due_text)
            # Reconnaissance reports are ordinary delivered information events,
            # not hard decision wakes. Event-bounded waits stop on the exact
            # delivered causal event when the caller requested that operation.
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)


__all__ = ["ProductionCampaignPlanner"]
