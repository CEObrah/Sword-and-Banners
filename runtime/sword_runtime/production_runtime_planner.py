"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
from sword_runtime.campaign_command_contact import CampaignCommandContactMixin
from sword_runtime.campaign_command_decision import CampaignCommandDecisionMixin
from sword_runtime.campaign_command_requests import CampaignCommandRequestMixin
from sword_runtime.campaign_follow_on_order import materialize_reconciled_campaign_follow_on_orders
from sword_runtime.causal_wait_provenance import CausalWaitProvenanceMixin
from sword_runtime.message_reply_flow import MessageReplyFlowMixin
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin
from sword_runtime.qin_operational_order_guard import QinOperationalOrderGuardMixin
from sword_runtime.reconnaissance import MilitaryReconnaissanceMixin
from sword_runtime.sovereign_campaign_authority_mixin import SovereignCampaignAuthorityMixin
from sword_runtime.time_integration import ProductionTimeIntegrationMixin


class ProductionCampaignPlanner(
    ProductionTimeIntegrationMixin,
    CausalWaitProvenanceMixin,
    MilitaryReconnaissanceMixin,
    SovereignCampaignAuthorityMixin,
    QinCommandSupportFlowMixin,
    QinOperationalOrderGuardMixin,
    CampaignCommandDecisionMixin,
    CampaignCommandRequestMixin,
    MessageReplyFlowMixin,
    CampaignCommandContactMixin,
    _BaseProductionCampaignPlanner,
):
    """Hosted planner with causal field support, command/message handoffs, order guarding, and derived strategic supply."""

    def _prepare_scheduler_for_advance(self, target_text: str) -> None:
        # Keep ProductionTimeIntegrationMixin first in the hosted MRO. Campaign
        # authority reconciliation and superior-command review are pre-chronology
        # lifecycle work, not alternate chronology owners. Materialize any entry
        # repair first, then let the one campaign decision owner forward newly
        # known command intelligence and persist a bounded mission-level follow-on
        # before the normal scheduler registers its existing delivery path.
        refreshed = self._reconcile_campaign_entry_authority()
        materialize_reconciled_campaign_follow_on_orders(self, refreshed)
        self._sync_campaign_command_decisions()
        super()._prepare_scheduler_for_advance(target_text)


__all__ = ["ProductionCampaignPlanner"]
