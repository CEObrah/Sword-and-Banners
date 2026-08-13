"""Opt-in, fail-closed Git remote durability for the transaction coordinator.

The remote adapter is intentionally narrower than a general Git client.  It
fetches one configured branch, requires exact local/remote equality before a
new transaction, and pushes one exact transaction commit without force.  It
never logs Git output because transport errors can contain credential-bearing
URLs.
"""

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from sword_runtime.tx.errors import (
    RemoteDivergenceError,
    RemoteDurabilityError,
    RemotePushError,
)
from sword_runtime.tx.git import GitStager


_REMOTE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_BRANCH_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _validated_remote_name(value: str) -> str:
    if not isinstance(value, str) or not _REMOTE_NAME.fullmatch(value):
        raise ValueError("Git remote name must be 1..64 safe ASCII characters")
    if value in (".", "..") or ".." in value:
        raise ValueError("Git remote name contains a forbidden component")
    return value


def _validated_branch_name(value: str) -> str:
    if not isinstance(value, str) or not _BRANCH_NAME.fullmatch(value):
        raise ValueError("Git branch must be a bounded safe ref name")
    if (
        value.endswith(("/", ".", ".lock"))
        or value.startswith(".")
        or "//" in value
        or ".." in value
        or "/." in value
        or "@{" in value
    ):
        raise ValueError("Git branch contains a forbidden ref component")
    return value


def _validated_object_id(value: str) -> str:
    if not isinstance(value, str) or not _OBJECT_ID.fullmatch(value):
        raise RemoteDurabilityError("verify", "invalid_object_id")
    return value


@dataclass(frozen=True)
class RemoteSnapshot:
    remote: str
    branch: str
    local_head: str
    remote_head: str


