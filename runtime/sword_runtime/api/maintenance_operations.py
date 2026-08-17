"""Narrow OOC maintenance operations for explicit campaign repairs."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Optional

from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.api.operations import OperationError
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import RepositoryCommandPlanner
from sword_runtime.qin_command_progression import render_probationary_offer, repaired_offer_details
from sword_runtime.tx.canonical import thaw_json
from sword_runtime.tx.errors import StaleRevisionError

_PLAYER_PATH = "state/player.json"
_RULES_PATH = "game/data/mechanics/career-progression.json"
_REPAIR_REASON = "OOC DEV: replace oversized first Qin field-command offer with scale-matched probationary detachment"


def _receipt_record(execution: Any) -> dict[str, Any]:
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


class QinCommandMaintenanceOperations(EquipmentAwareCampaignOperations):
    """Player surface plus one provenance-backed, fail-closed command-offer repair."""

    def _build_qin_offer_repair(self, request_id: str, expected_revision: int, offer_ref: str) -> CommandEnvelope:
        meta = self.store.read_json("state/meta.json")
        if expected_revision != int(meta.get("revision", -1)):
            raise OperationError(409, "stale_revision")
        player = copy.deepcopy(self.store.read_json(_PLAYER_PATH))
        career = player.get("career_state")
        offers = career.get("pending_qin_command_offers") if isinstance(career, Mapping) else None
        details = offers.get(offer_ref) if isinstance(offers, Mapping) else None
        if not isinstance(career, dict) or not isinstance(offers, dict) or not isinstance(details, Mapping):
            raise OperationError(404, "qin_command_offer_not_pending")
        if offer_ref not in career.get("pending_qin_command_offer_refs", []):
            raise OperationError(409, "qin_command_offer_not_pending")
        rules_doc = self.store.read_json(_RULES_PATH)
        rules = rules_doc.get("qin_field_command", {}) if isinstance(rules_doc, Mapping) else {}
        if not isinstance(rules, Mapping):
            raise OperationError(503, "career_progression_rules_unavailable")
        at = str(meta.get("time", ""))
        normalized = repaired_offer_details(player, rules, offer_ref, details, at)
        if normalized.get("offer_kind") != "qin_probationary_detachment_command":
            raise OperationError(409, "qin_command_offer_scale_repair_not_needed")
        if dict(details) == normalized:
            raise OperationError(409, "qin_command_offer_scale_repair_not_needed")
        old_personnel = max(0, int(details.get("personnel", 0) or 0))
        new_personnel = max(0, int(normalized.get("personnel", 0) or 0))
        offers[offer_ref] = normalized
        repairs = career.setdefault("offer_scale_repairs", [])
        repairs.append({
            "offer_ref": offer_ref,
            "repaired_at": at,
            "revision_before": expected_revision,
            "from_personnel": old_personnel,
            "to_personnel": new_personnel,
            "parent_formation_ref": normalized.get("parent_formation_ref"),
            "reason": _REPAIR_REASON,
        })
        career["offer_scale_repairs"] = repairs[-16:]
        career["last_command_scale_review_at"] = at
        return CommandEnvelope(
            campaign_id=str(meta["campaign_id"]),
            request_id=request_id,
            actor_id=RepositoryCommandPlanner.INTERNAL_ACTOR,
            command_type="repair",
            expected_revision=expected_revision,
            submitted_at=at,
            payload={
                "path": _PLAYER_PATH,
                "changes": {"career_state": career},
                "reason": _REPAIR_REASON,
            },
            mode="maintenance",
        )

    @staticmethod
    def _validate_qin_offer_repair_envelope(command: CommandEnvelope) -> None:
        payload = command.payload
        if (
            command.actor_id != RepositoryCommandPlanner.INTERNAL_ACTOR
            or command.command_type != "repair"
            or command.mode != "maintenance"
            or payload.get("path") != _PLAYER_PATH
            or set(payload.get("changes", {})) != {"career_state"}
            or payload.get("reason") != _REPAIR_REASON
        ):
            raise OperationError(403, "maintenance_repair_envelope_forbidden")

    def preview_qin_command_offer_scale_repair(
        self, request_id: str, expected_revision: int, offer_ref: str
    ) -> tuple[dict[str, Any], CommandEnvelope]:
        command = self._build_qin_offer_repair(request_id, expected_revision, offer_ref)
        try:
            preview = self.runtime.preview_for_execution(command)
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "maintenance_repair_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "maintenance_repair_rejected") from exc
        return preview, command

    def lookup_qin_command_offer_scale_repair_receipt(self, command: CommandEnvelope) -> Optional[dict[str, Any]]:
        self._validate_qin_offer_repair_envelope(command)
        try:
            receipt = self.runtime.coordinator.lookup_receipt(command)
        except StaleRevisionError:
            receipt = None
        if receipt is None:
            return None
        return {
            "status": "duplicate",
            "request_id": receipt.request_id,
            "transaction_id": receipt.transaction_id,
            "campaign_id": receipt.campaign_id,
            "committed_revision": receipt.committed_revision,
            "committed_at": receipt.committed_at,
            "result": thaw_json(receipt.result),
        }

    def execute_qin_command_offer_scale_repair(self, command: CommandEnvelope) -> dict[str, Any]:
        self._validate_qin_offer_repair_envelope(command)
        try:
            return _receipt_record(self.runtime.execute(command))
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "maintenance_repair_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "maintenance_repair_rejected") from exc
        except Exception as exc:
            raise OperationError(503, "campaign_runtime_unavailable") from exc

    def _current_repaired_offer(self) -> tuple[str, Mapping[str, Any], str] | None:
        player = self.store.read_json(_PLAYER_PATH)
        career = player.get("career_state", {}) if isinstance(player, Mapping) else {}
        refs = career.get("pending_qin_command_offer_refs", []) if isinstance(career, Mapping) else []
        offers = career.get("pending_qin_command_offers", {}) if isinstance(career, Mapping) else {}
        if not isinstance(refs, list) or not isinstance(offers, Mapping):
            return None
        for offer_ref in refs:
            if not isinstance(offer_ref, str):
                continue
            details = offers.get(offer_ref)
            if isinstance(details, Mapping) and details.get("offer_kind") == "qin_probationary_detachment_command":
                return offer_ref, details, render_probationary_offer(details)
        return None

    @staticmethod
    def _overlay_offer_projection(value: Any, offer_ref: str, summary: str) -> None:
        if isinstance(value, dict):
            if value.get("interaction_ref") == offer_ref and "summary" in value:
                value["summary"] = summary
            if value.get("campaign_event_ref") == offer_ref and "reason" in value:
                value["reason"] = summary
            for child in value.values():
                QinCommandMaintenanceOperations._overlay_offer_projection(child, offer_ref, summary)
        elif isinstance(value, list):
            for child in value:
                QinCommandMaintenanceOperations._overlay_offer_projection(child, offer_ref, summary)

    def play_context(self) -> dict[str, Any]:
        context = super().play_context()
        repaired = self._current_repaired_offer()
        if repaired is not None:
            offer_ref, _details, summary = repaired
            self._overlay_offer_projection(context, offer_ref, summary)
        return context

    def inspect_game_object(self, object_ref: str) -> dict[str, Any]:
        result = super().inspect_game_object(object_ref)
        repaired = self._current_repaired_offer()
        if repaired is not None and object_ref == repaired[0]:
            obj = result.get("object")
            if isinstance(obj, dict) and "summary" in obj:
                obj["summary"] = repaired[2]
        return result


__all__ = ["QinCommandMaintenanceOperations"]
