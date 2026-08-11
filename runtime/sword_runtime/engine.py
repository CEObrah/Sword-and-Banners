from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from sword_runtime.commands import CommandEnvelope
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
    "siege_start","siege_action","territorial_consequence","family_event","repair"
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
                available = sum(int(v) for v in force.get("available_by_role", {}).values())
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

    def _authorize_command(self, command: CommandEnvelope, payload: Mapping[str, Any]) -> None:
        if command.actor_id == self.INTERNAL_ACTOR:
            return
        actor = command.actor_id
        t = command.command_type

        if t == "relationship_change" and str(payload.get("source_ref", actor)) != actor:
            raise PermissionError("gameplay may mutate only relationships sourced by the player actor")

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

    def _material_depot(self, formation: Mapping[str, Any]) -> tuple[str, Dict[str, Any]]:
        force_ref = str(formation.get("owner_force_ref", ""))
        if force_ref.startswith("force_state_"):
            state = force_ref.replace("force_state_", "")
            path = f"state/depots/{state}.json"
            return path, _deepcopy(self.read(path))
        admin = str(formation.get("administrative_owner", "private"))
        slug = force_ref.replace("force_", "").replace("_", "-") or "private"
        path = f"state/depots/{slug}.json"
        existing = self.read_optional(path)
        if existing is None:
            depot = {
                "schema": "sword-depot",
                "owner_id": f"depot_{force_ref or slug}",
                "state": admin,
                "location_ref": formation.get("location_ref"),
                "stocks": {"grain_kg": 0, "fodder_kg": 0, "war_arrows": 0},
                "mounts": {},
            }
            self.put(path, depot)
            self._register_owner(depot["owner_id"], path)
            return path, depot
        return path, _deepcopy(existing)

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

    def _find_route(self, origin: str, destination: str) -> Mapping[str, Any]:
        routes = self.read("game/data/world/routes.json").get("routes", [])
        for route in routes:
            a, b = route.get("a", route.get("from")), route.get("b", route.get("to"))
            if {a, b} == {origin, destination}:
                return route
        # Tang Manor scene venues sit inside Kanyou. Local access is bounded and
        # may connect to the capital route node, but never bypass a strategic route.
        if origin.startswith("loc_tang_manor_") and destination == "loc_kanyou":
            return {"ref":"route_local_tang_manor_kanyou","a":origin,"b":destination,"hours":1,"modes":["foot","horse"]}
        if destination.startswith("loc_tang_manor_") and origin == "loc_kanyou":
            return {"ref":"route_local_tang_manor_kanyou","a":origin,"b":destination,"hours":1,"modes":["foot","horse"]}
        raise ValueError("no saved strategic route between %s and %s" % (origin, destination))

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
                force["headcount"]+=recruits; force["available_by_role"]["line_infantry"]=int(force["available_by_role"].get("line_infantry",0))+recruits
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
                need=max(0,target_n-int(formation.get("personnel",0)))
                take=min(need,int(force.get("available_by_role",{}).get(role,0)))
                if take:
                    force["available_by_role"][role]-=take
                    formation["personnel"]+=take
                    formation.setdefault("composition",{})[role]=int(formation["personnel"])
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
            n=target_n
            if int(force.get("available_by_role",{}).get(role,0)) < n:
                continue
            force["available_by_role"][role] -= n
            force.setdefault("allocated_to_formations",{})[ref] = {"personnel": n, "role": role}
            fpath = f"state/formations/{state}-{bp['key'].replace('_','-')}.json"
            formation = {
                "schema":"sword-formation","formation_ref":ref,
                "name":f"{state.upper()} {bp['key'].replace('_',' ').title()}",
                "owner_force_ref":f"force_state_{state}","administrative_owner":f"state_{state}",
                "command_authority":f"state_{state}","commander_ref":bp.get("commander_ref"),
                "personnel":n,"composition":{role:n},"location_ref":self.read(f"state/depots/{state}.json").get("location_ref"),
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
            _, commander = self.owner(str(commander_ref))
            if str(commander.get("life_status", commander.get("status", "active"))) in {"dead", "deceased"}:
                raise ValueError(f"battle rejected: {ref} commander is not active")

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
        seed = int(hashlib.sha256(command.digest.encode()).hexdigest()[:12], 16)
        variance = ((seed % 2001) - 1000) / 100000.0
        a_rate = max(.01, min(.18, 0.035 * (d_score / a_score) + variance))
        d_rate = max(.01, min(.22, 0.045 * (a_score / d_score) - variance))
        if terrain_kind in {"pass", "fort", "fortress"}:
            d_rate *= 0.86

        killed: Dict[str, int] = {}
        material_losses: Dict[str, Dict[str, Any]] = {}
        represented = sum(int(formations[r][1]["personnel"]) for r in all_refs)
        for refs, rate in ((attackers, a_rate), (defenders, d_rate)):
            for ref in refs:
                path, formation = formations[ref]
                before = int(formation["personnel"])
                adjusted_rate = rate * casualty_modifiers.get(ref, 1.0)
                loss = min(before - 1, max(0, int(round(before * adjusted_rate))))
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

        hist = _deepcopy(self.read("state/history/events/index.json"))
        event_id = "battle_" + command.digest[:16]
        hist.setdefault("events", []).append({
            "event_id": event_id,
            "kind": "battle",
            "at": command.submitted_at,
            "battlefield_ref": battlefield,
            "contact_proof": contact_proof,
            "terrain_kind": terrain_kind,
            "attackers": attackers,
            "defenders": defenders,
            "killed": killed,
            "material_losses": material_losses,
        })
        self.put("state/history/events/index.json", hist)
        return {
            "battle_event": event_id,
            "battlefield_ref": battlefield,
            "contact_proof": contact_proof,
            "terrain_kind": terrain_kind,
            "represented_personnel": represented,
            "casualties": killed,
            "winner": "attacker" if a_score >= d_score else "defender",
            "score_breakdown": score_details,
        }

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
            player=_deepcopy(self.read("state/player.json")); origin=player.get("location"); dest=str(payload["destination_ref"]); route=self._find_route(origin,dest); player["location"]=dest; self.put("state/player.json",player); duration=int(route.get("duration_hours",route.get("hours",24))); target=CampaignTime.parse(self.read("state/runtime.json")["world_time"]).add_seconds(duration*3600).__str__(); m=self._advance_runtime(target); self._write_meta(command,target); return self._result(origin=origin,destination=dest,route_ref=route.get("ref", route.get("route_ref")),**m)
        if t=="individual_training":
            player=_deepcopy(self.read("state/player.json")); hours=int(payload.get("hours",1)); focus=str(payload.get("focus","Training"))
            if hours<1 or hours>12: raise ValueError("deliberate personal training must be between 1 and 12 elapsed hours")
            if self._person_health(player)!="healthy": raise ValueError("injured player requires recovery before deliberate training")
            if int(player.get("fatigue",0))>70: raise ValueError("player is too fatigued for deliberate training")
            current=CampaignTime.parse(self.read("state/runtime.json")["world_time"]); target=current.add_seconds(hours*3600).__str__(); metrics=self._advance_runtime(target)
            ds=player.setdefault("development_state",{}); ds["training_credit"]=_fixed(ds.get("training_credit"))+hours; player["fatigue"]=_clamp(int(round(_fixed(player.get("fatigue"))+hours/2))); player.setdefault("training_history",[]).append({"started_at":str(current),"completed_at":target,"focus":focus,"hours":hours}); self.put("state/player.json",player); self._write_meta(command,target); return self._result(focus=focus,hours=hours,world_time=target,**metrics)
        if t=="cohort_training":
            p="state/forces/sword-manor.json"; doc=_deepcopy(self.read(p)); doc["cohort_training_hours"]=int(doc.get("cohort_training_hours",0))+int(payload.get("hours",1)); self.put(p,doc); self._write_meta(command); return self._result(cohort_ref=payload.get("cohort_ref","sword_manor"))
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
                fp=f"state/forces/state-{state}.json"; force=_deepcopy(self.read(fp)); role=str(payload.get("role","line_infantry")); force["headcount"]+=n; force["available_by_role"][role]=int(force["available_by_role"].get(role,0))+n; self.put(fp,force)
            self._write_meta(command); return self._result(state=state,personnel=n)
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
            if int(force["available_by_role"].get(role,0))<n: raise ValueError("insufficient conserved force role pool")
            force["available_by_role"][role]-=n
            equipment_pool=self._force_equipment_pool(force); requested_equipment=int(payload.get("equipment_units",int(round(n*0.8)))); equipped=min(n,max(0,requested_equipment),int(equipment_pool.get(role,0))); equipment_pool[role]=int(equipment_pool.get(role,0))-equipped
            force.setdefault("allocated_to_formations",{})[ref]={"personnel":n,"role":role}; self.put(fp,force)
            path=f"state/formations/{ref.replace('formation_','').replace('_','-')}.json"; f={"schema":"sword-formation","formation_ref":ref,"name":str(payload.get("name",ref)),"owner_force_ref":f"force_state_{state}","administrative_owner":f"state_{state}","command_authority":str(payload.get("command_authority",f"state_{state}")),"commander_ref":payload.get("commander_ref"),"personnel":n,"composition":{role:n},"location_ref":str(payload.get("location_ref",self.read(f"state/depots/{state}.json")["location_ref"])),"doctrine_ref":payload.get("doctrine_ref"),"training_ref":payload.get("training_ref"),"doctrine_behavior":{"casualty_tolerance":"moderate","reserve_commitment":50},"training_progress":0,"readiness":50,"morale":65,"cohesion":55,"fatigue":0,"experience":"new","mobilized":False,"status":"forming","logistics":{"food_kg":0,"fodder_kg":0,"war_arrows":0},"mounts":{}}
            self._set_equipment_units(f,{role:equipped})
            self.put(path,f); self._register_owner(ref,path); self._write_meta(command); return self._result(formation_ref=ref,personnel=n)
        if t in {"formation_reconstitute","formation_train","formation_mobilize","formation_demobilize","formation_doctrine_set","formation_training_set","formation_assign","force_assignment","command_assign","command_transfer","formation_move","resupply"}:
            ref=str(payload["formation_ref"]); p,f0=self._load_formation(ref); f=_deepcopy(f0)
            if t=="formation_reconstitute":
                target=int(payload.get("target_personnel",f["personnel"])); need=max(0,target-int(f["personnel"])); fp=self.owner_path(f["owner_force_ref"]); force=_deepcopy(self.read(fp)); role=next(iter(f.get("composition",{"line_infantry":1}))); take=min(need,int(force["available_by_role"].get(role,0))); force["available_by_role"][role]-=take; f["personnel"]+=take; f["composition"][role]=int(f["composition"].get(role,0))+take
                equipment=self._equipment_units(f); equipment_pool=self._force_equipment_pool(force); desired=int(payload.get("equipment_units",take)); gear_take=min(take,max(0,desired),int(equipment_pool.get(role,0))); equipment_pool[role]=int(equipment_pool.get(role,0))-gear_take; equipment[role]=int(equipment.get(role,0))+gear_take; self._set_equipment_units(f,equipment)
                force["allocated_to_formations"][ref]={"personnel":f["personnel"],"role":role}; self.put(fp,force)
            elif t=="formation_train": f["training_progress"]=_clamp(int(f.get("training_progress",0))+int(payload.get("hours",1))); f["cohesion"]=_clamp(int(f.get("cohesion",50))+int(payload.get("hours",1))//4); f["fatigue"]=_clamp(int(f.get("fatigue",0))+int(payload.get("hours",1))//5)
            elif t=="formation_mobilize": f["mobilized"]=True; f["status"]="mobilized"
            elif t=="formation_demobilize": f["mobilized"]=False; f["status"]="ready"
            elif t=="formation_doctrine_set": f["doctrine_ref"]=payload.get("doctrine_ref"); f["doctrine_behavior"]=dict(payload.get("doctrine_behavior",f.get("doctrine_behavior",{})))
            elif t=="formation_training_set": f["training_ref"]=payload.get("training_ref")
            elif t in {"formation_assign","force_assignment","command_assign","command_transfer"}: f["command_authority"]=str(payload.get("command_authority",payload.get("commander_ref",f.get("command_authority")))); f["commander_ref"]=payload.get("commander_ref",f.get("commander_ref"))
            elif t=="formation_move":
                dest=str(payload["destination_ref"]); origin=f["location_ref"]; route=self._find_route(origin,dest); hours=int(route.get("duration_hours",route.get("hours",24))); food=max(0,int(math.ceil(int(f["personnel"])*0.8*hours/24))); fod=max(0,int(math.ceil(sum(int(v) for v in f.get("mounts",{}).values())*4*hours/24))); 
                if int(f["logistics"].get("food_kg",0))<food or int(f["logistics"].get("fodder_kg",0))<fod: raise ValueError("formation lacks field supply for strategic movement")
                f["logistics"]["food_kg"]-=food; f["logistics"]["fodder_kg"]-=fod; f["location_ref"]=dest; f["fatigue"]=_clamp(int(f.get("fatigue",0))+max(1,hours//12))
            elif t=="resupply":
                dp,depot=self._material_depot(f)
                if depot.get("location_ref") and depot.get("location_ref")!=f.get("location_ref"): raise ValueError("resupply requires physical depot access")
                requests={"food_kg":int(payload.get("food_kg",int(f["personnel"])*5)),"fodder_kg":int(payload.get("fodder_kg",0)),"war_arrows":int(payload.get("war_arrows",0))}; mapkey={"food_kg":"grain_kg","fodder_kg":"fodder_kg","war_arrows":"war_arrows"}
                for k,n in requests.items(): take=min(n,int(depot["stocks"].get(mapkey[k],0))); depot["stocks"][mapkey[k]]-=take; f["logistics"][k]=int(f["logistics"].get(k,0))+take
                self.put(dp,depot)
            self.put(p,f); self._write_meta(command); return self._result(formation_ref=ref,status=f.get("status"))
        if t in {"formation_split","formation_merge","formation_dissolve"}:
            if t=="formation_split":
                ref=str(payload["formation_ref"]); p,f0=self._load_formation(ref); original=_deepcopy(f0); f=_deepcopy(f0); new_ref=str(payload["new_formation_ref"]); n=int(payload["personnel"]); 
                if n<=0 or n>=int(f["personnel"]): raise ValueError("invalid split personnel")
                total=int(original["personnel"]); f["personnel"]=total-n; parent_comp,child_comp=self._partition_counts(original.get("composition",{}),n,total); f["composition"]=parent_comp; new=_deepcopy(original); new["formation_ref"]=new_ref; new["name"]=str(payload.get("name",new_ref)); new["personnel"]=n; new["composition"]=child_comp
                f["logistics"],new["logistics"]=self._partition_material(original.get("logistics",{}),n,total); f["mounts"],new["mounts"]=self._partition_material(original.get("mounts",{}),n,total); parent_eq,child_eq=self._partition_material(self._equipment_units(original),n,total); self._set_equipment_units(f,parent_eq); self._set_equipment_units(new,child_eq)
                np=f"state/formations/{new_ref.replace('formation_','').replace('_','-')}.json"; fp=self.owner_path(f["owner_force_ref"]); force=_deepcopy(self.read(fp)); role=next(iter(f["composition"])); force["allocated_to_formations"][ref]={"personnel":f["personnel"],"role":role}; force["allocated_to_formations"][new_ref]={"personnel":n,"role":next(iter(new["composition"]))}; self.put(fp,force); self.put(p,f); self.put(np,new); self._register_owner(new_ref,np); self._write_meta(command); return self._result(formation_ref=ref,new_formation_ref=new_ref)
            refs=list(payload.get("formation_refs",[]));
            if t=="formation_merge":
                if len(refs)<2: raise ValueError("merge requires at least two formations")
                primary=refs[0]; pp,pf0=self._load_formation(primary); pf=_deepcopy(pf0); fp=self.owner_path(pf["owner_force_ref"]); force=_deepcopy(self.read(fp)); members=[pf]
                for ref in refs[1:]:
                    p,f=self._load_formation(ref)
                    if f.get("owner_force_ref")!=pf.get("owner_force_ref"): raise ValueError("merge requires one conserved owner force")
                    if f.get("location_ref")!=pf.get("location_ref"): raise ValueError("merge requires co-located formations")
                    members.append(_deepcopy(f)); self.delete(p); self._unregister_owner(ref); force["allocated_to_formations"].pop(ref,None)
                total=sum(int(x["personnel"]) for x in members); pf["personnel"]=total; pf["composition"]=self._merge_material(*(x.get("composition",{}) for x in members)); pf["logistics"]=self._merge_material(*(x.get("logistics",{}) for x in members)); pf["mounts"]=self._merge_material(*(x.get("mounts",{}) for x in members)); self._set_equipment_units(pf,self._merge_material(*(self._equipment_units(x) for x in members)))
                for field in ("readiness","morale","cohesion","fatigue","training_progress"):
                    pf[field]=_clamp(int(round(sum(int(x.get(field,0))*int(x["personnel"]) for x in members)/max(1,total))))
                role=next(iter(pf["composition"])); force["allocated_to_formations"][primary]={"personnel":total,"role":role}; self.put(pp,pf); self.put(fp,force); self._write_meta(command); return self._result(formation_ref=primary,personnel=total)
            ref=str(payload.get("formation_ref",refs[0] if refs else "")); p,f=self._load_formation(ref); fp=self.owner_path(f["owner_force_ref"]); force=_deepcopy(self.read(fp));
            for role,count in f.get("composition",{}).items(): force["available_by_role"][role]=int(force["available_by_role"].get(role,0))+int(count)
            equipment_pool=self._force_equipment_pool(force)
            for role,count in self._equipment_units(f).items(): equipment_pool[role]=int(equipment_pool.get(role,0))+int(count)
            force["allocated_to_formations"].pop(ref,None); self.put(fp,force); self._return_formation_materials(f); self.delete(p); self._unregister_owner(ref); self._write_meta(command); return self._result(dissolved=ref)
        if t=="battle_resolve":
            result=self._battle(command,payload); self._write_meta(command); return self._result(**result)
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
            def combat_score(person:Mapping[str,Any])->float:
                skills=person.get("skills",{}); attrs=person.get("attributes",{}); weapon=max((_fixed(skills.get(k,0)) for k in ("Sword","Spear","Grappling","Unarmed","Defense","Bow")),default=0.0); support=sum(_fixed(attrs.get(k,0)) for k in ("Agility","Awareness","Coordination","Composure","Endurance"))/5.0; fatigue=max(0,int(person.get("fatigue",0))); return max(1.0,weapon*0.65+support*0.35-fatigue*0.6)
            pscore=combat_score(player); oscore=combat_score(opponent); seed=int(command.digest[:12],16); jitter=((seed%2001)-1000)/100.0; margin=(pscore-oscore)+jitter*0.08; outcome="win" if margin>4 else ("loss" if margin<-4 else "draw")
            fatigue_gain=max(2,int(math.ceil(minutes/10))); player["fatigue"]=_clamp(int(player.get("fatigue",0))+fatigue_gain); opponent["fatigue"]=_clamp(int(opponent.get("fatigue",0))+fatigue_gain)
            if not spar and outcome in {"win","loss"}:
                loser=opponent if outcome=="win" else player; self._set_person_health(loser,"injured"); loser["injury_state"]={"label":"personal combat injury","severity":"moderate","inflicted_at":self.read("state/runtime.json")["world_time"],"minimum_recovery_hours":24,"recovered_hours":0,"active":True}
            current=CampaignTime.parse(self.read("state/runtime.json")["world_time"]); target=current.add_seconds(minutes*60).__str__(); metrics=self._advance_runtime(target); self.put("state/player.json",player); self.put(opponent_path,opponent); hist=_deepcopy(self.read("state/history/events/index.json")); eid="personal_combat_"+command.digest[:16]; hist.setdefault("events",[]).append({"event_id":eid,"kind":"personal_combat","at":str(current),"completed_at":target,"actor_ref":self.PLAYER_ACTOR,"opponent_ref":opponent_ref,"location_ref":player_loc,"objective":objective,"spar":spar,"outcome":outcome}); self.put("state/history/events/index.json",hist); self._write_meta(command,target); return self._result(outcome=outcome,scale="exact_personal",opponent_ref=opponent_ref,location_ref=player_loc,duration_minutes=minutes,world_time=target,score_scale=100,player_score=int(round(pscore*100)),opponent_score=int(round(oscore*100)),**metrics)
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
            idxp="state/information/index.json"; idx=_deepcopy(self.read(idxp));
            if t=="information_create":
                ref=str(payload["information_ref"]); path=f"state/information/{ref}.json"; doc={"schema":"sword-information","owner_id":ref,"information_ref":ref,"fact":str(payload.get("claim",payload.get("fact",""))),"claim":str(payload.get("claim",payload.get("fact",""))),"confidence":str(payload.get("confidence","1.0")),"provenance":str(payload.get("provenance","direct")),"knowers":list(payload.get("knowers",[])),"created_at":command.submitted_at}; self.put(path,doc); idx.setdefault("claims",{})[ref]=path; self.put(idxp,idx); self._register_owner(ref,path); self._write_meta(command); return self._result(information_ref=ref)
            ref=str(payload["information_ref"]); path=idx.get("claims",{}).get(ref); doc=_deepcopy(self.read(path)); target=str(payload.get("target_ref",self.PLAYER_ACTOR)); knowers=doc.setdefault("knowers",[]); 
            if target not in knowers: knowers.append(target)
            self.put(path,doc); self._write_meta(command); return self._result(information_ref=ref,delivered_to=target)
        if t=="institution_project":
            ref=str(payload["institution_ref"]); p=self.owner_path(ref); doc=_deepcopy(self.read(p)); doc.setdefault("projects",[]).append({"project_ref":str(payload.get("project_ref","project_"+command.digest[:8])),"kind":str(payload.get("kind","capacity")),"status":"active","started_at":command.submitted_at}); self.put(p,doc); self._write_meta(command); return self._result(institution_ref=ref)
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
        if t in {"market_purchase","economy_transfer","enlisted_service_pay"}:
            walletp="state/economy/player-wallet.json"; wallet=_deepcopy(self.read(walletp))
            if t=="market_purchase":
                marketp="state/markets/kanyou.json"; market=_deepcopy(self.read(marketp)); item=str(payload["item_key"]); qty=int(payload.get("quantity",1)); econ=self.read("game/data/mechanics/economy-gold.json"); prices=econ.get("prices_silver",econ.get("prices",{})); price=_fixed(prices.get(item)); total=int(round(price*qty));
                player_location=self.read("state/player.json").get("location")
                if player_location != market.get("location_ref"):
                    raise ValueError("market purchase requires lawful physical market access")
                if int(market["stock"].get(item,0))<qty: raise ValueError("insufficient market stock")
                if int(wallet.get("silver",0))<total: raise ValueError("insufficient player funds")
                wallet["silver"]-=total; market["stock"][item]-=qty; ep="state/economy/private/qin.json"; eco=_deepcopy(self.read(ep)); eco["cash_silver"]=int(eco.get("cash_silver",0))+total; self.put(ep,eco); self.put(marketp,market); invp="state/economy/player-inventory.json"; inv=_deepcopy(self.read_optional(invp) or {"schema":"sword-player-inventory","owner_id":"inventory_char_tang_wei","items":{}}); inv["items"][item]=int(inv["items"].get(item,0))+qty; self.put(invp,inv); self._register_owner("inventory_char_tang_wei",invp); result={"item":item,"quantity":qty,"spent_silver":total}
            else:
                state=self._state_key(payload.get("state","qin")); sp=f"state/states/{state}.json"; sd=_deepcopy(self.read(sp)); amount=int(payload.get("amount_silver",7 if t=="enlisted_service_pay" else 0));
                if t=="economy_transfer" and payload.get("direction")=="player_to_state":
                    if int(wallet["silver"]) < amount:
                        raise ValueError("insufficient funds")
                    wallet["silver"] -= amount
                    sd["treasury_silver"] += amount
                else:
                    if int(sd["treasury_silver"]) < amount:
                        raise ValueError("state treasury insufficient")
                    sd["treasury_silver"] -= amount
                    wallet["silver"] += amount
                self.put(sp,sd); result={"amount_silver":amount,"state":state}
            self.put(walletp,wallet); self._write_meta(command); return self._result(**result)
        if t=="fortification_materialize":
            ref=str(payload["fortification_ref"]); loc=str(payload["location_ref"]); profiles=self.read("game/data/world/fortification-profiles.json"); profile=next((p for p in profiles.get("profiles",[]) if p.get("site_ref",p.get("location_ref"))==loc),None)
            if not profile: raise ValueError("location has no fortification profile")
            garr=list(payload.get("garrison_formation_refs",[]));
            if not garr: raise ValueError("fortification requires exact saved garrison")
            for fr in garr:
                _,gf=self._load_formation(fr)
                if gf.get("location_ref")!=loc: raise ValueError("fortification garrison must already be at the exact fortified site")
            path=f"state/fortifications/{ref}.json"; doc={"schema":"sword-fortification","owner_id":ref,"fortification_ref":ref,"site_ref":loc,"location_ref":loc,"profile":profile,"integrity":int(payload.get("integrity",100)),"garrison_formation_refs":garr,"food_kg":int(payload.get("food_kg",100000)),"fodder_kg":int(payload.get("fodder_kg",0)),"commander_ref":payload.get("commander_ref"),"state":self._state_key(payload.get("state","qin"))}; self.put(path,doc); idx=_deepcopy(self.read("state/fortifications/index.json")); idx.setdefault("fortifications",{})[ref]=path; self.put("state/fortifications/index.json",idx); self._register_owner(ref,path); self._write_meta(command); return self._result(fortification_ref=ref)
        if t in {"siege_start","siege_action"}:
            idxp="state/sieges/index.json"; idx=_deepcopy(self.read(idxp))
            if t=="siege_start":
                ref=str(payload["siege_ref"]); fort_ref=str(payload["fortification_ref"]); _,fort=self.owner(fort_ref); path=f"state/sieges/{ref}.json"; doc={"schema":"sword-siege","owner_id":ref,"siege_ref":ref,"fortification_ref":fort_ref,"attacker_formation_refs":list(payload.get("attacker_formation_refs",[])),"defender_formation_refs":list(fort.get("garrison_formation_refs",[])),"status":"active","days":0,"casualties":{},"started_at":command.submitted_at};
                if not doc["attacker_formation_refs"]: raise ValueError("siege requires exact attacker formations")
                for fr in doc["attacker_formation_refs"]+doc["defender_formation_refs"]:
                    _,sf=self._load_formation(fr)
                    if sf.get("location_ref")!=fort.get("location_ref"): raise ValueError("siege requires exact physical contact at the fortified site")
                    if not bool(sf.get("mobilized",False)): raise ValueError("siege participants must be mobilized")
                self.put(path,doc); idx.setdefault("sieges",{})[ref]=path; self.put(idxp,idx); self._register_owner(ref,path); self._write_meta(command); return self._result(siege_ref=ref,status="active")
            ref=str(payload["siege_ref"]); path=idx.get("sieges",{}).get(ref); siege=_deepcopy(self.read(path)); action=str(payload["action"]); fp=self.owner_path(siege["fortification_ref"]); fort=_deepcopy(self.read(fp))
            if action=="blockade": days=int(payload.get("days",7)); siege["days"]+=days; consumption=days*sum(int(self._load_formation(fr)[1]["personnel"]) for fr in fort["garrison_formation_refs"]); fort["food_kg"]=max(0,int(fort.get("food_kg",0))-consumption)
            elif action=="repair": state=fort["state"]; sp=f"state/states/{state}.json"; sd=_deepcopy(self.read(sp)); points=int(payload.get("points",5)); cost=points*1000; ifood=points*100; 
            elif action=="assault":
                result=self._battle(command,{"attacker_formation_refs":siege["attacker_formation_refs"],"defender_formation_refs":fort["garrison_formation_refs"]},context={"kind":"siege_assault","contact_ref":ref,"location_ref":fort["location_ref"]}); siege["casualties"].update(result["casualties"]); fort["integrity"]=_clamp(int(fort.get("integrity",100))-int(payload.get("damage",10))); siege["last_assault_event"]=result["battle_event"]
            elif action in {"withdraw","settle","relief"}: siege["status"]="withdrawn" if action=="withdraw" else "settled"
            if action=="repair":
                state=fort["state"]; sp=f"state/states/{state}.json"; sd=_deepcopy(self.read(sp)); points=int(payload.get("points",5)); cost=points*1000; food=points*100
                if sd["treasury_silver"]<cost or fort["food_kg"]<food: raise ValueError("insufficient repair resources")
                sd["treasury_silver"]-=cost; fort["food_kg"]-=food; fort["integrity"]=_clamp(int(fort.get("integrity",0))+points); self.put(sp,sd)
            self.put(fp,fort); self.put(path,siege); self._write_meta(command); return self._result(siege_ref=ref,status=siege["status"],action=action)
        if t=="territorial_consequence":
            loc=str(payload["location_ref"]); controller=str(payload["controller"]); terr=_deepcopy(self.read("state/territory/control.json")); site=terr["sites"].get(loc)
            if not site: raise ValueError("unknown strategic territory")
            if site.get("fortified") and not payload.get("siege_ref"): raise ValueError("fortified territorial control requires siege settlement evidence")
            if payload.get("siege_ref"):
                _,sg=self.owner(str(payload["siege_ref"]));
                if sg.get("status") not in {"settled","captured"}: raise ValueError("siege is not settled")
            site["controller"]=controller; self.put("state/territory/control.json",terr); self._write_meta(command); return self._result(location_ref=loc,controller=controller)
        if t=="family_event":
            house_ref=str(payload.get("house_ref","house_tang")); p=self.owner_path(house_ref); house=_deepcopy(self.read(p)); kind=str(payload["kind"]); cohort=house.setdefault("lineage_cohort",{})
            if kind=="birth": cohort["children"]=int(cohort.get("children",0))+1
            elif kind=="marriage": cohort["marriages"]=int(cohort.get("marriages",0))+1
            elif kind=="death": cohort["adults"]=max(0,int(cohort.get("adults",0))-1)
            house.setdefault("family_events",[]).append({"kind":kind,"at":command.submitted_at,"person_ref":payload.get("person_ref")}); self.put(p,house); self._write_meta(command); return self._result(house_ref=house_ref,kind=kind)
        if t=="repair":
            if command.actor_id!=self.INTERNAL_ACTOR or command.mode!="maintenance": raise PermissionError("repair requires trusted internal maintenance actor")
            path=str(payload["path"]); before=self.read(path); after=_deepcopy(before); changes=dict(payload.get("changes",{})); after.update(changes); self.put(path,after); hist=_deepcopy(self.read("state/history/events/index.json")); eid="repair_"+command.digest[:16]; hist.setdefault("events",[]).append({"event_id":eid,"kind":"explicit_repair","at":command.submitted_at,"path":path,"reason":str(payload.get("reason","confirmed campaign-state repair"))}); self.put("state/history/events/index.json",hist); self._write_meta(command); return self._result(repair_event=eid,path=path)
        raise ValueError("unsupported Sword semantic command: %s" % t)

    def preview(self, command: CommandEnvelope) -> CommandPlan:
        self._reset(); self._authorize(command)
        if self.store.campaign_id()!=command.campaign_id: raise ValueError("campaign mismatch")
        self.store.require_revision(command.expected_revision)
        payload=thaw_json(command.payload)
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
