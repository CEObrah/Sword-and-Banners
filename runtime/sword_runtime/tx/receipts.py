"""Immutable idempotency receipts stored outside mutable campaign owners."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from sword_runtime.commands.envelope import CommandEnvelope
from sword_runtime.tx.canonical import (
    canonical_json_bytes,
    canonical_sha256,
    freeze_json,
    thaw_json,
)
from sword_runtime.tx.errors import IdempotencyConflictError


@dataclass(frozen=True)
class IdempotencyReceipt:
    request_id: str
    request_digest: str
    transaction_id: str
    campaign_id: str
    committed_revision: int
    committed_at: str
    result: Mapping[str, Any]

    SCHEMA = "sword.idempotency-receipt"
    VERSION = 1

    def __post_init__(self) -> None:
        for field in (
            "request_id",
            "request_digest",
            "transaction_id",
            "campaign_id",
            "committed_at",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ValueError("%s must be a non-empty string" % field)
        if len(self.request_digest) != 64:
            raise ValueError("request_digest must be a SHA-256 digest")
        try:
            int(self.request_digest, 16)
        except ValueError as exc:
            raise ValueError("request_digest must be hexadecimal") from exc
        if isinstance(self.committed_revision, bool) or not isinstance(
            self.committed_revision, int
        ):
            raise TypeError("committed_revision must be an integer")
        if self.committed_revision < 0:
            raise ValueError("committed_revision must be non-negative")
        if not isinstance(self.result, Mapping):
            raise TypeError("receipt result must be an object")
        object.__setattr__(self, "result", freeze_json(self.result))

    @classmethod
    def for_command(
        cls,
        command: CommandEnvelope,
        transaction_id: str,
        committed_revision: int,
        committed_at: str,
        result: Mapping[str, Any],
    ) -> "IdempotencyReceipt":
        return cls(
            request_id=command.request_id,
            request_digest=command.digest,
            transaction_id=transaction_id,
            campaign_id=command.campaign_id,
            committed_revision=committed_revision,
            committed_at=committed_at,
            result=result,
        )

    def to_record(self) -> Mapping[str, Any]:
        return {
            "schema": self.SCHEMA,
            "version": self.VERSION,
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "transaction_id": self.transaction_id,
            "campaign_id": self.campaign_id,
            "committed_revision": self.committed_revision,
            "committed_at": self.committed_at,
            "result": thaw_json(self.result),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "IdempotencyReceipt":
        if record.get("schema") != cls.SCHEMA or record.get("version") != cls.VERSION:
            raise ValueError("unsupported idempotency receipt")
        return cls(
            request_id=record.get("request_id"),
            request_digest=record.get("request_digest"),
            transaction_id=record.get("transaction_id"),
            campaign_id=record.get("campaign_id"),
            committed_revision=record.get("committed_revision"),
            committed_at=record.get("committed_at"),
            result=record.get("result"),
        )


class ReceiptStore:
    """Insert-once receipt files keyed by a hash of the external request ID."""

    def __init__(self, directory: object) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, request_id: str) -> Path:
        name = canonical_sha256({"request_id": request_id})
        return self.directory / (name + ".json")

    def _read(self, path: Path) -> IdempotencyReceipt:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("corrupt idempotency receipt: %s" % path) from exc
        if not isinstance(record, dict):
            raise ValueError("idempotency receipt must be an object")
        return IdempotencyReceipt.from_record(record)

    def get(self, request_id: str) -> Optional[IdempotencyReceipt]:
        path = self._path(request_id)
        try:
            return self._read(path)
        except FileNotFoundError:
            return None

    def lookup(self, command: CommandEnvelope) -> Optional[IdempotencyReceipt]:
        receipt = self.get(command.request_id)
        if receipt is None:
            return None
        if receipt.request_id != command.request_id:
            raise IdempotencyConflictError("receipt request identity mismatch")
        if receipt.request_digest != command.digest:
            raise IdempotencyConflictError(
                "request ID was already committed with different command bytes"
            )
        return receipt

    def put(self, receipt: IdempotencyReceipt) -> IdempotencyReceipt:
        path = self._path(receipt.request_id)
        content = canonical_json_bytes(receipt.to_record())
        path.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".%s." % path.name,
            suffix=".tmp",
            dir=str(path.parent),
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(str(temporary), str(path))
            except FileExistsError:
                existing = self._read(path)
                if canonical_json_bytes(existing.to_record()) != content:
                    raise IdempotencyConflictError(
                        "request ID already has a different committed receipt"
                    )
                return existing
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return receipt
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
