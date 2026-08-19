"""Production Sword runtime wiring for persistent hosted play."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.activity_living_world import (
    _ACTIVITY_CADENCE_SECONDS,
    _ACTIVITY_DEFAULT_VERIFIED_HOURS,
    _ACTIVITY_SHARD_SIZE,
)
from sword_runtime.causal_living_world import _WAKE_RESPONSE_COMMANDS
from sword_runtime.engine import SwordRuntime
from sword_runtime.living_world import HighSalienceWakeRequired
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_rates import verified_activity_hours_per_cycle
from sword_runtime.tx.canonical import thaw_json
from sword_runtime.tx.campaign_coordinator import TransactionCoordinator
from sword_runtime.tx.errors import RemoteDivergenceError, RemoteDurabilityError
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.receipts import ReceiptStore
from sword_runtime.tx.remote import GitRemoteDurability
from sword_runtime.tx.wal import WriteAheadLog

_COMMAND_PERSONNEL_INDEX = "state/cmd/command-personnel.json"
_ACTIVITY_PROFILES = "game/data/mil/recruitment-cohort-profiles.json"

_CONTESTED_COMMANDS = frozenset({
    "advance_time", "travel", "battle_resolve", "personal_combat",
    "medical_treatment", "military_allegiance_action",
})


class CommandRoutedProductionPlanner(ProductionCampaignPlanner):
    """Resolve exact command staff through the bounded command-person registry."""

    def owner_path(self, owner_ref: str) -> str:
        try:
            return super().owner_path(owner_ref)
        except ValueError:
            index = self.read_optional(_COMMAND_PERSONNEL_INDEX)
            records = index.get("record_index", {}) if isinstance(index, Mapping) else {}
            path = records.get(owner_ref) if isinstance(records, Mapping) else None
            if isinstance(path, str) and path:
                return path
            raise

    @staticmethod
    def _named_unit_command_count(formation: Mapping[str, Any], target: int) -> int:
        """Count full formal unit-command bodies without counting embedded ranks.

        If explicit persistent unit cells exist, only their formal commanders and
        deputies satisfy those unit-command billets. A higher field commander on
        the parent formation does not replace a missing cell commander/deputy.
        For ordinary single-unit formations without explicit cells, the top-level
        commander/deputy remain the formal unit-command pair.
        """
        target = max(0, int(target))
        if target <= 0:
            return 0

        nested: set[str] = set()

        def add_nested(value: Any) -> None:
            if isinstance(value, str) and value:
                nested.add(value)

        cell_lists: list[Any] = [formation.get("unit_command_cells")]
        structure = formation.get("command_structure")
        if isinstance(structure, Mapping):
            cell_lists.append(structure.get("unit_cells"))
            cell_lists.append(structure.get("unit_command_cells"))
        explicit_cells = False
        for cells in cell_lists:
            if not isinstance(cells, list) or not cells:
                continue
            explicit_cells = True
            for cell in cells:
                if not isinstance(cell, Mapping):
                    continue
                add_nested(cell.get("commander_ref"))
                add_nested(cell.get("deputy_ref"))
        if explicit_cells:
            return min(target, len(nested))

        top = {
            str(formation.get(key))
            for key in ("commander_ref", "deputy_ref")
            if isinstance(formation.get(key), str) and str(formation.get(key))
        }
        return min(target, len(top))

    def _ensure_activity_routes(self) -> None:
        """Route exact full-character command staff into normal smart training."""
        super()._ensure_activity_routes()
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")

        command_index = self.read_optional(_COMMAND_PERSONNEL_INDEX) or {}
        record_index = command_index.get("record_index", {}) if isinstance(command_index, Mapping) else {}
        if not isinstance(record_index, Mapping):
            return

        shards = self._activity_hosts(hosts)
        existing: set[str] = set()
        for _host_id, shard in shards:
            refs = shard.get("routed_person_refs", [])
            if isinstance(refs, list):
                existing.update(str(ref) for ref in refs if isinstance(ref, str))

        now_text = str(runtime.get("world_time"))
        now = CampaignTime.parse(now_text)
        profiles = self.read(_ACTIVITY_PROFILES)
        added: list[str] = []

        for person_ref, path in sorted(record_index.items()):
            if (
                not isinstance(person_ref, str)
                or person_ref == self.PLAYER_ACTOR
                or person_ref in existing
                or not isinstance(path, str)
                or not path.startswith("state/char/")
            ):
                continue
            person = copy.deepcopy(self.read(path))
            if str(person.get("schema", "")) != "sab_character":
                continue
            contract = self._effective_activity_contract(person)
            focuses = self._activity_focuses(person, contract) if isinstance(contract, Mapping) else []
            if not isinstance(contract, Mapping) or contract.get("autonomous_enabled") is False or not focuses:
                continue

            activity = person.setdefault("autonomous_activity_state", {})
            if not isinstance(activity, dict):
                raise ValueError("exact command person autonomous_activity_state is invalid")
            cadence = max(1, int(activity.get("cadence_seconds", _ACTIVITY_CADENCE_SECONDS)))
            cycle_hours = verified_activity_hours_per_cycle(
                person,
                contract,
                profiles,
                cadence,
                fallback_hours=_ACTIVITY_DEFAULT_VERIFIED_HOURS,
            )
            if cycle_hours <= 0:
                continue
            activity.setdefault("enabled", True)
            activity.setdefault("routed_at", now_text)
            activity["cadence_seconds"] = cadence
            activity["verified_hours_per_cycle"] = round(cycle_hours, 6)
            activity.setdefault("focus_cursor", 0)
            activity.setdefault("next_due", str(now.add_seconds(cadence)))
            activity["verification_rule"] = (
                "exact command staff use verified elapsed smart role training through the normal named-person activity owner"
            )
            self.put(path, person)

            shards = self._activity_hosts(hosts)
            if shards and len(shards[-1][1].get("routed_person_refs", [])) < _ACTIVITY_SHARD_SIZE:
                target_host = shards[-1][1]
            else:
                target_host = self._ensure_activity_shard(
                    hosts,
                    events,
                    index=len(shards),
                    now=now,
                    now_text=now_text,
                )
            refs = target_host.setdefault("routed_person_refs", [])
            refs.append(person_ref)
            refs[:] = sorted(set(str(ref) for ref in refs if isinstance(ref, str)))
            existing.add(person_ref)
            added.append(person_ref)

        if not added:
            return
        shards = self._activity_hosts(hosts)
        routing = runtime.setdefault("person_activity_routing", {})
        if isinstance(routing, dict):
            routing["routed_count"] = sum(len(shard.get("routed_person_refs", [])) for _host_id, shard in shards)
            routing["route_shards"] = len(shards)
            routing["last_route_scan_at"] = now_text
        metrics = runtime.setdefault("metrics", {})
        if isinstance(metrics, dict):
            metrics["person_activity_route_registrations"] = int(metrics.get("person_activity_route_registrations", 0)) + len(added)
        self.put("state/runtime.json", runtime)


class ProductionSwordRuntime(SwordRuntime):
    """Sword runtime with fail-closed production security and remote durability."""

    def __init__(self, root: object, runtime_root: object | None = None) -> None:
        super().__init__(root, runtime_root)
        player_id = self.store.read_json("state/meta.json").get("player_id")
        if not isinstance(player_id, str) or not player_id:
            raise RuntimeError("campaign meta must define a player_id")
        self.player_id = player_id
        self.planner = CommandRoutedProductionPlanner(self.root)
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
        self.replicator = None

    def _exact_person_record(self, person_ref: str) -> dict[str, Any]:
        owners = self.store.read_json("state/index/owner-index.json").get("owners", {})
        path = owners.get(person_ref) if isinstance(owners, Mapping) else None
        if not isinstance(path, str):
            command_index = self.store.read_json(_COMMAND_PERSONNEL_INDEX)
            records = command_index.get("record_index", {}) if isinstance(command_index, Mapping) else {}
            path = records.get(person_ref) if isinstance(records, Mapping) else None
        if not isinstance(path, str):
            raise ValueError("unknown exact person")
        person = self.store.read_json(path)
        if not isinstance(person, dict) or str(person.get("schema", "")) != "sab_character":
            raise ValueError("invalid exact person")
        return person

    def _validate_player_authored_agency(self, command) -> None:
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
            affiliation_value = person.get("affiliation", "")
            affiliations = {str(x) for x in affiliation_value} if isinstance(affiliation_value, list) else {str(affiliation_value)}
            current_formation = str(person.get("current_formation_id", ""))
            if (
                subject_ref != self.player_id
                and not ({"House Tang", "house_tang", "Tang Wei Personal Retinue"} & affiliations)
                and current_formation != "personal_force_tang_wei"
            ):
                raise PermissionError(
                    "House Tang duty assignment requires a person already within House Tang or Tang Wei's personal-retinue authority"
                )

    def _require_pending_wake_response(self, command_type: str) -> None:
        runtime_state = self.store.read_json("state/runtime.json")
        wake = runtime_state.get("pending_wake") if isinstance(runtime_state, Mapping) else None
        if not isinstance(wake, Mapping):
            return
        if command_type not in _WAKE_RESPONSE_COMMANDS:
            raise HighSalienceWakeRequired("pending_autonomous_contact_requires_player_resolution")

    @staticmethod
    def _is_contested(command_type: str, payload: dict[str, Any]) -> bool:
        return command_type in _CONTESTED_COMMANDS or (
            command_type == "siege_action" and str(payload.get("action")) in {"assault", "ram_gate"}
        )

    def _preview_persistence_readiness(self) -> dict[str, Any] | None:
        try:
            self.coordinator.recover()
        except RemoteDivergenceError as exc:
            if exc.code == "head_mismatch":
                return {"status":"deployment_sync_required","reason":"runtime_source_head_mismatch","contested_outcome_hidden":False}
            return {"status":"persistence_unavailable","reason":"remote_branch_diverged","contested_outcome_hidden":False}
        except RemoteDurabilityError:
            return {"status":"persistence_unavailable","reason":"remote_durability_unavailable","contested_outcome_hidden":False}
        return None

    def preview_for_execution(self, command):
        self._validate_player_authored_agency(command)
        self._require_pending_wake_response(command.command_type)
        persistence_block = self._preview_persistence_readiness()
        if persistence_block is not None:
            return persistence_block
        payload = thaw_json(command.payload)
        if not self._is_contested(command.command_type, payload):
            plan = self.preview(command)
            return {
                "status":"ready","target_revision":command.expected_revision + 1,
                "planning_reads":plan.planning_reads,"writes":len(plan.writes),
                "result":plan.result,"contested_outcome_hidden":False,
            }
        planner = self.planner
        planner._reset()
        planner._authorize(command)
        self.store.require_campaign(command.campaign_id)
        self.store.require_revision(command.expected_revision)
        planner._validate_command_semantics(command, payload)
        planner._authorize_command(command, payload)
        return {
            "status":"ready_execute_only","target_revision":command.expected_revision + 1,
            "planning_reads":len(planner._reads),"writes":None,"result":None,
            "contested_outcome_hidden":True,
        }

    def execute(self, command, *args, **kwargs):
        self._validate_player_authored_agency(command)
        self._require_pending_wake_response(command.command_type)
        return super().execute(command, *args, **kwargs)


__all__ = ["ProductionSwordRuntime", "CommandRoutedProductionPlanner"]
