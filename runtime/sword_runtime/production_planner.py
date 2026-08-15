from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.activity_living_world import ActivityCampaignEventPlanner
from sword_runtime.civil_world import CivilWorldMixin
from sword_runtime.equipment_planner import EquipmentStateProjectionMixin
from sword_runtime.force_cohort_living_world import ForceCohortLivingWorldMixin
from sword_runtime.house_tang_development import HouseTangDevelopmentMixin
from sword_runtime.sim.calendar import CampaignTime

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
    EquipmentStateProjectionMixin,
    CivilWorldMixin,
    HouseTangDevelopmentMixin,
    ForceCohortLivingWorldMixin,
    ActivityCampaignEventPlanner,
):
    """Production campaign planner with generic force cohorts and House Tang development."""

    _interruptible_personal_travel = False

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

    def _find_route(self, origin: str, destination: str, *, mode: str | None = None) -> Mapping[str, Any]:
        """Honor the production local-route graph for ordinary personal movement.

        The base reducer historically asks for one exact route edge. House Tang
        interiors and the garrison are registered production locations connected
        by the local route graph instead, so a lawful walk between them must not
        fail merely because no duplicate room-to-room edge exists in routes.json.
        Exact authored edges remain preferred; only foot/horse movement inside the
        Kanyou/Tang-manor local envelope falls back to the derived graph.
        """

        try:
            return super()._find_route(origin, destination, mode=mode)
        except ValueError:
            local = lambda ref: ref == "loc_kanyou" or ref.startswith("loc_tang_manor_")
            if mode not in {"foot", "horse"} or not (local(origin) and local(destination)):
                raise
            duration = self._route_travel_hours(origin, destination, modes=(str(mode),))
            return {
                "ref": "derived_route_graph",
                "a": origin,
                "b": destination,
                "modes": [str(mode)],
                "duration_hours": duration,
            }

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        """Let personal travel persist a real wake instead of previewing it forever.

        The causal scheduler normally permits only ``advance_time`` to commit a
        newly reached high-salience wake. During one unescorted personal travel
        reducer we temporarily give only the scheduler that permission. The
        outer travel adapter below rolls back the travel after-image only when
        the scheduler actually stops before arrival, while preserving the
        committed causal time and wake. Escorted travel does not use this adapter
        and remains fail-closed.
        """

        if self._interruptible_personal_travel and self._active_command_type == "travel":
            previous = self._active_command_type
            self._active_command_type = "advance_time"
            try:
                return super()._advance_runtime(target_text)
            finally:
                self._active_command_type = previous
        return super()._advance_runtime(target_text)

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        personal_travel = command.command_type == "travel" and not payload.get("formation_refs")
        if not personal_travel:
            return super()._dispatch(command, payload)

        # Existing wakes retain their normal response restrictions. This adapter
        # is only for a wake first reached while an otherwise legal personal
        # journey is consuming time.
        runtime_before = self.read("state/runtime.json")
        if isinstance(runtime_before.get("pending_wake"), Mapping):
            return super()._dispatch(command, payload)

        player_before = copy.deepcopy(self.read("state/player.json"))
        manifest_before = copy.deepcopy(self.read("state/player-detail/equipment-manifest.json"))
        previous_flag = self._interruptible_personal_travel
        self._interruptible_personal_travel = True
        try:
            result = super()._dispatch(command, payload)
        finally:
            self._interruptible_personal_travel = previous_flag

        if not (bool(result.get("interrupted")) and bool(result.get("wake_required"))):
            result["travel_completed"] = True
            return result

        runtime_after = self.read("state/runtime.json")
        actual_time = str(runtime_after["world_time"])
        requested_arrival = str(result.get("world_time", actual_time))
        result["requested_arrival_time"] = requested_arrival
        result["interrupted_at"] = actual_time

        # A wake exactly at the journey endpoint does not interrupt movement: the
        # full travel duration has already elapsed, so preserve the base reducer's
        # destination and equipment after-image while still surfacing the wake.
        if CampaignTime.parse(actual_time) >= CampaignTime.parse(requested_arrival):
            result["world_time"] = actual_time
            result["travel_completed"] = True
            return result

        # For an earlier wake, restore player-controlled travel after-images while
        # keeping the runtime wake and exact reached time that caused interruption.
        self.put("state/player.json", player_before)
        self.put("state/player-detail/equipment-manifest.json", manifest_before)
        self._write_meta(command, actual_time)

        result["world_time"] = actual_time
        result["travel_completed"] = False
        result["current_location"] = str(player_before.get("location", ""))
        return result


__all__ = ["HOUSE_TANG_GARRISON", "HOUSE_TANG_GARRISON_REF", "ProductionCampaignPlanner"]
