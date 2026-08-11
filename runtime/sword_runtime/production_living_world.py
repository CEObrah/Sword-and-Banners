"""Final production-only living-world normalizations.

Keep these corrections above the reusable causal planner so the historical
battle reducer remains authoritative while the hosted runtime exposes the exact
saved location as semantic provenance.
"""
from __future__ import annotations

from typing import Any, Mapping

from sword_runtime.causal_living_world import CausalLivingWorldSwordPlanner


class ProductionLivingWorldSwordPlanner(CausalLivingWorldSwordPlanner):
    """Hosted Sword planner with exact-location provenance normalization."""

    def _record_interstate_battle_memory(self, event: Mapping[str, Any], at: str) -> None:
        injected_legacy_field = False
        if isinstance(event, dict):
            location_ref = event.get("location_ref")
            if (
                isinstance(location_ref, str)
                and location_ref
                and not isinstance(event.get("battlefield_ref"), str)
            ):
                # CausalLivingWorldSwordPlanner historically named this semantic
                # input battlefield_ref. The interstate reducer actually owns
                # the exact field as location_ref. Bridge only for the duration
                # of provenance derivation and do not persist a duplicate field.
                event["battlefield_ref"] = location_ref
                injected_legacy_field = True
        try:
            super()._record_interstate_battle_memory(event, at)
        finally:
            if injected_legacy_field and isinstance(event, dict):
                event.pop("battlefield_ref", None)


__all__ = ["ProductionLivingWorldSwordPlanner"]
