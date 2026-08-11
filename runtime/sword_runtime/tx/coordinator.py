"""Lock-scoped transaction service joining filesystem, WAL, Git, and receipts."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Tuple

from sword_runtime.commands import CommandEnvelope
from sword_runtime.store.overlay import StagedOverlay
from sword_runtime.store.repository import RepositoryStore
from sword_runtime.tx.errors import (
    IdempotencyConflictError,
    ReadbackVerificationError,
    RecoveryError,
    WalError,
)
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.locking import SingleWriterLock
from sword_runtime.tx.manifest import TransactionManifest, TransactionPlanner
from sword_runtime.tx.persistence import AtomicManifestPersister
from sword_runtime.tx.receipts import IdempotencyReceipt, ReceiptStore
from sword_runtime.tx.remote import GitRemoteDurability
from sword_runtime.tx.wal import WriteAheadLog


OverlayValidator = Callable[[StagedOverlay, TransactionManifest], None]
CrashInjector = Callable[[str, Optional[TransactionManifest]], None]


@dataclass(frozen=True)
class TransactionExecution:
    status: str
    receipt: IdempotencyReceipt
    commit_hash: Optional[str]
    manifest_digest: Optional[str]
    readback_hashes: Mapping[str, Optional[str]]

    def __post_init__(self) -> None:
        if self.status not in ("committed", "duplicate"):
            raise ValueError("invalid transaction execution status")
        object.__setattr__(
            self,
            "readback_hashes",
            MappingProxyType(dict(self.readback_hashes)),
        )


@dataclass(frozen=True)
class RecoveryDecision:
    transaction_id: str
    action: str
    commit_hash: Optional[str] = None


class TransactionCoordinator:
    """Execute one gameplay or maintenance transaction under a writer lock.

    The coordinator intentionally accepts final raw owner bytes.  It never
    canonicalizes campaign owners, so an existing JSON owner containing floats
    or deliberate formatting can be changed without first rewriting unrelated
    bytes.  Canonical JSON is limited to runtime-owned WAL and receipt metadata.
    """

    PHASES = (
        "after_lock",
        "after_recovery",
        "after_remote_preflight",
        "after_idempotency",
        "after_plan",
        "after_wal_prepare",
        "after_validation",
        "after_apply",
        "after_wal_applied",
        "after_git_stage",
        "after_git_commit",
        "after_readback",
        "after_remote_push",
        "after_wal_commit",
        "after_receipt",
    )

    def __init__(
        self,
        repository: RepositoryStore,
        git: GitStager,
        wal: WriteAheadLog,
        receipts: ReceiptStore,
        lock_path: object,
        lock_timeout: float = 0.0,
        meta_path: str = "state/meta.json",
        remote_durability: Optional[GitRemoteDurability] = None,
    ) -> None:
        if repository.root != git.repository_root:
            raise ValueError("filesystem and Git adapters must share one repository root")
        self.repository = repository
        self.git = git
        self.wal = wal
        self.receipts = receipts
        self.lock_path = lock_path
        self.lock_timeout = lock_timeout
        self.meta_path = meta_path
        if remote_durability is not None and remote_durability.git is not git:
            raise ValueError(
                "remote durability and coordinator must share one Git adapter"
            )
        self.remote_durability = remote_durability
        self.planner = TransactionPlanner(repository, meta_path=meta_path)
        self.persister = AtomicManifestPersister(
            repository,
            final_paths=(meta_path,),
        )

    @staticmethod
    def _inject(
        injector: Optional[CrashInjector],
        phase: str,
        manifest: Optional[TransactionManifest],
    ) -> None:
        if injector is not None:
            injector(phase, manifest)

    @staticmethod
    def _receipt_from_wal(record: Mapping[str, Any]) -> IdempotencyReceipt:
        receipt_record = record.get("receipt")
        if not isinstance(receipt_record, Mapping):
            raise RecoveryError(
                "coordinator WAL lacks the receipt draft required for recovery"
            )
        try:
            return IdempotencyReceipt.from_record(receipt_record)
        except (TypeError, ValueError) as exc:
            raise RecoveryError("coordinator WAL receipt draft is invalid") from exc

    def _verify_readback(
        self, manifest: TransactionManifest
    ) -> Mapping[str, Optional[str]]:
        hashes = {}
        for mutation in manifest.mutations:
            actual = self.repository.digest(mutation.path)
            if actual != mutation.after_sha256:
                raise ReadbackVerificationError(
                    "readback mismatch for %s: expected %s, found %s"
                    % (mutation.path, mutation.after_sha256, actual)
                )
            hashes[mutation.path] = actual
        if self.repository.campaign_id(self.meta_path) != manifest.campaign_id:
            raise ReadbackVerificationError("campaign identity changed during transaction")
        actual_revision = self.repository.current_revision(self.meta_path)
        if actual_revision != manifest.target_revision:
            raise ReadbackVerificationError(
                "world revision readback mismatch: expected %d, found %d"
                % (manifest.target_revision, actual_revision)
            )
        return hashes

    def _assert_recovery_paths_are_bounded(
        self, manifest: TransactionManifest
    ) -> None:
        expected = set(manifest.paths)
        staged = set(self.git.staged_paths())
        unstaged = set(self.git.unstaged_paths())
        untracked = set(self.git.untracked_paths())

        # A process can die after fsyncing AtomicManifestPersister's internal
        # same-directory temp but before os.replace. Such a temp is runtime
        # machinery, not an unrelated campaign mutation. It is safe to remove
        # only when its implied target is in this exact WAL manifest and its
        # bytes equal one of that mutation's bounded before/after images.
        by_path = {mutation.path: mutation for mutation in manifest.mutations}
        removable = set()
        for rel in sorted(untracked):
            path = self.repository.resolve(rel)
            name = path.name
            if not (name.startswith(".") and name.endswith(".tmp")):
                continue
            middle = name[1:-4]
            if "." not in middle:
                continue
            target_name = middle.rsplit(".", 1)[0]
            target_rel = str(path.with_name(target_name).relative_to(self.repository.root))
            mutation = by_path.get(target_rel)
            if mutation is None:
                continue
            digest = self.repository.digest(rel)
            if digest not in {mutation.before_sha256, mutation.after_sha256}:
                continue
            path.unlink()
            removable.add(rel)

        untracked -= removable
        unexpected = (staged | unstaged | untracked) - expected
        if unexpected:
            raise RecoveryError(
                "refusing recovery with dirty paths outside the WAL manifest: %s"
                % sorted(unexpected)
            )

    def _remote_for_wal(
        self, record: Mapping[str, Any]
    ) -> Optional[GitRemoteDurability]:
        durability = self.wal.durability(record)
        if durability.get("kind") == "git_remote":
            if self.remote_durability is None:
                raise RecoveryError(
                    "WAL requires Git remote durability but it is not configured"
                )
            if dict(self.remote_durability.to_record()) != dict(durability):
                raise RecoveryError(
                    "configured Git remote differs from the recoverable WAL"
                )
            return self.remote_durability
        # Enabling required durability after a legacy/local WAL was written is
        # a safe strengthening: any discovered local commit must be delivered
        # before its receipt can be finalized.
        return self.remote_durability

    def _recover_locked(self) -> Tuple[RecoveryDecision, ...]:
        decisions = []
        records = self.wal.recoverable_records()
        for record in records:
            if record["status"] == "rolled_back":
                self.wal.archive_terminal(record["transaction_id"])
                continue
            required_remote = self._remote_for_wal(record)
            manifest = self.wal.manifest(record)
            draft = self._receipt_from_wal(record)
            existing = self.receipts.get(draft.request_id)
            if existing is not None and existing != draft:
                raise IdempotencyConflictError(
                    "stored receipt disagrees with recoverable WAL"
                )
            if record["status"] == "committed" and existing == draft:
                self.wal.archive_terminal(manifest.transaction_id)
                continue

            commit = self.git.find_transaction_commit(manifest.transaction_id)
            classification = self.wal.classify(
                manifest.transaction_id, self.repository
            )
            if commit is not None:
                self.git.verify_manifest_commit(manifest, commit)
                if classification != "applied":
                    raise RecoveryError(
                        "Git records transaction %s but campaign files are %s"
                        % (manifest.transaction_id, classification)
                    )
                self.git.assert_pristine()
                self._verify_readback(manifest)
                # A local Git commit is irrevocable transaction evidence.  If
                # remote durability is required, recovery retries/recognizes
                # its exact non-force push before publishing a receipt.  A
                # failed retry leaves the local commit and applied WAL intact.
                if required_remote is not None:
                    required_remote.ensure_commit_durable(commit.commit_hash)
                if record["status"] == "prepared":
                    record = self.wal.mark_applied(
                        manifest.transaction_id, self.repository
                    )
                if record["status"] == "applied":
                    record = self.wal.mark_committed(
                        manifest.transaction_id, self.repository
                    )
                self.receipts.put(draft)
                self.wal.archive_terminal(manifest.transaction_id)
                decisions.append(
                    RecoveryDecision(
                        manifest.transaction_id,
                        "finalized_commit",
                        commit.commit_hash,
                    )
                )
                continue

            if record["status"] == "committed" or existing is not None:
                raise RecoveryError(
                    "receipt/WAL claims a commit that Git cannot locate for %s"
                    % manifest.transaction_id
                )
            if classification == "diverged":
                raise RecoveryError(
                    "uncommitted WAL %s has divergent campaign files"
                    % manifest.transaction_id
                )
            # Recovery is about to alter the index and/or restore before
            # images.  Re-fetch the required branch first and allow rollback
            # only while the local Git HEAD is still its exact remote HEAD.
            if required_remote is not None:
                required_remote.verify_synchronized()
            self._assert_recovery_paths_are_bounded(manifest)
            staged = tuple(
                path for path in self.git.staged_paths() if path in manifest.paths
            )
            if staged:
                self.git.unstage(staged)
            self.wal.rollback(manifest.transaction_id, self.repository)
            self.git.assert_pristine()
            decisions.append(
                RecoveryDecision(manifest.transaction_id, "rolled_back")
            )
        return tuple(decisions)

    def recover(self) -> Tuple[RecoveryDecision, ...]:
        """Finish committed WALs and roll back all safe uncommitted WALs."""

        with SingleWriterLock(self.lock_path, timeout=self.lock_timeout):
            decisions = self._recover_locked()
            self.git.assert_pristine()
            if self.remote_durability is not None:
                self.remote_durability.verify_synchronized()
            return decisions

    def lookup_receipt(
        self, command: CommandEnvelope
    ) -> Optional[IdempotencyReceipt]:
        """Recover first, then resolve an exact retry before base validation.

        A successful request necessarily advances the gameplay revision.  Its
        byte-identical network retry therefore carries an intentionally stale
        expected revision and must be recognized from the durable receipt
        before a planner rejects that base.
        """

        with SingleWriterLock(self.lock_path, timeout=self.lock_timeout):
            self._recover_locked()
            self.git.assert_pristine()
            if self.remote_durability is not None:
                self.remote_durability.verify_synchronized()
            return self.receipts.lookup(command)

    def _abort_uncommitted(self, manifest: TransactionManifest) -> None:
        """Best-effort synchronous rollback after an ordinary exception.

        A real process crash is represented by a ``BaseException`` subclass and
        bypasses this handler; the next process then uses ``recover``.  Once a
        matching Git trailer exists, rollback is forbidden and recovery must
        finish the committed transaction.
        """

        try:
            record = self.wal.load(manifest.transaction_id)
        except WalError as exc:
            raise RecoveryError(
                "prepared transaction WAL cannot be inspected for rollback"
            ) from exc
        if record["status"] == "rolled_back":
            return
        commit = self.git.find_transaction_commit(manifest.transaction_id)
        if commit is not None:
            return
        if record["status"] == "committed":
            raise RecoveryError("committed WAL has no matching Git transaction")
        self._assert_recovery_paths_are_bounded(manifest)
        staged = tuple(path for path in self.git.staged_paths() if path in manifest.paths)
        if staged:
            self.git.unstage(staged)
        classification = self.wal.classify(manifest.transaction_id, self.repository)
        if classification == "diverged":
            raise RecoveryError("cannot synchronously roll back divergent files")
        self.wal.rollback(manifest.transaction_id, self.repository)
        self.git.assert_pristine()

    def execute(
        self,
        command: CommandEnvelope,
        transaction_id: str,
        created_at: str,
        writes: Mapping[str, Optional[bytes]],
        result: Mapping[str, Any],
        validator: OverlayValidator,
        crash_injector: Optional[CrashInjector] = None,
    ) -> TransactionExecution:
        """Validate, persist, commit, and receipt one explicit transaction."""

        if not callable(validator):
            raise TypeError("a staged-overlay validator callback is required")
        manifest: Optional[TransactionManifest] = None
        wal_prepared = False
        with SingleWriterLock(self.lock_path, timeout=self.lock_timeout):
            self._inject(crash_injector, "after_lock", None)
            self._recover_locked()
            self._inject(crash_injector, "after_recovery", None)
            self.git.assert_pristine()
            if self.remote_durability is not None:
                self.remote_durability.verify_synchronized()
            self._inject(crash_injector, "after_remote_preflight", None)

            existing = self.receipts.lookup(command)
            self._inject(crash_injector, "after_idempotency", None)
            if existing is not None:
                return TransactionExecution(
                    status="duplicate",
                    receipt=existing,
                    commit_hash=None,
                    manifest_digest=None,
                    readback_hashes={},
                )

            try:
                manifest = self.planner.plan(
                    command,
                    transaction_id=transaction_id,
                    created_at=created_at,
                    writes=writes,
                )
                self._inject(crash_injector, "after_plan", manifest)
                receipt = IdempotencyReceipt.for_command(
                    command,
                    transaction_id=transaction_id,
                    committed_revision=manifest.target_revision,
                    committed_at=created_at,
                    result=result,
                )
                prepared_record = self.wal.prepare(
                    manifest,
                    self.repository,
                    receipt_record=receipt.to_record(),
                    durability_record=(
                        None
                        if self.remote_durability is None
                        else self.remote_durability.to_record()
                    ),
                )
                if prepared_record.get("status") != "prepared":
                    raise WalError(
                        "transaction ID belongs to a terminal or already-applied WAL; "
                        "retry with a new transaction ID"
                    )
                wal_prepared = True
                self._inject(crash_injector, "after_wal_prepare", manifest)

                overlay = StagedOverlay(self.repository, manifest)
                validator(overlay, manifest)
                self._inject(crash_injector, "after_validation", manifest)
                # A validator is read-only.  Requiring a pristine Git tree here
                # catches accidental validator writes before campaign mutation.
                self.git.assert_pristine()
                self.repository.require_campaign(command.campaign_id, self.meta_path)
                self.repository.require_revision(
                    command.expected_revision, self.meta_path
                )

                self.persister.apply(manifest)
                self._inject(crash_injector, "after_apply", manifest)
                self.wal.mark_applied(manifest.transaction_id, self.repository)
                self._inject(crash_injector, "after_wal_applied", manifest)

                self.git.assert_manifest_worktree(manifest.paths)
                self.git.stage(manifest.paths)
                self.git.assert_staged_exact(manifest.paths)
                self._inject(crash_injector, "after_git_stage", manifest)

                commit = self.git.commit(manifest)
                self._inject(crash_injector, "after_git_commit", manifest)
                readback = self._verify_readback(manifest)
                self.git.assert_pristine()
                self._inject(crash_injector, "after_readback", manifest)

                if self.remote_durability is not None:
                    self.remote_durability.ensure_commit_durable(
                        commit.commit_hash
                    )
                self._inject(crash_injector, "after_remote_push", manifest)

                self.wal.mark_committed(manifest.transaction_id, self.repository)
                self._inject(crash_injector, "after_wal_commit", manifest)
                stored_receipt = self.receipts.put(receipt)
                self._inject(crash_injector, "after_receipt", manifest)
                self.wal.archive_terminal(manifest.transaction_id)
                return TransactionExecution(
                    status="committed",
                    receipt=stored_receipt,
                    commit_hash=commit.commit_hash,
                    manifest_digest=manifest.digest,
                    readback_hashes=readback,
                )
            except Exception as exc:
                if manifest is not None and wal_prepared:
                    try:
                        self._abort_uncommitted(manifest)
                    except Exception as recovery_exc:
                        raise recovery_exc from exc
                raise
