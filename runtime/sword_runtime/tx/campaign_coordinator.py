"""Production transaction coordinator with strict current-revision receipt integrity."""
from __future__ import annotations

from sword_runtime.store.overlay import StagedOverlay
from sword_runtime.tx.coordinator import (
    RecoveryDecision,
    TransactionCoordinator as _BaseTransactionCoordinator,
)
from sword_runtime.tx.errors import RecoveryError
from sword_runtime.tx.locking import SingleWriterLock


class TransactionCoordinator(_BaseTransactionCoordinator):
    """Keep current idempotency receipts consistent with the live campaign revision.

    A campaign never rewinds committed gameplay revisions. If a private receipt
    claims a revision newer than current campaign state, the runtime fails
    closed. A newly supplied revision-1 save starts with a fresh private runtime
    volume rather than carrying receipt tombstones in campaign state.
    """

    def _assert_receipt_integrity(self) -> None:
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
            if receipt.committed_revision > current_revision:
                raise RecoveryError(
                    "idempotency receipt claims a future campaign revision; "
                    "reset or restore the matching campaign state before startup"
                )

    def recover(self) -> tuple[RecoveryDecision, ...]:
        with SingleWriterLock(self.lock_path, timeout=self.lock_timeout):
            decisions = self._recover_locked()
            self.git.assert_pristine()
            if self.remote_durability is not None:
                self.remote_durability.verify_synchronized()
            self._assert_receipt_integrity()
            return decisions

    def validate_preview_plan(
        self,
        command,
        transaction_id: str,
        created_at: str,
        writes,
        validator,
    ):
        """Validate one deterministic staged plan without preparing or persisting it.

        The execution path validates against ``StagedOverlay`` only after WAL
        preparation. A player-facing preview must run the same staged validator
        before it can be advertised as executable, otherwise an invalid nested
        schema can receive an execution attestation that execute must reject.
        This method deliberately performs no WAL, receipt, Git commit, or campaign
        mutation; execute validates again under its own transaction boundary.
        """
        if not callable(validator):
            raise TypeError("a staged-overlay validator callback is required")
        with SingleWriterLock(self.lock_path, timeout=self.lock_timeout):
            self.git.assert_pristine()
            if self.remote_durability is not None:
                self.remote_durability.verify_synchronized()
            manifest = self.planner.plan(
                command,
                transaction_id=transaction_id,
                created_at=created_at,
                writes=writes,
            )
            overlay = StagedOverlay(self.repository, manifest)
            validator(overlay, manifest)
            # The validator is read-only. Mirror execute's post-validation guards
            # so a preview cannot bless a plan whose base changed underneath it.
            self.git.assert_pristine()
            self.repository.require_campaign(command.campaign_id, self.meta_path)
            self.repository.require_revision(command.expected_revision, self.meta_path)
            return manifest


__all__ = ["TransactionCoordinator"]
