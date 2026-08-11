"""Bounded player-facing operations shared by REST and MCP surfaces."""
from __future__ import annotations

from typing import Any, Mapping, Optional

from sword_runtime.api.input_guidance import COMMAND_INPUT_GUIDANCE, INPUT_GUIDANCE_POLICY
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import COMMAND_TYPES
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.tx.errors import StaleRevisionError
from sword_runtime.tx.invalidations import load_transaction_invalidations


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
        "result": dict(receipt.result),
    }


class CampaignOperations:
    """Expose only bounded, player-authorized campaign reads and semantic writes."""

    def __init__(self, runtime: ProductionSwordRuntime) -> None:
        self.runtime = runtime
        self.store = runtime.store

    def _known_information(self, player_id: str) -> list[dict[str, Any]]:
        known: list[dict[str, Any]] = []
        index = self.store.read_json("state/information/index.json")
        for _, path in sorted(index.get("claims", {}).items()):
            claim = self.store.read_json(path)
            if player_id not in claim.get("knowers", []):
                continue
            known.append({
                "information_ref": claim.get("information_ref"),
                "claim": claim.get("claim"),
                "confidence": claim.get("confidence"),
                "provenance": claim.get("provenance"),
            })
        return known

    def _controlled_formations(self, player_id: str) -> list[dict[str, Any]]:
        owners = self.store.read_json("state/index/owner-index-gold.json").get("owners", {})
        formations: list[dict[str, Any]] = []
        for ref, path in sorted(owners.items()):
            if not str(ref).startswith("formation_"):
                continue
            formation = self.store.read_json(path)
            if formation.get("command_authority") != player_id and formation.get("administrative_owner") not in {player_id, "house_tang"}:
                continue
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
        safe_scene = self._safe_scene(meta, player, scene)

        relevant: set[str] = set()
        if safe_scene["projection_status"] == "fresh":
            relevant.update(str(value) for value in scene.get("relevant_owner_ids", []) if isinstance(value, str) and value)
        relevant.add(player_id)
        permitted_people = sorted(ref for ref in relevant if ref.startswith("char_"))
        permitted_objects = set(ref for ref in relevant if not ref.startswith("char_"))
        permitted_objects.update(str(item["formation_ref"]) for item in formations if item.get("formation_ref"))
        for formation in formations:
            commander = formation.get("commander_ref")
            if isinstance(commander, str) and commander.startswith("char_"):
                permitted_people.append(commander)
        permitted_people = sorted(set(permitted_people))

        command_types = {
            command_type: {
                "accepted_payload_keys": sorted(COMMAND_PAYLOAD_KEYS.get(command_type, ())),
                "input_guidance": dict(COMMAND_INPUT_GUIDANCE.get(command_type, {})),
                "contested_preview_policy": "outcome_hidden_until_execute" if command_type in {"battle_resolve", "personal_combat", "siege_action"} else "deterministic_preview",
            }
            for command_type in sorted(COMMAND_TYPES)
            if command_type != "repair"
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
                "agency_constraints": player.get("narrative_constraints", []),
                "combat_agency_constraints": player.get("behavior", {}).get("combat_agency_constraints", []),
            },
            "scene": safe_scene,
            "wallet": {"silver": wallet.get("silver")},
            "known_information": self._known_information(player_id),
            "controlled_formations": formations,
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
                "unsupported_intent_fails_closed": True,
                "ooc_is_read_only": True,
            },
            "narration_guidance": {
                "person": "second_person_present",
                "knowledge_boundary": "player_visible_only",
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
        owners = self.store.read_json("state/index/owner-index-gold.json").get("owners", {})
        path = owners.get(person_id)
        if not isinstance(path, str):
            raise OperationError(404, "person_not_available")
        person = self.store.read_json(path)
        return {"visibility": "player_visible_identity", "person": {"person_id": person_id, "name": person.get("name"), "life_status": person.get("life_status", "active")}}

    def inspect_game_object(self, object_ref: str) -> dict[str, Any]:
        context = self.play_context()
        if object_ref not in set(context["permitted_object_refs"]):
            raise OperationError(404, "object_not_player_visible")
        controlled = {str(item.get("formation_ref")): item for item in context["controlled_formations"]}
        owners = self.store.read_json("state/index/owner-index-gold.json").get("owners", {})
        path = owners.get(object_ref)
        if not isinstance(path, str):
            raise OperationError(404, "object_not_inspectable")
        obj = self.store.read_json(path)
        if object_ref in controlled:
            fields = ("owner_id", "formation_ref", "name", "role", "personnel", "location_ref", "status", "mobilized", "commander_ref", "command_authority", "administrative_owner", "doctrine_ref", "training_ref", "supply", "logistics", "morale", "cohesion", "readiness", "training_progress", "fatigue", "experience")
        else:
            fields = ("owner_id", "name", "status", "role", "authority", "state", "location", "location_ref", "personnel", "commander_ref", "objective", "public_status")
        return {"object_ref": object_ref, "visibility": "bounded_player_visible", "object": {key: obj.get(key) for key in fields if key in obj}}

    def _player_actor(self) -> str:
        player_id = self.store.read_json("state/meta.json").get("player_id")
        if not isinstance(player_id, str) or not player_id:
            raise OperationError(503, "campaign_runtime_unavailable")
        return player_id

    def preview_command(self, command: CommandEnvelope) -> dict[str, Any]:
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")
        try:
            return self.runtime.preview_for_execution(command)
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "command_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "command_rejected") from exc

    def lookup_command_receipt(self, command: CommandEnvelope) -> Optional[dict[str, Any]]:
        try:
            receipt = self.runtime.coordinator.lookup_receipt(command)
        except StaleRevisionError:
            receipt = None
        if receipt is None:
            return None
        return {"status": "duplicate", "request_id": receipt.request_id, "transaction_id": receipt.transaction_id, "campaign_id": receipt.campaign_id, "committed_revision": receipt.committed_revision, "committed_at": receipt.committed_at, "result": dict(receipt.result)}

    def execute_command(self, command: CommandEnvelope) -> dict[str, Any]:
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")
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
        try:
            invalidation_count = len(load_transaction_invalidations(self.store))
        except (TypeError, ValueError):
            invalidation_count = None
        return {
            "mode": "read_only",
            "campaign_id": meta["campaign_id"],
            "revision": meta["revision"],
            "world_time": meta["time"],
            "metrics": runtime.get("metrics", {}),
            "remote_durability_configured": self.runtime.coordinator.remote_durability is not None,
            "transaction_invalidations_registered": invalidation_count,
            "focus": focus,
            "observations": [] if observations is None else list(observations),
        }


__all__ = ["CampaignOperations", "OperationError"]
