from __future__ import annotations

import copy
import heapq
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from sword_runtime.sim.calendar import CampaignTime


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


class OperationalBattlefieldMixin:
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

    def _battlefield_operation(self, operation_ref: str) -> tuple[str, Dict[str, Any]]:
        idx = self.read("state/operations/index.json")
        path = idx.get("operations", {}).get(operation_ref) if isinstance(idx, Mapping) else None
        if not isinstance(path, str) or not path:
            raise ValueError("unknown battlefield operation")
        operation = copy.deepcopy(self.read(path))
        if not isinstance(operation, dict) or operation.get("schema") != "sword-operation":
            raise ValueError("battlefield operation is invalid")
        return path, operation

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

    def _battlefield_effective_power(self, formation_ref: str, order: str) -> int:
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
        return max(1, personnel * quality_milli * order_power // 1_000_000)

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
            powers[side] += self._battlefield_effective_power(formation_ref, order)
            order_row = orders.get(order)
            if isinstance(order_row, Mapping):
                pressure_factors[side] = max(pressure_factors[side], int(order_row.get("pressure_milli", 1000)))
        rates: Dict[str, int] = {}
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
            parent=str(loc.get("contained_by_fortification_site_ref") or "")
            if parent and parent in static: candidate_sites.append(parent)
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

    @staticmethod
    def _battlefield_report_id(battlefield_ref: str, sector_ref: str, side_ref: str, level: str, at: CampaignTime) -> str:
        stamp = str(at).replace(":", "").replace("+", "p")
        safe_sector = sector_ref.replace(".", "_")
        safe_side = side_ref.replace(".", "_")
        return f"report_{battlefield_ref}_{safe_sector}_{safe_side}_{level}_{stamp}"

    def _battlefield_queue_report(self, battlefield: Dict[str, Any], *, sector_ref: str, side_ref: str, level: str, pressure_milli: int, at: CampaignTime, summary: str) -> Dict[str, Any]:
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
        }
        reports.append(report)
        return report

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
        assignment.update({
            "status": "redeploying",
            "sector_ref": None,
            "path_index": next_index,
            "transit_from_sector_ref": source,
            "transit_to_sector_ref": target,
            "leg_eta_at": str(at.add_seconds(seconds)),
            "updated_at": str(at),
        })

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

    def _battlefield_next_boundary_time(self, current: CampaignTime, target: CampaignTime) -> tuple[Optional[CampaignTime], Optional[Dict[str, Any]]]:
        if target <= current:
            return None, None
        try:
            idx = self.read("state/operations/index.json")
        except FileNotFoundError:
            return None, None
        operations = idx.get("operations") if isinstance(idx, Mapping) else None
        if not isinstance(operations, Mapping):
            return None, None
        critical, collapse, _reset = self._battlefield_pressure_thresholds()
        candidates: list[tuple[CampaignTime, Dict[str, Any]]] = []
        for operation_ref, path in sorted(operations.items()):
            if not isinstance(operation_ref, str) or not isinstance(path, str):
                continue
            operation = self.read(path)
            if not isinstance(operation, Mapping) or operation.get("status") not in {"active", "engaged"}:
                continue
            for battlefield_ref, battlefield in sorted((operation.get("battlefields") or {}).items()):
                if not isinstance(battlefield_ref, str) or not isinstance(battlefield, Mapping) or battlefield.get("status") != "active":
                    continue
                for formation_ref, assignment in sorted((battlefield.get("assignments") or {}).items()):
                    if not isinstance(formation_ref, str) or not isinstance(assignment, Mapping):
                        continue
                    if assignment.get("status") == "redeploying":
                        eta_text = assignment.get("leg_eta_at")
                        if isinstance(eta_text, str):
                            eta = CampaignTime.parse(eta_text)
                            if current < eta <= target:
                                candidates.append((eta, {"kind": "redeployment_leg", "operation_ref": operation_ref, "battlefield_ref": battlefield_ref, "formation_ref": formation_ref}))
                    order_eta_text = assignment.get("order_eta_at")
                    if isinstance(order_eta_text, str) and assignment.get("pending_order") in _VALID_ORDERS:
                        order_eta = CampaignTime.parse(order_eta_text)
                        if current < order_eta <= target:
                            candidates.append((order_eta, {"kind": "order_delivery", "operation_ref": operation_ref, "battlefield_ref": battlefield_ref, "formation_ref": formation_ref}))
                for report in battlefield.get("reports", []):
                    if not isinstance(report, Mapping) or report.get("status") != "queued":
                        continue
                    due_text = report.get("deliver_at")
                    if isinstance(due_text, str):
                        due = CampaignTime.parse(due_text)
                        if current < due <= target:
                            candidates.append((due, {"kind": "report_delivery", "operation_ref": operation_ref, "battlefield_ref": battlefield_ref, "report_id": report.get("report_id")}))
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
                                candidates.append((due, {"kind": "pressure_threshold", "operation_ref": operation_ref, "battlefield_ref": battlefield_ref, "sector_ref": sector_ref, "side_ref": side_ref, "level": level}))
        if not candidates:
            return None, None
        candidates.sort(key=lambda row: (str(row[0]), str(row[1].get("operation_ref", "")), str(row[1].get("battlefield_ref", "")), str(row[1].get("kind", ""))))
        return candidates[0]

    def _battlefield_settle_span(self, start: CampaignTime, end: CampaignTime) -> Dict[str, Any]:
        elapsed = _seconds_between(start, end)
        if elapsed < 0:
            raise ValueError("battlefield time cannot move backward")
        idx = self.read("state/operations/index.json")
        operations = idx.get("operations") if isinstance(idx, Mapping) else None
        if not isinstance(operations, Mapping):
            return {"changed": False, "reviews": [], "delivered_reports": [], "player_interrupt": False}
        critical, collapse, reset = self._battlefield_pressure_thresholds()
        changed = False
        reviews: list[Dict[str, Any]] = []
        delivered_to_player: list[Dict[str, Any]] = []
        for operation_ref, path in sorted(operations.items()):
            if not isinstance(operation_ref, str) or not isinstance(path, str):
                continue
            operation0 = self.read(path)
            if not isinstance(operation0, Mapping) or operation0.get("status") not in {"active", "engaged"}:
                continue
            operation = copy.deepcopy(operation0)
            operation_changes: list[Dict[str, Any]] = []
            battlefields = operation.get("battlefields")
            if not isinstance(battlefields, dict):
                continue
            for battlefield_ref, battlefield in sorted(battlefields.items()):
                if not isinstance(battlefield_ref, str) or not isinstance(battlefield, dict) or battlefield.get("status") != "active":
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
                        delivered_to_player.append({"operation_ref": operation_ref, "battlefield_ref": battlefield_ref, **dict(report)})
                    changed = True
                battlefield["last_settled_at"] = str(end)
                battlefield["updated_at"] = str(end)
            if operation_changes:
                operation.setdefault("battlefield_history", []).append({"at": str(end), "changes": operation_changes})
                self.put(path, operation)
                reviews.append({"operation_ref": operation_ref, "changes": operation_changes})
        return {"changed": changed, "reviews": reviews, "delivered_reports": delivered_to_player, "player_interrupt": bool(delivered_to_player)}

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
        return {"changed": changed, "reviews": all_reviews, "delivered_reports": delivered, "player_interrupt": bool(delivered), "reached_time": str(cursor)}

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

    def _battlefield_apply_battle_result(self, *, operation_ref: str, battlefield_ref: str, sector_ref: str, attacker_refs: Sequence[str], defender_refs: Sequence[str], winner: str, event_id: str, at: CampaignTime, hero_object_pressure: Optional[Mapping[str, Any]] = None, local_breach_summary: Optional[Mapping[str, Any]] = None) -> list[dict[str, Any]]:
        path, operation, battlefield = self._battlefield_validate_contact(
            operation_ref=operation_ref,
            battlefield_ref=battlefield_ref,
            sector_ref=sector_ref,
            attacker_refs=attacker_refs,
            defender_refs=defender_refs,
        )
        assignments = battlefield["assignments"]
        attacker_side = next(iter({assignments[ref]["side_ref"] for ref in attacker_refs}))
        defender_side = next(iter({assignments[ref]["side_ref"] for ref in defender_refs}))
        winner_side = attacker_side if winner == "attacker" else defender_side
        loser_side = defender_side if winner == "attacker" else attacker_side
        sector = battlefield["sectors"][sector_ref]
        pressure = sector.setdefault("pressure_milli", {})
        pressure[winner_side] = max(0, int(pressure.get(winner_side, 0)) - 120)
        pressure[loser_side] = min(1000, int(pressure.get(loser_side, 0)) + 180)
        consequences: list[dict[str, Any]] = []
        sector["last_combat"] = {"event_id": event_id, "winner_side_ref": winner_side, "loser_side_ref": loser_side, "at": str(at)}
        if isinstance(local_breach_summary, Mapping):
            sector["last_combat"]["local_breach_summary"] = copy.deepcopy(dict(local_breach_summary))

        # Named heroes may disrupt an exact operational command/signals owner, but
        # pressure never creates a standard, HQ, relay, or installation that is not
        # already represented by this battlefield/sector. Disruption is keyed by
        # the side suffering it because both coalitions occupy the same sector.
        pressure_row = hero_object_pressure if isinstance(hero_object_pressure, Mapping) else {}
        officer = max(0.0, float(pressure_row.get("officer_pressure", 0.0) or 0.0))
        cohesion = max(0.0, float(pressure_row.get("cohesion_shock_pressure", 0.0) or 0.0))
        artillery = max(0.0, float(pressure_row.get("artillery_pressure", 0.0) or 0.0))
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
        operation.setdefault("battlefield_history", []).append({"at": str(at), "changes": changes})
        self.put(path, operation)
        return consequences

    def _battlefield_control(self, command: Any, payload: Mapping[str, Any]) -> Dict[str, Any]:
        action = str(payload.get("action", ""))
        if action not in {"open", "assign", "redeploy", "set_order", "close"}:
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
            elif action == "close":
                if any(isinstance(value, Mapping) and value.get("status") == "redeploying" for value in assignments.values()):
                    raise ValueError("cannot close a battlefield while a formation is still redeploying")
                battlefield["status"] = "closed"
                battlefield["closed_at"] = str(now)
                battlefield["updated_at"] = str(now)
                affected_ref = battlefield_ref
        operation.setdefault("battlefield_history", []).append({"at": str(now), "changes": [{"kind": f"battlefield_{action}", "battlefield_ref": battlefield_ref, "affected_ref": affected_ref}]})
        self.put(path, operation)
        return {"action": action, "operation_ref": operation_ref, "battlefield_ref": battlefield_ref, "affected_ref": affected_ref, "world_time": str(now)}
