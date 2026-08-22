"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
from sword_runtime.formation_subsistence import FormationSubsistenceFlowMixin
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin
from sword_runtime.qin_operational_order_guard import QinOperationalOrderGuardMixin


class ProductionCampaignPlanner(
    FormationSubsistenceFlowMixin,
    QinCommandSupportFlowMixin,
    QinOperationalOrderGuardMixin,
    _BaseProductionCampaignPlanner,
):
    """Hosted planner with causal field support, order guarding, and continuous formation subsistence."""


__all__ = ["ProductionCampaignPlanner"]
