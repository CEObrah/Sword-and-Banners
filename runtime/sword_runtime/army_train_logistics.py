"""Lightweight aggregate army transport and camp logistics.

The moving army/formation owns its real food, fodder, ammunition and other cargo.
This owner persists only the aggregate transport capacity physically assigned to
carry that burden, its condition, route/camp footprint, and delay/corridor state.
It never models individual wagons, drivers, guards, camp sectors, or cargo copies.
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


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def train_ref_for_group(command_group_ref: str) -> str:
    return f"army_train.{_digest(command_group_ref)}"


def train_path_for_group(command_group_ref: str) -> str:
    return f"state/logistics/army-trains/army-train-{_digest(command_group_ref)}.json"


def train_ref_for_formation(formation_ref: str) -> str:
    return f"formation_train.{_digest('formation:' + str(formation_ref))}"


def train_path_for_formation(formation_ref: str) -> str:
    return f"state/logistics/army-trains/formation-train-{_digest('formation:' + str(formation_ref))}.json"


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


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
            state = admin.removeprefix("state_") if admin.startswith("state_") else force.removeprefix("force_state_") if force.startswith("force_state_") else ""
            if state in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
                add(f"state_depot_{state}")
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

    def _load_transport_depot(self, depot_ref: str, origin: str) -> tuple[str, dict[str, Any]] | None:
        try:
            path = self.owner_path(depot_ref); doc = self.read(path)
        except (KeyError, ValueError, FileNotFoundError):
            return None
        if not isinstance(doc, Mapping):
            return None
        location = str(doc.get("location_ref") or doc.get("site_ref") or "")
        if not location or not self._same_logistics_site(location, origin):
            return None
        return path, copy.deepcopy(dict(doc))

    def _register_train(self, train: Mapping[str, Any], path: str) -> None:
        index = copy.deepcopy(self.read(INDEX_PATH))
        ref = str(train["owner_id"])
        index.setdefault("trains", {})[ref] = path
        index["active_refs"] = sorted(set([str(x) for x in index.setdefault("active_refs", []) if isinstance(x, str)] + [ref]))
        self.put(INDEX_PATH, index)
        owners = copy.deepcopy(self.read("state/index/owner-index.json"))
        owners.setdefault("owners", {})[ref] = path
        self.put("state/index/owner-index.json", owners)

    def _new_train(self, *, ref: str, movement_owner_kind: str, movement_owner_ref: str, location_ref: str, cargo_refs: list[str]) -> dict[str, Any]:
        return {
            "schema": "sword-army-train",
            "owner_id": ref,
            "movement_owner_kind": movement_owner_kind,
            "movement_owner_ref": movement_owner_ref,
            "location_ref": location_ref,
            "status": "assembled",
            "transport_capacity_equivalents": 0,
            "transport_condition": 1.0,
            "baggage_burden_equivalents": 0,
            "cargo_custody_refs": list(cargo_refs),
            "relief_corridor_route_refs": [],
            "geography": {
                "owns_local_population": False,
                "rule": "aggregate transport owner only; formations own cargo and forces own people",
            },
        }

    def _effective_transport(self, train: Mapping[str, Any]) -> int:
        return max(0, int(math.floor(max(0, int(train.get("transport_capacity_equivalents", 0))) * _clamp01(train.get("transport_condition", 1.0)))))

    def _allocate_transport(self, train: dict[str, Any], *, need_effective: int, formations: list[Mapping[str, Any]], origin: str, at: str) -> None:
        need = max(0, int(need_effective) - self._effective_transport(train))
        if need <= 0:
            return
        old_capacity = max(0, int(train.get("transport_capacity_equivalents", 0)))
        old_condition = _clamp01(train.get("transport_condition", 1.0))
        allocated = 0
        for depot_ref in self._army_train_candidate_depots(formations, origin):
            loaded = self._load_transport_depot(depot_ref, origin)
            if loaded is None:
                continue
            depot_path, depot = loaded
            stocks = depot.setdefault("stocks", {})
            available = max(0, int(stocks.get("carts", 0)))
            take = min(need - allocated, available)
            if take <= 0:
                continue
            stocks["carts"] = available - take
            depot.setdefault("transfer_history", []).append({
                "at": at,
                "reason": f"aggregate military transport allocation for {train['movement_owner_ref']}",
                "moved": {"transport_capacity_equivalents": take},
                "destination_ref": train["owner_id"],
            })
            depot["transfer_history"] = depot["transfer_history"][-24:]
            self.put(depot_path, depot)
            allocated += take
            if allocated >= need:
                break
        if allocated < need:
            raise ValueError(f"movement requires {need_effective} transport equivalents; only {self._effective_transport(train)+allocated} are physically available")
        new_capacity = old_capacity + allocated
        weighted_serviceable = old_capacity * old_condition + allocated
        train["transport_capacity_equivalents"] = new_capacity
        train["transport_condition"] = round(weighted_serviceable / max(1, new_capacity), 6)

    def _prepare_common(self, *, train_ref: str, train_path: str, movement_owner_kind: str, movement_owner_ref: str, formations: list[Mapping[str, Any]], formation_refs: list[str], origin: str, plan: Mapping[str, Any], route: Mapping[str, Any], at: str) -> dict[str, Any]:
        burden = max(0, int(plan.get("required_wagon_equivalents", 0)))
        if burden <= 0:
            return {"army_train_ref": None, "required_wagon_equivalents": 0}
        existing = self.read_optional(train_path)
        if isinstance(existing, Mapping):
            train = copy.deepcopy(dict(existing))
            if str(train.get("movement_owner_ref")) != movement_owner_ref:
                raise ValueError("army transport owner mismatch")
            if str(train.get("location_ref", "")) != origin:
                raise ValueError("army transport is not physically assembled with its movement owner")
        else:
            train = self._new_train(
                ref=train_ref, movement_owner_kind=movement_owner_kind, movement_owner_ref=movement_owner_ref,
                location_ref=origin, cargo_refs=[f"{ref}#logistics" for ref in formation_refs],
            )
            self._register_train(train, train_path)
        delayed = train.get("delayed_until")
        if isinstance(delayed, str) and delayed:
            if CampaignTime.parse(delayed) > CampaignTime.parse(at):
                raise ValueError(f"army baggage transport is delayed until {delayed}")
            train.pop("delayed_until", None)
        self._allocate_transport(train, need_effective=burden, formations=formations, origin=origin, at=at)
        personnel = sum(max(0, int(f.get("personnel", 0))) for f in formations)
        mechanics = self.read(MECHANICS_PATH)
        duty_rate = max(0.0, float(mechanics.get("service_duty_personnel_per_transport_equivalent", 1.25)))
        duty_people = int(math.ceil(burden * duty_rate))
        if duty_people > personnel:
            raise ValueError("army lacks enough existing personnel for aggregate transport service duty")
        train["baggage_burden_equivalents"] = burden
        train["service_duty_fraction"] = round(duty_people / max(1, personnel), 6)
        train["cargo_custody_refs"] = [f"{ref}#logistics" for ref in formation_refs]
        train["formation_refs"] = list(formation_refs)
        train["route_refs"] = list(route.get("route_refs", []))
        train["status"] = "in_column"
        train["last_departed_at"] = at
        train["last_origin_ref"] = origin
        self.put(train_path, train)
        return {"army_train_ref": train_ref, "army_train_path": train_path, "required_wagon_equivalents": burden, "movement_owner_kind": movement_owner_kind}

    def _prepare_army_train(self, command_group_ref: str, formation_refs: list[str], formation_rows: Mapping[str, tuple[str, Mapping[str, Any]]], origin: str, plan: Mapping[str, Any], route: Mapping[str, Any], at: str) -> dict[str, Any]:
        return self._prepare_common(
            train_ref=train_ref_for_group(command_group_ref), train_path=train_path_for_group(command_group_ref),
            movement_owner_kind="recursive_army", movement_owner_ref=command_group_ref,
            formations=[formation_rows[ref][1] for ref in formation_refs], formation_refs=formation_refs,
            origin=origin, plan=plan, route=route, at=at,
        )

    def _prepare_formation_train(self, formation_ref: str, formation: Mapping[str, Any], origin: str, plan: Mapping[str, Any], route: Mapping[str, Any], at: str) -> dict[str, Any]:
        return self._prepare_common(
            train_ref=train_ref_for_formation(formation_ref), train_path=train_path_for_formation(formation_ref),
            movement_owner_kind="standalone_formation", movement_owner_ref=formation_ref,
            formations=[formation], formation_refs=[formation_ref], origin=origin, plan=plan, route=route, at=at,
        )

    def _complete_common(self, context: Mapping[str, Any], *, destination: str, completed_at: str, battle_ready_at: str, personnel: int, mounts: int) -> None:
        path = context.get("army_train_path")
        if not isinstance(path, str):
            return
        train = copy.deepcopy(self.read(path))
        ready = CampaignTime.parse(battle_ready_at) <= CampaignTime.parse(completed_at)
        mechanics = self.read(MECHANICS_PATH)
        camp = mechanics.get("camp_footprint") if isinstance(mechanics.get("camp_footprint"), Mapping) else {}
        transport = max(0, int(train.get("baggage_burden_equivalents", 0)))
        area = (
            max(0, int(personnel)) * float(camp.get("m2_per_person", 18.0))
            + max(0, int(mounts)) * float(camp.get("m2_per_mount", 18.0))
            + transport * float(camp.get("m2_per_transport_equivalent", 38.0))
        )
        train["location_ref"] = destination
        train["status"] = "encamped" if ready else "camp_forming"
        train["last_arrived_at"] = completed_at
        train["camp"] = {
            "location_ref": destination,
            "established_at": completed_at,
            "ready_at": battle_ready_at,
            "status": "established" if ready else "forming",
            "required_area_m2": int(math.ceil(area)),
            "cargo_custody_refs": list(train.get("cargo_custody_refs", [])),
            "rule": "aggregate camp footprint only; cargo and personnel remain in their existing owners",
        }
        self.put(path, train)

    def _complete_formation_train_move(self, context: Mapping[str, Any], *, formation_ref: str, formation: Mapping[str, Any], destination: str, completed_at: str, battle_ready_at: str, route: Mapping[str, Any]) -> None:
        self._complete_common(
            context, destination=destination, completed_at=completed_at, battle_ready_at=battle_ready_at,
            personnel=max(0, int(formation.get("personnel", 0))),
            mounts=sum(max(0, int(v)) for v in (formation.get("mounts", {}) or {}).values()),
        )

    def _complete_army_train_move(self, context: Mapping[str, Any], *, command_group_ref: str, formation_refs: list[str], formation_rows: Mapping[str, tuple[str, Mapping[str, Any]]], destination: str, completed_at: str, battle_ready_at: str, plan: Mapping[str, Any], route: Mapping[str, Any]) -> None:
        self._complete_common(
            context, destination=destination, completed_at=completed_at, battle_ready_at=battle_ready_at,
            personnel=sum(max(0, int(formation_rows[ref][1].get("personnel", 0))) for ref in formation_refs),
            mounts=sum(sum(max(0, int(v)) for v in (formation_rows[ref][1].get("mounts", {}) or {}).values()) for ref in formation_refs),
        )

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
        by_ref = {str(r.get("ref")): r for r in list(routes_doc.get("routes", [])) + list(routes_doc.get("local_routes", [])) if isinstance(r, Mapping) and r.get("ref")}
        current = str(location_ref)
        for ref in route_refs:
            route = by_ref.get(str(ref))
            if not isinstance(route, Mapping) or not route_is_usable(self.read, route):
                raise ValueError("relief corridor contains an unknown or unusable route")
            a, b = str(route.get("a", "")), str(route.get("b", ""))
            if current == a: current = b
            elif current == b: current = a
            else: raise ValueError("relief corridor routes must form one connected chain from the current camp")

    def _mutate_army_train(self, payload: Mapping[str, Any], at: str) -> dict[str, Any]:
        path, train = self._army_train_by_ref(str(payload["army_train_ref"]))
        action = str(payload["action"])
        capacity = max(0, int(train.get("transport_capacity_equivalents", 0)))
        condition = _clamp01(train.get("transport_condition", 1.0))
        qty = max(1, int(payload.get("quantity", 1)))
        if action == "damage_transport":
            condition = max(0.0, condition - qty / max(1, capacity))
            train["transport_condition"] = round(condition, 6)
        elif action == "destroy_transport":
            train["transport_capacity_equivalents"] = max(0, capacity - qty)
            train["transport_condition"] = round(condition, 6)
        elif action == "repair_transport":
            train["transport_condition"] = round(min(1.0, condition + qty / max(1, capacity)), 6)
        elif action == "delay_baggage":
            hours = max(1, int(payload.get("hours", 1))); train["delayed_until"] = str(CampaignTime.parse(at).add_seconds(hours * 3600)); train["status"] = "delayed"
        elif action == "clear_delay":
            train.pop("delayed_until", None); train["status"] = "encamped" if train.get("camp") else "assembled"
        elif action == "set_relief_corridor":
            refs = [str(x) for x in payload.get("route_refs", [])]; self._validate_relief_corridor(str(train.get("location_ref", "")), refs); train["relief_corridor_route_refs"] = refs
        elif action == "break_camp":
            train.pop("camp", None); train["status"] = "assembled"
        else:
            raise ValueError("unsupported army transport action")
        train["last_changed_at"] = at
        self.put(path, train)
        return {
            "army_train_ref": train["owner_id"], "action": action,
            "transport_capacity_equivalents": int(train.get("transport_capacity_equivalents", 0)),
            "transport_condition": float(train.get("transport_condition", 1.0)),
            "effective_transport_equivalents": self._effective_transport(train), "status": train.get("status"),
        }

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "army_train_action":
            if str(command.actor_id) != str(self.INTERNAL_ACTOR):
                raise PermissionError("army transport mutation is an internal causal consequence")
            at = str(self._world_time()); result = self._mutate_army_train(payload, at); world_time, metrics = self._advance_seconds(3600); self._write_meta(command, world_time); return self._result(world_time=world_time, **result, **metrics)
        if command.command_type == "formation_move":
            formation_ref = str(payload.get("formation_ref", "")); destination = str(payload.get("destination_ref", ""))
            _fp, formation0 = self._load_formation(formation_ref); formation = copy.deepcopy(dict(formation0)); origin = str(formation.get("location_ref", ""))
            route = self._find_route(origin, destination, mode="formation"); plan = formation_movement_profile(self.read, formation, route)
            context = self._prepare_formation_train(formation_ref, formation, origin, plan, route, str(self._world_time()))
            result = super()._dispatch(command, payload)
            _ap, after = self._load_formation(formation_ref); movement = after.get("operational_movement", {}) if isinstance(after.get("operational_movement"), Mapping) else {}
            completed_at = str(result.get("world_time") or movement.get("tail_arrived_at") or self._world_time()); battle_ready_at = str(movement.get("deployment_ready_at") or completed_at)
            self._complete_formation_train_move(context, formation_ref=formation_ref, formation=after, destination=destination, completed_at=completed_at, battle_ready_at=battle_ready_at, route=route)
            if isinstance(context.get("army_train_ref"), str):
                result = dict(result); result["army_train_ref"] = context["army_train_ref"]; result["required_wagon_equivalents"] = int(context.get("required_wagon_equivalents", 0))
            return result
        return super()._dispatch(command, payload)


__all__ = ["ArmyTrainLogisticsMixin", "INDEX_PATH", "MECHANICS_PATH", "train_ref_for_group", "train_ref_for_formation"]
