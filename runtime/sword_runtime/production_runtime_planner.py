"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
from sword_runtime.formation_subsistence import FormationSubsistenceFlowMixin
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin


class ProductionCampaignPlanner(
    FormationSubsistenceFlowMixin,
    QinCommandSupportFlowMixin,
    _BaseProductionCampaignPlanner,
):
    """Hosted planner with causal field support and continuous formation subsistence."""


__all__ = ["ProductionCampaignPlanner"]
