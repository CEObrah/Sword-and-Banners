"""Bounded player-safe routing for full command-establishment people.

The normal owner index remains the general exact-owner router. Newly represented
formal military commanders/deputies may also be registered in the bounded
command-personnel index. This adapter lets controlled-formation service reads
resolve those exact full characters without making the command index a second
campaign authority or exposing unrelated private state.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.api.command_staff_operations import (
    CommandStaffAwareCampaignOperations,
    _COMMAND_SERVICE_FIELDS,
)
from sword_runtime.api.operations import OperationError

_COMMAND_PERSON_INDEX_PATH = "state/cmd/command-personnel.json"


class RoutedCommandStaffAwareCampaignOperations(CommandStaffAwareCampaignOperations):
    """Resolve full controlled command staff through either exact bounded router."""

    def _exact_object_location(self, object_ref: str) -> str | None:
        """Resolve the player through the authoritative player owner before generic routing."""
        meta = self._read_optional_mapping("state/meta.json")
        player_id = meta.get("player_id") if isinstance(meta, Mapping) else None
        if isinstance(player_id, str) and object_ref == player_id:
            player = self._read_optional_mapping("state/player.json")
            if isinstance(player, Mapping):
                for key in ("current_location", "location_ref", "location", "loc", "site_ref"):
                    value = player.get(key)
                    if isinstance(value, str) and value:
                        return value
            return None
        return super()._exact_object_location(object_ref)

    def _command_person_path(self, person_id: str) -> str | None:
        index = self._read_optional_mapping(_COMMAND_PERSON_INDEX_PATH)
        records = index.get("record_index", {}) if isinstance(index, Mapping) else {}
        path = records.get(person_id) if isinstance(records, Mapping) else None
        return path if isinstance(path, str) and path else None

    def _registered_full_command_person(self, person_id: str) -> Mapping[str, Any] | None:
        # The bounded command-personnel index is an accelerator, never identity
        # authority.  A promoted command person may lawfully keep an officer.*
        # ref even if that projection is stale or absent, so fall back to the
        # canonical owner route and classify by the saved document schema.
        paths: list[str] = []
        registered = self._command_person_path(person_id)
        if isinstance(registered, str):
            paths.append(registered)
        owner_index = self._read_optional_mapping("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        owned = owners.get(person_id) if isinstance(owners, Mapping) else None
        if isinstance(owned, str) and owned not in paths:
            paths.append(owned)
        for path in paths:
            person = self._read_optional_mapping(path)
            if isinstance(person, Mapping) and str(person.get("schema", "")) in {"sab_character", "sword-materialized-person"}:
                return person
        return None

    @staticmethod
    def _full_command_service_sheet(person_id: str, person: Mapping[str, Any]) -> dict[str, Any]:
        projected: dict[str, Any] = {"person_id": person_id, "representation": "full_character"}
        projected.update({key: person.get(key) for key in _COMMAND_SERVICE_FIELDS if key in person})
        projected.setdefault("life_status", "active")
        return {
            "visibility": "player_visible_command_service_sheet",
            "person": projected,
            "scope": (
                "Command-relevant service capability only. Private motives, relationships, hidden knowledge, "
                "and unrelated personal state remain excluded."
            ),
        }

    def person_sheet(self, person_id: str) -> dict[str, Any]:
        context = self.play_context()
        permitted = set(context.get("permitted_person_ids", []))
        if person_id == context.get("campaign", {}).get("player_id"):
            return super().person_sheet(person_id)

        # Command-service projection is role-scoped, not a generic full-person
        # projection.  The owner/schema fallback exists so a promoted commander
        # may retain an officer.* identity, but it must never collapse an ordinary
        # family/court/person read into the smaller command-service sheet merely
        # because that person is a full sab_character.
        exact = self._exact_controlled_command_role(person_id)
        if exact is not None:
            person = self._registered_full_command_person(person_id)
            if isinstance(person, Mapping):
                return self._full_command_service_sheet(person_id, person)

        if person_id not in permitted:
            # Hot handoff projection limits are not command-authority limits.
            # Only an exact controlled command role can open the off-page
            # command-service read path.
            return super().person_sheet(person_id)

        return super().person_sheet(person_id)

    def inspect_game_object(self, object_ref: str) -> dict[str, Any]:
        result = dict(super().inspect_game_object(object_ref))
        obj = result.get("object")
        if not object_ref.startswith("formation_") or not isinstance(obj, dict):
            return result

        formation = self._formation_record(object_ref)
        structure = self._command_structure_for_formation(object_ref)
        refs = self._command_refs(structure, formation)
        person_lite: list[dict[str, str]] = []
        full_command: list[dict[str, str]] = []
        for ref, role in sorted(refs.items()):
            representation = self._command_person_representation(ref)
            if representation == "full_character":
                full_command.append({"person_ref": ref, "role": role, "representation": "full_character"})
            elif representation == "person_lite":
                person_lite.append({"person_ref": ref, "role": role, "representation": "person_lite"})
        obj["person_lite_officers"] = person_lite
        obj["person_lite_officer_count"] = len(person_lite)
        obj["full_command_officers"] = full_command
        obj["full_command_officer_count"] = len(full_command)
        result["object"] = obj
        return result


__all__ = ["RoutedCommandStaffAwareCampaignOperations"]
