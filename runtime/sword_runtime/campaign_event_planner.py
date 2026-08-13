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

    @classmethod
    def _clear_completed_campaign_event_ack(cls, runtime: dict[str, Any]) -> None:
        """Remove one-shot campaign-event acknowledgement after its handoff is served."""
        acknowledged = runtime.get("acknowledged_wake")
        if cls._is_campaign_event_wake(acknowledged):
            runtime.pop("acknowledged_wake", None)

    @staticmethod
    def _defer_new_world_arc_routes(runtime: dict[str, Any], previous_host_ids: set[str]) -> None:
        """Start newly discovered cold world arcs on their first normal review interval.

        Route discovery is bookkeeping, not an in-world occurrence. Existing arc
        hosts keep their exact due times; only hosts first registered at the current
        campaign instant are baselined to now and scheduled one recurrence later.
        """
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        current_text = runtime.get("world_time")
        if not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(current_text, str):
            raise ValueError("runtime causal queue is invalid")
        current = CampaignTime.parse(current_text)
        deferred: set[str] = set()
        for host_id, host in hosts.items():
            if host_id in previous_host_ids or not isinstance(host_id, str) or not isinstance(host, dict):
                continue
            if host.get("kind") != "world_arc" or host.get("next_due") != current_text:
                continue
            recurrence = host.get("recurrence_seconds")
            if isinstance(recurrence, bool) or not isinstance(recurrence, int) or recurrence <= 0:
                raise ValueError("world arc host recurrence is invalid")
            first_due = current.add_seconds(recurrence)
            host["resolved_through"] = current_text
            host["safe_through"] = str(first_due.add_seconds(-1))
            host["next_due"] = str(first_due)
            deferred.add(host_id)
        if not deferred:
            return
        routed: set[str] = set()
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("runtime event is invalid")
            host_id = event.get("target_host")
            if host_id not in deferred:
                continue
            event["due_at"] = hosts[host_id]["next_due"]
            event.pop("suspended", None)
            routed.add(host_id)
        if routed != deferred:
            raise ValueError("new world arc host is missing its scheduler event")

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
        self._clear_completed_campaign_event_ack(runtime)
        hosts = runtime.get("hosts")
        if not isinstance(hosts, dict):
            raise ValueError("runtime causal hosts are invalid")
        previous_host_ids = set(hosts)
        sync_world_arc_routes(self, runtime)
        self._defer_new_world_arc_routes(runtime, previous_host_ids)
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
        runtime.pop("pending_wake", None)
        self._clear_completed_campaign_event_ack(runtime)
        return None

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        runtime = self.read(_RUNTIME_PATH)
        pending = self._pending_wake(runtime)
        if self._is_campaign_event_wake(pending) and command.command_type != "advance_time":
            updated = copy.deepcopy(runtime)
            updated.pop("pending_wake", None)
            self._clear_completed_campaign_event_ack(updated)
            self.put(_RUNTIME_PATH, updated)
        return super()._dispatch(command, payload)


__all__ = ["CampaignEventPlayerGroupActionPlanner"]
