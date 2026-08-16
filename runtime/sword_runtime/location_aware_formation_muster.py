"""Allow formation creation from an exact location-aware reserve pool.

The base reducer historically treated one optional ``source_location_ref`` on a
force as the only lawful muster point. Production forces now carry exact
``available_by_location`` reserves, so that legacy shortcut can reject a real
conserved cohort at its actual location. This adapter changes no authority or
manpower accounting: it only lets the existing formation_create reducer use an
explicit requested location when that same force already proves enough of the
requested role there.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any


class LocationAwareFormationMusterMixin:
    """Bridge legacy single-source muster logic to exact location-aware reserves."""

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type != "formation_create" or not payload.get("force_ref") or not payload.get("location_ref"):
            return super()._dispatch(command, payload)

        force_ref = str(payload["force_ref"])
        force_path = self.owner_path(force_ref)
        force = copy.deepcopy(self.read(force_path))
        location = str(payload["location_ref"])
        role = str(payload.get("role", "line_infantry"))
        personnel = max(0, int(payload.get("personnel", 0)))
        by_location = force.get("available_by_location", {})
        pool = by_location.get(location, {}) if isinstance(by_location, Mapping) else {}
        exact_available = int(pool.get(role, 0)) if isinstance(pool, Mapping) else 0

        if personnel <= 0 or exact_available < personnel:
            return super()._dispatch(command, payload)

        had_source = "source_location_ref" in force
        previous_source = force.get("source_location_ref")
        if str(previous_source or "") == location:
            return super()._dispatch(command, payload)

        # The base formation_create reducer already performs the authoritative
        # role/location conservation transfer. Temporarily align its legacy
        # source-location guard with the exact pool it is about to consume, then
        # restore the force's ordinary default muster point afterwards.
        force["source_location_ref"] = location
        self.put(force_path, force)
        result = super()._dispatch(command, payload)

        updated = copy.deepcopy(self.read(force_path))
        if had_source:
            updated["source_location_ref"] = previous_source
        else:
            updated.pop("source_location_ref", None)
        self.put(force_path, updated)
        return result


__all__ = ["LocationAwareFormationMusterMixin"]
