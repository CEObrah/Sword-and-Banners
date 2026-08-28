from __future__ import annotations

import copy
import hashlib
import heapq
import math
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from sword_runtime.battle_command import initialize_battle_command_plan, review_battle_command_plan
from sword_runtime.battle_lifecycle import BattleLifecycleMixin
from sword_runtime.environment import is_daylight, next_sunrise_after
from sword_runtime.history_store import iter_history_events, write_history_index
from sword_runtime.military_doctrine import doctrine_behavior
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.terrain import encode_terrain, terrain_context_for_location, terrain_effects_for_tags, terrain_has


_BATTLEFIELD_MECHANICS_PATH = "game/data/mechanics/battlefield-operations.json"
_VALID_ORDERS = frozenset({"hold", "attack", "breakthrough", "delay", "reserve", "withdraw"})
_VALID_PACES = frozenset({"forced", "standard", "cautious"})


def _seconds_between(start: CampaignTime, end: CampaignTime) -> int:
    return max(0, int(start.seconds_until(end)))


def _div_with_signed_remainder(numerator: int, denominator: int = 3600) -> tuple[int, int]:
    if denominator <= 0:
        raise ValueError("invalid battlefield pressure denominator")
    if numerator >= 0:
        return divmod(numerator, denominator)
    whole, remainder = divmod(-numerator, denominator)
    return -whole, -remainder


