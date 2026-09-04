"""Bounded player-facing operations shared by REST and MCP surfaces."""
from __future__ import annotations

from sword_runtime.combat_doctrine import load_personal_combat_doctrine

from typing import Any, Mapping, Optional

from sword_runtime.api.input_guidance import COMMAND_INPUT_GUIDANCE, INPUT_GUIDANCE_POLICY
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import COMMAND_TYPES
from sword_runtime.fatigue import RULES_PATH as FATIGUE_RULES_PATH, project_formation_idle_fatigue
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.tx.canonical import thaw_json
from sword_runtime.tx.errors import StaleRevisionError
from sword_runtime.vitality import summarize_playability_vitality
from sword_runtime.operation_routing import exact_operation_record, iter_exact_operation_records
from sword_runtime.information_routing import information_supersession_groups


class OperationError(RuntimeError):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def _receipt_record(execution) -> dict[str, Any]:
    receipt = execution.receipt
    return {
        "status": execution.status,
        "request_id": receipt.request_id,
        "transaction_id": receipt.transaction_id,
        "campaign_id": receipt.campaign_id,
        "committed_revision": receipt.committed_revision,
        "committed_at": receipt.committed_at,
        "result": thaw_json(receipt.result),
    }


class CampaignOperations:
    """Expose only bounded, player-authorized campaign reads and semantic writes."""

    def __init__(self, runtime: ProductionSwordRuntime) -> None:
        self.runtime = runtime
        self.store = runtime.store

    @staticmethod
    def _information_freshness_band(subject_ref: str, age_days: float) -> str:
        text = str(subject_ref or "").lower()
        if any(token in text for token in ("operation", "formation", "battle", "siege", "front", "route", "military", "army", "report")):
            bounds = (3.0, 14.0, 30.0)
        elif any(token in text for token in ("market", "price", "economy", "supply", "weather")):
            bounds = (7.0, 30.0, 90.0)
        elif any(token in text for token in ("char_", "house_", "court", "polit", "diplom")):
            bounds = (14.0, 60.0, 180.0)
        else:
            bounds = (7.0, 30.0, 120.0)
        if age_days <= bounds[0]: return "fresh"
        if age_days <= bounds[1]: return "recent"
        if age_days <= bounds[2]: return "aging"
        return "stale"

    def _information_supersession_groups(self) -> dict[str, str]:
        try:
            information_index = self.store.read_json("state/information/index.json")
        except (FileNotFoundError, ValueError):
            return {}
        return information_supersession_groups(
            lambda path: self.store.read_json(path), information_index,
        )

    def _known_information(self, player_id: str) -> list[dict[str, Any]]:
        known: list[dict[str, Any]] = []
        index = self.store.read_json("state/information/index.json")
        claims = index.get("claims", {}) if isinstance(index, Mapping) else {}
        routed = index.get("by_holder", {}).get(player_id) if isinstance(index.get("by_holder"), Mapping) else None
        refs = [str(ref) for ref in routed if isinstance(ref, str)] if isinstance(routed, list) else sorted(claims)
        now = CampaignTime.parse(str(self.store.read_json("state/runtime.json")["world_time"]))
        inferred_groups = self._information_supersession_groups()
        raw_claims: dict[str, Mapping[str, Any]] = {}
        for ref in refs:
            path = claims.get(ref)
            if not isinstance(path, str):
                continue
            claim = self.store.read_json(path)
            if player_id not in claim.get("knowers", []):
                continue
            raw_claims[str(ref)] = claim
            holder_states = claim.get("holder_states") if isinstance(claim.get("holder_states"), Mapping) else {}
            holder = holder_states.get(player_id) if isinstance(holder_states, Mapping) else None
            created_at = claim.get("created_at")
            learned_at = holder.get("learned_at") if isinstance(holder, Mapping) else None
            source_age_days = None
            learned_age_days = None
            if isinstance(created_at, str):
                try: source_age_days = max(0.0, now.seconds_since(CampaignTime.parse(created_at)) / 86400.0)
                except ValueError: pass
            if isinstance(learned_at, str):
                try: learned_age_days = max(0.0, now.seconds_since(CampaignTime.parse(learned_at)) / 86400.0)
                except ValueError: pass
            subject_ref = claim.get("subject_ref")
            group_ref = claim.get("supersession_group_ref") or inferred_groups.get(str(ref)) or subject_ref
            known.append({
                "information_ref": claim.get("information_ref"),
                "subject_ref": subject_ref,
                "claim": claim.get("claim"),
                "epistemic_kind": (holder.get("epistemic_kind") if isinstance(holder, Mapping) else None) or claim.get("epistemic_kind"),
                "confidence_milli": (holder.get("confidence_milli") if isinstance(holder, Mapping) and holder.get("confidence_milli") is not None else claim.get("confidence_milli")),
                "source_ref": (holder.get("source_ref") if isinstance(holder, Mapping) else None) or claim.get("source_ref"),
                "evidence_refs": claim.get("evidence_refs", []),
                "classification": claim.get("classification"),
                "provenance": claim.get("provenance"),
                "created_at": created_at,
                "learned_at": learned_at,
                "source_age_days": round(source_age_days, 3) if source_age_days is not None else None,
                "learned_age_days": round(learned_age_days, 3) if learned_age_days is not None else None,
                "freshness": self._information_freshness_band(str(group_ref or subject_ref or ""), source_age_days if source_age_days is not None else (learned_age_days or 0.0)),
                "supersession_group_ref": group_ref,
                "supersedes_ref": claim.get("supersedes_ref"),
                "assessment_status": "current",
                "superseded_by_ref": None,
                "world_truth_authority": False,
            })
        # Preserve every historical claim, but make the newest assessment in a
        # declared/inferred semantic group explicit. Older claims remain visible
        # as historical knowledge rather than being silently deleted.
        newest: dict[str, tuple[CampaignTime, str]] = {}
        for row in known:
            group = str(row.get("supersession_group_ref") or "")
            stamp = row.get("created_at") or row.get("learned_at")
            ref = str(row.get("information_ref") or "")
            if not group or not isinstance(stamp, str) or not ref:
                continue
            try: when = CampaignTime.parse(stamp)
            except ValueError: continue
            prior = newest.get(group)
            if prior is None or when > prior[0] or (when == prior[0] and ref > prior[1]): newest[group] = (when, ref)
        for row in known:
            group = str(row.get("supersession_group_ref") or "")
            latest = newest.get(group)
            ref = str(row.get("information_ref") or "")
            explicit = row.get("supersedes_ref")
            if latest and latest[1] != ref:
                row["assessment_status"] = "historical_superseded"
                row["superseded_by_ref"] = latest[1]
            elif latest:
                row["assessment_status"] = "current_assessment"
            if explicit:
                row["supersedes_ref"] = explicit
        return known

    def _formation_with_projected_fatigue(self, formation: Mapping[str, Any]) -> dict[str, Any]:
        """Expose effective current fatigue without mutating authoritative state."""
        current = CampaignTime.parse(str(self.store.read_json("state/runtime.json")["world_time"]))
        rules = self.store.read_json(FATIGUE_RULES_PATH)
        return project_formation_idle_fatigue(formation, current=current, rules=rules)

    def _controlled_formations(self, player_id: str) -> list[dict[str, Any]]:
        owners = self.store.read_json("state/index/owner-index.json").get("owners", {})
        formations: list[dict[str, Any]] = []
        for ref, path in sorted(owners.items()):
            if not str(ref).startswith("formation_"):
                continue
            formation = self.store.read_json(path)
            if formation.get("command_authority") != player_id and formation.get("administrative_owner") not in {player_id, "house_tang"}:
                continue
            formation = self._formation_with_projected_fatigue(formation)
            formations.append({
                "formation_ref": ref,
                "name": formation.get("name"),
                "personnel": formation.get("personnel"),
                "location_ref": formation.get("location_ref"),
                "status": formation.get("status"),
                "mobilized": formation.get("mobilized"),
                "commander_ref": formation.get("commander_ref"),
                "command_authority": formation.get("command_authority"),
                "readiness": formation.get("readiness"),
                "morale": formation.get("morale"),
                "cohesion": formation.get("cohesion"),
                "training_progress": formation.get("training_progress"),
                "fatigue": formation.get("fatigue"),
                "experience": formation.get("experience"),
                "logistics": formation.get("logistics", {}),
            })
        return formations


    def _player_operations(self, controlled_refs: set[str]) -> tuple[list[dict[str, Any]], set[str]]:
        rows: list[dict[str, Any]] = []
        refs: set[str] = set()
        for operation_ref, _path, operation in iter_exact_operation_records(self.store.read_json):
            formation_refs = {str(ref) for ref in operation.get("formation_refs", []) if isinstance(ref, str)}
            if not formation_refs.intersection(controlled_refs):
                continue
            refs.add(operation_ref)
            battlefield_rows = []
            for battlefield_ref, battlefield in sorted((operation.get("battlefields") or {}).items()):
                if not isinstance(battlefield_ref, str) or not isinstance(battlefield, Mapping):
                    continue
                assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
                player_sides = {row.get("side_ref") for ref, row in assignments.items() if ref in controlled_refs and isinstance(row, Mapping) and isinstance(row.get("side_ref"), str)}
                reports = [
                    {
                        "report_id": report.get("report_id"),
                        "sector_ref": report.get("sector_ref"),
                        "level": report.get("level"),
                        "created_at": report.get("created_at"),
                        "delivered_at": report.get("delivered_at"),
                        "summary": report.get("summary"),
                    }
                    for report in battlefield.get("reports", [])
                    if isinstance(report, Mapping) and report.get("status") == "delivered" and report.get("target_side_ref") in player_sides
                ]
                battlefield_rows.append({
                    "battlefield_ref": battlefield_ref,
                    "name": battlefield.get("name"),
                    "status": battlefield.get("status"),
                    "location_ref": battlefield.get("location_ref"),
                    "layout_ref": battlefield.get("layout_ref"),
                    "delivered_reports": reports[-32:],
                })
            rows.append({
                "operation_ref": operation_ref,
                "status": operation.get("status"),
                "location_ref": operation.get("location_ref"),
                "objective": operation.get("objective"),
                "battlefields": battlefield_rows,
            })
        return rows, refs

    @staticmethod
    def _safe_scene(meta: Mapping[str, Any], player: Mapping[str, Any], scene: Mapping[str, Any]) -> dict[str, Any]:
        scene_time = scene.get("world_time")
        scene_revision = scene.get("projection_revision")
        fresh = (
            isinstance(scene_time, str)
            and scene_time == meta.get("time")
            and isinstance(scene_revision, int)
            and not isinstance(scene_revision, bool)
            and scene_revision == meta.get("revision")
        )
        narrative = scene.get("narrative", {}) if isinstance(scene.get("narrative"), dict) else {}
        if fresh:
            return {
                "projection_status": "fresh",
                "projected_at": scene_time,
                "projected_revision": scene_revision,
                "scene_id": scene.get("scene_id"),
                "summary": scene.get("scene_summary"),
                "location": scene.get("location"),
                "location_id": scene.get("location_id"),
                "physical_scene": scene.get("physical_scene", {}),
                "observable_pressures": scene.get("observable_pressures", []),
                "player_observable_state": scene.get("player_observable_state", {}),
                "unresolved_decision": scene.get("unresolved_decision"),
                "known_clock_boundaries": scene.get("known_clock_boundaries", []),
                "active_questions": narrative.get("active_questions", []),
                "available_reports": narrative.get("available_reports", []),
                "pending_information_paths": narrative.get("pending_information_paths", []),
                "recent_reveals": narrative.get("recent_reveals", []),
                "unresolved_hooks": narrative.get("unresolved_hooks", []),
            }
        return {
            "projection_status": "stale_after_state_change",
            "projected_at": scene_time,
            "projected_revision": scene_revision,
            "scene_id": None,
            "summary": None,
            "location": player.get("location"),
            "location_id": player.get("location"),
            "physical_scene": {},
            "observable_pressures": [],
            "player_observable_state": {"location": player.get("location"), "health": player.get("health"), "fatigue": player.get("fatigue")},
            "unresolved_decision": None,
            "known_clock_boundaries": [],
            "active_questions": [],
            "available_reports": [],
            "pending_information_paths": [],
            "recent_reveals": [],
            "unresolved_hooks": [],
        }

    def play_context(self) -> dict[str, Any]:
        meta = self.store.read_json("state/meta.json")
        player = self.store.read_json("state/player.json")
        scene = self.store.read_json("state/scene.json")
        wallet = self.store.read_json("state/economy/player-wallet.json")
        player_id = str(meta["player_id"])
        formations = self._controlled_formations(player_id)
        controlled_refs = {str(item.get("formation_ref")) for item in formations if item.get("formation_ref")}
        operations, operation_refs = self._player_operations(controlled_refs)
        safe_scene = self._safe_scene(meta, player, scene)

        relevant: set[str] = set()
        if safe_scene["projection_status"] == "fresh":
            relevant.update(str(value) for value in scene.get("relevant_owner_ids", []) if isinstance(value, str) and value)
        relevant.add(player_id)
        owner_index = self.store.read_json("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}

        def is_person_owner(ref: str) -> bool:
            path = owners.get(ref) if isinstance(owners, Mapping) else None
            if not isinstance(path, str):
                return False
            if path == "state/player.json" or path.startswith("state/char/"):
                return True
            if not path.startswith("state/person/"):
                return False
            try:
                record = self.store.read_json(path)
            except (FileNotFoundError, KeyError, TypeError, ValueError):
                return False
            return isinstance(record, Mapping) and str(record.get("schema", "")) in {"sab_character", "person-lite", "sword-materialized-person"}

        permitted_people = sorted(ref for ref in relevant if is_person_owner(ref))
        permitted_objects = set(ref for ref in relevant if not is_person_owner(ref))
        permitted_objects.update(controlled_refs)
        permitted_objects.update(operation_refs)
        # Static geography is player-safe only for the player's exact current
        # place and its immediate containment/access context.  This exposes no
        # enemy disposition, route safety, garrison, stock, or hidden control.
        location_rows = self.store.read_json("game/data/world/locations.json").get("locations", [])
        location_by_ref = {str(row.get("ref")): row for row in location_rows if isinstance(row, dict) and row.get("ref")}
        current_location_ref = str(player.get("location") or "")
        current_location = location_by_ref.get(current_location_ref, {})
        map_refs = {current_location_ref} if current_location_ref in location_by_ref else set()
        for key in ("parent_ref", "region_ref", "access_node_ref", "contained_by_fortification_site_ref"):
            value = current_location.get(key) if isinstance(current_location, dict) else None
            if isinstance(value, str) and value in location_by_ref:
                map_refs.add(value)
        permitted_objects.update(map_refs)
        map_context = {
            "location_ref": current_location_ref or None,
            "name": current_location.get("name") if isinstance(current_location, dict) else None,
            "kind": current_location.get("kind") if isinstance(current_location, dict) else None,
            "parent_ref": current_location.get("parent_ref") if isinstance(current_location, dict) else None,
            "region_ref": current_location.get("region_ref") if isinstance(current_location, dict) else None,
            "access_node_ref": current_location.get("access_node_ref") if isinstance(current_location, dict) else None,
            "enclosing_fortification_site_ref": current_location.get("contained_by_fortification_site_ref") if isinstance(current_location, dict) else None,
            "visibility": "current_place_static_geography_only",
        }
        for formation in formations:
            commander = formation.get("commander_ref")
            if isinstance(commander, str) and is_person_owner(commander):
                permitted_people.append(commander)
        permitted_people = sorted(set(permitted_people))

        command_types = {
            command_type: {
                "accepted_payload_keys": sorted(COMMAND_PAYLOAD_KEYS.get(command_type, ())),
                "input_guidance": dict(COMMAND_INPUT_GUIDANCE.get(command_type, {})),
                "contested_preview_policy": "outcome_hidden_until_execute" if command_type in {"battle_resolve", "personal_combat", "siege_action"} else "deterministic_preview",
            }
            for command_type in sorted(COMMAND_TYPES)
        }
        return {
            "campaign": {"campaign_id": meta["campaign_id"], "revision": meta["revision"], "world_time": meta["time"], "player_id": player_id},
            "player": {
                "player_id": player_id,
                "name": player.get("name"),
                "authority": player.get("authority"),
                "allegiance": player.get("allegiance"),
                "location": player.get("location"),
                "health": player.get("health"),
                "fatigue": player.get("fatigue"),
                "equipment_state": player.get("current_equipment_state", {}),
                "combat_agency_constraints": load_personal_combat_doctrine(self.runtime.store.read_json, player).get("combat_agency_constraints", []),
            },
            "scene": safe_scene,
            "wallet": {"silver": wallet.get("silver")},
            "known_information": self._known_information(player_id),
            "controlled_formations": formations,
            "controlled_operations": operations,
            "map_context": map_context,
            "permitted_person_ids": permitted_people,
            "permitted_object_refs": sorted(permitted_objects),
            "object_read_policy": "Use only exact IDs returned here. Hidden or guessed IDs fail closed. Non-player person reads return bounded player-visible identity data.",
            "commands": {
                "supported_command_types": sorted(command_types),
                "command_types": command_types,
                "input_guidance_policy": INPUT_GUIDANCE_POLICY,
            },
            "limits": {
                "one_semantic_command_per_write": True,
                "preview_before_execute": True,
                "execute_requires_exact_preview_envelope": True,
                "contested_outcomes_hidden_during_preview": True,
                "unsupported_mechanical_consequence_fails_closed": True,
                "ordinary_reversible_scene_actions_need_no_command": True,
                "command_catalog_role": "mechanical_consequence_registry_not_action_whitelist",
                "ooc_is_read_only": True,
            },
            "narration_guidance": {
                "person": "second_person_present",
                "gm_context_boundary": "scene_bounded_omniscient_when_material",
                "player_output_knowledge_boundary": "player_visible_only",
                "hidden_truth_rule": "The GM may use explicitly marked private scene/character/combat truth to understand causality and direct NPCs, but hidden facts are not narrated as Wei's knowledge unless perceived, disclosed, or lawfully inferred.",
                "decision_scaffolding": "narrate_first_then_scene_relevant_choices",
                "stale_scene_policy": "require_matching_time_and_projection_revision; strip_transient_scene_claims_and_scene_derived_read_permissions",
            },
        }

    def _permitted_people(self) -> set[str]:
        return set(self.play_context()["permitted_person_ids"])

    def _permitted_objects(self) -> set[str]:
        return set(self.play_context()["permitted_object_refs"])

    def person_sheet(self, person_id: str) -> dict[str, Any]:
        context = self.play_context()
        if person_id not in set(context["permitted_person_ids"]):
            raise OperationError(404, "person_not_player_visible")
        if person_id == context["campaign"]["player_id"]:
            return {"visibility": "player_full_sheet", "person": self.store.read_json("state/player.json")}
        owners = self.store.read_json("state/index/owner-index.json").get("owners", {})
        path = owners.get(person_id)
        if not isinstance(path, str):
            raise OperationError(404, "person_not_available")
        person = self.store.read_json(path)
        projected = {"person_id": person_id, "name": person.get("name"), "life_status": person.get("life_status", "active")}
        for key in ("sex", "pronouns", "family_role", "role"):
            if key in person:
                projected[key] = person.get(key)
        return {"visibility": "player_visible_identity", "person": projected}

    def inspect_game_object(self, object_ref: str) -> dict[str, Any]:
        context = self.play_context()
        if object_ref not in set(context["permitted_object_refs"]):
            raise OperationError(404, "object_not_player_visible")
        controlled = {str(item.get("formation_ref")): item for item in context["controlled_formations"]}
        locations = self.store.read_json("game/data/world/locations.json").get("locations", [])
        location = next((row for row in locations if isinstance(row, dict) and str(row.get("ref")) == object_ref), None)
        if isinstance(location, dict):
            fields = (
                "ref", "name", "kind", "state", "parent_ref", "region_ref", "polity_ref",
                "spatial_scale", "strategic_node", "demographic_role", "access_node_ref",
                "access_for_ref", "contained_by_fortification_site_ref", "fortified", "functions",
            )
            return {
                "object_ref": object_ref,
                "visibility": "player_current_map_static_geography",
                "object": {key: location.get(key) for key in fields if key in location},
                "hidden_current_state_excluded": ["enemy_disposition", "garrison", "route_safety", "route_status", "stockpiles", "secret_access"],
            }
        owners = self.store.read_json("state/index/owner-index.json").get("owners", {})
        path = owners.get(object_ref)
        if not isinstance(path, str):
            resolved_operation = exact_operation_record(self.store.read_json, object_ref)
            path = resolved_operation[0] if resolved_operation is not None else None
        if not isinstance(path, str) and object_ref.startswith("cmdgrp.") and all(
            ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in object_ref
        ):
            candidate = f"state/cmd/command-groups/{object_ref}.json"
            try:
                self.store.read_json(candidate)
            except (FileNotFoundError, ValueError):
                candidate = None
            path = candidate
        if not isinstance(path, str):
            raise OperationError(404, "object_not_inspectable")
        obj = self.store.read_json(path)
        if obj.get("schema") == "sword-investigation":
            fields = ("investigation_ref", "question", "subject_ref", "location_ref", "investigator_ref", "status", "started_at", "worked_hours", "discovered_claim_refs", "closed_at")
            return {"object_ref": object_ref, "visibility": "player_investigation", "object": {key: obj.get(key) for key in fields if key in obj}}
        if obj.get("schema") == "sword-commission-request":
            fields = ("request_ref", "requester_ref", "issuer_ref", "category", "status", "requested_at", "request_delivery_due_at", "responds_at", "source_location_ref", "issuer_location_ref", "communication_travel_seconds", "commission_ref", "responded_at")
            return {"object_ref": object_ref, "visibility": "player_commission_request", "object": {key: obj.get(key) for key in fields if key in obj}}
        if obj.get("schema") == "sword-commission":
            # Hidden assignment profile remains runtime-only until lawful evidence exposes it.
            fields = ("commission_ref", "request_ref", "issuer_ref", "assignee_ref", "archetype_ref", "category", "objective", "location_ref", "status", "offered_at", "accepted_at", "reported_at", "report_dispatched_at", "report_delivery_due_at", "report_response_due_at", "report_delivered_at", "report_source_location_ref", "report_issuer_location_ref", "communication_travel_seconds", "evidence_refs", "settlement_pending")
            return {"object_ref": object_ref, "visibility": "player_commission", "object": {key: obj.get(key) for key in fields if key in obj}}
        if obj.get("schema") == "sword-commitment":
            fields = ("commitment_ref", "obligor_ref", "beneficiary_ref", "kind", "description", "due_at", "status", "created_at", "fulfilled_at", "breached_at", "released_at", "evidence_refs")
            return {"object_ref": object_ref, "visibility": "player_commitment", "object": {key: obj.get(key) for key in fields if key in obj}}
        if obj.get("schema") == "command-group":
            fields = (
                "id", "display_name", "context", "commander_ref",
                "direct_person_refs", "units",
                "parent_command_group_ref", "standing_orders", "role_assignments",
                "familiarity_milli", "verified_group_training_hours", "active_context_ref",
                "communication_ref",
            )
            projected = {key: obj.get(key) for key in fields if key in obj}
            location = None
            location_basis = "not_established"
            commander_ref = obj.get("commander_ref")
            candidate_refs = [commander_ref] if isinstance(commander_ref, str) else []
            candidate_refs.extend(row.get("ref") for row in obj.get("units", []) if isinstance(row, Mapping) and row.get("kind") == "formation" and isinstance(row.get("ref"), str))
            found_locations: list[tuple[str, str]] = []
            for ref in candidate_refs:
                owner_path = owners.get(ref) if isinstance(owners, Mapping) else None
                if not isinstance(owner_path, str):
                    continue
                owner_doc = self.store.read_json(owner_path)
                for key in ("current_location", "location_ref", "location", "loc", "site_ref"):
                    value = owner_doc.get(key) if isinstance(owner_doc, Mapping) else None
                    if isinstance(value, str) and value:
                        found_locations.append((ref, value))
                        break
            if isinstance(commander_ref, str):
                commander_locations = [value for ref, value in found_locations if ref == commander_ref]
                if commander_locations:
                    location = commander_locations[0]
                    location_basis = "commander_exact_location"
            if location is None:
                unique_locations = {value for _ref, value in found_locations}
                if len(unique_locations) == 1:
                    location = next(iter(unique_locations))
                    location_basis = "co_located_attached_formations"
            projected["current_location_ref"] = location
            projected["location_basis"] = location_basis
            return {
                "object_ref": object_ref,
                "visibility": "player_command_hierarchy",
                "object": projected,
            }
        if obj.get("schema") == "sword-operation":
            controlled_refs = set(controlled)
            projected_battlefields = []
            for battlefield_ref, battlefield in sorted((obj.get("battlefields") or {}).items()):
                if not isinstance(battlefield_ref, str) or not isinstance(battlefield, Mapping):
                    continue
                assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
                player_assignments = [dict(row) for ref, row in assignments.items() if ref in controlled_refs and isinstance(row, Mapping)]
                player_sides = {row.get("side_ref") for row in player_assignments if isinstance(row.get("side_ref"), str)}
                delivered_reports = []
                for report in battlefield.get("reports", []):
                    if not isinstance(report, Mapping) or report.get("status") != "delivered" or report.get("target_side_ref") not in player_sides:
                        continue
                    projected = dict(report)
                    if hasattr(self.runtime, "_battlefield_enrich_player_report"):
                        projected = self.runtime._battlefield_enrich_player_report(battlefield, report)
                    delivered_reports.append(projected)
                projected_battlefields.append({
                    "battlefield_ref": battlefield_ref,
                    "name": battlefield.get("name"),
                    "status": battlefield.get("status"),
                    "location_ref": battlefield.get("location_ref"),
                    "layout_ref": battlefield.get("layout_ref"),
                    "sectors": [{"sector_ref": ref, "name": row.get("name"), "status": row.get("status")} for ref, row in sorted((battlefield.get("sectors") or {}).items()) if isinstance(ref, str) and isinstance(row, Mapping)],
                    "player_assignments": player_assignments,
                    "delivered_reports": delivered_reports[-64:],
                })
            return {
                "object_ref": object_ref,
                "visibility": "bounded_player_operational_view",
                "object": {
                    "operation_ref": obj.get("operation_ref"),
                    "status": obj.get("status"),
                    "location_ref": obj.get("location_ref"),
                    "objective": obj.get("objective"),
                    "battlefields": projected_battlefields,
                },
            }
        if object_ref in controlled:
            obj = self._formation_with_projected_fatigue(obj)
            fields = ("owner_id", "formation_ref", "name", "role", "personnel", "location_ref", "status", "mobilized", "commander_ref", "command_authority", "administrative_owner", "doctrine_ref", "training_ref", "supply", "logistics", "morale", "cohesion", "readiness", "training_progress", "fatigue", "experience")
        else:
            fields = ("owner_id", "name", "status", "role", "authority", "state", "location", "location_ref", "personnel", "commander_ref", "objective", "public_status")
        return {"object_ref": object_ref, "visibility": "bounded_player_visible", "object": {key: obj.get(key) for key in fields if key in obj}}

    def _player_actor(self) -> str:
        player_id = self.store.read_json("state/meta.json").get("player_id")
        if not isinstance(player_id, str) or not player_id:
            raise OperationError(503, "campaign_runtime_unavailable")
        return player_id

    def _authorize_public_command(self, command: CommandEnvelope) -> None:
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")

    def preview_command(self, command: CommandEnvelope) -> dict[str, Any]:
        self._authorize_public_command(command)
        try:
            return self.runtime.preview_for_execution(command)
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "command_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "command_rejected") from exc

    def lookup_command_receipt(self, command: CommandEnvelope) -> Optional[dict[str, Any]]:
        self._authorize_public_command(command)
        try:
            receipt = self.runtime.coordinator.lookup_receipt(command)
        except StaleRevisionError:
            receipt = None
        if receipt is None:
            return None
        return {"status": "duplicate", "request_id": receipt.request_id, "transaction_id": receipt.transaction_id, "campaign_id": receipt.campaign_id, "committed_revision": receipt.committed_revision, "committed_at": receipt.committed_at, "result": thaw_json(receipt.result)}

    def execute_command(self, command: CommandEnvelope) -> dict[str, Any]:
        self._authorize_public_command(command)
        try:
            return _receipt_record(self.runtime.execute(command))
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "command_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "command_rejected") from exc
        except Exception as exc:
            raise OperationError(503, "campaign_runtime_unavailable") from exc

    def ooc_audit(self, focus: Optional[str] = None, observations: Optional[list[str]] = None) -> dict[str, Any]:
        meta = self.store.read_json("state/meta.json")
        runtime = self.store.read_json("state/runtime.json")
        return {
            "mode": "read_only",
            "campaign_id": meta["campaign_id"],
            "revision": meta["revision"],
            "world_time": meta["time"],
            "metrics": runtime.get("metrics", {}),
            "playability_vitality": summarize_playability_vitality(self.store),
            "remote_durability_configured": self.runtime.coordinator.remote_durability is not None,
            "focus": focus,
            "observations": [] if observations is None else list(observations),
        }


__all__ = ["CampaignOperations", "OperationError"]
