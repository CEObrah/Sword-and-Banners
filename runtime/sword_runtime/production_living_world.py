"""Final production-only living-world normalizations.

Keep these corrections above the reusable causal planner so the historical
battle reducer remains authoritative while the hosted runtime exposes exact
saved locations and respects existing formation commitments as hard eligibility
constraints.
"""
from __future__ import annotations

from typing import Any, Mapping

from sword_runtime.causal_living_world import CausalLivingWorldSwordPlanner


class ProductionLivingWorldSwordPlanner(CausalLivingWorldSwordPlanner):
    """Hosted Sword planner with exact provenance and assignment integrity."""

    def _formation_score(
        self,
        formation_ref: str,
        formation: Mapping[str, Any],
        objective_text: str,
        memory: dict[str, Any],
        reserved: set[str],
    ) -> int:
        # Existing active operation commitments are hard custody/availability
        # facts, not a soft preference. A very strong formation must never win
        # its way through a penalty and become double-assigned.
        if formation_ref in reserved:
            return -(10**9)
        return super()._formation_score(
            formation_ref,
            formation,
            objective_text,
            memory,
            reserved,
        )

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