class OperationalBattlefieldMixin(BattleLifecycleMixin):
    """Persistent operational battlefield state subordinate to a saved operation.

    This layer owns sector geometry, tactical assignment, redeployment clocks,
    command pressure, contact signals and messenger delivery. It never owns
    manpower, casualties, exact combat outcomes, strategic location, occupation,
    or sovereignty. Those remain with formations, battle_resolve, operations and
    territorial systems.
    """

    def _battlefield_mechanics(self) -> Mapping[str, Any]:
        mechanics = self.read(_BATTLEFIELD_MECHANICS_PATH)
        if not isinstance(mechanics, Mapping):
            raise ValueError("battlefield mechanics are invalid")
        return mechanics


    def _battlefield_sector_terrain(self, location_ref: str, sector_key: str) -> dict[str, Any]:
        base = terrain_context_for_location(self, location_ref)
        tags = list(base["tags"])
        features: list[str] = []
        digest = int(hashlib.sha256(f"{location_ref}|{sector_key}|terrain".encode()).hexdigest()[:8], 16)
        frontline = sector_key in {"left", "center", "right", "forward"}
        if frontline and terrain_has(base["encoded"], "hills", "mountain"):
            features.append("higher_ground" if digest % 3 == 0 else "broken_ground" if digest % 3 == 1 else "")
        if frontline and terrain_has(base["encoded"], "woodland") and digest % 2 == 0:
            features.append("dense_woodland")
        if frontline and terrain_has(base["encoded"], "floodplain", "wetland", "marsh") and digest % 2 == 1:
            features.append("soft_ground")
        features = [x for x in features if x]
        tags.extend(x for x in features if x not in tags)
        effects = terrain_effects_for_tags(self, tags)
        return {"tags": tags, "encoded": encode_terrain(tags), "local_features": features, "mechanical_effects": effects}

    @staticmethod
    def _battlefield_sector_effect(sector: Mapping[str, Any], key: str, default: int = 1000) -> int:
        terrain = sector.get("terrain") if isinstance(sector.get("terrain"), Mapping) else {}
        effects = terrain.get("mechanical_effects") if isinstance(terrain.get("mechanical_effects"), Mapping) else {}
        value = effects.get(key, default)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else default

    def _battlefield_operation(self, operation_ref: str) -> tuple[str, Dict[str, Any]]:
        idx = self.read("state/operations/index.json")
        path = idx.get("operations", {}).get(operation_ref) if isinstance(idx, Mapping) else None
        if not isinstance(path, str) or not path:
            raise ValueError("unknown battlefield operation")
        operation = copy.deepcopy(self.read(path))
        if not isinstance(operation, dict) or operation.get("schema") != "sword-operation":
            raise ValueError("battlefield operation is invalid")
        return path, operation

    def _battlefield_active_operation_routes(self) -> list[tuple[str, str]]:
        """Return only operations that currently own an active operational battlefield.

        ``state/operations/index.json`` is routing-only state. Strategic operations may
        grow into the dozens or hundreds over a long campaign while only a tiny
        fraction have a materialized tactical battlefield. Battlefield chronology must
        therefore never scan every strategic operation merely to prove there is no
        battlefield work to settle.
        """
        try:
            idx = self.read("state/operations/index.json")
        except FileNotFoundError:
            return []
        if not isinstance(idx, Mapping):
            return []
        operations = idx.get("operations")
        routes = idx.get("active_battlefield_operation_refs")
        if not isinstance(operations, Mapping):
            return []
        if routes is None:
            raise ValueError("operation index is missing active battlefield routing")
        if not isinstance(routes, list):
            raise ValueError("active battlefield operation routing is invalid")
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_ref in routes:
            if not isinstance(raw_ref, str) or not raw_ref or raw_ref in seen:
                raise ValueError("active battlefield operation routing contains an invalid or duplicate ref")
            path = operations.get(raw_ref)
            if not isinstance(path, str) or not path:
                raise ValueError("active battlefield operation routing points to an unknown operation")
            seen.add(raw_ref)
            out.append((raw_ref, path))
        return sorted(out)

    def _battlefield_set_operation_route(self, operation_ref: str, *, active: bool) -> None:
        idx_path = "state/operations/index.json"
        idx = copy.deepcopy(self.read(idx_path))
        if not isinstance(idx, dict):
            raise ValueError("operation index is invalid")
        operations = idx.get("operations")
        if not isinstance(operations, Mapping) or operation_ref not in operations:
            raise ValueError("cannot route a battlefield for an unknown operation")
        current = idx.get("active_battlefield_operation_refs", [])
        if not isinstance(current, list) or any(not isinstance(ref, str) or not ref for ref in current):
            raise ValueError("active battlefield operation routing is invalid")
        refs = set(current)
        if active:
            refs.add(operation_ref)
        else:
            refs.discard(operation_ref)
        idx["active_battlefield_operation_refs"] = sorted(refs)
        self.put(idx_path, idx)

    @staticmethod
    def _battlefield_edges(battlefield: Mapping[str, Any]) -> Dict[str, Dict[str, int]]:
        graph: Dict[str, Dict[str, int]] = {}
        for row in battlefield.get("sector_edges", []):
            if not isinstance(row, Mapping):
                continue
            a, b, distance = row.get("a"), row.get("b"), row.get("distance_units")
            if not isinstance(a, str) or not isinstance(b, str) or isinstance(distance, bool) or not isinstance(distance, int) or distance <= 0:
                continue
            graph.setdefault(a, {})[b] = distance
            graph.setdefault(b, {})[a] = distance
        return graph

    @classmethod
    def _battlefield_shortest_path(cls, battlefield: Mapping[str, Any], source: str, target: str) -> tuple[list[str], int]:
        if source == target:
            return [source], 0
        graph = cls._battlefield_edges(battlefield)
        if source not in graph or target not in graph:
            raise ValueError("no battlefield sector path")
        queue: list[tuple[int, str, tuple[str, ...]]] = [(0, source, (source,))]
        best: Dict[str, int] = {}
        while queue:
            distance, node, path = heapq.heappop(queue)
            if node in best and best[node] <= distance:
                continue
            best[node] = distance
            if node == target:
                return list(path), distance
            for nxt, edge_distance in graph.get(node, {}).items():
                heapq.heappush(queue, (distance + edge_distance, nxt, (*path, nxt)))
        raise ValueError("no battlefield sector path")

    @staticmethod
    def _battlefield_ref(battlefield_ref: str, key: str) -> str:
        return f"{battlefield_ref}.sector.{key}"

    def _battlefield_player_controls_side(self, battlefield: Mapping[str, Any], side_ref: str) -> bool:
        assignments = battlefield.get("assignments")
        if not isinstance(assignments, Mapping):
            return False
        for formation_ref, assignment in assignments.items():
            if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
                continue
            if assignment.get("side_ref") != side_ref:
                continue
            try:
                if self._has_formation_authority(self.PLAYER_ACTOR, formation_ref):
                    return True
            except (KeyError, TypeError, ValueError, PermissionError, FileNotFoundError):
                continue
        return False

    def _battlefield_player_side_refs(self, battlefield: Mapping[str, Any]) -> set[str]:
        return {
            side_ref
            for side_ref in battlefield.get("side_refs", [])
            if isinstance(side_ref, str) and self._battlefield_player_controls_side(battlefield, side_ref)
        }

    @staticmethod
    def _battlefield_formation_owner_key(formation: Mapping[str, Any]) -> str:
        for key in ("administrative_owner", "owner_force_ref", "command_authority"):
            value = formation.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("battlefield formation has no stable owner key")

    def _battlefield_formation_side_hint(self, formation: Mapping[str, Any]) -> str:
        """Resolve the operational coalition without transferring ownership.

        State formations stay with their state. A House still subordinate to a
        state fights on that state's operational side; a House that has lawfully
        established a sovereign polity uses that polity instead. Other owners
        retain their exact owner key. This is a side label only, never a claim of
        military ownership or sovereignty.
        """

        owner = self._battlefield_formation_owner_key(formation)
        if owner.startswith(("state_", "polity_")):
            return owner
        if owner.startswith("house_"):
            try:
                house = self.read(self.owner_path(owner))
            except (FileNotFoundError, KeyError, ValueError):
                house = {}
            if isinstance(house, Mapping):
                sovereignty = house.get("sovereignty_ref")
                if isinstance(sovereignty, str) and sovereignty:
                    return sovereignty
                state = house.get("state")
                if isinstance(state, str) and state:
                    return "state_" + state.removeprefix("state_")
        return owner

    @staticmethod
    def _battlefield_mounted_fraction_milli(formation: Mapping[str, Any]) -> int:
        personnel = max(1, int(formation.get("personnel", 0)))
        mounts = sum(max(0, int(value)) for value in (formation.get("mounts") or {}).values()) if isinstance(formation.get("mounts"), Mapping) else 0
        composition = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
        cavalry = sum(max(0, int(count)) for role, count in composition.items() if any(token in str(role).lower() for token in ("cavalry", "mounted", "chariot")))
        return min(1000, max(mounts, cavalry) * 1000 // personnel)

    def _battlefield_leg_seconds(self, formation: Mapping[str, Any], distance_units: int, pace: str) -> int:
        mechanics = self._battlefield_mechanics().get("redeployment")
        if not isinstance(mechanics, Mapping) or pace not in _VALID_PACES:
            raise ValueError("battlefield redeployment mechanics are invalid")
        seconds_by_pace = mechanics.get("seconds_per_distance_unit")
        size_bands = mechanics.get("size_bands")
        if not isinstance(seconds_by_pace, Mapping) or not isinstance(size_bands, Sequence):
            raise ValueError("battlefield redeployment mechanics are invalid")
        base = seconds_by_pace.get(pace)
        if isinstance(base, bool) or not isinstance(base, int) or base <= 0:
            raise ValueError("battlefield redeployment mechanics are invalid")
        personnel = int(formation.get("personnel", 0))
        if personnel <= 0:
            raise ValueError("battlefield formation has no personnel")
        size_milli: Optional[int] = None
        for row in size_bands:
            if not isinstance(row, Mapping):
                continue
            maximum = row.get("max_personnel")
            factor = row.get("time_milli")
            if isinstance(maximum, int) and not isinstance(maximum, bool) and personnel <= maximum and isinstance(factor, int) and not isinstance(factor, bool):
                size_milli = factor
                break
        if size_milli is None or size_milli <= 0:
            raise ValueError("battlefield redeployment size band is invalid")
        mounted = self._battlefield_mounted_fraction_milli(formation)
        fatigue = max(0, min(100, int(formation.get("fatigue", 0))))
        readiness = max(0, min(100, int(formation.get("readiness", 50))))
        mobility_milli = 1000 + mounted * int(mechanics.get("mounted_speed_bonus_milli", 450)) // 1000
        mobility_milli = mobility_milli * max(600, 1000 - fatigue * 4) // 1000
        mobility_milli = mobility_milli * max(700, 800 + readiness * 2) // 1000
        seconds = max(1, int(distance_units) * int(base) * size_milli // max(1, mobility_milli))
        return seconds

    def _battlefield_effective_power(self, formation_ref: str, order: str, sector: Mapping[str, Any] | None = None) -> int:
        _path, formation = self._load_formation(formation_ref)
        personnel = max(0, int(formation.get("personnel", 0)))
        if personnel <= 0:
            return 0
        mechanics = self._battlefield_mechanics()
        order_row = mechanics.get("orders", {}).get(order) if isinstance(mechanics.get("orders"), Mapping) else None
        order_power = order_row.get("power_milli") if isinstance(order_row, Mapping) else None
        if isinstance(order_power, bool) or not isinstance(order_power, int) or order_power <= 0:
            raise ValueError("battlefield order mechanics are invalid")
        readiness = max(0, min(100, int(formation.get("readiness", 50))))
        morale = max(0, min(100, int(formation.get("morale", 50))))
        cohesion = max(0, min(100, int(formation.get("cohesion", 50))))
        fatigue = max(0, min(100, int(formation.get("fatigue", 0))))
        quality_milli = 350 + readiness * 2 + morale * 2 + cohesion * 2 + (100 - fatigue)
        terrain_power = 1000
        if isinstance(sector, Mapping):
            mobility = self._battlefield_sector_effect(sector, "formation_mobility_milli")
            mounted = self._battlefield_sector_effect(sector, "mounted_mobility_milli")
            defense = self._battlefield_sector_effect(sector, "defense_milli")
            comp = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
            total = max(1, sum(max(0, int(v)) for v in comp.values()))
            mounted_n = sum(max(0, int(v)) for role, v in comp.items() if "cavalry" in str(role).lower() or "chariot" in str(role).lower())
            move_mix = (mobility * (total - mounted_n) + mounted * mounted_n) // total
            terrain_power = move_mix if order in {"attack", "breakthrough"} else (move_mix + defense) // 2 if order in {"hold", "delay"} else (move_mix + 1000) // 2
        return max(1, personnel * quality_milli * order_power * terrain_power // 1_000_000_000)

    def _battlefield_sector_rates(self, battlefield: Mapping[str, Any], sector: Mapping[str, Any]) -> Dict[str, int]:
        mechanics = self._battlefield_mechanics()
        pressure_rules = mechanics.get("pressure")
        orders = mechanics.get("orders")
        if not isinstance(pressure_rules, Mapping) or not isinstance(orders, Mapping):
            raise ValueError("battlefield pressure mechanics are invalid")
        base = pressure_rules.get("base_milli_per_hour")
        recovery = pressure_rules.get("recovery_milli_per_hour")
        imbalance_weight = pressure_rules.get("imbalance_weight_milli")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (base, recovery, imbalance_weight)):
            raise ValueError("battlefield pressure mechanics are invalid")
        assignments = battlefield.get("assignments")
        if not isinstance(assignments, Mapping):
            raise ValueError("battlefield assignments are invalid")
        sector_ref = sector.get("id")
        side_refs = [str(side) for side in battlefield.get("side_refs", []) if isinstance(side, str)]
        powers = {side: 0 for side in side_refs}
        pressure_factors = {side: 1000 for side in side_refs}
        for formation_ref in sector.get("formation_refs", []):
            assignment = assignments.get(formation_ref) if isinstance(formation_ref, str) else None
            if not isinstance(assignment, Mapping) or assignment.get("status") == "redeploying" or assignment.get("sector_ref") != sector_ref:
                continue
            side = assignment.get("side_ref")
            order = str(assignment.get("order", "hold"))
            if side not in powers or order not in _VALID_ORDERS:
                continue
            powers[side] += self._battlefield_effective_power(formation_ref, order, sector)
            order_row = orders.get(order)
            if isinstance(order_row, Mapping):
                pressure_factors[side] = max(pressure_factors[side], int(order_row.get("pressure_milli", 1000)))
        rates: Dict[str, int] = {}
        day_cycle = battlefield.get("day_cycle") if isinstance(battlefield.get("day_cycle"), Mapping) else {}
        if str(day_cycle.get("posture", "day_operations")) == "night_camp":
            active_contact = battlefield.get("active_contact") if isinstance(battlefield.get("active_contact"), Mapping) else {}
            active_sector = active_contact.get("sector_ref") if isinstance(active_contact, Mapping) else None
            if active_sector != sector_ref:
                # Dusk is a real field-camp/security posture, not eight more hours
                # of invisible daytime combat. Only an explicitly persisted night
                # contact window keeps pressure active in its exact sector.
                return {side: (-int(recovery) if powers.get(side, 0) > 0 else 0) for side in side_refs}
        for side in side_refs:
            own = powers.get(side, 0)
            enemy_powers = [powers.get(other, 0) for other in side_refs if other != side]
            enemy = max(enemy_powers, default=0)
            if enemy <= 0:
                rates[side] = -int(recovery) if own > 0 else 0
                continue
            if own <= 0:
                rates[side] = max(1, int(base) * 3)
                continue
            enemy_side = next((other for other in side_refs if other != side and powers.get(other, 0) == enemy), side)
            ratio_milli = max(250, min(4000, enemy * 1000 // max(1, own)))
            imbalance = max(0, ratio_milli - 1000)
            rate = int(base) * ratio_milli // 1000
            rate = rate * (1000 + imbalance * int(imbalance_weight) // 1000) // 1000
            rate = rate * pressure_factors.get(enemy_side, 1000) // 1000
            rates[side] = max(1, min(4000, rate))
        return rates

    def _battlefield_hq_sector(self, battlefield: Mapping[str, Any]) -> Optional[str]:
        for sector_ref, sector in (battlefield.get("sectors") or {}).items():
            if isinstance(sector_ref, str) and isinstance(sector, Mapping) and str(sector.get("name", "")).lower().startswith("command"):
                return sector_ref
        return None

    def _battlefield_exact_object_bindings(self, operation: Mapping[str, Any], battlefield: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Bind only exact physical objects already proved by operation geography.

        These bindings give battle resolution a lawful target for tactical gate,
        bridge and fixed-artillery consequences without transferring sovereignty
        or creating infrastructure in prose.
        """
        location_ref=str(operation.get("location_ref") or battlefield.get("location_ref") or "")
        sectors=battlefield.get("sectors",{}) if isinstance(battlefield.get("sectors"),Mapping) else {}
        center=next((ref for ref,row in sectors.items() if isinstance(row,Mapping) and str(row.get("name","")).lower() in {"center","forward screen"}),None)
        if center is None:
            center=next(iter(sectors),None)
        if not isinstance(center,str):
            return []
        bindings=[]
        # Gate identity comes from static geography; the battlefield records only
        # temporary tactical possession, never territorial/legal ownership.
        locations=self.read("game/data/world/locations.json")
        loc_rows=locations.get("locations",locations) if isinstance(locations,Mapping) else {}
        loc=None
        if isinstance(loc_rows,Mapping): loc=loc_rows.get(location_ref)
        elif isinstance(loc_rows,list): loc=next((row for row in loc_rows if isinstance(row,Mapping) and str(row.get("ref",row.get("location_ref","")))==location_ref),None)
        if isinstance(loc,Mapping) and str(loc.get("kind","")).lower()=="gate":
            bindings.append({"kind":"gate_access","object_ref":location_ref,"sector_ref":center})
        # A bridge is bound only when the saved operation itself names exactly one
        # materialized strategic crossing route. This avoids guessing from nearby
        # map geometry.
        crossing_doc=self.read_optional("state/geography/strategic-crossings.json")
        crossing_rows=crossing_doc.get("crossings",{}) if isinstance(crossing_doc,Mapping) else {}
        route_refs=[str(x) for x in operation.get("route_refs",[]) if isinstance(x,str)] if isinstance(operation.get("route_refs"),list) else []
        crossing_refs=[ref for ref in route_refs if isinstance(crossing_rows,Mapping) and ref in crossing_rows]
        if len(crossing_refs)==1:
            bindings.append({"kind":"bridge_crossing","object_ref":crossing_refs[0],"sector_ref":center})
        # Hot fortified sites already own an exact artillery record. Bind it only
        # when the operation location is that site or an explicitly contained child.
        fort_index=self.read_optional("state/fortifications/index.json")
        static=fort_index.get("static_profiles",{}) if isinstance(fort_index,Mapping) else {}
        candidate_sites=[]
        if location_ref in static: candidate_sites.append(location_ref)
        if isinstance(loc,Mapping):
            # An access gate belongs tactically to the fortified site it opens
            # into, even when the gate itself is geographically nested in a
            # larger estate. Prefer that exact protected site before falling
            # back to generic containment.
            access_for=str(loc.get("access_for_ref") or "")
            if access_for and access_for in static and access_for not in candidate_sites:
                candidate_sites.append(access_for)
            parent=str(loc.get("contained_by_fortification_site_ref") or "")
            if parent and parent in static and parent not in candidate_sites:
                candidate_sites.append(parent)
        for site_ref in candidate_sites:
            row=static.get(site_ref,{}) if isinstance(static,Mapping) else {}
            depot_ref=str(row.get("live_logistics_depot_ref") or "") if isinstance(row,Mapping) else ""
            if not depot_ref: continue
            try:
                depot=self.read(self.owner_path(depot_ref))
            except Exception:
                continue
            artillery_ref=str(depot.get("artillery_ref") or "") if isinstance(depot,Mapping) else ""
            if artillery_ref:
                bindings.append({"kind":"fixed_artillery","object_ref":artillery_ref,"site_ref":site_ref,"sector_ref":center})
                break
        return bindings

    def _battlefield_report_latency(self, battlefield: Mapping[str, Any], sector_ref: str, side_ref: str) -> int:
        reporting_formations: list[str] = []
        assignments = battlefield.get("assignments")
        if isinstance(assignments, Mapping):
            for formation_ref in (battlefield.get("sectors", {}).get(sector_ref, {}) or {}).get("formation_refs", []):
                assignment = assignments.get(formation_ref) if isinstance(formation_ref, str) else None
                if not isinstance(assignment, Mapping) or assignment.get("side_ref") != side_ref:
                    continue
                reporting_formations.append(str(formation_ref))
                try:
                    _path, formation = self._load_formation(formation_ref)
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                if formation.get("commander_ref") == self.PLAYER_ACTOR:
                    return 0
        rules = self._battlefield_mechanics().get("information")
        if not isinstance(rules, Mapping):
            raise ValueError("battlefield information mechanics are invalid")
        hq = self._battlefield_hq_sector(battlefield)
        distance = 1
        if isinstance(hq, str):
            try:
                _path, distance = self._battlefield_shortest_path(battlefield, sector_ref, hq)
            except ValueError:
                distance = 1
        base = int(rules.get("mounted_messenger_base_seconds", 420))
        per_unit = int(rules.get("mounted_messenger_seconds_per_distance_unit", 90))
        latency = max(0, base + max(0, distance) * per_unit)
        # Persistent retinue familiarity improves routine command/report handling,
        # never combat power. A fully drilled command group can reduce only a
        # modest share of courier/relay overhead; terrain distance still dominates.
        try:
            group_index = self.read("state/cmd/command-groups/index.json")
            formation_groups = group_index.get("primary_formation_group", {}) if isinstance(group_index, Mapping) else {}
            best_familiarity = 0
            for formation_ref in reporting_formations:
                group_ref = formation_groups.get(formation_ref) if isinstance(formation_groups, Mapping) else None
                if not isinstance(group_ref, str):
                    continue
                group = self.read(f"state/cmd/command-groups/{group_ref}.json")
                best_familiarity = max(best_familiarity, int(group.get("familiarity_milli", 0)))
            reduction_milli = min(180, max(0, best_familiarity) * 180 // 1000)
            latency = latency * (1000 - reduction_milli) // 1000
        except (FileNotFoundError, ValueError, KeyError):
            pass
        return max(0, latency)

    def _battlefield_compact_reports(self, battlefield: Dict[str, Any]) -> None:
        """Keep all live reports plus only a bounded recent delivered tail.

        Delivered operational reports are presentation/command-memory, not the
        authoritative battle-history store.  Leaving every delivered report in an
        active operation makes long previews repeatedly deepcopy an ever-growing
        list at every pressure boundary.  Pending reports remain lossless because
        their delivery clocks are still mechanically live.
        """
        reports = battlefield.get("reports")
        if not isinstance(reports, list):
            return
        info = self._battlefield_mechanics().get("information")
        keep_terminal = max(0, int(info.get("max_retained_delivered_reports", 32))) if isinstance(info, Mapping) else 32
        terminal_indices = [
            index for index, report in enumerate(reports)
            if isinstance(report, Mapping) and str(report.get("status", "")) != "queued"
        ]
        retained_terminal = set(terminal_indices[-keep_terminal:]) if keep_terminal else set()
        battlefield["reports"] = [
            report for index, report in enumerate(reports)
            if not isinstance(report, Mapping)
            or str(report.get("status", "")) == "queued"
            or index in retained_terminal
        ]

    @staticmethod
    def _battlefield_report_id(battlefield_ref: str, sector_ref: str, side_ref: str, level: str, at: CampaignTime) -> str:
        stamp = str(at).replace(":", "").replace("+", "p")
        safe_sector = sector_ref.replace(".", "_")
        safe_side = side_ref.replace(".", "_")
        return f"report_{battlefield_ref}_{safe_sector}_{safe_side}_{level}_{stamp}"

    def _battlefield_queue_report(
        self,
        battlefield: Dict[str, Any],
        *,
        sector_ref: str,
        side_ref: str,
        level: str,
        pressure_milli: int,
        at: CampaignTime,
        summary: str,
        interrupt_player: bool | None = None,
    ) -> Dict[str, Any]:
        report_id = self._battlefield_report_id(str(battlefield["battlefield_ref"]), sector_ref, side_ref, level, at)
        reports = battlefield.setdefault("reports", [])
        existing = next((row for row in reports if isinstance(row, Mapping) and row.get("report_id") == report_id), None)
        if isinstance(existing, Mapping):
            return dict(existing)
        latency = self._battlefield_report_latency(battlefield, sector_ref, side_ref)
        deliver_at = at.add_seconds(latency)
        report = {
            "report_id": report_id,
            "sector_ref": sector_ref,
            "target_side_ref": side_ref,
            "level": level,
            "pressure_milli": max(0, min(1000, int(pressure_milli))),
            "created_at": str(at),
            "deliver_at": str(deliver_at),
            # Even zero-latency reports enter the delivery queue. Settlement at
            # this same boundary then records delivery and exposes the report to
            # the player exactly once. Marking them delivered here would skip
            # the player-facing delivery pass below.
            "delivered_at": None,
            "status": "queued",
            "summary": summary,
            "interrupt_player": (
                bool(interrupt_player)
                if interrupt_player is not None
                else str(level) in {"contact", "critical", "collapse", "support_request", "new_order"}
            ),
        }
        reports.append(report)
        return report

    def _battlefield_player_support_options(
        self, battlefield: Mapping[str, Any], *, target_sector_ref: str, side_ref: str
    ) -> list[dict[str, Any]]:
        """Return lawful player-controlled ways to reinforce another sector.

        This is a derived command view, never a new logistics or formation owner.
        It proves only that a controlled formation has a physical route and gives
        the estimated movement time from its current sector. Whether Wei actually
        sends it remains player agency.
        """
        assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
        sectors = battlefield.get("sectors") if isinstance(battlefield.get("sectors"), Mapping) else {}
        if target_sector_ref not in sectors:
            return []
        options: list[dict[str, Any]] = []
        for formation_ref, assignment in sorted(assignments.items()):
            if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
                continue
            if assignment.get("side_ref") != side_ref or assignment.get("status") == "redeploying":
                continue
            source_sector_ref = assignment.get("sector_ref")
            if not isinstance(source_sector_ref, str) or source_sector_ref == target_sector_ref:
                continue
            try:
                if not self._has_formation_authority(self.PLAYER_ACTOR, formation_ref):
                    continue
                path_refs, distance = self._battlefield_shortest_path(battlefield, source_sector_ref, target_sector_ref)
                _path, formation = self._load_formation(formation_ref)
            except (KeyError, TypeError, ValueError, PermissionError, FileNotFoundError):
                continue
            if int(formation.get("personnel", 0) or 0) <= 0 or str(formation.get("status", "")) == "destroyed":
                continue
            standard_seconds = 0
            for a, b in zip(path_refs, path_refs[1:]):
                graph = self._battlefield_edges(battlefield)
                leg_distance = graph.get(a, {}).get(b)
                if not isinstance(leg_distance, int) or leg_distance <= 0:
                    standard_seconds = 0
                    break
                standard_seconds += self._battlefield_leg_seconds(formation, leg_distance, "standard")
            if standard_seconds <= 0:
                continue
            source_sector = sectors.get(source_sector_ref) if isinstance(sectors.get(source_sector_ref), Mapping) else {}
            enemy_present = any(
                isinstance(other, Mapping)
                and other.get("status") != "redeploying"
                and other.get("sector_ref") == source_sector_ref
                and other.get("side_ref") != side_ref
                for other in assignments.values()
            )
            options.append({
                "formation_ref": formation_ref,
                "personnel": max(0, int(formation.get("personnel", 0) or 0)),
                "from_sector_ref": source_sector_ref,
                "from_sector_name": source_sector.get("name"),
                "target_sector_ref": target_sector_ref,
                "path_sector_refs": list(path_refs),
                "distance_units": int(distance),
                "estimated_standard_arrival_seconds": int(standard_seconds),
                "current_order": assignment.get("order"),
                "mission_ref": assignment.get("mission_ref"),
                "source_contact_status": "engaged" if enemy_present else "clear",
                "disengagement_note": (
                    "This formation is already opposed in its current sector; detaching it may expose that sector and does not erase enemy pressure."
                    if enemy_present
                    else None
                ),
            })
        return options

    def _battlefield_enrich_player_report(
        self, battlefield: Mapping[str, Any], report: Mapping[str, Any]
    ) -> dict[str, Any]:
        row = copy.deepcopy(dict(report))
        sector_ref = row.get("sector_ref")
        side_ref = row.get("target_side_ref")
        if isinstance(sector_ref, str) and isinstance(side_ref, str):
            options = self._battlefield_player_support_options(
                battlefield, target_sector_ref=sector_ref, side_ref=side_ref
            )
            if options:
                row["intervention_options"] = options
                row["player_can_intervene"] = True
            else:
                row["intervention_options"] = []
                row["player_can_intervene"] = False
        return row

    def _battlefield_queue_autonomous_contact_report(
        self,
        *,
        operation_ref: str,
        battlefield_ref: str,
        descriptor: Mapping[str, Any],
        completed_at: CampaignTime,
    ) -> list[dict[str, Any]]:
        """Route a real NPC-sector contact into the player's command picture.

        Exact battle state remains authoritative. This adds only a delayed report
        for the player's coalition when another sector has just fought, allowing
        Wei to reinforce, detach, request support, or deliberately stay committed
        where he is instead of discovering the event after it is too late.
        """
        path, operation = self._battlefield_operation(operation_ref)
        battlefield = (operation.get("battlefields") or {}).get(battlefield_ref)
        if not isinstance(battlefield, dict) or battlefield.get("status") != "active":
            return []
        sector_ref = str(descriptor.get("sector_ref") or "")
        sector = (battlefield.get("sectors") or {}).get(sector_ref)
        if not isinstance(sector, Mapping):
            return []
        player_sides = self._battlefield_player_side_refs(battlefield)
        if not player_sides:
            return []
        last_combat = sector.get("last_combat") if isinstance(sector.get("last_combat"), Mapping) else {}
        winner_side = str(last_combat.get("winner_side_ref") or "")
        pressure = sector.get("pressure_milli") if isinstance(sector.get("pressure_milli"), Mapping) else {}
        info = self._battlefield_mechanics().get("information")
        intervention_threshold = int(info.get("player_intervention_pressure_milli", 300)) if isinstance(info, Mapping) else 300
        queued: list[dict[str, Any]] = []
        for side_ref in sorted(player_sides):
            involved = side_ref in {str(descriptor.get("attacker_side_ref") or ""), str(descriptor.get("defender_side_ref") or "")}
            if not involved:
                continue
            current_pressure = max(0, min(1000, int(pressure.get(side_ref, 0) or 0)))
            options = self._battlefield_player_support_options(
                battlefield, target_sector_ref=sector_ref, side_ref=side_ref
            )
            lost_local_contact = bool(winner_side and winner_side != side_ref)
            actionable = bool(options) and (lost_local_contact or current_pressure >= intervention_threshold)
            sector_name = str(sector.get("name") or sector_ref)
            if winner_side == side_ref:
                summary = f"{sector_name} reports a local advantage after sustained contact; the wider battle remains active."
            elif winner_side:
                summary = f"{sector_name} reports the enemy held the local advantage in the latest contact; reinforcement or a change of effort may be possible."
            else:
                summary = f"{sector_name} reports a completed contact period; the wider battle remains active."
            report = self._battlefield_queue_report(
                battlefield,
                sector_ref=sector_ref,
                side_ref=side_ref,
                level="support_request" if actionable else "contact_result",
                pressure_milli=current_pressure,
                at=completed_at,
                summary=summary,
                interrupt_player=actionable,
            )
            queued.append(dict(report))
        if queued:
            battlefield["updated_at"] = str(completed_at)
            self.put(path, operation)
        return queued

    @staticmethod
    def _battlefield_remove_formation(battlefield: Dict[str, Any], formation_ref: str) -> None:
        for sector in (battlefield.get("sectors") or {}).values():
            if isinstance(sector, dict):
                refs = sector.get("formation_refs")
                if isinstance(refs, list) and formation_ref in refs:
                    refs[:] = [ref for ref in refs if ref != formation_ref]

    def _battlefield_start_leg(self, battlefield: Dict[str, Any], assignment: Dict[str, Any], formation: Mapping[str, Any], *, at: CampaignTime, next_index: int) -> None:
        path = assignment.get("path_sector_refs")
        if not isinstance(path, list) or next_index <= 0 or next_index >= len(path):
            raise ValueError("invalid battlefield redeployment path")
        source = path[next_index - 1]
        target = path[next_index]
        graph = self._battlefield_edges(battlefield)
        distance = graph.get(source, {}).get(target)
        if not isinstance(distance, int) or distance <= 0:
            raise ValueError("invalid battlefield redeployment leg")
        seconds = self._battlefield_leg_seconds(formation, distance, str(assignment.get("pace", "standard")))
        target_sector = (battlefield.get("sectors") or {}).get(target, {})
        terrain_mobility = max(350, self._battlefield_sector_effect(target_sector, "formation_mobility_milli"))
        seconds = max(1, int(math.ceil(seconds * 1000 / terrain_mobility)))
        assignment.update({
            "status": "redeploying",
            "sector_ref": None,
            "path_index": next_index,
            "transit_from_sector_ref": source,
            "transit_to_sector_ref": target,
            "leg_eta_at": str(at.add_seconds(seconds)),
            "updated_at": str(at),
        })


    def _battlefield_autonomous_contact_rules(self) -> Mapping[str, Any]:
        rules = self._battlefield_mechanics().get("autonomous_contacts")
        if not isinstance(rules, Mapping):
            return {"enabled": False}
        return rules

    def _battlefield_next_autonomous_contact_at(self, at: CampaignTime) -> CampaignTime | None:
        rules = self._battlefield_autonomous_contact_rules()
        if rules.get("enabled") is not True:
            return None
        interval = max(15, int(rules.get("review_interval_minutes", 90))) * 60
        base = at
        if not is_daylight(base):
            base = next_sunrise_after(base)
        due = base.add_seconds(interval)
        if not is_daylight(due):
            due = next_sunrise_after(base).add_seconds(interval)
        return due

    def _battlefield_player_controls_formation(self, formation_ref: str) -> bool:
        try:
            return bool(self._has_formation_authority(self.PLAYER_ACTOR, formation_ref))
        except (KeyError, TypeError, ValueError, PermissionError, FileNotFoundError):
            return False

    def _battlefield_select_autonomous_contacts(self, battlefield: Mapping[str, Any], *, at: CampaignTime) -> list[dict[str, Any]]:
        rules = self._battlefield_autonomous_contact_rules()
        if rules.get("enabled") is not True:
            return []
        # Every eligible NPC-only sector advances on the same battlefield clock.
        # Sector contacts are disjoint by construction, so a global cap here only
        # starves later sectors and can freeze parts of a large battle indefinitely.
        # Player-controlled sectors remain excluded below and still stop only at
        # lawful player-relevant causal boundaries.
        if not is_daylight(at):
            return []
        assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
        candidates: list[tuple[int, str, dict[str, Any]]] = []
        order_rank = {"withdraw": -2, "reserve": -1, "delay": 0, "hold": 1, "attack": 2, "breakthrough": 3}
        for sector_ref, sector in sorted((battlefield.get("sectors") or {}).items()):
            if not isinstance(sector_ref, str) or not isinstance(sector, Mapping):
                continue
            by_side: dict[str, list[str]] = {}
            player_present = False
            for formation_ref in sector.get("formation_refs", []):
                if not isinstance(formation_ref, str):
                    continue
                assignment = assignments.get(formation_ref)
                if not isinstance(assignment, Mapping) or assignment.get("status") == "redeploying" or assignment.get("sector_ref") != sector_ref:
                    continue
                try:
                    _path, formation = self._load_formation(formation_ref)
                except (FileNotFoundError, KeyError, ValueError):
                    continue
                if int(formation.get("personnel", 0) or 0) <= 0 or str(formation.get("status", "")) == "destroyed":
                    continue
                if self._battlefield_player_controls_formation(formation_ref):
                    player_present = True
                    break
                side = assignment.get("side_ref")
                if isinstance(side, str):
                    by_side.setdefault(side, []).append(formation_ref)
            if player_present or len([refs for refs in by_side.values() if refs]) < 2:
                continue
            sides = sorted((side for side, refs in by_side.items() if refs))
            if len(sides) != 2:
                continue
            side_score: dict[str, int] = {}
            total_power = 0
            for side in sides:
                score = 0
                for ref in by_side[side]:
                    assignment = assignments[ref]
                    order = str(assignment.get("order", "hold"))
                    power = max(1, self._battlefield_effective_power(ref, order, sector))
                    total_power += power
                    score += power * order_rank.get(order, 0)
                side_score[side] = score
            attacker_side = sorted(sides, key=lambda side: (-side_score.get(side, 0), side))[0]
            defender_side = next(side for side in sides if side != attacker_side)
            descriptor = {
                "sector_ref": sector_ref,
                "attacker_side_ref": attacker_side,
                "defender_side_ref": defender_side,
                "attacker_refs": sorted(by_side[attacker_side]),
                "defender_refs": sorted(by_side[defender_side]),
            }
            candidates.append((-total_power, sector_ref, descriptor))
        return [row[2] for row in sorted(candidates)]

    def _battlefield_resolve_autonomous_contact(
        self, *, operation_ref: str, battlefield_ref: str, descriptor: Mapping[str, Any], started_at: CampaignTime, completed_at: CampaignTime
    ) -> dict[str, Any]:
        if completed_at <= started_at:
            raise ValueError("autonomous battlefield contact requires positive elapsed time")
        duration_seconds = started_at.seconds_until(completed_at)
        rules = self._battle_lifecycle_rules().get("operational_contact")
        reference_hours = max(0.25, float(rules.get("casualty_reference_hours", 6.0))) if isinstance(rules, Mapping) else 6.0
        plan = {
            "operational_contact": True,
            "light_mode": "daylight" if is_daylight(completed_at) else "night",
            "started_at": str(started_at),
            "planned_end_at": str(completed_at),
            "duration_seconds": duration_seconds,
            "duration_hours": duration_seconds / 3600.0,
            "casualty_reference_hours": reference_hours,
            "casualty_duration_factor": min(1.0, duration_seconds / max(1.0, reference_hours * 3600.0)),
            "truncated_by_boundary": "autonomous_contact_review",
            "truncated_boundary_detail": None,
        }
        token = hashlib.sha256(
            f"{operation_ref}|{battlefield_ref}|{descriptor.get('sector_ref')}|{completed_at}|{'|'.join(descriptor.get('attacker_refs', []))}|{'|'.join(descriptor.get('defender_refs', []))}".encode()
        ).hexdigest()
        command = SimpleNamespace(digest=token, semantic_digest=token)
        result = self._battle(command, {
            "attacker_formation_refs": list(descriptor.get("attacker_refs", [])),
            "defender_formation_refs": list(descriptor.get("defender_refs", [])),
        }, context={
            "kind": "operational_autonomous_contact",
            "operation_ref": operation_ref,
            "battlefield_ref": battlefield_ref,
            "sector_ref": descriptor.get("sector_ref"),
            "contact_ref": f"npc_contact_{token[:16]}",
            "contact_plan": plan,
            "started_at": str(started_at),
            "completed_at": str(completed_at),
            "terrain_kind": str((((self._battlefield_operation(operation_ref)[1].get("battlefields") or {}).get(battlefield_ref, {}).get("sectors") or {}).get(str(descriptor.get("sector_ref")), {}).get("terrain") or {}).get("encoded", "")),
        })
        result["queued_player_reports"] = self._battlefield_queue_autonomous_contact_report(
            operation_ref=operation_ref,
            battlefield_ref=battlefield_ref,
            descriptor=descriptor,
            completed_at=completed_at,
        )
        return result

    def _battlefield_pressure_thresholds(self) -> tuple[int, int, int]:
        rules = self._battlefield_mechanics().get("pressure")
        if not isinstance(rules, Mapping):
            raise ValueError("battlefield pressure mechanics are invalid")
        critical = int(rules.get("critical_milli", 720))
        collapse = int(rules.get("collapse_milli", 920))
        reset = int(rules.get("report_reset_hysteresis_milli", 120))
        if not 0 < critical < collapse <= 1000 or reset < 0:
            raise ValueError("battlefield pressure thresholds are invalid")
        return critical, collapse, reset

    def _battlefield_next_boundary_time(
        self,
        current: CampaignTime,
        target: CampaignTime,
        *,
        operation_ref: str | None = None,
        battlefield_ref: str | None = None,
    ) -> tuple[Optional[CampaignTime], Optional[Dict[str, Any]]]:
        if target <= current:
            return None, None
        routes = self._battlefield_active_operation_routes()
        if not routes:
            return None, None
        critical, collapse, _reset = self._battlefield_pressure_thresholds()
        candidates: list[tuple[CampaignTime, Dict[str, Any]]] = []
        for routed_operation_ref, path in routes:
            if operation_ref is not None and routed_operation_ref != operation_ref:
                continue
            operation = self.read(path)
            if not isinstance(operation, Mapping) or operation.get("status") not in {"active", "engaged"}:
                continue
            for routed_battlefield_ref, battlefield in sorted((operation.get("battlefields") or {}).items()):
                if not isinstance(routed_battlefield_ref, str) or not isinstance(battlefield, Mapping) or battlefield.get("status") not in {"active", "ended"}:
                    continue
                if battlefield_ref is not None and routed_battlefield_ref != battlefield_ref:
                    continue
                # Ended battlefields remain routed only long enough to deliver
                # already-created command/aftermath reports. They no longer accrue
                # pressure, contacts, redeployment, or day-cycle work.
                if battlefield.get("status") == "ended":
                    for report in battlefield.get("reports", []):
                        if not isinstance(report, Mapping) or report.get("status") != "queued":
                            continue
                        due_text = report.get("deliver_at")
                        if isinstance(due_text, str):
                            due = CampaignTime.parse(due_text)
                            if current < due <= target:
                                candidates.append((due, {"kind": "report_delivery", "operation_ref": routed_operation_ref, "battlefield_ref": routed_battlefield_ref, "report_id": report.get("report_id")}))
                    continue
                lifecycle_due, lifecycle_detail = self._battle_lifecycle_next_boundary(current, target)
                if lifecycle_due is not None and lifecycle_detail is not None:
                    candidates.append((lifecycle_due, {
                        **dict(lifecycle_detail),
                        "operation_ref": routed_operation_ref,
                        "battlefield_ref": routed_battlefield_ref,
                    }))
                active_contact = battlefield.get("active_contact")
                if isinstance(active_contact, Mapping):
                    contact_end_text = active_contact.get("ends_at")
                    if isinstance(contact_end_text, str):
                        contact_end = CampaignTime.parse(contact_end_text)
                        if current < contact_end <= target:
                            candidates.append((contact_end, {
                                "kind": "active_contact_end",
                                "operation_ref": routed_operation_ref,
                                "battlefield_ref": routed_battlefield_ref,
                                "sector_ref": active_contact.get("sector_ref"),
                                "contact_ref": active_contact.get("contact_ref"),
                            }))
                npc_due_text = battlefield.get("next_autonomous_contact_at")
                if isinstance(npc_due_text, str):
                    npc_due = CampaignTime.parse(npc_due_text)
                    if current < npc_due <= target:
                        candidates.append((npc_due, {
                            "kind": "autonomous_contact_review",
                            "operation_ref": routed_operation_ref,
                            "battlefield_ref": routed_battlefield_ref,
                        }))
                for formation_ref, assignment in sorted((battlefield.get("assignments") or {}).items()):
                    if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
                        continue
                    if assignment.get("status") == "redeploying":
                        eta_text = assignment.get("leg_eta_at")
                        if isinstance(eta_text, str):
                            eta = CampaignTime.parse(eta_text)
                            if current < eta <= target:
                                candidates.append((eta, {"kind": "redeployment_leg", "operation_ref": routed_operation_ref, "battlefield_ref": routed_battlefield_ref, "formation_ref": formation_ref}))
                    order_eta_text = assignment.get("order_eta_at")
                    if isinstance(order_eta_text, str) and assignment.get("pending_order") in _VALID_ORDERS:
                        order_eta = CampaignTime.parse(order_eta_text)
                        if current < order_eta <= target:
                            candidates.append((order_eta, {"kind": "order_delivery", "operation_ref": routed_operation_ref, "battlefield_ref": routed_battlefield_ref, "formation_ref": formation_ref}))
                for report in battlefield.get("reports", []):
                    if not isinstance(report, Mapping) or report.get("status") != "queued":
                        continue
                    due_text = report.get("deliver_at")
                    if isinstance(due_text, str):
                        due = CampaignTime.parse(due_text)
                        if current < due <= target:
                            candidates.append((due, {"kind": "report_delivery", "operation_ref": routed_operation_ref, "battlefield_ref": routed_battlefield_ref, "report_id": report.get("report_id")}))
                for sector_ref, sector in sorted((battlefield.get("sectors") or {}).items()):
                    if not isinstance(sector_ref, str) or not isinstance(sector, Mapping):
                        continue
                    rates = self._battlefield_sector_rates(battlefield, sector)
                    pressure = sector.get("pressure_milli") if isinstance(sector.get("pressure_milli"), Mapping) else {}
                    residual = sector.get("pressure_residual") if isinstance(sector.get("pressure_residual"), Mapping) else {}
                    active_levels = sector.get("reported_levels") if isinstance(sector.get("reported_levels"), Mapping) else {}
                    for side_ref in battlefield.get("side_refs", []):
                        if not isinstance(side_ref, str):
                            continue
                        rate = int(rates.get(side_ref, 0))
                        if rate <= 0:
                            continue
                        value = int(pressure.get(side_ref, 0))
                        rem = int(residual.get(side_ref, 0))
                        levels = active_levels.get(side_ref, []) if isinstance(active_levels.get(side_ref, []), list) else []
                        for level, threshold in (("critical", critical), ("collapse", collapse)):
                            if level in levels:
                                continue
                            need = max(0, threshold - value) * 3600 - rem
                            seconds = 1 if need <= 0 else int(math.ceil(need / max(1, rate)))
                            due = current.add_seconds(seconds)
                            if current < due <= target:
                                candidates.append((due, {"kind": "pressure_threshold", "operation_ref": routed_operation_ref, "battlefield_ref": routed_battlefield_ref, "sector_ref": sector_ref, "side_ref": side_ref, "level": level}))
        if not candidates:
            return None, None
        # CampaignTime is intentionally orderable on its mapped BCE chronology.
        # Sorting the rendered ``244-BCE`` text is wrong across a year boundary:
        # lexicographically 243 sorts before 244 even though 243 BCE is later.
        candidates.sort(key=lambda row: (row[0], str(row[1].get("operation_ref", "")), str(row[1].get("battlefield_ref", "")), str(row[1].get("kind", ""))))
        return candidates[0]

    def _battlefield_settle_span(self, start: CampaignTime, end: CampaignTime) -> Dict[str, Any]:
        elapsed = _seconds_between(start, end)
        if elapsed < 0:
            raise ValueError("battlefield time cannot move backward")
        routes = self._battlefield_active_operation_routes()
        if not routes:
            return {"changed": False, "reviews": [], "delivered_reports": [], "player_interrupt": False}
        critical, collapse, reset = self._battlefield_pressure_thresholds()
        changed = False
        reviews: list[Dict[str, Any]] = []
        delivered_to_player: list[Dict[str, Any]] = []
        player_interrupt = False
        autonomous_contacts: list[dict[str, Any]] = []
        for operation_ref, path in routes:
            operation0 = self.read(path)
            if not isinstance(operation0, Mapping) or operation0.get("status") not in {"active", "engaged"}:
                continue
            operation = copy.deepcopy(operation0)
            operation_changes: list[Dict[str, Any]] = []
            battlefields = operation.get("battlefields")
            if not isinstance(battlefields, dict):
                continue
            for battlefield_ref, battlefield in sorted(battlefields.items()):
                if not isinstance(battlefield_ref, str) or not isinstance(battlefield, dict) or battlefield.get("status") not in {"active", "ended"}:
                    continue
                if battlefield.get("status") == "ended":
                    player_sides = self._battlefield_player_side_refs(battlefield)
                    for report in battlefield.get("reports", []):
                        if not isinstance(report, dict) or report.get("status") != "queued":
                            continue
                        due_text = report.get("deliver_at")
                        if not isinstance(due_text, str) or CampaignTime.parse(due_text) > end:
                            continue
                        report["status"] = "delivered"
                        report["delivered_at"] = str(end)
                        operation_changes.append({"kind": "report_delivered", "report_id": report.get("report_id"), "side_ref": report.get("target_side_ref")})
                        if report.get("target_side_ref") in player_sides:
                            enriched = self._battlefield_enrich_player_report(battlefield, report)
                            delivered_to_player.append({"operation_ref": operation_ref, "battlefield_ref": battlefield_ref, **enriched})
                            player_interrupt = player_interrupt or bool(report.get("interrupt_player", True))
                        changed = True
                    self._battlefield_compact_reports(battlefield)
                    battlefield["last_settled_at"] = str(end)
                    battlefield["updated_at"] = str(end)
                    continue
                rates_by_sector: Dict[str, Dict[str, int]] = {}
                for sector_ref, sector in sorted((battlefield.get("sectors") or {}).items()):
                    if not isinstance(sector_ref, str) or not isinstance(sector, dict):
                        continue
                    rates = self._battlefield_sector_rates(battlefield, sector)
                    rates_by_sector[sector_ref] = rates
                    pressure = sector.setdefault("pressure_milli", {})
                    residual = sector.setdefault("pressure_residual", {})
                    reported = sector.setdefault("reported_levels", {})
                    for side_ref in battlefield.get("side_refs", []):
                        if not isinstance(side_ref, str):
                            continue
                        old = int(pressure.get(side_ref, 0))
                        rate = int(rates.get(side_ref, 0))
                        numerator = rate * elapsed + int(residual.get(side_ref, 0))
                        delta, rem = _div_with_signed_remainder(numerator)
                        new = max(0, min(1000, old + delta))
                        pressure[side_ref] = new
                        residual[side_ref] = rem if 0 < new < 1000 else 0
                        levels = reported.setdefault(side_ref, [])
                        if not isinstance(levels, list):
                            levels = []
                            reported[side_ref] = levels
                        if new < critical - reset:
                            levels[:] = [value for value in levels if value not in {"critical", "collapse"}]
                        elif new < collapse - reset:
                            levels[:] = [value for value in levels if value != "collapse"]
                        if new != old:
                            changed = True
                    worst = max((int(pressure.get(side, 0)) for side in battlefield.get("side_refs", []) if isinstance(side, str)), default=0)
                    sector["status"] = "collapse_risk" if worst >= collapse else ("critical" if worst >= critical else "active")
                    sector["last_changed_at"] = str(end)

                # Delegated NPC commanders may commit an actual saved reserve when
                # their own side reaches a configured pressure threshold. This is
                # deterministic operational initiative, not free combat resolution:
                # the same formation physically redeploys through the sector graph,
                # and player-controlled formations are never moved autonomously.
                initiative = self._battlefield_mechanics().get("delegated_initiative")
                if isinstance(initiative, Mapping) and initiative.get("enabled") is True:
                    trigger = int(initiative.get("reserve_commit_pressure_milli", critical))
                    pace = str(initiative.get("reserve_pace", "standard"))
                    reserve_order = str(initiative.get("reserve_order", "attack"))
                    max_commits = max(0, int(initiative.get("max_autonomous_commits_per_boundary", 1)))
                    if pace not in _VALID_PACES or reserve_order not in _VALID_ORDERS or not 0 <= trigger <= 1000:
                        raise ValueError("battlefield delegated initiative mechanics are invalid")
                    commits = 0
                    candidates: list[tuple[int, str, str]] = []
                    for sector_ref, sector in sorted((battlefield.get("sectors") or {}).items()):
                        if not isinstance(sector_ref, str) or not isinstance(sector, Mapping):
                            continue
                        pressure = sector.get("pressure_milli") if isinstance(sector.get("pressure_milli"), Mapping) else {}
                        for side_ref in battlefield.get("side_refs", []):
                            if not isinstance(side_ref, str):
                                continue
                            value = int(pressure.get(side_ref, 0))
                            if value < trigger:
                                continue
                            enemy_present = any(
                                isinstance(other, Mapping)
                                and other.get("status") != "redeploying"
                                and other.get("sector_ref") == sector_ref
                                and other.get("side_ref") != side_ref
                                for other in (battlefield.get("assignments") or {}).values()
                            )
                            if enemy_present:
                                candidates.append((-value, side_ref, sector_ref))
                    for _negative_pressure, side_ref, target_sector_ref in sorted(candidates):
                        if commits >= max_commits:
                            break
                        reserve_refs: list[str] = []
                        for formation_ref, assignment in sorted((battlefield.get("assignments") or {}).items()):
                            if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
                                continue
                            if assignment.get("side_ref") != side_ref or assignment.get("status") != "holding" or assignment.get("order") != "reserve":
                                continue
                            source_sector_ref = assignment.get("sector_ref")
                            if not isinstance(source_sector_ref, str) or source_sector_ref == target_sector_ref:
                                continue
                            try:
                                if self._has_formation_authority(self.PLAYER_ACTOR, formation_ref):
                                    continue
                            except (KeyError, TypeError, ValueError, PermissionError, FileNotFoundError):
                                pass
                            # Formation doctrine is an executable autonomy boundary.
                            # A fixed protection formation may be ordered explicitly
                            # by its lawful commander, but delegated initiative may
                            # not detach it from its protected anchor.
                            try:
                                _formation_path, candidate_formation = self._load_formation(formation_ref)
                                behavior = doctrine_behavior(self.read, candidate_formation)
                            except (KeyError, TypeError, ValueError, PermissionError, FileNotFoundError):
                                behavior = {}
                            if str(behavior.get("autonomous_redeployment", "normal")) == "forbidden":
                                continue
                            if str(behavior.get("detachment_permission", "normal")) == "explicit_order_only":
                                continue
                            reserve_refs.append(formation_ref)
                        if not reserve_refs:
                            continue
                        formation_ref = reserve_refs[0]
                        assignment = battlefield["assignments"][formation_ref]
                        source_sector_ref = str(assignment["sector_ref"])
                        try:
                            path_refs, _distance = self._battlefield_shortest_path(battlefield, source_sector_ref, target_sector_ref)
                        except ValueError:
                            continue
                        _formation_path, formation = self._load_formation(formation_ref)
                        self._battlefield_remove_formation(battlefield, formation_ref)
                        assignment.update({
                            "path_sector_refs": path_refs,
                            "target_sector_ref": target_sector_ref,
                            "pace": pace,
                            "order": reserve_order,
                            "pending_order": None,
                            "order_eta_at": None,
                        })
                        self._battlefield_start_leg(battlefield, assignment, formation, at=end, next_index=1)
                        operation_changes.append({
                            "kind": "delegated_reserve_commitment",
                            "formation_ref": formation_ref,
                            "side_ref": side_ref,
                            "target_sector_ref": target_sector_ref,
                            "pressure_milli": -_negative_pressure,
                            "leg_eta_at": assignment.get("leg_eta_at"),
                        })
                        changed = True
                        commits += 1

                # Orders issued through the command chain take effect only at
                # their delivery boundary. Pressure up to this instant used the
                # previous standing order.
                for formation_ref, assignment in sorted((battlefield.get("assignments") or {}).items()):
                    if not isinstance(formation_ref, str) or not isinstance(assignment, dict):
                        continue
                    pending_order = assignment.get("pending_order")
                    eta_text = assignment.get("order_eta_at")
                    if pending_order not in _VALID_ORDERS or not isinstance(eta_text, str) or CampaignTime.parse(eta_text) > end:
                        continue
                    assignment["order"] = str(pending_order)
                    assignment["pending_order"] = None
                    assignment["order_eta_at"] = None
                    assignment["updated_at"] = str(end)
                    operation_changes.append({"kind": "order_received", "formation_ref": formation_ref, "order": pending_order})
                    changed = True

                # Redeployment legs physically complete before pressure reports are emitted.
                for formation_ref, assignment in sorted((battlefield.get("assignments") or {}).items()):
                    if not isinstance(formation_ref, str) or not isinstance(assignment, dict) or assignment.get("status") != "redeploying":
                        continue
                    eta_text = assignment.get("leg_eta_at")
                    if not isinstance(eta_text, str) or CampaignTime.parse(eta_text) > end:
                        continue
                    arrived = assignment.get("transit_to_sector_ref")
                    path_refs = assignment.get("path_sector_refs")
                    index = assignment.get("path_index")
                    if not isinstance(arrived, str) or not isinstance(path_refs, list) or not isinstance(index, int):
                        raise ValueError("battlefield redeployment state is invalid")
                    sector = battlefield.get("sectors", {}).get(arrived)
                    if not isinstance(sector, dict):
                        raise ValueError("battlefield redeployment arrived at an invalid sector")
                    assignment["sector_ref"] = arrived
                    refs = sector.setdefault("formation_refs", [])
                    if formation_ref not in refs:
                        refs.append(formation_ref)
                        refs.sort()
                    assignment["updated_at"] = str(end)
                    if index >= len(path_refs) - 1:
                        assignment.update({"status": "holding", "target_sector_ref": None, "path_sector_refs": [], "path_index": None, "leg_eta_at": None, "transit_from_sector_ref": None, "transit_to_sector_ref": None})
                        own_side = assignment.get("side_ref")
                        enemy_present = any(
                            isinstance(other, Mapping)
                            and other.get("sector_ref") == arrived
                            and other.get("status") != "redeploying"
                            and other.get("side_ref") != own_side
                            for other in (battlefield.get("assignments") or {}).values()
                        )
                        if enemy_present and isinstance(own_side, str):
                            report = self._battlefield_queue_report(
                                battlefield,
                                sector_ref=arrived,
                                side_ref=own_side,
                                level="contact",
                                pressure_milli=int(sector.get("pressure_milli", {}).get(own_side, 0)),
                                at=end,
                                summary=f"Redeploying formation {formation_ref} has reached {sector.get('name', arrived)} and made enemy contact.",
                            )
                            operation_changes.append({"kind": "contact", "formation_ref": formation_ref, "sector_ref": arrived, "report_id": report["report_id"]})
                            if report.get("status") == "delivered" and own_side in self._battlefield_player_side_refs(battlefield):
                                delivered_to_player.append({"operation_ref": operation_ref, "battlefield_ref": battlefield_ref, **dict(report)})
                        else:
                            operation_changes.append({"kind": "redeployment_arrived", "formation_ref": formation_ref, "sector_ref": arrived})
                    else:
                        _formation_path, formation = self._load_formation(formation_ref)
                        self._battlefield_remove_formation(battlefield, formation_ref)
                        self._battlefield_start_leg(battlefield, assignment, formation, at=end, next_index=index + 1)
                        operation_changes.append({"kind": "redeployment_leg", "formation_ref": formation_ref, "through_sector_ref": arrived, "next_eta_at": assignment.get("leg_eta_at")})
                    changed = True

                # Threshold reports are evidence of deteriorating command position, not casualty settlement.
                for sector_ref, sector in sorted((battlefield.get("sectors") or {}).items()):
                    if not isinstance(sector_ref, str) or not isinstance(sector, dict):
                        continue
                    pressure = sector.get("pressure_milli") if isinstance(sector.get("pressure_milli"), Mapping) else {}
                    reported = sector.get("reported_levels") if isinstance(sector.get("reported_levels"), Mapping) else {}
                    for side_ref in battlefield.get("side_refs", []):
                        if not isinstance(side_ref, str):
                            continue
                        value = int(pressure.get(side_ref, 0))
                        levels = reported.setdefault(side_ref, []) if isinstance(reported, dict) else []
                        for level, threshold in (("critical", critical), ("collapse", collapse)):
                            if value < threshold or level in levels:
                                continue
                            levels.append(level)
                            report = self._battlefield_queue_report(
                                battlefield,
                                sector_ref=sector_ref,
                                side_ref=side_ref,
                                level=level,
                                pressure_milli=value,
                                at=end,
                                summary=(
                                    f"{sector.get('name', sector_ref)} is under critical pressure and needs command attention."
                                    if level == "critical"
                                    else f"{sector.get('name', sector_ref)} is at immediate risk of operational collapse without relief, withdrawal, or a local reversal."
                                ),
                            )
                            operation_changes.append({"kind": "pressure_report_queued", "sector_ref": sector_ref, "side_ref": side_ref, "level": level, "report_id": report["report_id"]})
                            if report.get("status") == "delivered" and side_ref in self._battlefield_player_side_refs(battlefield):
                                delivered_to_player.append({"operation_ref": operation_ref, "battlefield_ref": battlefield_ref, **dict(report)})
                            changed = True

                # Superior command reacts to the same exact sector pressure.
                # Player-directed orders become delayed reports only; they never
                # move or retask Wei's formations without his subsequent action.
                command_changes = review_battle_command_plan(self, operation, battlefield, at=str(end))
                if command_changes:
                    operation_changes.extend(command_changes)
                    changed = True

                # Deliver lawful reports only after their messenger clock expires.
                player_sides = self._battlefield_player_side_refs(battlefield)
                for report in battlefield.get("reports", []):
                    if not isinstance(report, dict) or report.get("status") != "queued":
                        continue
                    due_text = report.get("deliver_at")
                    if not isinstance(due_text, str) or CampaignTime.parse(due_text) > end:
                        continue
                    report["status"] = "delivered"
                    report["delivered_at"] = str(end)
                    operation_changes.append({"kind": "report_delivered", "report_id": report.get("report_id"), "side_ref": report.get("target_side_ref")})
                    if report.get("target_side_ref") in player_sides:
                        enriched = self._battlefield_enrich_player_report(battlefield, report)
                        delivered_to_player.append({"operation_ref": operation_ref, "battlefield_ref": battlefield_ref, **enriched})
                        player_interrupt = player_interrupt or bool(report.get("interrupt_player", True))
                    changed = True
                npc_due_text = battlefield.get("next_autonomous_contact_at")
                if isinstance(npc_due_text, str) and CampaignTime.parse(npc_due_text) <= end:
                    due_at = CampaignTime.parse(npc_due_text)
                    descriptors = self._battlefield_select_autonomous_contacts(battlefield, at=due_at)
                    rules = self._battlefield_autonomous_contact_rules()
                    duration_seconds = max(15, int(rules.get("contact_duration_minutes", rules.get("review_interval_minutes", 90)))) * 60
                    started_at = due_at.add_seconds(-duration_seconds)
                    opened_at_text = battlefield.get("opened_at")
                    if isinstance(opened_at_text, str):
                        opened_at = CampaignTime.parse(opened_at_text)
                        if started_at < opened_at:
                            started_at = opened_at
                    for descriptor in descriptors:
                        autonomous_contacts.append({
                            "operation_ref": operation_ref,
                            "battlefield_ref": battlefield_ref,
                            "descriptor": copy.deepcopy(descriptor),
                            "started_at": started_at,
                            "completed_at": due_at,
                        })
                    battlefield["last_autonomous_contact_at"] = str(due_at)
                    next_due = self._battlefield_next_autonomous_contact_at(due_at)
                    battlefield["next_autonomous_contact_at"] = str(next_due) if next_due is not None else None
                    operation_changes.append({
                        "kind": "autonomous_contact_review",
                        "battlefield_ref": battlefield_ref,
                        "sector_contact_count": len(descriptors),
                        "at": str(due_at),
                    })
                    changed = True

                active_contact = battlefield.get("active_contact")
                if isinstance(active_contact, Mapping):
                    contact_end_text = active_contact.get("ends_at")
                    if isinstance(contact_end_text, str) and CampaignTime.parse(contact_end_text) <= end:
                        completed_contact = copy.deepcopy(dict(active_contact))
                        completed_contact["completed_at"] = str(end)
                        battlefield["last_contact"] = completed_contact
                        battlefield.pop("active_contact", None)
                        operation_changes.append({
                            "kind": "active_contact_completed",
                            "contact_ref": completed_contact.get("contact_ref"),
                            "sector_ref": completed_contact.get("sector_ref"),
                        })
                        changed = True

                conclusion = self._battlefield_conclusion(operation_ref, operation, battlefield, at=end)
                if isinstance(conclusion, Mapping):
                    operation_changes.append(copy.deepcopy(dict(conclusion)))
                    changed = True
                transition = self._battle_lifecycle_transition(battlefield, at=end) if battlefield.get("status") == "active" else None
                if isinstance(transition, Mapping):
                    operation_changes.append(copy.deepcopy(dict(transition)))
                    changed = True
                self._battlefield_compact_reports(battlefield)
                battlefield["last_settled_at"] = str(end)
                battlefield["updated_at"] = str(end)
            if operation_changes:
                self.put(path, operation)
                reviews.append({"operation_ref": operation_ref, "changes": operation_changes})
        for contact in autonomous_contacts:
            result = self._battlefield_resolve_autonomous_contact(**contact)
            reviews.append({
                "operation_ref": contact["operation_ref"],
                "changes": [{
                    "kind": "autonomous_exact_contact_resolved",
                    "battlefield_ref": contact["battlefield_ref"],
                    "sector_ref": contact["descriptor"].get("sector_ref"),
                    "battle_event": result.get("battle_event"),
                    "winner": result.get("winner"),
                    "casualties": copy.deepcopy(result.get("casualties", {})),
                }],
            })
            changed = True
        return {"changed": changed, "reviews": reviews, "delivered_reports": delivered_to_player, "player_interrupt": player_interrupt}

    def _settle_operational_battlefields(self, start: CampaignTime, end: CampaignTime) -> Dict[str, Any]:
        if end < start:
            raise ValueError("battlefield time cannot move backward")
        if end == start:
            return {"changed": False, "reviews": [], "delivered_reports": [], "player_interrupt": False, "reached_time": str(start)}
        cursor = start
        all_reviews: list[Dict[str, Any]] = []
        delivered: list[Dict[str, Any]] = []
        changed = False
        guard = 0
        while cursor < end:
            guard += 1
            if guard > 10000:
                raise RuntimeError("battlefield settlement failed to converge")
            boundary, _detail = self._battlefield_next_boundary_time(cursor, end)
            step = boundary if boundary is not None and boundary < end else end
            if step <= cursor:
                step = cursor.add_seconds(1)
                if step > end:
                    step = end
            result = self._battlefield_settle_span(cursor, step)
            changed = changed or bool(result.get("changed"))
            all_reviews.extend(result.get("reviews", []))
            delivered.extend(result.get("delivered_reports", []))
            cursor = step
            if result.get("player_interrupt"):
                return {
                    "changed": changed,
                    "reviews": all_reviews,
                    "delivered_reports": delivered,
                    "player_interrupt": True,
                    "reached_time": str(cursor),
                }
        return {"changed": changed, "reviews": all_reviews, "delivered_reports": delivered, "player_interrupt": False, "reached_time": str(cursor)}

    def _battlefield_after_action_staff_picture(
        self, operation_ref: str, battlefield: Mapping[str, Any], *, at: CampaignTime
    ) -> dict[str, Any]:
        """Build one compact field staff picture from exact battle/formations.

        The picture is a projection on the existing operation, not another battle
        owner.  It summarizes only battle receipts tied to this battlefield and
        current formation condition after those receipts have already settled.
        """
        battlefield_ref = str(battlefield.get("battlefield_ref", ""))
        assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
        event_rows: list[Mapping[str, Any]] = []
        for event in iter_history_events(self):
            if str(event.get("kind", "")) != "battle":
                continue
            if str(event.get("operation_ref", "")) != operation_ref:
                continue
            event_battlefield = str(event.get("operational_battlefield_ref") or event.get("battlefield_ref") or "")
            if event_battlefield != battlefield_ref:
                continue
            event_rows.append(event)
        event_rows.sort(key=lambda row: (str(row.get("at", "")), str(row.get("event_id", ""))))

        casualties_by_formation: dict[str, int] = {}
        for event in event_rows:
            killed = event.get("killed")
            if not isinstance(killed, Mapping):
                continue
            for formation_ref, value in killed.items():
                if not isinstance(formation_ref, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                casualties_by_formation[formation_ref] = casualties_by_formation.get(formation_ref, 0) + max(0, int(value))

        sides: dict[str, dict[str, Any]] = {}
        formation_rows: list[dict[str, Any]] = []
        for formation_ref, assignment in sorted(assignments.items()):
            if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
                continue
            side_ref = str(assignment.get("side_ref", ""))
            if not side_ref:
                continue
            try:
                _formation_path, formation = self._load_formation(formation_ref)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            personnel = max(0, int(formation.get("personnel", 0) or 0))
            casualties = max(0, int(casualties_by_formation.get(formation_ref, 0)))
            row = {
                "formation_ref": formation_ref,
                "side_ref": side_ref,
                "personnel_remaining": personnel,
                "battle_killed": casualties,
                "status": formation.get("status"),
                "readiness": formation.get("readiness"),
                "fatigue": formation.get("fatigue"),
                "cohesion": formation.get("cohesion"),
                "morale": formation.get("morale"),
            }
            formation_rows.append(row)
            side = sides.setdefault(side_ref, {
                "formation_count": 0,
                "personnel_remaining": 0,
                "battle_killed": 0,
                "destroyed_formation_count": 0,
            })
            side["formation_count"] += 1
            side["personnel_remaining"] += personnel
            side["battle_killed"] += casualties
            if personnel <= 0 or str(formation.get("status", "")) == "destroyed":
                side["destroyed_formation_count"] += 1

        picture = {
            "battlefield_ref": battlefield_ref,
            "reviewed_at": str(at),
            "outcome": copy.deepcopy(dict(battlefield.get("outcome") or {})),
            "battle_event_refs": [str(row.get("event_id")) for row in event_rows if isinstance(row.get("event_id"), str)],
            "side_summary": {side: sides[side] for side in sorted(sides)},
            "formation_summary": formation_rows,
            "scope": "field_battle_after_action",
            "authority_rule": "This staff picture summarizes already-settled battle evidence. It does not end the campaign, create casualties, move formations, or grant rewards.",
        }
        return picture

    def _battlefield_issue_follow_on_direction(
        self,
        operation_ref: str,
        operation: dict[str, Any],
        battlefield: Mapping[str, Any],
        after_action: Mapping[str, Any],
        *,
        at: CampaignTime,
    ) -> dict[str, Any] | None:
        """Issue the immediate superior post-battle phase order for Wei's command.

        This is intentionally conservative.  The field commander is told how to
        secure/re-form after the concluded battle, while pursuit, a new strategic
        destination, peace, or another battle still require their own exact causal
        basis.  House/retinue auxiliaries may remain attached without transferring
        institutional ownership to the state.
        """
        plan = battlefield.get("command_plan") if isinstance(battlefield.get("command_plan"), Mapping) else {}
        mission_index = plan.get("mission_index") if isinstance(plan.get("mission_index"), Mapping) else {}
        player_missions: list[Mapping[str, Any]] = []
        for mission in mission_index.values():
            if not isinstance(mission, Mapping):
                continue
            refs = [str(ref) for ref in mission.get("formation_refs", []) if isinstance(ref, str)]
            if str(mission.get("recipient_ref", "")) == "char_tang_wei" or any(self._battlefield_player_controls_formation(ref) for ref in refs):
                player_missions.append(mission)
        if not player_missions:
            return None

        player_refs = sorted({
            str(ref)
            for mission in player_missions
            for ref in mission.get("formation_refs", []) if isinstance(ref, str)
        })
        player_side = None
        assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
        for ref in player_refs:
            assignment = assignments.get(ref)
            if isinstance(assignment, Mapping) and isinstance(assignment.get("side_ref"), str):
                player_side = str(assignment.get("side_ref")); break
        outcome = battlefield.get("outcome") if isinstance(battlefield.get("outcome"), Mapping) else {}
        winner = outcome.get("winner_side_ref")
        loser = outcome.get("loser_side_ref")
        if player_side and winner == player_side:
            directive = "secure_field_reorganize_and_maintain_contact"
            objective = (
                "secure the concluded battlefield, account for casualties, re-form the field command, maintain reconnaissance of the withdrawing enemy, "
                "and remain ready for the next campaign order; do not treat this field victory as the end of the war"
            )
        elif player_side and loser == player_side:
            directive = "rally_reorganize_after_field_withdrawal"
            objective = (
                "complete the field withdrawal, re-form surviving formations under command, account for casualties, restore command cohesion, "
                "and remain ready for the next campaign order; the campaign remains active unless wider authority ends it"
            )
        else:
            directive = "reform_after_disengagement"
            objective = (
                "re-form the field command after disengagement, account for casualties, maintain reconnaissance and security, and await the next campaign order"
            )

        institutional_owner = str(operation.get("institutional_owner_ref") or operation.get("administrative_authority") or "")
        state_refs: list[str] = []
        auxiliary_refs: list[str] = []
        for ref in player_refs:
            try:
                _formation_path, formation = self._load_formation(ref)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            owner = str(formation.get("administrative_owner") or "")
            if institutional_owner and owner == institutional_owner:
                state_refs.append(ref)
            else:
                auxiliary_refs.append(ref)

        issuer_ref = next((str(m.get("issuer_ref")) for m in player_missions if isinstance(m.get("issuer_ref"), str) and m.get("issuer_ref")), institutional_owner or player_side or "superior_command")
        superior_commander_ref = operation.get("campaign_commander_ref") or operation.get("supreme_commander_ref")
        superior_commander_ref = superior_commander_ref if isinstance(superior_commander_ref, str) and superior_commander_ref else None
        coordination_authority_ref = operation.get("coordination_authority_ref")
        coordination_authority_ref = coordination_authority_ref if isinstance(coordination_authority_ref, str) and coordination_authority_ref else None
        token = hashlib.sha256(f"{operation_ref}|{battlefield.get('battlefield_ref')}|{directive}|{at}".encode()).hexdigest()[:18]
        order_ref = f"operational_order_post_battle_{token}"
        order = {
            "order_ref": order_ref,
            "issued_at": str(at),
            "issuer_ref": issuer_ref,
            "superior_commander_ref": superior_commander_ref,
            "coordination_authority_ref": coordination_authority_ref,
            "objective": objective,
            "status": "issued_awaiting_commander_execution",
            "actionability_status": "actionable",
            "post_battle_directive": directive,
            "battlefield_ref": battlefield.get("battlefield_ref"),
            "applies_to_formation_refs": state_refs,
            "accompanying_non_state_formation_refs": auxiliary_refs,
            "after_action_ref": f"{battlefield.get('battlefield_ref')}.after_action",
            "agency_rule": (
                "Superior command establishes the post-battle military objective for formations under its authority. Tang Wei still chooses protected tactics, "
                "pursuit, dialogue and voluntary use of privately owned auxiliaries; no troop ownership transfers by this order."
            ),
        }
        orders = operation.setdefault("operational_orders", [])
        if not isinstance(orders, list):
            orders = []
            operation["operational_orders"] = orders
        orders.append(order)
        operation["operational_orders"] = orders[-16:]
        operation["last_operational_order_ref"] = order_ref
        operation["last_operational_order_at"] = str(at)
        operation["order_status"] = "post_battle_direction_issued"
        operation["campaign_phase"] = "post_battle_reorganization_under_superior_order"
        return order

    def _battlefield_conclusion(self, operation_ref: str, operation: dict[str, Any], battlefield: dict[str, Any], *, at: CampaignTime) -> dict[str, Any] | None:
        """Conclude a field battle only from exact terminal battlefield evidence.

        Local contact victories never end the battle. Terminal evidence must be
        side-wide and exact: destruction, received withdrawal, accepted surrender,
        severe routed/disintegrated formations, explicit two-sided disengagement/
        non-renewal, or superior-command objective completion. The enclosing campaign
        operation remains alive.
        """
        if battlefield.get("status") != "active":
            return None
        assignments = battlefield.get("assignments") if isinstance(battlefield.get("assignments"), Mapping) else {}
        side_refs = [str(side) for side in battlefield.get("side_refs", []) if isinstance(side, str)]
        if len(side_refs) != 2:
            return None
        live: dict[str, list[str]] = {side: [] for side in side_refs}
        withdrawn: dict[str, list[str]] = {side: [] for side in side_refs}
        surrendered: dict[str, list[str]] = {side: [] for side in side_refs}
        routed_collapsed: dict[str, list[str]] = {side: [] for side in side_refs}
        terminal_rules = self._battlefield_mechanics().get("battle_terminal") or {}
        rout_morale = max(0, int(terminal_rules.get("rout_morale_max", 15) or 15))
        rout_cohesion = max(0, int(terminal_rules.get("rout_cohesion_max", 15) or 15))
        for formation_ref, assignment in sorted(assignments.items()):
            if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
                continue
            side = assignment.get("side_ref")
            if side not in live:
                continue
            try:
                _path, formation = self._load_formation(formation_ref)
            except (FileNotFoundError, KeyError, ValueError):
                continue
            status = str(formation.get("status", ""))
            if int(formation.get("personnel", 0) or 0) <= 0 or status == "destroyed":
                continue
            surrender_state = formation.get("surrender_state") if isinstance(formation.get("surrender_state"), Mapping) else {}
            if status == "surrendered" or str(surrender_state.get("status", "")) == "accepted":
                surrendered[str(side)].append(formation_ref)
                continue
            live[str(side)].append(formation_ref)
            if status == "routed" and int(formation.get("morale", 100) or 0) <= rout_morale and int(formation.get("cohesion", 100) or 0) <= rout_cohesion:
                routed_collapsed[str(side)].append(formation_ref)
            if assignment.get("status") != "redeploying" and assignment.get("order") == "withdraw" and not assignment.get("pending_order"):
                withdrawn[str(side)].append(formation_ref)

        terminal: dict[str, str] = {}
        for side in side_refs:
            if not live[side]:
                terminal[side] = "side_surrendered" if surrendered[side] else "no_surviving_committed_formations"
            elif len(withdrawn[side]) == len(live[side]):
                terminal[side] = "side_wide_withdrawal_order_received"
            elif len(routed_collapsed[side]) == len(live[side]):
                terminal[side] = "side_wide_rout_disintegration"

        explicit: tuple[str | None, str | None, str] | None = None
        for evidence in reversed(battlefield.get("termination_evidence", []) if isinstance(battlefield.get("termination_evidence"), list) else []):
            if not isinstance(evidence, Mapping):
                continue
            kind = str(evidence.get("kind", ""))
            if kind == "surrender" and str(evidence.get("side_ref", "")) in side_refs:
                terminal[str(evidence["side_ref"])] = "side_surrendered"
                break
            if kind == "objective_complete" and str(evidence.get("winner_side_ref", "")) in side_refs:
                winner = str(evidence["winner_side_ref"]); loser = next(side for side in side_refs if side != winner)
                explicit = (winner, loser, "field_objective_completed_by_superior_command")
                break
            accepted = sorted({str(x) for x in evidence.get("accepted_side_refs", []) if isinstance(x, str)})
            if kind == "mutual_disengagement" and accepted == sorted(side_refs):
                explicit = (None, None, "mutual_disengagement_by_authority")
                break
            if kind == "non_renewal" and accepted == sorted(side_refs) and str((battlefield.get("day_cycle") or {}).get("posture", "")) == "night_camp":
                explicit = (None, None, "dusk_non_renewal")
                break

        if explicit is None and not terminal:
            return None
        if explicit is not None:
            winner_side, loser_side, reason = explicit
        elif len(terminal) == 2:
            winner_side = None; loser_side = None; reason = "mutual_disengagement"
        else:
            loser_side = next(iter(terminal)); winner_side = next(side for side in side_refs if side != loser_side); reason = terminal[loser_side]
        outcome = {
            "concluded_at": str(at),
            "winner_side_ref": winner_side,
            "loser_side_ref": loser_side,
            "reason": reason,
            "live_formation_refs_by_side": {side: sorted(refs) for side, refs in live.items()},
            "withdrawn_formation_refs_by_side": {side: sorted(refs) for side, refs in withdrawn.items()},
            "surrendered_formation_refs_by_side": {side: sorted(refs) for side, refs in surrendered.items()},
            "routed_collapsed_formation_refs_by_side": {side: sorted(refs) for side, refs in routed_collapsed.items()},
            "scope": "field_battle_only",
            "campaign_continues_rule": "Field-battle conclusion does not itself end the enclosing operation, campaign, or war.",
        }
        battlefield["status"] = "ended"
        battlefield["closed_at"] = str(at)
        battlefield["outcome"] = copy.deepcopy(outcome)
        battlefield["updated_at"] = str(at)
        plan = battlefield.get("command_plan")
        if isinstance(plan, dict):
            for mission in (plan.get("mission_index") or {}).values():
                if isinstance(mission, dict) and mission.get("status") == "active":
                    mission["status"] = "battle_concluded"
                    mission["concluded_at"] = str(at)
        operation["campaign_phase"] = "battle_concluded_awaiting_superior_direction"
        operation["last_battlefield_outcome"] = {"battlefield_ref": battlefield.get("battlefield_ref"), **copy.deepcopy(outcome)}
        after_action = self._battlefield_after_action_staff_picture(operation_ref, battlefield, at=at)
        battlefield["after_action"] = copy.deepcopy(after_action)
        operation["last_battlefield_after_action"] = copy.deepcopy(after_action)
        follow_on_order = self._battlefield_issue_follow_on_direction(
            operation_ref, operation, battlefield, after_action, at=at
        )
        if isinstance(follow_on_order, Mapping):
            outcome["follow_on_order_ref"] = follow_on_order.get("order_ref")
            battlefield["outcome"] = copy.deepcopy(outcome)
            operation["last_battlefield_outcome"] = {"battlefield_ref": battlefield.get("battlefield_ref"), **copy.deepcopy(outcome)}

        event_id = "battlefield_conclusion_" + hashlib.sha256(
            f"{operation_ref}|{battlefield.get('battlefield_ref')}|{at}|{reason}".encode()
        ).hexdigest()[:18]
        history = copy.deepcopy(self.read("state/history/events/index.json"))
        if not any(isinstance(row, Mapping) and row.get("event_id") == event_id for row in history.get("events", [])):
            history.setdefault("events", []).append({
                "event_id": event_id, "kind": "battlefield_conclusion", "at": str(at),
                "operation_ref": operation_ref, "battlefield_ref": battlefield.get("battlefield_ref"), **copy.deepcopy(outcome),
            })
            write_history_index(self, history)

        player_sides = self._battlefield_player_side_refs(battlefield)
        for side in sorted(player_sides):
            sector_ref = next((
                str(a.get("sector_ref")) for ref, a in assignments.items()
                if isinstance(ref, str) and isinstance(a, Mapping) and a.get("side_ref") == side
                and self._battlefield_player_controls_formation(ref) and isinstance(a.get("sector_ref"), str)
            ), None)
            if not sector_ref:
                continue
            follow_on_text = ""
            if isinstance(follow_on_order, Mapping) and follow_on_order.get("objective"):
                follow_on_text = f" Immediate superior direction: {follow_on_order.get('objective')}."
            if winner_side == side:
                summary = "The opposing field force has withdrawn or ceased effective resistance. The battle is concluded; the wider campaign remains active." + follow_on_text
            elif loser_side == side:
                summary = "Your side has completed a field withdrawal. The battle is concluded; the wider campaign remains active." + follow_on_text
            else:
                summary = "Both sides have disengaged from the field. The battle is concluded; the wider campaign remains active." + follow_on_text
            self._battlefield_queue_report(
                battlefield, sector_ref=sector_ref, side_ref=side, level="battle_concluded",
                pressure_milli=0, at=at, summary=summary, interrupt_player=True,
            )
        return {"kind": "battlefield_concluded", "battlefield_ref": battlefield.get("battlefield_ref"), **outcome}

    def _battlefield_validate_contact(self, *, operation_ref: str, battlefield_ref: str, sector_ref: str, attacker_refs: Sequence[str], defender_refs: Sequence[str]) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
        path, operation = self._battlefield_operation(operation_ref)
        battlefield = (operation.get("battlefields") or {}).get(battlefield_ref)
        if not isinstance(battlefield, dict) or battlefield.get("status") != "active":
            raise ValueError("operational battlefield is not active")
        sector = (battlefield.get("sectors") or {}).get(sector_ref)
        if not isinstance(sector, Mapping):
            raise ValueError("operational battlefield sector is invalid")
        assignments = battlefield.get("assignments")
        if not isinstance(assignments, Mapping):
            raise ValueError("operational battlefield assignments are invalid")
        all_refs = list(attacker_refs) + list(defender_refs)
        if any(ref not in assignments for ref in all_refs):
            raise ValueError("battle contact includes a formation not assigned to the operational battlefield")
        for ref in all_refs:
            assignment = assignments[ref]
            if not isinstance(assignment, Mapping) or assignment.get("status") == "redeploying" or assignment.get("sector_ref") != sector_ref:
                raise ValueError("battle contact formations must be physically present in the selected sector")
        attacker_sides = {assignments[ref].get("side_ref") for ref in attacker_refs}
        defender_sides = {assignments[ref].get("side_ref") for ref in defender_refs}
        if len(attacker_sides) != 1 or len(defender_sides) != 1 or attacker_sides == defender_sides:
            raise ValueError("battle contact must oppose two battlefield sides")
        return path, operation, battlefield

    def _battlefield_contact_reconciliation_owner(
        self,
        *,
        operation_ref: str,
        battlefield_ref: str,
        sector_ref: str,
        attacker_refs: Sequence[str],
        defender_refs: Sequence[str],
        event_id: str,
    ) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
        """Resolve the exact battlefield owner for a contact result at its boundary.

        Normally the combatants remain physically in the sector. A causal host
        due at the exact contact boundary may begin a redeployment before the
        post-contact pressure reconciliation runs. In that narrow case the saved
        ``last_contact`` marker is authoritative proof of the just-completed
        geometry and participant set. It never authorizes a new contact.
        """
        try:
            return self._battlefield_validate_contact(
                operation_ref=operation_ref,
                battlefield_ref=battlefield_ref,
                sector_ref=sector_ref,
                attacker_refs=attacker_refs,
                defender_refs=defender_refs,
            )
        except ValueError as current_error:
            path, operation = self._battlefield_operation(operation_ref)
            battlefield = (operation.get("battlefields") or {}).get(battlefield_ref)
            if not isinstance(battlefield, dict) or battlefield.get("status") != "active":
                raise current_error
            last_contact = battlefield.get("last_contact")
            if not isinstance(last_contact, Mapping):
                raise current_error
            if last_contact.get("contact_ref") != event_id or last_contact.get("sector_ref") != sector_ref:
                raise current_error
            if sorted(str(ref) for ref in last_contact.get("attacker_formation_refs", [])) != sorted(str(ref) for ref in attacker_refs):
                raise current_error
            if sorted(str(ref) for ref in last_contact.get("defender_formation_refs", [])) != sorted(str(ref) for ref in defender_refs):
                raise current_error
            sector = (battlefield.get("sectors") or {}).get(sector_ref)
            assignments = battlefield.get("assignments")
            if not isinstance(sector, Mapping) or not isinstance(assignments, Mapping):
                raise current_error
            if any(ref not in assignments for ref in [*attacker_refs, *defender_refs]):
                raise current_error
            attacker_sides = {assignments[ref].get("side_ref") for ref in attacker_refs if isinstance(assignments.get(ref), Mapping)}
            defender_sides = {assignments[ref].get("side_ref") for ref in defender_refs if isinstance(assignments.get(ref), Mapping)}
            if len(attacker_sides) != 1 or len(defender_sides) != 1 or attacker_sides == defender_sides:
                raise current_error
            return path, operation, battlefield

    def _battlefield_apply_battle_result(self, *, operation_ref: str, battlefield_ref: str, sector_ref: str, attacker_refs: Sequence[str], defender_refs: Sequence[str], winner: str, event_id: str, at: CampaignTime, hero_object_pressure: Optional[Mapping[str, Any]] = None, local_breach_summary: Optional[Mapping[str, Any]] = None, contact_duration_factor: float = 1.0) -> list[dict[str, Any]]:
        path, operation, battlefield = self._battlefield_contact_reconciliation_owner(
            operation_ref=operation_ref,
            battlefield_ref=battlefield_ref,
            sector_ref=sector_ref,
            attacker_refs=attacker_refs,
            defender_refs=defender_refs,
            event_id=event_id,
        )
        assignments = battlefield["assignments"]
        attacker_side = next(iter({assignments[ref]["side_ref"] for ref in attacker_refs}))
        defender_side = next(iter({assignments[ref]["side_ref"] for ref in defender_refs}))
        winner_side = attacker_side if winner == "attacker" else defender_side
        loser_side = defender_side if winner == "attacker" else attacker_side
        sector = battlefield["sectors"][sector_ref]
        pressure = sector.setdefault("pressure_milli", {})
        pressure_scale = max(0.01, min(1.0, float(contact_duration_factor or 0.0)))
        winner_relief = max(1, int(round(120 * pressure_scale)))
        loser_pressure = max(1, int(round(180 * pressure_scale)))
        pressure[winner_side] = max(0, int(pressure.get(winner_side, 0)) - winner_relief)
        pressure[loser_side] = min(1000, int(pressure.get(loser_side, 0)) + loser_pressure)
        consequences: list[dict[str, Any]] = []
        sector["last_combat"] = {"event_id": event_id, "winner_side_ref": winner_side, "loser_side_ref": loser_side, "at": str(at)}
        if isinstance(local_breach_summary, Mapping):
            sector["last_combat"]["local_breach_summary"] = copy.deepcopy(dict(local_breach_summary))

        # Named heroes may disrupt an exact operational command/signals owner, but
        # pressure never creates a standard, HQ, relay, or installation that is not
        # already represented by this battlefield/sector. Disruption is keyed by
        # the side suffering it because both coalitions occupy the same sector.
        pressure_row = hero_object_pressure if isinstance(hero_object_pressure, Mapping) else {}
        officer = max(0.0, float(pressure_row.get("officer_pressure", 0.0) or 0.0)) * pressure_scale
        cohesion = max(0.0, float(pressure_row.get("cohesion_shock_pressure", 0.0) or 0.0)) * pressure_scale
        artillery = max(0.0, float(pressure_row.get("artillery_pressure", 0.0) or 0.0)) * pressure_scale
        command_add = min(420, max(0, int(round(officer * 10.0 + cohesion * 3.5))))
        signal_add = min(420, max(0, int(round(cohesion * 7.0 + officer * 3.0))))
        artillery_add = min(500, max(0, int(round(artillery * 8.0))))
        if command_add:
            bucket = sector.setdefault("command_disruption_milli", {})
            bucket[loser_side] = min(1000, max(0, int(bucket.get(loser_side, 0))) + command_add)
            consequences.append({"kind": "sector_command_disruption", "sector_ref": sector_ref, "affected_side_ref": loser_side, "added_milli": command_add, "total_milli": int(bucket[loser_side])})
        if signal_add:
            bucket = sector.setdefault("signal_disruption_milli", {})
            bucket[loser_side] = min(1000, max(0, int(bucket.get(loser_side, 0))) + signal_add)
            consequences.append({"kind": "sector_signal_disruption", "sector_ref": sector_ref, "affected_side_ref": loser_side, "added_milli": signal_add, "total_milli": int(bucket[loser_side])})
            if int(bucket[loser_side]) >= 250:
                disrupted = sector.setdefault("signal_network_disrupted_by_side", {})
                disrupted[loser_side] = {"at": str(at), "event_id": event_id, "disruption_milli": int(bucket[loser_side]), "caused_by_side_ref": winner_side}
                consequences.append({"kind": "exact_signal_network_disrupted", "sector_ref": sector_ref, "affected_side_ref": loser_side, "disruption_milli": int(bucket[loser_side])})
        if artillery_add:
            bucket = sector.setdefault("artillery_disruption_milli", {})
            bucket[loser_side] = min(1000, max(0, int(bucket.get(loser_side, 0))) + artillery_add)
            consequences.append({"kind": "sector_artillery_disruption", "sector_ref": sector_ref, "affected_side_ref": loser_side, "added_milli": artillery_add, "total_milli": int(bucket[loser_side])})
        # Exact tactical objects are bound when the battlefield opens from saved
        # operation geography. A local battle can seize a gate/bridge tactically
        # without changing sovereignty. Fixed artillery can be physically degraded
        # only when an exact artillery owner is actually bound to this sector.
        for binding in battlefield.get("physical_object_bindings", []) if isinstance(battlefield.get("physical_object_bindings"), list) else []:
            if not isinstance(binding, Mapping) or str(binding.get("sector_ref")) != sector_ref:
                continue
            kind=str(binding.get("kind", "")); object_ref=str(binding.get("object_ref", ""))
            if kind in {"gate_access", "bridge_crossing"} and object_ref:
                control=battlefield.setdefault("tactical_object_control", {})
                previous=control.get(object_ref) if isinstance(control, Mapping) else None
                control[object_ref]={"kind":kind,"held_by_side_ref":winner_side,"at":str(at),"event_id":event_id,"previous":copy.deepcopy(previous)}
                consequences.append({"kind":"exact_gate_seized" if kind=="gate_access" else "exact_bridge_seized","sector_ref":sector_ref,"object_ref":object_ref,"held_by_side_ref":winner_side,"previous_control":copy.deepcopy(previous)})
            elif kind=="fixed_artillery" and object_ref and artillery_add>0:
                total_art=int((sector.get("artillery_disruption_milli") or {}).get(loser_side,0))
                if total_art>=250:
                    try:
                        art_path=self.owner_path(object_ref); art=copy.deepcopy(self.read(art_path))
                    except Exception:
                        art_path=None; art=None
                    if isinstance(art,dict) and art_path:
                        condition=art.setdefault("condition",{})
                        before_condition=max(0.0,min(100.0,float(condition.get("condition_percent",100.0) or 100.0)))
                        total_installed=sum(max(0,int(v)) for v in (art.get("installed",{}) or {}).values() if isinstance(v,(int,float)))
                        damage_pct=min(28.0,max(1.0,total_art/35.0))
                        after_condition=max(0.0,before_condition-damage_pct)
                        damaged=max(1,int(round(total_installed*min(.22,total_art/5000.0)))) if total_installed>0 else 0
                        destroyed=max(0,int(round(total_installed*max(0.0,total_art-600)/12000.0))) if total_installed>0 else 0
                        condition["condition_percent"]=round(after_condition,3)
                        condition["damaged_installations"]=min(total_installed,max(int(condition.get("damaged_installations",0) or 0),damaged))
                        condition["destroyed_installations"]=min(total_installed,max(int(condition.get("destroyed_installations",0) or 0),destroyed))
                        art.setdefault("damage_history",[]).append({"at":str(at),"event_id":event_id,"kind":"hero_local_artillery_neutralization","disruption_milli":total_art,"condition_before_percent":round(before_condition,3),"condition_after_percent":round(after_condition,3),"damaged_installations":damaged,"destroyed_installations":destroyed})
                        art["damage_history"]=art["damage_history"][-32:]
                        self.put(art_path,art)
                        consequences.append({"kind":"exact_fixed_artillery_neutralized","sector_ref":sector_ref,"object_ref":object_ref,"disruption_milli":total_art,"condition_before_percent":round(before_condition,3),"condition_after_percent":round(after_condition,3),"damaged_installations":damaged,"destroyed_installations":destroyed})
        hq_ref = self._battlefield_hq_sector(battlefield)
        if hq_ref == sector_ref and command_add > 0:
            total = int((sector.get("command_disruption_milli") or {}).get(loser_side, 0))
            if total >= 250:
                hq = sector.setdefault("hq_disrupted_by_side", {})
                hq[loser_side] = {"at": str(at), "event_id": event_id, "disruption_milli": total, "caused_by_side_ref": winner_side}
                consequences.append({"kind": "exact_hq_disrupted", "sector_ref": sector_ref, "affected_side_ref": loser_side, "disruption_milli": total})
        sector["last_combat"]["hero_object_consequences"] = copy.deepcopy(consequences)
        sector["last_changed_at"] = str(at)
        battlefield["updated_at"] = str(at)
        changes = [{"kind": "exact_battle_reconciled", "battlefield_ref": battlefield_ref, "sector_ref": sector_ref, "event_id": event_id, "winner_side_ref": winner_side, "loser_side_ref": loser_side}]
        changes.extend({"kind": row["kind"], "battlefield_ref": battlefield_ref, "sector_ref": sector_ref, "event_id": event_id, **{k: v for k, v in row.items() if k != "kind"}} for row in consequences)
        self.put(path, operation)
        return consequences

    def _battlefield_control(self, command: Any, payload: Mapping[str, Any]) -> Dict[str, Any]:
        action = str(payload.get("action", ""))
        if action not in {"open", "assign", "redeploy", "set_order", "record_terminal_evidence", "close"}:
            raise ValueError("unknown battlefield action")
        operation_ref = str(payload.get("operation_ref", ""))
        battlefield_ref = str(payload.get("battlefield_ref", ""))
        if not operation_ref or not battlefield_ref.startswith("battlefield_"):
            raise ValueError("battlefield control requires stable operation_ref and battlefield_ref")
        path, operation = self._battlefield_operation(operation_ref)
        if operation.get("status") not in {"active", "engaged"} and action != "close":
            raise ValueError("battlefield control requires an active or engaged operation")
        battlefields = operation.setdefault("battlefields", {})
        if not isinstance(battlefields, dict):
            raise ValueError("operation battlefield registry is invalid")
        now = self._world_time()
        affected_ref: Optional[str] = None

        if action == "open":
            if battlefield_ref in battlefields:
                raise ValueError("battlefield_ref already exists in operation")
            name = str(payload.get("name", "")).strip()
            layout_ref = str(payload.get("layout_ref", ""))
            side_refs = payload.get("side_refs")
            if not name or len(name) > 200:
                raise ValueError("battlefield name is invalid")
            # The caller may name the two lawful sides but may not place an
            # enemy formation onto an invented side. Derive every formation's
            # operational coalition from its exact owner/House/polity state.
            side_by_formation: Dict[str, str] = {}
            owner_by_formation: Dict[str, str] = {}
            for raw_ref in operation.get("formation_refs", []):
                formation_ref = str(raw_ref)
                _formation_path, formation = self._load_formation(formation_ref)
                owner_by_formation[formation_ref] = self._battlefield_formation_owner_key(formation)
                side_by_formation[formation_ref] = self._battlefield_formation_side_hint(formation)
            derived_sides = set(side_by_formation.values())
            if len(derived_sides) != 2:
                raise ValueError("operational battlefield requires exactly two derived coalitions")
            if side_refs is None:
                side_refs = sorted(derived_sides)
            if not isinstance(side_refs, Sequence) or isinstance(side_refs, (str, bytes, bytearray)) or len(side_refs) != 2 or any(not isinstance(side, str) or not side for side in side_refs) or len(set(side_refs)) != 2:
                raise ValueError("battlefield requires exactly two distinct side_refs")
            if derived_sides != set(str(side) for side in side_refs):
                raise ValueError("battlefield side_refs must match the two exact operational coalitions represented by the saved operation")
            layouts = self._battlefield_mechanics().get("layouts")
            layout = layouts.get(layout_ref) if isinstance(layouts, Mapping) else None
            if not isinstance(layout, Mapping):
                raise ValueError("unknown battlefield layout_ref")
            sectors: Dict[str, Any] = {}
            keys: Dict[str, str] = {}
            for row in layout.get("sectors", []):
                if not isinstance(row, Mapping) or not isinstance(row.get("key"), str) or not isinstance(row.get("name"), str):
                    raise ValueError("battlefield layout is invalid")
                sector_ref = self._battlefield_ref(battlefield_ref, row["key"])
                keys[row["key"]] = sector_ref
                sectors[sector_ref] = {
                    "sector_ref": sector_ref,
                    "id": sector_ref,
                    "name": row["name"],
                    "terrain": self._battlefield_sector_terrain(str(operation.get("location_ref") or ""), str(row["key"])),
                    "status": "active",
                    "formation_refs": [],
                    "pressure_milli": {str(side_refs[0]): 0, str(side_refs[1]): 0},
                    "pressure_residual": {str(side_refs[0]): 0, str(side_refs[1]): 0},
                    "reported_levels": {str(side_refs[0]): [], str(side_refs[1]): []},
                    "last_changed_at": str(now),
                }
            edges = []
            for row in layout.get("edges", []):
                if not isinstance(row, Mapping) or row.get("a") not in keys or row.get("b") not in keys:
                    raise ValueError("battlefield layout edge is invalid")
                distance = row.get("distance_units")
                if isinstance(distance, bool) or not isinstance(distance, int) or distance <= 0:
                    raise ValueError("battlefield layout edge distance is invalid")
                edges.append({"a": keys[row["a"]], "b": keys[row["b"]], "distance_units": distance})
            battlefield = {
                "schema": "sword-operational-battlefield",
                "battlefield_ref": battlefield_ref,
                "name": name,
                "status": "active",
                "location_ref": operation.get("location_ref"),
                "layout_ref": layout_ref,
                "side_refs": [str(side_refs[0]), str(side_refs[1])],
                "owner_side_refs": {},
                "sectors": sectors,
                "sector_edges": edges,
                "assignments": {},
                "reports": [],
                "opened_at": str(now),
                "closed_at": None,
                "last_settled_at": str(now),
                "updated_at": str(now),
                "day_cycle": self._battle_lifecycle_initial_cycle(now),
                "next_autonomous_contact_at": (str(self._battlefield_next_autonomous_contact_at(now)) if self._battlefield_next_autonomous_contact_at(now) is not None else None),
                "last_autonomous_contact_at": None,
            }
            battlefield["physical_object_bindings"] = self._battlefield_exact_object_bindings(operation, battlefield)
            battlefield["tactical_object_control"] = {}
            # Bootstrap a neutral deployment from the exact formations already
            # committed to the operation. This is deterministic geometry, not a
            # caller-authored enemy choice. Commanders can then issue real timed
            # redeployments from these starting positions.
            frontline_keys = [str(key) for key in layout.get("frontline_keys", []) if str(key) in keys]
            if not frontline_keys:
                frontline_keys = [key for key in keys if key not in {str(layout.get("reserve_key", "reserve")), str(layout.get("command_key", "command"))}]
            if not frontline_keys:
                raise ValueError("battlefield layout has no frontline sectors")
            reserve_key = str(layout.get("reserve_key", "reserve"))
            reserve_ref = keys.get(reserve_key)
            by_side: Dict[str, list[str]] = {str(side_refs[0]): [], str(side_refs[1]): []}
            for formation_ref, side_ref in sorted(side_by_formation.items()):
                by_side[side_ref].append(formation_ref)
                battlefield["owner_side_refs"][owner_by_formation[formation_ref]] = side_ref
            for side_ref, formation_refs in sorted(by_side.items()):
                for index, formation_ref in enumerate(sorted(formation_refs)):
                    use_reserve = isinstance(reserve_ref, str) and len(formation_refs) >= 4 and index == len(formation_refs) - 1
                    sector_ref = reserve_ref if use_reserve else keys[frontline_keys[index % len(frontline_keys)]]
                    order = "reserve" if use_reserve else "hold"
                    battlefield["assignments"][formation_ref] = {
                        "formation_ref": formation_ref,
                        "side_ref": side_ref,
                        "sector_ref": sector_ref,
                        "status": "holding",
                        "order": order,
                        "pending_order": None,
                        "order_eta_at": None,
                        "pace": None,
                        "target_sector_ref": None,
                        "path_sector_refs": [],
                        "path_index": None,
                        "leg_eta_at": None,
                        "transit_from_sector_ref": None,
                        "transit_to_sector_ref": None,
                        "assigned_at": str(now),
                        "updated_at": str(now),
                    }
                    sectors[sector_ref].setdefault("formation_refs", []).append(formation_ref)
            for sector in sectors.values():
                if isinstance(sector, dict) and isinstance(sector.get("formation_refs"), list):
                    sector["formation_refs"] = sorted(set(str(ref) for ref in sector["formation_refs"]))
            initialize_battle_command_plan(self, operation, battlefield, at=str(now))
            battlefields[battlefield_ref] = battlefield
            affected_ref = battlefield_ref
        else:
            battlefield = battlefields.get(battlefield_ref)
            if not isinstance(battlefield, dict):
                raise ValueError("unknown operational battlefield")
            if battlefield.get("status") != "active" and action != "close":
                raise ValueError("operational battlefield is not active")
            assignments = battlefield.get("assignments")
            sectors = battlefield.get("sectors")
            if not isinstance(assignments, dict) or not isinstance(sectors, dict):
                raise ValueError("operational battlefield is invalid")
            if action == "assign":
                formation_ref = str(payload.get("formation_ref", ""))
                side_ref = str(payload.get("side_ref", ""))
                sector_ref = str(payload.get("sector_ref", ""))
                order = str(payload.get("order", "hold"))
                if formation_ref not in operation.get("formation_refs", []):
                    raise ValueError("formation is not part of the saved operation")
                if side_ref not in battlefield.get("side_refs", []) or sector_ref not in sectors or order not in _VALID_ORDERS:
                    raise ValueError("battlefield assignment is invalid")
                for other_ref, other in battlefields.items():
                    if other_ref != battlefield_ref and isinstance(other, Mapping) and other.get("status") == "active" and formation_ref in (other.get("assignments") or {}):
                        raise ValueError("formation is already committed to another active battlefield in this operation")
                _formation_path, formation = self._load_formation(formation_ref)
                if formation.get("location_ref") != operation.get("location_ref"):
                    raise ValueError("battlefield assignment requires physical presence at the operation location")
                owner_key = self._battlefield_formation_owner_key(formation)
                derived_side = self._battlefield_formation_side_hint(formation)
                if side_ref != derived_side:
                    raise ValueError("formation cannot be assigned to an opposing operational side")
                owner_sides = battlefield.setdefault("owner_side_refs", {})
                bound = owner_sides.get(owner_key)
                if bound is not None and bound != side_ref:
                    raise ValueError("one formation owner cannot be assigned to opposing sides in the same battlefield")
                owner_sides[owner_key] = side_ref
                existing = assignments.get(formation_ref)
                if isinstance(existing, Mapping):
                    # The opening deployment is a deterministic bootstrap. The
                    # player may rearrange a controlled formation freely only
                    # before any battlefield time has settled; afterward sector
                    # changes require timed redeployment.
                    if battlefield.get("last_settled_at") != battlefield.get("opened_at") or existing.get("status") == "redeploying":
                        raise ValueError("an already deployed formation must use timed redeployment")
                    self._battlefield_remove_formation(battlefield, formation_ref)
                assignments[formation_ref] = {
                    "formation_ref": formation_ref,
                    "side_ref": side_ref,
                    "sector_ref": sector_ref,
                    "status": "holding",
                    "order": order,
                    "pending_order": None,
                    "order_eta_at": None,
                    "pace": None,
                    "target_sector_ref": None,
                    "path_sector_refs": [],
                    "path_index": None,
                    "leg_eta_at": None,
                    "transit_from_sector_ref": None,
                    "transit_to_sector_ref": None,
                    "assigned_at": str(now),
                    "updated_at": str(now),
                }
                sectors[sector_ref].setdefault("formation_refs", []).append(formation_ref)
                sectors[sector_ref]["formation_refs"] = sorted(set(sectors[sector_ref]["formation_refs"]))
                affected_ref = formation_ref
            elif action == "redeploy":
                formation_ref = str(payload.get("formation_ref", ""))
                target_sector_ref = str(payload.get("target_sector_ref", ""))
                pace = str(payload.get("pace", "standard"))
                order = str(payload.get("order", "hold"))
                assignment = assignments.get(formation_ref)
                if not isinstance(assignment, dict) or assignment.get("status") == "redeploying" or target_sector_ref not in sectors or pace not in _VALID_PACES or order not in _VALID_ORDERS:
                    raise ValueError("battlefield redeployment is invalid")
                source_sector_ref = assignment.get("sector_ref")
                if not isinstance(source_sector_ref, str) or source_sector_ref == target_sector_ref:
                    raise ValueError("battlefield redeployment requires a different target sector")
                _formation_path, formation = self._load_formation(formation_ref)
                path_refs, _distance = self._battlefield_shortest_path(battlefield, source_sector_ref, target_sector_ref)
                self._battlefield_remove_formation(battlefield, formation_ref)
                assignment.update({"path_sector_refs": path_refs, "target_sector_ref": target_sector_ref, "pace": pace, "order": order})
                self._battlefield_start_leg(battlefield, assignment, formation, at=now, next_index=1)
                affected_ref = formation_ref
            elif action == "set_order":
                formation_ref = str(payload.get("formation_ref", ""))
                order = str(payload.get("order", ""))
                assignment = assignments.get(formation_ref)
                if not isinstance(assignment, dict) or order not in _VALID_ORDERS or assignment.get("status") == "redeploying":
                    raise ValueError("battlefield order is invalid")
                sector_ref = assignment.get("sector_ref")
                side_ref = assignment.get("side_ref")
                if not isinstance(sector_ref, str) or not isinstance(side_ref, str):
                    raise ValueError("battlefield order lacks a physical command route")
                delay = self._battlefield_report_latency(battlefield, sector_ref, side_ref)
                if delay <= 0:
                    assignment["order"] = order
                    assignment["pending_order"] = None
                    assignment["order_eta_at"] = None
                else:
                    assignment["pending_order"] = order
                    assignment["order_eta_at"] = str(now.add_seconds(delay))
                assignment["updated_at"] = str(now)
                affected_ref = formation_ref
            elif action == "record_terminal_evidence":
                kind = str(payload.get("termination_kind", ""))
                evidence_ref = str(payload.get("evidence_ref", "")).strip()
                if not evidence_ref:
                    raise ValueError("terminal evidence requires evidence_ref")
                row: Dict[str, Any] = {"kind": kind, "evidence_ref": evidence_ref, "recorded_at": str(now)}
                sides = [str(x) for x in battlefield.get("side_refs", []) if isinstance(x, str)]
                if kind == "surrender":
                    winner = str(payload.get("winner_side_ref", ""))
                    if winner not in sides:
                        raise ValueError("surrender evidence requires lawful winner_side_ref")
                    row["side_ref"] = next(side for side in sides if side != winner)
                    row["winner_side_ref"] = winner
                elif kind == "objective_complete":
                    winner = str(payload.get("winner_side_ref", ""))
                    if winner not in sides:
                        raise ValueError("objective evidence requires lawful winner_side_ref")
                    row["winner_side_ref"] = winner
                elif kind in {"mutual_disengagement", "non_renewal"}:
                    accepted = sorted({str(x) for x in payload.get("accepted_side_refs", []) if isinstance(x, str)})
                    if accepted != sorted(sides):
                        raise ValueError("two-sided terminal evidence requires both battlefield sides")
                    row["accepted_side_refs"] = accepted
                else:
                    raise ValueError("unsupported terminal evidence kind")
                rows = battlefield.setdefault("termination_evidence", [])
                if not isinstance(rows, list):
                    raise ValueError("battlefield termination evidence is invalid")
                rows.append(row)
                keep = max(1, int((self._battlefield_mechanics().get("battle_terminal") or {}).get("termination_evidence_tail", 8) or 8))
                del rows[:-keep]
                affected_ref = evidence_ref
                self._battlefield_conclusion(operation_ref, operation, battlefield, at=now)
            elif action == "close":
                if any(isinstance(value, Mapping) and value.get("status") == "redeploying" for value in assignments.values()):
                    raise ValueError("cannot close a battlefield while a formation is still redeploying")
                battlefield["status"] = "closed"
                battlefield["closed_at"] = str(now)
                battlefield["updated_at"] = str(now)
                affected_ref = battlefield_ref
        self.put(path, operation)
        if action == "open":
            self._battlefield_set_operation_route(operation_ref, active=True)
        elif action == "close":
            still_active = any(
                isinstance(other, Mapping) and other.get("status") == "active"
                for other in battlefields.values()
            )
            self._battlefield_set_operation_route(operation_ref, active=still_active)
        return {"action": action, "operation_ref": operation_ref, "battlefield_ref": battlefield_ref, "affected_ref": affected_ref, "world_time": str(now)}
