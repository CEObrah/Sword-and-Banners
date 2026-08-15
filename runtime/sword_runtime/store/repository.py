"""Read-only checks and explicit atomic image replacement for campaign files."""

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Optional

from sword_runtime.store.paths import normalize_relative_path
from sword_runtime.tx.canonical import sha256_bytes
from sword_runtime.tx.errors import StaleRevisionError


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_replace_bytes(path: Path, content: bytes, default_mode: int = 0o644) -> None:
    """Replace one file atomically and durably within its parent directory."""

    if not isinstance(content, bytes):
        raise TypeError("atomic content must be bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = default_mode
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        pass

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s." % path.name,
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
        _fsync_directory(path.parent)
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


class RepositoryStore:
    """Confines all owner reads and writes to one concrete repository root."""

    def __init__(self, root: object) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("repository root does not exist: %s" % self.root)

    def resolve(self, relative_path: object) -> Path:
        normalized = normalize_relative_path(relative_path)
        candidate = (self.root / normalized).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("repository path escapes the root") from exc
        return candidate

    def read_optional_bytes(self, relative_path: object) -> Optional[bytes]:
        path = self.resolve(relative_path)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def read_bytes(self, relative_path: object) -> bytes:
        content = self.read_optional_bytes(relative_path)
        if content is None:
            raise FileNotFoundError(str(self.resolve(relative_path)))
        return content

    def read_json(self, relative_path: object) -> Any:
        raw = self.read_bytes(relative_path)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON owner: %s" % relative_path) from exc

    def digest(self, relative_path: object) -> Optional[str]:
        content = self.read_optional_bytes(relative_path)
        return None if content is None else sha256_bytes(content)

    def current_revision(self, meta_path: str = "state/meta.json") -> int:
        meta = self.read_json(meta_path)
        if not isinstance(meta, dict):
            raise ValueError("campaign meta must be an object")
        revision = meta.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise ValueError("campaign meta revision must be an integer")
        if revision < 0:
            raise ValueError("campaign meta revision must be non-negative")
        return revision

    def campaign_id(self, meta_path: str = "state/meta.json") -> str:
        meta = self.read_json(meta_path)
        if not isinstance(meta, dict):
            raise ValueError("campaign meta must be an object")
        campaign_id = meta.get("campaign_id")
        if not isinstance(campaign_id, str) or not campaign_id:
            raise ValueError("campaign meta campaign_id must be a non-empty string")
        return campaign_id

    def require_campaign(
        self, expected_campaign_id: str, meta_path: str = "state/meta.json"
    ) -> str:
        if not isinstance(expected_campaign_id, str) or not expected_campaign_id:
            raise ValueError("expected campaign ID must be a non-empty string")
        actual = self.campaign_id(meta_path)
        if actual != expected_campaign_id:
            raise ValueError(
                "command campaign mismatch: expected %s, found %s"
                % (expected_campaign_id, actual)
            )
        return actual

    def require_revision(
        self, expected_revision: int, meta_path: str = "state/meta.json"
    ) -> int:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise TypeError("expected revision must be an integer")
        actual = self.current_revision(meta_path)
        if actual != expected_revision:
            raise StaleRevisionError(expected_revision, actual)
        return actual

    def replace_image(self, relative_path: object, content: Optional[bytes]) -> None:
        """Atomically write or remove one explicitly named repository file."""

        path = self.resolve(relative_path)
        if content is None:
            try:
                path.unlink()
            except FileNotFoundError:
                return
            _fsync_directory(path.parent)
            return
        atomic_replace_bytes(path, content)
