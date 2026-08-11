"""Production operations with stable low-information failure classification."""
from __future__ import annotations

from sword_runtime.api.operations import CampaignOperations, OperationError, _receipt_record
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


def transaction_failure_code(exc: TransactionError) -> str:
    for exc_type, code in _TRANSACTION_CODES.items():
        if isinstance(exc, exc_type):
            return code
    return "transaction_rejected"


class StableCampaignOperations(CampaignOperations):
    """Player surface that fails closed without leaking server/Git internals."""

    def play_context(self):
        context = super().play_context()
        context.setdefault("limits", {})["high_salience_wake_boundary"] = True
        context["limits"]["operational_memory_is_non_authoritative"] = True
        return context

    def preview_command(self, command):
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")
        try:
            return self.runtime.preview_for_execution(command)
        except HighSalienceWakeRequired as exc:
            raise OperationError(409, "high_salience_wake_required") from exc
        except StaleRevisionError as exc:
            raise OperationError(409, "stale_revision") from exc
        except PermissionError as exc:
            raise OperationError(403, "command_not_authorized") from exc
        except (TypeError, ValueError, FileNotFoundError) as exc:
            raise OperationError(422, "command_rejected") from exc

    def execute_command(self, command):
        if command.actor_id != self._player_actor() or command.mode != "gameplay":
            raise OperationError(403, "player_surface_forbids_internal_mode")
        try:
            return _receipt_record(self.runtime.execute(command))
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
