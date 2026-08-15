from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import (
    triggered_interaction_record,
    validate_interaction_payload,
)
from sword_runtime.api.operations import OperationError
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
_DIRECT_FAMILY_LIMIT = 16


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


def _person_location(person: Mapping[str, Any]) -> str | None:
    value = person.get("current_location")
    if not isinstance(value, str) or not value:
        value = person.get("location")
    return value if isinstance(value, str) and value else None


class EquipmentAwareCampaignOperations(StableCampaignOperations):
    """Stable player surface with equipment plus bounded direct-family scene fidelity."""

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

    def _direct_family_scene_people(self, player_id: str, player_location: object) -> list[dict[str, Any]]:
        """Return exact direct family who are physically at the player's current location.

        Family index reads are bounded routing only. Presence comes exclusively
        from the exact character owner current_location/location field, so a
        household residence never fabricates current occupancy.
        """
        if not isinstance(player_location, str) or not player_location:
            return []
        try:
            family = self.store.read_json("state/family/index.json")
            owners = self.store.read_json("state/index/owner-index.json").get("owners", {})
        except FileNotFoundError:
            return []
        if not isinstance(family, Mapping) or not isinstance(owners, Mapping):
            return []
        person_index = family.get("person_index", {})
        links = person_index.get(player_id, {}) if isinstance(person_index, Mapping) else {}
        if not isinstance(links, Mapping):
            return []

        relations: dict[str, str] = {}
        parentage_index = family.get("parentage", {})
        if isinstance(parentage_index, Mapping):
            for parentage_ref in links.get("parentage", []):
                path = parentage_index.get(parentage_ref)
                if not isinstance(path, str):
                    continue
                record = self.store.read_json(path)
                if not isinstance(record, Mapping):
                    continue
                child_id = record.get("child_id")
                parent_links = record.get("parent_links", [])
                if child_id == player_id and isinstance(parent_links, list):
                    for link in parent_links:
                        if not isinstance(link, Mapping):
                            continue
                        parent_id = link.get("parent_id")
                        if isinstance(parent_id, str) and parent_id.startswith("char_"):
                            relations.setdefault(parent_id, "parent")
                elif isinstance(child_id, str) and isinstance(parent_links, list):
                    if any(
                        isinstance(link, Mapping) and link.get("parent_id") == player_id
                        for link in parent_links
                    ):
                        relations.setdefault(child_id, "child")

        kinship_index = family.get("kinships", {})
        if isinstance(kinship_index, Mapping):
            for kinship_ref in links.get("kinships", []):
                path = kinship_index.get(kinship_ref)
                if not isinstance(path, str):
                    continue
                record = self.store.read_json(path)
                if not isinstance(record, Mapping) or record.get("status", "active") != "active":
                    continue
                participants = record.get("participants", [])
                relation_roles = record.get("relation_roles", {})
                if not isinstance(participants, list):
                    continue
                for person_ref in participants:
                    if person_ref == player_id or not isinstance(person_ref, str):
                        continue
                    relation = (
                        relation_roles.get(person_ref)
                        if isinstance(relation_roles, Mapping)
                        else None
                    )
                    relations.setdefault(
                        person_ref,
                        str(relation or record.get("kinship_type") or "family"),
                    )

        rows: list[dict[str, Any]] = []
        for person_ref in sorted(relations)[:_DIRECT_FAMILY_LIMIT]:
            path = owners.get(person_ref)
            if not isinstance(path, str):
                continue
            person = self.store.read_json(path)
            if not isinstance(person, Mapping):
                continue
            if str(person.get("life_status", "active")) != "active":
                continue
            location = _person_location(person)
            if location != player_location:
                continue
            rows.append({
                "person_id": person_ref,
                "name": person.get("name"),
                "relation": relations[person_ref],
                "role": person.get("role") or person.get("authority"),
                "location": location,
            })
        return rows

    def _validate_interaction_authority(self, command) -> None:
        """Validate against the final player surface, including exact present family."""
        payload = validate_interaction_payload(command.payload)
        context = self.play_context()
        player_id = str(context["campaign"]["player_id"])
        all_formations = self._all_controlled_formations(player_id)
        controlled_refs = {
            str(item["formation_ref"])
            for item in all_formations
            if item.get("formation_ref")
        }
        permitted = set(context.get("permitted_person_ids", [])) | set(
            context.get("permitted_object_refs", [])
        )

        target_ref = payload["target_ref"]
        target_visible = (
            target_ref in permitted
            or triggered_interaction_record(self.store, target_ref) is not None
        )
        current_location = context.get("player", {}).get("location")
        if payload["action"] == "seek_contact" and target_ref == current_location:
            target_visible = True
        if not target_visible:
            raise OperationError(404, "interaction_target_not_player_visible")

        process_ref = payload["process_ref"]
        if (
            process_ref is not None
            and process_ref not in permitted
            and triggered_interaction_record(self.store, process_ref) is None
        ):
            raise OperationError(404, "interaction_process_not_player_visible")
        if any(ref not in controlled_refs for ref in payload["formation_refs"]):
            raise OperationError(403, "interaction_formation_not_controlled")

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

        player_id = str(context.get("campaign", {}).get("player_id", ""))
        family_people = self._direct_family_scene_people(player_id, player.get("location"))
        if family_people:
            scene = context.setdefault("scene", {})
            cast = scene.get("scene_cast")
            cast = dict(cast) if isinstance(cast, Mapping) else {}
            present = cast.get("present_people", [])
            present_rows = [dict(row) for row in present if isinstance(row, Mapping)] if isinstance(present, list) else []
            by_id = {
                str(row.get("person_id")): row
                for row in present_rows
                if isinstance(row.get("person_id"), str)
            }
            for row in family_people:
                by_id[str(row["person_id"])] = row
            cast["present_people"] = [by_id[key] for key in sorted(by_id)]
            cast.setdefault("visible_people", [])
            cast.setdefault("nearby_people", [])
            cast.setdefault("referenced_people", [])
            cast["presence_rule"] = (
                "present_people are exact current-location matches from authoritative person owners; "
                "household residence alone never proves presence"
            )
            scene["scene_cast"] = cast

            contract = scene.get("scene_local_narration_contract")
            contract = dict(contract) if isinstance(contract, Mapping) else {}
            contract["co_located_social_rule"] = (
                "If a known person is listed in scene_cast.present_people, ordinary intent such as "
                "'talk to them', 'go speak to them', or 'join them' is a direct scene-local approach, "
                "not seek_contact, an audience request, or a waiting policy. Use interaction_action only "
                "for the player's actual consequential proposal, request, report, offer, petition, or other durable attempt."
            )
            scene["scene_local_narration_contract"] = contract

            permitted_people = set(context.get("permitted_person_ids", []))
            permitted_people.update(str(row["person_id"]) for row in family_people)
            context["permitted_person_ids"] = sorted(permitted_people)

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

        interaction = commands.get("interaction_action")
        if isinstance(interaction, dict):
            guidance = interaction.setdefault("input_guidance", {})
            guidance["seek_contact_rule"] = (
                "Do not use seek_contact for a person already listed in scene.scene_cast.present_people. "
                "Ordinary local conversation begins directly; seek_contact is for a person/channel not presently accessible."
            )
        return context


__all__ = ["EquipmentAwareCampaignOperations"]
