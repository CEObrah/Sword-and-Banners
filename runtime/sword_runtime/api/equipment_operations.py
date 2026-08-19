from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.api.operations import OperationError
from sword_runtime.api.standing_training_operations import StandingTrainingCampaignOperations
from sword_runtime.environment import environment_snapshot


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


def _states(equipment: list[dict[str, Any]], item_key: str) -> list[str]:
    return [
        str(row.get("current_state", "")).lower()
        for row in equipment
        if row.get("item_key") == item_key and int(row.get("quantity", 0)) > 0
    ]


def _active_personal(equipment: list[dict[str, Any]], item_key: str) -> bool:
    return any(
        any(token in state for token in ("equipped", "worn", "readied", "quivered"))
        for state in _states(equipment, item_key)
    )


def _project_equipment_state(
    base: Mapping[str, Any],
    equipment: list[dict[str, Any]],
    player_location: object,
) -> dict[str, Any]:
    compact = dict(base)
    compact["bow"] = "readied" if _active_personal(equipment, "weapon_bow_great_war") else "stored"
    compact["lance"] = "carried/secured" if _active_personal(equipment, "weapon_lance_cavalry") else "stored_with_mounted_issue"
    compact["shield"] = "readied/slung" if _active_personal(equipment, "shield_tang") else "stored"
    compact["sword"] = "sheathed_and_carried" if _active_personal(equipment, "weapon_sword_one_hand_long") else "sheathed_and_stored"
    worn = [item_key for item_key in ("armor_tang", "helmet_tang") if _active_personal(equipment, item_key)]
    if worn:
        compact["worn"] = " + ".join(worn)
    mounted = any("mounted by tang wei" in state for state in _states(equipment, "horse_tang_heavy_war"))
    compact["mounted"] = mounted
    if mounted and isinstance(player_location, str) and player_location:
        compact["mount_location"] = player_location
    elif not compact.get("mount_location"):
        compact["mount_location"] = "House Tang cavalry stables"
    return compact


class EquipmentAwareCampaignOperations(StandingTrainingCampaignOperations):
    """Stable player surface with exact, bounded owned-equipment identifiers."""

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        # OOC-development diagnostic only. This is process memory, never campaign
        # truth, and is exposed only through the read-only ooc_audit surface.
        self._last_command_rejection: dict[str, Any] | None = None

    def execute_command(self, command):
        try:
            result = super().execute_command(command)
        except OperationError as exc:
            cause = exc.__cause__
            if exc.code == "command_rejected" and cause is not None:
                self._last_command_rejection = {
                    "request_id": getattr(command, "request_id", None),
                    "command_type": getattr(command, "command_type", None),
                    "exception_type": type(cause).__name__,
                    "message": str(cause)[:1000],
                }
            raise
        self._last_command_rejection = None
        return result

    def ooc_audit(self, focus=None, observations=None):
        result = super().ooc_audit(focus=focus, observations=observations)
        result["last_command_rejection"] = (
            dict(self._last_command_rejection)
            if isinstance(self._last_command_rejection, Mapping)
            else None
        )
        return result

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
        base_equipment = player.get("equipment_state", {})
        if not isinstance(base_equipment, Mapping):
            base_equipment = {}
        player["equipment_state"] = _project_equipment_state(
            base_equipment,
            equipment,
            player.get("location"),
        )

        campaign = context.get("campaign", {})
        location_ref = player.get("location")
        world_time = campaign.get("world_time") if isinstance(campaign, Mapping) else None
        if isinstance(location_ref, str) and location_ref and isinstance(world_time, str) and world_time:
            context["environment"] = environment_snapshot(
                self.store,
                world_time=world_time,
                location_ref=location_ref,
            )

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
            guidance["environment"] = {
                "rule": "travel time is runtime-adjusted from the authoritative current/route environment; do not add a second weather penalty or assume unspecified route conditions"
            }
        return context


__all__ = ["EquipmentAwareCampaignOperations"]
