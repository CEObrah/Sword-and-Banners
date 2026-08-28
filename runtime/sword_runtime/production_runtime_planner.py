"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
from sword_runtime.campaign_command_contact_flow import CampaignCommandContactFlowMixin
from sword_runtime.campaign_follow_on_order import materialize_reconciled_campaign_follow_on_orders
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin
from sword_runtime.qin_operational_order_guard import QinOperationalOrderGuardMixin
from sword_runtime.sovereign_campaign_authority_mixin import SovereignCampaignAuthorityMixin
from sword_runtime.time_integration import ProductionTimeIntegrationMixin


class ProductionCampaignPlanner(
    CampaignCommandContactFlowMixin,
    ProductionTimeIntegrationMixin,
    SovereignCampaignAuthorityMixin,
    QinCommandSupportFlowMixin,
    QinOperationalOrderGuardMixin,
    _BaseProductionCampaignPlanner,
):
    """Hosted planner with causal field support, order guarding, and derived strategic supply."""

    def _prepare_scheduler_for_advance(self, target_text: str) -> None:
        # Campaign entry reconciliation and named-superior contact registration
        # are pre-chronology lifecycle work. Neither owns chronology; both finish
        # before delegating to the single production time-integration authority.
        refreshed = self._reconcile_campaign_entry_authority()
        materialize_reconciled_campaign_follow_on_orders(self, refreshed)
        super()._prepare_scheduler_for_advance(target_text)


__all__ = ["ProductionCampaignPlanner"]
