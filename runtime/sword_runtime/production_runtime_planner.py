"""Hosted production planner composition.

The current production planner is the single hosted gameplay authority.
"""
from sword_runtime.production_planner import ProductionCampaignPlanner as _BaseProductionCampaignPlanner
from sword_runtime.qin_command_support_flow import QinCommandSupportFlowMixin


class ProductionCampaignPlanner(QinCommandSupportFlowMixin, _BaseProductionCampaignPlanner):
    """Hosted planner with causally routed post-assumption Qin command support."""


__all__ = ["ProductionCampaignPlanner"]
