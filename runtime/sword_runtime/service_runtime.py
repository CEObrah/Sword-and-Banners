"""Production Sword runtime wiring for persistent hosted play.

Hosted service construction uses this subclass so a configured Git remote is
part of transaction durability: a gameplay receipt is not published until the
exact transaction commit is pushed and verified remotely.
"""
from __future__ import annotations
from typing import Any
from sword_runtime.engine import SwordRuntime
from sword_runtime.tx.canonical import thaw_json
from sword_runtime.tx.coordinator import TransactionCoordinator
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.receipts import ReceiptStore
from sword_runtime.tx.remote import GitRemoteDurability
from sword_runtime.tx.wal import WriteAheadLog

_CONTESTED_COMMANDS = frozenset({"battle_resolve", "personal_combat"})

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

    @staticmethod
    def _is_contested(command_type: str, payload: dict[str, Any]) -> bool:
        return command_type in _CONTESTED_COMMANDS or (
            command_type == "siege_action" and str(payload.get("action")) == "assault"
        )

    def preview_for_execution(self, command):
        """Preview intent without leaking a stochastic or contested outcome.

        Deterministic commands use the normal full planner preview. Contested
        commands only validate envelope identity, current revision, payload
        semantics, and player authority. Their outcome is sampled exactly once
        during execute, so preview cannot be used as an oracle.
        """
        payload = thaw_json(command.payload)
        if not self._is_contested(command.command_type, payload):
            plan = self.preview(command)
            return {
                "status": "ready",
                "target_revision": command.expected_revision + 1,
                "planning_reads": plan.planning_reads,
                "writes": len(plan.writes),
                "result": plan.result,
                "contested_outcome_hidden": False,
            }

        planner = self.planner
        planner._reset()
        planner._authorize(command)
        self.store.require_campaign(command.campaign_id)
        self.store.require_revision(command.expected_revision)
        planner._validate_command_semantics(command, payload)
        planner._authorize_command(command, payload)
        return {
            "status": "ready_execute_only",
            "target_revision": command.expected_revision + 1,
            "planning_reads": len(planner._reads),
            "writes": None,
            "result": None,
            "contested_outcome_hidden": True,
        }

__all__ = ["ProductionSwordRuntime"]
