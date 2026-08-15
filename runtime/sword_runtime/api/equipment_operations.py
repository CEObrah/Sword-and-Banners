from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.api.stable_operations import StableCampaignOperations


_EQUIPMENT_COMMANDS = frozenset({
    "equipment_equip",
    "equipment_unequip",
    "equipment_transfer",
    "equipment_issue",
    "equipment_return",
    "equipment_drop",
    "equipment_loot",
    "equipment_consume",
})


class EquipmentAwareCampaignOperations(StableCampaignOperations):
    """Stable player surface with exact, bounded owned-equipment identifiers."""

    def _owned_equipment_view(self) -> list[dict[str, Any]]:
        try:
            manifest = self.runtime.store.read_json("state/player-detail/equipment-manifest.json")
        except FileNotFoundError:
            return []
        entries = manifest.get("equipment_manifest", [])
        if not isinstance(entries, list):
            return []
        rows: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            item_key = entry.get("item_id")
            if not isinstance(item_key, str) or not item_key:
                continue
            rows.append({
                "item_key": item_key,
                "quantity": max(0, int(entry.get("quantity", 0))),
                "custody": entry.get("custody"),
                "current_state": entry.get("current_state"),
            })
        return rows[:64]

    def play_context(self):
        context = super().play_context()
        equipment = self._owned_equipment_view()
        player = context.setdefault("player", {})
        player["owned_equipment"] = equipment
        player["owned_equipment_count"] = len(equipment)

        commands = context.get("commands", {}).get("command_types", {})
        for command_type in _EQUIPMENT_COMMANDS:
            contract = commands.get(command_type)
            if not isinstance(contract, dict):
                continue
            guidance = contract.setdefault("input_guidance", {})
            guidance["item_key"] = {
                "rule": "use an exact item_key from player.owned_equipment; never guess hidden inventory identifiers"
            }

        travel = commands.get("travel")
        if isinstance(travel, dict):
            guidance = travel.setdefault("input_guidance", {})
            mode = guidance.setdefault("mode", {})
            if isinstance(mode, dict):
                mode["horse_rule"] = (
                    "horse mode mounts Tang Wei only at departure using an accessible assigned mount and tack; "
                    "preparing, assigning, tacking, or barding a horse while Wei is indoors never sets mounted=true"
                )
        return context


__all__ = ["EquipmentAwareCampaignOperations"]
