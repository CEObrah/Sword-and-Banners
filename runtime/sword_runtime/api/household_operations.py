from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import (
    triggered_interaction_record,
    validate_interaction_payload,
)
from sword_runtime.api.operations import OperationError
from sword_runtime.api.stable_operations import StableCampaignOperations


_DIRECT_FAMILY_LIMIT = 16
_SWORD_MANOR_REF = "institution_sword_manor"
_PLAYER_RETINUE_ROOT = "cmdgrp.tang_wei.personal_force"
_SUPERSEDED_RESPONSE_STATUS = "superseded_misclassified_response"


def _person_location(person: Mapping[str, Any]) -> str | None:
    value = person.get("current_location")
    if not isinstance(value, str) or not value:
        value = person.get("location")
    return value if isinstance(value, str) and value else None


_IMMEDIATE_SCENE_LOCATION_KINDS = frozenset({"hall", "office", "scene_venue", "training_ground"})


class HouseholdAwareCampaignOperations(StableCampaignOperations):
    """Stable player surface with bounded exact direct-family scene fidelity."""

    def _read_optional_mapping(self, path: str) -> Mapping[str, Any] | None:
        try:
            value = self.store.read_json(path)
        except (FileNotFoundError, ValueError):
            return None
        return value if isinstance(value, Mapping) else None

    @staticmethod
    def _command_group_path(command_group_ref: str) -> str | None:
        if not isinstance(command_group_ref, str) or not command_group_ref.startswith("cmdgrp."):
            return None
        if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in command_group_ref):
            return None
        return f"state/cmd/command-groups/{command_group_ref}.json"

    def _exact_object_location(self, object_ref: str) -> str | None:
        """Resolve current location from the exact owner instead of a command-group cache."""
        owners = self._read_optional_mapping("state/index/owner-index.json")
        owner_map = owners.get("owners", {}) if isinstance(owners, Mapping) else {}
        path = owner_map.get(object_ref) if isinstance(owner_map, Mapping) else None
        if not isinstance(path, str):
            return None
        doc = self._read_optional_mapping(path)
        if not isinstance(doc, Mapping):
            return None
        for key in ("current_location", "location_ref", "location", "loc", "site_ref"):
            value = doc.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _command_group_current_location(self, doc: Mapping[str, Any]) -> tuple[str | None, str]:
        commander_ref = doc.get("commander_ref")
        if isinstance(commander_ref, str):
            location = self._exact_object_location(commander_ref)
            if location:
                return location, "commander_exact_location"
        unit_locations = {
            location for ref in doc.get("direct_unit_refs", [])
            if isinstance(ref, str) and (location := self._exact_object_location(ref))
        }
        if len(unit_locations) == 1:
            return next(iter(unit_locations)), "co_located_attached_formations"
        return None, "not_established"

    def _retinue_projection(self) -> tuple[list[dict[str, Any]], set[str], set[str]]:
        """Return the player's durable retinue root and its immediate command layer.

        The projection follows saved hierarchy refs rather than scanning command-group
        files. Deeper descendants remain discoverable from exact subordinate refs.
        """
        root_path = self._command_group_path(_PLAYER_RETINUE_ROOT)
        if root_path is None:
            return [], set(), set()
        root = self._read_optional_mapping(root_path)
        if not isinstance(root, Mapping):
            return [], set(), set()
        docs: list[Mapping[str, Any]] = [root]
        for child_ref in root.get("subordinate_command_group_refs", []):
            child_path = self._command_group_path(child_ref) if isinstance(child_ref, str) else None
            child = self._read_optional_mapping(child_path) if isinstance(child_path, str) else None
            if isinstance(child, Mapping):
                docs.append(child)
        rows: list[dict[str, Any]] = []
        object_refs: set[str] = set()
        person_refs: set[str] = set()
        for doc in docs:
            ref = doc.get("id")
            if not isinstance(ref, str):
                continue
            object_refs.add(ref)
            subordinate_refs = [x for x in doc.get("subordinate_command_group_refs", []) if isinstance(x, str)]
            object_refs.update(subordinate_refs)
            exact_people = []
            for value in [doc.get("commander_ref"), doc.get("deputy_ref"), *doc.get("direct_person_refs", [])]:
                if isinstance(value, str) and value and value not in exact_people:
                    exact_people.append(value)
                    person_refs.add(value)
            current_location_ref, location_basis = self._command_group_current_location(doc)
            rows.append({
                "command_group_ref": ref,
                "display_name": doc.get("display_name"),
                "context": doc.get("context"),
                "commander_ref": doc.get("commander_ref"),
                "deputy_ref": doc.get("deputy_ref"),
                "exact_person_refs": exact_people,
                "direct_formation_refs": [x for x in doc.get("direct_unit_refs", []) if isinstance(x, str)],
                "subordinate_command_group_refs": subordinate_refs,
                "familiarity_milli": doc.get("familiarity_milli", 0),
                "verified_group_training_hours": doc.get("verified_group_training_hours", 0),
                "active_context_ref": doc.get("active_context_ref"),
                "communication_ref": doc.get("communication_ref"),
                "current_location_ref": current_location_ref,
                "location_basis": location_basis,
            })
        return rows, object_refs, person_refs

    def _superseded_house_response_refs(self) -> set[str]:
        """Return repaired House responses that must not remain live interaction handles.

        The causal event remains durable history.  House Tang is the exact owner of
        the administrative request classification, so an explicit repair marker on
        that request can supersede the old delivery without deleting history or
        rewriting an otherwise-valid gameplay transaction.
        """
        house = self._read_optional_mapping("state/houses/house_tang.json")
        requests = house.get("administrative_requests", {}) if isinstance(house, Mapping) else {}
        if not isinstance(requests, Mapping):
            return set()
        refs: set[str] = set()
        for request in requests.values():
            if not isinstance(request, Mapping):
                continue
            if request.get("response_validity") != _SUPERSEDED_RESPONSE_STATUS:
                continue
            response_ref = request.get("response_event_ref")
            if isinstance(response_ref, str) and response_ref:
                refs.add(response_ref)
        return refs

    def _interaction_refs(self) -> tuple[list[dict[str, Any]], set[str], int]:
        handles, refs, total = super()._interaction_refs()
        superseded = self._superseded_house_response_refs()
        if not superseded:
            return handles, refs, total
        filtered = [row for row in handles if str(row.get("interaction_ref", "")) not in superseded]
        return filtered, refs - superseded, max(0, total - len(superseded))

    def _direct_family_scene_people(self, player_id: str, player_location: object) -> list[dict[str, Any]]:
        """Return exact direct family at the player's exact saved location.

        Exact location equality proves co-location at the registered location,
        but a capital/city/fort/market is not an immediate room.  Rows therefore
        carry an explicit ``presence`` classification so broad-place matches are
        exposed as nearby rather than silently promoted to immediate witnesses.
        """
        if not isinstance(player_location, str) or not player_location:
            return []
        family = self._read_optional_mapping("state/family/index.json")
        owner_index = self._read_optional_mapping("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
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
                record = self._read_optional_mapping(path)
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
                record = self._read_optional_mapping(path)
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

        location_kind: str | None = None
        locations = self._read_optional_mapping("game/data/world/locations.json")
        location_rows = locations.get("locations", []) if isinstance(locations, Mapping) else []
        if isinstance(location_rows, list):
            for location_row in location_rows:
                if isinstance(location_row, Mapping) and location_row.get("ref") == player_location:
                    value = location_row.get("kind")
                    location_kind = str(value) if isinstance(value, str) else None
                    break
        presence = "present" if location_kind in _IMMEDIATE_SCENE_LOCATION_KINDS else "nearby"

        rows: list[dict[str, Any]] = []
        for person_ref in sorted(relations)[:_DIRECT_FAMILY_LIMIT]:
            path = owners.get(person_ref)
            if not isinstance(path, str):
                continue
            person = self._read_optional_mapping(path)
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
                "location_kind": location_kind,
                "presence": presence,
            })
        return rows

    def _validate_interaction_authority(self, command) -> None:
        """Validate against final context so exact present family can receive interactions."""
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
        superseded = self._superseded_house_response_refs()

        target_ref = payload["target_ref"]
        target_visible = (
            target_ref in permitted
            or (
                target_ref not in superseded
                and triggered_interaction_record(self.store, target_ref) is not None
            )
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
            and (
                process_ref in superseded
                or triggered_interaction_record(self.store, process_ref) is None
            )
        ):
            raise OperationError(404, "interaction_process_not_player_visible")
        if any(ref not in controlled_refs for ref in payload["formation_refs"]):
            raise OperationError(403, "interaction_formation_not_controlled")

    def play_context(self):
        context = super().play_context()
        retinue_rows, retinue_object_refs, retinue_person_refs = self._retinue_projection()
        if retinue_rows:
            context["retinue_command_groups"] = retinue_rows
            context["retinue_command_groups_count"] = len(retinue_rows)
            permitted_objects = set(context.get("permitted_object_refs", []))
            permitted_objects.update(retinue_object_refs)
            for row in retinue_rows:
                permitted_objects.update(row.get("direct_formation_refs", []))
            context["permitted_object_refs"] = sorted(permitted_objects)
            permitted_people = set(context.get("permitted_person_ids", []))
            permitted_people.update(retinue_person_refs)
            context["permitted_person_ids"] = sorted(permitted_people)
            context.setdefault("read_hints", {})["retinue_hierarchy"] = {
                "rule": "The root and immediate command layer are projected. Inspect an exact permitted subordinate command_group_ref for deeper hierarchy detail."
            }
        player = context.setdefault("player", {})
        player_id = str(context.get("campaign", {}).get("player_id", ""))
        player_location = player.get("location")
        family_people = self._direct_family_scene_people(player_id, player_location)

        if family_people:
            scene = context.setdefault("scene", {})
            cast = scene.get("scene_cast")
            cast = dict(cast) if isinstance(cast, Mapping) else {}
            present = cast.get("present_people", [])
            nearby = cast.get("nearby_people", [])
            present_rows = [dict(row) for row in present if isinstance(row, Mapping)] if isinstance(present, list) else []
            nearby_rows = [dict(row) for row in nearby if isinstance(row, Mapping)] if isinstance(nearby, list) else []
            present_by_id = {
                str(row.get("person_id")): row
                for row in present_rows
                if isinstance(row.get("person_id"), str)
            }
            nearby_by_id = {
                str(row.get("person_id")): row
                for row in nearby_rows
                if isinstance(row.get("person_id"), str)
            }
            for row in family_people:
                clean = dict(row)
                presence = clean.pop("presence", "nearby")
                person_ref = str(clean["person_id"])
                if presence == "present":
                    present_by_id[person_ref] = clean
                    nearby_by_id.pop(person_ref, None)
                elif person_ref not in present_by_id:
                    nearby_by_id[person_ref] = clean
            cast["present_people"] = [present_by_id[key] for key in sorted(present_by_id)]
            cast["nearby_people"] = [nearby_by_id[key] for key in sorted(nearby_by_id)]
            cast.setdefault("visible_people", [])
            cast.setdefault("referenced_people", [])
            cast["presence_rule"] = (
                "Exact same-place data is scale-aware: hall/office/scene-venue/training-ground matches may establish immediate presence; "
                "capital/city/fort/market/depot/regional matches establish nearby co-location only and never prove same-room witnessing."
            )
            scene["scene_cast"] = cast

            contract = scene.get("scene_local_narration_contract")
            contract = dict(contract) if isinstance(contract, Mapping) else {}
            contract["co_located_social_rule"] = (
                "A person in scene_cast.present_people is immediately accessible for ordinary local conversation. "
                "A person only in nearby_people shares the broader registered place but may require a local approach/contact handoff before substantive interaction."
            )
            scene["scene_local_narration_contract"] = contract

            permitted_people = set(context.get("permitted_person_ids", []))
            permitted_people.update(str(row["person_id"]) for row in family_people)
            context["permitted_person_ids"] = sorted(permitted_people)

            # Sword Manor is an exact House Tang institution/force owner. While Wei
            # is physically inside the Tang Manor household scene, exposing this
            # one known institutional handle permits bounded inspection without
            # turning the owner index into a browseable world dump.
            if isinstance(player_location, str) and player_location.startswith("loc_tang_manor_"):
                owner_index = self._read_optional_mapping("state/index/owner-index.json")
                owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
                if isinstance(owners, Mapping) and isinstance(owners.get(_SWORD_MANOR_REF), str):
                    permitted_objects = set(context.get("permitted_object_refs", []))
                    permitted_objects.add(_SWORD_MANOR_REF)
                    context["permitted_object_refs"] = sorted(permitted_objects)
                    scene["household_institutions"] = [{
                        "object_ref": _SWORD_MANOR_REF,
                        "name": "Sword Manor",
                        "relation": "House Tang institution",
                    }]

        interaction = context.get("commands", {}).get("command_types", {}).get("interaction_action")
        if isinstance(interaction, dict):
            guidance = interaction.setdefault("input_guidance", {})
            guidance["seek_contact_rule"] = (
                "Do not use seek_contact for a person already listed in scene.scene_cast.present_people. "
                "Ordinary local conversation begins directly; seek_contact is for a person/channel not presently accessible."
            )
        return context


__all__ = ["HouseholdAwareCampaignOperations"]
