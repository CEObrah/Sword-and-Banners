"""Exact aggregate baggage-train and army-camp state.

One recursive army receives at most one persistent train owner.  Exact depot
cart teams are transferred into that owner.  Formation logistics remain the
cargo authority; the train stores only custody references and transport/camp
state, preventing duplicated food/ammunition owners.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.geography import enclosing_fortification_site, route_is_usable
from sword_runtime.operational_logistics import formation_movement_profile
from sword_runtime.sim.calendar import CampaignTime

INDEX_PATH = "state/logistics/army-trains/index.json"
MECHANICS_PATH = "game/data/mechanics/army-trains.json"


def _train_digest(command_group_ref: str) -> str:
    return hashlib.sha256(str(command_group_ref).encode("utf-8")).hexdigest()[:16]


def train_ref_for_group(command_group_ref: str) -> str:
    return f"army_train.{_train_digest(command_group_ref)}"


def train_path_for_group(command_group_ref: str) -> str:
    return f"state/logistics/army-trains/army-train-{_train_digest(command_group_ref)}.json"


def train_ref_for_formation(formation_ref: str) -> str:
    return f"formation_train.{_train_digest('formation:' + str(formation_ref))}"


def train_path_for_formation(formation_ref: str) -> str:
    return f"state/logistics/army-trains/formation-train-{_train_digest('formation:' + str(formation_ref))}.json"


class ArmyTrainLogisticsMixin:
    def _same_logistics_site(self, a: str, b: str) -> bool:
        if str(a) == str(b):
            return True
        try:
            fa = enclosing_fortification_site(self.read, str(a))
            fb = enclosing_fortification_site(self.read, str(b))
        except (KeyError, ValueError, FileNotFoundError):
            return False
        return bool(fa and fb and fa == fb)

    def _army_train_candidate_depots(self, formations: list[Mapping[str, Any]], origin: str) -> list[str]:
        refs: list[str] = []
        def add(ref: Any) -> None:
            if isinstance(ref, str) and ref and ref not in refs:
                refs.append(ref)
        for formation in formations:
            add(formation.get("supply_depot_ref"))
            logistics = formation.get("logistics") if isinstance(formation.get("logistics"), Mapping) else {}
            add(logistics.get("source_depot_ref"))
            admin = str(formation.get("administrative_owner", ""))
            force = str(formation.get("owner_force_ref", ""))
            if admin == "house_tang" or force in {"force_house_tang", "force_sword_manor", "force_tang_wei_personal"}:
                add("depot_house_tang")
            state = ""
            if admin.startswith("state_"):
                state = admin.replace("state_", "", 1)
            elif force.startswith("force_state_"):
                state = force.replace("force_state_", "", 1)
            if state in {"qin","zhao","chu","wei","han","yan","qi"}:
                add(f"state_depot_{state}")
        # Fortified-site depots are deterministic route candidates, not a global scan.
        try:
            fort = enclosing_fortification_site(self.read, origin)
        except (KeyError, ValueError, FileNotFoundError):
            fort = None
        if fort == "loc_kankoku_pass":
            add("state_depot_qin_kankoku")
        elif fort == "loc_tang_manor":
            add("depot_house_tang")
        elif isinstance(fort, str) and fort.startswith("loc_"):
            add("depot_fort_" + fort[4:])
        return refs

    def _load_accessible_cart_depot(self, depot_ref: str, origin: str) -> tuple[str, dict[str, Any]] | None:
        try:
            path = self.owner_path(depot_ref)
            depot0 = self.read(path)
        except (KeyError, ValueError, FileNotFoundError):
            return None
        if not isinstance(depot0, Mapping):
            return None
        location = str(depot0.get("location_ref") or depot0.get("site_ref") or "")
        if not location or not self._same_logistics_site(location, origin):
            return None
        return path, copy.deepcopy(dict(depot0))

    def _register_army_train(self, movement_owner_ref: str, train: dict[str, Any], path: str) -> None:
        index = copy.deepcopy(self.read(INDEX_PATH))
        ref = str(train["owner_id"])
        index.setdefault("trains", {})[ref] = path
        active = [str(x) for x in index.setdefault("active_refs", []) if isinstance(x, str)]
        if ref not in active:
            active.append(ref)
        index["active_refs"] = sorted(set(active))
        self.put(INDEX_PATH, index)
        owner_index = copy.deepcopy(self.read("state/index/owner-index.json"))
        owner_index.setdefault("owners", {})[ref] = path
        self.put("state/index/owner-index.json", owner_index)

    def _prepare_army_train(
        self,
        command_group_ref: str,
        formation_refs: list[str],
        formation_rows: Mapping[str, tuple[str, Mapping[str, Any]]],
        origin: str,
        plan: Mapping[str, Any],
        route: Mapping[str, Any],
        at: str,
    ) -> dict[str, Any]:
        required = max(0, int(plan.get("required_wagon_equivalents", 0)))
        if required <= 0:
            return {"army_train_ref": None, "required_wagon_equivalents": 0}
        train_ref = train_ref_for_group(command_group_ref)
        train_path = train_path_for_group(command_group_ref)
        existing = self.read_optional(train_path)
        if isinstance(existing, Mapping):
            train = copy.deepcopy(dict(existing))
            if str(train.get("command_group_ref")) != command_group_ref:
                raise ValueError("army-train command-group authority mismatch")
            if str(train.get("location_ref", "")) != origin:
                raise ValueError("army baggage train is not physically assembled with the army")
        else:
            train = {
                "schema": "sword-army-train",
                "owner_id": train_ref,
                "movement_owner_kind": "recursive_army",
                "movement_owner_ref": command_group_ref,
                "command_group_ref": command_group_ref,
                "location_ref": origin,
                "status": "assembled",
                "cart_count": 0,
                "serviceable_cart_count": 0,
                "damaged_cart_count": 0,
                "destroyed_cart_count": 0,
                "cart_source_ledger": {},
                "cargo_custody_refs": [],
                "movement_history": [],
                "damage_history": [],
                "relief_corridor_route_refs": [],
                "geography": {"owns_local_population": False, "rule": "army train owns transport cart teams and camp arrangement only; formation ledgers own cargo and forces own people"},
            }
            self._register_army_train(command_group_ref, train, train_path)

        delayed_until = train.get("delayed_until")
        if isinstance(delayed_until, str) and delayed_until:
            if CampaignTime.parse(delayed_until) > CampaignTime.parse(at):
                raise ValueError(f"army baggage train is delayed until {delayed_until}")
            train.pop("delayed_until", None)

        serviceable = max(0, int(train.get("serviceable_cart_count", 0)))
        need = max(0, required - serviceable)
        formation_docs = [formation_rows[ref][1] for ref in formation_refs]
        if need:
            for depot_ref in self._army_train_candidate_depots(formation_docs, origin):
                loaded = self._load_accessible_cart_depot(depot_ref, origin)
                if loaded is None:
                    continue
                depot_path, depot = loaded
                stocks = depot.setdefault("stocks", {})
                available = max(0, int(stocks.get("carts", 0)))
                take = min(need, available)
                if take <= 0:
                    continue
                stocks["carts"] = available - take
                depot.setdefault("transfer_history", []).append({"at": at, "reason": f"army train allocation for {command_group_ref}", "moved": {"carts": take}, "destination_ref": train_ref})
                depot["transfer_history"] = depot["transfer_history"][-32:]
                self.put(depot_path, depot)
                train["cart_count"] = int(train.get("cart_count", 0)) + take
                train["serviceable_cart_count"] = int(train.get("serviceable_cart_count", 0)) + take
                ledger = train.setdefault("cart_source_ledger", {})
                ledger[depot_ref] = int(ledger.get(depot_ref, 0)) + take
                need -= take
                if need <= 0:
                    break
        if need > 0:
            raise ValueError(f"army movement requires {required} exact cart teams; only {required-need} are physically available with the army")

        total_personnel = sum(max(0, int(formation_rows[ref][1].get("personnel", 0))) for ref in formation_refs)
        driver_duty = required
        guard_duty = int(math.ceil(required / 4.0))
        if driver_duty + guard_duty > total_personnel:
            raise ValueError("army lacks enough existing personnel to crew and guard its exact baggage train")
        train["required_wagon_equivalents"] = required
        train["duty_allocation_requirements"] = {
            "cart_drivers": driver_duty,
            "baggage_guards": guard_duty,
            "source": "temporary aggregate duty allocation from the army's already-conserved formation personnel; creates zero bodies",
        }
        train["cargo_custody_refs"] = [f"{ref}#logistics" for ref in formation_refs]
        train["formation_refs"] = list(formation_refs)
        train["route_refs"] = list(route.get("route_refs", []))
        train["status"] = "in_column"
        train["last_departed_at"] = at
        train["last_origin_ref"] = origin
        self.put(train_path, train)
        return {"army_train_ref": train_ref, "army_train_path": train_path, "required_wagon_equivalents": required}

    def _prepare_formation_train(
        self,
        formation_ref: str,
        formation: Mapping[str, Any],
        origin: str,
        plan: Mapping[str, Any],
        route: Mapping[str, Any],
        at: str,
    ) -> dict[str, Any]:
        """Materialize one exact bounded baggage owner for an independently moving formation.

        This is the same physical cart/camp model as a recursive army train, but the
        movement owner is the formation itself.  It never creates a command group and
        it never duplicates the formation's food, ammunition, people, or mounts.
        """
        required = max(0, int(plan.get("required_wagon_equivalents", 0)))
        if required <= 0:
            return {"army_train_ref": None, "required_wagon_equivalents": 0}
        train_ref = train_ref_for_formation(formation_ref)
        train_path = train_path_for_formation(formation_ref)
        existing = self.read_optional(train_path)
        if isinstance(existing, Mapping):
            train = copy.deepcopy(dict(existing))
            if str(train.get("standalone_formation_ref")) != formation_ref:
                raise ValueError("formation-train authority mismatch")
            if str(train.get("location_ref", "")) != origin:
                raise ValueError("formation baggage train is not physically assembled with the formation")
        else:
            train = {
                "schema": "sword-army-train",
                "owner_id": train_ref,
                "movement_owner_kind": "standalone_formation",
                "movement_owner_ref": formation_ref,
                "standalone_formation_ref": formation_ref,
                "location_ref": origin,
                "status": "assembled",
                "cart_count": 0,
                "serviceable_cart_count": 0,
                "damaged_cart_count": 0,
                "destroyed_cart_count": 0,
                "cart_source_ledger": {},
                "cargo_custody_refs": [f"{formation_ref}#logistics"],
                "movement_history": [],
                "damage_history": [],
                "relief_corridor_route_refs": [],
                "geography": {
                    "owns_local_population": False,
                    "rule": "standalone formation train owns transport cart teams and camp arrangement only; the formation ledger owns cargo and the force owns people",
                },
            }
            self._register_army_train(formation_ref, train, train_path)

        delayed_until = train.get("delayed_until")
        if isinstance(delayed_until, str) and delayed_until:
            if CampaignTime.parse(delayed_until) > CampaignTime.parse(at):
                raise ValueError(f"formation baggage train is delayed until {delayed_until}")
            train.pop("delayed_until", None)

        serviceable = max(0, int(train.get("serviceable_cart_count", 0)))
        need = max(0, required - serviceable)
        if need:
            for depot_ref in self._army_train_candidate_depots([formation], origin):
                loaded = self._load_accessible_cart_depot(depot_ref, origin)
                if loaded is None:
                    continue
                depot_path, depot = loaded
                stocks = depot.setdefault("stocks", {})
                available = max(0, int(stocks.get("carts", 0)))
                take = min(need, available)
                if take <= 0:
                    continue
                stocks["carts"] = available - take
                depot.setdefault("transfer_history", []).append({
                    "at": at,
                    "reason": f"standalone formation train allocation for {formation_ref}",
                    "moved": {"carts": take},
                    "destination_ref": train_ref,
                })
                depot["transfer_history"] = depot["transfer_history"][-32:]
                self.put(depot_path, depot)
                train["cart_count"] = int(train.get("cart_count", 0)) + take
                train["serviceable_cart_count"] = int(train.get("serviceable_cart_count", 0)) + take
                ledger = train.setdefault("cart_source_ledger", {})
                ledger[depot_ref] = int(ledger.get(depot_ref, 0)) + take
                need -= take
                if need <= 0:
                    break
        if need > 0:
            raise ValueError(
                f"formation movement requires {required} exact cart teams; only {required-need} are physically available with the formation"
            )

        personnel = max(0, int(formation.get("personnel", 0)))
        driver_duty = required
        guard_duty = int(math.ceil(required / 4.0))
        if driver_duty + guard_duty > personnel:
            raise ValueError("formation lacks enough existing personnel to crew and guard its exact baggage train")
        train["required_wagon_equivalents"] = required
        train["duty_allocation_requirements"] = {
            "cart_drivers": driver_duty,
            "baggage_guards": guard_duty,
            "source": "temporary aggregate duty allocation from the formation's already-conserved personnel; creates zero bodies",
        }
        train["cargo_custody_refs"] = [f"{formation_ref}#logistics"]
        train["formation_refs"] = [formation_ref]
        train["route_refs"] = list(route.get("route_refs", []))
        train["status"] = "in_column"
        train["last_departed_at"] = at
        train["last_origin_ref"] = origin
        self.put(train_path, train)
        return {
            "army_train_ref": train_ref,
            "army_train_path": train_path,
            "required_wagon_equivalents": required,
            "movement_owner_kind": "standalone_formation",
        }

    def _complete_formation_train_move(
        self,
        context: Mapping[str, Any],
        *,
        formation_ref: str,
        formation: Mapping[str, Any],
        destination: str,
        completed_at: str,
        battle_ready_at: str,
        route: Mapping[str, Any],
    ) -> None:
        path = context.get("army_train_path")
        if not isinstance(path, str):
            return
        train0 = self.read(path)
        if not isinstance(train0, Mapping):
            raise ValueError("formation-train owner disappeared during movement")
        train = copy.deepcopy(dict(train0))
        personnel = max(0, int(formation.get("personnel", 0)))
        mounts = sum(max(0, int(v)) for v in (formation.get("mounts", {}) or {}).values())
        composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
        logistics_people = max(0, int(composition.get("logistics", 0)))
        mechanics = self.read(MECHANICS_PATH)
        space = mechanics.get("camp_space", {}) if isinstance(mechanics, Mapping) else {}
        carts = max(0, int(train.get("serviceable_cart_count", 0)))
        ready = CampaignTime.parse(battle_ready_at) <= CampaignTime.parse(completed_at)
        camp_ref = f"camp.{_train_digest('formation:' + formation_ref)}.{hashlib.sha256((destination+completed_at).encode()).hexdigest()[:10]}"
        train["location_ref"] = destination
        train["status"] = "encamped" if ready else "camp_forming"
        train["last_arrived_at"] = completed_at
        train["camp"] = {
            "camp_ref": camp_ref,
            "location_ref": destination,
            "established_at": completed_at,
            "ready_at": battle_ready_at,
            "status": "established" if ready else "forming",
            "sectors": {
                "headquarters": {"formation_ref": formation_ref},
                "baggage_park": {
                    "cart_teams": carts,
                    "required_area_m2": int(math.ceil(carts * float(space.get("baggage_park_m2_per_cart", 38)))),
                },
                "animal_lines": {
                    "formation_mounts": mounts,
                    "draft_cart_teams": carts,
                    "required_area_m2": int(math.ceil(mounts * float(space.get("animal_line_m2_per_mount", 18)))),
                },
                "kitchens": {
                    "station_requirement": max(1, int(math.ceil(personnel / max(1, int(space.get("kitchen_people_per_station", 800))))))
                },
                "sanitation": {
                    "latrine_trench_requirement": max(1, int(math.ceil(personnel / max(1, int(space.get("latrine_people_per_trench", 250))))))
                },
                "medical": {
                    "aid_station_requirement": max(1, int(math.ceil(personnel / max(1, int(space.get("medical_people_per_station", 2500))))))
                },
                "picket_line": {
                    "post_requirement": max(1, int(math.ceil(personnel / max(1, int(space.get("picket_people_per_post", 1500))))))
                },
            },
            "temporary_depot": {
                "authority": False,
                "cargo_custody_refs": [f"{formation_ref}#logistics"],
                "rule": "camp depot is a physical arrangement only; exact food/fodder/ammunition remain owned by the formation logistics ledger",
            },
            "service_capacity_evidence": {
                "logistics_personnel": logistics_people,
                "formation_personnel": personnel,
                "cart_teams": carts,
                "driver_duty_requirement": int((train.get("duty_allocation_requirements") or {}).get("cart_drivers", 0)),
                "baggage_guard_duty_requirement": int((train.get("duty_allocation_requirements") or {}).get("baggage_guards", 0)),
                "rule": "driver/guard duty is borne by already-conserved formation personnel and creates no camp followers",
            },
        }
        train.setdefault("movement_history", []).append({
            "departed_at": train.get("last_departed_at"),
            "arrived_at": completed_at,
            "origin_ref": train.get("last_origin_ref"),
            "destination_ref": destination,
            "route_refs": list(route.get("route_refs", [])),
            "required_wagon_equivalents": int(context.get("required_wagon_equivalents", 0)),
            "cart_teams_moved": carts,
        })
        train["movement_history"] = train["movement_history"][-24:]
        self.put(path, train)

    def _complete_army_train_move(
        self,
        context: Mapping[str, Any],
        *,
        command_group_ref: str,
        formation_refs: list[str],
        formation_rows: Mapping[str, tuple[str, Mapping[str, Any]]],
        destination: str,
        completed_at: str,
        battle_ready_at: str,
        plan: Mapping[str, Any],
        route: Mapping[str, Any],
    ) -> None:
        path = context.get("army_train_path")
        if not isinstance(path, str):
            return
        train0 = self.read(path)
        if not isinstance(train0, Mapping):
            raise ValueError("army-train owner disappeared during movement")
        train = copy.deepcopy(dict(train0))
        total_personnel = sum(max(0, int(formation_rows[ref][1].get("personnel", 0))) for ref in formation_refs)
        total_mounts = sum(sum(max(0, int(v)) for v in (formation_rows[ref][1].get("mounts", {}) or {}).values()) for ref in formation_refs)
        logistics_people = sum(max(0, int((formation_rows[ref][1].get("composition", {}) or {}).get("logistics", 0))) for ref in formation_refs)
        mechanics = self.read(MECHANICS_PATH)
        space = mechanics.get("camp_space", {}) if isinstance(mechanics, Mapping) else {}
        carts = max(0, int(train.get("serviceable_cart_count", 0)))
        ready = CampaignTime.parse(battle_ready_at) <= CampaignTime.parse(completed_at)
        camp_ref = f"camp.{_train_digest(command_group_ref)}.{hashlib.sha256((destination+completed_at).encode()).hexdigest()[:10]}"
        train["location_ref"] = destination
        train["status"] = "encamped" if ready else "camp_forming"
        train["last_arrived_at"] = completed_at
        train["camp"] = {
            "camp_ref": camp_ref,
            "location_ref": destination,
            "established_at": completed_at,
            "ready_at": battle_ready_at,
            "status": "established" if ready else "forming",
            "sectors": {
                "headquarters": {"command_group_ref": command_group_ref},
                "baggage_park": {"cart_teams": carts, "required_area_m2": int(math.ceil(carts * float(space.get("baggage_park_m2_per_cart", 38))))},
                "animal_lines": {"formation_mounts": total_mounts, "draft_cart_teams": carts, "required_area_m2": int(math.ceil(total_mounts * float(space.get("animal_line_m2_per_mount", 18))))},
                "kitchens": {"station_requirement": max(1, int(math.ceil(total_personnel / max(1, int(space.get("kitchen_people_per_station", 800))))))},
                "sanitation": {"latrine_trench_requirement": max(1, int(math.ceil(total_personnel / max(1, int(space.get("latrine_people_per_trench", 250))))))},
                "medical": {"aid_station_requirement": max(1, int(math.ceil(total_personnel / max(1, int(space.get("medical_people_per_station", 2500))))))},
                "picket_line": {"post_requirement": max(1, int(math.ceil(total_personnel / max(1, int(space.get("picket_people_per_post", 1500))))))},
            },
            "temporary_depot": {
                "authority": False,
                "cargo_custody_refs": [f"{ref}#logistics" for ref in formation_refs],
                "rule": "camp depot is a physical arrangement only; exact food/fodder/ammunition remain owned by formation logistics ledgers",
            },
            "service_capacity_evidence": {
                "logistics_personnel": logistics_people,
                "formation_personnel": total_personnel,
                "cart_teams": carts,
                "driver_duty_requirement": int((train.get("duty_allocation_requirements") or {}).get("cart_drivers", 0)),
                "baggage_guard_duty_requirement": int((train.get("duty_allocation_requirements") or {}).get("baggage_guards", 0)),
                "rule": "driver/guard duty is borne by already-conserved army personnel during movement and does not create camp followers",
            },
        }
        train.setdefault("movement_history", []).append({
            "departed_at": train.get("last_departed_at"), "arrived_at": completed_at,
            "origin_ref": train.get("last_origin_ref"), "destination_ref": destination,
            "route_refs": list(route.get("route_refs", [])),
            "required_wagon_equivalents": int(context.get("required_wagon_equivalents", 0)),
            "cart_teams_moved": carts,
        })
        train["movement_history"] = train["movement_history"][-24:]
        self.put(path, train)

    def _army_train_by_ref(self, train_ref: str) -> tuple[str, dict[str, Any]]:
        index = self.read(INDEX_PATH)
        path = (index.get("trains", {}) if isinstance(index, Mapping) else {}).get(train_ref)
        if not isinstance(path, str):
            raise ValueError("unknown army train")
        doc = self.read(path)
        if not isinstance(doc, Mapping):
            raise ValueError("army train route is invalid")
        return path, copy.deepcopy(dict(doc))

    def _validate_relief_corridor(self, location_ref: str, route_refs: list[str]) -> None:
        if not route_refs:
            raise ValueError("relief corridor requires at least one route")
        routes_doc = self.read("game/data/world/routes.json")
        by_ref = {str(r.get("ref")):r for r in list(routes_doc.get("routes",[]))+list(routes_doc.get("local_routes",[])) if isinstance(r,Mapping) and r.get("ref")}
        current = str(location_ref)
        for ref in route_refs:
            route = by_ref.get(str(ref))
            if not isinstance(route, Mapping) or not route_is_usable(self.read, route):
                raise ValueError("relief corridor contains an unknown or unusable route")
            a,b=str(route.get("a","")),str(route.get("b",""))
            if current == a: current=b
            elif current == b: current=a
            else: raise ValueError("relief corridor routes must form one connected chain from the current camp")

    def _mutate_army_train(self, payload: Mapping[str, Any], at: str) -> dict[str, Any]:
        path, train = self._army_train_by_ref(str(payload["army_train_ref"]))
        action = str(payload["action"])
        if action in {"damage_carts","destroy_carts","repair_carts"}:
            qty=max(1,int(payload.get("quantity",1)))
            service=max(0,int(train.get("serviceable_cart_count",0)))
            damaged=max(0,int(train.get("damaged_cart_count",0)))
            if action=="damage_carts":
                take=min(qty,service); train["serviceable_cart_count"]=service-take; train["damaged_cart_count"]=damaged+take
            elif action=="repair_carts":
                take=min(qty,damaged); train["damaged_cart_count"]=damaged-take; train["serviceable_cart_count"]=service+take
            else:
                from_service=min(qty,service); remain=qty-from_service; from_damaged=min(remain,damaged); lost=from_service+from_damaged
                train["serviceable_cart_count"]=service-from_service; train["damaged_cart_count"]=damaged-from_damaged
                train["cart_count"]=max(0,int(train.get("cart_count",0))-lost); train["destroyed_cart_count"]=int(train.get("destroyed_cart_count",0))+lost
            train.setdefault("damage_history",[]).append({"at":at,"action":action,"quantity":qty})
            train["damage_history"]=train["damage_history"][-24:]
        elif action == "delay_baggage":
            hours=max(1,int(payload.get("hours",1))); train["delayed_until"]=str(CampaignTime.parse(at).add_seconds(hours*3600)); train["status"]="delayed"
        elif action == "clear_delay":
            train.pop("delayed_until",None); train["status"]="encamped" if train.get("camp") else "assembled"
        elif action == "set_relief_corridor":
            refs=[str(x) for x in payload.get("route_refs",[])]; self._validate_relief_corridor(str(train.get("location_ref","")),refs); train["relief_corridor_route_refs"]=refs
        elif action == "break_camp":
            camp=train.get("camp") if isinstance(train.get("camp"),dict) else None
            if camp is not None: camp["status"]="broken_down"; camp["broken_down_at"]=at
            train["status"]="assembled"
        else:
            raise ValueError("unsupported army train action")
        train["last_changed_at"]=at
        self.put(path,train)
        return {"army_train_ref":train["owner_id"],"action":action,"serviceable_cart_count":int(train.get("serviceable_cart_count",0)),"damaged_cart_count":int(train.get("damaged_cart_count",0)),"destroyed_cart_count":int(train.get("destroyed_cart_count",0)),"status":train.get("status")}

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "army_train_action":
            if str(command.actor_id) != str(self.INTERNAL_ACTOR):
                raise PermissionError("army train mutation is an internal causal consequence")
            at=str(self._world_time()); result=self._mutate_army_train(payload,at); world_time,metrics=self._advance_seconds(3600); self._write_meta(command,world_time); return self._result(world_time=world_time,**result,**metrics)

        if command.command_type == "formation_move":
            formation_ref = str(payload.get("formation_ref", ""))
            destination = str(payload.get("destination_ref", ""))
            _fp, formation0 = self._load_formation(formation_ref)
            formation = copy.deepcopy(dict(formation0))
            origin = str(formation.get("location_ref", ""))
            # The downstream formation reducer remains authority for mobilization,
            # transit, field-supply, and command-staff validation. The train layer
            # only establishes the physical cart/camp owner that movement requires.
            route = self._find_route(origin, destination, mode="formation")
            plan = formation_movement_profile(self.read, formation, route)
            context = self._prepare_formation_train(formation_ref, formation, origin, plan, route, str(self._world_time()))
            result = super()._dispatch(command, payload)
            _after_path, after = self._load_formation(formation_ref)
            movement = after.get("operational_movement", {}) if isinstance(after.get("operational_movement"), Mapping) else {}
            completed_at = str(result.get("world_time") or movement.get("tail_arrived_at") or self._world_time())
            battle_ready_at = str(movement.get("deployment_ready_at") or completed_at)
            self._complete_formation_train_move(
                context,
                formation_ref=formation_ref,
                formation=after,
                destination=destination,
                completed_at=completed_at,
                battle_ready_at=battle_ready_at,
                route=route,
            )
            if isinstance(context.get("army_train_ref"), str):
                result = dict(result)
                result["army_train_ref"] = context["army_train_ref"]
                result["required_wagon_equivalents"] = int(context.get("required_wagon_equivalents", 0))
            return result

        return super()._dispatch(command,payload)
