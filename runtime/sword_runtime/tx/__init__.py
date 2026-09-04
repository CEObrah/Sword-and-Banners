"""Crash-recoverable transaction primitives.

Exports are loaded lazily so the command envelope can use canonical hashing
without creating an import cycle through the manifest planner.
"""

from importlib import import_module

__all__ = [
    "AtomicManifestPersister",
    "FileMutation",
    "GitStager",
    "GitRemoteDurability",
    "IdempotencyReceipt",
    "ReceiptStore",
    "SingleWriterLock",
    "TransactionManifest",
    "TransactionCoordinator",
    "TransactionExecution",
    "RecoveryDecision",
    "RemoteSnapshot",
    "TransactionPlanner",
    "WriteAheadLog",
    "canonical_json_bytes",
    "canonical_sha256",
    "sha256_bytes",
]


_EXPORT_MODULES = {
    "AtomicManifestPersister": ".persistence",
    "FileMutation": ".manifest",
    "GitStager": ".git",
    "GitRemoteDurability": ".remote",
    "IdempotencyReceipt": ".receipts",
    "ReceiptStore": ".receipts",
    "RecoveryDecision": ".coordinator",
    "RemoteSnapshot": ".remote",
    "SingleWriterLock": ".locking",
    "TransactionManifest": ".manifest",
    "TransactionCoordinator": ".coordinator",
    "TransactionExecution": ".coordinator",
    "TransactionPlanner": ".manifest",
    "WriteAheadLog": ".wal",
    "canonical_json_bytes": ".canonical",
    "canonical_sha256": ".canonical",
    "sha256_bytes": ".canonical",
}


def __getattr__(name: str):
    try:
        module_name = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
