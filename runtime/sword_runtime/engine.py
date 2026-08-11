from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from sword_runtime.commands import CommandEnvelope
from sword_runtime.development import age_years, settle_skill_training
from sword_runtime.semantic_validation import require_int, require_number, require_text, require_list
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.store.overlay import StagedOverlay
from sword_runtime.store.repository import RepositoryStore
from sword_runtime.store.schema_validation import RegisteredSchemaValidator
from sword_runtime.tx.canonical import thaw_json
from sword_runtime.tx.coordinator import TransactionCoordinator, TransactionExecution
from sword_runtime.tx.git import GitStager
from sword_runtime.tx.receipts import ReceiptStore
from sword_runtime.tx.wal import WriteAheadLog


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _deepcopy(value: Any) -> Any:
    return copy.deepcopy(value)


def _fixed(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _pct(value: Any) -> float:
    x = _fixed(value, 0.0)
    return x / 100.0 if x > 1.0 else x


def _clamp(v: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(v)))


@dataclass
class CommandPlan:
    transaction_id: str
    created_at: str
    writes: Dict[str, Optional[bytes]]
    result: Dict[str, Any]
    planning_reads: int
    validator: Any


COMMAND_TYPES = frozenset({
    "advance_time","scene_consequence","travel","individual_training","cohort_training",
    "health_injury","health_recovery","relationship_change","recruitment","population_transfer",
    "person_materialize","formation_create","formation_reconstitute","formation_split","formation_merge",
    "formation_dissolve","formation_assign","force_assignment","formation_move","formation_train",
    "formation_mobilize","formation_demobilize","formation_doctrine_set","formation_training_set",
    "command_assign","command_transfer","resupply","battle_resolve","personal_combat","operation_create",
    "operation_transition","information_create","information_deliver","institution_project","house_action",
    "state_action","market_purchase","economy_transfer","enlisted_service_pay","fortification_materialize",
    "siege_start","siege_action","territorial_consequence","family_event","repair",
    "equipment_equip","equipment_unequip","equipment_transfer","equipment_drop","equipment_consume","market_sell",
    "reputation_event","career_event","mercenary_contract","project_resolve"
})

