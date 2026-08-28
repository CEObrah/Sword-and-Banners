"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
import copy

from sword_runtime.campaign_command_contact_flow import CampaignCommandContactFlowMixin
from sword_runtime.campaign_follow_on_order import materialize_reconciled_campaign_follow_on_orders
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin
from sword_runtime.qin_operational_order_guard import QinOperationalOrderGuardMixin
from sword_runtime.sovereign_campaign_authority_mixin import SovereignCampaignAuthorityMixin
from sword_runtime.time_integration import ProductionTimeIntegrationMixin


class ProductionCampaignPlanner(
    ProductionTimeIntegrationMixin,
    CampaignCommandContactFlowMixin,
    SovereignCampaignAuthorityMixin,
    QinCommandSupportFlowMixin,
    QinOperationalOrderGuardMixin,
    _BaseProductionCampaignPlanner,
):
    """Hosted planner with causal field support, order guarding, and derived strategic supply."""

    def _prepare_scheduler_for_advance(self, target_text: str) -> None:
        # Keep ProductionTimeIntegrationMixin first in the hosted MRO. Campaign
        # entry reconciliation and named-superior contact registration are
        # pre-chronology lifecycle work, not alternate chronology owners.
        refreshed = self._reconcile_campaign_entry_authority()
        materialize_reconciled_campaign_follow_on_orders(self, refreshed)
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        if self._sync_campaign_command_contact_routes(runtime):
            self.put("state/runtime.json", runtime)
        super()._prepare_scheduler_for_advance(target_text)


__all__ = ["ProductionCampaignPlanner"]
