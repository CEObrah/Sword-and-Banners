"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
from sword_runtime.campaign_arrival_lifecycle import reconcile_satisfied_player_campaign_arrivals
from sword_runtime.campaign_command_contact import CampaignCommandContactMixin
from sword_runtime.campaign_command_decision import CampaignCommandDecisionMixin
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
        # repair first, then reconcile arrival through the existing physical
        # formation-location authority before a historical zero-distance packet
        # can suppress the field command cycle again. Let campaign command create
        # any bounded mission-level follow-on, canonicalize that mission so
        # completed-arrival metadata cannot bleed into its semantics, normalize
        # legacy Qin command-support routing/pointers, and only then let the normal
        # scheduler register its existing delivery paths. Once those routes exist,
        # catch recovered automatic briefings up to the original order timeline.
        refreshed = self._reconcile_campaign_entry_authority()
        reconcile_satisfied_player_campaign_arrivals(self)
        materialize_reconciled_campaign_follow_on_orders(self, refreshed)
        self._sync_campaign_command_decisions()
        normalize_current_contact_development_order(self)
        reconcile_legacy_qin_command_support_state(self)
        super()._prepare_scheduler_for_advance(target_text)
        reconcile_overdue_qin_command_support_routes(self)


__all__ = ["ProductionCampaignPlanner"]
