"""Player-safe projection of exact formation command staff.

Formation owners remain the sole authority for commander/deputy assignment. This
surface only rehydrates those exact refs into bounded controlled-formation views
so a registered deputy cannot disappear from play merely because a lower API
projection historically exposed only ``commander_ref``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from sword_runtime.api.household_operations import HouseholdAwareCampaignOperations


class CommandStaffAwareCampaignOperations(HouseholdAwareCampaignOperations):
    """Expose commander/deputy refs from exact controlled formation owners."""

    def _command_staff_for_formation(self, formation_ref: object) -> dict[str, str]:
        if not isinstance(formation_ref, str) or not formation_ref:
            return {}
        owner_index = self._read_optional_mapping("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        path = owners.get(formation_ref) if isinstance(owners, Mapping) else None
        if not isinstance(path, str):
            return {}
        formation = self._read_optional_mapping(path)
        if not isinstance(formation, Mapping):
            return {}
        staff: dict[str, str] = {}
        for field in ("commander_ref", "deputy_ref"):
            value = formation.get(field)
            if isinstance(value, str) and value.startswith("char_"):
                staff[field] = value
        return staff

    def _enrich_formation_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        enriched = dict(row)
        enriched.update(self._command_staff_for_formation(enriched.get("formation_ref")))
        return enriched

    def play_context(self):
        context = super().play_context()
        formations = [
            self._enrich_formation_row(row)
            for row in context.get("controlled_formations", [])
            if isinstance(row, Mapping)
        ]
        context["controlled_formations"] = formations

        permitted_people = set(context.get("permitted_person_ids", []))
        staff_by_formation: dict[str, dict[str, str]] = {}
        for row in formations:
            formation_ref = row.get("formation_ref")
            if not isinstance(formation_ref, str):
                continue
            staff = {
                field: value
                for field, value in (("commander_ref", row.get("commander_ref")), ("deputy_ref", row.get("deputy_ref")))
                if isinstance(value, str) and value.startswith("char_")
            }
            staff_by_formation[formation_ref] = staff
            permitted_people.update(staff.values())
        context["permitted_person_ids"] = sorted(permitted_people)

        scene = context.get("scene")
        if isinstance(scene, dict):
            physical = scene.get("physical_scene")
            if isinstance(physical, dict):
                colocated = physical.get("controlled_formations_at_player_location")
                if isinstance(colocated, list):
                    rows: list[dict[str, Any]] = []
                    for row in colocated:
                        if not isinstance(row, Mapping):
                            continue
                        enriched = dict(row)
                        ref = enriched.get("formation_ref")
                        if isinstance(ref, str):
                            enriched.update(staff_by_formation.get(ref, self._command_staff_for_formation(ref)))
                        rows.append(enriched)
                    physical["controlled_formations_at_player_location"] = rows
        return context

    def list_controlled_formations(self, cursor: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        result = dict(super().list_controlled_formations(cursor=cursor, limit=limit))
        result["formations"] = [
            self._enrich_formation_row(row)
            for row in result.get("formations", [])
            if isinstance(row, Mapping)
        ]
        return result

    def inspect_game_object(self, object_ref: str) -> dict[str, Any]:
        result = dict(super().inspect_game_object(object_ref))
        obj = result.get("object")
        if object_ref.startswith("formation_") and isinstance(obj, Mapping):
            result["object"] = self._enrich_formation_row(obj)
        return result


__all__ = ["CommandStaffAwareCampaignOperations"]
