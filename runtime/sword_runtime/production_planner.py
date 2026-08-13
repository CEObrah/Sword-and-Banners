from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.activity_living_world import ActivityCampaignEventPlanner
from sword_runtime.force_cohort_living_world import ForceCohortLivingWorldMixin
from sword_runtime.house_tang_baselines import HouseTangBaselineMixin
from sword_runtime.house_tang_development import HouseTangDevelopmentMixin

HOUSE_TANG_GARRISON_REF = "loc_tang_manor_garrison_yard"
HOUSE_TANG_GARRISON: dict[str, Any] = {
    "flavor_only": False,
    "fortified": True,
    "functions": ["house", "military", "movement", "supply", "stables", "training"],
    "kind": "garrison",
    "name": "House Tang Garrison and Muster Yard",
    "ref": HOUSE_TANG_GARRISON_REF,
    "state": "qin",
}


class ProductionCampaignPlanner(
    HouseTangBaselineMixin,
    HouseTangDevelopmentMixin,
    ForceCohortLivingWorldMixin,
    ActivityCampaignEventPlanner,
):
    """Production campaign planner with generic force cohorts and House Tang development."""

    def _location_record(self, location_ref: str) -> Mapping[str, Any]:
        if location_ref == HOUSE_TANG_GARRISON_REF:
            return HOUSE_TANG_GARRISON
        return super()._location_record(location_ref)

    def _route_travel_hours(self, origin: str, destination: str, *, modes: tuple[str, ...] = ("horse", "foot")) -> int:
        if origin == destination:
            return 0
        local = lambda ref: ref == "loc_kanyou" or ref.startswith("loc_tang_manor_")
        if local(origin) and local(destination):
            return 1
        return super()._route_travel_hours(origin, destination, modes=modes)


__all__ = ["HOUSE_TANG_GARRISON", "HOUSE_TANG_GARRISON_REF", "ProductionCampaignPlanner"]
