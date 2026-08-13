from __future__ import annotations

from sword_runtime.activity_living_world import ActivityCampaignEventPlanner
from sword_runtime.force_cohort_living_world import ForceCohortLivingWorldMixin
from sword_runtime.house_tang_development import HouseTangDevelopmentMixin


class ProductionCampaignPlanner(
    HouseTangDevelopmentMixin,
    ForceCohortLivingWorldMixin,
    ActivityCampaignEventPlanner,
):
    """Production campaign planner with generic force cohorts and House Tang development."""


__all__ = ["ProductionCampaignPlanner"]
