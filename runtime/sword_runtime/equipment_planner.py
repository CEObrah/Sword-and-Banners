from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


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


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _manifest_entries(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = manifest.get("equipment_manifest", [])
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _active_state(state: object) -> bool:
    text = str(state or "").lower()
    return any(token in text for token in ("equipped", "worn", "readied", "quivered", "mounted"))


def _sync_compact_player_state(player: dict[str, Any], manifest: Mapping[str, Any]) -> None:
    states: dict[str, list[str]] = {}
    for row in _manifest_entries(manifest):
        if int(row.get("quantity", 0)) <= 0:
            continue
        item_key = str(row.get("item_id", ""))
        if not item_key:
            continue
        states.setdefault(item_key, []).append(str(row.get("current_state", "")))

    def active(item_key: str) -> bool:
        return any(_active_state(state) for state in states.get(item_key, []))

    compact = dict(player.get("current_equipment_state", {}))
    compact["bow"] = "readied" if active("weapon_bow_great_war") else "stored"
    compact["lance"] = "carried/secured" if active("weapon_lance_cavalry") else "stored_with_mounted_issue"
    compact["shield"] = "readied/slung" if active("shield_tang") else "stored"
    compact["sword"] = "sheathed_and_carried" if active("weapon_sword_one_hand_long") else "sheathed_and_stored"

    worn = [item_key for item_key in ("armor_tang", "helmet_tang") if active(item_key)]
    if worn:
        compact["worn"] = " + ".join(worn)
    elif str(compact.get("worn", "")).startswith(("armor_tang", "helmet_tang")):
        compact["worn"] = "unarmored clothing"

    compact["mounted"] = any(
        "mounted" in state.lower()
        for item_states in states.values()
        for state in item_states
    )
    player["current_equipment_state"] = compact


def _special_equipment_state(item_key: str, *, equipping: bool) -> str | None:
    if item_key.startswith("horse_armor_") or item_key.startswith("tack_"):
        return "equipped: fitted to assigned mount" if equipping else "cavalry stables"
    if item_key.startswith("horse_") and not item_key.startswith("horse_armor_") and not item_key.startswith("horse_blanket_"):
        return "equipped: assigned/prepared in cavalry stables" if equipping else "cavalry stables"
    return None


class EquipmentStateProjectionMixin:
    """Derive compact player state from the exact equipment manifest.

    The underlying engine remains inventory/custody authority. This production
    post-processor only synchronizes the compact player projection and gives
    mount gear a physically meaningful stable-preparation state instead of
    claiming a horse or barding is worn on Tang Wei's person.
    """

    def plan(self, command):
        plan = super().plan(command)
        if command.command_type not in _EQUIPMENT_COMMANDS:
            return plan

        manifest_path = "state/player-detail/equipment-manifest.json"
        player_path = "state/player.json"
        raw_manifest = plan.writes.get(manifest_path)
        if raw_manifest is None:
            return plan
        manifest = json.loads(raw_manifest.decode("utf-8"))

        item_key = str(command.payload.get("item_key", ""))
        if command.command_type in {"equipment_equip", "equipment_unequip"}:
            desired = _special_equipment_state(item_key, equipping=command.command_type == "equipment_equip")
            if desired is not None:
                for row in manifest.get("equipment_manifest", []):
                    if not isinstance(row, dict) or str(row.get("item_id", "")) != item_key:
                        continue
                    current = str(row.get("current_state", "")).lower()
                    if command.command_type == "equipment_equip" and "equipped/readied on person" in current:
                        row["current_state"] = desired
                    elif command.command_type == "equipment_unequip" and current.startswith("stored with player at"):
                        row["current_state"] = desired
                plan.writes[manifest_path] = _json_bytes(manifest)

        raw_player = plan.writes.get(player_path)
        player = (
            json.loads(raw_player.decode("utf-8"))
            if raw_player is not None
            else dict(self.store.read_json(player_path))
        )
        _sync_compact_player_state(player, manifest)
        plan.writes[player_path] = _json_bytes(player)
        return plan


__all__ = ["EquipmentStateProjectionMixin"]
