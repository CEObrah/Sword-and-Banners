"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
from sword_runtime.campaign_arrival_lifecycle import reconcile_satisfied_player_campaign_arrivals
from sword_runtime.campaign_command_contact import CampaignCommandContactMixin
from sword_runtime.campaign_command_decision import CampaignCommandDecisionMixin
from sword_runtime.campaign_command_delivery import (
    CampaignCommandDeliveryMixin,
    reconcile_undelivered_campaign_decisions,
    sync_campaign_decision_delivery_routes,
)
from sword_runtime.campaign_command_requests import CampaignCommandRequestMixin
from sword_runtime.campaign_follow_on_order import materialize_reconciled_campaign_follow_on_orders
from sword_runtime.campaign_follow_on_semantics import normalize_current_contact_development_order
from sword_runtime.causal_wait_provenance import CausalWaitProvenanceMixin
from sword_runtime.message_reply_flow import MessageReplyFlowMixin
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin
from sword_runtime.qin_command_support_reconciliation import (
    reconcile_legacy_qin_command_support_state,
    reconcile_overdue_qin_command_support_routes,
)
from sword_runtime.qin_operational_order_guard import QinOperationalOrderGuardMixin
from sword_runtime.reconnaissance import MilitaryReconnaissanceMixin
from sword_runtime.sovereign_campaign_authority_mixin import SovereignCampaignAuthorityMixin
from sword_runtime.time_integration import ProductionTimeIntegrationMixin


class ProductionCampaignPlanner(
    CampaignCommandDeliveryMixin,
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
        # Campaign decision issuance and player receipt are distinct causal facts.
        # Heal any legacy decision that became current before its courier arrived
        # before other campaign reconcilers inspect the operation. Campaign
        # authority reconciliation and superior-command review remain
        # pre-chronology lifecycle work, not alternate chronology owners.
        reconcile_undelivered_campaign_decisions(self)
        refreshed = self._reconcile_campaign_entry_authority()
        reconcile_satisfied_player_campaign_arrivals(self)
        materialize_reconciled_campaign_follow_on_orders(self, refreshed)
        self._sync_campaign_command_decisions()
        normalize_current_contact_development_order(self)
        reconcile_legacy_qin_command_support_state(self)
        # Register every undelivered campaign decision on the existing physical
        # superior-order route. This also removes the obsolete parallel
        # follow-on-review host; the outbound player request already travels in
        # the ordinary upward campaign report.
        sync_campaign_decision_delivery_routes(self)
        super()._prepare_scheduler_for_advance(target_text)
        reconcile_overdue_qin_command_support_routes(self)


__all__ = ["ProductionCampaignPlanner"]
