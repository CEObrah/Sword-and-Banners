"""Production planner layer for short-horizon campaign work and world arcs.

One-shot campaign work, institutional follow-ups, and recurring world-arc
pressure share the existing chronological causal frontier. Exact event owners
become truth only when their runtime host settles.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.autonomy_routing import select_formations_fair
from sword_runtime.civil_world import sync_faction_routes, sync_polity_routes
from sword_runtime.information_handoff import record_delivered_world_arc_report_information
from sword_runtime.institutional_processes import (
    settle_institutional_process_followup,
    sync_institutional_process_routes,
)
from sword_runtime.player_group_actions import PlayerGroupActionPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.systems.campaign_events import (
    settle_campaign_work_target,
    sync_campaign_work_routes,
)
from sword_runtime.world_arc_report_handoff import settle_player_safe_world_arc_report
from sword_runtime.world_arcs import (
    settle_world_arc_review,
    sync_world_arc_routes,
)

_RUNTIME_PATH = "state/runtime.json"


class CampaignEventPlayerGroupActionPlanner(PlayerGroupActionPlanner):
    """Hosted planner with recurring world arcs and player-facing event notices."""

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
        # Fair bounded candidate rotation must not bypass exact operation custody.
        # Manual commitments and other operations remain hard reservations; only
        # this state's own autonomous response routes may be reconsidered here.
        operation_index = self.read("state/operations/index.json")
        operations = operation_index.get("operations") if isinstance(operation_index, Mapping) else None
        if not isinstance(operations, Mapping):
            raise ValueError("operation index is invalid")
        occupied = set(reserved)
        own_prefix = f"operation_auto_{state}_"
        own_response = f"operation_auto_{state}_border_response"
        active_states = {"planned", "mobilizing", "active", "engaged", "occupied"}
        for operation_ref, path in sorted(operations.items()):
            if not isinstance(operation_ref, str) or not isinstance(path, str):
                raise ValueError("operation index is invalid")
            operation = self.read(path)
            if str(operation.get("status", "")) not in active_states:
                continue
            if operation_ref == own_response or operation_ref.startswith(own_prefix):
                continue
            refs = operation.get("formation_refs")
            if not isinstance(refs, list):
                raise ValueError("active operation has invalid formation_refs")
            occupied.update(str(ref) for ref in refs if isinstance(ref, str) and ref)
        return select_formations_fair(
            self,
            state,
            objective_text,
            memory,
            reserved=occupied,
            count=count,
        )

    # Due-host settlement is centrally dispatched by time_integration.py.



__all__ = ["CampaignEventPlayerGroupActionPlanner"]