class GitRemoteDurability:
    """Require one exact remote branch to durably contain each transaction.

    Construction enables remote durability; omitting this adapter from the
    coordinator preserves local-only behavior.  All methods are expected to
    run while the campaign's single-writer lock is held.
    """

    def __init__(
        self,
        git: GitStager,
        remote: str,
        branch: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds, (int, float)
        ):
            raise TypeError("Git remote timeout must be numeric")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("Git remote timeout must be in (0, 300]")
        self.git = git
        self.remote = _validated_remote_name(remote)
        self.branch = _validated_branch_name(branch)
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_env(
        cls,
        git: GitStager,
        environ: Optional[Mapping[str, str]] = None,
    ) -> Optional["GitRemoteDurability"]:
        """Build required durability when both remote settings are present.

        With neither setting, local-only mode remains the default.  Supplying
        only one setting fails startup instead of silently dropping durability.
        """

        source = os.environ if environ is None else environ
        remote = source.get("SWORD_GIT_REMOTE")
        branch = source.get("SWORD_GIT_BRANCH")
        if remote is None and branch is None:
            if source.get("SWORD_GIT_URL") is not None:
                raise RuntimeError(
                    "SWORD_GIT_REMOTE and SWORD_GIT_BRANCH are required "
                    "when SWORD_GIT_URL configures a persistent checkout"
                )
            return None
        if not remote or not branch:
            raise RuntimeError(
                "SWORD_GIT_REMOTE and SWORD_GIT_BRANCH must be set together"
            )
        raw_timeout = source.get("SWORD_GIT_TIMEOUT_SECONDS", "30")
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("invalid SWORD_GIT_TIMEOUT_SECONDS") from exc
        try:
            return cls(git, remote, branch, timeout_seconds=timeout)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("invalid required Git remote configuration") from exc

    @property
    def tracking_ref(self) -> str:
        return "refs/remotes/%s/%s" % (self.remote, self.branch)

    @property
    def branch_ref(self) -> str:
        return "refs/heads/%s" % self.branch

    def to_record(self) -> Mapping[str, str]:
        """Return non-secret WAL metadata needed to resume required delivery."""

        return {
            "kind": "git_remote",
            "remote": self.remote,
            "branch": self.branch,
        }

    def _run(
        self,
        arguments: Tuple[str, ...],
        operation: str,
        push: bool = False,
    ) -> bytes:
        environment = dict(os.environ)
        environment["GIT_TERMINAL_PROMPT"] = "0"
        # The Railway bootstrap creates a 0700 askpass wrapper outside the
        # checkout and exports it to Uvicorn.  Preserve that environment for
        # every fetch/push.  If a token is present without the forced wrapper,
        # fail closed rather than fall back to an interactive prompt or place
        # the secret in a URL/argument.
        if environment.get("SWORD_GIT_TOKEN") is not None:
            askpass = environment.get("GIT_ASKPASS")
            if (
                not isinstance(askpass, str)
                or not askpass
                or not os.path.isabs(askpass)
                or not os.path.isfile(askpass)
                or not os.access(askpass, os.X_OK)
                or environment.get("GIT_ASKPASS_REQUIRE") != "force"
            ):
                error_type = RemotePushError if push else RemoteDurabilityError
                raise error_type(operation, "askpass_not_ready")
        try:
            completed = subprocess.run(
                [
                    self.git.git_binary,
                    "-C",
                    str(self.git.repository_root),
                ]
                + list(arguments),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=environment,
                timeout=self.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            error_type = RemotePushError if push else RemoteDurabilityError
            raise error_type(operation, "command_unavailable") from exc
        if completed.returncode:
            error_type = RemotePushError if push else RemoteDurabilityError
            # Do not retain or interpolate stdout/stderr.  Git transports may
            # include a URL containing deployment credentials in either stream.
            raise error_type(operation, "git_rejected", completed.returncode)
        return completed.stdout

    def _current_branch(self) -> str:
        output = self._run(
            ("symbolic-ref", "--quiet", "--short", "HEAD"),
            "inspect_local_branch",
        )
        try:
            branch = output.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise RemoteDurabilityError(
                "inspect_local_branch", "invalid_branch_output"
            ) from exc
        if branch != self.branch:
            raise RemoteDivergenceError(
                "preflight", "local_branch_mismatch"
            )
        return branch

    def _head_for_ref(self, ref: str, operation: str) -> str:
        output = self._run(
            ("rev-parse", "--verify", ref + "^{commit}"),
            operation,
        )
        try:
            value = output.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise RemoteDurabilityError(operation, "invalid_object_id") from exc
        return _validated_object_id(value)

    def _fetch(self) -> str:
        # The refspec is fully bounded and never begins with an option.  No
        # pruning, tags, wildcard, force marker, or arbitrary destination ref
        # is accepted.
        refspec = "%s:%s" % (self.branch_ref, self.tracking_ref)
        self._run(
            ("fetch", "--no-tags", self.remote, refspec),
            "fetch",
        )
        return self._head_for_ref(self.tracking_ref, "inspect_remote_head")

    def verify_synchronized(self) -> RemoteSnapshot:
        """Fetch and require the checked-out branch to equal remote exactly."""

        self._current_branch()
        local_head = _validated_object_id(self.git.head())
        remote_head = self._fetch()
        if local_head != remote_head:
            raise RemoteDivergenceError("preflight", "head_mismatch")
        return RemoteSnapshot(
            remote=self.remote,
            branch=self.branch,
            local_head=local_head,
            remote_head=remote_head,
        )

    def _single_parent(self, commit_hash: str) -> str:
        output = self._run(
            ("rev-list", "--parents", "-n", "1", commit_hash),
            "inspect_transaction_parent",
        )
        try:
            parts = output.decode("ascii", errors="strict").strip().split()
        except UnicodeDecodeError as exc:
            raise RemoteDurabilityError(
                "inspect_transaction_parent", "invalid_object_id"
            ) from exc
        if len(parts) != 2 or parts[0] != commit_hash:
            raise RemoteDivergenceError(
                "push", "transaction_commit_must_have_one_parent"
            )
        return _validated_object_id(parts[1])

    def ensure_commit_durable(self, commit_hash: str) -> RemoteSnapshot:
        """Push or verify one exact commit, without rolling it back on failure.

        Recovery calls this same method.  A remote already at ``commit_hash``
        means a prior push succeeded before the process died.  Otherwise the
        remote must still be at the transaction commit's sole parent; any other
        head is a divergence and is never overwritten.
        """

        commit_hash = _validated_object_id(commit_hash)
        self._current_branch()
        local_head = _validated_object_id(self.git.head())
        if local_head != commit_hash:
            raise RemoteDivergenceError("push", "transaction_not_local_head")
        parent = self._single_parent(commit_hash)
        remote_head = self._fetch()
        if remote_head == commit_hash:
            return RemoteSnapshot(
                remote=self.remote,
                branch=self.branch,
                local_head=local_head,
                remote_head=remote_head,
            )
        if remote_head != parent:
            raise RemoteDivergenceError("push", "unexpected_remote_head")

        refspec = "%s:%s" % (commit_hash, self.branch_ref)
        self._run(
            ("push", "--porcelain", "--no-force", self.remote, refspec),
            "push",
            push=True,
        )
        verified_head = self._fetch()
        if verified_head != commit_hash:
            raise RemotePushError("verify_push", "remote_ack_mismatch")
        return RemoteSnapshot(
            remote=self.remote,
            branch=self.branch,
            local_head=local_head,
            remote_head=verified_head,
        )
