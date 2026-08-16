"""Hosted production planner composition.

The ordinary production planner remains the gameplay authority.  This hosted
wrapper adds only the hidden internal maintenance bundle used by explicit OOC DEV
repairs; it does not add a player command or a second campaign authority.
"""
from sword_runtime.maintenance_bundle import MaintenanceRepairBundleMixin
from sword_runtime.production_planner import ProductionCampaignPlanner as GameplayProductionCampaignPlanner


class ProductionCampaignPlanner(MaintenanceRepairBundleMixin, GameplayProductionCampaignPlanner):
    pass


__all__ = ["ProductionCampaignPlanner"]
