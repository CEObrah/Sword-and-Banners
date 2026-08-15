"""Production operations with stable low-information failure classification."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from sword_runtime.api.interaction_surface import (
    HOT_FORMATION_LIMIT,
    HOT_INFORMATION_LIMIT,
    INTERACTION_ACTIONS,
    fresh_runtime_projection,
    recent_interaction_attempts,
    translate_interaction_command,
    triggered_interaction_handles,
    triggered_interaction_page,
    triggered_interaction_record,
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
    "opponent_state", "campaign_event_ref", "operation_ref", "battlefield_ref",
    "sector_ref", "report_id", "level", "reason",
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

    @staticmethod
    def _cursor_offset(cursor: Optional[str], code: str) -> int:
        if cursor is None:
            return 0
        if not isinstance(cursor, str) or not cursor.isdigit() or len(cursor) > 12:
            raise OperationError(422, code)
        offset = int(cursor)
        if offset < 0 or offset > 1_000_000:
            raise OperationError(422, code)
        return offset

    def _all_controlled_formations(self, player_id: str) -> list[dict[str, Any]]:
        return super()._controlled_formations(player_id)

    def _all_known_information(self, player_id: str) -> list[dict[str, Any]]:
        return super()._known_information(player_id)

    def _interaction_refs(self) -> tuple[list[dict[str, Any]], set[str], int]:
        handles, total = triggered_interaction_handles(self.store)
        handles = list(reversed(handles))
        return handles, {str(item["interaction_ref"]) for item in handles}, total

    def _controlled_operation_views(self, controlled_refs: set[str]) -> list[dict[str, Any]]:
        """Return only operational facts the player's command position can know.

        The active operation index is already the bounded routing owner. Enemy
        assignments and undelivered pressure reports stay hidden; the view
        exposes battlefield geometry, the player's own formation assignments,
        and reports whose messenger delivery has actually completed.
        """

        try:
            index = self.store.read_json("state/operations/index.json")
        except FileNotFoundError:
            return []
        operations = index.get("operations") if isinstance(index, Mapping) else None
        if not isinstance(operations, Mapping):
            return []
        views: list[dict[str, Any]] = []
        for operation_ref, path in sorted(operations.items()):
            if not isinstance(operation_ref, str) or not isinstance(path, str):
                continue
            operation = self.store.read_json(path)
            participants = {str(ref) for ref in operation.get("formation_refs", [])}
            own = participants & controlled_refs
            if not own:
                continue
            battlefields: list[dict[str, Any]] = []
            for battlefield_ref, battlefield in sorted((operation.get("battlefields") or {}).items()):
                if not isinstance(battlefield_ref, str) or not isinstance(battlefield, Mapping):
                    continue
                assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
                own_assignments = {
                    formation_ref: dict(assignments[formation_ref])
                    for formation_ref in sorted(own)
                    if isinstance(assignments.get(formation_ref), Mapping)
                }
                player_sides = {str(row.get("side_ref")) for row in own_assignments.values() if row.get("side_ref")}
                delivered_reports = [
                    {
                        key: report.get(key)
                        for key in ("report_id", "sector_ref", "target_side_ref", "level", "pressure_milli", "created_at", "delivered_at", "summary")
                        if key in report
                    }
                    for report in battlefield.get("reports", [])
                    if isinstance(report, Mapping)
                    and report.get("status") == "delivered"
                    and report.get("target_side_ref") in player_sides
                ]
                battlefields.append({
                    "battlefield_ref": battlefield_ref,
                    "name": battlefield.get("name"),
                    "status": battlefield.get("status"),
                    "layout_ref": battlefield.get("layout_ref"),
                    "sector_refs": sorted(str(ref) for ref in (battlefield.get("sectors") or {}) if isinstance(ref, str)),
                    "controlled_assignments": own_assignments,
                    "delivered_reports": delivered_reports,
                    "opened_at": battlefield.get("opened_at"),
                    "updated_at": battlefield.get("updated_at"),
                })
            views.append({
                "operation_ref": operation_ref,
                "status": operation.get("status"),
                "objective": operation.get("objective"),
                "location_ref": operation.get("location_ref"),
                "controlled_formation_refs": sorted(own),
                "battlefields": battlefields,
            })
        return views

    def _validate_interaction_authority(self, command: CommandEnvelope) -> None:
        payload = validate_interaction_payload(command.payload)
        base = super().play_context()
        player_id = str(base["campaign"]["player_id"])
        all_formations = self._all_controlled_formations(player_id)
        controlled_refs = {str(item["formation_ref"]) for item in all_formations if item.get("formation_ref")}
        permitted = set(base.get("permitted_person_ids", [])) | set(base.get("permitted_object_refs", []))

        target_ref = payload["target_ref"]
        target_visible = target_ref in permitted or triggered_interaction_record(self.store, target_ref) is not None
        current_location = base.get("player", {}).get("location")
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

    def _translate_surface_command(self, command: CommandEnvelope) -> CommandEnvelope:
        if command.command_type == "scene_consequence":
            raise OperationError(422, "raw_scene_consequence_not_player_authored")
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

        player_id = str(context["campaign"]["player_id"])
        handles, handle_refs, handle_count = self._interaction_refs()
        attempts, _ = recent_interaction_attempts(self.store, player_id)
        attempts = list(reversed(attempts))

        # Preserve a presentation-only anchor, then replace a stale authored
        # scene with a revision-matched projection made only from exact current
        # owners, triggered event-registry facts, and typed player attempts.
        scene_context = context.get("scene")
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
                projection = fresh_runtime_projection(context, handles, attempts)
                projection["continuity_anchor"] = continuity_anchor
                context["scene"] = projection
                scene_context = projection
                context.setdefault("narration_guidance", {})["stale_scene_policy"] = (
                    "stale authored scene claims are stripped; the runtime supplies a revision-matched "
                    "minimal projection from exact current owners, triggered event facts, and typed "
                    "player interaction attempts, while older prose remains presentation-only continuity"
                )
            else:
                scene_context.setdefault("continuity_anchor", None)

        # Keep ordinary turn handoff bounded. Paging and exact revalidation are
        # escape hatches, so projection limits never become world cardinality limits.
        known_all = list(context.get("known_information", []))
        known_recent = list(reversed(known_all[-HOT_INFORMATION_LIMIT:]))
        context["known_information"] = known_recent
        context["known_information_count"] = len(known_all)
        context["known_information_truncated"] = len(known_all) > len(known_recent)

        formations_all = list(context.get("controlled_formations", []))
        player_location = context.get("player", {}).get("location")
        formations_all.sort(key=lambda item: self._formation_sort_key(item, player_location))
        formations_hot = formations_all[:HOT_FORMATION_LIMIT]
        context["controlled_formations"] = formations_hot
        context["controlled_formations_count"] = len(formations_all)
        context["controlled_formations_truncated"] = len(formations_all) > len(formations_hot)

        all_formation_refs = {str(item.get("formation_ref")) for item in formations_all if item.get("formation_ref")}
        hot_formation_refs = {str(item.get("formation_ref")) for item in formations_hot if item.get("formation_ref")}
        controlled_operation_views = self._controlled_operation_views(all_formation_refs)
        controlled_operation_refs = {str(item["operation_ref"]) for item in controlled_operation_views}
        all_commanders = {str(item.get("commander_ref")) for item in formations_all if item.get("commander_ref")}
        hot_commanders = {str(item.get("commander_ref")) for item in formations_hot if item.get("commander_ref")}
        permitted_objects = set(context.get("permitted_object_refs", [])) - all_formation_refs
        permitted_objects.update(hot_formation_refs)
        permitted_objects.update(controlled_operation_refs)
        permitted_objects.update(handle_refs)
        context["permitted_object_refs"] = sorted(permitted_objects)
        permitted_people = set(context.get("permitted_person_ids", [])) - all_commanders
        permitted_people.update(hot_commanders)
        permitted_people.add(player_id)
        context["permitted_person_ids"] = sorted(permitted_people)

        context["interaction_handles"] = handles
        context["interaction_handles_count"] = handle_count
        context["interaction_handles_truncated"] = handle_count > len(handles)
        context["recent_interaction_attempts"] = attempts
        context["controlled_operations"] = controlled_operation_views

        read_hints = context.setdefault("read_hints", {})
        if context["controlled_formations_truncated"]:
            read_hints["controlled_formations_page"] = {
                "tool": "list_controlled_formations",
                "next_cursor": str(len(formations_hot)),
            }
        if context["known_information_truncated"]:
            read_hints["known_information_page"] = {
                "tool": "list_known_information",
                "next_cursor": str(len(known_recent)),
            }
        if context["interaction_handles_truncated"]:
            read_hints["interaction_handles_page"] = {
                "tool": "list_interaction_handles",
                "next_cursor": str(len(handles)),
            }

        commands = context.setdefault("commands", {})
        command_types = dict(commands.get("command_types", {}))
        command_types.pop("scene_consequence", None)
        command_types["interaction_action"] = {
            "accepted_payload_keys": ["action", "formation_refs", "player_statement", "posture", "process_ref", "target_ref"],
            "input_guidance": {
                "target_ref": {
                    "rule": (
                        "use an exact permitted person/object or returned interaction_ref; seek_contact may "
                        "instead target the player's exact current location to record an attempt to find a lawful receiving channel"
                    )
                },
                "process_ref": {"rule": "optional exact permitted process/interaction ref"},
                "action": {"allowed_values": sorted(INTERACTION_ACTIONS)},
                "formation_refs": {"rule": "optional unique exact controlled formation refs"},
                "player_statement": {"type": "string", "maximum_length": 2000, "rule": "player-authored speech only"},
                "posture": {"type": "string", "maximum_length": 500, "rule": "player-authored posture only"},
                "outcome_rule": "NPC/world response fields are forbidden; an interaction command commits only the player's attempt unless another runtime authority establishes a response.",
                "time_rule": "interaction_action never advances chronology; elapsed waiting must use advance_time.",
            },
            "contested_preview_policy": "attempt_only_no_external_outcome",
        }
        commands["command_types"] = command_types
        commands["supported_command_types"] = sorted(command_types)
        commands["hidden_internal_command_types"] = ["scene_consequence"]

        runtime = self.runtime.store.read_json("state/runtime.json")
        wake = runtime.get("pending_wake") if isinstance(runtime, Mapping) else None
        if isinstance(wake, Mapping):
            wake_operation_ref = wake.get("operation_ref")
            if isinstance(wake_operation_ref, str) and wake_operation_ref:
                context.setdefault("permitted_object_refs", [])
                context["permitted_object_refs"] = sorted(set(context["permitted_object_refs"]) | {wake_operation_ref})
            context["pending_wake"] = {key: wake[key] for key in _WAKE_VISIBLE_FIELDS if key in wake}
            context["decision_required"] = True
            if wake.get("kind") == "campaign_event":
                response_types = list(commands.get("supported_command_types", []))
                context["pending_wake"]["response_command_types"] = response_types
                context["pending_wake"]["continue_command"] = "advance_time"
                context["decision_reason"] = "campaign_event_boundary"
                commands["availability_scope"] = "campaign_event_response"
                commands["temporarily_available_command_types"] = response_types
            elif wake.get("kind") == "battlefield_report":
                response_types = sorted(set(_WAKE_RESPONSE_COMMANDS) | {'interaction_action'})
                if "scene_consequence" in response_types:
                    response_types.remove("scene_consequence")
                context["pending_wake"]["response_command_types"] = response_types
                context["pending_wake"]["continue_command"] = "advance_time"
                context["decision_reason"] = "battlefield_report_boundary"
                commands["availability_scope"] = "battlefield_report_response"
                commands["temporarily_available_command_types"] = response_types
            else:
                response_types = sorted(set(_WAKE_RESPONSE_COMMANDS) | {'interaction_action'})
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

    def list_controlled_formations(self, cursor: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        offset = self._cursor_offset(cursor, "formation_page_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 64:
            raise OperationError(422, "formation_page_invalid")
        player_id = self._player_actor()
        values = self._all_controlled_formations(player_id)
        player_location = self.store.read_json("state/player.json").get("location")
        values.sort(key=lambda item: self._formation_sort_key(item, player_location))
        page = values[offset:offset + limit]
        next_offset = offset + len(page)
        return {
            "cursor": cursor,
            "count": len(values),
            "returned": len(page),
            "truncated": next_offset < len(values),
            "next_cursor": str(next_offset) if next_offset < len(values) else None,
            "formations": page,
        }

    def list_known_information(self, cursor: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        offset = self._cursor_offset(cursor, "information_page_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 64:
            raise OperationError(422, "information_page_invalid")
        values = list(reversed(self._all_known_information(self._player_actor())))
        page = values[offset:offset + limit]
        next_offset = offset + len(page)
        return {
            "cursor": cursor,
            "count": len(values),
            "returned": len(page),
            "truncated": next_offset < len(values),
            "next_cursor": str(next_offset) if next_offset < len(values) else None,
            "known_information": page,
        }

    def list_interaction_handles(self, cursor: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
        try:
            return triggered_interaction_page(self.store, cursor=cursor, limit=limit)
        except ValueError as exc:
            raise OperationError(422, "interaction_page_invalid") from exc

    def inspect_game_object(self, object_ref: str) -> dict[str, Any]:
        interaction = triggered_interaction_record(self.store, object_ref)
        if interaction is not None:
            return {"object_ref": object_ref, "visibility": "player_visible_triggered_event", "object": interaction}
        context = self.play_context()
        operation_view = next((row for row in context.get("controlled_operations", []) if row.get("operation_ref") == object_ref), None)
        if isinstance(operation_view, Mapping):
            return {"object_ref": object_ref, "visibility": "controlled_operation", "object": dict(operation_view)}
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
        owners = self.store.read_json("state/index/owner-index.json").get("owners", {})
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
        if command.command_type == "scene_consequence":
            return super().lookup_command_receipt(command)
        translated = self._translate_surface_command(command)
        receipt = super().lookup_command_receipt(translated)
        if receipt is not None and command.command_type == "interaction_action":
            receipt = dict(receipt)
            receipt["surface_command_type"] = "interaction_action"
        return receipt

    def execute_command(self, command):
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")
        if command.command_type == "scene_consequence":
            existing = super().lookup_command_receipt(command)
            if existing is not None:
                return existing
            raise OperationError(422, "raw_scene_consequence_not_player_authored")
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
