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
_SWORD_MANOR_REF = "force_sword_manor"
_PLAYER_RETINUE_ROOT = "cmdgrp.tang_wei.personal_force"


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
    def _institutional_audiences_for_person(person: Mapping[str, Any]) -> list[str]:
        state = str(person.get("state", "")).strip().lower()
        if not state:
            background = person.get("background") if isinstance(person.get("background"), Mapping) else {}
            state = str(background.get("origin", "")).strip().lower()
        if not state:
            return []
        archetype = str(person.get("role_archetype", person.get("role", ""))).strip().lower()
        audiences: set[str] = set()
        if any(token in archetype for token in ("ruler", "official", "chancellor", "minister", "court", "diplomat", "royal_pretender")):
            audiences.add(f"audience:state_{state}:court")
            audiences.add(f"audience:state_{state}:nobility")
        if any(token in archetype for token in ("general", "commander", "officer", "strategist", "marshal")):
            audiences.add(f"audience:state_{state}:military_officers")
        return sorted(audiences)

    def _institutional_identity_awareness(self, observer_ref: str, subject_ref: str) -> dict[str, Any] | None:
        owners = self._read_optional_mapping("state/index/owner-index.json")
        owner_map = owners.get("owners", {}) if isinstance(owners, Mapping) else {}
        observer_path = owner_map.get(observer_ref) if isinstance(owner_map, Mapping) else None
        observer = self._read_optional_mapping(observer_path) if isinstance(observer_path, str) else None
        if not isinstance(observer, Mapping):
            return None
        registry = self._read_optional_mapping("state/information/institutional-awareness.json")
        subjects = registry.get("subjects", {}) if isinstance(registry, Mapping) else {}
        subject = subjects.get(subject_ref) if isinstance(subjects, Mapping) else None
        if not isinstance(subject, Mapping):
            return None
        audience_rows = subject.get("audiences", {}) if isinstance(subject.get("audiences"), Mapping) else {}
        matched: list[tuple[str, Mapping[str, Any]]] = []
        for audience_ref in self._institutional_audiences_for_person(observer):
            row = audience_rows.get(audience_ref) if isinstance(audience_rows, Mapping) else None
            if isinstance(row, Mapping):
                matched.append((audience_ref, row))
        if not matched:
            return None
        known: set[str] = set()
        restricted: set[str] = set()
        statuses: set[str] = set()
        for audience_ref, row in matched:
            statuses.add(str(row.get("status", "institutionally_known")))
            known.update(str(value) for value in row.get("known_fact_classes", []) if isinstance(value, str))
            restricted.update(str(value) for value in row.get("restricted_fact_classes", []) if isinstance(value, str))
        return {
            "status": "widely_known_in_network" if "widely_known_in_network" in statuses else "institutionally_known",
            "audience_refs": [ref for ref, _row in matched],
            "known_fact_classes": sorted(known),
            "restricted_fact_classes": sorted(restricted),
            "relationship_rule": "identity awareness is not friendship, trust, loyalty, consent, or a personal relationship",
        }

    def _decorate_present_identity_awareness(self, context: dict[str, Any]) -> None:
        scene = context.get("scene")
        cast = scene.get("scene_cast") if isinstance(scene, Mapping) else None
        present = cast.get("present_people") if isinstance(cast, Mapping) else None
        if not isinstance(present, list):
            return
        subject_ref = str(context.get("campaign", {}).get("player_id", ""))
        if not subject_ref:
            return
        for row in present:
            if not isinstance(row, dict):
                continue
            observer_ref = row.get("person_id")
            if not isinstance(observer_ref, str):
                continue
            awareness = self._institutional_identity_awareness(observer_ref, subject_ref)
            if awareness:
                row["player_identity_awareness"] = awareness
        contract = scene.get("scene_local_narration_contract")
        contract = dict(contract) if isinstance(contract, Mapping) else {}
        contract["institutional_identity_rule"] = (
            "If a present NPC carries player_identity_awareness, they may recognize Tang Wei from that saved institutional network without a personal relationship edge. "
            "Use only the listed public fact classes; never infer private stats, secrets, exact confidential force strength, affection, trust, or loyalty. "
            "Absence of this cue does not prove ignorance if direct personal knowledge is separately established."
        )
        scene["scene_local_narration_contract"] = contract

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
            location for row in doc.get("units", [])
            if isinstance(row, Mapping) and row.get("kind") == "formation" and isinstance(row.get("ref"), str)
            and (location := self._exact_object_location(str(row.get("ref"))))
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
        for child_ref in [row.get("ref") for row in root.get("units", []) if isinstance(row, Mapping) and row.get("kind") == "nested_army"]:
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
            subordinate_refs = [str(row.get("ref")) for row in doc.get("units", []) if isinstance(row, Mapping) and row.get("kind") == "nested_army" and isinstance(row.get("ref"), str)]
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
                "units": [dict(row) for row in doc.get("units", []) if isinstance(row, Mapping)],
                "direct_formation_refs": [str(row.get("ref")) for row in doc.get("units", []) if isinstance(row, Mapping) and row.get("kind") == "formation" and isinstance(row.get("ref"), str)],
                "nested_army_refs": subordinate_refs,
                "familiarity_milli": doc.get("familiarity_milli", 0),
                "verified_group_training_hours": doc.get("verified_group_training_hours", 0),
                "active_context_ref": doc.get("active_context_ref"),
                "communication_ref": doc.get("communication_ref"),
                "current_location_ref": current_location_ref,
                "location_basis": location_basis,
            })
        return rows, object_refs, person_refs

    def _generic_scene_people(self, context: Mapping[str, Any], player_location: object) -> list[dict[str, Any]]:
        """Return bounded exact people whose saved duties and location support scene participation.

        This is discovery, never presence authority by itself. Every candidate is
        revalidated against the exact person's current location, and broad places
        become ``nearby`` rather than same-room ``present``. The candidate set is
        built from already player-visible people, controlled formations, and House
        Tang/Sword Manor command routing rather than a global person scan.
        """
        if not isinstance(player_location, str) or not player_location:
            return []
        owners_doc = self._read_optional_mapping("state/index/owner-index.json")
        owners = owners_doc.get("owners", {}) if isinstance(owners_doc, Mapping) else {}
        if not isinstance(owners, Mapping):
            return []
        candidates: dict[str, set[str]] = {}
        def add(ref: object, basis: str) -> None:
            if isinstance(ref, str) and ref.startswith("char_"):
                candidates.setdefault(ref, set()).add(basis)

        for ref in context.get("permitted_person_ids", []) if isinstance(context.get("permitted_person_ids"), list) else []:
            add(ref, "already_player_visible")

        # Commanders/deputies of formations currently controlled by Wei are lawful
        # scene candidates; exact location still decides whether they are nearby.
        for row in context.get("controlled_formations", []) if isinstance(context.get("controlled_formations"), list) else []:
            if not isinstance(row, Mapping):
                continue
            fref = row.get("formation_ref")
            path = owners.get(fref) if isinstance(fref, str) else None
            formation = self._read_optional_mapping(path) if isinstance(path, str) else None
            if isinstance(formation, Mapping):
                add(formation.get("commander_ref"), "controlled_formation_command")
                add(formation.get("deputy_ref"), "controlled_formation_command")

        # House Tang/Sword Manor high command is a bounded explicit hierarchy.
        # This makes a real training-ground/council cast discoverable without
        # scanning every exact character in the world.
        group_index = self._read_optional_mapping("state/cmd/command-groups/index.json")
        group_refs = group_index.get("refs", []) if isinstance(group_index, Mapping) else []
        allowed_authorities = {"house_tang", "force_sword_manor", "char_tang_wei", "pforce.tang_wei", "force_tang_wei_personal"}
        if isinstance(group_refs, list):
            for group_ref in group_refs:
                path = self._command_group_path(group_ref) if isinstance(group_ref, str) else None
                group = self._read_optional_mapping(path) if isinstance(path, str) else None
                if not isinstance(group, Mapping) or str(group.get("authority_ref")) not in allowed_authorities:
                    continue
                add(group.get("commander_ref"), "house_or_command_duty")
                add(group.get("deputy_ref"), "house_or_command_duty")
                for ref in group.get("direct_person_refs", []) if isinstance(group.get("direct_person_refs"), list) else []:
                    add(ref, "house_or_command_duty")

        # Active durable processes and fresh scene/event routing may establish other
        # named participants without granting universal world visibility.
        for process in context.get("active_player_processes", []) if isinstance(context.get("active_player_processes"), list) else []:
            if not isinstance(process, Mapping):
                continue
            for key in ("issuer_ref", "subject_ref", "obligor_ref", "beneficiary_ref"):
                add(process.get(key), "active_process")
        scene = context.get("scene")
        if isinstance(scene, Mapping):
            for field in ("present_people", "visible_people", "nearby_people", "referenced_people"):
                rows = scene.get("scene_cast", {}).get(field, []) if isinstance(scene.get("scene_cast"), Mapping) else []
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, Mapping):
                            add(row.get("person_id"), "established_scene")

        locations = self._read_optional_mapping("game/data/world/locations.json")
        location_rows = locations.get("locations", []) if isinstance(locations, Mapping) else []
        location_kind = None
        if isinstance(location_rows, list):
            for row in location_rows:
                if isinstance(row, Mapping) and row.get("ref") == player_location:
                    location_kind = str(row.get("kind", "")); break
        immediate = location_kind in _IMMEDIATE_SCENE_LOCATION_KINDS
        result: list[dict[str, Any]] = []
        for person_ref in sorted(candidates):
            if person_ref == context.get("campaign", {}).get("player_id"):
                continue
            path = owners.get(person_ref)
            person = self._read_optional_mapping(path) if isinstance(path, str) else None
            if not isinstance(person, Mapping) or _person_location(person) != player_location:
                continue
            life = str(person.get("life_status", "active")).lower()
            if life in {"dead", "deceased", "missing"}:
                continue
            result.append({
                "person_id": person_ref,
                "name": person.get("name"),
                "role": person.get("role"),
                "location": player_location,
                "presence": "present" if immediate else "nearby",
                "scene_basis": sorted(candidates[person_ref]),
            })
        return result

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
        generic_people = self._generic_scene_people(context, player_location)

        if generic_people:
            scene = context.setdefault("scene", {})
            cast = scene.get("scene_cast")
            cast = dict(cast) if isinstance(cast, Mapping) else {}
            present_rows = [dict(row) for row in cast.get("present_people", []) if isinstance(row, Mapping)] if isinstance(cast.get("present_people"), list) else []
            nearby_rows = [dict(row) for row in cast.get("nearby_people", []) if isinstance(row, Mapping)] if isinstance(cast.get("nearby_people"), list) else []
            present_by_id = {str(row.get("person_id")): row for row in present_rows if isinstance(row.get("person_id"), str)}
            nearby_by_id = {str(row.get("person_id")): row for row in nearby_rows if isinstance(row.get("person_id"), str)}
            for row in generic_people:
                clean = dict(row); presence = clean.pop("presence", "nearby"); ref = str(clean["person_id"])
                if presence == "present":
                    present_by_id.setdefault(ref, clean); nearby_by_id.pop(ref, None)
                elif ref not in present_by_id:
                    nearby_by_id.setdefault(ref, clean)
            cast["present_people"] = [present_by_id[key] for key in sorted(present_by_id)]
            cast["nearby_people"] = [nearby_by_id[key] for key in sorted(nearby_by_id)]
            cast.setdefault("visible_people", [])
            cast.setdefault("referenced_people", [])
            cast["generic_participation_rule"] = (
                "Named people are surfaced only from player-visible, controlled-command, House/institution, active-process, or already-established scene routing, then revalidated against exact current location. Broad-place co-location is nearby, never automatic same-room presence."
            )
            scene["scene_cast"] = cast
            permitted_people = set(context.get("permitted_person_ids", []))
            permitted_people.update(str(row["person_id"]) for row in generic_people)
            context["permitted_person_ids"] = sorted(permitted_people)

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

            # Sword Manor is an exact House Tang military-force owner. While Wei
            # is physically inside the Tang Manor household scene, exposing this
            # one known military handle permits bounded inspection without
            # turning the owner index into a browseable world dump.
            if isinstance(player_location, str) and player_location.startswith("loc_tang_manor_"):
                owner_index = self._read_optional_mapping("state/index/owner-index.json")
                owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
                if isinstance(owners, Mapping) and isinstance(owners.get(_SWORD_MANOR_REF), str):
                    permitted_objects = set(context.get("permitted_object_refs", []))
                    permitted_objects.add(_SWORD_MANOR_REF)
                    context["permitted_object_refs"] = sorted(permitted_objects)
                    scene["household_military_forces"] = [{
                        "object_ref": _SWORD_MANOR_REF,
                        "name": "Sword Manor",
                        "relation": "House Tang military force",
                    }]

        self._decorate_present_identity_awareness(context)

        interaction = context.get("commands", {}).get("command_types", {}).get("interaction_action")
        if isinstance(interaction, dict):
            guidance = interaction.setdefault("input_guidance", {})
            guidance["seek_contact_rule"] = (
                "Do not use seek_contact for a person already listed in scene.scene_cast.present_people. "
                "Ordinary local conversation begins directly; seek_contact is for a person/channel not presently accessible."
            )
        return context


__all__ = ["HouseholdAwareCampaignOperations"]
