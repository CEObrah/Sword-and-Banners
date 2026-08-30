"""Explicit transaction manifests and optimistic write-set planning."""

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from sword_runtime.commands.envelope import CommandEnvelope
from sword_runtime.store.paths import normalize_relative_path
from sword_runtime.store.repository import RepositoryStore
from sword_runtime.tx.canonical import canonical_sha256, sha256_bytes


def _validate_digest(value: Optional[str], field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("%s must be a SHA-256 hex digest or null" % field)
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError("%s must be hexadecimal" % field) from exc


@dataclass(frozen=True)
class FileMutation:
    """One create, update, or delete with an exact expected base image."""

    path: str
    before_sha256: Optional[str]
    after_bytes: Optional[bytes]

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_relative_path(self.path))
        _validate_digest(self.before_sha256, "before_sha256")
        if self.after_bytes is not None and not isinstance(self.after_bytes, bytes):
            raise TypeError("after_bytes must be bytes or null")
        if self.before_sha256 is None and self.after_bytes is None:
            raise ValueError("missing-to-missing mutation is invalid")
        if self.after_sha256 == self.before_sha256:
            raise ValueError("no-op file mutation is invalid")

    @property
    def after_sha256(self) -> Optional[str]:
        return None if self.after_bytes is None else sha256_bytes(self.after_bytes)

    @property
    def operation(self) -> str:
        if self.after_bytes is None:
            return "delete"
        if self.before_sha256 is None:
            return "create"
        return "update"

    def to_record(self) -> Mapping[str, Any]:
        return {
            "path": self.path,
            "operation": self.operation,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
        }


@dataclass(frozen=True)
class TransactionManifest:
    """Complete, deterministic set of files one transaction may touch."""

    transaction_id: str
    campaign_id: str
    request_id: str
    command_digest: str
    mode: str
    base_revision: int
    target_revision: int
    created_at: str
    mutations: Tuple[FileMutation, ...]

    SCHEMA = "sword.transaction-manifest"
    VERSION = 1

    def __post_init__(self) -> None:
        for field in (
            "transaction_id",
            "campaign_id",
            "request_id",
            "mode",
            "created_at",
        ):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or not value.strip()
                or any(character in value for character in ("\x00", "\r", "\n"))
            ):
                raise ValueError("%s must be a non-empty string" % field)
        if self.mode not in ("gameplay", "autonomous", "maintenance"):
            raise ValueError("transaction mode must be gameplay or maintenance")
        _validate_digest(self.command_digest, "command_digest")
        if self.command_digest is None:
            raise ValueError("command_digest is required")
        for field in ("base_revision", "target_revision"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("%s must be a non-negative integer" % field)
        expected_target = (
            self.base_revision + 1
        )
        if self.target_revision != expected_target:
            raise ValueError(
                "%s transaction target revision must be %d"
                % (self.mode, expected_target)
            )
        if not isinstance(self.mutations, tuple):
            object.__setattr__(self, "mutations", tuple(self.mutations))
        if not self.mutations:
            raise ValueError("transaction manifest must contain at least one mutation")
        paths = [mutation.path for mutation in self.mutations]
        if len(paths) != len(set(paths)):
            raise ValueError("transaction manifest contains duplicate paths")
        if paths != sorted(paths):
            object.__setattr__(
                self,
                "mutations",
                tuple(sorted(self.mutations, key=lambda item: item.path)),
            )

    @property
    def paths(self) -> Tuple[str, ...]:
        return tuple(mutation.path for mutation in self.mutations)

    def to_record(self) -> Mapping[str, Any]:
        return {
            "schema": self.SCHEMA,
            "version": self.VERSION,
            "transaction_id": self.transaction_id,
            "campaign_id": self.campaign_id,
            "request_id": self.request_id,
            "command_digest": self.command_digest,
            "mode": self.mode,
            "base_revision": self.base_revision,
            "target_revision": self.target_revision,
            "created_at": self.created_at,
            "mutations": [mutation.to_record() for mutation in self.mutations],
        }

    @property
    def digest(self) -> str:
        return canonical_sha256(self.to_record())


class TransactionPlanner:
    """Build a write manifest from current bytes after checking the base revision."""

    def __init__(self, repository: RepositoryStore, meta_path: str = "state/meta.json") -> None:
        self.repository = repository
        self.meta_path = normalize_relative_path(meta_path)

    def plan(
        self,
        command: CommandEnvelope,
        transaction_id: str,
        created_at: str,
        writes: Mapping[str, Optional[bytes]],
        target_revision: Optional[int] = None,
    ) -> TransactionManifest:
        self.repository.require_campaign(command.campaign_id, self.meta_path)
        self.repository.require_revision(command.expected_revision, self.meta_path)
        if command.mode == "ooc":
            raise ValueError("OOC commands may not create transaction manifests")
        if not isinstance(writes, Mapping) or not writes:
            raise ValueError("writes must be a non-empty explicit path map")

        required_revision = (
            command.expected_revision + 1
        )
        final_revision = required_revision if target_revision is None else target_revision
        if final_revision != required_revision:
            raise ValueError(
                "%s transaction must target revision %d"
                % (command.mode, required_revision)
            )

        if command.mode in ("gameplay", "autonomous", "maintenance"):
            if self.meta_path not in writes:
                raise ValueError(
                    "%s manifest must explicitly update %s" % (command.mode, self.meta_path)
                )
            proposed_meta_bytes = writes[self.meta_path]
            if not isinstance(proposed_meta_bytes, bytes):
                raise ValueError("revision-advancing manifest may not delete campaign meta")
            try:
                proposed_meta = json.loads(proposed_meta_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("proposed campaign meta is invalid JSON") from exc
            if not isinstance(proposed_meta, dict):
                raise ValueError("proposed campaign meta must be an object")
            if proposed_meta.get("campaign_id") != command.campaign_id:
                raise ValueError("proposed campaign meta changes campaign identity")
            if proposed_meta.get("revision") != final_revision:
                raise ValueError(
                    "proposed campaign meta does not contain target revision"
                )

        mutations = []
        for path, content in writes.items():
            normalized = normalize_relative_path(path)
            if content is not None and not isinstance(content, bytes):
                raise TypeError("write content for %s must be bytes or null" % normalized)
            before = self.repository.digest(normalized)
            mutations.append(FileMutation(normalized, before, content))

        return TransactionManifest(
            transaction_id=transaction_id,
            campaign_id=command.campaign_id,
            request_id=command.request_id,
            command_digest=command.digest,
            mode=command.mode,
            base_revision=command.expected_revision,
            target_revision=final_revision,
            created_at=created_at,
            mutations=tuple(mutations),
        )
