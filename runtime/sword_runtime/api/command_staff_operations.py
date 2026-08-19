"""Player-safe projection of exact controlled-formation command detail.

Formation owners remain the sole authority for commander/deputy assignment and
force owners remain the sole authority for cohort manpower/capability. This
surface rehydrates those exact owners into bounded command views so a player
commander can inspect the officers and troop capability that are lawfully under
his command without exposing unrelated NPC private state or creating a second
military authority.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Optional

from sword_runtime.api.household_operations import HouseholdAwareCampaignOperations
from sword_runtime.cohort_tx_support import project_person_lite_stats
from sword_runtime.warfare_depth import build_formation_command_structure
from sword_runtime.warfare_depth_integrity import resolve_scoped_formation_profile

_RULES_PATH = "game/data/mechanics/warfare-organization.json"
_COMMAND_PERSON_INDEX_PATH = "state/cmd/command-personnel.json"
_COMMAND_SERVICE_FIELDS = (
    "name",
    "life_status",
    "role",
    "rank",
    "authority",
    "affiliation",
    "current_formation_id",
    "current_location",
    "location",
    "location_ref",
    "health",
    "fatigue",
    "attributes",
    "aptitude",
    "skills",
    "specializations",
    "equipment_loadout_id",
)


class CommandStaffAwareCampaignOperations(HouseholdAwareCampaignOperations):
    """Expose bounded command establishment, troop capability, and service sheets."""

    def _formation_record(self, formation_ref: object) -> Mapping[str, Any] | None:
        if not isinstance(formation_ref, str) or not formation_ref:
            return None
        owner_index = self._read_optional_mapping("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        path = owners.get(formation_ref) if isinstance(owners, Mapping) else None
        if not isinstance(path, str):
            return None
        formation = self._read_optional_mapping(path)
        return formation if isinstance(formation, Mapping) else None

    def _command_staff_for_formation(self, formation_ref: object) -> dict[str, str]:
        formation = self._formation_record(formation_ref)
        if not isinstance(formation, Mapping):
            return {}
        staff: dict[str, str] = {}
        for field in ("commander_ref", "deputy_ref"):
            value = formation.get(field)
            if isinstance(value, str) and value:
                staff[field] = value
        return staff

    def _command_structure_for_formation(self, formation_ref: object) -> dict[str, Any]:
        formation = self._formation_record(formation_ref)
        if not isinstance(formation, Mapping):
            return {}
        rules = self._read_optional_mapping(_RULES_PATH)
        if not isinstance(rules, Mapping):
            return {}
        profile = resolve_scoped_formation_profile(formation, rules)
        if isinstance(profile, Mapping) and profile:
            adjusted = copy.deepcopy(dict(rules))
            profiles = adjusted.get("formation_profiles", {})
            profiles = dict(profiles) if isinstance(profiles, Mapping) else {}
            profiles[str(formation.get("formation_ref", formation_ref))] = copy.deepcopy(dict(profile))
            adjusted["formation_profiles"] = profiles
            rules = adjusted
        return build_formation_command_structure(formation, rules)

    @staticmethod
    def _command_refs(structure: Mapping[str, Any], formation: Mapping[str, Any] | None = None) -> dict[str, str]:
        refs: dict[str, str] = {}

        def add(value: Any, role: str) -> None:
            if isinstance(value, str) and value:
                refs.setdefault(value, role)

        unit_command = structure.get("unit_command")
        if isinstance(unit_command, Mapping):
            add(unit_command.get("named_commander_ref"), "persistent_unit_commander")
            add(unit_command.get("named_deputy_ref"), "persistent_unit_deputy")
            values = unit_command.get("unit_cell_commander_refs")
            if isinstance(values, list):
                for value in values:
                    add(value, "persistent_unit_commander")
            values = unit_command.get("unit_cell_deputy_refs")
            if isinstance(values, list):
                for value in values:
                    add(value, "persistent_unit_deputy")
        cells = structure.get("unit_command_cells")
        if isinstance(cells, list):
            for cell in cells:
                if not isinstance(cell, Mapping):
                    continue
                add(cell.get("commander_ref"), "persistent_unit_commander")
                add(cell.get("deputy_ref"), "persistent_unit_deputy")
                for value in cell.get("internal_1000_commander_refs", []) if isinstance(cell.get("internal_1000_commander_refs"), list) else []:
                    add(value, "internal_1000_commander")
                for value in cell.get("internal_500_commander_refs", []) if isinstance(cell.get("internal_500_commander_refs"), list) else []:
                    add(value, "internal_500_commander")
        if isinstance(formation, Mapping):
            saved = formation.get("command_structure", {}) if isinstance(formation.get("command_structure"), Mapping) else {}
            saved_unit = saved.get("unit_command", {}) if isinstance(saved.get("unit_command"), Mapping) else {}
            add(formation.get("commander_ref"), "persistent_unit_commander")
            add(formation.get("deputy_ref"), "persistent_unit_deputy")
            add(saved_unit.get("commander_ref"), "persistent_unit_commander")
            add(saved_unit.get("deputy_ref"), "persistent_unit_deputy")
            internal = saved.get("internal_person_refs", []) if isinstance(saved.get("internal_person_refs"), list) else []
            if not internal and isinstance(formation.get("embedded_person_refs"), list):
                internal = formation.get("embedded_person_refs", [])
            for value in internal:
                text = str(value)
                role = "internal_1000_commander" if ".1000." in text else ("internal_500_commander" if ".500." in text else "internal_commander")
                add(value, role)
        return refs

    def _command_refs_for_formation(self, formation_ref: str) -> dict[str, str]:
        formation = self._formation_record(formation_ref)
        if not isinstance(formation, Mapping):
            return {}
        return self._command_refs(self._command_structure_for_formation(formation_ref), formation)

    def _command_person_record(self, person_ref: str) -> Mapping[str, Any] | None:
        index = self._read_optional_mapping(_COMMAND_PERSON_INDEX_PATH)
        records = index.get("record_index", {}) if isinstance(index, Mapping) else {}
        path = records.get(person_ref) if isinstance(records, Mapping) else None
        if not isinstance(path, str):
            return None
        record = self._read_optional_mapping(path)
        return record if isinstance(record, Mapping) else None

    def _source_force_for_formation(self, formation: Mapping[str, Any]) -> Mapping[str, Any] | None:
        force_ref = formation.get("owner_force_ref")
        if not isinstance(force_ref, str) or not force_ref:
            return None
        owner_index = self._read_optional_mapping("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        force_path = owners.get(force_ref) if isinstance(owners, Mapping) else None
        if not isinstance(force_path, str):
            return None
        force = self._read_optional_mapping(force_path)
        return force if isinstance(force, Mapping) else None

    @staticmethod
    def _source_cohort_for_person_lite(
        force: Mapping[str, Any],
        formation: Mapping[str, Any],
        person_ref: str,
        role_label: str,
    ) -> tuple[str, Mapping[str, Any]] | tuple[None, None]:
        ledger = force.get("cohort_ledger", {}) if isinstance(force.get("cohort_ledger"), Mapping) else {}
        cohorts = ledger.get("cohorts", {}) if isinstance(ledger.get("cohorts"), Mapping) else {}
        if not isinstance(cohorts, Mapping):
            return None, None
        assignments = force.get("materialized_assignments", {}) if isinstance(force.get("materialized_assignments"), Mapping) else {}
        assignment = assignments.get(person_ref, {}) if isinstance(assignments, Mapping) else {}
        source_role = str(assignment.get("role", "")) if isinstance(assignment, Mapping) else ""
        if not source_role and role_label in {"persistent_unit_commander", "persistent_unit_deputy"}:
            source_role = "command_personnel"
        formation_ref = str(formation.get("formation_ref", ""))
        candidates: list[tuple[int, str, Mapping[str, Any]]] = []
        for cohort_id, cohort in cohorts.items():
            if not isinstance(cohort, Mapping):
                continue
            role = str(cohort.get("role", ""))
            allocated = cohort.get("allocated_by_formation", {}) if isinstance(cohort.get("allocated_by_formation"), Mapping) else {}
            score = 0
            if source_role and role == source_role:
                score += 4
            if int(allocated.get(formation_ref, 0) or 0) > 0:
                score += 2
            if role_label.startswith("internal_") and role == source_role:
                score += 2
            if score > 0 and (cohort.get("attribute_means") or cohort.get("skill_means")):
                candidates.append((-score, str(cohort_id), cohort))
        if not candidates:
            for item in formation.get("cohort_composition", []):
                if not isinstance(item, Mapping):
                    continue
                cohort_id = str(item.get("cohort_id", ""))
                cohort = cohorts.get(cohort_id)
                if isinstance(cohort, Mapping) and (cohort.get("attribute_means") or cohort.get("skill_means")):
                    candidates.append((0, cohort_id, cohort))
        if not candidates:
            return None, None
        candidates.sort(key=lambda row: (row[0], row[1]))
        _score, cohort_id, cohort = candidates[0]
        return cohort_id, cohort

    def _person_lite_service_sheet(
        self,
        person_ref: str,
        formation_ref: str,
        role_label: str,
    ) -> dict[str, Any] | None:
        formation = self._formation_record(formation_ref)
        if not isinstance(formation, Mapping):
            return None
        record = self._command_person_record(person_ref)
        projected: dict[str, Any] = {
            "person_id": person_ref,
            "representation": "person_lite",
            "role": role_label,
            "current_formation_id": formation_ref,
            "current_location": formation.get("location_ref"),
        }
        if isinstance(record, Mapping):
            command = record.get("command", {}) if isinstance(record.get("command"), Mapping) else {}
            stats = record.get("stats", {}) if isinstance(record.get("stats"), Mapping) else {}
            projected["role"] = command.get("role", role_label)
            projected["current_location"] = record.get("current_location", formation.get("location_ref"))
            projected["attributes"] = dict(stats.get("attributes", {})) if isinstance(stats.get("attributes"), Mapping) else {}
            projected["skills"] = dict(stats.get("skills", {})) if isinstance(stats.get("skills"), Mapping) else {}
            projected["aptitude"] = dict(record.get("aptitude", {})) if isinstance(record.get("aptitude"), Mapping) else {}
            development = record.get("development_state", {}) if isinstance(record.get("development_state"), Mapping) else {}
            projected["development"] = {
                "verified_training_hours": development.get("verified_training_hours", 0.0),
                "verified_role_exposure_hours": development.get("verified_role_exposure_hours", 0.0),
                "deterministic_training_cursor": development.get("deterministic_training_cursor", development.get("smart_training_cursor", 0)),
                "last_training_program_ref": development.get("last_training_program_ref"),
            }
            projected["source_cohort_ref"] = record.get("source_cohort_ref")
            return projected
        force = self._source_force_for_formation(formation)
        if not isinstance(force, Mapping):
            return projected
        cohort_id, cohort = self._source_cohort_for_person_lite(force, formation, person_ref, role_label)
        if isinstance(cohort, Mapping):
            stats = project_person_lite_stats(
                cohort, person_ref, command_rank=role_label,
                loadout_id=str(formation.get("registered_loadout_ref") or "loadout_house_guard"),
            )
            projected["attributes"] = stats["attributes"]
            projected["skills"] = stats["skills"]
            projected["aptitude"] = stats["aptitude"]
            projected["source_cohort_ref"] = cohort_id
            projected["development"] = {
                "verified_training_hours": cohort.get("verified_training_hours_per_person", 0.0),
                "verified_role_exposure_hours": cohort.get("verified_role_exposure_hours_per_person", 0.0),
                "projection_status": "deterministic_from_conserved_source_until_first_person_lite_development_write",
            }
        return projected

    def _troop_capability_for_formation(self, formation_ref: object) -> dict[str, Any]:
        formation = self._formation_record(formation_ref)
        if not isinstance(formation_ref, str) or not isinstance(formation, Mapping):
            return {}
        force_ref = formation.get("owner_force_ref")
        if not isinstance(force_ref, str) or not force_ref:
            return {
                "formation_personnel": max(0, int(formation.get("personnel", 0) or 0)),
                "cohort_personnel": 0,
                "unprojected_personnel": max(0, int(formation.get("personnel", 0) or 0)),
                "cohorts": [],
                "note": "No exact source-force cohort ledger is registered for this formation.",
            }
        owner_index = self._read_optional_mapping("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        force_path = owners.get(force_ref) if isinstance(owners, Mapping) else None
        if not isinstance(force_path, str):
            return {}
        force = self._read_optional_mapping(force_path)
        ledger = force.get("cohort_ledger") if isinstance(force, Mapping) else None
        cohorts = ledger.get("cohorts", {}) if isinstance(ledger, Mapping) else {}
        projected: list[dict[str, Any]] = []
        cohort_personnel = 0
        if isinstance(cohorts, Mapping):
            for cohort_id, cohort in sorted(cohorts.items()):
                if not isinstance(cohort, Mapping):
                    continue
                allocations = cohort.get("allocated_by_formation")
                count = int(allocations.get(formation_ref, 0) or 0) if isinstance(allocations, Mapping) else 0
                if count <= 0:
                    continue
                cohort_personnel += count
                projected.append({
                    "cohort_id": str(cohort_id),
                    "role": cohort.get("role"),
                    "personnel": count,
                    "age_distribution": cohort.get("age_distribution", {}),
                    "aptitude_means": cohort.get("aptitude_means", {}),
                    "attribute_means": cohort.get("attribute_means", {}),
                    "skill_means": cohort.get("skill_means", {}),
                    "service_months_mean": cohort.get("service_months_mean", 0.0),
                    "verified_training_hours_per_person": cohort.get("verified_training_hours_per_person", 0.0),
                    "verified_role_exposure_hours_per_person": cohort.get("verified_role_exposure_hours_per_person", 0.0),
                    "tags": cohort.get("tags", []),
                })
        formation_personnel = max(0, int(formation.get("personnel", 0) or 0))
        return {
            "source_force_ref": force_ref,
            "formation_personnel": formation_personnel,
            "cohort_personnel": cohort_personnel,
            "unprojected_personnel": max(0, formation_personnel - cohort_personnel),
            "cohorts": projected,
            "accounting_rule": (
                "Cohort rows are exact conserved source-force bodies allocated to this formation. "
                "Any unprojected personnel remain conserved in other exact representations, such as materialized assignments; no bodies are invented here."
            ),
        }

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
                if isinstance(value, str) and value
            }
            staff_by_formation[formation_ref] = staff
            permitted_people.update(staff.values())
            permitted_people.update(self._command_refs_for_formation(formation_ref))
        context["permitted_person_ids"] = sorted(permitted_people)

        read_hints = context.setdefault("read_hints", {})
        read_hints["controlled_formation_command_detail"] = {
            "rule": (
                "Inspect one exact controlled formation_ref for its current command-structure projection and "
                "conserved cohort capability breakdown. Every returned exact or person-lite command ref is a "
                "permitted person read with bounded command-service stats."
            )
        }

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

    def _exact_controlled_command_role(self, person_id: str) -> tuple[str, str] | None:
        """Revalidate one exact command person without relying on hot-context truncation.

        Projection limits bound handoff size, not lawful command visibility.  This
        path follows only the person's already-routed current formation and then
        verifies that exact formation remains under the player's authority.
        """
        record = self._command_person_record(person_id)
        if not isinstance(record, Mapping) and person_id.startswith("char_"):
            owner_index = self._read_optional_mapping("state/index/owner-index.json")
            owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
            path = owners.get(person_id) if isinstance(owners, Mapping) else None
            if isinstance(path, str):
                record = self._read_optional_mapping(path)
        if not isinstance(record, Mapping):
            return None
        formation_ref = record.get("current_formation_id")
        if not isinstance(formation_ref, str) or not formation_ref:
            assignment = record.get("command_assignment") if isinstance(record.get("command_assignment"), Mapping) else {}
            formation_ref = assignment.get("formation_ref") if isinstance(assignment, Mapping) else None
        if not isinstance(formation_ref, str) or not formation_ref:
            return None
        formation = self._formation_record(formation_ref)
        if not isinstance(formation, Mapping):
            return None
        player_id = self._player_actor()
        if formation.get("command_authority") != player_id and formation.get("administrative_owner") not in {player_id, "house_tang"}:
            return None
        role = self._command_refs_for_formation(formation_ref).get(person_id)
        if not isinstance(role, str) or not role:
            return None
        return formation_ref, role

    def person_sheet(self, person_id: str) -> dict[str, Any]:
        context = self.play_context()
        if person_id == context.get("campaign", {}).get("player_id"):
            return super().person_sheet(person_id)
        command_refs: dict[str, tuple[str, str]] = {}
        for row in context.get("controlled_formations", []):
            if not isinstance(row, Mapping):
                continue
            formation_ref = row.get("formation_ref")
            if not isinstance(formation_ref, str):
                continue
            for ref, role in self._command_refs_for_formation(formation_ref).items():
                command_refs.setdefault(ref, (formation_ref, role))
        if person_id in command_refs:
            formation_ref, role_label = command_refs[person_id]
        else:
            exact = self._exact_controlled_command_role(person_id)
            if exact is None:
                return super().person_sheet(person_id)
            formation_ref, role_label = exact
        if not person_id.startswith("char_"):
            projected = self._person_lite_service_sheet(person_id, formation_ref, role_label)
            if isinstance(projected, Mapping):
                return {
                    "visibility": "player_visible_command_service_sheet",
                    "person": dict(projected),
                    "scope": (
                        "Command-relevant person-lite service capability only. The officer is one already-conserved "
                        "body; private motives, relationships, hidden knowledge and unrelated personal state remain excluded."
                    ),
                }
            return super().person_sheet(person_id)
        owner_index = self._read_optional_mapping("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        path = owners.get(person_id) if isinstance(owners, Mapping) else None
        if not isinstance(path, str):
            return super().person_sheet(person_id)
        person = self._read_optional_mapping(path)
        if not isinstance(person, Mapping):
            return super().person_sheet(person_id)
        projected = {"person_id": person_id, "representation": "full_character"}
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

    def inspect_game_object(self, object_ref: str) -> dict[str, Any]:
        result = dict(super().inspect_game_object(object_ref))
        obj = result.get("object")
        if object_ref.startswith("formation_") and isinstance(obj, Mapping):
            enriched = self._enrich_formation_row(obj)
            structure = self._command_structure_for_formation(object_ref)
            enriched["command_structure"] = structure
            enriched["troop_capability"] = self._troop_capability_for_formation(object_ref)
            refs = self._command_refs(structure, self._formation_record(object_ref))
            person_lite = [
                {"person_ref": ref, "role": role, "representation": "person_lite"}
                for ref, role in sorted(refs.items())
                if not ref.startswith("char_")
            ]
            enriched["person_lite_officers"] = person_lite
            enriched["person_lite_officer_count"] = len(person_lite)
            enriched["command_service_read_rule"] = (
                "Pass any exact or person-lite officer ref returned here to get_person_sheet for bounded command-service stats."
            )
            result["object"] = enriched
        return result


__all__ = ["CommandStaffAwareCampaignOperations"]
