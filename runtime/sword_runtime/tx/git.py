"""Exact-path Git staging, commits, and transaction-trailer recovery lookup."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple

from sword_runtime.store.paths import normalize_relative_path
from sword_runtime.tx.errors import (
    CommitVerificationError,
    DirtyRepositoryError,
    GitCommitError,
    GitStageError,
)
from sword_runtime.tx.manifest import TransactionManifest


TRANSACTION_TRAILER = "Sword-Transaction"
CAMPAIGN_TRAILER = "Sword-Campaign"
REVISION_TRAILER = "Sword-World-Revision"
MODE_TRAILER = "Sword-Mode"
REQUEST_TRAILER = "Sword-Request"
COMMAND_DIGEST_TRAILER = "Sword-Command-Digest"
CAMPAIGN_AUTHORITY_ROOTS = ("state", "data", "schemas")


@dataclass(frozen=True)
class GitCommitRecord:
    commit_hash: str
    paths: Tuple[str, ...]
    trailers: Mapping[str, str]


class GitStager:
    """Git adapter that never stages a wildcard or unspecified path."""

    def __init__(
        self,
        repository_root: object,
        git_binary: str = "git",
        user_name: str = "Sword Runtime",
        user_email: str = "runtime@invalid",
    ) -> None:
        self.repository_root = Path(repository_root).resolve()
        if not self.repository_root.is_dir():
            raise ValueError("Git repository root does not exist")
        if (
            not isinstance(user_name, str)
            or not user_name
            or len(user_name) > 128
            or user_name != user_name.strip()
            or any(character in user_name for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("Git transaction user name must be bounded text")
        if (
            not isinstance(user_email, str)
            or not user_email
            or len(user_email) > 254
            or user_email != user_email.strip()
            or "@" not in user_email
            or any(
                character in user_email
                for character in ("\x00", "\r", "\n", " ", "\t")
            )
        ):
            raise ValueError("Git transaction user email must be bounded text")
        self.git_binary = git_binary
        self.user_name = user_name
        self.user_email = user_email

    def _run_bytes(
        self,
        arguments: Iterable[str],
        input_bytes: Optional[bytes] = None,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.git_binary, "-C", str(self.repository_root)] + list(arguments),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def _path_output(self, arguments: Iterable[str]) -> Tuple[str, ...]:
        completed = self._run_bytes(arguments)
        if completed.returncode:
            raise GitStageError(
                completed.returncode,
                completed.stderr.decode("utf-8", errors="replace"),
            )
        return tuple(
            sorted(
                path.decode("utf-8")
                for path in completed.stdout.split(b"\x00")
                if path
            )
        )

    def stage(self, paths: Iterable[str]) -> Tuple[str, ...]:
        normalized = tuple(sorted({normalize_relative_path(path) for path in paths}))
        if not normalized:
            raise ValueError("at least one exact path is required for Git staging")
        completed = subprocess.run(
            [
                self.git_binary,
                "--literal-pathspecs",
                "-C",
                str(self.repository_root),
                "add",
                "-A",
                "--",
            ]
            + list(normalized),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode:
            raise GitStageError(completed.returncode, completed.stderr)
        return normalized

    def staged_paths(self) -> Tuple[str, ...]:
        return self._path_output(
            ("diff", "--cached", "--no-renames", "--name-only", "-z")
        )

    def unstaged_paths(self) -> Tuple[str, ...]:
        return self._path_output(("diff", "--no-renames", "--name-only", "-z"))

    def untracked_paths(self) -> Tuple[str, ...]:
        untracked = self._path_output(
            ("ls-files", "--others", "--exclude-standard", "-z")
        )
        # Ignored files are normally outside Git cleanliness, but an ignored
        # JSON owner under an authority root could still be discovered by a
        # bounded runtime directory scan. Treat such files as untracked dirt;
        # caches and commits may then safely identify campaign bytes by HEAD.
        ignored_authority = tuple(
            path
            for path in self._path_output(
                (
                    "ls-files",
                    "--others",
                    "--ignored",
                    "--exclude-standard",
                    "-z",
                    "--",
                    *CAMPAIGN_AUTHORITY_ROOTS,
                )
            )
            # Finder metadata cannot match any runtime owner/module route and
            # is common in a local macOS checkout. It remains excluded from
            # committed content roots and must never be read as authority.
            if Path(path).name != ".DS_Store"
        )
        return tuple(sorted(set(untracked) | set(ignored_authority)))

    def assert_pristine(self) -> None:
        staged = self.staged_paths()
        unstaged = self.unstaged_paths()
        untracked = self.untracked_paths()
        if staged or unstaged or untracked:
            raise DirtyRepositoryError(staged, unstaged, untracked)

    def assert_manifest_worktree(self, paths: Iterable[str]) -> Tuple[str, ...]:
        expected = tuple(sorted({normalize_relative_path(path) for path in paths}))
        staged = self.staged_paths()
        unstaged = self.unstaged_paths()
        untracked = self.untracked_paths()
        actual = tuple(sorted(set(unstaged) | set(untracked)))
        if staged or actual != expected:
            raise DirtyRepositoryError(
                staged,
                unstaged,
                untracked,
                message="worktree does not match the explicit transaction manifest",
            )
        return expected

    def assert_staged_exact(self, paths: Iterable[str]) -> Tuple[str, ...]:
        expected = tuple(sorted({normalize_relative_path(path) for path in paths}))
        staged = self.staged_paths()
        unstaged = self.unstaged_paths()
        untracked = self.untracked_paths()
        if staged != expected or unstaged or untracked:
            raise DirtyRepositoryError(
                staged,
                unstaged,
                untracked,
                message="Git index does not contain exactly the transaction manifest",
            )
        return expected

    def unstage(self, paths: Iterable[str]) -> Tuple[str, ...]:
        normalized = tuple(sorted({normalize_relative_path(path) for path in paths}))
        if not normalized:
            return ()
        completed = subprocess.run(
            [
                self.git_binary,
                "--literal-pathspecs",
                "-C",
                str(self.repository_root),
                "reset",
                "--quiet",
                "HEAD",
                "--",
            ]
            + list(normalized),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode:
            raise GitStageError(completed.returncode, completed.stderr)
        return normalized

    @staticmethod
    def _expected_trailers(manifest: TransactionManifest) -> Mapping[str, str]:
        return {
            TRANSACTION_TRAILER: manifest.transaction_id,
            CAMPAIGN_TRAILER: manifest.campaign_id,
            REVISION_TRAILER: str(manifest.target_revision),
            MODE_TRAILER: manifest.mode,
            REQUEST_TRAILER: manifest.request_id,
            COMMAND_DIGEST_TRAILER: manifest.command_digest,
        }

    @classmethod
    def _commit_message(cls, manifest: TransactionManifest) -> str:
        lines = [
            "sword: %s transaction %s" % (manifest.mode, manifest.transaction_id),
            "",
        ]
        lines.extend(
            "%s: %s" % (key, value)
            for key, value in cls._expected_trailers(manifest).items()
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _parse_trailers(message: str) -> Mapping[str, str]:
        trailers: Dict[str, str] = {}
        for line in message.splitlines():
            if ": " not in line:
                continue
            key, value = line.split(": ", 1)
            if not key.startswith("Sword-"):
                continue
            if key in trailers:
                raise CommitVerificationError("duplicate transaction trailer: %s" % key)
            trailers[key] = value
        return trailers

    def head(self) -> str:
        completed = self._run_bytes(("rev-parse", "HEAD"))
        if completed.returncode:
            raise GitStageError(
                completed.returncode,
                completed.stderr.decode("utf-8", errors="replace"),
            )
        return completed.stdout.decode("ascii").strip()

    def commit(self, manifest: TransactionManifest) -> GitCommitRecord:
        self.assert_staged_exact(manifest.paths)
        completed = self._run_bytes(
            (
                "-c",
                "commit.gpgSign=false",
                "-c",
                "user.name=" + self.user_name,
                "-c",
                "user.email=" + self.user_email,
                "commit",
                "--cleanup=verbatim",
                "-F",
                "-",
            ),
            input_bytes=self._commit_message(manifest).encode("utf-8"),
        )
        if completed.returncode:
            raise GitCommitError(
                completed.returncode,
                completed.stderr.decode("utf-8", errors="replace"),
            )
        record = self.get_commit(self.head())
        self.verify_manifest_commit(manifest, record)
        return record

    def get_commit(self, commit_hash: str) -> GitCommitRecord:
        message_result = self._run_bytes(("show", "-s", "--format=%B", commit_hash))
        if message_result.returncode:
            raise GitStageError(
                message_result.returncode,
                message_result.stderr.decode("utf-8", errors="replace"),
            )
        paths = self._path_output(
            (
                "diff-tree",
                "--root",
                "--no-commit-id",
                "--no-renames",
                "--name-only",
                "-r",
                "-z",
                commit_hash,
            )
        )
        message = message_result.stdout.decode("utf-8", errors="strict")
        return GitCommitRecord(
            commit_hash=commit_hash,
            paths=paths,
            trailers=self._parse_trailers(message),
        )

    def find_transaction_commit(
        self, transaction_id: str, max_count: int = 512
    ) -> Optional[GitCommitRecord]:
        if max_count <= 0:
            raise ValueError("max_count must be positive")

        # A recoverable transaction commit is normally the current local HEAD:
        # the process crashed after committing but before publishing its WAL or
        # receipt.  Check that exact commit before walking other refs so normal
        # recovery does not issue a show + diff-tree pair for every commit that
        # `git log --all` happens to order ahead of it.
        head_hash = self.head()
        head_record = self.get_commit(head_hash)
        if head_record.trailers.get(TRANSACTION_TRAILER) == transaction_id:
            return head_record

        completed = self._run_bytes(
            ("log", "--all", "--format=%H", "--max-count=%d" % max_count)
        )
        if completed.returncode:
            raise GitStageError(
                completed.returncode,
                completed.stderr.decode("utf-8", errors="replace"),
            )
        for commit_hash in completed.stdout.decode("ascii").splitlines():
            if commit_hash == head_hash:
                continue
            record = self.get_commit(commit_hash)
            if record.trailers.get(TRANSACTION_TRAILER) == transaction_id:
                return record
        return None

    def verify_manifest_commit(
        self, manifest: TransactionManifest, record: GitCommitRecord
    ) -> None:
        expected_trailers = self._expected_trailers(manifest)
        for key, expected in expected_trailers.items():
            if record.trailers.get(key) != expected:
                raise CommitVerificationError(
                    "commit %s has invalid %s trailer" % (record.commit_hash, key)
                )
        if tuple(sorted(record.paths)) != tuple(sorted(manifest.paths)):
            raise CommitVerificationError(
                "commit paths do not match transaction manifest: %s" % (record.paths,)
            )
