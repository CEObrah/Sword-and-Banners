"""Transaction-domain exceptions with machine-readable attributes."""

from typing import Iterable, Optional, Tuple


class TransactionError(RuntimeError):
    """Base class for transaction failures."""


class StaleRevisionError(TransactionError):
    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__("stale campaign revision: expected %d, found %d" % (expected, actual))


class ConcurrentModificationError(TransactionError):
    def __init__(self, path: str, expected: Optional[str], actual: Optional[str]) -> None:
        self.path = path
        self.expected = expected
        self.actual = actual
        super().__init__(
            "owner changed before persistence: %s (expected %s, found %s)"
            % (path, expected, actual)
        )


class LockUnavailableError(TransactionError):
    def __init__(self, path: str, timeout: float) -> None:
        self.path = path
        self.timeout = timeout
        super().__init__("writer lock unavailable after %.3fs: %s" % (timeout, path))


class PartialApplyError(TransactionError):
    def __init__(self, paths: Iterable[str], cause: BaseException) -> None:
        self.paths: Tuple[str, ...] = tuple(paths)
        self.cause = cause
        super().__init__("manifest application stopped after: %s" % ", ".join(self.paths))


class WalError(TransactionError):
    """Malformed or invalid write-ahead-log operation."""


class WalDivergenceError(WalError):
    """Current files match neither the before nor after WAL images."""


class IdempotencyConflictError(TransactionError):
    """A request ID was reused for different canonical command bytes."""


class GitStageError(TransactionError):
    def __init__(self, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr
        super().__init__("git exact-path staging failed: %s" % stderr.strip())


class DirtyRepositoryError(TransactionError):
    def __init__(
        self,
        staged: Iterable[str],
        unstaged: Iterable[str],
        untracked: Iterable[str],
        message: str = "Git repository is not in the required state",
    ) -> None:
        self.staged = tuple(sorted(staged))
        self.unstaged = tuple(sorted(unstaged))
        self.untracked = tuple(sorted(untracked))
        detail = "staged=%s unstaged=%s untracked=%s" % (
            self.staged,
            self.unstaged,
            self.untracked,
        )
        super().__init__("%s: %s" % (message, detail))


class GitCommitError(TransactionError):
    def __init__(self, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self.stderr = stderr
        super().__init__("Git transaction commit failed: %s" % stderr.strip())


class CommitVerificationError(TransactionError):
    """The Git commit paths or transaction trailers do not match the WAL."""


class ReadbackVerificationError(TransactionError):
    """Persisted owner bytes do not match the transaction manifest."""


class RecoveryError(TransactionError):
    """Automatic recovery cannot choose a safe finish or rollback action."""


class RemoteDurabilityError(RecoveryError):
    """A required Git remote could not safely acknowledge campaign state.

    Remote command output is deliberately not retained on the exception.  Git
    transports can echo credential-bearing URLs, so callers receive a stable
    operation/code pair without potentially secret stderr.
    """

    def __init__(self, operation: str, code: str, returncode: Optional[int] = None) -> None:
        self.operation = operation
        self.code = code
        self.returncode = returncode
        super().__init__("required Git remote %s failed (%s)" % (operation, code))


class RemoteDivergenceError(RemoteDurabilityError):
    """Local and required remote branch heads do not have the expected shape."""


class RemotePushError(RemoteDurabilityError):
    """The exact transaction commit could not be durably pushed."""
