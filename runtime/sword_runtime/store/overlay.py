"""Read-only proposed-file overlay used by pre-persistence validators."""

import json
from typing import Any, Dict, Optional, Tuple

from sword_runtime.store.paths import normalize_relative_path
from sword_runtime.store.repository import RepositoryStore
from sword_runtime.tx.canonical import sha256_bytes
from sword_runtime.tx.manifest import TransactionManifest


class StagedOverlay:
    """Expose manifest after-images without touching the campaign worktree."""

    def __init__(
        self, repository: RepositoryStore, manifest: TransactionManifest
    ) -> None:
        self.repository = repository
        self.manifest = manifest
        self._images: Dict[str, Optional[bytes]] = {
            mutation.path: mutation.after_bytes for mutation in manifest.mutations
        }

    @property
    def changed_paths(self) -> Tuple[str, ...]:
        return tuple(sorted(self._images))

    def read_optional_bytes(self, relative_path: object) -> Optional[bytes]:
        path = normalize_relative_path(relative_path)
        if path in self._images:
            return self._images[path]
        return self.repository.read_optional_bytes(path)

    def read_bytes(self, relative_path: object) -> bytes:
        content = self.read_optional_bytes(relative_path)
        if content is None:
            raise FileNotFoundError(str(relative_path))
        return content

    def read_json(self, relative_path: object) -> Any:
        content = self.read_bytes(relative_path)
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid staged JSON: %s" % relative_path) from exc

    def digest(self, relative_path: object) -> Optional[str]:
        content = self.read_optional_bytes(relative_path)
        return None if content is None else sha256_bytes(content)
