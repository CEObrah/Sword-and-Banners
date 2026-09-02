"""Exact world-time view for production causal callbacks.

The chronological scheduler advances the runtime cursor to each host's exact due
instant before invoking the callback. The outer semantic command intentionally
updates the campaign meta clock only after all due work has settled. Generic
reducers that call `_world_time()` inside a callback therefore need a bounded
view of the scheduler's active instant; outside callbacks the ordinary strict
meta/runtime chronology equality remains authoritative.
"""
from __future__ import annotations

from sword_runtime.sim.calendar import CampaignTime


class CausalCallbackWorldTimeMixin:
    """Expose only the scheduler's exact active due instant during a callback."""

    def _world_time(self) -> CampaignTime:
        if (
            getattr(self, "_active_event_id", None) is not None
            and getattr(self, "_active_host_id", None) is not None
        ):
            runtime = self.read("state/runtime.json")
            due_text = runtime.get("world_time") if isinstance(runtime, dict) else None
            if not isinstance(due_text, str) or not due_text:
                raise ValueError("active causal callback lost its runtime time cursor")
            return CampaignTime.parse(due_text)
        return super()._world_time()


__all__ = ["CausalCallbackWorldTimeMixin"]
