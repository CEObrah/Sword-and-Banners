"""Pre-departure causal sequencing for escorted House Tang travel.

A declared escorted departure first settles any already-due House field-service
preparation at the current campaign instant, then lets exact command staff muster
and ordinary travel run. The chronology bridge only synchronizes the staged meta
clock after the command-staff muster phase has lawfully advanced runtime time;
it never repairs or suppresses a pre-existing clock disagreement.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime


class HouseFieldDeparturePreflightMixin:
    """Settle due House departure preparation before formations are snapshotted."""

    def _command_layer_house_field_departure_preflight(self, command: Any, payload: Mapping[str, Any], next_dispatch: Any) -> dict[str, Any]:
        refs = payload.get("formation_refs")
        if (
            command.command_type == "travel"
            and command.actor_id == self.PLAYER_ACTOR
            and isinstance(refs, list)
            and refs
        ):
            player = self.read("state/player.json")
            origin = str(player.get("location", "")) if isinstance(player, Mapping) else ""
            if origin.startswith("loc_tang_manor_"):
                # This intentionally advances zero seconds. It gives the causal
                # scheduler a chance to discover and settle due-at-now House
                # preparation before grouped travel copies formation logistics.
                self._advance_runtime(str(self._world_time()))
        return next_dispatch()


class CommandStaffMusterChronologyMixin:
    """Bridge the two deliberate time phases inside one escorted-travel write."""

    def _muster_escorted_command_staff(
        self,
        command: Any,
        payload: Mapping[str, Any],
        snapshots: list[tuple[str, str, str, str]],
    ) -> dict[str, Any]:
        meta_before = self.read("state/meta.json")
        runtime_before = self.read("state/runtime.json")
        meta_time_before = str(meta_before.get("time", ""))
        runtime_time_before = str(runtime_before.get("world_time", ""))
        if meta_time_before != runtime_time_before:
            # Preserve the existing fail-closed invariant. The underlying
            # implementation will raise the canonical chronology error.
            return super()._muster_escorted_command_staff(command, payload, snapshots)

        result = super()._muster_escorted_command_staff(command, payload, snapshots)
        muster_hours = max(0, int(result.get("hours", 0) or 0))
        if muster_hours <= 0:
            return result

        meta_after = copy.deepcopy(self.read("state/meta.json"))
        runtime_after = self.read("state/runtime.json")
        meta_time_after = str(meta_after.get("time", ""))
        runtime_time_after = str(runtime_after.get("world_time", ""))
        expected_runtime_time = str(
            CampaignTime.parse(meta_time_before).add_seconds(muster_hours * 3600)
        )
        if meta_time_after != meta_time_before:
            raise ValueError("command-staff muster unexpectedly changed campaign meta chronology")
        if runtime_time_after != expected_runtime_time:
            raise ValueError("command-staff muster runtime chronology does not match charged muster time")

        # The muster phase and the subsequent column phase are one semantic
        # travel command. Align the staged campaign clock between those phases
        # without incrementing revision; the ordinary travel reducer performs
        # the one final revision/time commit for the whole command.
        meta_after["time"] = runtime_time_after
        self.put("state/meta.json", meta_after)
        return result


__all__ = [
    "HouseFieldDeparturePreflightMixin",
    "CommandStaffMusterChronologyMixin",
]
