"""Causal provenance overlay for autonomous living-world consequences."""
from __future__ import annotations

from typing import Any, Mapping

from sword_runtime.living_world import LivingWorldSwordPlanner


class CausalLivingWorldSwordPlanner(LivingWorldSwordPlanner):
    """Enrich new autonomous material events without replacing their authority."""

    def _record_interstate_battle_memory(self, event: Mapping[str, Any], at: str) -> None:
        # The inherited interstate reducer owns the actual battle result. This
        # overlay adds bounded provenance to that same mutable event before the
        # planned history after-image is serialized.
        if isinstance(event, dict):
            battlefield = event.get("battlefield_ref")
            theater = event.get("theater_ref")
            attacker_state = event.get("attacker_state")
            defender_state = event.get("defender_state")
            attacker_ref = event.get("attacker_formation_ref")
            defender_ref = event.get("defender_formation_ref")
            losses = event.get("losses") if isinstance(event.get("losses"), Mapping) else {}

            place_refs = [str(battlefield)] if isinstance(battlefield, str) and battlefield else []
            causal_refs = [str(theater)] if isinstance(theater, str) and theater else []
            affected: list[str] = []
            for value in (attacker_ref, defender_ref):
                if isinstance(value, str) and value and value not in affected:
                    affected.append(value)
            for state in (attacker_state, defender_state):
                if isinstance(state, str) and state:
                    ref = f"state_{state}"
                    if ref not in affected:
                        affected.append(ref)

            actor_refs: list[str] = []
            material: list[str] = []
            for formation_ref, row in sorted(losses.items()):
                if not isinstance(formation_ref, str) or not isinstance(row, Mapping):
                    continue
                commander = row.get("commander_ref")
                if isinstance(commander, str) and commander and commander not in actor_refs:
                    actor_refs.append(commander)
                loss = row.get("loss")
                if isinstance(loss, int) and not isinstance(loss, bool) and loss > 0:
                    material.append(f"casualties:{formation_ref}:{loss}")
                commander_outcome = row.get("commander_outcome")
                if isinstance(commander_outcome, str) and commander_outcome not in {"", "unharmed"}:
                    material.append(f"commander:{commander}:{commander_outcome}")

            event["actor_refs"] = actor_refs[:16]
            event["place_refs"] = place_refs
            event["causal_refs"] = causal_refs
            event["affected_owner_refs"] = affected[:16]
            event["material_consequence_refs"] = material[:32]
            event["provenance"] = {
                "kind": "autonomous_runtime_resolution",
                "authority": "existing interstate battle reducer",
                "recorded_at": at,
            }

        super()._record_interstate_battle_memory(event, at)


__all__ = ["CausalLivingWorldSwordPlanner"]
