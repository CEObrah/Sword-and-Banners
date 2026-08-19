from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.geography import shortest_path, route_is_usable
from sword_runtime.sim.calendar import CampaignTime

_REGISTRY = "state/economy/merchant-houses.json"
_INDEX = "state/economy/merchant-convoys.json"


class MerchantConvoyMixin:
    """Selective exact cargo materialization for strategically meaningful trade.

    Routine commerce remains aggregate. A materialized convoy is one exact cargo
    owner. Its cargo exists in exactly one place, its merchant silver is conserved,
    moving guards are reserved from the existing mercenary ecology, and any military
    interception requires an exact formation to meet the convoy on its route at the
    time the convoy is physically there.
    """

    def _merchant_convoy_rules(self) -> Mapping[str, Any]:
        return self.read("game/data/mechanics/merchant-convoys.json")

    def _merchant_convoy_index(self) -> dict[str, Any]:
        raw = self.read_optional(_INDEX)
        if isinstance(raw, Mapping):
            out = copy.deepcopy(dict(raw))
        else:
            out = {
                "schema": "sword-merchant-convoy-index",
                "authority": False,
                "convoys": {},
                "active_refs": [],
            }
        out.setdefault("convoys", {})
        out.setdefault("active_refs", [])
        return out

    def _merchant_convoy_exact(self, convoy_ref: str) -> tuple[str, dict[str, Any]]:
        index = self._merchant_convoy_index()
        path = (index.get("convoys", {}) or {}).get(str(convoy_ref))
        if not isinstance(path, str):
            raise ValueError("unknown merchant convoy")
        row = self.read_optional(path)
        if not isinstance(row, Mapping) or str(row.get("schema", "")) != "sword-merchant-convoy":
            raise ValueError("merchant convoy route is invalid")
        return path, copy.deepcopy(dict(row))

    def _market_routes(self) -> dict[str, tuple[str, dict[str, Any]]]:
        out: dict[str, tuple[str, dict[str, Any]]] = {}
        owner = self.read("state/index/owner-index.json")
        owners = owner.get("owners", {}) if isinstance(owner, Mapping) else {}
        for ref, path in owners.items():
            if not str(ref).startswith("market_") or not isinstance(path, str):
                continue
            doc = self.read_optional(path)
            if isinstance(doc, Mapping) and str(doc.get("schema", "")) == "sword-market":
                out[str(ref)] = (path, copy.deepcopy(dict(doc)))
        return out

    @staticmethod
    def _market_for_location(
        markets: Mapping[str, tuple[str, Mapping[str, Any]]], location_ref: str
    ) -> tuple[str, tuple[str, Mapping[str, Any]]] | None:
        for ref, pair in sorted(markets.items()):
            if str(pair[1].get("location_ref", "")) == str(location_ref):
                return ref, pair
        return None

    def _merchant_route_rows_by_ref(self) -> dict[str, dict[str, Any]]:
        doc = self.read("game/data/world/routes.json")
        rows = list(doc.get("routes", [])) + list(doc.get("local_routes", [])) if isinstance(doc, Mapping) else []
        dynamic = self.read_optional("state/geography/dynamic.json")
        if isinstance(dynamic, Mapping):
            rows.extend(dynamic.get("routes", []))
        return {
            str(row.get("ref")): dict(row)
            for row in rows
            if isinstance(row, Mapping) and isinstance(row.get("ref"), str)
        }

    def _convoy_routes_usable(self, convoy: Mapping[str, Any]) -> bool:
        by_ref = self._merchant_route_rows_by_ref()
        for ref in convoy.get("route_refs", []) if isinstance(convoy.get("route_refs"), list) else []:
            route = by_ref.get(str(ref))
            if not isinstance(route, Mapping) or not route_is_usable(self.read, route):
                return False
        return True

    def _convoy_open_war(self, source_state: str, destination_state: str) -> bool:
        if source_state == destination_state:
            return False
        treaties = self.read_optional("state/politics/treaties.json")
        if not isinstance(treaties, Mapping):
            return False
        for row in treaties.get("treaties", []):
            if not isinstance(row, Mapping):
                continue
            parties = {str(x) for x in row.get("parties", []) if isinstance(x, str)}
            if not parties:
                parties = {
                    str(row.get("a_ref", "")),
                    str(row.get("b_ref", "")),
                    str(row.get("source_ref", "")),
                    str(row.get("target_ref", "")),
                }
            state_parties = {x.removeprefix("state_") for x in parties if x}
            kind = str(row.get("kind", row.get("treaty_kind", "")))
            status = str(row.get("status", "active"))
            if {source_state, destination_state}.issubset(state_parties) and kind == "war" and status in {"active", "in_force", "open"}:
                return True
        return False

    # ------------------------------------------------------------------
    # Moving commercial guards. These are existing mercenary bodies, not
    # anonymous bonus strength and not a second troop population.
    # ------------------------------------------------------------------

    def _merchant_guard_pool(self) -> tuple[str, dict[str, Any]] | None:
        try:
            path = self.owner_path("merc.local.pool")
            pool = self.read(path)
        except (KeyError, ValueError, FileNotFoundError):
            return None
        if not isinstance(pool, Mapping):
            return None
        return path, copy.deepcopy(dict(pool))

    @staticmethod
    def _merchant_guard_region(pool: Mapping[str, Any], state: str) -> str | None:
        rows = pool.get("short_notice_available_by_location", {})
        rows = rows if isinstance(rows, Mapping) else {}
        candidates = [
            (max(0, int(v)), str(k))
            for k, v in rows.items()
            if str(k).startswith(f"loc_{state}_regional_")
        ]
        return sorted(candidates, key=lambda x: (-x[0], x[1]))[0][1] if candidates else None

    def _merchant_reserve_guards(
        self,
        convoy_ref: str,
        state: str,
        wagon_equivalents: int,
        travel_hours: int,
        house: dict[str, Any],
        regional: dict[str, Any],
        at: str,
    ) -> dict[str, Any]:
        loaded = self._merchant_guard_pool()
        rules = self._merchant_convoy_rules()
        if loaded is None:
            return {"personnel": 0, "quality": 0, "wage_silver": 0}
        path, pool = loaded
        region = self._merchant_guard_region(pool, state)
        if not region:
            return {"personnel": 0, "quality": 0, "wage_silver": 0}

        per = max(0, int(rules.get("guard_personnel_per_wagon_equivalent", 2)))
        minimum = max(0, int(rules.get("minimum_guard_personnel", 8)))
        desired = max(minimum, max(0, int(wagon_equivalents)) * per)
        role_count = 0
        for row in pool.get("classes", []) if isinstance(pool.get("classes"), list) else []:
            if isinstance(row, Mapping) and str(row.get("role")) == "caravan_guard":
                role_count = max(0, int(row.get("count", 0)))
                break
        reservations = pool.setdefault("convoy_guard_reservations", {})
        already = sum(
            max(0, int(v.get("count", 0)))
            for v in reservations.values()
            if isinstance(v, Mapping)
        )
        role_available = max(0, role_count - already)
        regional_available = max(
            0,
            int((pool.get("short_notice_available_by_location", {}) or {}).get(region, 0)),
        )
        days = max(1, int(math.ceil(max(1, travel_hours) / 24.0)))
        wage_ppd = max(1, int(rules.get("guard_hire_silver_per_person_day", 1)))
        unit_cost = max(1, days * wage_ppd)
        affordable = max(0, int(house.get("capital_silver", 0))) // unit_cost
        take = min(desired, role_available, regional_available, affordable)
        if take <= 0:
            return {"personnel": 0, "quality": 0, "wage_silver": 0}

        cost = take * unit_cost
        house["capital_silver"] = int(house.get("capital_silver", 0)) - cost
        regional["cash_silver"] = int(regional.get("cash_silver", 0)) + cost
        available_map = pool.setdefault("short_notice_available_by_location", {})
        available_map[region] = regional_available - take
        pool["short_notice_available_total"] = sum(max(0, int(v)) for v in available_map.values())
        quality = max(1, min(100, int(rules.get("guard_quality", 50))))
        reservations[convoy_ref] = {
            "count": take,
            "region_ref": region,
            "role": "caravan_guard",
            "reserved_at": at,
            "quality": quality,
        }
        self.put(path, pool)
        return {
            "personnel": take,
            "quality": quality,
            "wage_silver": cost,
            "source_ref": "merc.local.pool",
            "region_ref": region,
            "reserved_at": at,
        }

    def _merchant_apply_guard_losses_in_transit(
        self, convoy: dict[str, Any], losses: int, at: str
    ) -> int:
        guard = convoy.get("guard_detail", {})
        guard = dict(guard) if isinstance(guard, Mapping) else {}
        count = max(0, int(guard.get("personnel", 0)))
        lost = min(count, max(0, int(losses)))
        if lost <= 0:
            return 0
        loaded = self._merchant_guard_pool()
        if loaded is None:
            return 0
        path, pool = loaded
        reservations = pool.setdefault("convoy_guard_reservations", {})
        reservation = reservations.get(str(convoy.get("owner_id", "")))
        region = str((reservation or {}).get("region_ref", guard.get("region_ref", ""))) if isinstance(reservation, Mapping) else str(guard.get("region_ref", ""))
        pool["armed_total"] = max(0, int(pool.get("armed_total", 0)) - lost)
        for row in pool.get("classes", []) if isinstance(pool.get("classes"), list) else []:
            if isinstance(row, dict) and str(row.get("role")) == "caravan_guard":
                row["count"] = max(0, int(row.get("count", 0)) - lost)
                break
        regional_distribution = pool.get("regional_distribution", {})
        if isinstance(regional_distribution, dict) and region in regional_distribution:
            regional_distribution[region] = max(0, int(regional_distribution.get(region, 0)) - lost)
        if isinstance(reservation, dict):
            reservation["count"] = max(0, int(reservation.get("count", 0)) - lost)
            reservation["losses"] = int(reservation.get("losses", 0)) + lost
        guard["personnel"] = count - lost
        guard["losses"] = int(guard.get("losses", 0)) + lost
        guard["last_loss_at"] = at
        convoy["guard_detail"] = guard
        self.put(path, pool)
        return lost

    def _merchant_release_guards(
        self, convoy: dict[str, Any], *, at: str, additional_losses: int = 0
    ) -> dict[str, int]:
        if additional_losses:
            self._merchant_apply_guard_losses_in_transit(convoy, additional_losses, at)
        guard = convoy.get("guard_detail", {})
        guard = dict(guard) if isinstance(guard, Mapping) else {}
        count = max(0, int(guard.get("personnel", 0)))
        loaded = self._merchant_guard_pool()
        if loaded is None or count <= 0:
            guard["personnel"] = 0
            guard.setdefault("released_at", at)
            convoy["guard_detail"] = guard
            return {"released": 0, "lost": 0}
        path, pool = loaded
        reservations = pool.setdefault("convoy_guard_reservations", {})
        reservation = reservations.pop(str(convoy.get("owner_id", "")), None)
        region = str((reservation or {}).get("region_ref", guard.get("region_ref", ""))) if isinstance(reservation, Mapping) else str(guard.get("region_ref", ""))
        survivors = count
        if survivors and region:
            cap = max(0, int((pool.get("regional_distribution", {}) or {}).get(region, survivors)))
            available_map = pool.setdefault("short_notice_available_by_location", {})
            current = max(0, int(available_map.get(region, 0)))
            available_map[region] = min(cap, current + survivors)
            pool["short_notice_available_total"] = sum(max(0, int(v)) for v in available_map.values())
        self.put(path, pool)
        guard["personnel"] = 0
        guard["released_at"] = at
        convoy["guard_detail"] = guard
        return {"released": survivors, "lost": 0}

    # ------------------------------------------------------------------
    # Exact route chronology and disruption.
    # ------------------------------------------------------------------

    @staticmethod
    def _convoy_leg_departure(convoy: Mapping[str, Any]) -> CampaignTime:
        return CampaignTime.parse(str(convoy.get("leg_departed_at") or convoy.get("departed_at")))

    def _convoy_edge_hours(self, convoy: Mapping[str, Any]) -> list[int]:
        path = [str(x) for x in convoy.get("route_path", []) if isinstance(x, str)]
        raw = convoy.get("route_edge_hours", [])
        if isinstance(raw, list) and len(raw) == max(0, len(path) - 1):
            return [max(1, int(x)) for x in raw]
        if len(path) <= 1:
            return []
        depart = self._convoy_leg_departure(convoy)
        total = max(1, int(depart.seconds_until(CampaignTime.parse(str(convoy.get("arrives_at")))) / 3600))
        count = len(path) - 1
        base, rem = divmod(total, count)
        return [max(1, base + (1 if i < rem else 0)) for i in range(count)]

    def _convoy_progress_node(self, convoy: Mapping[str, Any], at: str) -> str:
        path = [str(x) for x in convoy.get("route_path", []) if isinstance(x, str)]
        if not path:
            return str(convoy.get("current_location_ref", ""))
        edges = self._convoy_edge_hours(convoy)
        depart = self._convoy_leg_departure(convoy)
        now = CampaignTime.parse(at)
        elapsed = max(0, int(depart.seconds_until(now) / 3600))
        cumulative = 0
        anchor = path[0]
        for i, hours in enumerate(edges):
            if elapsed < cumulative + hours:
                break
            cumulative += hours
            anchor = path[i + 1]
        return anchor

    def _convoy_node_window(self, convoy: Mapping[str, Any], node_ref: str) -> tuple[CampaignTime, CampaignTime]:
        path = [str(x) for x in convoy.get("route_path", []) if isinstance(x, str)]
        if node_ref not in path:
            raise ValueError("formation is not on the convoy route")
        idx = path.index(node_ref)
        cumulative = sum(self._convoy_edge_hours(convoy)[:idx])
        center = self._convoy_leg_departure(convoy).add_seconds(cumulative * 3600)
        window = max(1, int(self._merchant_convoy_rules().get("interception_node_window_hours", 12)))
        return center.add_seconds(-window * 3600), center.add_seconds(window * 3600)

    def _reroute_merchant_convoy(
        self,
        convoy: dict[str, Any],
        at: str,
        *,
        destination_market_ref: str | None = None,
    ) -> None:
        if destination_market_ref is not None:
            destination_path = self.owner_path(destination_market_ref)
            destination = self.read(destination_path)
            if not isinstance(destination, Mapping) or str(destination.get("schema", "")) != "sword-market":
                raise ValueError("reroute destination must be an exact market")
            convoy["destination_market_ref"] = destination_market_ref
            convoy["destination_state"] = str(destination.get("state", ""))
        else:
            destination = self.read(self.owner_path(str(convoy.get("destination_market_ref", ""))))
        origin = self._convoy_progress_node(convoy, at)
        dest = str(destination.get("location_ref", ""))
        route = shortest_path(self.read, origin, dest, modes=("convoy",))
        hours = max(1, int(route.get("duration_hours", 1)))
        convoy["original_departed_at"] = str(convoy.get("original_departed_at") or convoy.get("departed_at"))
        convoy["current_location_ref"] = origin
        convoy["leg_departed_at"] = at
        convoy["route_path"] = [str(x) for x in route.get("path", [])]
        convoy["route_refs"] = [str(x) for x in route.get("route_refs", [])]
        convoy["route_edge_hours"] = [max(1, int(x)) for x in route.get("edge_hours", [])]
        convoy["arrives_at"] = str(CampaignTime.parse(at).add_seconds(hours * 3600))
        convoy.setdefault("delay_history", []).append(
            {
                "at": at,
                "kind": "rerouted",
                "origin_ref": origin,
                "destination_market_ref": convoy.get("destination_market_ref"),
                "route_refs": list(convoy["route_refs"]),
            }
        )
        convoy["delay_history"] = convoy["delay_history"][-24:]

    # ------------------------------------------------------------------
    # Dispatch and arrival.
    # ------------------------------------------------------------------

    def _dispatch_one_merchant_convoy(
        self,
        state: str,
        house_ref: str,
        house: dict[str, Any],
        at: str,
        index: dict[str, Any],
        registry: dict[str, Any],
    ) -> bool:
        rules = self._merchant_convoy_rules()
        markets = self._market_routes()
        home_location = str(house.get("home_market_location_ref", ""))
        home = self._market_for_location(markets, home_location)
        if home is None:
            return False
        source_ref, source_pair = home
        source_path, source0 = source_pair
        source = copy.deepcopy(dict(source0))
        source_state = str(source.get("state", state))
        if source_state != str(state):
            return False
        source_stock = source.setdefault("stock", {})
        source_normal = source.get("normal_stock", {}) if isinstance(source.get("normal_stock"), Mapping) else {}
        reserve_fraction = max(0.0, min(1.0, float(rules.get("source_reserve_fraction", 0.55))))
        max_units = max(1, int(rules.get("max_market_units_per_convoy", 120)))
        max_active = max(
            1,
            int(house.get("capital_silver", 0))
            // max(1, int(rules.get("capital_silver_per_concurrent_convoy", 250000))),
        )
        current_active = 0
        for ref in index.get("active_refs", []):
            path = index.get("convoys", {}).get(str(ref))
            doc = self.read_optional(path) if isinstance(path, str) else None
            if (
                isinstance(doc, Mapping)
                and str(doc.get("merchant_house_ref", "")) == house_ref
                and str(doc.get("status", "")) in {"in_transit", "arrived_holding"}
            ):
                current_active += 1
        if current_active >= max_active:
            return False

        price_doc = self.read(str(source.get("prices_ref", "game/data/mechanics/economy.json")))
        prices = price_doc.get("prices_silver", {}) if isinstance(price_doc, Mapping) else {}
        candidates: list[tuple[int, str, str, str, int, int, dict[str, Any]]] = []
        for destination_ref, (destination_path, destination) in markets.items():
            if destination_ref == source_ref:
                continue
            destination_state = str(destination.get("state", ""))
            if not destination_state or self._convoy_open_war(source_state, destination_state):
                continue
            try:
                route = shortest_path(
                    self.read,
                    str(source.get("location_ref", "")),
                    str(destination.get("location_ref", "")),
                    modes=("convoy",),
                )
            except (ValueError, KeyError):
                continue
            destination_stock = destination.get("stock", {}) if isinstance(destination.get("stock"), Mapping) else {}
            destination_normal = destination.get("normal_stock", {}) if isinstance(destination.get("normal_stock"), Mapping) else {}
            for key in sorted(set(source_stock) & set(destination_normal)):
                source_floor = int(math.ceil(max(0, int(source_normal.get(key, 0))) * reserve_fraction))
                surplus = max(0, int(source_stock.get(key, 0)) - source_floor)
                shortage = max(0, int(destination_normal.get(key, 0)) - int(destination_stock.get(key, 0)))
                if surplus <= 0 or shortage <= 0:
                    continue
                qty = min(surplus, shortage, max_units)
                unit_price = max(1, int(round(float(prices.get(key, 1)))))
                capital = max(0, int(house.get("capital_silver", 0)))
                qty = min(qty, capital // unit_price)
                if qty <= 0:
                    continue
                score = shortage * 1000 + qty
                candidates.append((score, destination_ref, destination_path, key, qty, unit_price, dict(route)))
        if not candidates:
            return False

        _score, destination_ref, destination_path, key, qty, unit_price, route = sorted(
            candidates, key=lambda x: (-x[0], x[1], x[3])
        )[0]
        destination = copy.deepcopy(self.read(destination_path))
        cost = qty * unit_price
        if int(source_stock.get(key, 0)) < qty or int(house.get("capital_silver", 0)) < cost:
            return False
        source_stock[key] = int(source_stock.get(key, 0)) - qty
        house["capital_silver"] = int(house.get("capital_silver", 0)) - cost

        ep, eco = self._private_economy(source_state)
        _site, regional = self._local_economy_region(
            source_state, eco, str(source.get("location_ref", ""))
        )
        regional["cash_silver"] = int(regional.get("cash_silver", 0)) + cost

        token = hashlib.sha256(
            f"{house_ref}|{source_ref}|{destination_ref}|{key}|{at}|{len(index.get('convoys', {}))}".encode()
        ).hexdigest()[:18]
        convoy_ref = f"merchant_convoy_{token}"
        path = f"state/economy/convoys/{token}.json"
        hours = max(1, int(route.get("duration_hours", 1)))
        wagon_units = max(1, int(rules.get("market_units_per_wagon_equivalent", 30)))
        wagon_equivalents = max(1, int(math.ceil(qty / wagon_units)))
        guard = self._merchant_reserve_guards(
            convoy_ref,
            source_state,
            wagon_equivalents,
            hours,
            house,
            regional,
            at,
        )
        self._sync_local_economy_aggregate(eco)
        self._write_private_economy(ep, eco)

        convoy = {
            "schema": "sword-merchant-convoy",
            "owner_id": convoy_ref,
            "merchant_house_ref": house_ref,
            "source_market_ref": source_ref,
            "destination_market_ref": destination_ref,
            "source_state": source_state,
            "destination_state": str(destination.get("state", "")),
            "cargo": {key: qty},
            "purchase_cost_silver": cost,
            "status": "in_transit",
            "departed_at": at,
            "leg_departed_at": at,
            "arrives_at": str(CampaignTime.parse(at).add_seconds(hours * 3600)),
            "route_refs": [str(x) for x in route.get("route_refs", [])],
            "route_path": [str(x) for x in route.get("path", [])],
            "route_edge_hours": [max(1, int(x)) for x in route.get("edge_hours", [])],
            "wagon_equivalents": wagon_equivalents,
            "guard_detail": guard,
            "escort_formation_refs": [],
            "security_incidents": [],
            "delay_history": [],
            "current_location_ref": str(source.get("location_ref", "")),
            "rule": "one aggregate exact cargo owner; individual merchants and wagons remain unmaterialized",
        }
        self.put(source_path, source)
        self.put(path, convoy)
        self._register_owner(convoy_ref, path)
        index.setdefault("convoys", {})[convoy_ref] = path
        index.setdefault("active_refs", []).append(convoy_ref)
        index["active_refs"] = sorted(set(str(x) for x in index["active_refs"]))
        registry["last_convoy_dispatch"] = {"at": at, "convoy_ref": convoy_ref}
        return True

    def _settle_arriving_merchant_convoys(self, state: str, at: str) -> bool:
        index = self._merchant_convoy_index()
        registry = copy.deepcopy(self.read(_REGISTRY))
        houses = registry.get("houses", {}) if isinstance(registry.get("houses"), Mapping) else {}
        changed = False
        now = CampaignTime.parse(at)
        active_out: list[str] = []
        rules = self._merchant_convoy_rules()
        margin = max(1.0, float(rules.get("destination_sale_margin", 1.12)))

        for convoy_ref in list(index.get("active_refs", [])):
            path = index.get("convoys", {}).get(str(convoy_ref))
            if not isinstance(path, str):
                continue
            row = self.read_optional(path)
            if not isinstance(row, Mapping):
                continue
            convoy = copy.deepcopy(dict(row))
            if str(convoy.get("status", "")) not in {"in_transit", "arrived_holding"}:
                continue
            if str(convoy.get("status", "")) == "in_transit" and convoy.get("escort_formation_refs"):
                self._sync_convoy_escorts(convoy, at)

            if str(convoy.get("status", "")) == "in_transit" and not self._convoy_routes_usable(convoy):
                try:
                    self._reroute_merchant_convoy(convoy, at)
                except (ValueError, KeyError, FileNotFoundError):
                    convoy["arrives_at"] = str(CampaignTime.parse(at).add_seconds(24 * 3600))
                    convoy.setdefault("delay_history", []).append(
                        {"at": at, "kind": "route_blocked", "hours": 24}
                    )
                    convoy["delay_history"] = convoy["delay_history"][-24:]
                self.put(path, convoy)
                active_out.append(str(convoy_ref))
                continue

            if CampaignTime.parse(str(convoy.get("arrives_at"))) > now:
                active_out.append(str(convoy_ref))
                continue
            destination_state = str(convoy.get("destination_state", ""))
            if destination_state != state:
                active_out.append(str(convoy_ref))
                continue

            destination_path = self.owner_path(str(convoy["destination_market_ref"]))
            destination = copy.deepcopy(self.read(destination_path))
            ep, eco = self._private_economy(destination_state)
            _site, regional = self._local_economy_region(
                destination_state, eco, str(destination.get("location_ref", ""))
            )
            house_ref = str(convoy.get("merchant_house_ref", ""))
            house = houses.get(house_ref)
            if str(convoy.get("status", "")) == "in_transit":
                convoy["current_location_ref"] = str(destination.get("location_ref", ""))
                # Arrival is already due, so attached exact escorts reach the same
                # destination under the convoy chronology before duty is released.
                for escort_ref in list(convoy.get("escort_formation_refs", [])):
                    self._convoy_detach_escort(convoy, str(escort_ref), at, "convoy_arrived")
                self._merchant_release_guards(convoy, at=at)
            if not isinstance(house, dict):
                convoy["status"] = "arrived_holding"
                self.put(path, convoy)
                active_out.append(str(convoy_ref))
                continue

            price_doc = self.read(str(destination.get("prices_ref", "game/data/mechanics/economy.json")))
            prices = price_doc.get("prices_silver", {}) if isinstance(price_doc, Mapping) else {}
            remaining: dict[str, int] = {}
            sold: dict[str, int] = {}
            revenue = 0
            for key, raw_qty in convoy.get("cargo", {}).items():
                qty = max(0, int(raw_qty))
                if qty <= 0:
                    continue
                unit = max(1, int(round(float(prices.get(key, 1)) * margin)))
                affordable = max(0, int(regional.get("cash_silver", 0))) // unit
                take = min(qty, affordable)
                if take:
                    payment = take * unit
                    regional["cash_silver"] = int(regional.get("cash_silver", 0)) - payment
                    house["capital_silver"] = int(house.get("capital_silver", 0)) + payment
                    destination.setdefault("stock", {})[key] = int(destination.get("stock", {}).get(key, 0)) + take
                    sold[key] = take
                    revenue += payment
                if qty - take:
                    remaining[key] = qty - take
            convoy["cargo"] = remaining
            convoy["arrival_sale"] = {"at": at, "sold": sold, "revenue_silver": revenue}
            convoy["status"] = "delivered" if not remaining else "arrived_holding"
            self.put(destination_path, destination)
            self._sync_local_economy_aggregate(eco)
            self._write_private_economy(ep, eco)
            self.put(path, convoy)
            changed = changed or bool(sold)
            if remaining:
                active_out.append(str(convoy_ref))

        index["active_refs"] = sorted(set(active_out))
        if changed:
            registry["aggregate_capital_silver"] = sum(
                max(0, int(h.get("capital_silver", 0)))
                for h in houses.values()
                if isinstance(h, Mapping)
            )
            registry["last_convoy_arrival"] = at
            self.put(_REGISTRY, registry)
        self.put(_INDEX, index)
        return changed

    # ------------------------------------------------------------------
    # Exact military escort attachment. An assigned escort formation travels
    # on the convoy's already-paid route chronology. Its people, supply, and
    # location remain exact formation authority rather than becoming bonus
    # convoy strength.
    # ------------------------------------------------------------------

    def _convoy_detach_escort(self, convoy: dict[str, Any], formation_ref: str, at: str, reason: str) -> None:
        refs = [str(x) for x in convoy.get("escort_formation_refs", []) if isinstance(x, str)]
        convoy["escort_formation_refs"] = [x for x in refs if x != formation_ref]
        state = convoy.setdefault("escort_state", {})
        row = state.get(formation_ref) if isinstance(state, Mapping) else None
        if isinstance(row, dict):
            row["detached_at"] = at
            row["detach_reason"] = reason
        try:
            fp, f0 = self._load_formation(formation_ref)
            formation = copy.deepcopy(dict(f0))
            assignment = formation.get("convoy_escort_assignment")
            if isinstance(assignment, Mapping) and str(assignment.get("convoy_ref", "")) == str(convoy.get("owner_id", "")):
                formation.pop("convoy_escort_assignment", None)
                self.put(fp, formation)
        except (KeyError, ValueError, FileNotFoundError):
            pass

    def _sync_convoy_escorts(self, convoy: dict[str, Any], at: str) -> str:
        current = self._convoy_progress_node(convoy, at)
        convoy["current_location_ref"] = current
        refs = [str(x) for x in convoy.get("escort_formation_refs", []) if isinstance(x, str)]
        state = convoy.setdefault("escort_state", {})
        if not isinstance(state, dict):
            state = {}
            convoy["escort_state"] = state
        live: list[str] = []
        for formation_ref in refs:
            try:
                fp, f0 = self._load_formation(formation_ref)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            formation = copy.deepcopy(dict(f0))
            assignment = formation.get("convoy_escort_assignment")
            if not isinstance(assignment, Mapping) or str(assignment.get("convoy_ref", "")) != str(convoy.get("owner_id", "")):
                continue
            st = state.setdefault(formation_ref, {})
            if not isinstance(st, dict):
                st = {}
                state[formation_ref] = st
            last_location = str(st.get("last_location_ref") or formation.get("location_ref", ""))
            if str(formation.get("location_ref", "")) != last_location:
                # An exact formation moved by another lawful command, so it is no
                # longer physically attached to this convoy. Never teleport it back.
                self._convoy_detach_escort(convoy, formation_ref, at, "formation_moved_independently")
                convoy.setdefault("security_incidents", []).append({
                    "at": at, "kind": "escort_detached", "formation_ref": formation_ref,
                    "reason": "formation_moved_independently",
                })
                continue
            last_sync = str(st.get("last_sync_at") or assignment.get("joined_at") or at)
            elapsed_seconds = max(0, CampaignTime.parse(last_sync).seconds_until(CampaignTime.parse(at)))
            elapsed_hours = int(math.ceil(elapsed_seconds / 3600.0)) if elapsed_seconds else 0
            personnel = max(0, int(formation.get("personnel", 0)))
            mounts = sum(max(0, int(v)) for v in (formation.get("mounts", {}) or {}).values())
            food_need = max(0, int(math.ceil(personnel * 0.8 * elapsed_hours / 24.0)))
            fodder_need = max(0, int(math.ceil(mounts * 4.0 * elapsed_hours / 24.0)))
            logistics = formation.setdefault("logistics", {})
            if int(logistics.get("food_kg", 0)) < food_need or int(logistics.get("fodder_kg", 0)) < fodder_need:
                self._convoy_detach_escort(convoy, formation_ref, at, "field_supply_exhausted")
                convoy.setdefault("security_incidents", []).append({
                    "at": at, "kind": "escort_detached", "formation_ref": formation_ref,
                    "reason": "field_supply_exhausted", "food_need": food_need, "fodder_need": fodder_need,
                })
                continue
            if food_need:
                logistics["food_kg"] = int(logistics.get("food_kg", 0)) - food_need
            if fodder_need:
                logistics["fodder_kg"] = int(logistics.get("fodder_kg", 0)) - fodder_need
            origin = str(formation.get("location_ref", ""))
            snapshots = self._command_staff_snapshots([formation_ref]) if hasattr(self, "_command_staff_snapshots") else []
            if origin != current:
                formation["location_ref"] = current
                formation["status"] = "convoy_escort"
                formation["fatigue"] = min(100, max(0, int(formation.get("fatigue", 0))) + max(0, int(math.ceil(elapsed_hours / 12.0))))
                formation["last_convoy_escort_movement"] = {
                    "convoy_ref": convoy.get("owner_id"),
                    "from_ref": origin,
                    "to_ref": current,
                    "elapsed_hours": elapsed_hours,
                    "food_kg": food_need,
                    "fodder_kg": fodder_need,
                    "at": at,
                    "rule": "formation traveled on the convoy's exact route chronology; no second movement time was created",
                }
                self.put(fp, formation)
                self._index_formation_location(formation_ref, origin, current)
                if snapshots and hasattr(self, "_reconcile_moved_command_staff"):
                    self._reconcile_moved_command_staff(snapshots, current)
            else:
                self.put(fp, formation)
            st.update({
                "last_sync_at": at,
                "last_location_ref": current,
                "food_consumed_kg": int(st.get("food_consumed_kg", 0)) + food_need,
                "fodder_consumed_kg": int(st.get("fodder_consumed_kg", 0)) + fodder_need,
            })
            live.append(formation_ref)
        convoy["escort_formation_refs"] = sorted(set(live))
        convoy["security_incidents"] = list(convoy.get("security_incidents", []))[-24:]
        return current

    # ------------------------------------------------------------------
    # Military interaction with exact materialized convoys.
    # ------------------------------------------------------------------

    @staticmethod
    def _formation_authority_state(formation: Mapping[str, Any]) -> str:
        admin = str(formation.get("administrative_owner", ""))
        force = str(formation.get("owner_force_ref", ""))
        if admin.startswith("state_"):
            return admin.removeprefix("state_")
        if force.startswith("force_state_"):
            return force.removeprefix("force_state_")
        return str(formation.get("state", "qin") or "qin")

    def _convoy_escort_power(self, convoy: Mapping[str, Any], location_ref: str) -> tuple[float, list[str]]:
        power = 0.0
        refs: list[str] = []
        for ref in convoy.get("escort_formation_refs", []) if isinstance(convoy.get("escort_formation_refs"), list) else []:
            try:
                _path, formation = self._load_formation(str(ref))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if str(formation.get("location_ref", "")) != location_ref or int(formation.get("personnel", 0)) <= 0:
                continue
            refs.append(str(ref))
            if hasattr(self, "_autonomy_formation_power"):
                power += float(self._autonomy_formation_power(str(ref), defender=True))
            else:
                power += float(max(1, int(formation.get("personnel", 0))) * max(25, int(formation.get("readiness", 50))))
        return power, refs

    def _convoy_apply_formation_losses(
        self,
        formation_ref: str,
        losses: int,
        at: str,
        *,
        losing_side: bool,
        opponent_state: str,
        evidence_ref: str,
    ) -> dict[str, Any]:
        if losses <= 0:
            return {"loss": 0}
        # Starting after MerchantConvoyMixin in the MRO bypasses the autonomous
        # player-handoff guard while retaining the lower conservation/political
        # casualty reducers. This combat was explicitly caused by the current
        # merchant_convoy_action, so no autonomous player handoff is appropriate.
        return super(MerchantConvoyMixin, self)._autonomy_apply_battle_losses(
            formation_ref,
            losses,
            at,
            losing_side=losing_side,
            opponent_state=opponent_state,
            seed_material=evidence_ref,
        )

    def _merchant_interdict_convoy(
        self, command: Any, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        convoy_ref = str(payload.get("convoy_ref", ""))
        formation_ref = str(payload.get("formation_ref", ""))
        disposition = str(payload.get("disposition", "seize"))
        path, convoy = self._merchant_convoy_exact(convoy_ref)
        if str(convoy.get("status", "")) != "in_transit":
            raise ValueError("merchant convoy interception requires an in-transit convoy")
        self._sync_convoy_escorts(convoy, str(self._world_time()))
        fp, attacker0 = self._load_formation(formation_ref)
        attacker = copy.deepcopy(dict(attacker0))
        attacker_n = max(0, int(attacker.get("personnel", 0)))
        if attacker_n <= 0:
            raise ValueError("intercepting formation has no fighting personnel")
        location_ref = str(attacker.get("location_ref", ""))
        low, high = self._convoy_node_window(convoy, location_ref)
        now = self._world_time()
        if now < low or now > high:
            raise ValueError("convoy is not physically within the formation's interception window")
        if disposition not in {"seize", "destroy"}:
            raise ValueError("merchant convoy interception disposition must be seize or destroy")

        guard = convoy.get("guard_detail", {})
        guard = guard if isinstance(guard, Mapping) else {}
        guards = max(0, int(guard.get("personnel", 0)))
        quality = max(1, min(100, int(guard.get("quality", 50))))
        guard_factor = max(0.1, float(self._merchant_convoy_rules().get("guard_combat_factor", 0.75)))
        guard_power = float(guards * quality * guard_factor)
        escort_power, live_escorts = self._convoy_escort_power(convoy, location_ref)
        defense_power = guard_power + escort_power
        if hasattr(self, "_autonomy_formation_power"):
            attacker_power = float(self._autonomy_formation_power(formation_ref, defender=False))
        else:
            attacker_power = float(attacker_n * max(25, int(attacker.get("readiness", 50))))
        seed = hashlib.sha256(
            f"merchant-interdict|{convoy_ref}|{formation_ref}|{now}|{command.expected_revision}".encode()
        ).hexdigest()
        jitter = 0.90 + (int(seed[:8], 16) % 2101) / 10000.0
        attacker_wins = defense_power <= 0 or attacker_power * jitter >= defense_power

        if defense_power > 0:
            attacker_loss_estimate = int(
                round((guards * quality / 100.0) * (0.45 if attacker_wins else 1.35))
            )
            for ref in live_escorts:
                try:
                    _ep, e = self._load_formation(ref)
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                attacker_loss_estimate += max(
                    0,
                    int(round(min(int(e.get("personnel", 0)) * 0.02, attacker_n * 0.025))),
                )
        else:
            attacker_loss_estimate = 0
        if attacker_wins:
            attacker_loss_estimate = min(max(0, attacker_n - 1), max(0, attacker_loss_estimate))
        else:
            attacker_loss_estimate = min(attacker_n, max(0, attacker_loss_estimate))
        casualty = self._convoy_apply_formation_losses(
            formation_ref,
            attacker_loss_estimate,
            str(now),
            losing_side=not attacker_wins,
            opponent_state=str(convoy.get("source_state") or convoy.get("destination_state") or "qin"),
            evidence_ref=f"merchant_convoy_interception:{convoy_ref}",
        )

        guard_loss_rate = 0.45 if attacker_wins else 0.12
        if guards:
            guard_loss_rate += min(
                0.25,
                attacker_power / max(1.0, attacker_power + defense_power) * 0.25,
            )
        guard_losses = min(guards, max(0, int(round(guards * guard_loss_rate))))
        actual_guard_losses = self._merchant_apply_guard_losses_in_transit(
            convoy, guard_losses, str(now)
        )

        escort_losses: dict[str, int] = {}
        if live_escorts and attacker_power > 0:
            total_escort_personnel = 0
            escort_rows: list[tuple[str, int]] = []
            for ref in live_escorts:
                _ep, e = self._load_formation(ref)
                n = max(0, int(e.get("personnel", 0)))
                if n:
                    escort_rows.append((ref, n))
                    total_escort_personnel += n
            target_total = min(
                total_escort_personnel,
                max(0, int(round(attacker_n * (0.018 if attacker_wins else 0.008)))),
            )
            remaining = target_total
            for i, (ref, n) in enumerate(escort_rows):
                if remaining <= 0:
                    break
                if i == len(escort_rows) - 1:
                    take = min(n, remaining)
                else:
                    take = min(n, int(round(target_total * n / max(1, total_escort_personnel))))
                if take:
                    row = self._convoy_apply_formation_losses(
                        ref,
                        take,
                        str(now),
                        losing_side=attacker_wins,
                        opponent_state=self._formation_authority_state(attacker),
                        evidence_ref=f"merchant_convoy_escort_battle:{convoy_ref}",
                    )
                    escort_losses[ref] = int(row.get("loss", take)) if isinstance(row, Mapping) else take
                    remaining -= take

        result: dict[str, Any] = {
            "convoy_ref": convoy_ref,
            "attacker_formation_ref": formation_ref,
            "location_ref": location_ref,
            "attacker_wins": bool(attacker_wins),
            "attacker_losses": int(casualty.get("loss", 0)) if isinstance(casualty, Mapping) else attacker_loss_estimate,
            "guard_losses": actual_guard_losses,
            "escort_losses": escort_losses,
            "escort_formation_refs": live_escorts,
        }

        if attacker_wins:
            cargo = {
                str(k): max(0, int(v))
                for k, v in (convoy.get("cargo", {}) or {}).items()
                if max(0, int(v)) > 0
            }
            if disposition == "seize":
                # Reload after casualty settlement so the cargo write cannot restore
                # pre-skirmish personnel/composition state.
                _fp, attacker_now0 = self._load_formation(formation_ref)
                attacker_now = copy.deepcopy(dict(attacker_now0))
                seized = attacker_now.setdefault("captured_cargo", {})
                for key, qty in cargo.items():
                    seized[key] = int(seized.get(key, 0)) + qty
                attacker_now.setdefault("captured_cargo_history", []).append(
                    {"at": str(now), "source_ref": convoy_ref, "cargo": cargo}
                )
                attacker_now["captured_cargo_history"] = attacker_now["captured_cargo_history"][-24:]
                self.put(fp, attacker_now)
                convoy["status"] = "seized"
                convoy["seized_by_formation_ref"] = formation_ref
            else:
                convoy["status"] = "destroyed"
                convoy["destroyed_cargo"] = cargo
            convoy["cargo"] = {}
            self._merchant_release_guards(convoy, at=str(now))
            index = self._merchant_convoy_index()
            index["active_refs"] = [
                str(x) for x in index.get("active_refs", []) if str(x) != convoy_ref
            ]
            self.put(_INDEX, index)
            result["cargo"] = cargo
            result["disposition"] = disposition
        else:
            delay = max(
                1,
                int(self._merchant_convoy_rules().get("failed_interception_delay_hours", 6)),
            )
            convoy["arrives_at"] = str(
                CampaignTime.parse(str(convoy.get("arrives_at"))).add_seconds(delay * 3600)
            )
            result["delay_hours"] = delay

        incident = {
            "at": str(now),
            "kind": "interception",
            **{k: v for k, v in result.items() if k != "cargo"},
        }
        convoy.setdefault("security_incidents", []).append(incident)
        convoy["security_incidents"] = convoy["security_incidents"][-24:]
        self.put(path, convoy)
        world_time, metrics = self._advance_seconds(3600)
        self._write_meta(command, world_time)
        return self._result(world_time=world_time, **metrics, **result)

    def _merchant_convoy_interaction(
        self, command: Any, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        action = str(payload.get("action", ""))
        ref = str(payload.get("convoy_ref", ""))
        path, convoy = self._merchant_convoy_exact(ref)
        at = str(self._world_time())
        if str(convoy.get("status", "")) != "in_transit":
            raise ValueError("merchant convoy interaction requires an in-transit convoy")
        current = self._sync_convoy_escorts(convoy, at) if convoy.get("escort_formation_refs") else self._convoy_progress_node(convoy, at)
        convoy["current_location_ref"] = current

        if action in {"assign_escort", "remove_escort"}:
            formation_ref = str(payload.get("formation_ref", ""))
            self._require_formation_authority(str(command.actor_id), formation_ref)
            _fp, formation = self._load_formation(formation_ref)
            if str(formation.get("location_ref", "")) != current:
                raise ValueError("escort formation must be physically co-located with the convoy")
            refs = [
                str(x)
                for x in convoy.get("escort_formation_refs", [])
                if isinstance(x, str)
            ]
            if action == "assign_escort":
                if not bool(formation.get("mobilized", False)):
                    raise ValueError("merchant convoy escort formation must be mobilized")
                existing = formation.get("convoy_escort_assignment")
                if isinstance(existing, Mapping) and str(existing.get("convoy_ref", "")) not in {"", ref}:
                    raise ValueError("formation is already attached to another merchant convoy")
                if formation_ref not in refs:
                    refs.append(formation_ref)
                formation = copy.deepcopy(dict(formation))
                formation["convoy_escort_assignment"] = {
                    "convoy_ref": ref, "joined_at": at, "joined_location_ref": current,
                    "rule": "formation remains an exact military owner and moves only on this convoy's route chronology while attached",
                }
                self.put(_fp, formation)
                convoy.setdefault("escort_state", {})[formation_ref] = {
                    "joined_at": at, "last_sync_at": at, "last_location_ref": current,
                    "food_consumed_kg": 0, "fodder_consumed_kg": 0,
                }
            else:
                self._convoy_detach_escort(convoy, formation_ref, at, "escort_released")
                refs = [x for x in refs if x != formation_ref]
            convoy["escort_formation_refs"] = sorted(set(refs))
            result = {"escort_formation_refs": convoy["escort_formation_refs"]}
        elif action == "delay":
            if str(command.actor_id) != str(self.INTERNAL_ACTOR):
                raise PermissionError("merchant convoy delay is an internal physical consequence")
            hours = max(1, int(payload.get("hours", 1)))
            convoy["arrives_at"] = str(
                CampaignTime.parse(str(convoy["arrives_at"])).add_seconds(hours * 3600)
            )
            convoy.setdefault("delay_history", []).append(
                {"at": at, "kind": "physical_delay", "hours": hours}
            )
            convoy["delay_history"] = convoy["delay_history"][-24:]
            result = {"delayed_hours": hours}
        elif action == "reroute":
            if str(command.actor_id) != str(self.INTERNAL_ACTOR):
                raise PermissionError("merchant convoy reroute is an internal merchant/logistics decision")
            destination_ref = str(
                payload.get("destination_market_ref") or convoy.get("destination_market_ref", "")
            )
            self._reroute_merchant_convoy(
                convoy, at, destination_market_ref=destination_ref
            )
            result = {
                "destination_market_ref": destination_ref,
                "route_refs": list(convoy.get("route_refs", [])),
            }
        elif action == "interdict":
            # The interception reducer handles its own write/time transaction.
            return self._merchant_interdict_convoy(command, payload)
        else:
            raise ValueError("unsupported merchant convoy action")

        self.put(path, convoy)
        world, metrics = self._advance_seconds(3600)
        self._write_meta(command, world)
        return self._result(
            convoy_ref=ref,
            status=convoy.get("status"),
            world_time=world,
            **result,
            **metrics,
        )

    # ------------------------------------------------------------------
    # Command boundary.
    # ------------------------------------------------------------------

    def _authorize_command(self, command: Any, payload: Mapping[str, Any]) -> None:
        super()._authorize_command(command, payload)
        if command.command_type != "merchant_convoy_action" or command.actor_id == self.INTERNAL_ACTOR:
            return
        action = str(payload.get("action", ""))
        if action not in {"assign_escort", "remove_escort", "interdict"}:
            raise PermissionError("merchant convoy administration is an autonomous/internal action")
        self._require_formation_authority(
            str(command.actor_id), str(payload.get("formation_ref", ""))
        )

    def _validate_command_semantics(
        self, command: Any, payload: Mapping[str, Any]
    ) -> None:
        super()._validate_command_semantics(command, payload)
        if command.command_type != "merchant_convoy_action":
            return
        action = str(payload.get("action", ""))
        if action not in {"assign_escort", "remove_escort", "delay", "reroute", "interdict"}:
            raise ValueError("unsupported merchant convoy action")
        if not str(payload.get("convoy_ref", "")):
            raise ValueError("convoy_ref is required")
        self._merchant_convoy_exact(str(payload.get("convoy_ref")))
        if action in {"assign_escort", "remove_escort", "interdict"}:
            self._load_formation(str(payload.get("formation_ref", "")))
        if action == "interdict" and str(payload.get("disposition", "seize")) not in {"seize", "destroy"}:
            raise ValueError("merchant convoy interception disposition must be seize or destroy")
        if action == "delay" and int(payload.get("hours", 0)) <= 0:
            raise ValueError("delay hours must be positive")
        if action == "reroute" and payload.get("destination_market_ref"):
            self.read(self.owner_path(str(payload.get("destination_market_ref"))))

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "merchant_convoy_action":
            return self._merchant_convoy_interaction(command, payload)
        return super()._dispatch(command, payload)

    # ------------------------------------------------------------------
    # Monthly/private-economy hook.
    # ------------------------------------------------------------------

    def _settle_strategic_merchant_convoys(self, state: str, at: str) -> None:
        self._settle_arriving_merchant_convoys(state, at)
        registry = copy.deepcopy(self.read(_REGISTRY))
        index = self._merchant_convoy_index()
        changed = False
        for house_ref in sorted(registry.get("houses", {})):
            house = registry["houses"][house_ref]
            if (
                not isinstance(house, dict)
                or str(house.get("status", "active")) != "active"
                or str(house.get("state", "")) != state
            ):
                continue
            if self._dispatch_one_merchant_convoy(
                state, house_ref, house, at, index, registry
            ):
                changed = True
        if changed:
            registry["aggregate_capital_silver"] = sum(
                max(0, int(h.get("capital_silver", 0)))
                for h in registry.get("houses", {}).values()
                if isinstance(h, Mapping)
            )
            registry["last_convoy_dispatch"] = at
            self.put(_REGISTRY, registry)
            self.put(_INDEX, index)

    def _settle_private_production(self, state: str, occurrences: int, at: str) -> None:
        super()._settle_private_production(state, occurrences, at)
        if occurrences > 0:
            self._settle_strategic_merchant_convoys(state, at)
