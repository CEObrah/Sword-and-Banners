"""Trusted atomic multi-owner campaign repair support for explicit OOC DEV work.

The public gameplay surface never advertises this command. It is accepted only
for the internal actor in maintenance mode. The command carries only a registered
repair identifier; the runtime derives exact changes from current owners and
stages the entire recipe in one transaction, keeping maintenance envelopes small
and preventing arbitrary path mutation through the MCP surface.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.warfare_command_roster_repair import apply_warfare_house_gbg_depth_v3

_COMMAND = "repair_bundle"
_REPAIRS = {
    "warfare_house_gbg_depth_v3": apply_warfare_house_gbg_depth_v3,
}


class MaintenanceRepairBundleMixin:
    def _authorize(self, command: Any) -> None:
        if (
            command.command_type == _COMMAND
            and command.actor_id == self.INTERNAL_ACTOR
            and command.mode == "maintenance"
        ):
            return
        super()._authorize(command)

    def _validate_command_semantics(self, command: Any, payload: Mapping[str, Any]) -> None:
        if command.command_type != _COMMAND:
            return super()._validate_command_semantics(command, payload)
        if set(payload) != {"repair_id", "reason"}:
            raise ValueError("repair_bundle requires exactly repair_id and reason")
        repair_id = payload.get("repair_id")
        reason = payload.get("reason")
        if repair_id not in _REPAIRS:
            raise ValueError("repair_bundle repair_id is not registered")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2048:
            raise ValueError("repair_bundle reason is invalid")
        return None

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type != _COMMAND:
            return super()._dispatch(command, payload)
        repair_id = str(payload["repair_id"])
        handler = _REPAIRS[repair_id]
        result = handler(self, command, str(payload["reason"]))
        self._write_meta(command)
        return self._result(
            repair_id=repair_id,
            world_time=str(self._world_time()),
            **result,
        )


__all__ = ["MaintenanceRepairBundleMixin"]
