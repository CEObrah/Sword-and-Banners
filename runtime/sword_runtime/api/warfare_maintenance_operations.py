"""Explicit OOC maintenance operation for the warfare/House/GBG command repair."""
from __future__ import annotations

from typing import Any, Optional

from sword_runtime.api.maintenance_operations import QinCommandMaintenanceOperations, _receipt_record
from sword_runtime.api.operations import OperationError
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import RepositoryCommandPlanner
from sword_runtime.tx.canonical import thaw_json
from sword_runtime.tx.errors import StaleRevisionError

_REPAIR_ID = "warfare_house_gbg_depth_v3"
_REPAIR_REASON = (
    "OOC DEV: complete the Great Bow Guard scale repair, split the Qin Border Detachment into four conserved "
    "2,000-fighter persistent units, materialize conserved officer rosters, reconcile Qin support, and preserve "
    "multi-formation briefing and command-assumption continuity"
)


class WarfareHouseMaintenanceOperations(QinCommandMaintenanceOperations):
    """Existing player/maintenance surface plus one registered multi-owner repair."""

    def _build_warfare_house_scale_repair(self, request_id: str, expected_revision: int) -> CommandEnvelope:
        meta = self.store.read_json("state/meta.json")
        if expected_revision != int(meta.get("revision", -1)):
            raise OperationError(409, "stale_revision")
        return CommandEnvelope(
            campaign_id=str(meta["campaign_id"]),
            request_id=request_id,
            actor_id=RepositoryCommandPlanner.INTERNAL_ACTOR,
            command_type="repair_bundle",
            expected_revision=expected_revision,
            submitted_at=str(meta.get("time", "")),
            payload={"repair_id": _REPAIR_ID, "reason": _REPAIR_REASON},
            mode="maintenance",
        )

    @staticmethod
    def _validate_warfare_house_scale_repair(command: CommandEnvelope) -> None:
        payload = thaw_json(command.payload)
        if (
            command.actor_id != RepositoryCommandPlanner.INTERNAL_ACTOR
            or command.command_type != "repair_bundle"
            or command.mode != "maintenance"
            or payload != {"repair_id": _REPAIR_ID, "reason": _REPAIR_REASON}
        ):
            raise OperationError(403, "warfare_house_scale_repair_envelope_forbidden")

    def preview_warfare_house_scale_repair(
        self, request_id: str, expected_revision: int
    ) -> tuple[dict[str, Any], CommandEnvelope]:
        command = self._build_warfare_house_scale_repair(request_id, expected_revision)
        try:
            preview = self.runtime.preview_for_execution(command)
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "maintenance_repair_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "warfare_house_scale_repair_rejected") from exc
        return preview, command

    def lookup_warfare_house_scale_repair_receipt(self, command: CommandEnvelope) -> Optional[dict[str, Any]]:
        self._validate_warfare_house_scale_repair(command)
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

    def execute_warfare_house_scale_repair(self, command: CommandEnvelope) -> dict[str, Any]:
        self._validate_warfare_house_scale_repair(command)
        try:
            return _receipt_record(self.runtime.execute(command))
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "maintenance_repair_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "warfare_house_scale_repair_rejected") from exc
        except Exception as exc:
            raise OperationError(503, "campaign_runtime_unavailable") from exc


__all__ = ["WarfareHouseMaintenanceOperations"]
