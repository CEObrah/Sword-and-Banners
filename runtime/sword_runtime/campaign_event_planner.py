"""Production planner layer for short-horizon campaign event work and world arcs.

One-shot campaign work and recurring world-arc pressure share the existing
chronological causal frontier. Exact event owners become truth only when their
runtime host settles.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.autonomy_routing import select_formations_fair
from sword_runtime.player_group_actions import PlayerGroupActionPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.systems.campaign_events import (
    settle_campaign_work_target,
    sync_campaign_work_routes,
)
from sword_runtime.world_arcs import (
    settle_world_arc_report,
    settle_world_arc_review,
    sync_world_arc_routes,
)

_RUNTIME_PATH = "state/runtime.json"


class CampaignEventPlayerGroupActionPlanner(PlayerGroupActionPlanner):
    """Hosted planner with recurring world arcs and resumable event wakes."""

    @staticmethod
    def _is_campaign_event_wake(wake: Mapping[str, Any] | None) -> bool:
        return isinstance(wake, Mapping) and wake.get("kind") == "campaign_event"

    def _select_formations(
        self,
        state: str,
        objective_text: str,
        memory: dict[str, Any],
        *,
        reserved: set[str],
        count: int = 2,
    ) -> list[str]:
        return select_formations_fair(
            self,
            state,
            objective_text,
            memory,
            reserved=reserved,
            count=count,
        )

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        sync_world_arc_routes(self, runtime)
        sync_campaign_work_routes(self, runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        kind = host.get("kind")
        if kind == "world_arc":
            settle_world_arc_review(self, host, due_text)
            self._pending_wake_created = None
            return
        if kind == "world_arc_report":
            wake = settle_world_arc_report(self, host, due_text)
            if wake is not None:
                wake["target_host"] = self._active_host_id
                wake["event_id"] = self._active_event_id
            self._pending_wake_created = wake
            return
        if kind != "campaign_event":
            super()._run_due_host(host, due_text)
            return
        wake = settle_campaign_work_target(self, host, due_text)
        if wake is not None:
            wake["target_host"] = self._active_host_id
            wake["event_id"] = self._active_event_id
        self._pending_wake_created = wake

    def _resume_pending_wake(self, runtime: dict[str, Any]) -> dict[str, Any] | None:
        wake = self._pending_wake(runtime)
        if not self._is_campaign_event_wake(wake):
            return super()._resume_pending_wake(runtime)
        if self._active_command_type != "advance_time":
            return wake

        current = CampaignTime.parse(str(runtime["world_time"]))
        acknowledged = dict(wake)
        acknowledged["acknowledged_at"] = str(current)
        acknowledged["resumed_for"] = "campaign_event_one_shot"
        runtime["acknowledged_wake"] = acknowledged
        runtime.pop("pending_wake", None)
        return None

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        runtime = self.read(_RUNTIME_PATH)
        pending = self._pending_wake(runtime)
        if self._is_campaign_event_wake(pending) and command.command_type != "advance_time":
            updated = copy.deepcopy(runtime)
            current = CampaignTime.parse(str(updated["world_time"]))
            acknowledged = dict(pending)
            acknowledged["acknowledged_at"] = str(current)
            acknowledged["resumed_for"] = command.command_type
            updated["acknowledged_wake"] = acknowledged
            updated.pop("pending_wake", None)
            self.put(_RUNTIME_PATH, updated)
        return super()._dispatch(command, payload)


__all__ = ["CampaignEventPlayerGroupActionPlanner"]
