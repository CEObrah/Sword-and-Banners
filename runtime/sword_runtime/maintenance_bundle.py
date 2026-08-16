"""Trusted atomic multi-owner campaign repair support for explicit OOC DEV work.

The public gameplay surface never advertises this command.  It is accepted only
for the internal actor in maintenance mode, validates a bounded list of exact
state owners, stages all replacements in one transaction, records provenance in
the bounded semantic history, and advances no campaign time.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.history_store import HISTORY_INDEX_PATH, write_history_index

_COMMAND = "repair_bundle"


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
        if set(payload) != {"repairs", "reason"}:
            raise ValueError("repair_bundle requires exactly repairs and reason")
        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2048:
            raise ValueError("repair_bundle reason is invalid")
        repairs = payload.get("repairs")
        if not isinstance(repairs, list) or not 1 <= len(repairs) <= 64:
            raise ValueError("repair_bundle repairs must contain 1..64 owners")
        seen: set[str] = set()
        for row in repairs:
            if not isinstance(row, Mapping) or set(row) != {"path", "changes"}:
                raise ValueError("repair_bundle row must contain exactly path and changes")
            path = row.get("path")
            changes = row.get("changes")
            if (
                not isinstance(path, str)
                or not path.startswith("state/")
                or not path.endswith(".json")
                or ".." in path
                or "\\" in path
                or len(path) > 240
                or path in {"state/meta.json", HISTORY_INDEX_PATH}
                or path in seen
            ):
                raise ValueError("repair_bundle path is invalid or duplicated")
            if not isinstance(changes, Mapping) or not changes or len(changes) > 128:
                raise ValueError("repair_bundle changes are invalid")
            seen.add(path)
        return None

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type != _COMMAND:
            return super()._dispatch(command, payload)
        repairs = payload["repairs"]
        reason = str(payload["reason"])
        paths: list[str] = []
        changed_top_level_keys: dict[str, list[str]] = {}
        for row in repairs:
            path = str(row["path"])
            before = self.read(path)
            if not isinstance(before, Mapping):
                raise ValueError(f"repair_bundle owner is not an object: {path}")
            after = copy.deepcopy(dict(before))
            changes = copy.deepcopy(dict(row["changes"]))
            after.update(changes)
            self.put(path, after)
            paths.append(path)
            changed_top_level_keys[path] = sorted(str(key) for key in changes)

        history = copy.deepcopy(self.read(HISTORY_INDEX_PATH))
        events = history.setdefault("events", [])
        if not isinstance(events, list):
            raise ValueError("semantic history index is invalid")
        event_id = "repair_bundle_" + command.digest[:16]
        events.append({
            "event_id": event_id,
            "kind": "explicit_repair_bundle",
            "at": command.submitted_at,
            "paths": paths,
            "changed_top_level_keys": changed_top_level_keys,
            "reason": reason,
        })
        write_history_index(self, history)
        self._write_meta(command)
        return self._result(
            repair_event=event_id,
            repaired_paths=paths,
            repaired_owner_count=len(paths),
            world_time=str(self._world_time()),
        )


__all__ = ["MaintenanceRepairBundleMixin"]
