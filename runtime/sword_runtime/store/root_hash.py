"""Deterministic content roots for campaign snapshots and readback."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from pathlib import PurePosixPath
import stat
import subprocess
from threading import Lock
from typing import Iterable, Iterator, Optional, Tuple

from sword_runtime.tx.canonical import canonical_sha256, sha256_bytes


@dataclass(frozen=True)
class RootEntry:
    path: str
    sha256: str
    size: int

    def to_record(self):
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class ContentRoot:
    algorithm: str
    root_sha256: str
    entries: Tuple[RootEntry, ...]

    def to_record(self):
        return {
            "algorithm": self.algorithm,
            "root_sha256": self.root_sha256,
            "file_count": len(self.entries),
            "entries": [entry.to_record() for entry in self.entries],
        }


class CommittedContentRootCache:
    """Cache one immutable content root per Git commit identity.

    Callers using ``tracked_only=True`` must prove the repository is pristine.
    A clean Git HEAD then identifies every byte included by the cache without
    allowing ignored files to affect a HEAD-keyed result.  The default remains
    the historical all-files behavior for non-Git callers.  A new commit key
    automatically invalidates the cached root.
    """

    def __init__(
        self,
        repository_root: object,
        *,
        include_roots: Iterable[str] = ("state",),
        tracked_only: bool = False,
    ) -> None:
        self.repository_root = Path(repository_root).resolve()
        self.include_roots = tuple(sorted(set(include_roots)))
        if not self.include_roots:
            raise ValueError("content-root cache requires at least one include root")
        self.tracked_only = tracked_only
        self._lock = Lock()
        self._commit_key: Optional[str] = None
        self._content_root: Optional[ContentRoot] = None

    def read(self, commit_key: str) -> ContentRoot:
        if not isinstance(commit_key, str) or not commit_key:
            raise ValueError("content-root cache key must be non-empty text")
        with self._lock:
            if self._commit_key != commit_key or self._content_root is None:
                self._content_root = content_root(
                    self.repository_root,
                    include_roots=self.include_roots,
                    tracked_only=self.tracked_only,
                )
                self._commit_key = commit_key
            return self._content_root


def content_root(
    repository_root: object,
    *,
    include_roots: Iterable[str] = ("state",),
    tracked_only: bool = False,
) -> ContentRoot:
    root = Path(repository_root).resolve()
    if not root.is_dir():
        raise ValueError("repository root does not exist")
    roots = _validated_include_roots(root, include_roots)
    paths = (
        _tracked_files(root, roots)
        if tracked_only
        else _tree_files(root, roots)
    )
    entries = []
    seen = set()
    for relative, path in paths:
        if relative in seen:
            continue
        seen.add(relative)
        raw = _read_regular_file(path, relative)
        entries.append(RootEntry(relative, sha256_bytes(raw), len(raw)))
    ordered = tuple(sorted(entries, key=lambda item: item.path))
    digest = canonical_sha256({
        "algorithm": "sha256-path-content-v1",
        "entries": [entry.to_record() for entry in ordered],
    })
    return ContentRoot("sha256-path-content-v1", digest, ordered)


def _validated_include_roots(
    repository_root: Path,
    include_roots: Iterable[str],
) -> Tuple[Tuple[str, Path], ...]:
    if isinstance(include_roots, (str, bytes)):
        raise ValueError("include roots must be an iterable of relative paths")
    validated = {}
    for value in include_roots:
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError("include roots must be non-empty relative paths")
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("include roots must be relative and may not escape repository")
        normalized = pure.as_posix()
        if normalized == "":
            raise ValueError("include roots must be non-empty relative paths")

        lexical = repository_root.joinpath(*pure.parts)
        _reject_symlink_components(repository_root, lexical, normalized)
        try:
            target = lexical.resolve(strict=True)
            target.relative_to(repository_root)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise ValueError(f"invalid include root: {value}") from exc
        if not target.is_dir():
            raise ValueError(f"include root is not a directory: {value}")
        relative = target.relative_to(repository_root).as_posix() or "."
        validated[relative] = target
    if not validated:
        raise ValueError("content root requires at least one include root")
    return tuple((relative, validated[relative]) for relative in sorted(validated))


def _reject_symlink_components(
    repository_root: Path,
    target: Path,
    display_path: str,
) -> None:
    try:
        relative = target.relative_to(repository_root)
    except ValueError as exc:
        raise ValueError("include root escapes repository") from exc
    cursor = repository_root
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise ValueError(
                f"content roots do not follow symlinks: {display_path}"
            )


def _tree_files(
    repository_root: Path,
    include_roots: Tuple[Tuple[str, Path], ...],
) -> Iterator[Tuple[str, Path]]:
    for _, target in include_roots:
        for path in sorted(target.rglob("*")):
            relative = path.relative_to(repository_root).as_posix()
            if path.is_symlink():
                raise ValueError(f"content roots do not follow symlinks: {relative}")
            if path.is_file():
                yield relative, path


def _tracked_files(
    repository_root: Path,
    include_roots: Tuple[Tuple[str, Path], ...],
) -> Iterator[Tuple[str, Path]]:
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(repository_root), "ls-files", "--cached", "-z"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ValueError("unable to enumerate Git-tracked files") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        if len(detail) > 512:
            detail = detail[:509] + "..."
        suffix = f": {detail}" if detail else ""
        raise ValueError(f"unable to enumerate Git-tracked files{suffix}")

    prefixes = tuple(
        () if relative == "." else PurePosixPath(relative).parts
        for relative, _ in include_roots
    )
    decoded = []
    for raw_relative in result.stdout.split(b"\0"):
        if not raw_relative:
            continue
        try:
            relative = raw_relative.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Git-tracked paths must be valid UTF-8") from exc
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or not pure.parts
            or any(part in {".", ".."} for part in pure.parts)
            or pure.as_posix() != relative
        ):
            raise ValueError(f"invalid Git-tracked path: {relative!r}")
        if any(pure.parts[:len(prefix)] == prefix for prefix in prefixes):
            decoded.append((relative, pure.parts))

    for relative, parts in sorted(decoded):
        path = repository_root.joinpath(*parts)
        _reject_symlink_components(repository_root, path, relative)
        yield relative, path


def _read_regular_file(path: Path, relative: str) -> bytes:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise ValueError(f"content-root file is unavailable: {relative}") from exc
    if stat.S_ISLNK(file_stat.st_mode):
        raise ValueError(f"content roots do not follow symlinks: {relative}")
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError(f"content-root path is not a regular file: {relative}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"content-root file is unreadable: {relative}") from exc
    try:
        after = path.lstat()
    except OSError as exc:
        raise ValueError(f"content-root file changed while hashing: {relative}") from exc
    identity_before = (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
    )
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(raw) != after.st_size:
        raise ValueError(f"content-root file changed while hashing: {relative}")
    return raw
