"""Production operations with stable low-information failure classification."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from sword_runtime.api.interaction_surface import (
    HOT_FORMATION_LIMIT,
    HOT_INFORMATION_LIMIT,
    INTERACTION_ACTIONS,
    fresh_runtime_projection,
    translate_interaction_command,
    triggered_interaction_handles,
    validate_interaction_payload,
)
from sword_runtime.api.operations import CampaignOperations, OperationError, _receipt_record
from sword_runtime.causal_living_world import _WAKE_RESPONSE_COMMANDS
from sword_runtime.commands import CommandEnvelope
from sword_runtime.living_world import HighSalienceWakeRequired
from sword_runtime.tx.errors import (
    CommitVerificationError,
    ConcurrentModificationError,
    DirtyRepositoryError,
    GitCommitError,
    GitStageError,
    IdempotencyConflictError,
    LockUnavailableError,
    ReadbackVerificationError,
    RecoveryError,
    RemoteDurabilityError,
    StaleRevisionError,
    TransactionError,
    WalError,
)


_TRANSACTION_CODES = {
    GitStageError: "transaction_git_stage_failed",
    GitCommitError: "transaction_git_commit_failed",
    CommitVerificationError: "transaction_commit_verification_failed",
    ReadbackVerificationError: "transaction_readback_failed",
    WalError: "transaction_wal_failed",
    ConcurrentModificationError: "transaction_concurrent_modification",
}

_WAKE_VISIBLE_FIELDS = (
    "wake_ref", "kind", "at", "theater_ref", "formation_ref", "location_ref",
    "opponent_state", "campaign_event_ref", "reason",
)


def transaction_failure_code(exc: TransactionError) -> str:
    for exc_type, code in _TRANSACTION_CODES.items():
        if isinstance(exc, exc_type):
            return code
    return "transaction_rejected"


class StableCampaignOperations(CampaignOperations):
    """Player surface that fails closed without leaking server/Git internals."""

    @staticmethod
    def _formation_sort_key(item: Mapping[str, Any], player_location: object) -> tuple[int, str]:
        return (0 if item.get("location_ref") == player_location else 1, str(item.get("formation_ref") or ""))

    def _all_controlled_formations(self, player_id: str) -> list[dict[str, Any]]:
        return super()._controlled_formations(player_id)

    def _interaction_refs(self) -> tuple[list[dict[str, Any]], set[str]]:
        handles = triggered_interaction_handles(self.store)
        return handles, {str(item["interaction_ref"]) for item in handles}

    def _validate_interaction_authority(self, command: CommandEnvelope) -> None:
        payload = validate_interaction_payload(command.payload)
        base = super().play_context()
        player_id = str(base["campaign"]["player_id"])
        handles, handle_refs = self._interaction_refs()
        del handles
        all_formations = self._all_controlled_formations(player_id)
        controlled_refs = {str(item["formation_ref"]) for item in all_formations if item.get("formation_ref")}
        permitted = set(base.get("permitted_person_ids", [])) | set(base.get("permitted_object_refs", [])) | handle_refs
        if payload["target_ref"] not in permitted:
            raise OperationError(404, "interaction_target_not_player_visible")
        if payload["process_ref"] is not None and payload["process_ref"] not in permitted:
            raise OperationError(404, "interaction_process_not_player_visible")
        if any(ref not in controlled_refs for ref in payload["formation_refs"]):
            raise OperationError(403, "interaction_formation_not_controlled")

    def _translate_surface_command(self, command: CommandEnvelope) -> CommandEnvelope:
        if command.command_type != "interaction_action":
            return command
        self._validate_interaction_authority(command)
        return translate_interaction_command(command)

    def play_context(self):
        context = super().play_context()
        context.setdefault("limits", {})["high_salience_wake_boundary"] = True
        context["limits"]["operational_memory_is_non_authoritative"] = True
        context["limits"]["campaign_event_boundaries"] = True
        context["limits"]["bounded_hot_context_with_exact_rehydration"] = True

        # Preserve a presentation-only anchor, then replace a stale authored
        # scene with a revision-matched projection made only from exact current
        # owners and already-triggered event-registry facts.
        scene_context = context.get("scene")
        handles, handle_refs = self._interaction_refs()
        if isinstance(scene_context, dict):
            continuity_anchor = None
            if scene_context.get("projection_status") == "stale_after_state_change":
                raw_scene = self.runtime.store.read_json("state/scene.json")
                narrative = raw_scene.get("narrative", {}) if isinstance(raw_scene, Mapping) else {}
                if not isinstance(narrative, Mapping):
                    narrative = {}
                summary = raw_scene.get("scene_summary") if isinstance(raw_scene, Mapping) else None
                if not isinstance(summary, str) or not summary.strip():
                    summary = narrative.get("last_scene_summary")
                if isinstance(summary, str) and summary.strip():
                    continuity_anchor = {
                        "presentation_only": True,
                        "prior_scene_id": raw_scene.get("scene_id"),
                        "prior_location": raw_scene.get("location_id") or raw_scene.get("location"),
                        "summary": summary.strip(),
                        "warning": (
                            "Previous-scene orientation only; it does not prove current presence, access, "
                            "pressure, opportunity, occupancy, or unresolved status."
                        ),
                    }
                projection = fresh_runtime_projection(context, handles)
                projection["continuity_anchor"] = continuity_anchor
                context["scene"] = projection
                scene_context = projection
                context.setdefault("narration_guidance", {})["stale_scene_policy"] = (
                    "stale authored scene claims are stripped; the runtime supplies a revision-matched "
                    "minimal projection from exact current owners and triggered event facts, while any "
                    "older prose remains presentation-only continuity"
                )
            else:
                scene_context.setdefault("continuity_anchor", None)

        # Keep ordinary turn handoff bounded. Paging and exact revalidation are
        # the escape hatches, so this is a projection limit rather than a world
        # cardinality limit.
        known_all = list(context.get("known_information", []))
        known_hot = known_all[-HOT_INFORMATION_LIMIT:]
        context["known_information"] = known_hot
        context["known_information_count"] = len(known_all)
        context["known_information_truncated"] = len(known_all) > len(known_hot)

        formations_all = list(context.get("controlled_formations", []))
        player_location = context.get("player", {}).get("location")
        formations_all.sort(key=lambda item: self._formation_sort_key(item, player_location))
        formations_hot = formations_all[:HOT_FORMATION_LIMIT]
        context["controlled_formations"] = formations_hot
        context["controlled_formations_count"] = len(formations_all)
        context["controlled_formations_truncated"] = len(formations_all) > len(formations_hot)

        all_formation_refs = {str(item.get("formation_ref")) for item in formations_all if item.get("formation_ref")}
        hot_formation_refs = {str(item.get("formation_ref")) for item in formations_hot if item.get("formation_ref")}
        all_commanders = {str(item.get("commander_ref")) for item in formations_all if item.get("commander_ref")}
        hot_commanders = {str(item.get("commander_ref")) for item in formations_hot if item.get("commander_ref")}
        permitted_objects = set(context.get("permitted_object_refs", [])) - all_formation_refs
        permitted_objects.update(hot_formation_refs)
        permitted_objects.update(handle_refs)
        context["permitted_object_refs"] = sorted(permitted_objects)
        permitted_people = set(context.get("permitted_person_ids", [])) - all_commanders
        permitted_people.update(hot_commanders)
        permitted_people.add(str(context["campaign"]["player_id"]))
        context["permitted_person_ids"] = sorted(permitted_people)

        context["interaction_handles"] = handles
        context["interaction_handles_count"] = len(handles)
        context["interaction_handles_truncated"] = False

        commands = context.setdefault("commands", {})
        command_types = dict(commands.get("command_types", {}))
        command_types.pop("scene_consequence", None)
        command_types["interaction_action"] = {
            "accepted_payload_keys": ["action", "formation_refs", "player_statement", "posture", "process_ref", "target_ref"],
            "input_guidance": {
                "target_ref": {"rule": "use an exact permitted person/object or returned interaction_ref"},
                "process_ref": {"rule": "optional exact permitted process/interaction ref"},
                "action": {"allowed_values": sorted(INTERACTION_ACTIONS)},
                "formation_refs": {"rule": "optional unique exact controlled formation refs"},
                "player_statement": {"type": "string", "maximum_length": 2000, "rule": "player-authored speech only"},
                "posture": {"type": "string", "maximum_length": 500, "rule": "player-authored posture only"},
                "outcome_rule": "NPC/world response fields are forbidden at every nesting depth; an interaction command commits only the player's attempt unless another runtime authority establishes a response.",
            },
            "contested_preview_policy": "attempt_only_no_external_outcome",
        }
        commands["command_types"] = command_types
        commands["supported_command_types"] = sorted(command_types)
        commands["legacy_hidden_command_types"] = ["scene_consequence"]

        runtime = self.runtime.store.read_json("state/runtime.json")
        wake = runtime.get("pending_wake") if isinstance(runtime, Mapping) else None
        if isinstance(wake, Mapping):
            context["pending_wake"] = {key: wake[key] for key in _WAKE_VISIBLE_FIELDS if key in wake}
            context["decision_required"] = True
            if wake.get("kind") == "campaign_event":
                response_types = list(commands.get("supported_command_types", []))
                context["pending_wake"]["response_command_types"] = response_types
                context["pending_wake"]["continue_command"] = "advance_time"
                context["decision_reason"] = "campaign_event_boundary"
                commands["availability_scope"] = "campaign_event_response"
                commands["temporarily_available_command_types"] = response_types
            else:
                response_types = sorted(_WAKE_RESPONSE_COMMANDS)
                if "scene_consequence" in response_types:
                    response_types.remove("scene_consequence")
                if "interaction_action" not in response_types:
                    response_types.append("interaction_action")
                    response_types.sort()
                context["pending_wake"]["response_command_types"] = response_types
                context["pending_wake"]["continue_contact_command"] = "advance_time"
                context["decision_reason"] = "high_salience_autonomous_contact"
                commands["availability_scope"] = "pending_wake_response"
                commands["temporarily_available_command_types"] = response_types
        return context

    def get_command_contract(self, command_type: str) -> dict[str, Any]:
        context = self.play_context()
        record = context.get("commands", {}).get("command_types", {}).get(command_type)
        if not isinstance(record, Mapping):
            raise OperationError(404, "command_contract_not_available")
        return {"command_type": command_type, **dict(record)}

    def list_controlled_formations(self, offset: int = 0, limit: int = 20) -> dict[str, Any]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or offset > 100000:
            raise OperationError(422, "formation_page_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 64:
            raise OperationError(422, "formation_page_invalid")
        player_id = self._player_actor()
        values = self._all_controlled_formations(player_id)
        player_location = self.store.read_json("state/player.json").get("location")
        values.sort(key=lambda item: self._formation_sort_key(item, player_location))
        page = values[offset:offset + limit]
        return {
            "offset": offset,
            "limit": limit,
            "count": len(values),
            "returned": len(page),
            "truncated": offset + len(page) < len(values),
            "formations": page,
        }

    def inspect_game_object(self, object_ref: str) -> dict[str, Any]:
        handles, handle_refs = self._interaction_refs()
        if object_ref in handle_refs:
            record = next(item for item in handles if item["interaction_ref"] == object_ref)
            return {"object_ref": object_ref, "visibility": "player_visible_triggered_event", "object": record}
        context = self.play_context()
        if object_ref in set(context.get("permitted_object_refs", [])):
            return super().inspect_game_object(object_ref)

        # Exact known claims may fall out of the hot window without becoming
        # forgotten. Revalidate the exact saved knower before returning it.
        info_index = self.store.read_json("state/information/index.json")
        claim_path = info_index.get("claims", {}).get(object_ref)
        if isinstance(claim_path, str):
            claim = self.store.read_json(claim_path)
            if context["campaign"]["player_id"] in claim.get("knowers", []):
                return {
                    "object_ref": object_ref,
                    "visibility": "player_known_information",
                    "object": {
                        "information_ref": claim.get("information_ref"),
                        "claim": claim.get("claim"),
                        "confidence": claim.get("confidence"),
                        "provenance": claim.get("provenance"),
                    },
                }

        # Controlled formations outside the hot window remain inspectable by
        # exact ref after current authority is revalidated.
        owners = self.store.read_json("state/index/owner-index-gold.json").get("owners", {})
        path = owners.get(object_ref)
        if isinstance(path, str) and object_ref.startswith("formation_"):
            formation = self.store.read_json(path)
            player_id = context["campaign"]["player_id"]
            if formation.get("command_authority") == player_id or formation.get("administrative_owner") in {player_id, "house_tang"}:
                fields = ("owner_id", "formation_ref", "name", "role", "personnel", "location_ref", "status", "mobilized", "commander_ref", "command_authority", "administrative_owner", "doctrine_ref", "training_ref", "supply", "logistics", "morale", "cohesion", "readiness", "training_progress", "fatigue", "experience")
                return {"object_ref": object_ref, "visibility": "controlled_exact_rehydration", "object": {key: formation.get(key) for key in fields if key in formation}}
        raise OperationError(404, "object_not_player_visible")

    def preview_command(self, command):
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")
        translated = self._translate_surface_command(command)
        try:
            preview = self.runtime.preview_for_execution(translated)
            if command.command_type == "interaction_action":
                preview = dict(preview)
                preview["surface_command_type"] = "interaction_action"
                preview["world_response_status"] = "not_established_by_attempt"
            return preview
        except HighSalienceWakeRequired as exc:
            raise OperationError(409, "high_salience_wake_required") from exc
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "command_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "command_rejected") from exc

    def lookup_command_receipt(self, command: CommandEnvelope) -> Optional[dict[str, Any]]:
        translated = self._translate_surface_command(command)
        receipt = super().lookup_command_receipt(translated)
        if receipt is not None and command.command_type == "interaction_action":
            receipt = dict(receipt)
            receipt["surface_command_type"] = "interaction_action"
        return receipt

    def execute_command(self, command):
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")
        translated = self._translate_surface_command(command)
        try:
            receipt = _receipt_record(self.runtime.execute(translated))
            if command.command_type == "interaction_action":
                receipt["surface_command_type"] = "interaction_action"
            return receipt
        except HighSalienceWakeRequired as exc:
            raise OperationError(409, "high_salience_wake_required") from exc
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except IdempotencyConflictError as exc:
            raise OperationError(409, "idempotency_conflict") from exc
        except LockUnavailableError as exc:
            raise OperationError(503, "campaign_writer_busy") from exc
        except RemoteDurabilityError as exc:
            raise OperationError(503, "transaction_remote_durability_failed") from exc
        except (DirtyRepositoryError, RecoveryError) as exc:
            raise OperationError(503, "campaign_unavailable") from exc
        except PermissionError as exc:
            raise OperationError(403, "command_not_authorized") from exc
        except TransactionError as exc:
            raise OperationError(409, transaction_failure_code(exc)) from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "command_rejected") from exc
        except Exception as exc:
            raise OperationError(503, "campaign_runtime_unavailable") from exc


__all__ = ["StableCampaignOperations", "transaction_failure_code"]
