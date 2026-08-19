"""Crash-consistent application of an explicit file manifest."""

from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from sword_runtime.store.paths import normalize_relative_path
from sword_runtime.store.repository import RepositoryStore
from sword_runtime.tx.errors import ConcurrentModificationError, PartialApplyError
from sword_runtime.tx.manifest import FileMutation, TransactionManifest


class AtomicManifestPersister:
    """Apply each file atomically, with WAL expected to cover process crashes.

    Filesystems do not provide a portable atomic rename spanning many files.  The
    persister therefore verifies the complete base set before the first write,
    atomically replaces each exact path, and relies on a prepared WAL to finish
    or roll back a crash-interrupted sequence.  A final owner such as
    ``state/meta.json`` is always written last.
    """

    def __init__(
        self,
        repository: RepositoryStore,
        final_paths: Sequence[str] = ("state/meta.json",),
    ) -> None:
        self.repository = repository
        self.final_paths = tuple(normalize_relative_path(path) for path in final_paths)

    def verify_before(self, manifest: TransactionManifest) -> None:
        for mutation in manifest.mutations:
            actual = self.repository.digest(mutation.path)
            if actual != mutation.before_sha256:
                raise ConcurrentModificationError(
                    mutation.path, mutation.before_sha256, actual
                )

    def _ordered(self, manifest: TransactionManifest) -> Tuple[FileMutation, ...]:
        by_path = {mutation.path: mutation for mutation in manifest.mutations}
        ordinary = [
            mutation
            for mutation in manifest.mutations
            if mutation.path not in self.final_paths
        ]
        finals = [by_path[path] for path in self.final_paths if path in by_path]
        return tuple(sorted(ordinary, key=lambda item: item.path) + finals)

    def apply(
        self,
        manifest: TransactionManifest,
        after_apply: Optional[Callable[[str, int], None]] = None,
    ) -> Tuple[str, ...]:
        """Apply exactly the manifest paths and return their applied order."""

        self.verify_before(manifest)
        applied: List[str] = []
        try:
            for index, mutation in enumerate(self._ordered(manifest), start=1):
                self.repository.replace_image(mutation.path, mutation.after_bytes)
                actual = self.repository.digest(mutation.path)
                if actual != mutation.after_sha256:
                    raise IOError("post-write digest mismatch for %s" % mutation.path)
                applied.append(mutation.path)
                if after_apply is not None:
                    after_apply(mutation.path, index)
        except BaseException as exc:
            raise PartialApplyError(applied, exc) from exc
        return tuple(applied)

    def restore_images(
        self, images: Iterable[Tuple[str, Optional[bytes]]]
    ) -> Tuple[str, ...]:
        """Atomically restore explicit images during WAL recovery."""

        restored = []
        for path, content in images:
            normalized = normalize_relative_path(path)
            self.repository.replace_image(normalized, content)
            restored.append(normalized)
        return tuple(restored)

