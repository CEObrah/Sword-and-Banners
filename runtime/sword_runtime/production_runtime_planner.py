"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin
from sword_runtime.qin_operational_order_guard import QinOperationalOrderGuardMixin
from sword_runtime.sovereign_campaign_authority_mixin import SovereignCampaignAuthorityMixin
from sword_runtime.time_integration import ProductionTimeIntegrationMixin


class ProductionCampaignPlanner(
    ProductionTimeIntegrationMixin,
    SovereignCampaignAuthorityMixin,
    QinCommandSupportFlowMixin,
    QinOperationalOrderGuardMixin,
    _BaseProductionCampaignPlanner,
):
    """Hosted planner with causal field support, order guarding, and derived strategic supply."""

    def _prepare_scheduler_for_advance(self, target_text: str) -> None:
        # Keep ProductionTimeIntegrationMixin first in the hosted MRO. Campaign
        # authority reconciliation is a pre-chronology lifecycle repair, not an
        # alternate chronology owner, so perform it explicitly before delegating
        # to the single production time-integration implementation.
        self._reconcile_campaign_entry_authority()
        super()._prepare_scheduler_for_advance(target_text)


__all__ = ["ProductionCampaignPlanner"]
