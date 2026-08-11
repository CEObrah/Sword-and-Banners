"""Production Sword runtime wiring for persistent hosted play.

Hosted service construction uses this subclass so a configured Git remote is
part of transaction durability: a gameplay receipt is not published until the
exact transaction commit is pushed and verified remotely.
"""
from __future__ import annotations
from typing import Any

from sword_runtime.engine import SwordRuntime
from sword_runtime.production_living_world import ProductionLivingWorldSwordPlanner
from sword_runtime.tx.canonical import thaw_json
from sword_runtime.tx.campaign_coordinator import TransactionCoordinator
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.receipts import ReceiptStore
from sword_runtime.tx.remote import GitRemoteDurability
from sword_runtime.tx.wal import WriteAheadLog

# Broad time advancement can cross hidden autonomous causal events. Treat its
# preview like other contested resolution so the model cannot probe future
# contacts by repeatedly previewing different horizons.
_CONTESTED_COMMANDS = frozenset({"advance_time", "battle_resolve", "personal_combat"})


class ProductionSwordRuntime(SwordRuntime):
    """Sword runtime with fail-closed production security and remote durability."""

    def __init__(self, root: object, runtime_root: object | None = None) -> None:
        super().__init__(root, runtime_root)
        player_id = self.store.read_json("state/meta.json").get("player_id")
        if not isinstance(player_id, str) or not player_id:
            raise RuntimeError("campaign meta must define a player_id")
        self.player_id = player_id
        # Production autonomy is layered over the same exact repository owners.
        # Replacing the generic planner here avoids a second runtime instance or
        # a second campaign authority while allowing the hosted service to use
        # learned operational memory, causal provenance, and high-salience wake
        # protection.
        self.planner = ProductionLivingWorldSwordPlanner(self.root)
        self.planner.PLAYER_ACTOR = player_id

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

    def _exact_person_record(self, person_ref: str) -> dict[str, Any]:
        owners = self.store.read_json("state/index/owner-index-gold.json").get("owners", {})
        path = owners.get(person_ref)
        if not isinstance(path, str) or not person_ref.startswith("char_"):
            raise ValueError("unknown exact person")
        person = self.store.read_json(path)
        if not isinstance(person, dict):
            raise ValueError("invalid exact person")
        return person

    def _validate_player_authored_agency(self, command) -> None:
        """Close player-surface agency channels broader than organizational authority."""

        if command.mode != "gameplay" or command.actor_id != self.player_id:
            return
        payload = thaw_json(command.payload)
        if command.command_type == "family_event" and str(payload.get("kind")) == "marriage":
            parties = {str(payload.get("person_ref", "")), str(payload.get("partner_ref", ""))}
            if self.player_id not in parties:
                raise PermissionError(
                    "player-authored marriage requires the player actor to be one of the marrying parties; NPC marriages are autonomous/runtime consequences"
                )

        if command.command_type == "house_action" and str(payload.get("action", "assign_duty")) == "assign_duty":
            subject_ref = str(payload.get("subject_ref", ""))
            person = self._exact_person_record(subject_ref)
            affiliation = str(person.get("affiliation", ""))
            current_formation = str(person.get("current_formation_id", ""))
            if (
                subject_ref != self.player_id
                and affiliation not in {"House Tang", "Tang Wei Personal Retinue"}
                and current_formation != "personal_force_tang_wei"
            ):
                raise PermissionError(
                    "House Tang duty assignment requires a person already within House Tang or Tang Wei's personal-retinue authority"
                )

    @staticmethod
    def _is_contested(command_type: str, payload: dict[str, Any]) -> bool:
        return command_type in _CONTESTED_COMMANDS or (
            command_type == "siege_action" and str(payload.get("action")) == "assault"
        )

    def preview_for_execution(self, command):
        """Preview intent without leaking a stochastic or hidden-future outcome."""

        self._validate_player_authored_agency(command)
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

    def execute(self, command, *args, **kwargs):
        self._validate_player_authored_agency(command)
        return super().execute(command, *args, **kwargs)


__all__ = ["ProductionSwordRuntime"]
