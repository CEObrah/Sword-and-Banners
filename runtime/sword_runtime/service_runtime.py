"""Production Sword runtime wiring for persistent hosted play.

Hosted service construction uses this subclass so a configured Git remote is
part of transaction durability: a gameplay receipt is not published until the
exact transaction commit is pushed and verified remotely.
"""
from __future__ import annotations
from sword_runtime.engine import SwordRuntime
from sword_runtime.tx.coordinator import TransactionCoordinator
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.receipts import ReceiptStore
from sword_runtime.tx.remote import GitRemoteDurability
from sword_runtime.tx.wal import WriteAheadLog

class ProductionSwordRuntime(SwordRuntime):
    """Sword runtime with fail-closed remote durability when Git is configured."""
    def __init__(self, root: object, runtime_root: object | None = None) -> None:
        super().__init__(root, runtime_root)
        git = GitStager(self.root)
        remote_durability = GitRemoteDurability.from_env(git)
        self.coordinator = TransactionCoordinator(
            self.store,
            git,
            WriteAheadLog(self.runtime_dir / "wal"),
            ReceiptStore(self.runtime_dir / "receipts"),
            self.runtime_dir / "campaign.lock",
            lock_timeout=10.0,
            remote_durability=remote_durability,
        )
        # Disable the legacy post-receipt best-effort path. Remote delivery is
        # now inside the transaction coordinator and recovery protocol.
        self.replicator = None

__all__ = ["ProductionSwordRuntime"]
