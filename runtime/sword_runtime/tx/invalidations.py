"""Machine-readable tombstones for explicitly repaired Sword transactions."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping, Tuple

from sword_runtime.commands.envelope import CommandEnvelope
from sword_runtime.tx.receipts import IdempotencyReceipt

TRANSACTION_INVALIDATIONS_PATH = "runtime/contracts/transaction-invalidations.json"
_MAX_INVALIDATIONS = 512


@dataclass(frozen=True)
class TransactionInvalidation:
    campaign_id: str
    transaction_id: str
    request_id: str
    request_digest: str
    invalidated_revision: int
    restored_revision: int
    bad_commit: str
    repair_commit: str
    reason: str


def _hex(value: object, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _expected_transaction_id(request_digest: str, restored_revision: int) -> str:
    material = f"{request_digest}:{restored_revision}".encode("utf-8")
    return "sword-" + hashlib.sha256(material).hexdigest()[:24]


def load_transaction_invalidations(repository) -> Tuple[TransactionInvalidation, ...]:
    """Load exact repair tombstones. Missing registry means no invalidations."""

    try:
        record = repository.read_json(TRANSACTION_INVALIDATIONS_PATH)
    except FileNotFoundError:
        return ()
    if (
        not isinstance(record, Mapping)
        or record.get("schema") != "sword.transaction-invalidations"
        or record.get("version") != 1
    ):
        raise ValueError("transaction invalidation registry is invalid")
    rows = record.get("records")
    if not isinstance(rows, list) or len(rows) > _MAX_INVALIDATIONS:
        raise ValueError("transaction invalidation registry is invalid")

    result = []
    seen_requests = set()
    seen_transactions = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ValueError("transaction invalidation record is invalid")
        campaign_id = raw.get("campaign_id")
        transaction_id = raw.get("transaction_id")
        request_id = raw.get("request_id")
        request_digest = raw.get("request_digest")
        invalidated_revision = raw.get("invalidated_revision")
        restored_revision = raw.get("restored_revision")
        bad_commit = raw.get("bad_commit")
        repair_commit = raw.get("repair_commit")
        reason = raw.get("reason")
        if (
            not isinstance(campaign_id, str)
            or not campaign_id
            or not isinstance(transaction_id, str)
            or not transaction_id
            or not isinstance(request_id, str)
            or not request_id
            or not _hex(request_digest, 64)
            or isinstance(invalidated_revision, bool)
            or not isinstance(invalidated_revision, int)
            or isinstance(restored_revision, bool)
            or not isinstance(restored_revision, int)
            or invalidated_revision <= restored_revision
            or restored_revision < 0
            or transaction_id != _expected_transaction_id(request_digest, restored_revision)
            or not _hex(bad_commit, 40)
            or not _hex(repair_commit, 40)
            or not isinstance(reason, str)
            or not reason.strip()
            or request_id in seen_requests
            or transaction_id in seen_transactions
        ):
            raise ValueError("transaction invalidation record is invalid")
        seen_requests.add(request_id)
        seen_transactions.add(transaction_id)
        result.append(
            TransactionInvalidation(
                campaign_id=campaign_id,
                transaction_id=transaction_id,
                request_id=request_id,
                request_digest=request_digest,
                invalidated_revision=invalidated_revision,
                restored_revision=restored_revision,
                bad_commit=bad_commit,
                repair_commit=repair_commit,
                reason=reason,
            )
        )
    return tuple(result)


def receipt_is_invalidated(
    receipt: IdempotencyReceipt,
    invalidations: Tuple[TransactionInvalidation, ...],
    *,
    current_revision: int,
) -> bool:
    """Return true only for an exact receipt named by a completed state repair."""

    return any(
        receipt.campaign_id == row.campaign_id
        and receipt.transaction_id == row.transaction_id
        and receipt.request_id == row.request_id
        and receipt.request_digest == row.request_digest
        and receipt.committed_revision == row.invalidated_revision
        and current_revision >= row.restored_revision
        for row in invalidations
    )


def command_matches_invalidated_request(
    command: CommandEnvelope,
    invalidations: Tuple[TransactionInvalidation, ...],
) -> bool:
    """Prevent an invalidated external request ID from being replayed."""

    return any(
        command.campaign_id == row.campaign_id
        and command.request_id == row.request_id
        and command.digest == row.request_digest
        for row in invalidations
    )


__all__ = [
    "TRANSACTION_INVALIDATIONS_PATH",
    "TransactionInvalidation",
    "command_matches_invalidated_request",
    "load_transaction_invalidations",
    "receipt_is_invalidated",
]