class RepositoryCommandPlanner:
    INTERNAL_ACTOR = "internal:sword-autonomy"
    PLAYER_ACTOR = "char_tang_wei"

    def __init__(self, root: object) -> None:
        self.store = RepositoryStore(root)
        self.root = self.store.root
        self.schema_validator = RegisteredSchemaValidator.optional(self.store)
        self._reads: set[str] = set()
        self._cache: Dict[str, Any] = {}
        self._writes: Dict[str, Any] = {}
        self._deletes: set[str] = set()

    def _reset(self) -> None:
        self._reads = set()
        self._cache = {}
        self._writes = {}
        self._deletes = set()

    def read(self, path: str) -> Any:
        if path in self._writes:
            return self._writes[path]
        if path in self._cache:
            return self._cache[path]
        self._reads.add(path)
        value = self.store.read_json(path)
        self._cache[path] = value
        return value

    def read_optional(self, path: str) -> Any:
        if path in self._writes:
            return self._writes[path]
        if path in self._cache:
            return self._cache[path]
        self._reads.add(path)
        raw = self.store.read_optional_bytes(path)
        if raw is None:
            self._cache[path] = None
            return None
        value = json.loads(raw.decode("utf-8"))
        self._cache[path] = value
        return value

    def put(self, path: str, value: Any) -> None:
        self._writes[path] = value
        self._deletes.discard(path)

    def delete(self, path: str) -> None:
        self._writes.pop(path, None)
        self._deletes.add(path)

    def owner_path(self, owner_ref: str) -> str:
        idx = self.read("state/index/owner-index-gold.json")
        path = idx.get("owners", {}).get(owner_ref)
        if not isinstance(path, str):
            raise ValueError("unknown authoritative owner: %s" % owner_ref)
        return path

    def owner(self, owner_ref: str) -> tuple[str, Any]:
        path = self.owner_path(owner_ref)
        return path, self.read(path)

    @staticmethod
    def _state_key(value: str) -> str:
        v = str(value).lower().replace("state_", "").replace("population_", "")
        if v not in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
            raise ValueError("unknown Warring States polity: %s" % value)
        return v

    def _authorize(self, command: CommandEnvelope) -> None:
        if command.mode == "ooc":
            raise ValueError("OOC is read-only and may not execute a transaction")
        if command.actor_id == self.INTERNAL_ACTOR:
            if command.mode == "maintenance" and command.command_type != "repair":
                raise ValueError("maintenance mode is reserved for explicit repair")
            if command.mode not in {"autonomous", "maintenance"}:
                raise ValueError("internal actor must use autonomous or maintenance mode")
            return
        if command.actor_id != self.PLAYER_ACTOR:
            raise PermissionError("gameplay actor identity is fixed by campaign authority")
        if command.mode != "gameplay":
            raise PermissionError("player-facing actors may only use gameplay mode")
        if command.command_type == "repair":
            raise PermissionError("repair is OOC DEV internal maintenance only")

    def _write_meta(self, command: CommandEnvelope, world_time: Optional[str] = None) -> None:
        meta = _deepcopy(self.read("state/meta.json"))
        meta["revision"] = command.expected_revision + 1
        if world_time is not None:
            meta["time"] = world_time
        self.put("state/meta.json", meta)

    def _result(self, **kwargs: Any) -> Dict[str, Any]:
        out = {"planning_reads": len(self._reads)}
        out.update(kwargs)
        return out

    def _validator(self, overlay: StagedOverlay, manifest: Any) -> None:
        if self.schema_validator is not None:
            self.schema_validator.validate_overlay(overlay, manifest.paths)
        self._validate_invariants(overlay, manifest.paths)

    def _validate_invariants(self, overlay: StagedOverlay, paths: Iterable[str]) -> None:
        meta = overlay.read_json("state/meta.json")
        if meta.get("game") != "sword_and_banners":
            raise ValueError("wrong game authority")
        rt = overlay.read_json("state/runtime.json") if overlay.read_optional_bytes("state/runtime.json") else None
        if isinstance(rt, dict):
            metrics = rt.get("metrics", {})
            for key in ("global_person_scans", "global_faction_scans", "global_force_scans", "global_house_scans"):
                if int(metrics.get(key, 0)) != 0:
                    raise ValueError("global polling is forbidden: %s" % key)
        # Validate only directly affected state/military owners, never scan directories.
        touched_states: set[str] = set()
        for path in paths:
            for prefix in ("state/population/", "state/forces/", "state/states/", "state/mounts/"):
                if path.startswith(prefix):
                    name = Path(path).stem.replace("state-", "")
                    if name in {"qin","zhao","chu","wei","han","yan","qi"}:
                        touched_states.add(name)
        for state in touched_states:
            pp = f"state/population/{state}.json"
            if overlay.read_optional_bytes(pp):
                pop = overlay.read_json(pp)
                if sum(int(v) for v in pop.get("strata", {}).values()) != int(pop.get("population_total", -1)):
                    raise ValueError("population conservation failed for %s" % state)
            fp = f"state/forces/state-{state}.json"
            if overlay.read_optional_bytes(fp):
                force = overlay.read_json(fp)
                available_by_role = {str(k): int(v) for k, v in force.get("available_by_role", {}).items()}
                available = sum(available_by_role.values())
                by_location: Dict[str, int] = {}
                for pool in force.get("available_by_location", {}).values():
                    if isinstance(pool, dict):
                        for role, count in pool.items():
                            by_location[str(role)] = int(by_location.get(str(role), 0)) + int(count)
                if by_location and by_location != available_by_role:
                    raise ValueError("force location-aware reserve conservation failed for %s" % state)
                allocated = sum(int(v.get("personnel", 0)) if isinstance(v, dict) else int(v) for v in force.get("allocated_to_formations", {}).values())
                materialized = sum(int(v) if not isinstance(v, dict) else int(v.get("personnel", 1)) for v in force.get("materialized_people", {}).values())
                if available + allocated + materialized != int(force.get("headcount", -1)):
                    raise ValueError("force conservation failed for %s" % state)
            mp = f"state/mounts/{state}.json"
            if overlay.read_optional_bytes(mp):
                mounts = overlay.read_json(mp)
                if sum(int(v) for v in mounts.get("types", {}).values()) != int(mounts.get("total", -1)):
                    raise ValueError("mount type conservation failed for %s" % state)
                if sum(int(v) for v in mounts.get("health", {}).values()) != int(mounts.get("total", -1)):
                    raise ValueError("mount health conservation failed for %s" % state)

    def _formation_path(self, ref: str) -> str:
        idx = self.read("state/index/owner-index-gold.json")
        p = idx.get("owners", {}).get(ref)
        if isinstance(p, str):
            return p
        p = f"state/formations/{ref.replace('formation_','').replace('_','-')}.json"
        if self.read_optional(p) is not None:
            return p
        raise ValueError("unknown formation: %s" % ref)

    def _load_formation(self, ref: str) -> tuple[str, Any]:
        p = self._formation_path(ref)
        return p, self.read(p)

    def _register_owner(self, owner_id: str, path: str) -> None:
        idx = _deepcopy(self.read("state/index/owner-index-gold.json"))
        owners = idx.setdefault("owners", {})
        if owner_id in owners and owners[owner_id] != path:
            raise ValueError("duplicate mutable authority: %s" % owner_id)
        owners[owner_id] = path
        self.put("state/index/owner-index-gold.json", idx)

    def _unregister_owner(self, owner_id: str) -> None:
        idx = _deepcopy(self.read("state/index/owner-index-gold.json"))
        idx.get("owners", {}).pop(owner_id, None)
        self.put("state/index/owner-index-gold.json", idx)

    def _actor_authority(self, actor_ref: str) -> Mapping[str, Any]:
        ref = f"authority_{actor_ref}"
        path = self.owner_path(ref)
        doc = self.read(path)
        if doc.get("actor_ref") != actor_ref:
            raise PermissionError("actor authority record does not match gameplay actor")
        return doc

    def _has_role_capability(self, actor_ref: str, authority_ref: str, capability: str) -> bool:
        doc = self._actor_authority(actor_ref)
        for role in doc.get("roles", []):
            if role.get("authority_ref") != authority_ref:
                continue
            caps = role.get("capabilities", [])
            if capability in caps or "*" in caps:
                return True
        return False

    def _state_capabilities(self, actor_ref: str, state: str) -> set[str]:
        state = self._state_key(state)
        caps: set[str] = set()
        if self._has_role_capability(actor_ref, f"state_{state}", "state_command"):
            caps.add("*")
        doc = self.read(f"state/states/{state}.json")
        for appointment in doc.get("appointments", {}).values():
            if isinstance(appointment, str):
                # Legacy string appointments are identity evidence only and do
                # not grant a blanket capability.
                continue
            if not isinstance(appointment, dict) or appointment.get("person_ref") != actor_ref:
                continue
            caps.update(str(x) for x in appointment.get("capabilities", []))
        return caps

    def _require_state_authority(self, actor_ref: str, state: str, capability: str) -> None:
        caps = self._state_capabilities(actor_ref, state)
        if "*" not in caps and capability not in caps:
            raise PermissionError(
                f"{actor_ref} lacks saved {capability} authority for state_{self._state_key(state)}"
            )

    def _require_house_authority(self, actor_ref: str, house_ref: str, capability: str) -> None:
        if not self._has_role_capability(actor_ref, house_ref, capability):
            raise PermissionError(f"{actor_ref} lacks saved {capability} authority for {house_ref}")

    def _require_institution_authority(self, actor_ref: str, institution_ref: str, capability: str) -> None:
        if self._has_role_capability(actor_ref, institution_ref, capability):
            return
        _, inst = self.owner(institution_ref)
        state = inst.get("state")
        if state:
            self._require_state_authority(actor_ref, str(state), capability)
            return
        raise PermissionError(f"{actor_ref} lacks saved {capability} authority for {institution_ref}")

    def _has_formation_authority(self, actor_ref: str, formation_ref: str, capability: str = "formation_command") -> bool:
        _, formation = self._load_formation(formation_ref)
        if formation.get("command_authority") == actor_ref or formation.get("administrative_owner") == actor_ref:
            return True
        force_ref = str(formation.get("owner_force_ref", ""))
        if force_ref and self._has_role_capability(actor_ref, force_ref, capability):
            return True
        admin = str(formation.get("administrative_owner", ""))
        if admin.startswith("house_") and self._has_role_capability(actor_ref, admin, capability):
            return True
        return False

    def _require_formation_authority(self, actor_ref: str, formation_ref: str, capability: str = "formation_command") -> None:
        if not self._has_formation_authority(actor_ref, formation_ref, capability):
            raise PermissionError(f"{actor_ref} lacks saved {capability} authority for {formation_ref}")

    def _commander_index(self) -> Dict[str, Any]:
        path = "state/index/commander-formation-index.json"
        return _deepcopy(self.read_optional(path) or {"schema":"sword-commander-formation-index","authority":False,"assignments":{}})

    def _assign_commander_index(self, commander_ref: str, formation_ref: str, *, replace: bool = False) -> None:
        idx = self._commander_index(); assignments = idx.setdefault("assignments", {})
        current = [str(x) for x in assignments.get(commander_ref, [])]
        if formation_ref not in current:
            current.append(formation_ref)
        assignments[commander_ref] = sorted(set(current))
        self.put("state/index/commander-formation-index.json", idx)

    def _release_commander_index(self, commander_ref: Optional[str], formation_ref: str) -> None:
        if not commander_ref:
            return
        idx = self._commander_index(); assignments = idx.setdefault("assignments", {})
        current = [str(x) for x in assignments.get(str(commander_ref), []) if str(x) != formation_ref]
        if current:
            assignments[str(commander_ref)] = current
        else:
            assignments.pop(str(commander_ref), None)
        self.put("state/index/commander-formation-index.json", idx)

    def _authorize_command(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> None:
        if command.actor_id == self.INTERNAL_ACTOR:
            return
        actor = command.actor_id
        t = command.command_type

        if t == "relationship_change" and str(payload.get("source_ref", actor)) != actor:
            raise PermissionError("gameplay may mutate only relationships sourced by the player actor")

        if t in {"reputation_event", "career_event"}:
            raise PermissionError(f"{t} is a derived world consequence and cannot be directly authored by the player")
        if t == "mercenary_contract":
            self._require_house_authority(actor, "house_tang", "house_administration")
            if str(payload.get("action")) == "accept":
                raise PermissionError("mercenary acceptance is an autonomous company decision, not a player-authored outcome")
        if t == "project_resolve":
            self._require_institution_authority(actor, str(payload["institution_ref"]), "institution_administration")

        if t == "information_create":
            knowers = {str(x) for x in payload.get("knowers", [])}
            if actor not in knowers:
                raise PermissionError("gameplay information creation requires the player actor as an exact knower")
        elif t == "information_deliver":
            ref = str(payload["information_ref"])
            path = self.read("state/information/index.json").get("claims", {}).get(ref)
            if not path:
                raise ValueError("unknown information claim")
            claim = self.read(path)
            if actor not in claim.get("knowers", []):
                raise PermissionError("actor may deliver only information they already know")

        if t in {"house_action", "family_event"}:
            self._require_house_authority(actor, str(payload.get("house_ref", "house_tang")), "house_administration")
            if t == "family_event" and str(payload.get("kind")) in {"pregnancy","birth","death","widowhood","succession_review"}:
                raise PermissionError("involuntary family life-course outcomes are runtime/internal consequences, not player-authored commands")
        elif t == "cohort_training":
            self._require_house_authority(actor, "house_tang", "house_training")

        state_capabilities = {
            "state_action": "state_command",
            "recruitment": "recruitment",
            "population_transfer": "population_administration",
            "person_materialize": "personnel_administration",
            "formation_create": "force_administration",
            "fortification_materialize": "fortification_administration",
            "enlisted_service_pay": "treasury_disbursement",
        }
        if t in state_capabilities:
            self._require_state_authority(actor, str(payload.get("state", "qin")), state_capabilities[t])
        elif t == "economy_transfer" and payload.get("direction") != "player_to_state":
            self._require_state_authority(actor, str(payload.get("state", "qin")), "treasury_disbursement")

        formation_commands = {
            "formation_reconstitute", "formation_train", "formation_mobilize", "formation_demobilize",
            "formation_doctrine_set", "formation_training_set", "formation_assign", "force_assignment",
            "command_assign", "command_transfer", "formation_move", "resupply", "formation_split",
            "formation_dissolve",
        }
        if t in formation_commands:
            self._require_formation_authority(actor, str(payload["formation_ref"]))
        elif t == "formation_merge":
            refs = [str(x) for x in payload.get("formation_refs", [])]
            if not refs:
                raise ValueError("merge requires formations")
            for ref in refs:
                self._require_formation_authority(actor, ref)
        elif t == "battle_resolve":
            side = str(payload.get("controlled_side", "attacker"))
            key = "defender_formation_refs" if side == "defender" else "attacker_formation_refs"
            refs = [str(x) for x in payload.get(key, [])]
            if not refs:
                raise PermissionError("gameplay battle requires an explicitly controlled formation side")
            for ref in refs:
                self._require_formation_authority(actor, ref)
        elif t == "operation_create":
            for ref in payload.get("formation_refs", []):
                self._require_formation_authority(actor, str(ref))
        elif t == "operation_transition":
            op_ref = str(payload["operation_ref"])
            op_path = self.read("state/operations/index.json").get("operations", {}).get(op_ref)
            if not op_path:
                raise ValueError("unknown operation")
            op = self.read(op_path)
            for ref in op.get("formation_refs", []):
                self._require_formation_authority(actor, str(ref))
        elif t == "institution_project":
            self._require_institution_authority(actor, str(payload["institution_ref"]), "institution_administration")
        elif t == "siege_start":
            for ref in payload.get("attacker_formation_refs", []):
                self._require_formation_authority(actor, str(ref))
        elif t == "siege_action":
            ref = str(payload["siege_ref"])
            path = self.read("state/sieges/index.json").get("sieges", {}).get(ref)
            if not path:
                raise ValueError("unknown siege")
            siege = self.read(path)
            refs = list(siege.get("attacker_formation_refs", [])) + list(siege.get("defender_formation_refs", []))
            if refs and not any(self._has_formation_authority(actor, str(x)) for x in refs):
                raise PermissionError("actor lacks command authority over either side of the siege")
        elif t == "territorial_consequence":
            controller = str(payload.get("controller", ""))
            if controller.startswith("state_"):
                self._require_state_authority(actor, controller.replace("state_", ""), "territorial_administration")

    @staticmethod
    def _partition_counts(values: Mapping[str, Any], take_total: int, population_total: int) -> tuple[Dict[str, int], Dict[str, int]]:
        if take_total < 0 or population_total <= 0 or take_total > population_total:
            raise ValueError("invalid proportional partition")
        keys = sorted(str(k) for k in values)
        source = {k: int(values.get(k, 0)) for k in keys}
        taken: Dict[str, int] = {}
        remaining_target = take_total
        remaining_population = population_total
        for i, key in enumerate(keys):
            count = source[key]
            if i == len(keys) - 1:
                share = min(count, remaining_target)
            else:
                share = min(count, int(math.floor(count * remaining_target / max(1, remaining_population))))
            taken[key] = share
            remaining_target -= share
            remaining_population -= count
        if remaining_target:
            for key in reversed(keys):
                spare = source[key] - taken[key]
                add = min(spare, remaining_target)
                taken[key] += add
                remaining_target -= add
                if not remaining_target:
                    break
        if remaining_target:
            raise ValueError("partition could not conserve requested count")
        remainder = {k: source[k] - taken[k] for k in keys}
        return remainder, taken

    @staticmethod
    def _partition_material(values: Mapping[str, Any], take_personnel: int, total_personnel: int) -> tuple[Dict[str, int], Dict[str, int]]:
        parent: Dict[str, int] = {}
        child: Dict[str, int] = {}
        for key in sorted(str(k) for k in values):
            amount = max(0, int(values.get(key, 0)))
            share = int(math.floor(amount * take_personnel / max(1, total_personnel)))
            child[key] = share
            parent[key] = amount - share
        return parent, child

    @staticmethod
    def _merge_material(*maps: Mapping[str, Any]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for values in maps:
            for key, value in values.items():
                out[str(key)] = int(out.get(str(key), 0)) + int(value)
        return out

    @staticmethod
    def _equipment_units(formation: Mapping[str, Any]) -> Dict[str, int]:
        explicit = formation.get("equipment_units_by_role")
        if isinstance(explicit, dict):
            return {str(k): max(0, int(v)) for k, v in explicit.items()}
        completeness = max(0.0, min(1.0, _pct(formation.get("equipment_completeness", 0.0))))
        return {
            str(role): min(int(count), max(0, int(round(int(count) * completeness))))
            for role, count in formation.get("composition", {}).items()
        }

    @staticmethod
    def _set_equipment_units(formation: Dict[str, Any], units: Mapping[str, Any]) -> None:
        normalized = {str(k): max(0, int(v)) for k, v in units.items()}
        formation["equipment_units_by_role"] = normalized
        personnel = max(1, int(formation.get("personnel", 0)))
        total_units = sum(normalized.values())
        formation["equipment_completeness"] = f"{min(1.0, total_units / personnel):.4f}"

    def _force_equipment_pool(self, force: Dict[str, Any]) -> Dict[str, int]:
        pool = force.setdefault("available_equipment_units_by_role", {})
        return pool

    @staticmethod
    def _force_equipment_location_pool(force: Dict[str, Any], location_ref: str) -> Dict[str, int]:
        return force.setdefault("available_equipment_by_location", {}).setdefault(location_ref, {})

    def _take_force_equipment(self, force: Dict[str, Any], role: str, count: int, location_ref: str) -> int:
        if count <= 0:
            return 0
        aggregate = self._force_equipment_pool(force); local = self._force_equipment_location_pool(force, location_ref)
        take = min(count, int(aggregate.get(role, 0)), int(local.get(role, 0)))
        aggregate[role] = int(aggregate.get(role, 0)) - take; local[role] = int(local.get(role, 0)) - take
        return take

    def _return_force_equipment(self, force: Dict[str, Any], role: str, count: int, location_ref: str) -> None:
        if count <= 0:
            return
        aggregate = self._force_equipment_pool(force); local = self._force_equipment_location_pool(force, location_ref)
        aggregate[role] = int(aggregate.get(role, 0)) + count; local[role] = int(local.get(role, 0)) + count

    @staticmethod
    def _force_location_pool(force: Dict[str, Any], location_ref: str) -> Dict[str, int]:
        pools = force.setdefault("available_by_location", {})
        return pools.setdefault(location_ref, {})

    def _take_force_personnel(self, force: Dict[str, Any], role: str, count: int, location_ref: str) -> None:
        if count < 0:
            raise ValueError("cannot take negative force personnel")
        loc_pool = self._force_location_pool(force, location_ref)
        if int(loc_pool.get(role, 0)) < count:
            raise ValueError("insufficient conserved personnel at the exact source location")
        if int(force.get("available_by_role", {}).get(role, 0)) < count:
            raise ValueError("insufficient conserved force role pool")
        loc_pool[role] = int(loc_pool.get(role, 0)) - count
        force["available_by_role"][role] = int(force["available_by_role"].get(role, 0)) - count

    def _return_force_personnel(self, force: Dict[str, Any], role: str, count: int, location_ref: str) -> None:
        if count < 0:
            raise ValueError("cannot return negative force personnel")
        loc_pool = self._force_location_pool(force, location_ref)
        loc_pool[role] = int(loc_pool.get(role, 0)) + count
        force.setdefault("available_by_role", {})[role] = int(force.get("available_by_role", {}).get(role, 0)) + count

    def _material_depot(self, formation: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
        force_ref = str(formation.get("owner_force_ref", "")); location = str(formation.get("location_ref", ""))
        if force_ref.startswith("force_state_"):
            state = force_ref.replace("force_state_", ""); home_path = f"state/depots/{state}.json"; home = _deepcopy(self.read(home_path))
            if home.get("location_ref") == location:
                return home_path, home
            slug = str(formation.get("formation_ref", "field")).replace("formation_", "").replace("_", "-")
            path = f"state/depots/field-{slug}.json"; existing = self.read_optional(path)
            if existing is not None:
                return path, _deepcopy(existing)
            depot={"schema":"sword-depot","owner_id":f"depot_field_{slug}","state":state,"location_ref":location,"stocks":{"grain_kg":0,"fodder_kg":0,"war_arrows":0},"mounts":{},"kind":"field_cache"}; self.put(path,depot); self._register_owner(depot["owner_id"],path); return path,depot
        admin = str(formation.get("administrative_owner", "private")); slug = force_ref.replace("force_", "").replace("_", "-") or "private"; home_path=f"state/depots/{slug}.json"; existing=self.read_optional(home_path)
        if existing is not None and existing.get("location_ref") == location:
            return home_path, _deepcopy(existing)
        if existing is None:
            depot={"schema":"sword-depot","owner_id":f"depot_{force_ref or slug}","state":admin,"location_ref":location,"stocks":{"grain_kg":0,"fodder_kg":0,"war_arrows":0},"mounts":{}}; self.put(home_path,depot); self._register_owner(depot["owner_id"],home_path); return home_path,depot
        field_slug=str(formation.get("formation_ref","field")).replace("formation_","").replace("_","-"); path=f"state/depots/field-{field_slug}.json"; field=self.read_optional(path)
        if field is None:
            field={"schema":"sword-depot","owner_id":f"depot_field_{field_slug}","state":admin,"location_ref":location,"stocks":{"grain_kg":0,"fodder_kg":0,"war_arrows":0},"mounts":{},"kind":"field_cache"}; self.put(path,field); self._register_owner(field["owner_id"],path)
        return path,_deepcopy(field)

    def _return_formation_materials(self, formation: Mapping[str, Any]) -> None:
        path, depot = self._material_depot(formation)
        stocks = depot.setdefault("stocks", {})
        keymap = {"food_kg": "grain_kg", "fodder_kg": "fodder_kg", "war_arrows": "war_arrows"}
        for key, amount in formation.get("logistics", {}).items():
            stock_key = keymap.get(str(key), str(key))
            stocks[stock_key] = int(stocks.get(stock_key, 0)) + int(amount)
        mounts = depot.setdefault("mounts", {})
        for kind, count in formation.get("mounts", {}).items():
            mounts[str(kind)] = int(mounts.get(str(kind), 0)) + int(count)
        self.put(path, depot)

    def _location_record(self, location_ref: str) -> Mapping[str, Any]:
        for location in self.read("game/data/world/locations.json").get("locations", []):
            if location.get("ref") == location_ref:
                return location
        if location_ref.startswith("loc_tang_manor_"):
            return {"ref": location_ref, "kind": "estate", "functions": ["house"]}
        raise ValueError(f"unknown battlefield location: {location_ref}")

    @staticmethod
    def _person_location(person: Mapping[str, Any]) -> Optional[str]:
        for key in ("location", "current_location"):
            value = person.get(key)
            if isinstance(value, str) and value.startswith("loc_"):
                return value
        return None

    @staticmethod
    def _person_health(person: Mapping[str, Any]) -> str:
        return str(person.get("health", person.get("health_status", "healthy")))

    @staticmethod
    def _set_person_health(person: Dict[str, Any], value: str) -> None:
        if "health" in person:
            person["health"] = value
        else:
            person["health_status"] = value

    @staticmethod
    def _set_person_location(person: Dict[str, Any], value: str) -> None:
        if "location" in person:
            person["location"] = value
        else:
            person["current_location"] = value
        person.pop("location_scope", None)

    @staticmethod
    def _set_person_life_status(person: Dict[str, Any], value: str) -> None:
        if "life_status" in person:
            person["life_status"] = value
        elif "status" in person:
            person["status"] = value
        else:
            person["life_status"] = value

    def _world_time(self) -> CampaignTime:
        runtime_time = CampaignTime.parse(str(self.read("state/runtime.json")["world_time"]))
        meta_time = CampaignTime.parse(str(self.read("state/meta.json")["time"]))
        if runtime_time != meta_time:
            raise ValueError("campaign chronology authorities disagree")
        return runtime_time

    def _causal_seed(self, command: CommandEnvelope, payload: Mapping[str, Any], salt: str = "") -> int:
        meta = self.read("state/meta.json")
        material = {
            "world_seed": meta.get("world_seed"),
            "revision": command.expected_revision,
            "world_time": str(self._world_time()),
            "actor": command.actor_id,
            "command_type": command.command_type,
            "payload": payload,
            "salt": salt,
        }
        raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return int(hashlib.sha256(raw).hexdigest()[:16], 16)

    def _exact_person(self, person_ref: str, *, active: bool = True) -> tuple[str, Dict[str, Any]]:
        path, person0 = self.owner(str(person_ref))
        person = _deepcopy(person0)
        if person.get("schema") not in {"sab_character", "sword-materialized-person"}:
            raise ValueError(f"{person_ref} is not an exact saved person")
        life = str(person.get("life_status", person.get("status", "active"))).lower()
        if active and life in {"dead", "deceased", "destroyed"}:
            raise ValueError(f"{person_ref} is not an active living person")
        return path, person

    def _item_record(self, item_id: str) -> Dict[str, Any]:
        index = self.read("game/data/items.json")
        shard_path = index.get("record_index", {}).get(str(item_id))
        if not isinstance(shard_path, str):
            raise ValueError(f"unknown exact item: {item_id}")
        shard = self.read(shard_path)
        record = shard.get("items", {}).get(str(item_id))
        if not isinstance(record, dict):
            raise ValueError(f"item index is inconsistent for {item_id}")
        return _deepcopy(record)

    @staticmethod
    def _market_item_id(item_key: str) -> str:
        aliases = {
            "common_sword": "weapon_sword_one_hand",
            "military_sword": "weapon_sword_one_hand_long",
            "military_spear": "weapon_spear_long",
            "military_bow": "weapon_bow_composite",
            "helmet": "helmet_iron",
            "lamellar_cuirass": "armor_lamellar_military",
            "padded_coat": "armor_padded",
            "shield": "shield_medium",
            "arrows_20": "ammo_arrow_war",
        }
        item_id = aliases.get(str(item_key))
        if item_id is None:
            raise ValueError(f"market item has no exact equipment identity: {item_key}")
        return item_id

    def _player_inventory(self) -> tuple[str, Dict[str, Any]]:
        path = "state/economy/player-inventory.json"
        inv = _deepcopy(self.read_optional(path) or {"schema":"sword-player-inventory","owner_id":"inventory_char_tang_wei","items":{}})
        inv.setdefault("items", {})
        return path, inv

    def _player_manifest(self) -> tuple[str, Dict[str, Any]]:
        path = "state/player-detail/equipment-manifest.json"
        manifest = _deepcopy(self.read(path))
        manifest.setdefault("equipment_manifest", [])
        return path, manifest

    @staticmethod
    def _manifest_quantity(manifest: Mapping[str, Any], item_id: str, *, equipped_only: bool = False) -> int:
        total = 0
        for entry in manifest.get("equipment_manifest", []):
            if str(entry.get("item_id")) != item_id:
                continue
            state = str(entry.get("current_state", "")).lower()
            if equipped_only and not any(word in state for word in ("equipped", "worn", "readied", "quivered", "mounted")):
                continue
            total += max(0, int(entry.get("quantity", 0)))
        return total

    @staticmethod
    def _take_manifest_items(manifest: Dict[str, Any], item_id: str, quantity: int, *, require_equipped: bool = False) -> None:
        remaining = int(quantity)
        entries = manifest.setdefault("equipment_manifest", [])
        for entry in list(entries):
            if str(entry.get("item_id")) != item_id:
                continue
            state = str(entry.get("current_state", "")).lower()
            if require_equipped and not any(word in state for word in ("equipped", "worn", "readied", "quivered", "mounted")):
                continue
            take = min(remaining, max(0, int(entry.get("quantity", 0))))
            entry["quantity"] = int(entry.get("quantity", 0)) - take
            remaining -= take
            if int(entry.get("quantity", 0)) <= 0:
                entries.remove(entry)
            if remaining <= 0:
                break
        if remaining:
            raise ValueError("insufficient exact equipment custody")

    def _advance_seconds(self, seconds: int) -> tuple[str, Dict[str, int]]:
        if seconds < 0:
            raise ValueError("elapsed simulation time cannot be negative")
        current = self._world_time()
        target = str(current.add_seconds(max(1, int(seconds))))
        return target, self._advance_runtime(target)

    def _route_travel_hours(self, origin: str, destination: str, *, modes: tuple[str, ...] = ("horse", "foot")) -> int:
        if origin == destination:
            return 0
        import heapq
        graph: Dict[str, list[tuple[int, str]]] = {}
        for route in self.read("game/data/world/routes.json").get("routes", []):
            allowed = {str(x) for x in route.get("modes", [])}
            if not any(mode in allowed for mode in modes):
                continue
            a, b = str(route.get("a", route.get("from"))), str(route.get("b", route.get("to")))
            hours = max(1, int(route.get("duration_hours", route.get("hours", 24))))
            graph.setdefault(a, []).append((hours, b)); graph.setdefault(b, []).append((hours, a))
        if origin.startswith("loc_tang_manor_"):
            graph.setdefault(origin, []).append((1, "loc_kanyou")); graph.setdefault("loc_kanyou", []).append((1, origin))
        if destination.startswith("loc_tang_manor_"):
            graph.setdefault(destination, []).append((1, "loc_kanyou")); graph.setdefault("loc_kanyou", []).append((1, destination))
        queue=[(0,origin)]; best={origin:0}
        while queue:
            cost,node=heapq.heappop(queue)
            if node==destination: return int(cost)
            if cost!=best.get(node): continue
            for edge,nxt in graph.get(node,[]):
                nc=cost+edge
                if nc<best.get(nxt,10**18): best[nxt]=nc; heapq.heappush(queue,(nc,nxt))
        raise ValueError(f"no lawful messenger route between {origin} and {destination}")

    def _validate_person_location_for_formation(self, person_ref: str, formation: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
        path, person = self._exact_person(person_ref)
        floc = str(formation.get("location_ref", ""))
        ploc = self._person_location(person)
        if ploc == floc:
            return path, person
        scope = str(person.get("location_scope", ""))
        admin = str(formation.get("administrative_owner", ""))
        owner_force = str(formation.get("owner_force_ref", ""))
        expected_state = ""
        if admin.startswith("state_"):
            expected_state = admin
        elif owner_force.startswith("force_state_"):
            expected_state = owner_force.replace("force_", "")
        if ploc is None and scope == expected_state + "_unresolved":
            self._set_person_location(person, floc)
            return path, person
        raise ValueError("formation commander must be physically co-located with the formation")

    def _settle_person_death(self, person_ref: str, person_path: str, person: Dict[str, Any], at: str, reason: str) -> None:
        if str(person.get("life_status", person.get("status", "active"))).lower() in {"dead","deceased"}:
            return
        self._set_person_life_status(person, "dead"); self._set_person_health(person, "dead"); person["died_at"] = at; person["death_reason"] = reason; self.put(person_path, person)
        # Remove the exact person from every routed command assignment without a directory scan.
        cidx=self._commander_index(); assignments=list(cidx.get("assignments",{}).get(person_ref,[]))
        for formation_ref in assignments:
            try:
                fp,formation0=self._load_formation(str(formation_ref)); formation=_deepcopy(formation0)
            except ValueError:
                continue
            if formation.get("commander_ref")==person_ref:
                formation["commander_ref"]=None; formation["status"]="commander_vacant" if int(formation.get("personnel",0))>0 else formation.get("status"); self.put(fp,formation)
            self._release_commander_index(person_ref,str(formation_ref))
        # Family records are exact authority: death causes widowhood and succession review.
        family_index_path="state/family/index.json"; fidx=_deepcopy(self.read(family_index_path)); source_refs=[]
        for uid,up in list(fidx.get("unions",{}).items()):
            union=_deepcopy(self.read(up))
            if person_ref in union.get("participants",[]) and union.get("status")=="married":
                union["status"]="widowed"; union["widowed_at"]=at; self.put(up,union); source_refs.append(up)
        for sid,sp in list(fidx.get("successions",{}).items()):
            succession=_deepcopy(self.read(sp))
            if str(succession.get("current_holder_id",""))!=person_ref:
                continue
            replacement=None
            for candidate in succession.get("candidate_order",[]):
                ref=str(candidate.get("person_id",""))
                if not ref or ref==person_ref: continue
                try: self._exact_person(ref); replacement=ref; break
                except ValueError: continue
            if replacement:
                succession["current_holder_id"]=replacement; succession["last_changed_at"]=at; succession["cause"]="death of prior holder"; self.put(sp,succession); source_refs.append(sp)
        if person_ref in fidx.get("person_index",{}):
            eid="family.death."+hashlib.sha256((person_ref+":"+at).encode()).hexdigest()[:12]; ep=f"state/family/events/{eid}.json"; event={"schema":"family-event.v1","event_id":eid,"event_type":"death_family_settlement","occurred_at":at,"authority":True,"subject_refs":[person_ref],"source_refs":source_refs}; self.put(ep,event); fidx.setdefault("events",{})[eid]=ep; fidx.setdefault("counts",{})["events"]=len(fidx["events"]); pi=fidx.setdefault("person_index",{}).setdefault(person_ref,{}); pi.setdefault("events",[]).append(eid); self.put(family_index_path,fidx)
        hist=_deepcopy(self.read("state/history/events/index.json")); event_id="death_"+hashlib.sha256((person_ref+":"+at+":"+reason).encode()).hexdigest()[:16]; hist.setdefault("events",[]).append({"event_id":event_id,"kind":"named_person_death","at":at,"person_ref":person_ref,"reason":reason}); self.put("state/history/events/index.json",hist)

    def _validate_command_semantics(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> None:
        # Chronology is server-owned. Requests bind to the exact world instant
        # represented by expected_revision; callers cannot forge future/past events.
        now = self._world_time()
        if CampaignTime.parse(command.submitted_at) != now:
            raise ValueError("submitted_at must equal authoritative campaign world time")
        t = command.command_type
        if t not in COMMAND_TYPES:
            raise ValueError("unsupported Sword semantic command: %s" % t)

        if t == "scene_consequence":
            require_text(payload, "summary", max_length=4000)
        if t == "travel":
            self._location_record(require_text(payload, "destination_ref"))
            require_text(payload, "mode", allowed={"foot","horse"}, default="foot")
        if t == "health_injury":
            require_text(payload, "severity", allowed={"minor","moderate","severe","critical"}, default="minor")
        if t in {"recruitment", "population_transfer", "formation_create"}:
            require_int(payload, "personnel", minimum=1, maximum=1_000_000)
            state = self._state_key(require_text(payload, "state"))
            pop = self.read(f"state/population/{state}.json")
            if t in {"recruitment","population_transfer"}:
                source = require_text(payload, "source_stratum", default="agricultural")
                if source not in pop.get("strata", {}): raise ValueError("unknown population source stratum")
            if t == "population_transfer":
                dest = require_text(payload, "destination_stratum", default="active_military")
                if dest not in pop.get("strata", {}): raise ValueError("unknown population destination stratum")
            if t in {"recruitment","formation_create"}:
                force = self.read(f"state/forces/state-{state}.json")
                role = require_text(payload, "role", default="line_infantry")
                if role not in force.get("available_by_role", {}): raise ValueError("unknown force role")
        if t == "person_materialize":
            self._state_key(require_text(payload, "state", default="qin")); require_text(payload, "person_ref")
            if self.read("state/index/owner-index-gold.json").get("owners",{}).get(str(payload["person_ref"])):
                raise ValueError("person_ref already exists")
        if t == "formation_split":
            require_int(payload, "personnel", minimum=1, maximum=1_000_000); require_text(payload, "new_formation_ref")
        if t == "formation_reconstitute":
            require_int(payload, "target_personnel", minimum=1, maximum=1_000_000)
            if "equipment_units" in payload: require_int(payload, "equipment_units", minimum=0, maximum=1_000_000)
        if t in {"individual_training", "formation_train", "cohort_training"}:
            require_int(payload, "hours", minimum=1, maximum=12)
        if t == "health_recovery":
            require_int(payload, "hours", minimum=1, maximum=168)
        if t == "advance_time":
            if ("hours" in payload) == ("target_time" in payload):
                raise ValueError("advance_time requires exactly one of hours or target_time")
            if "hours" in payload: require_int(payload, "hours", minimum=1, maximum=876_000)
            if "target_time" in payload:
                target = CampaignTime.parse(require_text(payload, "target_time", max_length=64)); seconds = now.seconds_until(target)
                if seconds < 0 or seconds > 100 * 366 * 86400: raise ValueError("advance_time target must be within the next 100 years")
        if t == "relationship_change":
            require_text(payload, "target_ref"); delta = require_int(payload, "delta", minimum=-20, maximum=20)
            if delta == 0: raise ValueError("relationship delta must be non-zero")
            self._exact_person(str(payload.get("source_ref", command.actor_id))); self._exact_person(str(payload["target_ref"]))
            require_text(payload, "kind", allowed={"trust","affection","respect","fear","resentment","loyalty"}, default="trust")
        if t in {"market_purchase","market_sell"}:
            require_int(payload, "quantity", minimum=1, maximum=10_000); require_text(payload, "item_key")
        if t in {"economy_transfer", "enlisted_service_pay"}:
            require_int(payload, "amount_silver", minimum=1, maximum=1_000_000_000, default=7 if t == "enlisted_service_pay" else None)
            if t == "economy_transfer": require_text(payload, "direction", allowed={"player_to_state", "state_to_player"})
        if t == "resupply":
            values=[]
            for key in ("food_kg","fodder_kg","war_arrows"):
                if key in payload: values.append(require_int(payload,key,minimum=0,maximum=1_000_000_000))
            if not values or not any(values): raise ValueError("resupply must request at least one positive material quantity")
        if t == "formation_move":
            self._location_record(require_text(payload,"destination_ref"))
        if t in {"command_assign","command_transfer","formation_assign","force_assignment"}:
            if payload.get("commander_ref") is not None: self._exact_person(str(payload["commander_ref"]))
        if t == "formation_doctrine_set":
            behavior=payload.get("doctrine_behavior",{})
            if not isinstance(behavior,dict): raise ValueError("doctrine_behavior must be an object")
            if "reserve_commitment" in behavior: require_int(behavior,"reserve_commitment",minimum=0,maximum=100)
            if "withdrawal_threshold" in behavior: require_int(behavior,"withdrawal_threshold",minimum=0,maximum=100)
            if "casualty_tolerance" in behavior: require_text(behavior,"casualty_tolerance",allowed={"low","moderate","high","extreme"})
        if t == "battle_resolve":
            attackers=require_list(payload,"attacker_formation_refs",minimum=1,maximum=128); defenders=require_list(payload,"defender_formation_refs",minimum=1,maximum=128)
            if set(map(str,attackers)) & set(map(str,defenders)): raise ValueError("a formation cannot fight on both sides")
        if t == "personal_combat":
            self._exact_person(require_text(payload,"opponent_ref")); require_int(payload,"duration_minutes",minimum=5,maximum=240,default=60)
        if t == "operation_create":
            require_text(payload,"operation_ref"); require_list(payload,"formation_refs",minimum=1,maximum=128); self._location_record(require_text(payload,"location_ref"))
        if t == "operation_transition":
            require_text(payload,"operation_ref"); require_text(payload,"status",allowed={"planned","mobilizing","active","engaged","occupied","completed","cancelled"})
        if t == "information_create":
            require_text(payload,"information_ref"); require_text(payload,"claim",default=str(payload.get("fact","")),max_length=4000); require_list(payload,"knowers",minimum=1,maximum=128)
            for ref in payload.get("knowers",[]): self._exact_person(str(ref))
        if t == "information_deliver":
            self._exact_person(require_text(payload,"target_ref",default=self.PLAYER_ACTOR)); require_text(payload,"information_ref")
        if t == "state_action":
            action=require_text(payload,"action",allowed={"strategic_goal","appointment","enemy_action","record_threat"},default="strategic_goal")
            self._state_key(require_text(payload,"state",default="qin"))
            if action=="appointment": self._exact_person(require_text(payload,"person_ref")); require_text(payload,"office")
            if action in {"enemy_action","record_threat"}: require_int(payload,"severity",minimum=0,maximum=100,default=50); self._state_key(require_text(payload,"source_state",default="zhao"))
        if t == "fortification_materialize":
            require_int(payload,"integrity",minimum=1,maximum=100,default=100); require_int(payload,"food_kg",minimum=0,maximum=1_000_000_000,default=100000); require_int(payload,"fodder_kg",minimum=0,maximum=1_000_000_000,default=0)
            self._location_record(require_text(payload,"location_ref")); require_list(payload,"garrison_formation_refs",minimum=1,maximum=64)
            if payload.get("commander_ref"): self._exact_person(str(payload["commander_ref"]))
        if t == "siege_start":
            require_text(payload,"siege_ref"); require_text(payload,"fortification_ref"); require_list(payload,"attacker_formation_refs",minimum=1,maximum=128)
        if t == "siege_action":
            require_text(payload,"siege_ref"); action=require_text(payload,"action",allowed={"blockade","repair","assault","withdraw","settle","relief"})
            if action=="blockade": require_int(payload,"days",minimum=1,maximum=30,default=7)
            if action=="repair": require_int(payload,"points",minimum=1,maximum=20,default=5)
            if "damage" in payload: raise ValueError("siege assault damage is runtime-derived and may not be caller supplied")
        if t == "territorial_consequence":
            self._location_record(require_text(payload,"location_ref")); controller=require_text(payload,"controller")
            if not controller.startswith("state_"): raise ValueError("territorial controller must be a recognized state authority")
            self._state_key(controller)
        if t == "family_event":
            kind=require_text(payload,"kind",allowed={"proposal","engagement","marriage","pregnancy","birth","death","widowhood","succession_review"})
            if kind in {"proposal","marriage"}: self._exact_person(require_text(payload,"person_ref")); self._exact_person(require_text(payload,"partner_ref"))
            elif kind=="engagement": require_text(payload,"proposal_ref")
            elif kind in {"pregnancy","birth"}:
                self._exact_person(require_text(payload,"mother_ref")); self._exact_person(require_text(payload,"father_ref"))
                if kind=="birth": require_text(payload,"child_ref")
            elif kind in {"death","widowhood"}: self._exact_person(require_text(payload,"person_ref"),active=(kind=="death"))
        if t in {"equipment_equip","equipment_unequip","equipment_transfer","equipment_drop","equipment_consume"}:
            item_id=require_text(payload,"item_key"); self._item_record(item_id); require_int(payload,"quantity",minimum=1,maximum=10_000,default=1)
            if t=="equipment_transfer": self._exact_person(require_text(payload,"target_ref"))
        if t == "reputation_event":
            self._exact_person(require_text(payload,"subject_ref")); delta=require_int(payload,"delta",minimum=-20,maximum=20)
            if delta==0: raise ValueError("reputation delta must be non-zero")
            audience=require_text(payload,"audience_ref")
            if audience.startswith("state_"): self._state_key(audience)
            elif audience.startswith("char_"): self._exact_person(audience)
            else: self.owner(audience)
        if t == "career_event":
            self._exact_person(require_text(payload,"person_ref")); kind=require_text(payload,"kind",allowed={"qualification","promotion","appointment","merit"})
            if kind=="merit": require_int(payload,"merit",minimum=1,maximum=1000)
            if kind=="qualification": require_text(payload,"qualification_ref")
            if kind=="promotion": require_text(payload,"grade",allowed={f"C{i}" for i in range(1,11)})
            if kind=="appointment": require_text(payload,"office")
        if t == "mercenary_contract":
            merc_ref=require_text(payload,"mercenary_ref"); _,merc=self.owner(merc_ref)
            if "mercenary" not in str(merc.get("schema","")): raise ValueError("mercenary_ref is not a mercenary company")
            action=require_text(payload,"action",allowed={"offer","accept","pay","deploy","breach","renew","complete"})
            if action in {"offer","accept","pay","renew"}: require_int(payload,"amount_silver",minimum=1,maximum=100_000_000)
            if action=="offer": require_int(payload,"term_days",minimum=1,maximum=3650,default=90)
            else: require_text(payload,"contract_ref")
            if action=="deploy": self._location_record(require_text(payload,"location_ref"))
        if t == "institution_project":
            require_text(payload,"institution_ref"); require_int(payload,"duration_hours",minimum=1,maximum=8760,default=168); require_text(payload,"project_ref",default="project_"+command.digest[:8]); require_int(payload,"magnitude",minimum=1,maximum=1_000_000,default=1)
        if t == "project_resolve":
            require_text(payload,"institution_ref"); require_text(payload,"project_ref")


    def _find_route(self, origin: str, destination: str, *, mode: Optional[str] = None) -> Mapping[str, Any]:
        routes = self.read("game/data/world/routes.json").get("routes", [])
        found: Optional[Mapping[str, Any]] = None
        for route in routes:
            a, b = route.get("a", route.get("from")), route.get("b", route.get("to"))
            if {a, b} == {origin, destination}:
                found = route
                break
        # Tang Manor scene venues sit inside Kanyou. Local access is bounded and
        # deliberately does not support formation movement through household corridors.
        if found is None and origin.startswith("loc_tang_manor_") and destination == "loc_kanyou":
            found = {"ref":"route_local_tang_manor_kanyou","a":origin,"b":destination,"hours":1,"modes":["foot","horse"]}
        if found is None and destination.startswith("loc_tang_manor_") and origin == "loc_kanyou":
            found = {"ref":"route_local_tang_manor_kanyou","a":origin,"b":destination,"hours":1,"modes":["foot","horse"]}
        if found is None:
            raise ValueError("no saved strategic route between %s and %s" % (origin, destination))
        modes = {str(x) for x in found.get("modes", [])}
        if mode is not None and mode not in modes:
            raise ValueError(f"saved route does not permit {mode} movement")
        return found

    def _advance_runtime(self, target_text: str) -> Dict[str, int]:
        runtime_path = "state/runtime.json"
        rt = _deepcopy(self.read(runtime_path))
        current = CampaignTime.parse(rt["world_time"])
        target = CampaignTime.parse(target_text)
        if target < current:
            raise ValueError("time may not move backward")
        events = list(rt.get("events", []))
        hosts = rt.get("hosts", {})
        woken = 0
        processed = 0
        # Only due queue is inspected. Owners are loaded only for due hosts.
        for event in sorted(events, key=lambda e: (CampaignTime.parse(e["due_at"]), e.get("priority", 100), e["event_id"])):
            due = CampaignTime.parse(event["due_at"])
            if due > target:
                continue
            host = hosts[event["target_host"]]
            recurrence = int(host.get("recurrence_seconds", 0))
            if recurrence <= 0:
                occurrences = 1
                successor = None
            else:
                delta = due.seconds_until(target)
                occurrences = int(delta // recurrence) + 1
                successor = due.add_seconds(occurrences * recurrence)
            woken += 1
            processed += occurrences
            kind = host.get("kind")
            if kind == "state":
                self._autonomy_state(host, occurrences, target_text)
            elif kind == "population":
                self._autonomy_population(host, occurrences, target_text)
            elif kind == "house":
                self._autonomy_house(host, occurrences, target_text)
            elif kind == "institution":
                self._autonomy_institution(host, occurrences, target_text)
            elif kind == "faction":
                self._autonomy_faction(host, occurrences, target_text)
            elif kind == "mercenary":
                self._autonomy_mercenary(host, occurrences, target_text)
            elif kind == "person":
                self._autonomy_person(host, occurrences, target_text)
            elif kind == "sword_manor":
                self._autonomy_manor(host, occurrences, target_text)
            host["resolved_through"] = target_text
            if successor is None:
                host["safe_through"] = target_text
                host["next_due"] = None
                event["due_at"] = "9999-BCE-01-01T00:00:00+08:00"
            else:
                host["next_due"] = successor.__str__()
                # Proven safe-horizon rule: safe through the instant before the known successor.
                host["safe_through"] = successor.add_seconds(-1).__str__()
                event["due_at"] = successor.__str__()
        rt["world_time"] = target_text
        metrics = rt.setdefault("metrics", {})
        metrics["hosts_woken"] = int(metrics.get("hosts_woken", 0)) + woken
        metrics["events_processed"] = int(metrics.get("events_processed", 0)) + processed
        for key in ("global_person_scans","global_faction_scans","global_force_scans","global_house_scans"):
            metrics[key] = 0
        self.put(runtime_path, rt)
        return {"hosts_woken": woken, "events_processed": processed}

    def _autonomy_person(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        person_ref=str(host["owner_ref"]); person_path,person0=self._exact_person(person_ref,active=False); person=_deepcopy(person0); life=str(person.get("life_status",person.get("status","active"))).lower()
        if life in {"dead","deceased"}:
            person.setdefault("runtime",{})["last_life_course_review_at"]=at; self.put(person_path,person); return
        first_due=CampaignTime.parse(str(host.get("next_due",at))); recurrence=max(1,int(host.get("recurrence_seconds",31536000))); training=self.read("game/data/mechanics/training.json"); world_seed=str(self.read("state/meta.json").get("world_seed","sword")); reviews=0
        for i in range(max(0,int(occurrences))):
            review=first_due.add_seconds(i*recurrence)
            if review>CampaignTime.parse(at): break
            age=age_years(person,review); person["life_course_age_index"]=age; person.setdefault("runtime",{})["last_life_course_review_at"]=str(review); person["runtime"]["completed_life_course_reviews"]=int(person["runtime"].get("completed_life_course_reviews",0))+1; reviews+=1
            # Standing activity contracts are evidence of opportunity, but explicit
            # "not automatic progress" clauses remain binding. The player never
            # receives autonomous training from a time skip.
            contract=person.get("activity_contract") if isinstance(person.get("activity_contract"),dict) else None
            if person_ref!=self.PLAYER_ACTOR and contract and "not automatic progress" not in str(contract.get("growth_rule","")).lower() and self._person_health(person) in {"healthy","fit","stable"}:
                focus_text=str(contract.get("focus","")); focus=next((part.strip() for part in focus_text.split(",") if part.strip() in person.get("skills",{})),None)
                if focus:
                    development=settle_skill_training(person,focus,48,review,training); person.setdefault("autonomous_development_history",[]).append({"at":str(review),"focus":focus,"hours":48,"development":development}); person["autonomous_development_history"]=person["autonomous_development_history"][-12:]
            # Deterministic annual mortality. Named/canon/player status grants no
            # immunity; age and active injury change the annual hazard.
            if age<35: bp=5
            elif age<45: bp=15
            elif age<55: bp=50
            elif age<65: bp=150
            elif age<75: bp=400
            elif age<85: bp=1000
            else: bp=2500
            if self._person_health(person) not in {"healthy","fit","stable"}: bp=min(9000,int(bp*2.5)+100)
            material=f"{world_seed}|person-life|{person_ref}|{review}"; roll=int(hashlib.sha256(material.encode()).hexdigest()[:8],16)%10000
            if roll<bp:
                self._settle_person_death(person_ref,person_path,person,str(review),"deterministic life-course mortality"); return
        if reviews:
            self.put(person_path,person)

    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        owner_ref = str(host["owner_ref"])
        state = self._state_key(owner_ref)
        sp = f"state/states/{state}.json"
        state_doc = _deepcopy(self.read(sp))
        net = int(state_doc.get("normal_monthly_revenue_silver",0)) - int(state_doc.get("normal_monthly_expense_silver",0))
        state_doc["treasury_silver"] = max(0, int(state_doc.get("treasury_silver",0)) + net * occurrences)
        state_doc["last_review"] = at
        threats=state_doc.get("known_threats",{})
        def threat_severity(value):
            if isinstance(value,dict): return int(value.get("severity",0))
            return int(_fixed(value,0))
        max_threat=max((threat_severity(v) for v in threats.values()),default=0)
        posture="fortify_and_reinforce" if max_threat>=70 else ("heightened_border_defense" if max_threat>=35 else "routine_readiness")
        state_doc["autonomous_posture"]=posture
        state_doc.setdefault("autonomous_actions",[]).append({"at":at,"posture":posture,"basis":"known_threats_and_resources"})
        if len(state_doc["autonomous_actions"])>12: del state_doc["autonomous_actions"][:-12]
        self.put(sp, state_doc)
        blueprints = self.read("game/data/mil/autonomy-blueprints.json").get("states",{}).get(state,[])
        force_path = f"state/forces/state-{state}.json"
        force = _deepcopy(self.read(force_path))
        # Replacement recruiting is bounded by the exact recruitment office, treasury and civilian population.
        authorized=int(force.get("authorized_strength",force.get("headcount",0))); shortage=max(0,authorized-int(force.get("headcount",0)))
        if shortage:
            inst=self.read(f"state/institutions/inst_{state}_recruitment_office.json"); capacity=int(inst.get("capacity",0))*occurrences
            pp=f"state/population/{state}.json"; pop=_deepcopy(self.read(pp)); available=max(0,int(pop["strata"].get("agricultural",0)))
            econ=self.read("game/data/mechanics/economy-gold.json"); unit_cost=int(econ.get("military_finance",{}).get("recruitment_and_basic_issue_cost_silver_per_person",12))
            affordable=int(state_doc.get("treasury_silver",0))//max(1,unit_cost)
            recruits=min(shortage,capacity,available,affordable)
            if recruits:
                pop["strata"]["agricultural"]-=recruits; pop["strata"]["active_military"]+=recruits
                force["headcount"]+=recruits; force["available_by_role"]["line_infantry"]=int(force["available_by_role"].get("line_infantry",0))+recruits; source_loc=str(force.get("source_location_ref") or self.read(f"state/depots/{state}.json").get("location_ref")); local=self._force_location_pool(force,source_loc); local["line_infantry"]=int(local.get("line_infantry",0))+recruits
                state_doc["treasury_silver"]-=recruits*unit_cost
                self.put(pp,pop); self.put(sp,state_doc)
        owner_index=self.read("state/index/owner-index-gold.json").get("owners",{})
        for bp in blueprints:
            ref = f"formation_{state}_{bp['key']}"
            existing = owner_index.get(ref)
            role = bp["role"]; target_n = int(bp["personnel"])
            if existing:
                formation=_deepcopy(self.read(existing))
                # Reconstitution uses the same conserved force pool as explicit player/state commands.
                need=max(0,target_n-int(formation.get("personnel",0))); formation_loc=str(formation.get("location_ref")); local=self._force_location_pool(force,formation_loc)
                take=min(need,int(force.get("available_by_role",{}).get(role,0)),int(local.get(role,0)))
                if take:
                    self._take_force_personnel(force,role,take,formation_loc)
                    old_n=int(formation.get("personnel",0)); formation["personnel"]+=take
                    formation.setdefault("composition",{})[role]=int(formation["personnel"]); new_n=int(formation["personnel"]); incoming={"readiness":35,"morale":60,"cohesion":25,"training_progress":10,"fatigue":0}
                    for field,base in incoming.items(): formation[field]=_clamp(int(round((int(formation.get(field,base))*old_n+base*take)/max(1,new_n))))
                    force["allocated_to_formations"][ref]={"personnel":int(formation["personnel"]),"role":role}
                formation["training_progress"]=_clamp(int(formation.get("training_progress",0))+min(20,occurrences*2))
                formation["cohesion"]=_clamp(int(formation.get("cohesion",50))+min(10,occurrences))
                formation["readiness"]=_clamp(int(formation.get("readiness",50))+min(10,occurrences))
                formation["fatigue"]=_clamp(int(formation.get("fatigue",0))-min(10,occurrences))
                if max_threat>=35:
                    formation["mobilized"]=True; formation["status"]="mobilized"
                depot_p=f"state/depots/{state}.json"; depot=_deepcopy(self.read(depot_p))
                desired_food=int(formation["personnel"])*5; missing=max(0,desired_food-int(formation.get("logistics",{}).get("food_kg",0))); grain=min(missing,int(depot["stocks"].get("grain_kg",0)))
                if grain:
                    depot["stocks"]["grain_kg"]-=grain; formation["logistics"]["food_kg"]+=grain; self.put(depot_p,depot)
                self.put(existing,formation)
                continue
            n=target_n; source_loc=str(force.get("source_location_ref") or self.read(f"state/depots/{state}.json").get("location_ref")); local=self._force_location_pool(force,source_loc)
            if int(force.get("available_by_role",{}).get(role,0)) < n or int(local.get(role,0)) < n:
                continue
            self._take_force_personnel(force,role,n,source_loc)
            force.setdefault("allocated_to_formations",{})[ref] = {"personnel": n, "role": role}
            fpath = f"state/formations/{state}-{bp['key'].replace('_','-')}.json"
            formation = {
                "schema":"sword-formation","formation_ref":ref,
                "name":f"{state.upper()} {bp['key'].replace('_',' ').title()}",
                "owner_force_ref":f"force_state_{state}","administrative_owner":f"state_{state}",
                "command_authority":f"state_{state}","commander_ref":bp.get("commander_ref"),
                "personnel":n,"composition":{role:n},"location_ref":source_loc,
                "doctrine_ref":bp.get("doctrine_ref"),"training_ref":bp.get("training_ref"),
                "doctrine_behavior":{"casualty_tolerance":"moderate","reserve_commitment":50,"withdrawal_threshold":30},
                "training_progress":15,"readiness":65,"morale":70,"cohesion":65,"fatigue":0,
                "equipment_completeness":"0.9","experience":"formed","mobilized":max_threat>=35,"status":"mobilized" if max_threat>=35 else "forming",
                "logistics":{"food_kg":n*5,"fodder_kg":n*2 if role=="cavalry" else 0,"war_arrows":n*10 if "missile" in role else 0},
                "mounts":{}
            }
            if role == "cavalry":
                mp=f"state/mounts/{state}.json"; mounts=_deepcopy(self.read(mp)); count=min(n,int(mounts.get("types",{}).get("horse_war_military",0)))
                if count:
                    mounts.setdefault("allocated_to_formations",{})[ref]={"horse_war_military":count}
                    formation["mounts"]={"horse_war_military":count}
                    self.put(mp,mounts)
            depot_p=f"state/depots/{state}.json"; depot=_deepcopy(self.read(depot_p))
            for key,needed in (("grain_kg",n*5),("fodder_kg",formation["logistics"]["fodder_kg"])):
                take=min(int(depot.get("stocks",{}).get(key,0)),needed)
                depot["stocks"][key]-=take
                if key=="grain_kg": formation["logistics"]["food_kg"]=take
                else: formation["logistics"]["fodder_kg"]=take
            self.put(depot_p,depot)
            if formation.get("commander_ref"):
                cp,commander=self._validate_person_location_for_formation(str(formation["commander_ref"]),formation); self.put(cp,commander); self._assign_commander_index(str(formation["commander_ref"]),ref)
            self.put(fpath,formation); self._register_owner(ref,fpath)
        self.put(force_path,force)
        # A material known threat creates one bounded strategic response operation, not a global war tick.
        if max_threat>=35:
            op_ref=f"operation_auto_{state}_border_response"
            op_idx=_deepcopy(self.read("state/operations/index.json"))
            if op_ref not in op_idx.get("operations",{}):
                op_path=f"state/operations/{op_ref}.json"
                refs=[f"formation_{state}_{bp['key']}" for bp in blueprints[:2] if self.read("state/index/owner-index-gold.json").get("owners",{}).get(f"formation_{state}_{bp['key']}")]
                op={"schema":"sword-operation","owner_id":op_ref,"operation_ref":op_ref,"objective":"respond to known border threat","status":"active","formation_refs":refs,"location_ref":self.read(f"state/depots/{state}.json").get("location_ref"),"created_at":at,"autonomous":True}
                self.put(op_path,op); op_idx.setdefault("operations",{})[op_ref]=op_path; self.put("state/operations/index.json",op_idx); self._register_owner(op_ref,op_path)

    def _autonomy_population(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        state=self._state_key(str(host["owner_ref"]))
        p=f"state/population/{state}.json"; pop=_deepcopy(self.read(p))
        total=int(pop["population_total"]); dem=pop.get("demography",{})
        rate=(_fixed(dem.get("birth_rate_per_thousand"))-_fixed(dem.get("death_rate_per_thousand")))/1000.0
        # closed-form annual aggregate. Integer result is deterministic.
        new_total=max(1,int(round(total*((1.0+rate)**occurrences))))
        delta=new_total-total
        if delta:
            strata=pop["strata"]
            target_key="dependents_children_elderly" if delta>0 else "agricultural"
            strata[target_key]=max(0,int(strata.get(target_key,0))+delta)
        pop["population_total"]=sum(int(v) for v in pop["strata"].values())
        dem["closes"]=int(dem.get("closes",0))+occurrences; dem["last_close"]=at
        self.put(p,pop)

    def _autonomy_house(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        p=self.owner_path(str(host["owner_ref"])); house=_deepcopy(self.read(p)); cohort=house.get("lineage_cohort",{})
        adults=int(cohort.get("adults",0)); children=int(cohort.get("children",0)); elders=int(cohort.get("elders",0))
        births=max(0,(adults//2)*occurrences//3); mature=min(children, occurrences); deaths=min(elders, occurrences//2)
        cohort["children"]=children+births-mature; cohort["adults"]=max(0,adults+mature); cohort["elders"]=max(0,elders-deaths)
        cohort["marriages"]=int(cohort.get("marriages",0))+max(0,mature//2); cohort["last_close"]=at
        house["last_review"]=at
        if house.get("treasury_ref")=="treasury_house_tang":
            tp="state/treasury/treasury-house-tang.json"; treasury=_deepcopy(self.read(tp))
            # House host reviews are quarterly; realize exact saved monthly flows.
            months=max(1,int(round(int(host.get("recurrence_seconds",7776000))*occurrences/2592000)))
            flows=treasury.get("stable_monthly_flows",{})
            treasury["silver"] += (int(flows.get("revenue_silver",0))-int(flows.get("expense_silver",0)))*months
            treasury["food_kg"] += int(flows.get("food_net_change_kg",0))*months
            treasury["fodder_kg"] += int(flows.get("fodder_net_change_kg",0))*months
            treasury.setdefault("runtime",{})["completed_monthly_closes"]=int(treasury.get("runtime",{}).get("completed_monthly_closes",0))+months
            treasury["runtime"]["last_monthly_close_at"]=at
            self.put(tp,treasury)
        else:
            house["treasury_silver"]=max(0,int(house.get("treasury_silver",0))+occurrences*1000)
        force_ref=house.get("military_force_ref")
        if isinstance(force_ref,str):
            fp=self.owner_path(force_ref); force=_deepcopy(self.read(fp)); authorized=int(force.get("authorized_strength",force.get("headcount",0)))
            shortage=max(0,authorized-int(force.get("headcount",0)))
            if shortage:
                state=self._state_key(house.get("state")); pp=f"state/population/{state}.json"; pop=_deepcopy(self.read(pp)); source="household_and_service"; available=int(pop["strata"].get(source,0)); recruits=min(shortage,available,max(1,25*occurrences))
                if recruits:
                    pop["strata"][source]-=recruits; pop["strata"]["private_household_military"]+=recruits; force["headcount"]+=recruits
                    role="heavy_cavalry" if force_ref=="force_house_tang" else "household_retainer"; force["available_by_role"][role]=int(force["available_by_role"].get(role,0))+recruits; self.put(pp,pop)
            formation_refs=["formation_tang_champions_first","formation_tang_champions_second"] if force_ref=="force_house_tang" else [f"formation_{house['house_ref']}_guard"]
            idx=self.read("state/index/owner-index-gold.json").get("owners",{})
            for fr in formation_refs:
                fpath=idx.get(fr)
                if not fpath: continue
                formation=_deepcopy(self.read(fpath)); target=50 if fr.startswith("formation_tang_champions_") else authorized; need=max(0,target-int(formation.get("personnel",0))); role=next(iter(formation.get("composition",{})),"household_retainer"); take=min(need,int(force["available_by_role"].get(role,0)))
                if take:
                    force["available_by_role"][role]-=take; formation["personnel"]+=take; formation["composition"][role]=formation["personnel"]; force["allocated_to_formations"][fr]={"personnel":formation["personnel"],"role":role}
                formation["readiness"]=_clamp(int(formation.get("readiness",50))+min(8,occurrences)); formation["cohesion"]=_clamp(int(formation.get("cohesion",50))+min(5,occurrences)); formation["training_progress"]=_clamp(int(formation.get("training_progress",20))+min(10,occurrences)); self.put(fpath,formation)
            self.put(fp,force)
        projects=house.setdefault("projects",[])
        threat=_fixed(house.get("threat_level","0"))
        action="guard_readiness" if threat>=0.5 else "estate_and_retainer_review"
        projects.append({"kind":action,"status":"active","at":at,"source":"autonomous_house_policy"})
        # compact repetitive housekeeping rather than append unbounded project history
        if len(projects)>8: del projects[:-8]
        self.put(p,house)

    def _autonomy_institution(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        if str(host.get("owner_ref")) == "institution_sword_manor":
            self._autonomy_manor(host, occurrences, at)
            return
        p=self.owner_path(str(host["owner_ref"])); inst=_deepcopy(self.read(p)); inst["last_review"]=at
        kind=inst.get("kind"); state=self._state_key(inst.get("state"))
        if kind=="horse_administration":
            mp=f"state/mounts/{state}.json"; mounts=_deepcopy(self.read(mp)); recovering=int(mounts["health"].get("recovering",0)); recover=min(recovering,int(inst.get("capacity",500))*occurrences)
            mounts["health"]["recovering"]-=recover; mounts["health"]["fit"]+=recover; self.put(mp,mounts)
        elif kind=="granary_depot_office":
            dp=f"state/depots/{state}.json"; depot=_deepcopy(self.read(dp)); cap=max(1,int(inst.get("capacity",1000))); depot["stocks"]["grain_kg"]+=cap*occurrences; self.put(dp,depot)
        inst["backlog"]=max(0,int(inst.get("backlog",0))-int(inst.get("capacity",0))*occurrences)
        self.put(p,inst)

    def _autonomy_faction(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        p=self.owner_path(str(host["owner_ref"])); doc=_deepcopy(self.read(p)); doc["last_review"]=at
        pressure=_clamp(int(doc.get("pressure",0))+min(20,occurrences*2)); doc["pressure"]=pressure
        commitments=doc.setdefault("commitments",[])
        if pressure>=40 and doc.get("goals"):
            commitments.append({"at":at,"action":"advance_goal","goal":doc["goals"][0],"basis":"resources_relationships_and_pressure"}); doc["pressure"]=max(0,pressure-20)
        if len(commitments)>8: del commitments[:-8]
        self.put(p,doc)

    def _autonomy_manor(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        p="state/forces/sword-manor.json"; doc=_deepcopy(self.read(p)); doc["cohort_training_closes"]=int(doc.get("cohort_training_closes",0))+occurrences; doc["last_review"]=at; self.put(p,doc)

    def _autonomy_mercenary(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        owner_ref=str(host["owner_ref"]); path=self.owner_path(owner_ref); doc=_deepcopy(self.read(path)); runtime=doc.setdefault("runtime",{}); runtime["completed_quarterly_reviews"]=int(runtime.get("completed_quarterly_reviews",0))+occurrences; runtime["last_settled_at"]=at
        if "status" in doc and doc.get("status") not in {"destroyed","dissolved"}:
            contracts=doc.get("contracts",[]); doc["status"]="contracted" if contracts else "available"
        self.put(path,doc)

    def _battle(
        self,
        command: CommandEnvelope,
        payload: Mapping[str, Any],
        *,
        context: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        attackers = [str(x) for x in payload.get("attacker_formation_refs", [])]
        defenders = [str(x) for x in payload.get("defender_formation_refs", [])]
        if not attackers or not defenders:
            raise ValueError("battle requires saved attacker and defender formations")
        all_refs = attackers + defenders
        if len(set(all_refs)) != len(all_refs):
            raise ValueError("a formation may not appear on both battle sides")

        formations: Dict[str, tuple[str, Dict[str, Any]]] = {}
        for ref in all_refs:
            path, formation = self._load_formation(ref)
            formations[ref] = (path, _deepcopy(formation))

        locations = {str(formations[ref][1].get("location_ref")) for ref in all_refs}
        if len(locations) != 1:
            raise ValueError("battle rejected: formations are not co-located on one battlefield")
        battlefield = next(iter(locations))
        location = self._location_record(battlefield)

        if context is None:
            operation_ref = str(payload.get("operation_ref", ""))
            if not operation_ref:
                raise ValueError("field battle requires an active saved operation proving contact")
            op_path = self.read("state/operations/index.json").get("operations", {}).get(operation_ref)
            if not op_path:
                raise ValueError("unknown battle operation")
            operation = self.read(op_path)
            if operation.get("status") not in {"active", "engaged"}:
                raise ValueError("battle operation is not active")
            if operation.get("location_ref") != battlefield:
                raise ValueError("battle operation location does not match formation contact")
            if not set(all_refs).issubset(set(str(x) for x in operation.get("formation_refs", []))):
                raise ValueError("battle formations are not all participants in the saved operation")
            contact_proof = operation_ref
        else:
            if context.get("location_ref") != battlefield:
                raise ValueError("battle context location does not match exact formation contact")
            contact_proof = str(context.get("contact_ref", context.get("kind", "context")))

        terrain_kind = str(location.get("kind", "open"))
        admission: Dict[str, Dict[str, Any]] = {}
        commander_scores: Dict[str, float] = {}
        for ref in all_refs:
            _, formation = formations[ref]
            if not bool(formation.get("mobilized", False)):
                raise ValueError(f"battle rejected: {ref} is not mobilized")
            if int(formation.get("personnel", 0)) <= 0:
                raise ValueError(f"battle rejected: {ref} has no personnel")
            command_authority = str(formation.get("command_authority", ""))
            if not command_authority:
                raise ValueError(f"battle rejected: {ref} has no command authority")
            if command_authority != self.PLAYER_ACTOR:
                self.owner(command_authority)
            commander_ref = formation.get("commander_ref")
            if not commander_ref:
                raise ValueError(f"battle rejected: {ref} has no exact saved commander")
            commander_path, commander = self._validate_person_location_for_formation(str(commander_ref), formation)
            self.put(commander_path, commander)

            n = int(formation["personnel"])
            food_need = max(1, int(math.ceil(n * 0.5)))
            ranged = sum(
                int(count)
                for role, count in formation.get("composition", {}).items()
                if any(tag in str(role).lower() for tag in ("archer", "bow", "crossbow"))
            )
            arrow_need = ranged * 2
            logistics = formation.get("logistics", {})
            if int(logistics.get("food_kg", 0)) < food_need:
                raise ValueError(f"battle rejected: {ref} lacks field food for contact")
            if arrow_need and int(logistics.get("war_arrows", 0)) < arrow_need:
                raise ValueError(f"battle rejected: {ref} lacks ammunition for its ranged composition")
            if int(formation.get("fatigue", 0)) >= 95:
                raise ValueError(f"battle rejected: {ref} is too fatigued for deliberate engagement")

            caps = commander.get("capabilities", commander.get("skills", {}))
            command_score = 0.0
            if isinstance(caps, dict):
                for key in ("Formation Command", "Tactics", "Leadership", "Strategy", "Mass Combat"):
                    command_score += _fixed(caps.get(key, 0))
            commander_scores[ref] = command_score
            admission[ref] = {
                "food_need": food_need,
                "arrow_need": arrow_need,
                "ranged_personnel": ranged,
                "commander_ref": commander_ref,
                "commander_path": commander_path,
            }

        def terrain_role_factor(formation: Mapping[str, Any]) -> float:
            comp = formation.get("composition", {})
            total = max(1, sum(int(v) for v in comp.values()))
            weighted = 0.0
            for role, count in comp.items():
                r = str(role).lower()
                factor = 1.0
                if terrain_kind in {"pass", "fort", "fortress"}:
                    if "cavalry" in r or "chariot" in r:
                        factor *= 0.78
                    if any(x in r for x in ("infantry", "guard", "crossbow", "archer")):
                        factor *= 1.10
                    if "siege" in r or "engineer" in r:
                        factor *= 1.08
                elif terrain_kind in {"capital", "city", "town", "estate", "hall"}:
                    if "cavalry" in r or "chariot" in r:
                        factor *= 0.82
                    if any(x in r for x in ("infantry", "guard", "crossbow")):
                        factor *= 1.06
                else:
                    if "cavalry" in r or "chariot" in r:
                        factor *= 1.10
                weighted += int(count) * factor
            return weighted / total

        def doctrine_factor(formation: Mapping[str, Any]) -> tuple[float, float]:
            doctrine = formation.get("doctrine_behavior", {})
            reserve = _clamp(int(doctrine.get("reserve_commitment", 50)))
            power = 0.85 + 0.30 * (reserve / 100.0)
            casualty = 1.0
            tolerance = str(doctrine.get("casualty_tolerance", "moderate")).lower()
            if "low" in tolerance:
                power *= 0.96
                casualty *= 0.78
            elif "high" in tolerance:
                power *= 1.05
                casualty *= 1.18
            extraction = _clamp(int(doctrine.get("extraction_priority", 0)))
            if extraction >= 80:
                power *= 0.92
                casualty *= 0.80
            return power, casualty

        # Receipts are canonical JSON and intentionally forbid binary floating
        # point values. Keep battle factors as fixed-point basis points so the
        # diagnostic surface is exact, sortable, and receipt-safe.
        score_details: Dict[str, Dict[str, int]] = {}
        casualty_modifiers: Dict[str, float] = {}

        def side_score(refs: list[str]) -> float:
            score = 0.0
            for ref in refs:
                formation = formations[ref][1]
                n = int(formation["personnel"])
                readiness = int(formation.get("readiness", 50))
                morale = int(formation.get("morale", 50))
                cohesion = int(formation.get("cohesion", 50))
                fatigue = int(formation.get("fatigue", 0))
                training = int(formation.get("training_progress", 20))
                equipment = _pct(formation.get("equipment_completeness", "0"))
                logistics = formation.get("logistics", {})
                food_ratio = min(1.0, int(logistics.get("food_kg", 0)) / max(1, admission[ref]["food_need"] * 2))
                arrow_need = admission[ref]["arrow_need"]
                arrow_ratio = 1.0 if arrow_need == 0 else min(1.0, int(logistics.get("war_arrows", 0)) / max(1, arrow_need * 2))
                supply = 0.72 + 0.18 * food_ratio + 0.10 * arrow_ratio
                command_factor = 1.0 + min(commander_scores[ref], 500.0) / 2500.0
                role_factor = terrain_role_factor(formation)
                doctrine_power, casualty_modifier = doctrine_factor(formation)
                casualty_modifiers[ref] = casualty_modifier
                base = max(0.10, (readiness + morale + cohesion + training + max(0, 100 - fatigue)) / 500.0)
                quality = base * max(0.20, equipment) * supply * command_factor * role_factor * doctrine_power
                score_details[ref] = {
                    "scale": 10000,
                    "base": int(round(base * 10000)),
                    "equipment": int(round(equipment * 10000)),
                    "supply": int(round(supply * 10000)),
                    "command": int(round(command_factor * 10000)),
                    "terrain_role": int(round(role_factor * 10000)),
                    "doctrine": int(round(doctrine_power * 10000)),
                    "quality": int(round(quality * 10000)),
                }
                score += n * quality
            return max(1.0, score)

        a_score = side_score(attackers)
        d_score = side_score(defenders)
        seed = self._causal_seed(command, payload, "mass-battle")
        variance = ((seed % 2001) - 1000) / 100000.0
        attack_pressure = d_score / max(1.0, a_score); defense_pressure = a_score / max(1.0, d_score)
        a_rate = max(.01, min(.45, 0.035 * attack_pressure + variance))
        d_rate = max(.01, min(.45, 0.045 * defense_pressure - variance))
        if attack_pressure >= 5.0: a_rate = min(1.0, 0.60 + min(0.40, (attack_pressure - 5.0) * 0.10))
        if defense_pressure >= 5.0: d_rate = min(1.0, 0.60 + min(0.40, (defense_pressure - 5.0) * 0.10))
        if terrain_kind in {"pass", "fort", "fortress"}:
            d_rate *= 0.86

        killed: Dict[str, int] = {}
        material_losses: Dict[str, Dict[str, Any]] = {}
        named_person_outcomes: Dict[str, Dict[str, Any]] = {}
        represented = sum(int(formations[r][1]["personnel"]) for r in all_refs)
        battle_hours = max(1, min(12, 2 + int(math.log10(max(10, represented)))))
        battle_started = self._world_time(); battle_completed = battle_started.add_seconds(battle_hours * 3600)
        attacker_won = a_score >= d_score
        for refs, rate in ((attackers, a_rate), (defenders, d_rate)):
            for ref in refs:
                path, formation = formations[ref]
                before = int(formation["personnel"])
                adjusted_rate = rate * casualty_modifiers.get(ref, 1.0)
                loss = min(before, max(0, int(round(before * adjusted_rate))))
                survivor_comp, dead_comp = self._partition_counts(formation.get("composition", {}), loss, before)
                survivor_eq, lost_eq = self._partition_material(self._equipment_units(formation), loss, before)
                survivor_mounts, lost_mounts = self._partition_material(formation.get("mounts", {}), loss, before)
                formation["personnel"] = before - loss
                formation["composition"] = survivor_comp
                formation["mounts"] = survivor_mounts
                self._set_equipment_units(formation, survivor_eq)
                food_used = admission[ref]["food_need"]
                arrows_used = min(int(formation.get("logistics", {}).get("war_arrows", 0)), admission[ref]["ranged_personnel"] * 3)
                formation.setdefault("logistics", {})["food_kg"] = max(0, int(formation["logistics"].get("food_kg", 0)) - food_used)
                formation["logistics"]["war_arrows"] = max(0, int(formation["logistics"].get("war_arrows", 0)) - arrows_used)
                formation["fatigue"] = _clamp(int(formation.get("fatigue", 0)) + 15)
                formation["morale"] = _clamp(int(formation.get("morale", 50)) - (8 if loss else 0))
                formation["cohesion"] = _clamp(int(formation.get("cohesion", 50)) - 5)
                formation["status"] = "combat_effective" if formation["personnel"] > 0 else "destroyed"
                killed[ref] = loss
                material_losses[ref] = {
                    "equipment_units": lost_eq,
                    "mounts": lost_mounts,
                    "food_kg_consumed": food_used,
                    "war_arrows_consumed": arrows_used,
                    "composition_losses": dead_comp,
                }
                commander_ref = str(admission[ref]["commander_ref"]); commander_path = str(admission[ref]["commander_path"]); commander = _deepcopy(self.read(commander_path))
                casualty_fraction = loss / max(1, before); losing_side = (ref in attackers and not attacker_won) or (ref in defenders and attacker_won); roll = (self._causal_seed(command, payload, "commander:" + ref) % 10000) / 10000.0
                death_p = min(0.35, casualty_fraction * (0.32 if losing_side else 0.18)); capture_p = min(0.45, casualty_fraction * 0.55) if losing_side else 0.0; wound_p = min(0.85, 0.03 + casualty_fraction * 1.8)
                outcome = "unharmed"
                if roll < death_p:
                    outcome = "killed"; self._settle_person_death(commander_ref,commander_path,commander,str(battle_completed),"battle casualty"); commander=_deepcopy(self.read(commander_path)); formation["commander_ref"] = None; self._release_commander_index(commander_ref,ref)
                elif roll < death_p + capture_p:
                    outcome = "captured"; commander["custody_state"]={"status":"captured","captured_at":str(battle_completed),"battle_ref":"battle_"+command.digest[:16],"captured_by":"defender" if ref in attackers else "attacker"}; formation["commander_ref"] = None; self._release_commander_index(commander_ref,ref)
                elif roll < death_p + capture_p + wound_p:
                    outcome = "wounded"; self._set_person_health(commander,"injured"); commander["injury_state"]={"label":"battle wound","severity":"severe" if casualty_fraction>=0.20 else "moderate","inflicted_at":str(battle_completed),"minimum_recovery_hours":72 if casualty_fraction>=0.20 else 24,"recovered_hours":0,"active":True}; formation["commander_ref"] = None; self._release_commander_index(commander_ref,ref)
                named_person_outcomes[commander_ref]={"formation_ref":ref,"outcome":outcome,"roll_basis_points":int(round(roll*10000)),"casualty_fraction_basis_points":int(round(casualty_fraction*10000))}
                self.put(commander_path,commander)
                self.put(path, formation)

                force_ref = formation["owner_force_ref"]
                fp = self.owner_path(force_ref)
                force = _deepcopy(self.read(fp))
                alloc = force.get("allocated_to_formations", {}).get(ref)
                if isinstance(alloc, dict):
                    alloc["personnel"] = formation["personnel"]
                elif alloc is not None:
                    force["allocated_to_formations"][ref] = formation["personnel"]
                force["headcount"] -= loss
                self.put(fp, force)
                if force_ref.startswith("force_state_"):
                    state = force_ref.replace("force_state_", "")
                    pp = f"state/population/{state}.json"
                    pop = _deepcopy(self.read(pp))
                    pop["strata"]["active_military"] -= loss
                    pop["population_total"] -= loss
                    self.put(pp, pop)
                elif str(force.get("administrative_owner", "")).startswith("house_"):
                    house_ref = str(force["administrative_owner"])
                    hp = self.owner_path(house_ref)
                    house = self.read(hp)
                    state = self._state_key(house.get("state"))
                    pp = f"state/population/{state}.json"
                    pop = _deepcopy(self.read(pp))
                    pop["strata"]["private_household_military"] = max(0, int(pop["strata"].get("private_household_military", 0)) - loss)
                    pop["population_total"] -= loss
                    self.put(pp, pop)

        time_metrics = self._advance_runtime(str(battle_completed))
        hist = _deepcopy(self.read("state/history/events/index.json"))
        event_id = "battle_" + command.digest[:16]
        hist.setdefault("events", []).append({
            "event_id": event_id,
            "kind": "battle",
            "at": str(battle_started),
            "completed_at": str(battle_completed),
            "duration_hours": battle_hours,
            "battlefield_ref": battlefield,
            "contact_proof": contact_proof,
            "terrain_kind": terrain_kind,
            "attackers": attackers,
            "defenders": defenders,
            "killed": killed,
            "material_losses": material_losses,
            "named_person_outcomes": named_person_outcomes,
        })
        self.put("state/history/events/index.json", hist)
        result = {
            "battle_event": event_id,
            "battlefield_ref": battlefield,
            "contact_proof": contact_proof,
            "terrain_kind": terrain_kind,
            "represented_personnel": represented,
            "casualties": killed,
            "winner": "attacker" if attacker_won else "defender",
            "score_breakdown": score_details,
            "named_person_outcomes": named_person_outcomes,
            "duration_hours": battle_hours,
            "world_time": str(battle_completed),
        }
        result.update(time_metrics)
        return result

    def _dispatch(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> Dict[str, Any]:
        t=command.command_type
        if t not in COMMAND_TYPES:
            raise ValueError("unsupported Sword semantic command: %s" % t)
        if t=="advance_time":
            target=payload.get("target_time")
            if not target:
                hours=int(payload.get("hours",0)); current=CampaignTime.parse(self.read("state/runtime.json")["world_time"]); target=current.add_seconds(hours*3600).__str__()
            metrics=self._advance_runtime(str(target)); self._write_meta(command,str(target)); return self._result(world_time=str(target),**metrics)
        if t=="scene_consequence":
            hist=_deepcopy(self.read("state/history/events/index.json")); eid="scene_"+command.digest[:16]; hist.setdefault("events",[]).append({"event_id":eid,"kind":"scene_consequence","at":command.submitted_at,"summary":str(payload.get("summary","material scene consequence"))}); self.put("state/history/events/index.json",hist); self._write_meta(command); return self._result(event_id=eid)
        if t=="travel":
            player=_deepcopy(self.read("state/player.json")); origin=player.get("location"); dest=str(payload["destination_ref"]); mode=str(payload.get("mode","foot"));
            if mode not in {"foot","horse"}: raise ValueError("personal travel mode must be foot or horse")
            route=self._find_route(origin,dest,mode=mode); duration=int(route.get("duration_hours",route.get("hours",24))); current=self._world_time(); target=current.add_seconds(duration*3600).__str__(); m=self._advance_runtime(target); player["location"]=dest; self.put("state/player.json",player); self._write_meta(command,target); return self._result(origin=origin,destination=dest,route_ref=route.get("ref", route.get("route_ref")),duration_hours=duration,world_time=target,**m)
        if t=="individual_training":
            player=_deepcopy(self.read("state/player.json")); hours=int(payload.get("hours",1)); focus=str(payload.get("focus","Training"))
            if self._person_health(player)!="healthy": raise ValueError("injured player requires recovery before deliberate training")
            if int(player.get("fatigue",0))>70: raise ValueError("player is too fatigued for deliberate training")
            if focus not in player.get("skills",{}): raise ValueError("training focus must name an exact saved skill")
            current=self._world_time(); target_time=current.add_seconds(hours*3600); target=str(target_time); metrics=self._advance_runtime(target)
            training=self.read("game/data/mechanics/training.json"); development=settle_skill_training(player,focus,hours,target_time,training); player["fatigue"]=_clamp(int(round(_fixed(player.get("fatigue"))+hours/2))); player.setdefault("training_history",[]).append({"started_at":str(current),"completed_at":target,"focus":focus,"hours":hours,"development":development}); self.put("state/player.json",player); self._write_meta(command,target); return self._result(focus=focus,hours=hours,world_time=target,development=development,**metrics)
        if t=="cohort_training":
            p="state/forces/sword-manor.json"; doc=_deepcopy(self.read(p)); hours=int(payload.get("hours",1)); cohort_ref=str(payload.get("cohort_ref","trainee"))
            if cohort_ref not in doc.get("available_by_role",{}): raise ValueError("unknown Sword Manor training cohort")
            current=self._world_time(); target=str(current.add_seconds(hours*3600)); metrics=self._advance_runtime(target); development=doc.setdefault("cohort_development",{}).setdefault(cohort_ref,{"verified_hours":0,"development_bank":0.0,"quality_score":50}); development["verified_hours"]=int(development.get("verified_hours",0))+hours; development["development_bank"]=round(_fixed(development.get("development_bank"))+hours*0.65,3);
            while development["development_bank"]>=18.0 and int(development.get("quality_score",50))<100:
                development["development_bank"]=round(development["development_bank"]-18.0,3); development["quality_score"]=int(development.get("quality_score",50))+1
            doc["cohort_training_hours"]=int(doc.get("cohort_training_hours",0))+hours; doc["last_training_at"]=target; self.put(p,doc); self._write_meta(command,target); return self._result(cohort_ref=cohort_ref,hours=hours,world_time=target,quality_score=development["quality_score"],**metrics)
        if t in {"health_injury","health_recovery"}:
            player=_deepcopy(self.read("state/player.json"));
            if t=="health_injury":
                severity=str(payload.get("severity","minor")).lower(); recovery_hours={"minor":8,"moderate":24,"severe":72,"critical":168}.get(severity)
                if recovery_hours is None: raise ValueError("unknown injury severity")
                fatigue_cost={"minor":8,"moderate":18,"severe":30,"critical":45}[severity]; self._set_person_health(player,"injured"); player["fatigue"]=_clamp(int(player.get("fatigue",0))+fatigue_cost); player["injury_state"]={"label":str(payload.get("injury","injury")),"severity":severity,"inflicted_at":self.read("state/runtime.json")["world_time"],"minimum_recovery_hours":recovery_hours,"recovered_hours":0,"active":True}; self.put("state/player.json",player); self._write_meta(command); return self._result(health=self._person_health(player),severity=severity,minimum_recovery_hours=recovery_hours)
            hours=int(payload.get("hours",8))
            if hours<1 or hours>168: raise ValueError("recovery must consume between 1 and 168 elapsed hours")
            current=CampaignTime.parse(self.read("state/runtime.json")["world_time"]); target=current.add_seconds(hours*3600).__str__(); metrics=self._advance_runtime(target); player["fatigue"]=_clamp(int(player.get("fatigue",0))-max(1,hours*2)); injury=player.get("injury_state")
            if isinstance(injury,dict) and injury.get("active"):
                injury["recovered_hours"]=int(injury.get("recovered_hours",0))+hours
                if int(injury["recovered_hours"])>=int(injury.get("minimum_recovery_hours",0)):
                    injury["active"]=False; injury["resolved_at"]=target; self._set_person_health(player,"healthy")
                else:
                    self._set_person_health(player,"injured")
            self.put("state/player.json",player); self._write_meta(command,target); return self._result(health=self._person_health(player),fatigue=player["fatigue"],hours=hours,world_time=target,**metrics)
        if t=="relationship_change":
            p="state/relationships-gold.json"; doc=_deepcopy(self.read_optional(p) or {"schema":"sword-relationship-ledger","owner_id":"relationships_gold","edges":[]}); src=str(payload.get("source_ref",command.actor_id)); dst=str(payload["target_ref"]); kind=str(payload.get("kind","trust")); delta=int(payload.get("delta",0));
            edge=next((e for e in doc["edges"] if e["source_ref"]==src and e["target_ref"]==dst and e["kind"]==kind),None)
            if edge is None: edge={"source_ref":src,"target_ref":dst,"kind":kind,"value":0}; doc["edges"].append(edge)
            edge["value"]=_clamp(int(edge["value"])+delta,-100,100); self.put(p,doc); self._write_meta(command); return self._result(target_ref=dst,kind=kind,value=edge["value"])
        if t in {"recruitment","population_transfer"}:
            state=self._state_key(payload["state"]); n=int(payload["personnel"]); pp=f"state/population/{state}.json"; pop=_deepcopy(self.read(pp)); source=str(payload.get("source_stratum","agricultural")); dest=str(payload.get("destination_stratum","active_military"));
            if int(pop["strata"].get(source,0))<n: raise ValueError("insufficient population source")
            pop["strata"][source]-=n; pop["strata"][dest]=int(pop["strata"].get(dest,0))+n; self.put(pp,pop)
            if t=="recruitment":
                fp=f"state/forces/state-{state}.json"; force=_deepcopy(self.read(fp)); role=str(payload.get("role","line_infantry")); source_loc=str(force.get("source_location_ref") or self.read(f"state/depots/{state}.json").get("location_ref")); force["headcount"]+=n; force["available_by_role"][role]=int(force["available_by_role"].get(role,0))+n; local=self._force_location_pool(force,source_loc); local[role]=int(local.get(role,0))+n; force.setdefault("recruitment_history",[]).append({"at":str(self._world_time()),"personnel":n,"role":role,"source_location_ref":source_loc}); force["recruitment_history"]=force["recruitment_history"][-24:]; self.put(fp,force); duration_hours=max(8,int(math.ceil(n/250.0))*8)
            else:
                duration_hours=max(4,int(math.ceil(n/1000.0))*4)
            target,metrics=self._advance_seconds(duration_hours*3600); self._write_meta(command,target); return self._result(state=state,personnel=n,duration_hours=duration_hours,world_time=target,**metrics)
        if t=="person_materialize":
            state=self._state_key(payload.get("state","qin")); person_ref=str(payload["person_ref"]); if_path=f"state/char/{person_ref.replace('char_','').replace('_','-')}.json"; existing=self.read_optional(if_path)
            if existing is None:
                fp=f"state/forces/state-{state}.json"; force=_deepcopy(self.read(fp)); role=str(payload.get("role","command_personnel"));
                if int(force["available_by_role"].get(role,0))<1: raise ValueError("no lawful person source")
                force["available_by_role"][role]-=1; force.setdefault("materialized_people",{})[person_ref]=1; self.put(fp,force)
                person={"schema":"sword-materialized-person","id":person_ref,"name":str(payload.get("name",person_ref)),"state":state,"birth_date":str(payload.get("birth_date","270-BCE-01-01")),"status":"alive"}; self.put(if_path,person); self._register_owner(person_ref,if_path)
            self._write_meta(command); return self._result(person_ref=person_ref)
        if t=="formation_create":
            state=self._state_key(payload["state"]); ref=str(payload["formation_ref"]); role=str(payload.get("role","line_infantry")); n=int(payload["personnel"]); fp=f"state/forces/state-{state}.json"; force=_deepcopy(self.read(fp));
            if self.read_optional(f"state/formations/{ref.replace('formation_','').replace('_','-')}.json") is not None: raise ValueError("formation_ref already exists")
            source_loc=str(force.get("source_location_ref",self.read(f"state/depots/{state}.json")["location_ref"])); location=str(payload.get("location_ref",source_loc))
            if location!=source_loc: raise ValueError("new formation must muster from personnel at the exact force source location")
            self._take_force_personnel(force,role,n,location)
            requested_equipment=int(payload.get("equipment_units",int(round(n*0.8)))); equipped=self._take_force_equipment(force,role,min(n,max(0,requested_equipment)),location)
            force.setdefault("allocated_to_formations",{})[ref]={"personnel":n,"role":role}; self.put(fp,force)
            path=f"state/formations/{ref.replace('formation_','').replace('_','-')}.json"; commander_ref=payload.get("commander_ref"); f={"schema":"sword-formation","formation_ref":ref,"name":str(payload.get("name",ref)),"owner_force_ref":f"force_state_{state}","administrative_owner":f"state_{state}","command_authority":str(payload.get("command_authority",f"state_{state}")),"commander_ref":commander_ref,"personnel":n,"composition":{role:n},"location_ref":location,"doctrine_ref":payload.get("doctrine_ref"),"training_ref":payload.get("training_ref"),"doctrine_behavior":{"casualty_tolerance":"moderate","reserve_commitment":50},"training_progress":0,"readiness":40,"morale":60,"cohesion":35,"fatigue":0,"experience":"new","mobilized":False,"status":"forming","logistics":{"food_kg":0,"fodder_kg":0,"war_arrows":0},"mounts":{},"created_at":str(self._world_time())}
            self._set_equipment_units(f,{role:equipped})
            if commander_ref:
                cp, commander=self._validate_person_location_for_formation(str(commander_ref),f); self.put(cp,commander); self._assign_commander_index(str(commander_ref),ref)
            self.put(path,f); self._register_owner(ref,path)
            muster_hours=max(1,min(48,int(math.ceil(n/500.0)))); current=self._world_time(); target=str(current.add_seconds(muster_hours*3600)); metrics=self._advance_runtime(target); self._write_meta(command,target); return self._result(formation_ref=ref,personnel=n,world_time=target,muster_hours=muster_hours,**metrics)
        if t in {"formation_reconstitute","formation_train","formation_mobilize","formation_demobilize","formation_doctrine_set","formation_training_set","formation_assign","force_assignment","command_assign","command_transfer","formation_move","resupply"}:
            ref=str(payload["formation_ref"]); p,f0=self._load_formation(ref); f=_deepcopy(f0); world_time: Optional[str]=None; time_metrics: Dict[str,int]={}
            if t=="formation_reconstitute":
                target=int(payload.get("target_personnel",f["personnel"])); need=max(0,target-int(f["personnel"]));
                if need<=0: raise ValueError("reconstitution target must exceed current personnel")
                fp=self.owner_path(f["owner_force_ref"]); force=_deepcopy(self.read(fp)); role=next(iter(f.get("composition",{"line_infantry":1}))); location=str(f.get("location_ref")); local=self._force_location_pool(force,location); take=min(need,int(local.get(role,0)),int(force["available_by_role"].get(role,0)));
                if take<=0: raise ValueError("no replacement personnel are physically available at formation location")
                self._take_force_personnel(force,role,take,location); old_n=int(f["personnel"]); new_n=old_n+take; f["personnel"]=new_n; f["composition"][role]=int(f["composition"].get(role,0))+take
                desired=int(payload.get("equipment_units",take)); gear_take=self._take_force_equipment(force,role,min(take,max(0,desired)),location); equipment=self._equipment_units(f); equipment[role]=int(equipment.get(role,0))+gear_take; self._set_equipment_units(f,equipment)
                # Replacements enter at baseline recruit quality. Veteran state is diluted, never cloned.
                incoming={"readiness":35,"morale":60,"cohesion":25,"training_progress":10,"fatigue":0}
                for field,base in incoming.items(): f[field]=_clamp(int(round((int(f.get(field,base))*old_n + base*take)/max(1,new_n))))
                if take*2>=new_n and str(f.get("experience","new")) in {"veteran","hardened"}: f["experience"]="field_tested"
                force["allocated_to_formations"][ref]={"personnel":new_n,"role":role}; self.put(fp,force); hours=max(1,min(72,int(math.ceil(take/250.0)))); current=self._world_time(); world_time=str(current.add_seconds(hours*3600)); time_metrics=self._advance_runtime(world_time); f["last_reconstituted_at"]=world_time
            elif t=="formation_train":
                hours=int(payload.get("hours",1)); current=self._world_time(); world_time=str(current.add_seconds(hours*3600)); time_metrics=self._advance_runtime(world_time); f["training_progress"]=_clamp(int(f.get("training_progress",0))+max(1,hours//3)); f["cohesion"]=_clamp(int(f.get("cohesion",50))+max(1,hours//4)); f["readiness"]=_clamp(int(f.get("readiness",50))+max(0,hours//6)); f["fatigue"]=_clamp(int(f.get("fatigue",0))+max(1,hours//5)); f["verified_training_hours"]=int(f.get("verified_training_hours",0))+hours; f["last_training_at"]=world_time
            elif t=="formation_mobilize":
                if bool(f.get("mobilized",False)): raise ValueError("formation is already mobilized")
                world_time,time_metrics=self._advance_seconds(4*3600); f["mobilized"]=True; f["status"]="mobilized"; f["mobilized_at"]=world_time
            elif t=="formation_demobilize":
                if not bool(f.get("mobilized",False)): raise ValueError("formation is already demobilized")
                world_time,time_metrics=self._advance_seconds(2*3600); f["mobilized"]=False; f["status"]="ready"; f["demobilized_at"]=world_time
            elif t=="formation_doctrine_set":
                world_time,time_metrics=self._advance_seconds(8*3600); f["doctrine_ref"]=payload.get("doctrine_ref"); f["doctrine_behavior"]=dict(payload.get("doctrine_behavior",f.get("doctrine_behavior",{}))); f["doctrine_last_reformed_at"]=world_time
            elif t=="formation_training_set":
                world_time,time_metrics=self._advance_seconds(4*3600); f["training_ref"]=payload.get("training_ref"); f["training_program_last_changed_at"]=world_time
            elif t in {"formation_assign","force_assignment","command_assign","command_transfer"}:
                commander_ref=payload.get("commander_ref",f.get("commander_ref")); command_authority=str(payload.get("command_authority",f.get("command_authority")))
                if command.actor_id!=self.INTERNAL_ACTOR and command_authority not in {command.actor_id,str(f.get("administrative_owner"))}: raise PermissionError("player may not forge a new command authority")
                old_commander=f.get("commander_ref")
                if commander_ref:
                    cp,commander=self._validate_person_location_for_formation(str(commander_ref),f); self.put(cp,commander); self._assign_commander_index(str(commander_ref),ref)
                if old_commander and old_commander!=commander_ref: self._release_commander_index(str(old_commander),ref)
                f["command_authority"]=command_authority; f["commander_ref"]=commander_ref; world_time,time_metrics=self._advance_seconds(3600); f["command_last_changed_at"]=world_time
            elif t=="formation_move":
                if not bool(f.get("mobilized",False)): raise ValueError("formation movement requires mobilization")
                dest=str(payload["destination_ref"]); origin=str(f["location_ref"]); route=self._find_route(origin,dest,mode="formation"); hours=int(route.get("duration_hours",route.get("hours",24))); food=max(0,int(math.ceil(int(f["personnel"])*0.8*hours/24))); fod=max(0,int(math.ceil(sum(int(v) for v in f.get("mounts",{}).values())*4*hours/24)));
                if int(f["logistics"].get("food_kg",0))<food or int(f["logistics"].get("fodder_kg",0))<fod: raise ValueError("formation lacks field supply for strategic movement")
                commander_ref=f.get("commander_ref"); commander_path=None; commander=None
                if commander_ref:
                    commander_path,commander=self._validate_person_location_for_formation(str(commander_ref),f)
                current=self._world_time(); world_time=str(current.add_seconds(hours*3600)); time_metrics=self._advance_runtime(world_time); f["logistics"]["food_kg"]-=food; f["logistics"]["fodder_kg"]-=fod; f["location_ref"]=dest; f["fatigue"]=_clamp(int(f.get("fatigue",0))+max(1,hours//12)); f["last_moved_at"]=world_time
                if commander is not None and commander_path is not None: self._set_person_location(commander,dest); self.put(commander_path,commander)
            elif t=="resupply":
                dp,depot=self._material_depot(f)
                if depot.get("location_ref") and depot.get("location_ref")!=f.get("location_ref"): raise ValueError("resupply requires physical depot access")
                requests={"food_kg":int(payload.get("food_kg",int(f["personnel"])*5)),"fodder_kg":int(payload.get("fodder_kg",0)),"war_arrows":int(payload.get("war_arrows",0))}; mapkey={"food_kg":"grain_kg","fodder_kg":"fodder_kg","war_arrows":"war_arrows"}
                transferred=0
                for k,n in requests.items():
                    take=min(n,int(depot["stocks"].get(mapkey[k],0))); depot["stocks"][mapkey[k]]-=take; f["logistics"][k]=int(f["logistics"].get(k,0))+take; transferred+=take
                if transferred<=0: raise ValueError("no requested resupply material is physically available")
                world_time,time_metrics=self._advance_seconds(max(3600,min(12*3600,int(math.ceil(transferred/5000.0))*3600))); f["last_resupplied_at"]=world_time; self.put(dp,depot)
            self.put(p,f); self._write_meta(command,world_time); result=self._result(formation_ref=ref,status=f.get("status"),world_time=world_time or str(self._world_time())); result.update(time_metrics); return result
        if t in {"formation_split","formation_merge","formation_dissolve"}:
            if t=="formation_split":
                ref=str(payload["formation_ref"]); p,f0=self._load_formation(ref); original=_deepcopy(f0); f=_deepcopy(f0); new_ref=str(payload["new_formation_ref"]); n=int(payload["personnel"]); 
                if n<=0 or n>=int(f["personnel"]): raise ValueError("invalid split personnel")
                total=int(original["personnel"]); f["personnel"]=total-n; parent_comp,child_comp=self._partition_counts(original.get("composition",{}),n,total); f["composition"]=parent_comp; new=_deepcopy(original); new["formation_ref"]=new_ref; new["name"]=str(payload.get("name",new_ref)); new["personnel"]=n; new["composition"]=child_comp; new["commander_ref"]=None; new["status"]="detached_pending_commander"
                f["logistics"],new["logistics"]=self._partition_material(original.get("logistics",{}),n,total); f["mounts"],new["mounts"]=self._partition_material(original.get("mounts",{}),n,total); parent_eq,child_eq=self._partition_material(self._equipment_units(original),n,total); self._set_equipment_units(f,parent_eq); self._set_equipment_units(new,child_eq)
                np=f"state/formations/{new_ref.replace('formation_','').replace('_','-')}.json"; fp=self.owner_path(f["owner_force_ref"]); force=_deepcopy(self.read(fp)); role=next(iter(f["composition"])); force["allocated_to_formations"][ref]={"personnel":f["personnel"],"role":role}; force["allocated_to_formations"][new_ref]={"personnel":n,"role":next(iter(new["composition"]))}; self.put(fp,force); self.put(p,f); self.put(np,new); self._register_owner(new_ref,np); world_time,metrics=self._advance_seconds(max(3600,int(math.ceil(n/1000.0))*3600)); self._write_meta(command,world_time); return self._result(formation_ref=ref,new_formation_ref=new_ref,world_time=world_time,**metrics)
            refs=list(payload.get("formation_refs",[]));
            if t=="formation_merge":
                if len(refs)<2: raise ValueError("merge requires at least two formations")
                primary=refs[0]; pp,pf0=self._load_formation(primary); pf=_deepcopy(pf0); fp=self.owner_path(pf["owner_force_ref"]); force=_deepcopy(self.read(fp)); members=[pf]; adopted_commander=pf.get("commander_ref")
                for ref in refs[1:]:
                    p,f=self._load_formation(ref)
                    if f.get("owner_force_ref")!=pf.get("owner_force_ref"): raise ValueError("merge requires one conserved owner force")
                    if f.get("location_ref")!=pf.get("location_ref"): raise ValueError("merge requires co-located formations")
                    secondary_commander=f.get("commander_ref")
                    if adopted_commander is None and secondary_commander:
                        adopted_commander=secondary_commander; pf["commander_ref"]=secondary_commander; self._release_commander_index(str(secondary_commander),ref); self._assign_commander_index(str(secondary_commander),primary)
                    elif secondary_commander:
                        self._release_commander_index(str(secondary_commander),ref)
                    members.append(_deepcopy(f)); self.delete(p); self._unregister_owner(ref); force["allocated_to_formations"].pop(ref,None)
                total=sum(int(x["personnel"]) for x in members); pf["personnel"]=total; pf["composition"]=self._merge_material(*(x.get("composition",{}) for x in members)); pf["logistics"]=self._merge_material(*(x.get("logistics",{}) for x in members)); pf["mounts"]=self._merge_material(*(x.get("mounts",{}) for x in members)); self._set_equipment_units(pf,self._merge_material(*(self._equipment_units(x) for x in members)))
                for field in ("readiness","morale","cohesion","fatigue","training_progress"):
                    pf[field]=_clamp(int(round(sum(int(x.get(field,0))*int(x["personnel"]) for x in members)/max(1,total))))
                role=next(iter(pf["composition"])); force["allocated_to_formations"][primary]={"personnel":total,"role":role}; self.put(pp,pf); self.put(fp,force); world_time,metrics=self._advance_seconds(max(3600,int(math.ceil(total/2000.0))*3600)); self._write_meta(command,world_time); return self._result(formation_ref=primary,personnel=total,world_time=world_time,**metrics)
            ref=str(payload.get("formation_ref",refs[0] if refs else "")); p,f=self._load_formation(ref); fp=self.owner_path(f["owner_force_ref"]); force=_deepcopy(self.read(fp)); location=str(f.get("location_ref"))
            for role,count in f.get("composition",{}).items(): self._return_force_personnel(force,str(role),int(count),location)
            for role,count in self._equipment_units(f).items(): self._return_force_equipment(force,str(role),int(count),location)
            force["allocated_to_formations"].pop(ref,None); self.put(fp,force); self._return_formation_materials(f); self._release_commander_index(f.get("commander_ref"),ref); self.delete(p); self._unregister_owner(ref); world_time,metrics=self._advance_seconds(max(3600,int(math.ceil(int(f.get("personnel",0))/1000.0))*3600)); self._write_meta(command,world_time); return self._result(dissolved=ref,location_ref=location,world_time=world_time,**metrics)
        if t=="battle_resolve":
            result=self._battle(command,payload); self._write_meta(command,str(result["world_time"])); return self._result(**result)
        if t=="personal_combat":
            player=_deepcopy(self.read("state/player.json")); opponent_ref=str(payload["opponent_ref"])
            if opponent_ref==self.PLAYER_ACTOR: raise ValueError("personal combat opponent must be another exact person")
            opponent_path,opponent0=self.owner(opponent_ref); opponent=_deepcopy(opponent0)
            if opponent.get("schema") not in {"sab_character","sword-materialized-person"}: raise ValueError("personal combat opponent is not an exact saved person")
            if str(opponent.get("life_status",opponent.get("status","active"))) in {"dead","deceased"}: raise ValueError("personal combat opponent is not active")
            player_loc=self._person_location(player); opponent_loc=self._person_location(opponent)
            if not player_loc or not opponent_loc or player_loc!=opponent_loc: raise ValueError("personal combat requires exact co-location of both saved people")
            if self._person_health(player)!="healthy": raise ValueError("player is not healthy enough for deliberate personal combat")
            if self._person_health(opponent)!="healthy": raise ValueError("opponent is not healthy enough for deliberate personal combat")
            minutes=int(payload.get("duration_minutes",60));
            if minutes<5 or minutes>240: raise ValueError("personal combat duration must be between 5 and 240 minutes")
            objective=str(payload.get("objective","combat")); spar="spar" in objective.lower() or "controlled" in objective.lower()
            def equipment_profile(person_ref: str, person: Mapping[str,Any]) -> Dict[str,Any]:
                manifest=None
                if person_ref==self.PLAYER_ACTOR:
                    manifest=self.read("state/player-detail/equipment-manifest.json")
                else:
                    manifest_ref=person.get("equipment_manifest_ref")
                    if isinstance(manifest_ref,str): manifest=self.read_optional(manifest_ref)
                equipped=[] if not isinstance(manifest,dict) else [e for e in manifest.get("equipment_manifest",[]) if any(w in str(e.get("current_state","")).lower() for w in ("equipped","worn","readied","quivered","mounted"))]
                best_weapon=None; weapon_bonus=0.0; armor_bonus=0.0; skill_name="Grappling" if _fixed(person.get("skills",{}).get("Grappling",0))>=_fixed(person.get("skills",{}).get("Unarmed",0)) else "Unarmed"
                family_skill={"sword":"Sword","spear":"Spear","glaive":"Glaive","axe":"Axe","mace":"Mace","staff":"Staff","dagger":"Dagger","bow":"Bow","crossbow":"Crossbow"}
                for entry in equipped:
                    item_id=str(entry.get("item_id",""))
                    try: item=self._item_record(item_id)
                    except ValueError: continue
                    schema=str(item.get("schema","")); family=str(item.get("family",item.get("combat_profile",""))).lower()
                    if "weapon" in schema or schema in {"melee_weapon_v2","bow_v2","crossbow_v2"}:
                        force=max(_fixed(item.get("base_force_cut")),_fixed(item.get("base_force_thrust")),_fixed(item.get("base_force_blunt")),_fixed(item.get("projectile_profile")))
                        bonus=force*8.0+_fixed(item.get("handling"))*5.0+min(4.0,_fixed(item.get("reach_m")))*1.5
                        if bonus>weapon_bonus: weapon_bonus=bonus; best_weapon=item_id; skill_name=family_skill.get(family,skill_name)
                    if "armor" in schema or schema=="human_armor_v2":
                        armor_bonus=max(armor_bonus,(_fixed(item.get("cut_resistance"))+_fixed(item.get("thrust_resistance"))+_fixed(item.get("blunt_resistance")))/30.0)
                    if str(item.get("family","")).lower()=="shield" or "shield" in item_id:
                        armor_bonus+=4.0
                return {"best_weapon":best_weapon,"weapon_bonus_x100":int(round(weapon_bonus*100)),"armor_bonus_x100":int(round(armor_bonus*100)),"skill_name":skill_name,"equipped_item_ids":[str(e.get("item_id")) for e in equipped]}
            def combat_score(person_ref:str,person:Mapping[str,Any])->tuple[float,Dict[str,Any]]:
                skills=person.get("skills",{}); attrs=person.get("attributes",{}); eq=equipment_profile(person_ref,person); weapon=_fixed(skills.get(eq["skill_name"],0)); defense=_fixed(skills.get("Defense",0)); support=sum(_fixed(attrs.get(k,0)) for k in ("Agility","Awareness","Coordination","Composure","Endurance"))/5.0; fatigue=max(0,int(person.get("fatigue",0))); score=max(1.0,weapon*0.50+defense*0.10+support*0.30+eq["weapon_bonus_x100"]/100.0+eq["armor_bonus_x100"]/100.0-fatigue*0.6); eq["score_x100"]=int(round(score*100)); return score,eq
            pscore,player_equipment=combat_score(self.PLAYER_ACTOR,player); oscore,opponent_equipment=combat_score(opponent_ref,opponent); seed=self._causal_seed(command,payload,"personal_combat"); jitter=((seed%2001)-1000)/100.0; margin=(pscore-oscore)+jitter*0.08; outcome="win" if margin>4 else ("loss" if margin<-4 else "draw")
            fatigue_gain=max(2,int(math.ceil(minutes/10))); player["fatigue"]=_clamp(int(player.get("fatigue",0))+fatigue_gain); opponent["fatigue"]=_clamp(int(opponent.get("fatigue",0))+fatigue_gain)
            if not spar and outcome in {"win","loss"}:
                loser=opponent if outcome=="win" else player; self._set_person_health(loser,"injured"); loser["injury_state"]={"label":"personal combat injury","severity":"moderate","inflicted_at":self.read("state/runtime.json")["world_time"],"minimum_recovery_hours":24,"recovered_hours":0,"active":True}
            current=CampaignTime.parse(self.read("state/runtime.json")["world_time"]); target=current.add_seconds(minutes*60).__str__(); metrics=self._advance_runtime(target); self.put("state/player.json",player); self.put(opponent_path,opponent); hist=_deepcopy(self.read("state/history/events/index.json")); eid="personal_combat_"+hashlib.sha256((str(current)+":"+self.PLAYER_ACTOR+":"+opponent_ref+":"+objective).encode()).hexdigest()[:16]; hist.setdefault("events",[]).append({"event_id":eid,"kind":"personal_combat","at":str(current),"completed_at":target,"actor_ref":self.PLAYER_ACTOR,"opponent_ref":opponent_ref,"location_ref":player_loc,"objective":objective,"spar":spar,"outcome":outcome,"player_equipment":player_equipment,"opponent_equipment":opponent_equipment}); self.put("state/history/events/index.json",hist); self._write_meta(command,target); return self._result(outcome=outcome,scale="exact_personal",opponent_ref=opponent_ref,location_ref=player_loc,duration_minutes=minutes,world_time=target,score_scale=100,player_score=int(round(pscore*100)),opponent_score=int(round(oscore*100)),player_equipment=player_equipment,opponent_equipment=opponent_equipment,**metrics)
        if t in {"operation_create","operation_transition"}:
            idxp="state/operations/index.json"; idx=_deepcopy(self.read(idxp));
            if t=="operation_create":
                ref=str(payload["operation_ref"]); formation_refs=[str(x) for x in payload.get("formation_refs",[])]; [self._load_formation(x) for x in formation_refs]; path=f"state/operations/{ref}.json"; doc={"schema":"sword-operation","owner_id":ref,"operation_ref":ref,"objective":str(payload.get("objective","operation")),"status":"planned","location_ref":payload.get("location_ref"),"formation_refs":formation_refs,"created_at":command.submitted_at}; self.put(path,doc); idx.setdefault("operations",{})[ref]=path; self.put(idxp,idx); self._register_owner(ref,path); self._write_meta(command); return self._result(operation_ref=ref,status="planned")
            ref=str(payload["operation_ref"]); path=idx.get("operations",{}).get(ref)
            if not path: raise ValueError("unknown operation")
            doc=_deepcopy(self.read(path)); status=str(payload["status"])
            if status in {"active","engaged"}:
                refs=[str(x) for x in doc.get("formation_refs",[])]
                if not refs: raise ValueError("active operation requires exact participating formations")
                forms=[self._load_formation(x)[1] for x in refs]; locations={str(x.get("location_ref")) for x in forms}
                if len(locations)!=1 or next(iter(locations))!=doc.get("location_ref"): raise ValueError("active operation requires all formations at the exact operation location")
                if any(not bool(x.get("mobilized",False)) for x in forms): raise ValueError("active operation requires mobilized formations")
            doc["status"]=status; doc["updated_at"]=command.submitted_at; self.put(path,doc); self._write_meta(command); return self._result(operation_ref=ref,status=doc["status"])
        if t in {"information_create","information_deliver"}:
            idxp="state/information/index.json"; idx=_deepcopy(self.read(idxp))
            if t=="information_create":
                ref=str(payload["information_ref"]); path=f"state/information/{ref}.json"
                if self.read_optional(path) is not None: raise ValueError("information_ref already exists")
                claim=str(payload.get("claim",payload.get("fact",""))); knowers=[str(x) for x in payload.get("knowers",[])]; doc={"schema":"sword-information","owner_id":ref,"information_ref":ref,"fact":claim,"claim":claim,"confidence":str(payload.get("confidence","1.0")),"provenance":str(payload.get("provenance","direct")),"knowers":knowers,"deliveries":[],"created_at":str(self._world_time())}; self.put(path,doc); idx.setdefault("claims",{})[ref]=path; self.put(idxp,idx); self._register_owner(ref,path); world_time,metrics=self._advance_seconds(300); self._write_meta(command,world_time); return self._result(information_ref=ref,world_time=world_time,**metrics)
            ref=str(payload["information_ref"]); path=idx.get("claims",{}).get(ref)
            if not path: raise ValueError("unknown information claim")
            doc=_deepcopy(self.read(path)); target=str(payload.get("target_ref",self.PLAYER_ACTOR)); _,target_person=self._exact_person(target); sender_ref=command.actor_id if command.actor_id!=self.INTERNAL_ACTOR else str(payload.get("source_ref",doc.get("knowers",[self.PLAYER_ACTOR])[0] if doc.get("knowers") else self.PLAYER_ACTOR)); _,sender=self._exact_person(sender_ref); sender_loc=self._person_location(sender); target_loc=self._person_location(target_person)
            if sender_ref not in doc.get("knowers",[]): raise PermissionError("information may travel only from an exact saved knower")
            if not sender_loc or not target_loc: raise ValueError("information delivery requires exact sender and recipient locations")
            hours=self._route_travel_hours(sender_loc,target_loc); seconds=300 if hours==0 else hours*3600; departed=str(self._world_time()); world_time,metrics=self._advance_seconds(seconds); knowers=doc.setdefault("knowers",[])
            if target not in knowers: knowers.append(target)
            delivery={"source_ref":sender_ref,"target_ref":target,"departed_at":departed,"arrived_at":world_time,"source_location_ref":sender_loc,"target_location_ref":target_loc,"channel":"courier","travel_hours":hours}; doc.setdefault("deliveries",[]).append(delivery); doc["deliveries"]=doc["deliveries"][-64:]; self.put(path,doc); self._write_meta(command,world_time); return self._result(information_ref=ref,delivered_to=target,world_time=world_time,travel_hours=hours,**metrics)
        if t in {"institution_project","project_resolve"}:
            ref=str(payload["institution_ref"]); p=self.owner_path(ref); doc=_deepcopy(self.read(p)); projects=doc.setdefault("projects",[])
            if t=="institution_project":
                project_ref=str(payload.get("project_ref","project_"+command.digest[:8]));
                if any(str(x.get("project_ref"))==project_ref and str(x.get("status")) not in {"completed","cancelled"} for x in projects): raise ValueError("active project_ref already exists")
                duration=int(payload.get("duration_hours",168)); kind=str(payload.get("kind","capacity")); magnitude=int(payload.get("magnitude",1)); current=self._world_time(); completes=str(current.add_seconds(duration*3600)); project={"project_ref":project_ref,"kind":kind,"magnitude":magnitude,"status":"active","started_at":str(current),"completes_at":completes,"effect":dict(payload.get("effect",{}))}; projects.append(project); self.put(p,doc); world_time,metrics=self._advance_seconds(3600); self._write_meta(command,world_time); return self._result(institution_ref=ref,project_ref=project_ref,completes_at=completes,world_time=world_time,**metrics)
            project_ref=str(payload["project_ref"]); project=next((x for x in projects if str(x.get("project_ref"))==project_ref),None)
            if not project: raise ValueError("unknown institution project")
            if project.get("status")!="active": raise ValueError("institution project is not active")
            if self._world_time()<CampaignTime.parse(str(project["completes_at"])): raise ValueError("institution project is not complete yet")
            kind=str(project.get("kind","capacity")); magnitude=max(1,int(project.get("magnitude",1))); effect=project.get("effect",{}) if isinstance(project.get("effect"),dict) else {}
            if kind in {"capacity","construction","expansion"}: doc["capacity"]=max(0,int(doc.get("capacity",0))+magnitude)
            elif kind in {"backlog","process"}: doc["backlog"]=max(0,int(doc.get("backlog",0))-magnitude)
            elif kind in {"stock","resource","logistics"}:
                key=str(effect.get("resource","generic_stock")); doc.setdefault("resources",{})[key]=int(doc.get("resources",{}).get(key,0))+magnitude
            else: doc.setdefault("resolved_effects",{})[kind]=int(doc.get("resolved_effects",{}).get(kind,0))+magnitude
            project["status"]="completed"; project["resolved_at"]=str(self._world_time()); self.put(p,doc); world_time,metrics=self._advance_seconds(3600); self._write_meta(command,world_time); return self._result(institution_ref=ref,project_ref=project_ref,status="completed",world_time=world_time,**metrics)
        if t=="house_action":
            ref=str(payload.get("house_ref","house_tang")); p=self.owner_path(ref); doc=_deepcopy(self.read(p)); action=str(payload.get("action","assign_duty")); doc.setdefault("projects",[]).append({"kind":action,"subject_ref":payload.get("subject_ref"),"at":command.submitted_at}); self.put(p,doc); self._write_meta(command); return self._result(house_ref=ref,action=action)
        if t=="state_action":
            state=self._state_key(payload.get("state","qin")); p=f"state/states/{state}.json"; doc=_deepcopy(self.read(p)); action=str(payload.get("action","strategic_goal"));
            if action=="strategic_goal": doc.setdefault("strategic_goals",[]).append(str(payload.get("goal","maintain readiness")))
            elif action=="appointment":
                person_ref=str(payload["person_ref"]); self.owner(person_ref); capabilities=[str(x) for x in payload.get("capabilities",[])]; doc.setdefault("appointments",{})[str(payload["office"])]={"person_ref":person_ref,"capabilities":capabilities,"appointed_at":command.submitted_at}
            elif action in {"enemy_action","record_threat"}:
                source=self._state_key(payload.get("source_state","zhao")); severity=_clamp(int(payload.get("severity",50)))
                doc.setdefault("known_threats",{})[source]={"severity":severity,"observed_at":command.submitted_at,"provenance":str(payload.get("provenance","lawful report"))}
                doc.setdefault("diplomacy",{})[source]={"tension":severity}
            self.put(p,doc); self._write_meta(command); return self._result(state=state,action=action)
        if t in {"market_purchase","market_sell","economy_transfer","enlisted_service_pay"}:
            walletp="state/economy/player-wallet.json"; wallet=_deepcopy(self.read(walletp))
            if t in {"market_purchase","market_sell"}:
                marketp="state/markets/kanyou.json"; market=_deepcopy(self.read(marketp)); market_key=str(payload["item_key"]); qty=int(payload.get("quantity",1)); econ=self.read("game/data/mechanics/economy-gold.json"); prices=econ.get("prices_silver",econ.get("prices",{}))
                if market_key not in market.get("stock",{}) or market_key not in prices: raise ValueError("unknown or unpriced market item")
                item_id=self._market_item_id(market_key); self._item_record(item_id); pack_size=20 if market_key=="arrows_20" else 1; exact_qty=qty*pack_size; unit_price=_fixed(prices[market_key]); total=int(round(unit_price*qty)); player_location=self.read("state/player.json").get("location")
                if player_location != market.get("location_ref"): raise ValueError("market transaction requires lawful physical market access")
                invp,inv=self._player_inventory()
                ep="state/economy/private/qin.json"; eco=_deepcopy(self.read(ep))
                if t=="market_purchase":
                    if int(market["stock"].get(market_key,0))<qty: raise ValueError("insufficient market stock")
                    if int(wallet.get("silver",0))<total: raise ValueError("insufficient player funds")
                    wallet["silver"]-=total; market["stock"][market_key]-=qty; eco["cash_silver"]=int(eco.get("cash_silver",0))+total; inv["items"][item_id]=int(inv["items"].get(item_id,0))+exact_qty; result={"item_key":market_key,"item_id":item_id,"quantity":qty,"exact_quantity":exact_qty,"spent_silver":total}
                else:
                    if int(inv["items"].get(item_id,0))<exact_qty: raise ValueError("insufficient unequipped player inventory to sell")
                    proceeds=max(1,int(math.floor(total*0.70))); if_cash=int(eco.get("cash_silver",0))
                    if if_cash<proceeds: raise ValueError("local private economy cannot fund this purchase")
                    inv["items"][item_id]-=exact_qty; wallet["silver"]+=proceeds; market["stock"][market_key]=int(market["stock"].get(market_key,0))+qty; eco["cash_silver"]-=proceeds; result={"item_key":market_key,"item_id":item_id,"quantity":qty,"exact_quantity":exact_qty,"received_silver":proceeds}
                self.put(invp,inv); self._register_owner("inventory_char_tang_wei",invp); self.put(ep,eco); self.put(marketp,market); self.put(walletp,wallet); world_time,metrics=self._advance_seconds(max(300,qty*60)); self._write_meta(command,world_time); return self._result(world_time=world_time,**result,**metrics)
            state=self._state_key(payload.get("state","qin")); sp=f"state/states/{state}.json"; sd=_deepcopy(self.read(sp)); amount=int(payload.get("amount_silver",7 if t=="enlisted_service_pay" else 0));
            if t=="economy_transfer" and payload.get("direction")=="player_to_state":
                if int(wallet["silver"]) < amount: raise ValueError("insufficient funds")
                wallet["silver"] -= amount; sd["treasury_silver"] += amount
            else:
                if int(sd["treasury_silver"]) < amount: raise ValueError("state treasury insufficient")
                sd["treasury_silver"] -= amount; wallet["silver"] += amount
            self.put(sp,sd); self.put(walletp,wallet); self._write_meta(command); return self._result(amount_silver=amount,state=state)
        if t in {"equipment_equip","equipment_unequip","equipment_transfer","equipment_drop","equipment_consume"}:
            item_id=str(payload["item_key"]); qty=int(payload.get("quantity",1)); self._item_record(item_id); player=_deepcopy(self.read("state/player.json")); player_loc=self._person_location(player); invp,inv=self._player_inventory(); mp,manifest=self._player_manifest(); entries=manifest.setdefault("equipment_manifest",[])
            def find_entry(states: tuple[str,...]=()) -> Optional[Dict[str,Any]]:
                for entry in entries:
                    if str(entry.get("item_id"))!=item_id: continue
                    state=str(entry.get("current_state","")).lower()
                    if not states or any(token in state for token in states): return entry
                return None
            if t=="equipment_equip":
                equipped=self._manifest_quantity(manifest,item_id,equipped_only=True)
                if equipped>=qty: raise ValueError("requested item quantity is already equipped")
                need=qty-equipped; stored=find_entry(("stored","ready room","stables","sheathed"))
                while need>0 and stored is not None and int(stored.get("quantity",0))>0:
                    take=min(need,int(stored["quantity"])); stored["quantity"]-=take; entries.append({"item_id":item_id,"quantity":take,"custody":"Tang Wei player equipment","current_state":"equipped/readied on person"}); need-=take
                    if stored["quantity"]<=0: entries.remove(stored)
                    stored=find_entry(("stored","ready room","stables","sheathed"))
                if need:
                    if int(inv["items"].get(item_id,0))<need: raise ValueError("player does not own enough of the exact item to equip")
                    inv["items"][item_id]-=need; entries.append({"item_id":item_id,"quantity":need,"custody":"Tang Wei player equipment","current_state":"equipped/readied on person"})
                action="equipped"
            elif t=="equipment_unequip":
                if self._manifest_quantity(manifest,item_id,equipped_only=True)<qty: raise ValueError("insufficient equipped quantity")
                self._take_manifest_items(manifest,item_id,qty,require_equipped=True); entries.append({"item_id":item_id,"quantity":qty,"custody":"Tang Wei player equipment","current_state":"stored with player at "+str(player_loc)}); action="unequipped"
            elif t=="equipment_transfer":
                target_ref=str(payload["target_ref"]); tp,target=self._exact_person(target_ref); target_loc=self._person_location(target)
                if not player_loc or player_loc!=target_loc: raise ValueError("equipment transfer requires exact co-location")
                available=int(inv["items"].get(item_id,0)); take_inv=min(qty,available); inv["items"][item_id]=available-take_inv; remaining=qty-take_inv
                if remaining: self._take_manifest_items(manifest,item_id,remaining,require_equipped=False)
                target.setdefault("personal_inventory",{})[item_id]=int(target.get("personal_inventory",{}).get(item_id,0))+qty; self.put(tp,target); action="transferred"
            elif t=="equipment_drop":
                available=int(inv["items"].get(item_id,0)); take_inv=min(qty,available); inv["items"][item_id]=available-take_inv; remaining=qty-take_inv
                if remaining: self._take_manifest_items(manifest,item_id,remaining,require_equipped=False)
                hist=_deepcopy(self.read("state/history/events/index.json")); eid="equipment_drop_"+command.digest[:16]; hist.setdefault("events",[]).append({"event_id":eid,"kind":"equipment_drop","at":str(self._world_time()),"person_ref":self.PLAYER_ACTOR,"location_ref":player_loc,"item_id":item_id,"quantity":qty}); self.put("state/history/events/index.json",hist); action="dropped"
            else:
                available=int(inv["items"].get(item_id,0)); take_inv=min(qty,available); inv["items"][item_id]=available-take_inv; remaining=qty-take_inv
                if remaining: self._take_manifest_items(manifest,item_id,remaining,require_equipped=True)
                action="consumed"
            entries[:]=[e for e in entries if int(e.get("quantity",0))>0]; inv["items"]={k:int(v) for k,v in inv["items"].items() if int(v)>0}; self.put(invp,inv); self._register_owner("inventory_char_tang_wei",invp); self.put(mp,manifest); world_time,metrics=self._advance_seconds(300 if t in {"equipment_equip","equipment_unequip","equipment_consume"} else 600); self._write_meta(command,world_time); return self._result(action=action,item_id=item_id,quantity=qty,world_time=world_time,**metrics)
        if t=="reputation_event":
            subject_ref=str(payload["subject_ref"]); audience_ref=str(payload["audience_ref"]); delta=int(payload["delta"]); event_type=str(payload.get("event_type","material_conduct")); now=str(self._world_time()); idxp="state/reputation/index.json"; idx=_deepcopy(self.read(idxp)); subject_path=idx.get("subjects",{}).get(subject_ref)
            if not subject_path: raise ValueError("reputation subject is not registered")
            subject=_deepcopy(self.read(subject_path)); slug=lambda x: x.replace(".","-").replace("_","-").replace(":","-"); profile_id=f"reputation.{slug(subject_ref)}.{slug(audience_ref)}"; profile_path=subject.get("audience_profiles",{}).get(audience_ref,f"state/reputation/audiences/{slug(subject_ref)}--{slug(audience_ref)}.json"); profile=_deepcopy(self.read_optional(profile_path) or {"schema":"reputation-audience-profile.v1","subject_id":subject_ref,"audience_id":audience_ref,"as_of":now,"authority":True,"standing":{"overall":0},"dimensions":{},"evidence_count":0,"last_event_refs":[],"memory_class":"normal"}); profile["standing"]["overall"]=_clamp(int(profile.get("standing",{}).get("overall",0))+delta,-100,100); dimension=str(payload.get("dimension","general")); profile.setdefault("dimensions",{})[dimension]=_clamp(int(profile.get("dimensions",{}).get(dimension,0))+delta,-100,100); eid="reputation."+hashlib.sha256((now+":"+subject_ref+":"+audience_ref+":"+str(command.expected_revision)).encode()).hexdigest()[:16]; event_path=f"state/reputation/events/{eid}.json"; event={"schema":"reputation-event.v1","event_id":eid,"subject_id":subject_ref,"event_type":event_type,"occurred_at":now,"source_event_ref":payload.get("source_event_ref"),"authority":True,"signals":{dimension:delta},"standing_signals":{"overall":delta},"visibility":{"audience_ref":audience_ref,"basis":str(payload.get("basis","verified material evidence"))},"witnesses":[str(x) for x in payload.get("witnesses",[])],"report_routes":[],"deliveries":{},"status":"settled"}; self.put(event_path,event); profile["as_of"]=now; profile["evidence_count"]=int(profile.get("evidence_count",0))+1; profile.setdefault("last_event_refs",[]).append(eid); profile["last_event_refs"]=profile["last_event_refs"][-16:]; self.put(profile_path,profile); subject.setdefault("audience_profiles",{})[audience_ref]=profile_path; subject["as_of"]=now; self.put(subject_path,subject); idx["event_count"]=int(idx.get("event_count",0))+1; idx["audience_profile_count"]=sum(len(self.read(path).get("audience_profiles",{})) if path!=subject_path else len(subject.get("audience_profiles",{})) for path in idx.get("subjects",{}).values()); self.put(idxp,idx); self._write_meta(command); return self._result(event_ref=eid,subject_ref=subject_ref,audience_ref=audience_ref,standing=profile["standing"]["overall"])
        if t=="career_event":
            person_ref=str(payload["person_ref"]); pp,person=self._exact_person(person_ref); kind=str(payload["kind"]); registry_path="state/career/merit-and-career-history.json"; registry=_deepcopy(self.read(registry_path)); career=person.setdefault("career_state",{"merit_total":0,"qualifications":[],"grade":None,"appointments":[]}); record={"record_id":"career."+hashlib.sha256((str(self._world_time())+":"+person_ref+":"+kind+":"+str(command.expected_revision)).encode()).hexdigest()[:14],"person_ref":person_ref,"kind":kind,"at":str(self._world_time()),"authority":True}
            if kind=="merit":
                merit=int(payload["merit"]); career["merit_total"]=int(career.get("merit_total",0))+merit; record.update({"merit":merit,"evidence_ref":payload.get("evidence_ref")})
            elif kind=="qualification":
                q=str(payload["qualification_ref"]); quals=career.setdefault("qualifications",[]);
                if q not in quals: quals.append(q)
                record["qualification_ref"]=q; record["evidence_ref"]=payload.get("evidence_ref")
            elif kind=="promotion":
                grade=str(payload["grade"]); mechanics=self.read("game/data/mechanics/career.json"); thresholds=mechanics.get("ecc_thresholds",{}); skills=person.get("skills",{}); attrs=person.get("attributes",{}); command_score=0.22*_fixed(skills.get("Leadership"))+0.22*_fixed(skills.get("Formation Command"))+0.16*_fixed(skills.get("Tactics"))+0.10*_fixed(skills.get("Strategy"))+0.10*_fixed(attrs.get("Composure"))+0.08*_fixed(skills.get("Logistics"))+0.06*_fixed(attrs.get("Intelligence"))+0.06*_fixed(skills.get("Training")); grade_n=int(grade[1:]); merit_required=grade_n*25
                if command_score < _fixed(thresholds.get(grade,10**9)): raise ValueError("person lacks deterministic command capacity for requested grade")
                if int(career.get("merit_total",0)) < merit_required: raise ValueError("person lacks saved merit evidence for requested grade")
                if not career.get("qualifications"): raise ValueError("promotion requires at least one saved qualification")
                career["grade"]=grade; record.update({"grade":grade,"command_score":round(command_score,3),"merit_required":merit_required})
            else:
                office=str(payload["office"]); career.setdefault("appointments",[]).append({"office":office,"at":str(self._world_time()),"grantor_ref":payload.get("grantor_ref")}); record["office"]=office
            registry.setdefault("records",[]).append(record); registry.setdefault("runtime",{})["last_settled_at"]=str(self._world_time()); self.put(registry_path,registry); self.put(pp,person); self._write_meta(command); return self._result(person_ref=person_ref,kind=kind,career_state=career,record_id=record["record_id"])
        if t=="mercenary_contract":
            merc_ref=str(payload["mercenary_ref"]); mp,merc0=self.owner(merc_ref); merc=_deepcopy(merc0); action=str(payload["action"]); contracts=merc.setdefault("contracts",[]); now=self._world_time(); contract_ref=str(payload.get("contract_ref","contract."+hashlib.sha256((merc_ref+":"+str(now)+":"+str(command.expected_revision)).encode()).hexdigest()[:12])); contract=next((x for x in contracts if str(x.get("contract_ref"))==contract_ref),None); treasury_path=self.owner_path("treasury_house_tang"); treasury=_deepcopy(self.read(treasury_path)); metrics: Dict[str,int]={}; world_time=str(now)
            if action=="offer":
                amount=int(payload["amount_silver"]); term=int(payload.get("term_days",90)); contract={"contract_ref":contract_ref,"employer_ref":"house_tang","company_ref":merc_ref,"status":"offered","offered_at":str(now),"amount_silver":amount,"term_days":term,"paid_silver":0,"deployment_location_ref":None}; contracts.append(contract); merc["status"]="considering_offer"; world_time,metrics=self._advance_seconds(3600)
            else:
                if contract is None: raise ValueError("unknown exact mercenary contract")
                amount=int(payload.get("amount_silver",contract.get("amount_silver",0)))
                if action=="accept":
                    if contract.get("status") not in {"offered","renewal_offered"}: raise ValueError("contract is not awaiting company acceptance")
                    contract["status"]="accepted_unpaid"; contract["accepted_at"]=str(now); merc["status"]="contracted_unpaid"; world_time,metrics=self._advance_seconds(3600)
                elif action=="pay":
                    if contract.get("status") not in {"accepted_unpaid","active","renewal_accepted"}: raise ValueError("contract is not payable in its current state")
                    due=max(0,int(contract.get("amount_silver",0))-int(contract.get("paid_silver",0))); pay=min(amount,due)
                    if pay<=0: raise ValueError("contract has no outstanding lawful payment")
                    if int(treasury.get("silver",0))<pay: raise ValueError("House Tang treasury cannot fund mercenary payment")
                    treasury["silver"]-=pay; merc["treasury_silver"]=int(merc.get("treasury_silver",0))+pay; contract["paid_silver"]=int(contract.get("paid_silver",0))+pay
                    if int(contract["paid_silver"])>=int(contract.get("amount_silver",0)): contract["status"]="active"; contract["active_at"]=str(now); merc["status"]="contracted"
                    self.put(treasury_path,treasury); world_time,metrics=self._advance_seconds(3600)
                elif action=="deploy":
                    if contract.get("status")!="active": raise ValueError("mercenary deployment requires a paid active contract")
                    dest=str(payload["location_ref"]); origin=merc.get("current_location_ref") or merc.get("location_ref"); hours=24 if not isinstance(origin,str) else self._route_travel_hours(origin,dest,modes=("formation","horse","foot")); world_time,metrics=self._advance_seconds(max(1,hours)*3600); merc["current_location_ref"]=dest; contract["deployment_location_ref"]=dest; contract["deployed_at"]=world_time; merc["status"]="deployed"
                elif action=="breach":
                    contract["status"]="breached"; contract["breached_at"]=str(now); contract["breach_reason"]=str(payload.get("reason","material breach")); merc["status"]="breached"; world_time,metrics=self._advance_seconds(3600)
                elif action=="renew":
                    if contract.get("status") not in {"active","completed"}: raise ValueError("only active/completed contracts may be renewed")
                    contract["status"]="renewal_offered"; contract["amount_silver"]=amount; contract["paid_silver"]=0; contract["term_days"]=int(payload.get("term_days",contract.get("term_days",90))); contract["renewal_offered_at"]=str(now); world_time,metrics=self._advance_seconds(3600)
                elif action=="complete":
                    if contract.get("status") not in {"active","breached"}: raise ValueError("contract is not completable")
                    contract["status"]="completed"; contract["completed_at"]=str(now); merc["status"]="available"; world_time,metrics=self._advance_seconds(3600)
            merc.setdefault("runtime",{})["last_contract_event_at"]=world_time; self.put(mp,merc); self._write_meta(command,world_time); return self._result(mercenary_ref=merc_ref,contract_ref=contract_ref,action=action,status=contract.get("status") if contract else None,world_time=world_time,**metrics)
        if t=="fortification_materialize":
            ref=str(payload["fortification_ref"]); loc=str(payload["location_ref"]); profiles=self.read("game/data/world/fortification-profiles.json"); profile=next((x for x in profiles.get("profiles",[]) if x.get("site_ref",x.get("location_ref"))==loc),None)
            if not profile: raise ValueError("location has no fortification profile")
            if self.read("state/fortifications/index.json").get("fortifications",{}).get(ref): raise ValueError("fortification_ref already exists")
            garr=[str(x) for x in payload.get("garrison_formation_refs",[])]; requested_food=int(payload.get("food_kg",0)); requested_fodder=int(payload.get("fodder_kg",0)); loaded=[]
            for fr in garr:
                fp0,gf0=self._load_formation(fr); gf=_deepcopy(gf0)
                if gf.get("location_ref")!=loc: raise ValueError("fortification garrison must already be at the exact fortified site")
                loaded.append((fp0,gf))
            if not loaded: raise ValueError("fortification requires exact saved garrison")
            if sum(int(gf.get("logistics",{}).get("food_kg",0)) for _,gf in loaded)<requested_food: raise ValueError("fortification food must come from exact co-located garrison stores")
            if sum(int(gf.get("logistics",{}).get("fodder_kg",0)) for _,gf in loaded)<requested_fodder: raise ValueError("fortification fodder must come from exact co-located garrison stores")
            remaining_food=requested_food; remaining_fodder=requested_fodder
            for gp,gf in loaded:
                food=min(remaining_food,int(gf.get("logistics",{}).get("food_kg",0))); fod=min(remaining_fodder,int(gf.get("logistics",{}).get("fodder_kg",0))); gf.setdefault("logistics",{})["food_kg"]-=food; gf["logistics"]["fodder_kg"]-=fod; remaining_food-=food; remaining_fodder-=fod; self.put(gp,gf)
            commander_ref=payload.get("commander_ref")
            if commander_ref:
                cp,commander=self._validate_person_location_for_formation(str(commander_ref),loaded[0][1]); self.put(cp,commander)
            path=f"state/fortifications/{ref}.json"; doc={"schema":"sword-fortification","owner_id":ref,"fortification_ref":ref,"site_ref":loc,"location_ref":loc,"profile":profile,"integrity":int(payload.get("integrity",100)),"garrison_formation_refs":garr,"food_kg":requested_food,"fodder_kg":requested_fodder,"commander_ref":commander_ref,"state":self._state_key(payload.get("state","qin")),"materialized_at":str(self._world_time())}; self.put(path,doc); idx=_deepcopy(self.read("state/fortifications/index.json")); idx.setdefault("fortifications",{})[ref]=path; self.put("state/fortifications/index.json",idx); self._register_owner(ref,path); world_time,metrics=self._advance_seconds(2*3600); self._write_meta(command,world_time); return self._result(fortification_ref=ref,food_kg=requested_food,fodder_kg=requested_fodder,world_time=world_time,**metrics)
        if t in {"siege_start","siege_action"}:
            idxp="state/sieges/index.json"; idx=_deepcopy(self.read(idxp))
            if t=="siege_start":
                ref=str(payload["siege_ref"]); fort_ref=str(payload["fortification_ref"]);
                if idx.get("sieges",{}).get(ref): raise ValueError("siege_ref already exists")
                _,fort0=self.owner(fort_ref); fort=_deepcopy(fort0)
                if fort.get("schema")!="sword-fortification": raise ValueError("siege requires an exact fortification")
                attackers=[str(x) for x in payload.get("attacker_formation_refs",[])]; defenders=[str(x) for x in fort.get("garrison_formation_refs",[])]
                if set(attackers)&set(defenders): raise ValueError("a siege formation cannot attack itself")
                attack_states=set(); defend_states=set()
                for fr in attackers+defenders:
                    _,sf=self._load_formation(fr)
                    if sf.get("location_ref")!=fort.get("location_ref"): raise ValueError("siege requires exact physical contact at the fortified site")
                    if not bool(sf.get("mobilized",False)): raise ValueError("siege participants must be mobilized")
                    admin=str(sf.get("administrative_owner","")); (attack_states if fr in attackers else defend_states).add(admin)
                if attack_states & defend_states: raise ValueError("siege requires hostile administrative sides")
                path=f"state/sieges/{ref}.json"; now=str(self._world_time()); doc={"schema":"sword-siege","owner_id":ref,"siege_ref":ref,"fortification_ref":fort_ref,"attacker_formation_refs":attackers,"defender_formation_refs":defenders,"status":"active","days":0,"casualties":{},"started_at":now,"attacker_authorities":sorted(attack_states),"defender_authorities":sorted(defend_states),"outcome":None}; self.put(path,doc); idx.setdefault("sieges",{})[ref]=path; self.put(idxp,idx); self._register_owner(ref,path); world_time,metrics=self._advance_seconds(6*3600); self._write_meta(command,world_time); return self._result(siege_ref=ref,status="active",world_time=world_time,**metrics)
            ref=str(payload["siege_ref"]); path=idx.get("sieges",{}).get(ref)
            if not path: raise ValueError("unknown siege")
            siege=_deepcopy(self.read(path)); action=str(payload["action"]); fp=self.owner_path(siege["fortification_ref"]); fort=_deepcopy(self.read(fp)); world_time=str(self._world_time()); metrics: Dict[str,int]={}
            if siege.get("status") not in {"active","captured","withdrawn","relieved"} and action!="settle": raise ValueError("siege is not active")
            if action=="blockade":
                if siege.get("status")!="active": raise ValueError("blockade requires an active siege")
                days=int(payload.get("days",7)); defenders=sum(int(self._load_formation(fr)[1].get("personnel",0)) for fr in fort.get("garrison_formation_refs",[])); defender_food=days*defenders; fort["food_kg"]=max(0,int(fort.get("food_kg",0))-defender_food)
                for fr in siege.get("attacker_formation_refs",[]):
                    ap,af0=self._load_formation(str(fr)); af=_deepcopy(af0); need=days*int(af.get("personnel",0));
                    if int(af.get("logistics",{}).get("food_kg",0))<need: raise ValueError("attacking formation lacks field food for requested blockade duration")
                    af["logistics"]["food_kg"]-=need; af["fatigue"]=_clamp(int(af.get("fatigue",0))+max(1,days//3)); self.put(ap,af)
                siege["days"]=int(siege.get("days",0))+days; world_time,metrics=self._advance_seconds(days*86400)
            elif action=="assault":
                if siege.get("status")!="active": raise ValueError("assault requires an active siege")
                result=self._battle(command,{"attacker_formation_refs":siege["attacker_formation_refs"],"defender_formation_refs":fort["garrison_formation_refs"]},context={"kind":"siege_assault","contact_ref":ref,"location_ref":fort["location_ref"]}); siege["casualties"].update(result["casualties"]); total_def_before=max(1,sum(int(self._load_formation(fr)[1].get("personnel",0))+int(result["casualties"].get(fr,0)) for fr in fort.get("garrison_formation_refs",[]))); defender_losses=sum(int(result["casualties"].get(fr,0)) for fr in fort.get("garrison_formation_refs",[])); damage=max(1,min(25,int(round(5+20*defender_losses/total_def_before)))); fort["integrity"]=_clamp(int(fort.get("integrity",100))-damage); siege["last_assault_event"]=result["battle_event"]; siege["last_assault_damage"]=damage; world_time=str(result["world_time"]); metrics={k:int(result.get(k,0)) for k in ("hosts_woken","events_processed") if k in result}
                defenders_left=sum(int(self._load_formation(fr)[1].get("personnel",0)) for fr in fort.get("garrison_formation_refs",[]));
                if int(fort.get("integrity",0))<=0 or defenders_left<=0: siege["status"]="captured"; siege["outcome"]="attacker_control"; siege["captured_at"]=world_time
            elif action=="repair":
                if siege.get("status")!="active": raise ValueError("repair requires an active siege")
                state=fort["state"]; sp=f"state/states/{state}.json"; sd=_deepcopy(self.read(sp)); points=int(payload.get("points",5)); cost=points*1000; food=points*100
                if sd["treasury_silver"]<cost or fort["food_kg"]<food: raise ValueError("insufficient repair resources")
                sd["treasury_silver"]-=cost; fort["food_kg"]-=food; fort["integrity"]=_clamp(int(fort.get("integrity",0))+points); self.put(sp,sd); world_time,metrics=self._advance_seconds(6*3600)
            elif action=="withdraw":
                if siege.get("status")!="active": raise ValueError("only an active siege may withdraw")
                siege["status"]="withdrawn"; siege["outcome"]="defender_holds"; world_time,metrics=self._advance_seconds(4*3600)
            elif action=="relief":
                if siege.get("status")!="active": raise ValueError("relief requires an active siege")
                siege["status"]="relieved"; siege["outcome"]="defender_holds"; world_time,metrics=self._advance_seconds(4*3600)
            elif action=="settle":
                if siege.get("status") not in {"captured","withdrawn","relieved"}: raise ValueError("siege cannot settle until a causal outcome exists")
                siege["settled_from"]=siege["status"]; siege["status"]="settled"; siege["settled_at"]=str(self._world_time()); world_time,metrics=self._advance_seconds(3600)
            self.put(fp,fort); self.put(path,siege); self._write_meta(command,world_time); return self._result(siege_ref=ref,status=siege["status"],action=action,outcome=siege.get("outcome"),world_time=world_time,**metrics)
        if t=="territorial_consequence":
            loc=str(payload["location_ref"]); controller=str(payload["controller"]); terr=_deepcopy(self.read("state/territory/control.json")); site=terr["sites"].get(loc)
            if not site: raise ValueError("unknown strategic territory")
            old_controller=str(site.get("controller"))
            if controller==old_controller: raise ValueError("territorial consequence must materially change control")
            evidence_ref=None; basis=None
            if payload.get("siege_ref"):
                evidence_ref=str(payload["siege_ref"]); _,sg=self.owner(evidence_ref)
                if sg.get("status") not in {"captured","settled"} or sg.get("outcome")!="attacker_control": raise ValueError("territorial transfer requires an attacker-captured siege outcome")
                attacker_states={str(x) for x in sg.get("attacker_authorities",[])}
                if controller not in attacker_states: raise ValueError("territorial controller must be the authority that actually captured the site")
                basis="captured_siege"
            elif payload.get("operation_ref"):
                evidence_ref=str(payload["operation_ref"]); op_path=self.read("state/operations/index.json").get("operations",{}).get(evidence_ref)
                if not op_path: raise ValueError("unknown occupation operation")
                op=self.read(op_path)
                if op.get("status") not in {"occupied","completed"} or op.get("location_ref")!=loc: raise ValueError("territorial transfer requires a completed occupation at the exact site")
                forms=[self._load_formation(str(fr))[1] for fr in op.get("formation_refs",[])]; authorities={str(f.get("administrative_owner")) for f in forms if int(f.get("personnel",0))>0}
                if controller not in authorities: raise ValueError("territorial controller must have a surviving occupying formation")
                basis="occupation_operation"
            else:
                raise ValueError("territorial control changes require exact siege or occupation evidence")
            now=str(self._world_time()); site["controller"]=controller; site["previous_controller"]=old_controller; site["changed_at"]=now; site["change_evidence_ref"]=evidence_ref; site["change_basis"]=basis; self.put("state/territory/control.json",terr); hist=_deepcopy(self.read("state/history/events/index.json")); eid="territory_"+hashlib.sha256((now+":"+loc+":"+controller).encode()).hexdigest()[:16]; hist.setdefault("events",[]).append({"event_id":eid,"kind":"territorial_control_change","at":now,"location_ref":loc,"from":old_controller,"to":controller,"evidence_ref":evidence_ref,"basis":basis}); self.put("state/history/events/index.json",hist); world_time,metrics=self._advance_seconds(12*3600); self._write_meta(command,world_time); return self._result(location_ref=loc,controller=controller,previous_controller=old_controller,evidence_ref=evidence_ref,world_time=world_time,**metrics)
        if t=="family_event":
            house_ref=str(payload.get("house_ref","house_tang")); hp=self.owner_path(house_ref); house=_deepcopy(self.read(hp)); kind=str(payload["kind"]); idxp="state/family/index.json"; idx=_deepcopy(self.read(idxp)); now=self._world_time(); world_time=str(now); subjects: list[str]=[]; source_refs: list[str]=[]; result: Dict[str,Any]={"house_ref":house_ref,"kind":kind}
            def person_age(ref: str) -> int:
                return age_years(self._exact_person(ref)[1], now)
            def active_union(a: str, b: Optional[str]=None) -> tuple[Optional[str],Optional[str],Optional[Dict[str,Any]]]:
                for uid,path in idx.get("unions",{}).items():
                    u=self.read(path); participants={str(x) for x in u.get("participants",[])}
                    if a in participants and (b is None or b in participants) and str(u.get("status")) in {"betrothed","married"}: return str(uid),str(path),_deepcopy(u)
                return None,None,None
            def add_person_index(ref: str, bucket: str, record_id: str) -> None:
                pi=idx.setdefault("person_index",{}).setdefault(ref,{}); values=pi.setdefault(bucket,[]);
                if record_id not in values: values.append(record_id)
            def write_family_event(event_type: str, refs: list[str], refs_sources: list[str]) -> str:
                eid="family."+event_type+"."+hashlib.sha256((str(now)+":"+":".join(sorted(refs))+":"+str(command.expected_revision)).encode()).hexdigest()[:12]; path=f"state/family/events/{eid}.json"; event={"schema":"family-event.v1","event_id":eid,"event_type":event_type,"occurred_at":str(now),"authority":True,"subject_refs":refs,"source_refs":refs_sources}; self.put(path,event); idx.setdefault("events",{})[eid]=path; idx.setdefault("counts",{})["events"]=len(idx["events"]);
                for ref in refs: add_person_index(ref,"events",eid)
                return eid
            if kind=="proposal":
                a=str(payload["person_ref"]); b=str(payload["partner_ref"]);
                if a==b: raise ValueError("a family proposal requires two distinct people")
                if person_age(a)<16 or person_age(b)<16: raise ValueError("marriage proposal participants must be at least 16")
                pa,aa=self._exact_person(a); pb,bb=self._exact_person(b);
                if self._person_location(aa)!=self._person_location(bb) or self._person_location(aa) is None: raise ValueError("family proposal requires exact co-location")
                if active_union(a)[2] or active_union(b)[2]: raise ValueError("participant already has an active union")
                if command.actor_id!=self.INTERNAL_ACTOR and a!=command.actor_id: raise PermissionError("player may author only their own proposal")
                pid=str(payload.get("proposal_ref",f"proposal.{a}.{b}.{command.expected_revision}")); path=f"state/family/proposals/{pid}.json";
                if self.read_optional(path) is not None: raise ValueError("proposal_ref already exists")
                proposal={"schema":"family-proposal.v1","proposal_id":pid,"kind":"marriage_proposal","proposer_id":a,"target_id":b,"status":"pending","authority":True,"proposed_at":str(now),"player_choice_required":b==self.PLAYER_ACTOR}; self.put(path,proposal); idx.setdefault("proposals",{})[pid]=path; idx.setdefault("counts",{})["proposals"]=len(idx["proposals"]); add_person_index(a,"proposals",pid); add_person_index(b,"proposals",pid); subjects=[a,b]; source_refs=[path]; result["proposal_ref"]=pid; result["family_event"]=write_family_event("proposal_made",subjects,source_refs)
            elif kind=="engagement":
                pid=str(payload.get("proposal_ref","")); path=idx.get("proposals",{}).get(pid);
                if not path: raise ValueError("engagement requires an exact saved proposal")
                proposal=_deepcopy(self.read(path));
                if proposal.get("status")!="pending": raise ValueError("proposal is not pending")
                a=str(proposal["proposer_id"]); b=str(proposal["target_id"]);
                if command.actor_id!=self.INTERNAL_ACTOR and command.actor_id!=b: raise PermissionError("player may accept only a proposal made to the player")
                pa,aa=self._exact_person(a); pb,bb=self._exact_person(b);
                if self._person_location(aa)!=self._person_location(bb) or self._person_location(aa) is None: raise ValueError("engagement requires exact co-location")
                proposal["status"]="accepted"; proposal["accepted_at"]=str(now); self.put(path,proposal); uid="union."+"_".join(sorted([a.replace("char_",""),b.replace("char_","")])) ; up=f"state/family/unions/{uid}.json"; union={"schema":"family-union.v1","union_id":uid,"participants":[a,b],"status":"betrothed","authority":True,"formed_at":str(now),"date_precision":"exact_runtime","recognition":{"recognized":True,"basis":"accepted saved proposal"},"relationship_refs":[],"proposal_ref":pid}; self.put(up,union); idx.setdefault("unions",{})[uid]=up; idx.setdefault("counts",{})["unions"]=len(idx["unions"]); add_person_index(a,"unions",uid); add_person_index(b,"unions",uid); subjects=[a,b]; source_refs=[path,up]; result["union_ref"]=uid; result["family_event"]=write_family_event("betrothal_formed",subjects,source_refs)
            elif kind=="marriage":
                a=str(payload["person_ref"]); b=str(payload["partner_ref"]); uid,up,union=active_union(a,b)
                if union is None or union.get("status")!="betrothed": raise ValueError("marriage requires a saved accepted betrothal")
                pa,aa=self._exact_person(a); pb,bb=self._exact_person(b); loc=self._person_location(aa)
                if not loc or loc!=self._person_location(bb): raise ValueError("marriage requires exact co-location")
                union["status"]="married"; union["married_at"]=str(now); self.put(str(up),union); hid="household."+"_".join(sorted([a.replace("char_",""),b.replace("char_","")])) ; hpath=f"state/family/households/{hid}.json"; household={"schema":"family-household.v1","household_id":hid,"authority":True,"status":"active","member_refs":[a,b],"dependent_refs":[],"property_refs":[],"institution_refs":[],"residence_ref":loc,"union_refs":[uid]}; self.put(hpath,household); union["household_ref"]=hpath; self.put(str(up),union); idx.setdefault("households",{})[hid]=hpath; idx.setdefault("counts",{})["households"]=len(idx["households"]); add_person_index(a,"households",hid); add_person_index(b,"households",hid); house.setdefault("lineage_cohort",{})["marriages"]=int(house.get("lineage_cohort",{}).get("marriages",0))+1; subjects=[a,b]; source_refs=[str(up),hpath]; result.update({"union_ref":uid,"household_ref":hid}); result["family_event"]=write_family_event("marriage_formed",subjects,source_refs)
            elif kind=="pregnancy":
                mother_ref=str(payload["mother_ref"]); father_ref=str(payload["father_ref"]); uid,up,union=active_union(mother_ref,father_ref)
                if union is None or union.get("status")!="married": raise ValueError("pregnancy requires a recognized active married union")
                mp,mother=self._exact_person(mother_ref); self._exact_person(father_ref)
                if isinstance(mother.get("pregnancy_state"),dict) and mother["pregnancy_state"].get("active"): raise ValueError("pregnancy already active")
                due=now.add_days(270); mother["pregnancy_state"]={"active":True,"father_ref":father_ref,"union_ref":uid,"recognized_at":str(now),"due_at":str(due)}; self.put(mp,mother); subjects=[mother_ref,father_ref]; source_refs=[str(up)]; result["due_at"]=str(due)
            elif kind=="birth":
                mother_ref=str(payload["mother_ref"]); father_ref=str(payload["father_ref"]); child_ref=str(payload["child_ref"]); mp,mother=self._exact_person(mother_ref); fp,father=self._exact_person(father_ref); preg=mother.get("pregnancy_state")
                if not isinstance(preg,dict) or not preg.get("active") or preg.get("father_ref")!=father_ref: raise ValueError("birth requires a matching active saved pregnancy")
                due=CampaignTime.parse(str(preg["due_at"]));
                if now<due: raise ValueError("birth cannot occur before the saved due time")
                if self.read("state/index/owner-index-gold.json").get("owners",{}).get(child_ref): raise ValueError("child_ref already exists")
                loc=self._person_location(mother); birth_date=f"{now.bce_year}-BCE-{now.month:02d}-{now.day:02d}"; seed=self._causal_seed(command,payload,"birth:"+child_ref); child_path=f"state/char/{child_ref.replace('char_','').replace('_','-')}.json"; child={"schema":"sab_character","owner_id":child_ref,"owner_type":"character","name":str(payload.get("name",child_ref.replace('char_','').replace('_',' ').title())),"birth_date":birth_date,"body":{"adult_height_cm":float(160+(seed%1800)/100.0),"growth_end_age":18,"current_weight_kg":3.2+((seed//100)%8)/10.0,"frame":"infant","growth_profile_id":"human_height_to_18"},"appearance":int(40+(seed%61)),"attributes":{},"skills":{},"aptitude":{"physical_learning":100,"technical_learning":100,"tactical_learning":100,"academic_learning":100,"social_learning":100},"development_state":{"completed_reviews":0,"maintenance_credit":0.0,"training_credit":0.0},"health_status":"healthy","life_status":"active","current_location":loc,"family":house_ref}; self.put(child_path,child); self._register_owner(child_ref,child_path); parentage_id=f"parentage.{child_ref.replace('char_','')}.birth_parents"; parpath=f"state/family/parentage/{parentage_id}.json"; parentage={"schema":"family-parentage.v1","parentage_id":parentage_id,"child_id":child_ref,"authority":True,"parent_links":[{"parent_id":mother_ref,"kind":"biological"},{"parent_id":father_ref,"kind":"biological"}],"guardian_links":[]}; self.put(parpath,parentage); idx.setdefault("parentage",{})[parentage_id]=parpath; idx.setdefault("counts",{})["parentage"]=len(idx["parentage"]); add_person_index(child_ref,"parentage",parentage_id); add_person_index(mother_ref,"parentage",parentage_id); add_person_index(father_ref,"parentage",parentage_id); uid=str(preg.get("union_ref")); up=idx.get("unions",{}).get(uid); union=self.read(up) if up else {}; hpath=union.get("household_ref") if isinstance(union,dict) else None
                if isinstance(hpath,str): household=_deepcopy(self.read(hpath)); deps=household.setdefault("dependent_refs",[]);
                if isinstance(hpath,str) and child_ref not in deps: deps.append(child_ref); self.put(hpath,household); add_person_index(child_ref,"households",str(household.get("household_id")))
                preg["active"]=False; preg["resolved_at"]=str(now); preg["child_ref"]=child_ref; mother["pregnancy_state"]=preg; self.put(mp,mother); house.setdefault("lineage_cohort",{})["children"]=int(house.get("lineage_cohort",{}).get("children",0))+1; subjects=[mother_ref,father_ref,child_ref]; source_refs=[parpath]+([str(hpath)] if hpath else []); result.update({"child_ref":child_ref,"parentage_ref":parentage_id}); result["family_event"]=write_family_event("birth",subjects,source_refs)
            elif kind=="death":
                person_ref=str(payload["person_ref"]); pp,person=self._exact_person(person_ref); self._set_person_life_status(person,"dead"); self._set_person_health(person,"dead"); person["died_at"]=str(now); self.put(pp,person); subjects=[person_ref]
                for uid,up in list(idx.get("unions",{}).items()):
                    union=_deepcopy(self.read(up));
                    if person_ref in union.get("participants",[]) and union.get("status")=="married": union["status"]="widowed"; union["widowed_at"]=str(now); self.put(up,union); source_refs.append(up)
                cohort=house.setdefault("lineage_cohort",{}); cohort["adults"]=max(0,int(cohort.get("adults",0))-1); result["family_event"]=write_family_event("death_family_settlement",subjects,source_refs)
            elif kind=="widowhood":
                person_ref=str(payload["person_ref"]); changed=[]
                for uid,up in list(idx.get("unions",{}).items()):
                    union=_deepcopy(self.read(up));
                    if person_ref in union.get("participants",[]) and union.get("status")=="married": union["status"]="widowed"; union["widowed_at"]=str(now); self.put(up,union); changed.append(up)
                if not changed: raise ValueError("no active marriage exists for widowhood settlement")
                subjects=[person_ref]; source_refs=changed; result["family_event"]=write_family_event("widowhood",subjects,source_refs)
            elif kind=="succession_review":
                sid=str(payload.get("succession_ref","succession.house_tang")); sp=idx.get("successions",{}).get(sid);
                if not sp: raise ValueError("unknown succession record")
                succession=_deepcopy(self.read(sp)); holder=str(succession.get("current_holder_id","")); holder_dead=False
                if holder:
                    try: holder_dead=str(self._exact_person(holder,active=False)[1].get("life_status","active")) in {"dead","deceased"}
                    except ValueError: holder_dead=True
                if holder_dead:
                    replacement=None
                    for c in succession.get("candidate_order",[]):
                        ref=str(c.get("person_id",""));
                        try:
                            self._exact_person(ref); replacement=ref; break
                        except ValueError: continue
                    if replacement is None: raise ValueError("succession has no living eligible candidate")
                    succession["current_holder_id"]=replacement; succession["last_changed_at"]=str(now); self.put(sp,succession); result["new_holder_ref"]=replacement; subjects=[holder,replacement]; source_refs=[sp]; result["family_event"]=write_family_event("succession_change",subjects,source_refs)
                else: result["new_holder_ref"]=holder
            idx.setdefault("counts",{})["unions"]=len(idx.get("unions",{})); idx["counts"]["households"]=len(idx.get("households",{})); idx["counts"]["parentage"]=len(idx.get("parentage",{})); self.put(idxp,idx); house.setdefault("family_events",[]).append({"kind":kind,"at":str(now),"subjects":subjects}); house["family_events"]=house["family_events"][-32:]; self.put(hp,house); self._write_meta(command,world_time); return self._result(**result)
        if t=="repair":
            if command.actor_id!=self.INTERNAL_ACTOR or command.mode!="maintenance": raise PermissionError("repair requires trusted internal maintenance actor")
            path=str(payload["path"]); before=self.read(path); after=_deepcopy(before); changes=dict(payload.get("changes",{})); after.update(changes); self.put(path,after); hist=_deepcopy(self.read("state/history/events/index.json")); eid="repair_"+command.digest[:16]; hist.setdefault("events",[]).append({"event_id":eid,"kind":"explicit_repair","at":command.submitted_at,"path":path,"reason":str(payload.get("reason","confirmed campaign-state repair"))}); self.put("state/history/events/index.json",hist); self._write_meta(command); return self._result(repair_event=eid,path=path)
        raise ValueError("unsupported Sword semantic command: %s" % t)

    def preview(self, command: CommandEnvelope) -> CommandPlan:
        self._reset(); self._authorize(command)
        if self.store.campaign_id()!=command.campaign_id: raise ValueError("campaign mismatch")
        self.store.require_revision(command.expected_revision)
        payload=thaw_json(command.payload)
        self._validate_command_semantics(command,payload)
        self._authorize_command(command,payload)
        result=self._dispatch(command,payload)
        # Make runtime metrics reflect actual unique planning fanout and write count when runtime is touched.
        if "state/runtime.json" in self._writes:
            rt=self._writes["state/runtime.json"]; rt.setdefault("metrics",{})["planning_reads"]=len(self._reads); rt["metrics"]["writes"]=len(self._writes)+len(self._deletes)
        writes={}
        for p,v in self._writes.items():
            raw=_json_bytes(v)
            if self.store.read_optional_bytes(p) != raw:
                writes[p]=raw
        for p in self._deletes:
            if self.store.read_optional_bytes(p) is not None:
                writes[p]=None
        result["planning_reads"]=len(self._reads); result["writes"]=len(writes)
        txid="sword-"+hashlib.sha256((command.digest+":"+str(command.expected_revision)).encode()).hexdigest()[:24]
        return CommandPlan(txid,command.submitted_at,writes,result,len(self._reads),self._validator)


class SwordRuntime:
    def __init__(self, root: object, runtime_root: object | None = None) -> None:
        import os
        self.root=Path(root).resolve(); self.store=RepositoryStore(self.root); self.planner=RepositoryCommandPlanner(self.root)
        runtime_dir=(Path(runtime_root).resolve() if runtime_root is not None else self.root/".sword-runtime"); runtime_dir.mkdir(parents=True,exist_ok=True)
        self.runtime_dir=runtime_dir
        self.coordinator=TransactionCoordinator(
            self.store, GitStager(self.root), WriteAheadLog(runtime_dir/"wal"), ReceiptStore(runtime_dir/"receipts"), runtime_dir/"campaign.lock", lock_timeout=10.0, remote_durability=None)
        self.replicator=None
        remote=os.environ.get("SWORD_GIT_REMOTE"); branch=os.environ.get("SWORD_GIT_BRANCH")
        if remote and branch:
            from sword_runtime.replication import BestEffortReplicator
            self.replicator=BestEffortReplicator(self.root,runtime_dir,remote,branch)

    def preview(self, command: CommandEnvelope) -> CommandPlan:
        if command.actor_id == RepositoryCommandPlanner.INTERNAL_ACTOR or command.mode in {"autonomous", "maintenance"}:
            raise PermissionError("trusted internal commands are not exposed through player-facing preview")
        return self.planner.preview(command)

    def execute(self, command: CommandEnvelope, crash_injector=None) -> TransactionExecution:
        # Durable duplicate lookup comes before planning because a retry is intentionally stale.
        existing=self.coordinator.lookup_receipt(command)
        if existing is not None:
            from sword_runtime.tx.coordinator import TransactionExecution
            return TransactionExecution("duplicate",existing,None,None,{})
        plan=self.planner.preview(command)
        execution=self.coordinator.execute(command,plan.transaction_id,plan.created_at,plan.writes,plan.result,plan.validator,crash_injector=crash_injector)
        if execution.status=="committed" and execution.commit_hash and self.replicator is not None:
            self.replicator.replicate(execution.commit_hash)
        return execution

    def recover(self):
        return self.coordinator.recover()

__all__=["RepositoryCommandPlanner","SwordRuntime","CommandPlan","COMMAND_TYPES"]
