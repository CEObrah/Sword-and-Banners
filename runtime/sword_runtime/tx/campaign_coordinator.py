"""Production coordinator guards for campaigns that may undergo explicit repair."""
from __future__ import annotations

from sword_runtime.commands.envelope import CommandEnvelope
from sword_runtime.tx.coordinator import (
    RecoveryDecision,
    TransactionCoordinator as _BaseTransactionCoordinator,
)
from sword_runtime.tx.errors import IdempotencyConflictError, RecoveryError
from sword_runtime.tx.invalidations import (
    command_matches_invalidated_request,
    load_transaction_invalidations,
    receipt_is_invalidated,
)
from sword_runtime.tx.locking import SingleWriterLock



class TransactionCoordinator(_BaseTransactionCoordinator):
    """Fail closed on unexplained future receipts after a campaign repair.

    A deliberate repair can restore campaign state to an earlier revision while
    immutable runtime receipts still remember the removed transaction. Exact
    tombstones distinguish that reviewed repair from unexplained corruption and
    permanently reserve the invalidated request ID.
    """

    def _invalidations(self):
        try:
            return load_transaction_invalidations(self.repository)
        except (TypeError, ValueError) as exc:
            raise RecoveryError("transaction invalidation registry is invalid") from exc

    def _assert_invalidated_request_not_retried(self, command: CommandEnvelope) -> None:
        if command_matches_invalidated_request(command, self._invalidations()):
            raise IdempotencyConflictError(
                "request ID belongs to an explicitly invalidated campaign transaction; "
                "submit the intended action with a new request ID"
            )

    def _assert_receipt_integrity(self) -> None:
        invalidations = self._invalidations()
        try:
            campaign_id = self.repository.campaign_id(self.meta_path)
            current_revision = self.repository.current_revision(self.meta_path)
            paths = sorted(self.receipts.directory.glob("*.json"))
        except (OSError, TypeError, ValueError) as exc:
            raise RecoveryError("idempotency receipt integrity check failed") from exc
        for path in paths:
            try:
                receipt = self.receipts._read(path)
            except (OSError, TypeError, ValueError) as exc:
                raise RecoveryError("corrupt idempotency receipt detected") from exc
            if receipt.campaign_id != campaign_id:
                continue
            if receipt.committed_revision <= current_revision:
                continue
            if receipt_is_invalidated(
                receipt,
                invalidations,
                current_revision=current_revision,
            ):
                continue
            raise RecoveryError(
                "idempotency receipt claims a future campaign revision without "
                "an exact registered repair invalidation"
            )

    def recover(self) -> tuple[RecoveryDecision, ...]:
        """Recover WAL/Git state, then verify receipt history against repairs."""

        with SingleWriterLock(self.lock_path, timeout=self.lock_timeout):
            decisions = self._recover_locked()
            self.git.assert_pristine()
            if self.remote_durability is not None:
                self.remote_durability.verify_synchronized()
            self._assert_receipt_integrity()
            return decisions

    def lookup_receipt(self, command: CommandEnvelope):
        self._assert_invalidated_request_not_retried(command)
        return super().lookup_receipt(command)

    def execute(self, command: CommandEnvelope, *args, **kwargs):
        self._assert_invalidated_request_not_retried(command)
        return super().execute(command, *args, **kwargs)


__all__ = ["TransactionCoordinator"]
