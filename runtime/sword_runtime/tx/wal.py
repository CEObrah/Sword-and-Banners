"""Durable write-ahead-log records and deterministic recovery primitives."""

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from sword_runtime.store.paths import normalize_relative_path
from sword_runtime.store.repository import RepositoryStore, atomic_replace_bytes
from sword_runtime.tx.canonical import canonical_json_bytes, canonical_sha256, sha256_bytes
from sword_runtime.tx.errors import ConcurrentModificationError, WalDivergenceError, WalError
from sword_runtime.tx.manifest import FileMutation, TransactionManifest
from sword_runtime.tx.persistence import AtomicManifestPersister


def _encoded(content: Optional[bytes]) -> Optional[str]:
    return None if content is None else base64.b64encode(content).decode("ascii")


def _decoded(content: Optional[str]) -> Optional[bytes]:
    if content is None:
        return None
    if not isinstance(content, str):
        raise WalError("WAL image must be base64 text or null")
    try:
        return base64.b64decode(content.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise WalError("invalid WAL base64 image") from exc


class WriteAheadLog:
    """One immutable-image WAL file per transaction with explicit state changes."""

    SCHEMA = "sword.wal"
    VERSION = 1
    TRANSITIONS = {
        "prepared": frozenset(("applied", "rolled_back")),
        "applied": frozenset(("committed", "rolled_back")),
        "committed": frozenset(),
        "rolled_back": frozenset(),
    }

    def __init__(self, directory: object) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.pending_directory = self.directory / "pending"
        self.terminal_directory = self.directory / "terminal"
        self.pending_directory.mkdir(parents=True, exist_ok=True)
        self.terminal_directory.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_flat_records()

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _record_name(transaction_id: str) -> str:
        if not isinstance(transaction_id, str) or not transaction_id:
            raise ValueError("transaction_id must be a non-empty string")
        return canonical_sha256({"transaction_id": transaction_id}) + ".json"

    def _legacy_path(self, transaction_id: str) -> Path:
        return self.directory / self._record_name(transaction_id)

    def _pending_path(self, transaction_id: str) -> Path:
        return self.pending_directory / self._record_name(transaction_id)

    def _terminal_path(self, transaction_id: str) -> Path:
        return self.terminal_directory / self._record_name(transaction_id)

    def _path(self, transaction_id: str) -> Path:
        """Locate one WAL without scanning history; pending wins during retries."""

        pending = self._pending_path(transaction_id)
        if pending.exists():
            return pending
        terminal = self._terminal_path(transaction_id)
        if terminal.exists():
            return terminal
        legacy = self._legacy_path(transaction_id)
        if legacy.exists():
            return legacy
        return pending

    def _read_path(self, path: Path) -> Mapping[str, Any]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise WalError("WAL record does not exist: %s" % path)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WalError("WAL record is corrupt: %s" % path) from exc
        transaction_id = record.get("transaction_id")
        if not isinstance(transaction_id, str):
            raise WalError("missing WAL transaction ID")
        self._validate_record(record, transaction_id)
        return record

    def _migrate_legacy_flat_records(self) -> None:
        """Move the old flat WAL layout once, without touching terminal history later.

        Legacy committed records intentionally enter ``pending`` first. Recovery
        verifies their Git commit and receipt before archiving them, preserving
        the crash window where a commit existed but its receipt had not yet been
        published. Rolled-back records are already terminal and can move directly
        to the audit-only terminal directory.
        """

        moved_pending = False
        moved_terminal = False
        for path in sorted(self.directory.glob("*.json")):
            record = self._read_path(path)
            destination = (
                self.terminal_directory
                if record["status"] == "rolled_back"
                else self.pending_directory
            ) / path.name
            if destination.exists():
                raise WalError(
                    "legacy WAL migration collides with partitioned record: %s"
                    % destination
                )
            os.replace(str(path), str(destination))
            if destination.parent == self.pending_directory:
                moved_pending = True
            else:
                moved_terminal = True
        if moved_pending:
            self._fsync_directory(self.pending_directory)
        if moved_terminal:
            self._fsync_directory(self.terminal_directory)
        if moved_pending or moved_terminal:
            self._fsync_directory(self.directory)

    def prepare(
        self,
        manifest: TransactionManifest,
        repository: RepositoryStore,
        receipt_record: Optional[Mapping[str, Any]] = None,
        durability_record: Optional[Mapping[str, str]] = None,
    ) -> Mapping[str, Any]:
        entries = []
        for mutation in manifest.mutations:
            before = repository.read_optional_bytes(mutation.path)
            actual = None if before is None else sha256_bytes(before)
            if actual != mutation.before_sha256:
                raise ConcurrentModificationError(
                    mutation.path, mutation.before_sha256, actual
                )
            entries.append(
                {
                    "path": mutation.path,
                    "before_sha256": mutation.before_sha256,
                    "after_sha256": mutation.after_sha256,
                    "before_b64": _encoded(before),
                    "after_b64": _encoded(mutation.after_bytes),
                }
            )

        durability = (
            {"kind": "local"}
            if durability_record is None
            else dict(durability_record)
        )
        self._validate_durability(durability)
        record = {
            "schema": self.SCHEMA,
            "version": self.VERSION,
            "status": "prepared",
            "transaction_id": manifest.transaction_id,
            "manifest_digest": manifest.digest,
            "manifest": manifest.to_record(),
            "entries": entries,
            "receipt": None if receipt_record is None else dict(receipt_record),
            "durability": durability,
            "durability_digest": canonical_sha256(durability),
        }
        pending_path = self._pending_path(manifest.transaction_id)
        terminal_path = self._terminal_path(manifest.transaction_id)
        if pending_path.exists() or terminal_path.exists():
            existing = self.load(manifest.transaction_id)
            if existing.get("manifest_digest") != manifest.digest:
                raise WalError("transaction ID already has a different WAL manifest")
            if existing.get("receipt") != record.get("receipt"):
                raise WalError("transaction ID already has a different WAL receipt")
            if self.durability(existing) != durability:
                raise WalError("transaction ID already has different WAL durability")
            # A rolled-back attempt has no committed gameplay receipt and its
            # exact before-images have been restored.  Re-preparing the same
            # manifest lets an idempotent client retry the identical request
            # after a pre-commit crash instead of permanently poisoning its
            # deterministic transaction ID.  Any changed manifest/receipt or
            # durability contract is rejected above.
            if existing.get("status") == "rolled_back":
                atomic_replace_bytes(
                    pending_path, canonical_json_bytes(record), default_mode=0o600
                )
                return record
            return existing
        atomic_replace_bytes(
            pending_path, canonical_json_bytes(record), default_mode=0o600
        )
        return record

    def load(self, transaction_id: str) -> Mapping[str, Any]:
        path = self._path(transaction_id)
        if not path.exists():
            raise WalError("WAL transaction does not exist: %s" % transaction_id)
        record = self._read_path(path)
        if record.get("transaction_id") != transaction_id:
            raise WalError("WAL transaction identity does not match filename lookup")
        return record

    def _validate_record(self, record: Any, transaction_id: str) -> None:
        if not isinstance(record, dict):
            raise WalError("WAL record must be an object")
        if record.get("schema") != self.SCHEMA or record.get("version") != self.VERSION:
            raise WalError("unsupported WAL record")
        if record.get("transaction_id") != transaction_id:
            raise WalError("WAL transaction identity mismatch")
        if record.get("status") not in self.TRANSITIONS:
            raise WalError("invalid WAL status")
        durability = record.get("durability", {"kind": "local"})
        self._validate_durability(durability)
        if "durability" in record:
            if record.get("durability_digest") != canonical_sha256(durability):
                raise WalError("WAL durability digest mismatch")
        elif "durability_digest" in record:
            raise WalError("legacy WAL has an orphan durability digest")
        manifest = record.get("manifest")
        if not isinstance(manifest, dict):
            raise WalError("WAL manifest must be an object")
        if canonical_sha256(manifest) != record.get("manifest_digest"):
            raise WalError("WAL manifest digest mismatch")
        mutations = manifest.get("mutations")
        if not isinstance(mutations, list):
            raise WalError("WAL manifest mutations must be an array")
        manifest_by_path = {}
        for mutation in mutations:
            if not isinstance(mutation, dict):
                raise WalError("invalid WAL manifest mutation")
            try:
                mutation_path = normalize_relative_path(mutation.get("path"))
            except (TypeError, ValueError) as exc:
                raise WalError("invalid WAL manifest path") from exc
            manifest_by_path[mutation_path] = mutation
        entries = record.get("entries")
        if not isinstance(entries, list) or not entries:
            raise WalError("WAL record has no entries")
        paths = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise WalError("invalid WAL entry")
            try:
                entry_path = normalize_relative_path(entry["path"])
            except (TypeError, ValueError) as exc:
                raise WalError("invalid WAL entry path") from exc
            before = _decoded(entry.get("before_b64"))
            after = _decoded(entry.get("after_b64"))
            before_hash = None if before is None else sha256_bytes(before)
            after_hash = None if after is None else sha256_bytes(after)
            if before_hash != entry.get("before_sha256"):
                raise WalError("WAL before-image digest mismatch")
            if after_hash != entry.get("after_sha256"):
                raise WalError("WAL after-image digest mismatch")
            manifest_mutation = manifest_by_path.get(entry_path)
            if manifest_mutation is None:
                raise WalError("WAL entry is absent from manifest")
            if manifest_mutation.get("before_sha256") != before_hash:
                raise WalError("WAL before-image disagrees with manifest")
            if manifest_mutation.get("after_sha256") != after_hash:
                raise WalError("WAL after-image disagrees with manifest")
            paths.append(entry_path)
        if len(paths) != len(set(paths)):
            raise WalError("WAL contains duplicate paths")
        if set(paths) != set(manifest_by_path):
            raise WalError("WAL entries do not cover the full manifest")
        receipt = record.get("receipt")
        if receipt is not None:
            if not isinstance(receipt, dict):
                raise WalError("WAL receipt must be an object or null")
            expected_receipt_fields = {
                "schema": "sword.idempotency-receipt",
                "version": 1,
                "request_id": manifest.get("request_id"),
                "request_digest": manifest.get("command_digest"),
                "transaction_id": manifest.get("transaction_id"),
                "campaign_id": manifest.get("campaign_id"),
                "committed_revision": manifest.get("target_revision"),
            }
            for field, expected in expected_receipt_fields.items():
                if receipt.get(field) != expected:
                    raise WalError("WAL receipt disagrees with manifest: %s" % field)

    @staticmethod
    def _validate_durability(value: Any) -> None:
        if not isinstance(value, dict):
            raise WalError("WAL durability must be an object")
        kind = value.get("kind")
        if kind == "local":
            if set(value) != {"kind"}:
                raise WalError("local WAL durability has unknown fields")
            return
        if kind != "git_remote" or set(value) != {"kind", "remote", "branch"}:
            raise WalError("unsupported WAL durability contract")
        for field, maximum in (("remote", 64), ("branch", 128)):
            item = value.get(field)
            if (
                not isinstance(item, str)
                or not item
                or len(item) > maximum
                or any(character in item for character in ("\x00", "\r", "\n"))
            ):
                raise WalError("invalid WAL Git durability %s" % field)

    def durability(self, record_or_transaction_id: object) -> Mapping[str, str]:
        """Return the persisted durability contract; old WALs mean local-only."""

        if isinstance(record_or_transaction_id, str):
            record = self.load(record_or_transaction_id)
        elif isinstance(record_or_transaction_id, Mapping):
            record = record_or_transaction_id
            transaction_id = record.get("transaction_id")
            if not isinstance(transaction_id, str):
                raise WalError("WAL record has no transaction identity")
            self._validate_record(record, transaction_id)
        else:
            raise TypeError("WAL durability source must be a transaction ID or record")
        value = record.get("durability", {"kind": "local"})
        return dict(value)

    def _write_status(self, record: Mapping[str, Any], status: str) -> Mapping[str, Any]:
        current = record.get("status")
        if status == current:
            return record
        if status not in self.TRANSITIONS.get(current, frozenset()):
            raise WalError("invalid WAL transition: %s -> %s" % (current, status))
        updated = dict(record)
        updated["status"] = status
        path = self._pending_path(record["transaction_id"])
        if not path.exists():
            raise WalError("only pending WALs may transition state")
        atomic_replace_bytes(path, canonical_json_bytes(updated), default_mode=0o600)
        return updated

    def archive_terminal(self, transaction_id: str) -> Mapping[str, Any]:
        """Atomically remove one terminal WAL from the recovery working set."""

        pending = self._pending_path(transaction_id)
        terminal = self._terminal_path(transaction_id)
        if not pending.exists():
            if terminal.exists():
                return self._read_path(terminal)
            raise WalError("WAL transaction does not exist: %s" % transaction_id)
        record = self._read_path(pending)
        if record["status"] not in ("committed", "rolled_back"):
            raise WalError("only terminal WAL states may be archived")
        os.replace(str(pending), str(terminal))
        self._fsync_directory(self.pending_directory)
        self._fsync_directory(self.terminal_directory)
        return record

    def manifest(self, record_or_transaction_id: object) -> TransactionManifest:
        """Reconstruct the typed manifest, including after-images, from a WAL."""

        if isinstance(record_or_transaction_id, str):
            record = self.load(record_or_transaction_id)
        elif isinstance(record_or_transaction_id, Mapping):
            record = record_or_transaction_id
            transaction_id = record.get("transaction_id")
            if not isinstance(transaction_id, str):
                raise WalError("WAL record has no transaction identity")
            self._validate_record(record, transaction_id)
        else:
            raise TypeError("WAL manifest source must be a transaction ID or record")
        summary = record["manifest"]
        entries = {entry["path"]: entry for entry in record["entries"]}
        mutations = tuple(
            FileMutation(
                mutation["path"],
                mutation["before_sha256"],
                _decoded(entries[mutation["path"]]["after_b64"]),
            )
            for mutation in summary["mutations"]
        )
        return TransactionManifest(
            transaction_id=summary["transaction_id"],
            campaign_id=summary["campaign_id"],
            request_id=summary["request_id"],
            command_digest=summary["command_digest"],
            mode=summary["mode"],
            base_revision=summary["base_revision"],
            target_revision=summary["target_revision"],
            created_at=summary["created_at"],
            mutations=mutations,
        )

    def classify(self, transaction_id: str, repository: RepositoryStore) -> str:
        record = self.load(transaction_id)
        matches: List[str] = []
        for entry in record["entries"]:
            current = repository.digest(entry["path"])
            if current == entry["before_sha256"]:
                matches.append("before")
            elif current == entry["after_sha256"]:
                matches.append("after")
            else:
                return "diverged"
        if all(match == "before" for match in matches):
            return "not_applied"
        if all(match == "after" for match in matches):
            return "applied"
        return "partial"

    def mark_applied(
        self, transaction_id: str, repository: RepositoryStore
    ) -> Mapping[str, Any]:
        record = self.load(transaction_id)
        if self.classify(transaction_id, repository) != "applied":
            raise WalError("cannot mark WAL applied until every after-image is present")
        return self._write_status(record, "applied")

    def mark_committed(
        self, transaction_id: str, repository: RepositoryStore
    ) -> Mapping[str, Any]:
        record = self.load(transaction_id)
        if self.classify(transaction_id, repository) != "applied":
            raise WalError("cannot mark WAL committed until every after-image is present")
        return self._write_status(record, "committed")

    def _images(
        self, record: Mapping[str, Any], side: str
    ) -> Iterable[Tuple[str, Optional[bytes]]]:
        key = "%s_b64" % side
        entries = list(record["entries"])
        # Meta is restored last on finish and first on rollback.  Rollback first
        # removing the advertised revision prevents readers seeing a new revision
        # while old owners are restored.
        if side == "after":
            entries.sort(key=lambda item: (item["path"] == "state/meta.json", item["path"]))
        else:
            entries.sort(key=lambda item: (item["path"] != "state/meta.json", item["path"]))
        for entry in entries:
            yield entry["path"], _decoded(entry[key])

    def finish(
        self, transaction_id: str, repository: RepositoryStore
    ) -> Mapping[str, Any]:
        record = self.load(transaction_id)
        if record["status"] in ("committed", "rolled_back"):
            raise WalError("terminal WAL cannot be finished")
        classification = self.classify(transaction_id, repository)
        if classification == "diverged":
            raise WalDivergenceError("cannot finish divergent WAL images")
        persister = AtomicManifestPersister(repository)
        persister.restore_images(self._images(record, "after"))
        if self.classify(transaction_id, repository) != "applied":
            raise WalError("WAL finish did not reproduce all after-images")
        return self._write_status(record, "applied")

    def rollback(
        self, transaction_id: str, repository: RepositoryStore
    ) -> Mapping[str, Any]:
        record = self.load(transaction_id)
        if record["status"] in ("committed", "rolled_back"):
            raise WalError("terminal WAL cannot be rolled back")
        classification = self.classify(transaction_id, repository)
        if classification == "diverged":
            raise WalDivergenceError("cannot overwrite divergent files during WAL rollback")
        persister = AtomicManifestPersister(repository)
        persister.restore_images(self._images(record, "before"))
        if self.classify(transaction_id, repository) != "not_applied":
            raise WalError("WAL rollback did not reproduce all before-images")
        updated = self._write_status(record, "rolled_back")
        self.archive_terminal(transaction_id)
        return updated

    def recoverable_records(self) -> Tuple[Mapping[str, Any], ...]:
        """Return only WALs that can still require coordinator recovery.

        This is the hot-path operation. It never enumerates ``terminal/`` and
        therefore remains bounded by the number of interrupted transactions,
        normally zero or one, rather than total campaign history.
        """

        records = []
        for path in sorted(self.pending_directory.glob("*.json")):
            records.append(self._read_path(path))
        records.sort(
            key=lambda item: (
                item.get("manifest", {}).get("created_at", ""),
                item["transaction_id"],
            )
        )
        return tuple(records)

    def records(
        self, statuses: Optional[Iterable[str]] = None
    ) -> Tuple[Mapping[str, Any], ...]:
        """Enumerate full WAL history for explicit audit/debug operations only."""

        selected = None if statuses is None else frozenset(statuses)
        by_transaction: Dict[str, Mapping[str, Any]] = {}
        # Terminal first, then pending so an in-flight retry of a previously
        # rolled-back deterministic transaction ID is the visible current WAL.
        for directory in (self.terminal_directory, self.pending_directory):
            for path in sorted(directory.glob("*.json")):
                record = self._read_path(path)
                by_transaction[record["transaction_id"]] = record
        records = []
        for record in by_transaction.values():
            if selected is None or record["status"] in selected:
                records.append(record)
        records.sort(
            key=lambda item: (
                item.get("manifest", {}).get("created_at", ""),
                item["transaction_id"],
            )
        )
        return tuple(records)

    def pending(self) -> Tuple[str, ...]:
        return tuple(
            record["transaction_id"]
            for record in self.recoverable_records()
            if record["status"] in ("prepared", "applied", "committed")
        )
