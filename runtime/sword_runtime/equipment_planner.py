from __future__ import annotations

import copy
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

_MOUNT_KEY = "horse_tang_heavy_war"
_TACK_KEY = "tack_tang"
_BARDING_KEY = "horse_armor_tang"
_LANCE_KEY = "weapon_lance_cavalry"
_MANIFEST_PATH = "state/player-detail/equipment-manifest.json"
_PLAYER_PATH = "state/player.json"
_HOUSE_TANG_STABLES = "House Tang cavalry stables"


def _manifest_entries(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = manifest.get("equipment_manifest", [])
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _rows_for(manifest: Mapping[str, Any], item_key: str) -> list[Mapping[str, Any]]:
    return [
        row
        for row in _manifest_entries(manifest)
        if str(row.get("item_id", "")) == item_key and int(row.get("quantity", 0)) > 0
    ]


def _quantity(manifest: Mapping[str, Any], item_key: str) -> int:
    return sum(int(row.get("quantity", 0)) for row in _rows_for(manifest, item_key))


def _state_contains(manifest: Mapping[str, Any], item_key: str, *tokens: str) -> bool:
    lowered = tuple(token.lower() for token in tokens)
    for row in _rows_for(manifest, item_key):
        state = str(row.get("current_state", "")).lower()
        if any(token in state for token in lowered):
            return True
    return False


def _set_item_state(manifest: dict[str, Any], item_key: str, state: str) -> None:
    for row in manifest.get("equipment_manifest", []):
        if not isinstance(row, dict):
            continue
        if str(row.get("item_id", "")) != item_key or int(row.get("quantity", 0)) <= 0:
            continue
        row["current_state"] = state


def _active_personal_item(manifest: Mapping[str, Any], item_key: str) -> bool:
    for row in _rows_for(manifest, item_key):
        state = str(row.get("current_state", "")).lower()
        if any(token in state for token in ("equipped", "worn", "readied", "quivered")):
            return True
    return False


def _mount_label(player: Mapping[str, Any]) -> str:
    compact = player.get("current_equipment_state", {})
    if isinstance(compact, Mapping):
        mount_location = compact.get("mount_location")
        if isinstance(mount_location, str) and mount_location:
            return mount_location
    return _HOUSE_TANG_STABLES


def _mount_accessible(player: Mapping[str, Any], origin: str) -> bool:
    compact = player.get("current_equipment_state", {})
    mount_location = str(compact.get("mount_location", "")) if isinstance(compact, Mapping) else ""
    if mount_location == origin:
        return True
    if mount_location == _HOUSE_TANG_STABLES and origin.startswith("loc_tang_manor_"):
        return True
    return bool(compact.get("mounted", False)) and mount_location == origin if isinstance(compact, Mapping) else False


def _sync_compact_player_state(player: dict[str, Any], manifest: Mapping[str, Any]) -> None:
    compact = dict(player.get("current_equipment_state", {}))
    compact["bow"] = "readied" if _active_personal_item(manifest, "weapon_bow_great_war") else "stored"
    compact["lance"] = "carried/secured" if _active_personal_item(manifest, _LANCE_KEY) else "stored_with_mounted_issue"
    compact["shield"] = "readied/slung" if _active_personal_item(manifest, "shield_tang") else "stored"
    compact["sword"] = "sheathed_and_carried" if _active_personal_item(manifest, "weapon_sword_one_hand_long") else "sheathed_and_stored"

    worn = [item_key for item_key in ("armor_tang", "helmet_tang") if _active_personal_item(manifest, item_key)]
    if worn:
        compact["worn"] = " + ".join(worn)
    elif str(compact.get("worn", "")).startswith(("armor_tang", "helmet_tang")):
        compact["worn"] = "unarmored clothing"

    mounted = _state_contains(manifest, _MOUNT_KEY, "mounted by tang wei")
    compact["mounted"] = mounted
    if mounted:
        compact["mount_location"] = str(player.get("location", compact.get("mount_location", "")))
    elif not compact.get("mount_location"):
        compact["mount_location"] = _HOUSE_TANG_STABLES
    player["current_equipment_state"] = compact


def _prepared_state(item_key: str, player: Mapping[str, Any]) -> str:
    mount_location = _mount_label(player)
    if item_key == _MOUNT_KEY:
        if mount_location == _HOUSE_TANG_STABLES:
            return "equipped: assigned/prepared in cavalry stables"
        return f"equipped: assigned/prepared at {mount_location}"
    if mount_location == _HOUSE_TANG_STABLES:
        return "equipped: fitted/prepared on assigned mount in cavalry stables"
    return f"equipped: fitted/prepared on assigned mount at {mount_location}"


def _stored_mount_state(player: Mapping[str, Any]) -> str:
    location = str(player.get("location", ""))
    mount_location = _mount_label(player)
    if location.startswith("loc_tang_manor_") or mount_location == _HOUSE_TANG_STABLES:
        return "cavalry stables"
    return f"stored at {mount_location or location}"


def _normalize_mount_rows(manifest: dict[str, Any], player: Mapping[str, Any]) -> None:
    compact = player.get("current_equipment_state", {})
    if isinstance(compact, Mapping) and bool(compact.get("mounted", False)):
        return
    for item_key in (_MOUNT_KEY, _TACK_KEY, _BARDING_KEY):
        for row in manifest.get("equipment_manifest", []):
            if not isinstance(row, dict) or str(row.get("item_id", "")) != item_key:
                continue
            if int(row.get("quantity", 0)) <= 0:
                continue
            if str(row.get("current_state", "")).lower() == "equipped/readied on person":
                row["current_state"] = _prepared_state(item_key, player)


class EquipmentStateProjectionMixin:
    """Keep personal equipment, prepared mounts, and mounted travel physically distinct.

    The base engine remains inventory/custody authority. This production layer
    normalizes mount/tack/barding custody after equipment commands and applies
    the rider transition only when the player actually chooses horse travel.
    Merely assigning or barding a horse never means Tang Wei is mounted indoors.
    """

    def _require_horse_travel_ready(self, player: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        origin = str(player.get("location", ""))
        if _quantity(manifest, _MOUNT_KEY) < 1:
            raise ValueError("horse travel requires an assigned player mount")
        if _quantity(manifest, _TACK_KEY) < 1:
            raise ValueError("horse travel requires assigned tack")
        if not _mount_accessible(player, origin):
            raise ValueError("assigned mount is not physically accessible from the player's current location")

    def _postprocess_equipment(self, command: Any) -> None:
        manifest = copy.deepcopy(self.read(_MANIFEST_PATH))
        player = copy.deepcopy(self.read(_PLAYER_PATH))
        _normalize_mount_rows(manifest, player)

        item_key = str(command.payload.get("item_key", ""))
        if command.command_type in {"equipment_equip", "equipment_unequip"} and item_key in {
            _MOUNT_KEY,
            _TACK_KEY,
            _BARDING_KEY,
        }:
            if command.command_type == "equipment_equip":
                _set_item_state(manifest, item_key, _prepared_state(item_key, player))
            else:
                _set_item_state(manifest, item_key, _stored_mount_state(player))
                if item_key == _MOUNT_KEY:
                    compact = dict(player.get("current_equipment_state", {}))
                    compact["mounted"] = False
                    compact["mount_location"] = _mount_label(player)
                    player["current_equipment_state"] = compact

        _sync_compact_player_state(player, manifest)
        self.put(_MANIFEST_PATH, manifest)
        self.put(_PLAYER_PATH, player)

    def _postprocess_travel(
        self,
        *,
        mode: str,
        origin: str,
        was_mounted: bool,
        barding_prepared: bool,
    ) -> None:
        manifest = copy.deepcopy(self.read(_MANIFEST_PATH))
        player = copy.deepcopy(self.read(_PLAYER_PATH))
        _normalize_mount_rows(manifest, player)
        destination = str(player.get("location", ""))

        if mode == "horse":
            _set_item_state(manifest, _MOUNT_KEY, f"equipped: mounted by Tang Wei at {destination}")
            _set_item_state(manifest, _TACK_KEY, "equipped: fitted to mounted horse")
            if barding_prepared:
                _set_item_state(manifest, _BARDING_KEY, "equipped: fitted to mounted horse")
            if _quantity(manifest, _LANCE_KEY) > 0 and (
                _state_contains(manifest, _LANCE_KEY, "mounted issue")
                or _active_personal_item(manifest, _LANCE_KEY)
            ):
                _set_item_state(manifest, _LANCE_KEY, "equipped: secured with mounted issue")
            compact = dict(player.get("current_equipment_state", {}))
            compact["mount_location"] = destination
            player["current_equipment_state"] = compact
        elif was_mounted:
            _set_item_state(manifest, _MOUNT_KEY, f"equipped: assigned/prepared at {origin}")
            _set_item_state(manifest, _TACK_KEY, f"equipped: fitted/prepared on assigned mount at {origin}")
            if barding_prepared:
                _set_item_state(manifest, _BARDING_KEY, f"equipped: fitted/prepared on assigned mount at {origin}")
            if _state_contains(manifest, _LANCE_KEY, "secured with mounted issue"):
                _set_item_state(manifest, _LANCE_KEY, "stored with mounted issue")
            compact = dict(player.get("current_equipment_state", {}))
            compact["mounted"] = False
            compact["mount_location"] = origin
            player["current_equipment_state"] = compact

        _sync_compact_player_state(player, manifest)
        self.put(_MANIFEST_PATH, manifest)
        self.put(_PLAYER_PATH, player)

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        travel_mode = str(payload.get("mode", "foot")) if command.command_type == "travel" else ""
        origin = ""
        was_mounted = False
        barding_prepared = False

        if command.command_type == "travel":
            player_before = copy.deepcopy(self.read(_PLAYER_PATH))
            manifest_before = copy.deepcopy(self.read(_MANIFEST_PATH))
            _normalize_mount_rows(manifest_before, player_before)
            origin = str(player_before.get("location", ""))
            compact_before = player_before.get("current_equipment_state", {})
            was_mounted = bool(compact_before.get("mounted", False)) if isinstance(compact_before, Mapping) else False
            barding_prepared = _state_contains(
                manifest_before,
                _BARDING_KEY,
                "equipped",
                "fitted",
                "prepared",
            )
            if travel_mode == "horse":
                self._require_horse_travel_ready(player_before, manifest_before)

        result = super()._dispatch(command, payload)

        if command.command_type in _EQUIPMENT_COMMANDS:
            self._postprocess_equipment(command)
        elif command.command_type == "travel":
            self._postprocess_travel(
                mode=travel_mode,
                origin=origin,
                was_mounted=was_mounted,
                barding_prepared=barding_prepared,
            )
        return result


__all__ = ["EquipmentStateProjectionMixin"]
