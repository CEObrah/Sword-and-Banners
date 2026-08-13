"""House Tang estate location extensions kept out of residential scene rooms."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.house_tang_campaign import HouseTangCampaignPlanner

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


class HouseTangLocationCampaignPlanner(HouseTangCampaignPlanner):
    """Add the garrison node without treating the Family Hall as a force depot."""

    def _location_record(self, location_ref: str) -> Mapping[str, Any]:
        if location_ref == HOUSE_TANG_GARRISON_REF:
            return HOUSE_TANG_GARRISON
        return super()._location_record(location_ref)


__all__ = [
    "HOUSE_TANG_GARRISON",
    "HOUSE_TANG_GARRISON_REF",
    "HouseTangLocationCampaignPlanner",
]
