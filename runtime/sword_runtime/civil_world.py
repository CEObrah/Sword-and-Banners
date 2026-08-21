"""Causal civil, political, market, and occupation systems for hosted Sword play.

This mixin does not introduce new campaign authorities. It connects existing exact
state, population, private-economy, market, institution, House, faction, territory,
and mercenary owners so autonomous civil activity has material inputs and outputs.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.cohort_personnel import (
    add_recruits,
    ensure_cohort_ledger,
    record_recruitment_cohort,
    take_reserve_slices,
    validate_cohort_ledger,
)
from sword_runtime.engine import _clamp, _fixed
from sword_runtime.history_store import write_history_index
from sword_runtime.infrastructure_projects import INFRASTRUCTURE_PATH, apply_infrastructure_work, calculate_project_schedule, infrastructure_work_spec
from sword_runtime.land_development import (
    LAND_RULES_PATH, LAND_STATE_PATH, apply_site_land_reservation, productive_land_area_km2,
    productive_labor_access_factor, release_site_land_reservation, reserve_site_land,
)
from sword_runtime.settlement_development import complete_settlement_foundation, settle_development_project, settle_state_settlement_development
from sword_runtime.geography import demographic_anchor, enclosing_fortification_site, nearest_reachable_destination as geography_nearest_destination, shortest_path as geography_shortest_path, route_exists
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.stat_access import merged_skill_map


_CIVIL_RULES = "game/data/mechanics/civil-economy.json"
_FACTION_PROFILES = "game/data/politics/faction-profiles.json"
_REGIONAL_MERCENARY_INDEX = "state/merc/regional.json"
_REGIONAL_MERCENARY_PROFILES = "game/data/mil/regional-mercenary-profiles.json"
_MERCENARY_REVIEW_SECONDS = 90 * 86400

def sync_faction_routes(planner: Any, runtime: dict[str, Any]) -> None:
    """Apply domain-sensitive faction clocks without editing baseline campaign state.

    Routine reviews use the cadence registered by each faction profile.  Newly
    delivered exact information can shorten the next review to the profile's
    urgent cadence.  Existing earlier due work is never postponed.
    """
    raw = planner.read(_FACTION_PROFILES)
    profiles = raw.get("profiles", {}) if isinstance(raw, Mapping) else {}
    route_profiles = dict(profiles) if isinstance(profiles, Mapping) else {}
    # Dynamic coalition owners are discovered through the exact owner index, not
    # by scanning directories. They use their saved cadence and the same faction
    # review machinery without requiring runtime edits to static game data.
    owner_index = planner.read("state/index/owner-index.json")
    for ref, path in sorted((owner_index.get("owners", {}) or {}).items()):
        if not isinstance(ref, str) or not isinstance(path, str) or not path.startswith("state/factions/") or ref.startswith("faction_occupation_revolt_") or ref in route_profiles:
            continue
        doc = planner.read_optional(path)
        if not isinstance(doc, Mapping) or str(doc.get("status", "active")) == "dissolved":
            continue
        route_profiles[ref] = {
            "review_seconds": max(6 * 3600, int(doc.get("review_seconds", 30 * 86400))),
            "urgent_review_seconds": max(3600, int(doc.get("urgent_review_seconds", 24 * 3600))),
        }
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    current_text = runtime.get("world_time")
    if not isinstance(profiles, Mapping) or not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(current_text, str):
        raise ValueError("faction causal routing inputs are invalid")
    current = CampaignTime.parse(current_text)
    _sync_rebel_routes(planner, runtime)
    by_host = {str(row.get("target_host")): row for row in events if isinstance(row, dict) and isinstance(row.get("target_host"), str)}

    # Reconciliation must be able to *repair* a missing static faction route, not
    # merely retime hosts that already happen to exist.  Profiles plus the exact
    # owner index are the bounded authority for which standing factions require
    # a clock.  Dynamic revolt factions continue to use _sync_rebel_routes.
    routed_static = {
        str(host.get("owner_ref"))
        for host in hosts.values()
        if isinstance(host, Mapping) and host.get("kind") == "faction" and host.get("dynamic_revolt_route") is not True
    }
    for ref, profile in sorted(route_profiles.items()):
        if not isinstance(ref, str) or not isinstance(profile, Mapping) or ref in routed_static:
            continue
        try:
            doc = planner.read(planner.owner_path(ref))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        normal = max(6 * 3600, int(profile.get("review_seconds", 30 * 86400)))
        urgent = max(3600, min(normal, int(profile.get("urgent_review_seconds", 24 * 3600))))
        pending = doc.get("pending_information_refs", []) if isinstance(doc, Mapping) else []
        interval = urgent if isinstance(pending, list) and pending else normal
        host_id = f"host_{ref}"
        event_id = f"event_host_{ref}_review"
        due = current.add_seconds(interval)
        hosts[host_id] = {
            "kind": "faction",
            "owner_ref": ref,
            "quiet_run_count": 0,
            "recurrence_seconds": interval,
            "resolved_through": current_text,
            "next_due": str(due),
            "safe_through": str(due.add_seconds(-1)),
        }
        event = {
            "event_id": event_id,
            "kind": "faction_review",
            "priority": 100,
            "target_host": host_id,
            "due_at": str(due),
        }
        events.append(event)
        by_host[host_id] = event

    for host_id, host in hosts.items():
        if not isinstance(host, dict) or host.get("kind") != "faction":
            continue
        ref = str(host.get("owner_ref", ""))
        if host.get("dynamic_revolt_route") is True:
            continue
        profile = route_profiles.get(ref, {})
        if not isinstance(profile, Mapping):
            continue
        normal = max(6 * 3600, int(profile.get("review_seconds", 30 * 86400)))
        urgent = max(3600, min(normal, int(profile.get("urgent_review_seconds", 24 * 3600))))
        try:
            doc = planner.read(planner.owner_path(ref))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        pending = doc.get("pending_information_refs", []) if isinstance(doc, Mapping) else []
        interval = urgent if isinstance(pending, list) and pending else normal
        host["recurrence_seconds"] = interval
        next_due_text = host.get("next_due")
        if not isinstance(next_due_text, str):
            continue
        next_due = CampaignTime.parse(next_due_text)
        desired = current.add_seconds(interval)
        if next_due > desired:
            host["next_due"] = str(desired)
            host["safe_through"] = str(desired.add_seconds(-1))
            event = by_host.get(str(host_id))
            if isinstance(event, dict):
                event["due_at"] = str(desired)

def sync_polity_routes(planner: Any, runtime: dict[str, Any]) -> None:
    """Register bounded monthly causal hosts for House-founded sovereign polities.

    Polity routing is discovered from already-routed House owners, never from a
    directory scan.  This gives territorial authorities their own chronology so
    taxation/governance is not accidentally tied to the 120-day House cadence.
    """
    hosts = runtime.get("hosts"); events = runtime.get("events"); now_text = runtime.get("world_time")
    if not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(now_text, str):
        raise ValueError("polity causal routing inputs are invalid")
    now = CampaignTime.parse(now_text); recurrence = 30 * 86400
    by_host = {str(row.get("target_host")): row for row in events if isinstance(row, dict) and isinstance(row.get("target_host"), str)}
    active: set[str] = set()
    active_institution_hosts: set[str] = set()
    routed_polity_refs: set[str] = set()
    for house_host in list(hosts.values()):
        if not isinstance(house_host, Mapping) or house_host.get("kind") != "house":
            continue
        house_ref = str(house_host.get("owner_ref", ""))
        if not house_ref:
            continue
        try:
            house = planner.read(planner.owner_path(house_ref))
        except (KeyError, ValueError, FileNotFoundError):
            continue
        polity_ref = str(house.get("sovereignty_ref", "")) if isinstance(house, Mapping) else ""
        if polity_ref:
            routed_polity_refs.add(polity_ref)
    polity_index = planner.read_optional("state/politics/polity-index.json")
    if isinstance(polity_index, Mapping):
        for polity_ref in polity_index.get("active_polity_refs", []):
            if isinstance(polity_ref, str) and polity_ref:
                routed_polity_refs.add(polity_ref)
    for polity_ref in sorted(routed_polity_refs):
        try:
            polity = planner.read(planner.owner_path(polity_ref))
        except (KeyError, ValueError, FileNotFoundError):
            continue
        if str(polity.get("status", "")) == "dissolved":
            continue
        active.add(polity_ref)
        suffix = polity_ref.removeprefix("polity_")
        host_id = f"host_polity_{suffix}"; event_id = f"event_polity_{suffix}_review"
        host = hosts.get(host_id)
        if not isinstance(host, dict):
            due = now.add_seconds(recurrence)
            host = {"host_id": host_id, "kind": "polity", "owner_ref": polity_ref, "event_id": event_id, "recurrence_seconds": recurrence, "next_due": str(due), "resolved_through": now_text, "safe_through": str(due.add_seconds(-1))}
            hosts[host_id] = host
            events.append({"event_id": event_id, "kind": "polity_review", "priority": 88, "target_host": host_id, "due_at": str(due)})
        else:
            host["recurrence_seconds"] = recurrence
            host["owner_ref"] = polity_ref
            if host.get("next_due") is None:
                due = now.add_seconds(recurrence); host["next_due"] = str(due); host["safe_through"] = str(due.add_seconds(-1))
                event = by_host.get(host_id)
                if isinstance(event, dict): event["due_at"] = str(due); event.pop("suspended", None)

        institution_refs = polity.get("institution_refs", {}) if isinstance(polity.get("institution_refs"), Mapping) else {}
        for institution_ref in sorted(str(x) for x in institution_refs.values() if isinstance(x, str)):
            inst_suffix = institution_ref.removeprefix("inst_")
            inst_host_id = f"host_inst_{inst_suffix}"
            inst_event_id = f"event_{inst_host_id}_review"
            active_institution_hosts.add(inst_host_id)
            inst_host = hosts.get(inst_host_id)
            if not isinstance(inst_host, dict):
                due = now.add_seconds(recurrence)
                hosts[inst_host_id] = {
                    "host_id": inst_host_id,
                    "kind": "institution",
                    "owner_ref": institution_ref,
                    "event_id": inst_event_id,
                    "recurrence_seconds": recurrence,
                    "next_due": str(due),
                    "resolved_through": now_text,
                    "safe_through": str(due.add_seconds(-1)),
                    "dynamic_polity_institution_route": True,
                }
                events.append({"event_id": inst_event_id, "kind": "institution_review", "priority": 87, "target_host": inst_host_id, "due_at": str(due)})
            else:
                inst_host["owner_ref"] = institution_ref
                inst_host["recurrence_seconds"] = recurrence
                inst_host["dynamic_polity_institution_route"] = True
                if inst_host.get("next_due") is None:
                    due = now.add_seconds(recurrence)
                    inst_host["next_due"] = str(due)
                    inst_host["safe_through"] = str(due.add_seconds(-1))
                    event = by_host.get(inst_host_id)
                    if isinstance(event, dict):
                        event["due_at"] = str(due)
                        event.pop("suspended", None)
    # Remove inactive polity scheduler routes after dissolution; durable polity/history owners remain.
    for host_id, host in list(hosts.items()):
        if not isinstance(host, Mapping) or host.get("kind") != "polity":
            continue
        if str(host.get("owner_ref", "")) in active:
            continue
        hosts.pop(host_id, None)
        events[:] = [row for row in events if not (isinstance(row, Mapping) and row.get("target_host") == host_id)]
    for host_id, host in list(hosts.items()):
        if not isinstance(host, Mapping) or host.get("dynamic_polity_institution_route") is not True:
            continue
        if host_id in active_institution_hosts:
            continue
        hosts.pop(host_id, None)
        events[:] = [row for row in events if not (isinstance(row, Mapping) and row.get("target_host") == host_id)]


def _sync_rebel_routes(planner: Any, runtime: dict[str, Any]) -> None:
    """Route active materialized occupation revolts onto bounded weekly faction clocks."""
    hosts = runtime.get("hosts"); events = runtime.get("events"); now_text = runtime.get("world_time")
    if not isinstance(hosts, dict) or not isinstance(events, list) or not isinstance(now_text, str):
        raise ValueError("rebel causal routing inputs are invalid")
    territory = planner.read("state/territory/control.json")
    active: set[str] = set()
    now = CampaignTime.parse(now_text); recurrence = 7 * 86400
    for site in territory.get("sites", {}).values() if isinstance(territory, Mapping) else []:
        if not isinstance(site, Mapping): continue
        gov = site.get("governance") if isinstance(site.get("governance"), Mapping) else None
        revolt = gov.get("revolt") if isinstance(gov, Mapping) and isinstance(gov.get("revolt"), Mapping) else None
        if not revolt or revolt.get("active") is not True: continue
        faction_ref = str(revolt.get("faction_ref", ""))
        if not faction_ref: continue
        active.add(faction_ref); suffix = faction_ref.removeprefix("faction_")
        host_id = f"host_rebel_{suffix}"; event_id = f"event_rebel_{suffix}_review"
        if host_id not in hosts:
            due = now.add_seconds(recurrence)
            hosts[host_id] = {"host_id": host_id, "kind": "faction", "owner_ref": faction_ref, "event_id": event_id, "recurrence_seconds": recurrence, "next_due": str(due), "resolved_through": now_text, "safe_through": str(due.add_seconds(-1)), "dynamic_revolt_route": True}
            events.append({"event_id": event_id, "kind": "faction_review", "priority": 84, "target_host": host_id, "due_at": str(due)})
    for host_id, host in list(hosts.items()):
        if not isinstance(host, Mapping) or host.get("dynamic_revolt_route") is not True: continue
        if str(host.get("owner_ref", "")) in active: continue
        hosts.pop(host_id, None); events[:] = [row for row in events if not (isinstance(row, Mapping) and row.get("target_host") == host_id)]


class CivilWorldMixin:
    """Production-only causal bridges for economy, institutions, politics and rule."""

    def _civil_rules(self) -> Mapping[str, Any]:
        rules = self.read(_CIVIL_RULES)
        if not isinstance(rules, Mapping):
            raise ValueError("civil economy rules are invalid")
        return rules

    def _private_economy(self, state: str) -> tuple[str, dict[str, Any]]:
        path = f"state/economy/private/{state}.json"
        raw = self.read(path)
        if not isinstance(raw, Mapping):
            raise ValueError("private economy owner is invalid")
        eco = copy.deepcopy(dict(raw))
        self._ensure_local_economy_ledger(state, eco)
        return path, eco

    @staticmethod
    def _adjust_local_pool(regions: dict[str, Any], field: str, key: str | None, delta: int) -> None:
        if delta == 0 or not regions:
            return
        rows = [(ref, row) for ref, row in sorted(regions.items()) if isinstance(row, dict)]
        if not rows:
            return
        weights = [(ref, max(1, int(row.get("resident_population", 0)))) for ref, row in rows]
        if delta > 0:
            shares = CivilWorldMixin._weighted_integer_partition(delta, weights)
            for ref, row in rows:
                if key is None:
                    row[field] = max(0, int(row.get(field, 0))) + int(shares.get(ref, 0))
                else:
                    pool = row.setdefault(field, {})
                    pool[key] = max(0, int(pool.get(key, 0))) + int(shares.get(ref, 0))
            return
        # An aggregate deduction without an exact source locality is distributed
        # across the existing spatial stock proportionally. This preserves local
        # conservation without inventing an arbitrary single-site source.
        need = -delta
        holdings: list[tuple[str, int]] = []
        for ref, row in rows:
            if key is None:
                have = max(0, int(row.get(field, 0)))
            else:
                have = max(0, int(row.setdefault(field, {}).get(key, 0)))
            if have:
                holdings.append((ref, have))
        if sum(v for _ref, v in holdings) < need:
            raise ValueError("local private-economy partition cannot reconcile aggregate deduction")
        shares = CivilWorldMixin._weighted_integer_partition(need, holdings)
        remaining = need
        by_ref = dict(rows)
        for ref, have in holdings:
            take = min(have, int(shares.get(ref, 0)))
            row = by_ref[ref]
            if key is None:
                row[field] = have - take
            else:
                row.setdefault(field, {})[key] = have - take
            remaining -= take
        if remaining:
            for ref, _have in holdings:
                if remaining <= 0:
                    break
                row = by_ref[ref]
                current = max(0, int(row.get(field, 0))) if key is None else max(0, int(row.setdefault(field, {}).get(key, 0)))
                take = min(current, remaining)
                if key is None:
                    row[field] = current - take
                else:
                    row.setdefault(field, {})[key] = current - take
                remaining -= take
        if remaining:
            raise ValueError("local private-economy partition cannot reconcile aggregate deduction")

    def _ensure_local_economy_ledger(self, state: str, eco: dict[str, Any]) -> dict[str, Any]:
        """Partition one private-economy authority into conserved site-local production regions.

        The top-level private-economy document remains the sole writable economy owner.
        `local_regions` is a physical partition inside that owner, not a second economy.
        Aggregate mirrors are reconciled into the regional partition on read.
        """
        pop_path = f"state/population/{state}.json"
        pop = copy.deepcopy(self.read(pop_path))
        had_local = isinstance(pop.get("local_population"), Mapping) and isinstance(pop.get("local_population", {}).get("sites"), Mapping)
        _population_path, pop = self._ensure_local_population_ledger(state, pop)
        if not had_local:
            self.put(pop_path, pop)
        sites = pop.get("local_population", {}).get("sites", {})
        if not isinstance(sites, Mapping) or not sites:
            return eco
        local = eco.get("local_regions")
        if not isinstance(local, dict) or not isinstance(local.get("regions"), Mapping):
            weights = [(str(ref), max(1, int(row.get("civilian_population", 0)))) for ref, row in sorted(sites.items()) if isinstance(row, Mapping)]
            cash = self._weighted_integer_partition(max(0, int(eco.get("cash_silver", 0))), weights)
            commodity_parts = {
                str(key): self._weighted_integer_partition(max(0, int(value)), weights)
                for key, value in (eco.get("commodity_stock", {}) or {}).items()
            }
            finished_parts = {
                str(key): self._weighted_integer_partition(max(0, int(value)), weights)
                for key, value in (eco.get("finished_goods", {}) or {}).items()
            }
            regions: dict[str, Any] = {}
            for ref, _weight in weights:
                pop_row = sites.get(ref, {})
                regions[ref] = {
                    "location_ref": ref,
                    "resident_population": max(0, int(pop_row.get("civilian_population", 0))),
                    "cash_silver": int(cash.get(ref, 0)),
                    "commodity_stock": {key: int(parts.get(ref, 0)) for key, parts in commodity_parts.items()},
                    "finished_goods": {key: int(parts.get(ref, 0)) for key, parts in finished_parts.items()},
                    "production_runtime": {"completed_monthly_closes": 0, "last_close": None},
                }
            local = {
                "authority": True,
                "basis": "demographic-owner-only site-local physical production/cash partition nested inside the one native private-economy owner",
                "regions": regions,
            }
            eco["local_regions"] = local
        regions = local.get("regions", {})
        if not isinstance(regions, dict):
            raise ValueError("local private-economy regions are invalid")
        # Update resident weights from the authoritative local population partition.
        for ref, pop_row in sites.items():
            if not isinstance(pop_row, Mapping):
                continue
            row = regions.setdefault(str(ref), {"location_ref": str(ref), "cash_silver": 0, "commodity_stock": {}, "finished_goods": {}, "production_runtime": {}})
            row["resident_population"] = max(0, int(pop_row.get("civilian_population", 0)))
        # Reconcile aggregate mirrors into the exact regional partition.
        regional_cash = sum(max(0, int(row.get("cash_silver", 0))) for row in regions.values() if isinstance(row, Mapping))
        self._adjust_local_pool(regions, "cash_silver", None, int(eco.get("cash_silver", 0)) - regional_cash)
        commodity_keys = set(str(k) for k in (eco.get("commodity_stock", {}) or {}))
        for row in regions.values():
            if isinstance(row, Mapping) and isinstance(row.get("commodity_stock"), Mapping):
                commodity_keys.update(str(k) for k in row.get("commodity_stock", {}))
        for key in sorted(commodity_keys):
            regional = sum(max(0, int(row.get("commodity_stock", {}).get(key, 0))) for row in regions.values() if isinstance(row, Mapping))
            target = max(0, int((eco.get("commodity_stock", {}) or {}).get(key, regional)))
            self._adjust_local_pool(regions, "commodity_stock", key, target - regional)
        finished_keys = set(str(k) for k in (eco.get("finished_goods", {}) or {}))
        for row in regions.values():
            if isinstance(row, Mapping) and isinstance(row.get("finished_goods"), Mapping):
                finished_keys.update(str(k) for k in row.get("finished_goods", {}))
        for key in sorted(finished_keys):
            regional = sum(max(0, int(row.get("finished_goods", {}).get(key, 0))) for row in regions.values() if isinstance(row, Mapping))
            target = max(0, int((eco.get("finished_goods", {}) or {}).get(key, regional)))
            self._adjust_local_pool(regions, "finished_goods", key, target - regional)
        self._sync_local_economy_aggregate(eco)
        return eco

    def _sync_local_economy_aggregate(self, eco: dict[str, Any]) -> None:
        local = eco.get("local_regions")
        regions = local.get("regions", {}) if isinstance(local, Mapping) else {}
        if not isinstance(regions, Mapping) or not regions:
            return
        eco["cash_silver"] = sum(max(0, int(row.get("cash_silver", 0))) for row in regions.values() if isinstance(row, Mapping))
        commodities: dict[str, int] = {}
        finished: dict[str, int] = {}
        for row in regions.values():
            if not isinstance(row, Mapping):
                continue
            for key, value in (row.get("commodity_stock", {}) or {}).items():
                commodities[str(key)] = commodities.get(str(key), 0) + max(0, int(value))
            for key, value in (row.get("finished_goods", {}) or {}).items():
                finished[str(key)] = finished.get(str(key), 0) + max(0, int(value))
        eco["commodity_stock"] = commodities
        eco["finished_goods"] = finished

    def _write_private_economy(self, path: str, eco: dict[str, Any]) -> None:
        state = str(eco.get("state", ""))
        if state:
            self._ensure_local_economy_ledger(state, eco)
            self._sync_local_economy_aggregate(eco)
        self.put(path, eco)

    def _record_private_realized_sale(
        self,
        region: dict[str, Any],
        *,
        amount_silver: int,
        at: str,
        kind: str,
        resource: str | None = None,
        quantity: int = 0,
    ) -> None:
        """Record cash-paid private economic activity without minting cash.

        The caller must already have moved the payer's exact silver and any physical
        commodity/service consequence. This record is only the next fiscal close's
        realization evidence, so unsold production never becomes taxable merely by
        existing in stock.
        """
        amount = max(0, int(amount_silver))
        if amount <= 0:
            return
        runtime = region.setdefault("production_runtime", {})
        runtime["realized_sales_since_last_close_silver"] = max(0, int(runtime.get("realized_sales_since_last_close_silver", 0))) + amount
        history = runtime.setdefault("realized_sale_history", [])
        if isinstance(history, list):
            row = {"at": str(at), "kind": str(kind), "silver": amount}
            if resource:
                row["resource"] = str(resource)
            if quantity:
                row["quantity"] = max(0, int(quantity))
            history.append(row)
            runtime["realized_sale_history"] = history[-24:]

    def _regional_commodity_unit_price(self, region: Mapping[str, Any], resource: str, base_price: float) -> tuple[float, dict[str, float]]:
        """Return one shared scarcity-aware local commodity price.

        Only grain currently has a universal monthly consumption denominator. Other
        commodities keep their registered base price until a similarly conserved
        demand denominator exists; this avoids decorative scarcity guesses.
        """
        base = max(0.0, float(base_price))
        factor = 1.0
        reserve_months = 0.0
        shortfall_fraction = 0.0
        if str(resource) == "grain_kg":
            feedback = self._civil_rules().get("economy_feedback", {})
            runtime = region.get("production_runtime", {}) if isinstance(region.get("production_runtime"), Mapping) else {}
            food = runtime.get("last_food_close", {}) if isinstance(runtime.get("last_food_close"), Mapping) else {}
            due = max(0, int(food.get("grain_due_kg", 0)))
            shortfall = max(0, int(food.get("grain_shortfall_kg", food.get("grain_shortfall_kg_before_internal_transfer", 0))))
            stock = region.get("commodity_stock", {}) if isinstance(region.get("commodity_stock"), Mapping) else {}
            available = max(0, int(stock.get("grain_kg", 0)))
            if due > 0:
                reserve_months = available / due
                shortfall_fraction = min(1.0, shortfall / due)
                target = max(0.1, _fixed(feedback.get("grain_target_reserve_months", 3.0), 3.0))
                exponent = max(0.0, _fixed(feedback.get("grain_scarcity_exponent", 0.35), 0.35))
                floor = max(0.01, _fixed(feedback.get("minimum_commodity_price_factor", 0.70), 0.70))
                ceiling = max(floor, _fixed(feedback.get("maximum_commodity_price_factor", 2.50), 2.50))
                effective_cover = max(0.05, reserve_months)
                reserve_factor = (target / effective_cover) ** exponent
                shortage_pressure = 1.0 + shortfall_fraction * max(0.0, _fixed(feedback.get("food_shortfall_price_pressure_at_total_shortfall", 1.0), 1.0))
                factor = max(floor, min(ceiling, reserve_factor * shortage_pressure))
        return base * factor, {"base_price": base, "scarcity_factor": factor, "reserve_months": reserve_months, "shortfall_fraction": shortfall_fraction}

    def _local_economy_region(self, state: str, eco: dict[str, Any], location_ref: str, *, require_controller: str | None = None) -> tuple[str, dict[str, Any]]:
        self._ensure_local_economy_ledger(state, eco)
        try:
            _pp, _pop, site_ref = self._local_population_site_for_location(state, location_ref, controller_ref=require_controller)
        except ValueError:
            site_ref = location_ref
        regions = eco.get("local_regions", {}).get("regions", {})
        row = regions.get(site_ref) if isinstance(regions, Mapping) else None
        if not isinstance(row, dict):
            raise ValueError("location has no conserved local production region")
        return str(site_ref), row

    def _settle_private_production(self, state: str, occurrences: int, at: str) -> None:
        """Settle one conserved land/labor production close.

        Physical land owns productive capacity; population owns workers.  Neither
        source can create output alone.  Site identity and polity identity never
        alter the formula.  Finished goods remain workforce/capacity bounded and
        food shortfalls are balanced from actual same-state surplus stock.
        """
        if occurrences <= 0:
            return
        rules = self._civil_rules()
        land_rules = self.read(LAND_RULES_PATH)
        land = self.read(LAND_STATE_PATH)
        infrastructure = self.read(INFRASTRUCTURE_PATH)
        economy_rules = self.read("game/data/mechanics/economy.json")
        construction_rules = self.read("game/data/mechanics/construction-physics.json")
        pp = f"state/population/{state}.json"
        pop = copy.deepcopy(self.read(pp))
        _pp, pop = self._ensure_local_population_ledger(state, pop)
        sites = pop.get("local_population", {}).get("sites", {})
        path, eco = self._private_economy(state)
        regions = eco.get("local_regions", {}).get("regions", {})
        if not isinstance(sites, Mapping) or not isinstance(regions, Mapping):
            raise ValueError("local production requires conserved site population/economy partitions")

        labor = eco.setdefault("labor_allocation", {})
        projects = labor.setdefault("projects", {})
        if not isinstance(projects, dict):
            raise ValueError("private economy project labor allocation is invalid")
        now = CampaignTime.parse(at)
        active_allocations: dict[str, dict[str, Any]] = {}
        allocated_by_site: dict[str, int] = {}
        allocated_workers = 0
        for project_ref, raw in list(projects.items()):
            if not isinstance(raw, Mapping):
                continue
            releases_at = raw.get("releases_at")
            if isinstance(releases_at, str) and CampaignTime.parse(releases_at) <= now:
                continue
            row = copy.deepcopy(dict(raw))
            institution_ref = str(row.get("institution_ref", ""))
            location_ref = str(row.get("location_ref", ""))
            if not location_ref and institution_ref:
                inst = self.read_optional(self.owner_path(institution_ref))
                if isinstance(inst, Mapping):
                    location_ref = str(inst.get("location_ref", ""))
            site_ref = None
            if location_ref:
                try:
                    _pp, _pop, site_ref = self._local_population_site_for_location(state, location_ref)
                except ValueError:
                    site_ref = None
            if site_ref:
                row["location_ref"] = site_ref
                allocated_by_site[site_ref] = allocated_by_site.get(site_ref, 0) + max(0, int(row.get("workers", 0)))
            active_allocations[str(project_ref)] = row
            allocated_workers += max(0, int(row.get("workers", 0)))
        labor["projects"] = active_allocations
        labor["allocated_construction_workers"] = allocated_workers

        productive = land_rules.get("productive_land", {}) if isinstance(land_rules, Mapping) else {}
        ag_rule = productive.get("agriculture", {}) if isinstance(productive, Mapping) else {}
        pasture_rule = productive.get("pasture", {}) if isinstance(productive, Mapping) else {}
        wood_rule = productive.get("woodland", {}) if isinstance(productive, Mapping) else {}
        extraction_rule = productive.get("extraction", {}) if isinstance(productive, Mapping) else {}
        crop_mix = ag_rule.get("default_crop_mix", {}) if isinstance(ag_rule, Mapping) else {}
        workers_ag = max(0.01, _fixed(ag_rule.get("workers_per_km2_full_output", 36), 36))
        workers_pasture = max(0.01, _fixed(pasture_rule.get("workers_per_km2_full_output", 4), 4))
        workers_wood = max(0.01, _fixed(wood_rule.get("workers_per_km2_full_output", 8), 8))
        workers_extract = max(0.01, _fixed(extraction_rule.get("workers_per_km2_full_output", 20), 20))
        gross_staple = max(0.0, _fixed(ag_rule.get("gross_staple_kg_per_km2_year", 250000), 250000))
        usable_staple = gross_staple * max(0.0, 1.0 - _fixed(ag_rule.get("seed_reserve_fraction", 0.08), 0.08) - _fixed(ag_rule.get("normal_processing_storage_loss_fraction", 0.04), 0.04))
        staple_fraction = max(0.0, min(1.0, _fixed(crop_mix.get("staple", 0.951), 0.951)))
        fodder_fraction = max(0.0, min(1.0, _fixed(crop_mix.get("fodder", 0.02), 0.02)))
        fodder_yield = max(0.0, _fixed(ag_rule.get("harvested_fodder_kg_per_km2_year", 500000), 500000))
        residue_fraction = max(0.0, _fixed(ag_rule.get("usable_crop_residue_fraction_of_gross_staple", 0.02), 0.02))
        pasture_yield = max(0.0, _fixed(pasture_rule.get("grazing_fodder_kg_equivalent_per_km2_year", 100000), 100000))
        wood_output = max(0.0, _fixed(wood_rule.get("construction_material_units_per_km2_month", 40), 40))
        extract_output = max(0.0, _fixed(extraction_rule.get("construction_material_units_per_km2_month", 60), 60))
        food_rules = rules.get("labor", {})
        daily_ration = max(0.0, _fixed(food_rules.get("civilian_grain_consumption_kg_per_person_per_day", 0.68), 0.68))
        finished_rates = rules.get("monthly_finished_goods_per_craft_worker", {})
        market_prices = economy_rules.get("prices_silver", {}) if isinstance(economy_rules, Mapping) else {}
        material_value = max(0.0, _fixed((construction_rules.get("material_equivalent", {}) if isinstance(construction_rules, Mapping) else {}).get("base_procurement_silver_per_unit", 1.25), 1.25))
        infra_sites = infrastructure.get("sites", {}) if isinstance(infrastructure, Mapping) else {}

        totals = {"agricultural": 0, "craft_total": 0, "craft_available": 0, "civilian_population": 0, "grain_due": 0, "grain_consumed": 0, "grain_produced": 0, "fodder_produced": 0, "construction_material_units": 0, "gross_output_value_silver": 0, "taxable_output_value_silver": 0, "realized_sales_silver": 0}
        regional_closes: dict[str, Any] = {}
        shortages: list[tuple[str, int]] = []
        for site_ref in sorted(regions):
            region = regions.get(site_ref)
            pop_row = sites.get(site_ref)
            if not isinstance(region, dict) or not isinstance(pop_row, Mapping):
                continue
            runtime = region.setdefault("production_runtime", {})
            pending_realized_sales = max(0, int(runtime.pop("realized_sales_since_last_close_silver", 0)))
            civilian_strata = pop_row.get("civilian_strata", {}) if isinstance(pop_row.get("civilian_strata"), Mapping) else {}
            agricultural = max(0, int(civilian_strata.get("agricultural", 0)))
            craft_total = max(0, int(civilian_strata.get("craft_and_industry", 0)))
            reserved = min(craft_total, max(0, int(allocated_by_site.get(site_ref, 0))))
            craft = max(0, craft_total - reserved)
            civilian_population = sum(max(0, int(value)) for value in civilian_strata.values())

            agriculture_km2 = productive_land_area_km2(land, site_ref, "agriculture")
            pasture_km2 = productive_land_area_km2(land, site_ref, "pasture")
            woodland_km2 = productive_land_area_km2(land, site_ref, "woodland")
            extraction_km2 = productive_land_area_km2(land, site_ref, "extraction")
            required_rural_workers = agriculture_km2 * workers_ag + pasture_km2 * workers_pasture
            required_material_workers = woodland_km2 * workers_wood + extraction_km2 * workers_extract
            # A centralized-residence estate must physically move its rural and
            # resource workers through the resident enclosure and road network.
            # Ordinary sites receive factor 1.0. This is shared physical access,
            # not an owner-specific productivity multiplier.
            commuting_workers = agricultural + min(craft, int(math.ceil(required_material_workers)))
            access = productive_labor_access_factor(
                land, site_ref=site_ref, commuting_workers=commuting_workers, rules=land_rules
            )
            access_factor = max(0.0, min(1.0, float(access.get("factor", 1.0))))
            rural_labor_factor = min(1.0, (agricultural * access_factor) / required_rural_workers) if required_rural_workers > 0 else 0.0
            material_labor_factor = min(1.0, (craft * access_factor) / required_material_workers) if required_material_workers > 0 else 0.0

            months = float(occurrences)
            agriculture_factor = 1.0
            forage_factor = 1.0
            environment_basis: dict[str, Any] = {}
            if hasattr(self, "_environment_snapshot"):
                env_snapshot = self._environment_snapshot(site_ref)
                effects = env_snapshot.get("mechanical_effects", {}) if isinstance(env_snapshot, Mapping) else {}
                agriculture_milli = max(0, int(effects.get("agriculture_output_milli", 1000))) if isinstance(effects, Mapping) else 1000
                forage_milli = max(0, int(effects.get("forage_availability_milli", 1000))) if isinstance(effects, Mapping) else 1000
                agriculture_factor = agriculture_milli / 1000.0
                forage_factor = forage_milli / 1000.0
                environment_basis = {
                    "weather_block_ref": str(env_snapshot.get("weather_block_ref", "")),
                    "season": str(env_snapshot.get("season", "")),
                    "agriculture_output_milli": agriculture_milli,
                    "forage_availability_milli": forage_milli,
                }
            produced_grain = int(math.floor(agriculture_km2 * staple_fraction * usable_staple / 12.0 * rural_labor_factor * agriculture_factor * months))
            crop_fodder = (
                agriculture_km2 * fodder_fraction * fodder_yield / 12.0
                + agriculture_km2 * staple_fraction * gross_staple * residue_fraction / 12.0
            ) * agriculture_factor
            grazing_fodder = pasture_km2 * pasture_yield / 12.0 * forage_factor
            produced_fodder = int(math.floor((crop_fodder + grazing_fodder) * rural_labor_factor * months))
            produced_material = int(math.floor((woodland_km2 * wood_output + extraction_km2 * extract_output) * material_labor_factor * months))

            support_ref = site_ref
            land_site = land.get("sites", {}).get(site_ref, {}) if isinstance(land.get("sites"), Mapping) else {}
            labor_access = land_site.get("labor_access", {}) if isinstance(land_site, Mapping) and isinstance(land_site.get("labor_access"), Mapping) else {}
            resident_ref = labor_access.get("permanent_residence_site_ref")
            if isinstance(resident_ref, str) and resident_ref:
                support_ref = resident_ref
            support = infra_sites.get(support_ref, {}) if isinstance(infra_sites, Mapping) else {}
            physical_support = support.get("physical_support", {}) if isinstance(support, Mapping) else {}
            work_access = max(0, int(physical_support.get("ordinary_work_access_capacity_people", craft))) if isinstance(physical_support, Mapping) else craft
            productive_craft = min(craft, work_access)

            stock = region.setdefault("commodity_stock", {})
            finished = region.setdefault("finished_goods", {})
            stock["grain_kg"] = int(stock.get("grain_kg", 0)) + produced_grain
            stock["fodder_kg"] = int(stock.get("fodder_kg", 0)) + produced_fodder
            stock["construction_material_units"] = int(stock.get("construction_material_units", 0)) + produced_material
            goods_made: dict[str, int] = {}
            gross_output_value = produced_grain * _fixed(market_prices.get("grain_kg", 0.08), 0.08) + produced_fodder * _fixed(market_prices.get("fodder_kg", 0.10), 0.10) + produced_material * material_value
            for key, rate in finished_rates.items():
                produced = int(math.floor(productive_craft * _fixed(rate, 0.0) * months))
                if produced > 0:
                    finished[str(key)] = int(finished.get(str(key), 0)) + produced
                    goods_made[str(key)] = produced
                    gross_output_value += produced * _fixed(market_prices.get(str(key), 0.0), 0.0)

            grain_due = max(0, int(round(civilian_population * daily_ration * 30.0 * occurrences)))
            grain_consumed = min(grain_due, max(0, int(stock.get("grain_kg", 0))))
            stock["grain_kg"] = max(0, int(stock.get("grain_kg", 0)) - grain_consumed)
            shortfall = max(0, grain_due - grain_consumed)
            if shortfall:
                shortages.append((site_ref, shortfall))
            region["resident_population"] = civilian_population
            feedback_rules = rules.get("economy_feedback", {}) if isinstance(rules, Mapping) else {}
            household_fraction = max(0.0, min(1.0, _fixed(feedback_rules.get("taxable_household_consumption_fraction", 1.0), 1.0)))
            household_consumption_value = grain_consumed * _fixed(market_prices.get("grain_kg", 0.08), 0.08) * household_fraction
            taxable_realized_value = max(0, int(round(household_consumption_value + pending_realized_sales)))
            runtime["completed_monthly_closes"] = int(runtime.get("completed_monthly_closes", 0)) + occurrences
            runtime["last_close"] = at
            runtime["last_land_basis"] = {
                "agriculture_km2": round(agriculture_km2, 6), "pasture_km2": round(pasture_km2, 6),
                "woodland_km2": round(woodland_km2, 6), "extraction_km2": round(extraction_km2, 6),
                "rural_labor_factor": round(rural_labor_factor, 6), "material_labor_factor": round(material_labor_factor, 6),
                "environment": environment_basis,
            }
            runtime["last_labor_basis"] = {"agricultural": agricultural, "craft_total": craft_total, "construction_workers_reserved": reserved, "craft_available": craft, "productive_craft_workers": productive_craft, "productive_land_access": access}
            runtime["last_food_close"] = {"civilian_population": civilian_population, "grain_due_kg": grain_due, "grain_consumed_kg": grain_consumed, "grain_shortfall_kg_before_internal_transfer": shortfall, "produced_grain_kg": produced_grain}
            runtime["last_output"] = {"grain_kg": produced_grain, "fodder_kg": produced_fodder, "construction_material_units": produced_material, "finished_goods": copy.deepcopy(goods_made)}
            runtime["last_gross_output_value_silver"] = max(0, int(round(gross_output_value)))
            runtime["last_taxable_output_value_silver"] = taxable_realized_value
            runtime["last_realization_basis"] = {"household_consumption_value_silver": max(0, int(round(household_consumption_value))), "cash_paid_private_sales_silver": pending_realized_sales, "unsold_output_is_not_realized": True}
            private_owner_ref = self._private_site_owner(site_ref)
            owner_due = 0
            owner_paid = 0
            if private_owner_ref:
                estate_rules = economy_rules.get("house_estate_finance", {}) if isinstance(economy_rules, Mapping) else {}
                owner_share = max(0.0, min(1.0, _fixed(estate_rules.get("owner_share_fraction_of_realized_output_value", 0.20), 0.20)))
                owner_due = max(0, int(round(taxable_realized_value * owner_share)))
                owner_paid = min(owner_due, max(0, int(region.get("cash_silver", 0))))
                if owner_paid:
                    region["cash_silver"] = max(0, int(region.get("cash_silver", 0)) - owner_paid)
                    self._credit_house_cash(private_owner_ref, owner_paid)
                runtime["last_private_owner_close"] = {"owner_ref": private_owner_ref, "due_silver": owner_due, "paid_silver": owner_paid, "arrears_silver": max(0, owner_due - owner_paid)}
            else:
                runtime.pop("last_private_owner_close", None)
            regional_closes[site_ref] = {"grain_kg": produced_grain, "fodder_kg": produced_fodder, "construction_material_units": produced_material, "finished_goods": goods_made, "grain_consumed_kg": grain_consumed, "grain_shortfall_kg_before_internal_transfer": shortfall, "gross_output_value_silver": max(0, int(round(gross_output_value))), "taxable_output_value_silver": taxable_realized_value, "cash_paid_private_sales_silver": pending_realized_sales, "private_owner_ref": private_owner_ref, "owner_income_due_silver": owner_due, "owner_income_paid_silver": owner_paid}
            totals["agricultural"] += agricultural
            totals["craft_total"] += craft_total
            totals["craft_available"] += craft
            totals["civilian_population"] += civilian_population
            totals["grain_due"] += grain_due
            totals["grain_consumed"] += grain_consumed
            totals["grain_produced"] += produced_grain
            totals["fodder_produced"] += produced_fodder
            totals["construction_material_units"] += produced_material
            totals["gross_output_value_silver"] += max(0, int(round(gross_output_value)))
            totals["taxable_output_value_silver"] += taxable_realized_value
            totals["realized_sales_silver"] += pending_realized_sales

        # Internal state food circulation is aggregate but conserved.  It moves only
        # stock that really exists, prioritizing the shortest known route.  This
        # prevents a capital from needing farmland inside its own walls while still
        # making blockades and route disruption meaningful elsewhere in the market
        # and siege systems.
        transfers: list[dict[str, Any]] = []
        for target_ref, initial_shortfall in shortages:
            remaining = initial_shortfall
            target = regions.get(target_ref)
            if not isinstance(target, dict):
                continue
            donors: list[tuple[int, str]] = []
            for donor_ref, donor in regions.items():
                if donor_ref == target_ref or not isinstance(donor, Mapping):
                    continue
                available = max(0, int((donor.get("commodity_stock", {}) if isinstance(donor.get("commodity_stock"), Mapping) else {}).get("grain_kg", 0)))
                if available <= 0:
                    continue
                try:
                    hours = int(self._route_travel_hours(str(donor_ref), str(target_ref)))
                except Exception:
                    hours = 10**9
                donors.append((hours, str(donor_ref)))
            for hours, donor_ref in sorted(donors, key=lambda row: (row[0], row[1])):
                if remaining <= 0 or hours >= 10**9:
                    break
                donor = regions[donor_ref]
                donor_stock = donor.setdefault("commodity_stock", {})
                available = max(0, int(donor_stock.get("grain_kg", 0)))
                moved = min(remaining, available)
                if moved <= 0:
                    continue
                donor_stock["grain_kg"] = available - moved
                remaining -= moved
                totals["grain_consumed"] += moved
                transfers.append({"from": donor_ref, "to": target_ref, "grain_kg": moved, "route_hours": hours})
            target_runtime = target.setdefault("production_runtime", {})
            food_close = target_runtime.setdefault("last_food_close", {})
            food_close["internal_grain_received_kg"] = initial_shortfall - remaining
            food_close["grain_consumed_kg"] = int(food_close.get("grain_consumed_kg", 0)) + initial_shortfall - remaining
            food_close["grain_shortfall_kg"] = remaining
            if target_ref in regional_closes:
                regional_closes[target_ref]["internal_grain_received_kg"] = initial_shortfall - remaining
                regional_closes[target_ref]["grain_shortfall_kg"] = remaining


        # Convert conserved food stock/consumption into a compact economic pressure
        # signal after internal transfers have settled. The signal changes prices
        # and lawful strategic affordability but never creates or removes goods.
        feedback_rules = rules.get("economy_feedback", {}) if isinstance(rules, Mapping) else {}
        target_reserve = max(0.1, _fixed(feedback_rules.get("grain_target_reserve_months", 3.0), 3.0))
        demand_pressure = max(0.0, _fixed(feedback_rules.get("food_shortfall_demand_pressure_at_total_shortfall", 0.75), 0.75))
        for region_ref, region in regions.items():
            if not isinstance(region, dict):
                continue
            rruntime = region.setdefault("production_runtime", {})
            food = rruntime.get("last_food_close", {}) if isinstance(rruntime.get("last_food_close"), Mapping) else {}
            due = max(0, int(food.get("grain_due_kg", 0)))
            shortfall = max(0, int(food.get("grain_shortfall_kg", food.get("grain_shortfall_kg_before_internal_transfer", 0))))
            stock = region.get("commodity_stock", {}) if isinstance(region.get("commodity_stock"), Mapping) else {}
            grain_stock = max(0, int(stock.get("grain_kg", 0)))
            reserve_months = grain_stock / due if due > 0 else 0.0
            supply_fraction = 1.0 if due <= 0 else max(0.0, min(1.0, (due - shortfall) / due))
            shortfall_fraction = 0.0 if due <= 0 else min(1.0, shortfall / due)
            demand_factor = max(1.0, 1.0 + shortfall_fraction * demand_pressure + max(0.0, target_reserve - reserve_months) / target_reserve * 0.20)
            _grain_price, price_basis = self._regional_commodity_unit_price(region, "grain_kg", _fixed(market_prices.get("grain_kg", 0.08), 0.08))
            rruntime["economic_feedback"] = {
                "grain_reserve_months": round(reserve_months, 4),
                "grain_supply_fraction": round(supply_fraction, 6),
                "grain_shortfall_fraction": round(shortfall_fraction, 6),
                "grain_price_factor": round(float(price_basis.get("scarcity_factor", 1.0)), 6),
                "demand_factor": round(demand_factor, 6),
            }

        runtime = eco.setdefault("production_runtime", {})
        runtime["completed_monthly_closes"] = int(runtime.get("completed_monthly_closes", 0)) + occurrences
        runtime["last_close"] = at
        runtime["last_labor_basis"] = {"agricultural": totals["agricultural"], "craft_and_industry_total": totals["craft_total"], "construction_workers_reserved": allocated_workers, "craft_and_industry_available_for_production": totals["craft_available"]}
        runtime["last_food_close"] = {"civilian_population": totals["civilian_population"], "grain_due_kg": totals["grain_due"], "grain_consumed_kg": totals["grain_consumed"], "grain_shortfall_kg": max(0, totals["grain_due"] - totals["grain_consumed"]), "produced_grain_kg": totals["grain_produced"]}
        runtime["last_gross_output_value_silver"] = totals["gross_output_value_silver"]
        runtime["last_taxable_output_value_silver"] = totals["taxable_output_value_silver"]
        runtime["last_realized_sales_silver"] = totals["realized_sales_silver"]
        runtime["last_internal_food_transfers"] = transfers[-64:]
        runtime["last_regional_close"] = regional_closes
        self._sync_local_economy_aggregate(eco)
        self._write_private_economy(path, eco)
        self.put(pp, pop)

    def _market_transport_conditions(self, state: str, market_location_ref: str) -> dict[str, Any]:
        rules = self._civil_rules().get("transport", {})
        territory = self.read("state/territory/control.json")
        routes = self.read("game/data/world/routes.json").get("routes", [])
        operations_index = self.read_optional("state/operations/index.json")
        disruptive_operations: list[dict[str, Any]] = []
        if isinstance(operations_index, Mapping):
            for operation_ref, path in operations_index.get("operations", {}).items():
                if not isinstance(path, str):
                    continue
                operation = self.read_optional(path)
                if not isinstance(operation, Mapping) or str(operation.get("status", "")) not in {"active", "mobilizing", "marching", "occupied"}:
                    continue
                objective = str(operation.get("objective", "")).lower()
                explicit_routes = {str(x) for x in operation.get("route_refs", []) if isinstance(x, str)} if isinstance(operation.get("route_refs"), list) else set()
                tokens = {"raid", "interdict", "blockade", "disrupt", "cut road", "cut route", "bridge", "convoy", "supply line", "harass"}
                if not explicit_routes and not any(token in objective for token in tokens):
                    continue
                authorities = {str(x) for x in operation.get("administrative_authorities", []) if isinstance(x, str)} if isinstance(operation.get("administrative_authorities"), list) else set()
                authority = str(operation.get("administrative_authority", ""))
                if authority:
                    authorities.add(authority)
                if not authorities:
                    for formation_ref in operation.get("formation_refs", []) if isinstance(operation.get("formation_refs"), list) else []:
                        try:
                            _fp, formation = self._load_formation(str(formation_ref))
                        except ValueError:
                            continue
                        if int(formation.get("personnel", 0)) > 0:
                            authorities.add(str(formation.get("administrative_owner", "")))
                if f"state_{state}" in authorities and all(a == f"state_{state}" for a in authorities if a):
                    continue
                disruptive_operations.append({
                    "operation_ref": str(operation_ref),
                    "location_ref": str(operation.get("location_ref", operation.get("target_location_ref", ""))),
                    "route_refs": explicit_routes,
                    "objective": objective,
                    "authorities": sorted(a for a in authorities if a),
                })
        relevant = 0
        disrupted = 0
        disrupted_refs: list[str] = []
        operation_disruption_refs: list[str] = []
        for route in routes if isinstance(routes, list) else []:
            if not isinstance(route, Mapping):
                continue
            a = str(route.get("a", route.get("from", "")))
            b = str(route.get("b", route.get("to", "")))
            if self._native_site_state(a) != state and self._native_site_state(b) != state:
                continue
            relevant += 1
            broken = False
            for endpoint in (a, b):
                if self._native_site_state(endpoint) != state:
                    continue
                site = territory.get("sites", {}).get(endpoint) if isinstance(territory, Mapping) else None
                if isinstance(site, Mapping) and str(site.get("controller")) != f"state_{state}":
                    broken = True
            route_ref = str(route.get("ref", ""))
            for operation in disruptive_operations:
                if (route_ref and route_ref in operation["route_refs"]) or operation["location_ref"] in {a, b}:
                    broken = True
                    operation_disruption_refs.append(str(operation["operation_ref"]))
            if broken:
                disrupted += 1
                disrupted_refs.append(route_ref)
        ratio = disrupted / max(1, relevant)
        penalty = max(0.0, min(1.0, _fixed(rules.get("foreign_control_route_penalty", 0.25), 0.25)))
        route_factor = max(_fixed(rules.get("minimum_restock_route_factor", 0.20), 0.20), 1.0 - ratio * (1.0 + penalty))

        active_siege = False
        siege_refs: list[str] = []
        sieges = self.read_optional("state/sieges/index.json")
        if isinstance(sieges, Mapping):
            for siege_ref, raw in sieges.get("sieges", {}).items():
                if not isinstance(raw, Mapping) or str(raw.get("status", "active")) not in {"active", "blockade"}:
                    continue
                location_ref = str(raw.get("location_ref", raw.get("fortification_location_ref", "")))
                fort_ref = raw.get("fortification_ref")
                if not location_ref and isinstance(fort_ref, str):
                    fort = self.read_optional(self.owner_path(fort_ref))
                    location_ref = str(fort.get("location_ref", "")) if isinstance(fort, Mapping) else ""
                if location_ref == market_location_ref:
                    active_siege = True
                    siege_refs.append(str(siege_ref))
        if active_siege:
            route_factor = min(route_factor, 0.10)
        return {
            "route_factor": round(max(0.0, min(1.0, route_factor)), 4),
            "relevant_routes": relevant,
            "disrupted_routes": disrupted,
            "disrupted_route_refs": [ref for ref in disrupted_refs if ref][-32:],
            "operation_disruption_refs": sorted(set(operation_disruption_refs))[-32:],
            "active_siege": active_siege,
            "siege_refs": siege_refs[-8:],
        }

    def _restock_capital_market(self, state: str, at: str) -> None:
        rules = self._civil_rules()
        spec = rules.get("capital_markets", {}).get(state)
        if not isinstance(spec, Mapping):
            return
        market_path = str(spec.get("path", ""))
        if not market_path or self.read_optional(market_path) is None:
            return
        market = copy.deepcopy(self.read(market_path))
        ep, eco = self._private_economy(state)
        market_location = str(spec.get("location_ref", market.get("location_ref", "")))
        try:
            regional_source_ref, regional = self._local_economy_region(state, eco, market_location)
        except ValueError:
            return
        finished = regional.setdefault("finished_goods", {})
        normal = market.get("normal_stock") if isinstance(market.get("normal_stock"), Mapping) else rules.get("market_normal_stock", {})
        stock = market.setdefault("stock", {})
        conditions = self._market_transport_conditions(state, market_location)
        route_factor = max(0.0, min(1.0, _fixed(conditions.get("route_factor", 1.0), 1.0)))

        population = self.read(f"state/population/{state}.json")
        transport_workers = max(0, int(population.get("strata", {}).get("merchant_and_transport", 0)))
        total_population = max(1, int(population.get("population_total", 1)))
        transport_share = transport_workers / total_population
        capacity_factor = max(0.25, min(1.0, transport_share / 0.03))
        delivery_factor = route_factor * capacity_factor

        moved: dict[str, int] = {}
        for key, target_raw in normal.items():
            key = str(key)
            target = max(0, int(target_raw))
            need = max(0, target - int(stock.get(key, 0)))
            available = max(0, int(finished.get(key, 0)))
            transportable = max(0, int(math.floor(need * delivery_factor)))
            if need > 0 and delivery_factor > 0 and transportable == 0:
                transportable = 1
            take = min(need, available, transportable)
            if take:
                finished[key] = available - take
                stock[key] = int(stock.get(key, 0)) + take
                moved[key] = take

        transport_rules = rules.get("transport", {})
        recovery = max(0.0, _fixed(transport_rules.get("market_recovery_per_month", 0.03), 0.03))
        disruption_increase = max(0.0, _fixed(transport_rules.get("route_disruption_insecurity_increment", 0.08), 0.08)) * int(conditions.get("disrupted_routes", 0))
        siege_increase = max(0.0, _fixed(transport_rules.get("active_siege_market_insecurity_increment", 0.35), 0.35)) if conditions.get("active_siege") else 0.0
        demand_increase = max(0.0, _fixed(transport_rules.get("active_siege_demand_increment", 0.20), 0.20)) if conditions.get("active_siege") else 0.0
        current_insecurity = _fixed(market.get("insecurity_hoarding_factor", 1.0), 1.0)
        current_demand = _fixed(market.get("demand_factor", 1.0), 1.0)
        regional_feedback = regional.get("production_runtime", {}).get("economic_feedback", {}) if isinstance(regional.get("production_runtime"), Mapping) else {}
        food_demand = max(1.0, _fixed(regional_feedback.get("demand_factor", 1.0), 1.0)) if isinstance(regional_feedback, Mapping) else 1.0
        market["insecurity_hoarding_factor"] = round(max(1.0, current_insecurity - recovery + disruption_increase + siege_increase), 4)
        market["demand_factor"] = round(max(1.0, current_demand - recovery + demand_increase, food_demand), 4)
        market["transport_state"] = {**conditions, "transport_workers": transport_workers, "capacity_factor": round(capacity_factor, 4), "delivery_factor": round(delivery_factor, 4), "last_review": at}
        if moved or int(conditions.get("disrupted_routes", 0)) or conditions.get("active_siege"):
            market.setdefault("restock_history", []).append({"at": at, "source_ref": f"private_economy_{state}", "regional_source_ref": regional_source_ref, "moved": moved, "transport": market["transport_state"]})
            market["restock_history"] = market["restock_history"][-24:]
        self.put(market_path, market)
        self._sync_local_economy_aggregate(eco)
        self._write_private_economy(ep, eco)

    def _market_at_player_location(self) -> tuple[str, str, dict[str, Any], str]:
        location = str(self.read("state/player.json").get("location", ""))
        rules = self._civil_rules()
        for state, spec in rules.get("capital_markets", {}).items():
            if not isinstance(spec, Mapping) or str(spec.get("location_ref")) != location:
                continue
            path = str(spec.get("path", ""))
            if not path:
                break
            market = self.read_optional(path)
            if isinstance(market, Mapping):
                return str(state), path, copy.deepcopy(dict(market)), location
        # Dynamic sovereign markets are exact owners rather than static civil-rule
        # entries.  The owner index is a bounded routing surface; exact market files
        # remain authority.
        owners = self.read("state/index/owner-index.json").get("owners", {})
        for market_ref in sorted(str(ref) for ref in owners if str(ref).startswith("market_")):
            path = owners.get(market_ref)
            if not isinstance(path, str):
                continue
            market = self.read_optional(path)
            if not isinstance(market, Mapping) or str(market.get("location_ref", "")) != location:
                continue
            state = str(market.get("state", ""))
            if state not in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
                state = self._native_site_state(location) or ""
            if not state:
                raise ValueError("market has no physical regional economy for settlement")
            return state, path, copy.deepcopy(dict(market)), location
        raise ValueError("market transaction requires lawful physical access to an active exact market")

    def _restock_dynamic_market(self, market_ref: str, at: str) -> None:
        """Restock one exact non-static market from its physical local economy.

        A founded market is a place where goods are exchanged, never a source of
        inventory.  Stock therefore moves from the site's nested regional economy
        into the exact market owner, and transport disruption still constrains the
        transfer.
        """
        try:
            market_path = self.owner_path(market_ref)
            market = copy.deepcopy(self.read(market_path))
        except (KeyError, ValueError, FileNotFoundError):
            return
        location_ref = str(market.get("location_ref", ""))
        state = str(market.get("state", ""))
        if state not in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
            state = self._native_site_state(location_ref) or ""
        if not state:
            market.setdefault("transport_state", {})["last_review"] = at
            market["transport_state"]["status"] = "no_registered_production_region"
            self.put(market_path, market)
            return
        ep, eco = self._private_economy(state)
        try:
            site_ref, region = self._local_economy_region(state, eco, location_ref)
        except ValueError:
            return
        normal = market.get("normal_stock") if isinstance(market.get("normal_stock"), Mapping) else self._civil_rules().get("market_normal_stock", {})
        stock = market.setdefault("stock", {})
        finished = region.setdefault("finished_goods", {})
        conditions = self._market_transport_conditions(state, location_ref)
        route_factor = max(0.0, min(1.0, _fixed(conditions.get("route_factor", 1.0), 1.0)))
        moved: dict[str, int] = {}
        for key, target_raw in normal.items():
            key = str(key); target = max(0, int(target_raw)); need = max(0, target - int(stock.get(key, 0)))
            available = max(0, int(finished.get(key, 0)))
            take = min(need, available, max(0, int(math.floor(need * route_factor))))
            if need and available and route_factor > 0 and take == 0:
                take = 1
            if take:
                finished[key] = available - take
                stock[key] = int(stock.get(key, 0)) + take
                moved[key] = take
        regional_feedback = region.get("production_runtime", {}).get("economic_feedback", {}) if isinstance(region.get("production_runtime"), Mapping) else {}
        if isinstance(regional_feedback, Mapping):
            market["demand_factor"] = round(max(1.0, _fixed(market.get("demand_factor", 1.0), 1.0), _fixed(regional_feedback.get("demand_factor", 1.0), 1.0)), 4)
        market["transport_state"] = {**conditions, "regional_source_ref": site_ref, "last_review": at}
        if moved:
            market.setdefault("restock_history", []).append({"at": at, "regional_source_ref": site_ref, "moved": moved})
            market["restock_history"] = market["restock_history"][-24:]
        self._sync_local_economy_aggregate(eco)
        self._write_private_economy(ep, eco)
        self.put(market_path, market)

    def _market_unit_price(self, market: Mapping[str, Any], item_key: str) -> tuple[float, dict[str, float]]:
        econ = self.read("game/data/mechanics/economy.json")
        base = _fixed(econ.get("prices_silver", {}).get(item_key), -1)
        if base < 0:
            raise ValueError("unknown or unpriced market item")
        current = max(0, int(market.get("stock", {}).get(item_key, 0)))
        normal_map = market.get("normal_stock") if isinstance(market.get("normal_stock"), Mapping) else self._civil_rules().get("market_normal_stock", {})
        normal = max(1, int(normal_map.get(item_key, current or 1)))
        if current <= 0:
            raise ValueError("market item is unavailable because no positive physical stock exists")
        scarcity = max(0.55, min(3.50, (normal / current) ** 0.55))
        demand = max(0.1, _fixed(market.get("demand_factor", 1.0), 1.0))
        insecurity = max(0.1, _fixed(market.get("insecurity_hoarding_factor", 1.0), 1.0))
        return base * scarcity * demand * insecurity, {"base": base, "scarcity": scarcity, "demand": demand, "insecurity": insecurity}

    def _native_site_state(self, location_ref: str) -> str | None:
        """Return the cold homeland state for one exact territorial site.

        Homeland is a tax/population provenance fact only. Current controller and
        occupation status remain owned by state/territory/control.json.
        """
        try:
            row = self._location_record(location_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return None
        state = str(row.get("state", "")).lower() if isinstance(row, Mapping) else ""
        return state if state in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"} else None

    def _native_site_counts(self) -> dict[str, int]:
        counts = {state: 0 for state in ("qin", "zhao", "chu", "wei", "han", "yan", "qi")}
        territory = self.read("state/territory/control.json")
        for location_ref in territory.get("sites", {}) if isinstance(territory, Mapping) else {}:
            native = self._native_site_state(str(location_ref))
            if native in counts:
                counts[native] += 1
        return counts

    def _local_site_weight(self, location_ref: str) -> float:
        row = self._location_record(location_ref)
        if not isinstance(row, Mapping) or not bool(row.get("national_population_eligible", False)):
            return 0.0
        kind = str(row.get("kind", "site"))
        weights = {"capital": 8.0, "major_city": 5.5, "city": 4.5, "region": 3.0, "town": 2.0, "fort": 0.55, "pass": 0.35, "village": 0.7}
        weight = weights.get(kind, 1.0)
        functions = {str(x) for x in row.get("functions", [])} if isinstance(row.get("functions"), list) else set()
        if "taxation" in functions: weight += 1.0
        if "market" in functions and kind in {"capital","major_city","city","town"}: weight += 0.6
        if "recruitment" in functions and kind in {"capital","major_city","city","region","town"}: weight += 0.3
        return max(0.0, weight)

    @staticmethod
    def _weighted_integer_partition(total: int, rows: list[tuple[str, float]]) -> dict[str, int]:
        total = max(0, int(total))
        if not rows:
            return {}
        positive = [(ref, max(0.0, float(weight))) for ref, weight in rows]
        denom = sum(weight for _ref, weight in positive)
        if denom <= 0:
            positive = [(ref, 1.0) for ref, _weight in positive]
            denom = float(len(positive))
        raw = [(ref, total * weight / denom) for ref, weight in positive]
        out = {ref: int(math.floor(value)) for ref, value in raw}
        remaining = total - sum(out.values())
        order = sorted(raw, key=lambda row: (-(row[1] - math.floor(row[1])), row[0]))
        for ref, _value in order[:remaining]:
            out[ref] += 1
        return out

    def _state_fiscal_rules(self) -> dict[str, Any]:
        economy = self.read("game/data/mechanics/economy.json")
        rules = economy.get("state_fiscal_model", {}) if isinstance(economy, Mapping) else {}
        return dict(rules) if isinstance(rules, Mapping) else {}

    def _state_administration_realization(self, state: str) -> float:
        rules = self._state_fiscal_rules().get("administration_realization", {})
        rules = rules if isinstance(rules, Mapping) else {}
        state_doc = self.read(f"state/states/{state}.json")
        administrative_capacity = max(0.0, _fixed(state_doc.get("administrative_capacity", 0), 0.0))
        floor_factor = max(0.0, _fixed(rules.get("floor_factor", 0.45), 0.45))
        marginal_factor = max(0.0, _fixed(rules.get("marginal_factor", 0.75), 0.75))
        scale = max(1.0, _fixed(rules.get("diminishing_scale", 80.0), 80.0))
        return max(0.0, floor_factor + marginal_factor * (1.0 - math.exp(-administrative_capacity / scale)))

    def _controlled_demographic_population_rows(self, state: str) -> list[tuple[str, str, dict[str, Any]]]:
        """Return unique demographic population owners controlled by ``state``.

        Facilities, gates, halls, depots, offices and other child locations may
        inherit a demographic anchor for access/recruitment queries, but they are
        never additional population owners. Fiscal settlement must therefore walk
        the exact local-population partition, then filter those owner locations by
        current territorial control.
        """
        territory = self.read("state/territory/control.json")
        rows: list[tuple[str, str, dict[str, Any]]] = []
        for native in ("qin", "zhao", "chu", "wei", "han", "yan", "qi"):
            try:
                _pp, pop = self._ensure_local_population_ledger(native)
            except (ValueError, KeyError, FileNotFoundError):
                continue
            sites = pop.get("local_population", {}).get("sites", {}) if isinstance(pop, Mapping) else {}
            if not isinstance(sites, Mapping):
                continue
            for location_ref, local_row in sorted(sites.items()):
                if not isinstance(local_row, Mapping):
                    continue
                site = territory.get("sites", {}).get(location_ref, {}) if isinstance(territory, Mapping) else {}
                if not isinstance(site, Mapping) or str(site.get("controller")) != f"state_{state}":
                    continue
                rows.append((native, str(location_ref), dict(local_row)))
        return rows

    def _state_controlled_living_population(self, state: str) -> int:
        return sum(
            max(0, int(self._local_taxable_civilian_population(local_row)))
            for _native, _location_ref, local_row in self._controlled_demographic_population_rows(state)
        )

    def _state_monthly_expense_plan(self, state: str, monthly_revenue_due: int) -> dict[str, int | float]:
        economy = self.read("game/data/mechanics/economy.json")
        rules = self._state_fiscal_rules()
        ordinary = economy.get("ordinary_market_reference", {}) if isinstance(economy, Mapping) else {}
        wage = max(0.0, _fixed(ordinary.get("professional_soldier_monthly_pay_silver_before_support", 7), 7.0))
        force = self.read(f"state/forces/state-{state}.json")
        military_headcount = max(0, int(force.get("headcount", 0)))
        service_equivalent = max(0.0, _fixed(rules.get("military_cash_service_equivalent_fraction", 0.52), 0.52))
        support_multiplier = max(0.0, _fixed(rules.get("military_support_multiplier", 1.35), 1.35))
        military_due = max(0, int(round(military_headcount * wage * service_equivalent * support_multiplier)))
        controlled_population = self._state_controlled_living_population(state)
        civil_rate = max(0.0, _fixed(rules.get("civil_administration_silver_per_controlled_civilian_month", 0.18), 0.18))
        civil_due = max(0, int(round(controlled_population * civil_rate)))
        maintenance_fraction = max(0.0, _fixed(rules.get("strategic_maintenance_fraction_of_due_revenue", 0.15), 0.15))
        maintenance_due = max(0, int(round(max(0, int(monthly_revenue_due)) * maintenance_fraction)))
        return {
            "military_headcount": military_headcount,
            "controlled_living_population": controlled_population,
            "professional_wage_silver": round(wage, 4),
            "military_cash_service_equivalent_fraction": round(service_equivalent, 4),
            "military_support_multiplier": round(support_multiplier, 4),
            "military_due_silver": military_due,
            "civil_administration_due_silver": civil_due,
            "strategic_maintenance_due_silver": maintenance_due,
            "total_due_silver": military_due + civil_due + maintenance_due,
        }

    def _ensure_local_site_baselines(self, native_state: str) -> dict[str, dict[str, Any]]:
        """Persist a bounded local demographic/tax partition for strategic sites.

        State population remains the conserved body authority.  These site rows are
        an explicit non-authoritative allocation view used for local occupation/tax
        scale, replacing the old equal-division shortcut.  Once materialized, a
        site's relative importance remains stable instead of changing merely because
        another site was added to world data.
        """
        territory = copy.deepcopy(self.read("state/territory/control.json"))
        sites = territory.get("sites", {}) if isinstance(territory, Mapping) else {}
        native_refs = sorted(str(ref) for ref in sites if self._native_site_state(str(ref)) == native_state and self._local_site_weight(str(ref)) > 0)
        if not native_refs:
            return {}
        population = self.read(f"state/population/{native_state}.json")
        population_total = max(0, int(population.get("population_total", 0)))
        state_doc = self.read(f"state/states/{native_state}.json")
        expected_monthly_tax = max(0, int(state_doc.get("normal_monthly_revenue_silver", 0)))
        existing: dict[str, dict[str, Any]] = {}
        complete = True
        for ref in native_refs:
            site = sites.get(ref)
            baseline = site.get("local_baseline") if isinstance(site, Mapping) and isinstance(site.get("local_baseline"), Mapping) else None
            required = {"authority", "population_allocation", "monthly_tax_base_silver", "relative_weight"}
            if not isinstance(baseline, Mapping) or not required.issubset(baseline) or baseline.get("authority") is not False:
                complete = False
                break
            existing[ref] = copy.deepcopy(dict(baseline))
        if complete:
            conserved_population = sum(max(0, int(row.get("population_allocation", 0))) for row in existing.values())
            conserved_tax = sum(max(0, int(row.get("monthly_tax_base_silver", 0))) for row in existing.values())
            if conserved_population == population_total and conserved_tax == expected_monthly_tax:
                return existing

        fiscal_rules = self._state_fiscal_rules()
        weighted = [(ref, self._local_site_weight(ref)) for ref in native_refs]
        pop_partition = self._weighted_integer_partition(population_total, weighted)
        tax_partition = self._weighted_integer_partition(expected_monthly_tax, [(ref, max(1.0, float(pop_partition.get(ref, 0)))) for ref, _weight in weighted])
        result: dict[str, dict[str, Any]] = {}
        for ref, weight in weighted:
            site = sites[ref]
            baseline = {
                "authority": False,
                "population_allocation": int(pop_partition.get(ref, 0)),
                "monthly_tax_base_silver": int(tax_partition.get(ref, 0)),
                "relative_weight": round(float(weight), 4),
            }
            site["local_baseline"] = baseline
            result[ref] = copy.deepcopy(baseline)
        self.put("state/territory/control.json", territory)
        return result

    @staticmethod
    def _local_service_class(service_key: str) -> str:
        return {
            "serving_native_military": "native_military",
            "serving_foreign_military": "foreign_state_military",
            "private_household_military": "private_house_military",
            "rebel_military": "rebel_military",
        }.get(str(service_key), str(service_key))

    @staticmethod
    def _local_service_total(row: Mapping[str, Any], service_class: str | None = None) -> int:
        allocations = row.get("service_allocations", {}) if isinstance(row, Mapping) else {}
        if not isinstance(allocations, Mapping):
            return 0
        total = 0
        for value in allocations.values():
            if not isinstance(value, Mapping):
                continue
            if service_class is not None and str(value.get("service_class", "")) != service_class:
                continue
            total += max(0, int(value.get("personnel", 0)))
        return total

    @staticmethod
    def _local_reserved_total(row: Mapping[str, Any]) -> int:
        reservations = row.get("candidate_reservations", {}) if isinstance(row, Mapping) else {}
        if not isinstance(reservations, Mapping):
            return 0
        total = 0
        for value in reservations.values():
            if not isinstance(value, Mapping):
                continue
            sources = value.get("source_strata", {}) if isinstance(value.get("source_strata"), Mapping) else {}
            total += sum(max(0, int(v)) for v in sources.values())
        return total

    def _sync_local_population_row(self, row: dict[str, Any]) -> None:
        civilian_strata = row.get("civilian_strata", {}) if isinstance(row.get("civilian_strata"), Mapping) else {}
        row["civilian_population"] = sum(max(0, int(v)) for v in civilian_strata.values())
        row["agricultural_available"] = max(0, int(civilian_strata.get("agricultural", 0)))
        row["serving_native_military"] = self._local_service_total(row, "native_military")
        row["serving_foreign_military"] = self._local_service_total(row, "foreign_state_military")
        row["rebel_military"] = self._local_service_total(row, "rebel_military")
        row["private_household_military"] = self._local_service_total(row, "private_house_military")
        # Readable mirrors are derived from the exact nested allocations and
        # are never independent writable population authorities.
        row["service_population"] = self._local_service_total(row)
        row["candidates_reserved"] = self._local_reserved_total(row)
        row["reserved_candidates"] = row["candidates_reserved"]

    def _ensure_local_population_ledger(self, native_state: str, population: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        """Maintain one authoritative local-origin partition inside the population owner.

        The current partition assigns every civilian source stratum only among legitimate demographic owners and
        tracks candidate reservations plus service allocations by exact force or owner.
        The parent population file remains the sole body authority; locality is a
        nested partition of those same conserved people, not a second population.
        """
        path = f"state/population/{native_state}.json"
        pop = copy.deepcopy(population) if isinstance(population, dict) else copy.deepcopy(self.read(path))
        local = pop.get("local_population")
        if isinstance(local, Mapping) and isinstance(local.get("sites"), Mapping):
            for row in local.get("sites", {}).values():
                if isinstance(row, dict):
                    self._sync_local_population_row(row)
            return path, pop
        if native_state not in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
            raise ValueError("non-core population owner requires an explicit conserved local population ledger")

        baselines = self._ensure_local_site_baselines(native_state)
        weighted = [(ref, max(0.0001, _fixed(row.get("relative_weight", 1.0), 1.0))) for ref, row in sorted(baselines.items())]
        if not weighted:
            return path, pop
        strata = pop.get("strata", {}) if isinstance(pop.get("strata"), Mapping) else {}
        population_total = max(0, int(pop.get("population_total", 0)))
        service_strata = {
            "active_military": (f"force_state_{native_state}", "native_military"),
            "foreign_military_service": ("foreign_state_service_unresolved", "foreign_state_military"),
            "rebel_military": ("rebel_service_unresolved", "rebel_military"),
            "private_household_military": ("private_service_unresolved", "private_house_military"),
        }
        reserved_key = "recruitment_candidates_reserved"
        civilian_keys = [str(k) for k in strata if str(k) not in set(service_strata) | {reserved_key}]

        old_sites = local.get("sites", {}) if isinstance(local, Mapping) and isinstance(local.get("sites"), Mapping) else {}
        if old_sites:
            living_weights = []
            for ref, fallback in weighted:
                old = old_sites.get(ref, {}) if isinstance(old_sites.get(ref), Mapping) else {}
                living = sum(max(0, int(old.get(k, 0))) for k in ("civilian_population", "serving_native_military", "serving_foreign_military", "rebel_military", "displaced"))
                living_weights.append((ref, max(1.0, float(living)) if living else fallback))
            weighted = living_weights

        civilian_partitions = {key: self._weighted_integer_partition(max(0, int(strata.get(key, 0))), weighted) for key in civilian_keys}
        service_partitions = {key: self._weighted_integer_partition(max(0, int(strata.get(key, 0))), weighted) for key in service_strata}
        reserved_partition = self._weighted_integer_partition(max(0, int(strata.get(reserved_key, 0))), weighted)
        total_partition = self._weighted_integer_partition(population_total, weighted)

        sites: dict[str, dict[str, Any]] = {}
        for ref, _weight in weighted:
            old = old_sites.get(ref, {}) if isinstance(old_sites.get(ref), Mapping) else {}
            civilian_strata = {key: int(civilian_partitions[key].get(ref, 0)) for key in civilian_keys}
            allocations: dict[str, dict[str, Any]] = {}
            for source_key, (owner_ref, service_class) in service_strata.items():
                count = int(service_partitions[source_key].get(ref, 0))
                if count:
                    allocations[owner_ref] = {"personnel": count, "service_class": service_class, "source_stratum": source_key}
            reservations: dict[str, Any] = {}
            reserved = int(reserved_partition.get(ref, 0))
            if reserved:
                reservations["unresolved_reserved_candidates"] = {"source_strata": {"unresolved": reserved}, "reserved_at": None}
            row = {
                "location_ref": ref,
                "initial_population": int(old.get("initial_population", total_partition.get(ref, 0))),
                "civilian_strata": civilian_strata,
                "service_allocations": allocations,
                "candidate_reservations": reservations,
                "displaced": max(0, int(old.get("displaced", 0))),
                "deaths_cumulative": max(0, int(old.get("deaths_cumulative", 0))),
            }
            self._sync_local_population_row(row)
            sites[ref] = row
        pop["local_population"] = {
            "authority": True,
            "representation": "aggregate local-origin partition inside the exact regional population owner",
            "sites": sites,
            "initialized_from_population_total": population_total,
            "basis": "every civilian source stratum, candidate reservation and military/private/rebel service allocation remains a partition of the parent population owner",
        }
        return path, pop

    def _local_population_site_for_location(self, native_state: str, location_ref: str, population: dict[str, Any] | None = None, *, controller_ref: str | None = None) -> tuple[str, dict[str, Any], str]:
        path, pop = self._ensure_local_population_ledger(native_state, population)
        sites = pop.get("local_population", {}).get("sites", {})
        if location_ref in sites:
            return path, pop, location_ref
        anchor = demographic_anchor(self.read, str(location_ref), sites.keys())
        if anchor in sites:
            if controller_ref:
                territory = self.read("state/territory/control.json")
                site = territory.get("sites", {}).get(anchor, {}) if isinstance(territory, Mapping) else {}
                if str(site.get("controller", "")) == controller_ref:
                    return path, pop, str(anchor)
            else:
                return path, pop, str(anchor)
        territory = self.read("state/territory/control.json")
        candidates = []
        for ref in sorted(str(x) for x in sites):
            site = territory.get("sites", {}).get(ref, {}) if isinstance(territory, Mapping) else {}
            if controller_ref and str(site.get("controller", "")) != controller_ref:
                continue
            try:
                hours = int(self._route_travel_hours(location_ref, ref))
            except Exception:
                hours = 10**9
            candidates.append((hours, ref))
        if not candidates:
            raise ValueError(f"no locally allocated population is accessible from {location_ref}")
        return path, pop, sorted(candidates)[0][1]

    @staticmethod
    def _local_taxable_civilian_population(row: Mapping[str, Any]) -> int:
        civilian_strata = row.get("civilian_strata", {}) if isinstance(row.get("civilian_strata"), Mapping) else {}
        if civilian_strata:
            return sum(max(0, int(value)) for value in civilian_strata.values())
        return max(0, int(row.get("civilian_population", 0)))

    @staticmethod
    def _local_origin_living(row: Mapping[str, Any]) -> int:
        allocations = row.get("service_allocations", {}) if isinstance(row.get("service_allocations"), Mapping) else {}
        service = sum(max(0, int(v.get("personnel", 0))) for v in allocations.values() if isinstance(v, Mapping))
        reservations = row.get("candidate_reservations", {}) if isinstance(row.get("candidate_reservations"), Mapping) else {}
        reserved = sum(sum(max(0, int(x)) for x in (v.get("source_strata", {}) if isinstance(v, Mapping) and isinstance(v.get("source_strata"), Mapping) else {}).values()) for v in reservations.values())
        if allocations or reservations or isinstance(row.get("civilian_strata"), Mapping):
            civilian = sum(max(0, int(v)) for v in (row.get("civilian_strata", {}) if isinstance(row.get("civilian_strata"), Mapping) else {}).values())
            return civilian + service + reserved + max(0, int(row.get("displaced", 0)))
        return sum(max(0, int(row.get(key, 0))) for key in ("civilian_population", "serving_native_military", "serving_foreign_military", "rebel_military", "displaced"))

    def _local_population_row(self, native_state: str, location_ref: str, population: dict[str, Any] | None = None) -> tuple[str, dict[str, Any], dict[str, Any]]:
        path, pop = self._ensure_local_population_ledger(native_state, population)
        local = pop.setdefault("local_population", {}).setdefault("sites", {})
        row = local.get(location_ref)
        if not isinstance(row, dict):
            # Facilities, gates, depots and offices do not own demographic rows.
            # Resolve them through explicit containment to the legitimate
            # settlement or territorial population owner.
            anchor = demographic_anchor(self.read, str(location_ref), local.keys())
            row = local.get(anchor) if isinstance(anchor, str) else None
        if not isinstance(row, dict):
            raise ValueError(f"location {location_ref} has no demographic owner inside population_{native_state}")
        return path, pop, row

    def _add_local_service_allocation(self, row: dict[str, Any], owner_ref: str, count: int, *, service_class: str, source_stratum: str) -> None:
        if count <= 0:
            return
        allocations = row.setdefault("service_allocations", {})
        record = allocations.setdefault(owner_ref, {"personnel": 0, "service_class": service_class, "source_stratum": source_stratum})
        if str(record.get("service_class", service_class)) != service_class:
            raise ValueError("local service allocation owner has conflicting service class")
        record["personnel"] = int(record.get("personnel", 0)) + int(count)
        record["source_stratum"] = source_stratum
        self._sync_local_population_row(row)

    def _consume_local_recruitment(self, population: dict[str, Any], native_state: str, location_ref: str, count: int, *, service_key: str, source_stratum: str = "agricultural", service_owner_ref: str | None = None) -> int:
        _path, pop, row = self._local_population_row(native_state, location_ref, population)
        requested = max(0, int(count)); civilian = row.setdefault("civilian_strata", {})
        available = max(0, int(civilian.get(source_stratum, 0))); take = min(requested, available)
        if take:
            civilian[source_stratum] = available - take
            service_class = self._local_service_class(service_key)
            owner_ref = str(service_owner_ref or {
                "native_military": f"force_state_{native_state}",
                "foreign_state_military": "foreign_state_service_unresolved",
                "private_house_military": "private_service_unresolved",
                "rebel_military": "rebel_service_unresolved",
            }.get(service_class, service_class))
            self._add_local_service_allocation(row, owner_ref, take, service_class=service_class, source_stratum=source_stratum)
            row["last_service_transfer"] = {"kind": service_class, "owner_ref": owner_ref, "source_stratum": source_stratum, "personnel": take}
        self._sync_local_population_row(row); population.clear(); population.update(pop); return take

    def _consume_local_private_recruitment(self, population: dict[str, Any], native_state: str, requested_location: str, count: int, *, source_stratum: str, force_ref: str, controller_ref: str | None = None) -> list[dict[str, Any]]:
        path, pop = self._ensure_local_population_ledger(native_state, population)
        territory = self.read("state/territory/control.json"); sites = pop.get("local_population", {}).get("sites", {})
        preferred_anchor: str | None = None
        try:
            _anchor_path, _anchor_pop, preferred_anchor = self._local_population_site_for_location(
                native_state, requested_location, pop, controller_ref=controller_ref
            )
        except ValueError:
            preferred_anchor = None
        ranked: list[tuple[int, int, str]] = []
        for ref, row in sites.items():
            site = territory.get("sites", {}).get(ref, {}) if isinstance(territory, Mapping) else {}
            if controller_ref and str(site.get("controller", "")) != controller_ref: continue
            available = max(0, int((row.get("civilian_strata", {}) if isinstance(row, Mapping) else {}).get(source_stratum, 0)))
            if available <= 0: continue
            try: hours = int(self._route_travel_hours(requested_location, str(ref)))
            except Exception: hours = 10**9
            ranked.append((0 if str(ref) == preferred_anchor else 1, hours, str(ref)))
        remaining = max(0, int(count)); moved: list[dict[str, Any]] = []
        for _preferred, _hours, ref in sorted(ranked):
            if remaining <= 0: break
            take = self._consume_local_recruitment(pop, native_state, ref, remaining, service_key="private_household_military", source_stratum=source_stratum, service_owner_ref=force_ref)
            if take: moved.append({"location_ref": ref, "source_stratum": source_stratum, "personnel": take, "force_ref": force_ref}); remaining -= take
        if remaining:
            raise ValueError("private recruitment exceeded population physically accessible in controlled territory")
        population.clear(); population.update(pop); return moved

    def _reserve_local_candidates(self, population: dict[str, Any], native_state: str, requested_location: str, campaign_ref: str, source_counts: Mapping[str, Any], *, controller_ref: str | None = None) -> list[dict[str, Any]]:
        _path, pop = self._ensure_local_population_ledger(native_state, population)
        territory = self.read("state/territory/control.json"); sites = pop.get("local_population", {}).get("sites", {})
        preferred_anchor: str | None = None
        try:
            _anchor_path, _anchor_pop, preferred_anchor = self._local_population_site_for_location(
                native_state, requested_location, pop, controller_ref=controller_ref
            )
        except ValueError:
            preferred_anchor = None
        reserved_rows: list[dict[str, Any]] = []
        for source_stratum, raw_count in sorted(source_counts.items()):
            remaining = max(0, int(raw_count)); ranked=[]
            for ref, row in sites.items():
                site = territory.get("sites", {}).get(ref, {}) if isinstance(territory, Mapping) else {}
                if controller_ref and str(site.get("controller", "")) != controller_ref: continue
                available=max(0,int((row.get("civilian_strata",{}) if isinstance(row,Mapping) else {}).get(str(source_stratum),0)))
                if available<=0: continue
                try: hours=int(self._route_travel_hours(requested_location,str(ref)))
                except Exception: hours=10**9
                ranked.append((0 if str(ref) == preferred_anchor else 1,hours,str(ref)))
            for _preferred, _hours, ref in sorted(ranked):
                if remaining<=0: break
                row=sites[ref]; civilians=row.setdefault("civilian_strata",{}); available=max(0,int(civilians.get(str(source_stratum),0))); take=min(remaining,available)
                if not take: continue
                civilians[str(source_stratum)]=available-take
                reservation=row.setdefault("candidate_reservations",{}).setdefault(campaign_ref,{"source_strata":{},"reserved_at":str(self._world_time())})
                reservation["source_strata"][str(source_stratum)]=int(reservation["source_strata"].get(str(source_stratum),0))+take
                self._sync_local_population_row(row); reserved_rows.append({"location_ref":ref,"source_stratum":str(source_stratum),"personnel":take}); remaining-=take
            if remaining: raise ValueError(f"candidate campaign lacks locally accessible {source_stratum} population")
        population.clear(); population.update(pop); return reserved_rows

    def _release_local_candidate_rejections(self, population: dict[str, Any], campaign_ref: str, rejected_by_source: Mapping[str, Any]) -> list[dict[str, Any]]:
        local = population.get("local_population", {}) if isinstance(population.get("local_population"), Mapping) else {}; sites=local.get("sites",{}) if isinstance(local.get("sites"),Mapping) else {}
        remaining={str(k):max(0,int(v)) for k,v in rejected_by_source.items()}; rows=[]
        for ref,row in sorted(sites.items()):
            reservation=row.get("candidate_reservations",{}).get(campaign_ref) if isinstance(row,Mapping) and isinstance(row.get("candidate_reservations"),Mapping) else None
            if not isinstance(reservation,dict): continue
            sources=reservation.get("source_strata",{}) if isinstance(reservation.get("source_strata"),dict) else {}
            for source in sorted(list(sources)):
                need=remaining.get(source,0)
                if need<=0: continue
                take=min(need,max(0,int(sources.get(source,0))))
                if take:
                    sources[source]-=take; row.setdefault("civilian_strata",{})[source]=int(row.get("civilian_strata",{}).get(source,0))+take; remaining[source]-=take; rows.append({"location_ref":str(ref),"source_stratum":source,"personnel":take}); self._sync_local_population_row(row)
            reservation["source_strata"]={k:v for k,v in sources.items() if int(v)>0}
            if not reservation["source_strata"]: row.get("candidate_reservations",{}).pop(campaign_ref,None)
        if any(remaining.values()): raise ValueError("candidate rejection could not be reconciled to local reservations")
        return rows

    def _finalize_local_candidate_reservations(self, population: dict[str, Any], campaign_ref: str, force_ref: str) -> list[dict[str, Any]]:
        local=population.get("local_population",{}) if isinstance(population.get("local_population"),Mapping) else {}; sites=local.get("sites",{}) if isinstance(local.get("sites"),Mapping) else {}; rows=[]
        for ref,row in sorted(sites.items()):
            reservation=row.get("candidate_reservations",{}).get(campaign_ref) if isinstance(row,Mapping) and isinstance(row.get("candidate_reservations"),Mapping) else None
            if not isinstance(reservation,dict): continue
            sources=reservation.get("source_strata",{}) if isinstance(reservation.get("source_strata"),Mapping) else {}
            for source,count in sorted(sources.items()):
                count=max(0,int(count))
                if count:
                    self._add_local_service_allocation(row,force_ref,count,service_class="private_house_military",source_stratum=str(source)); rows.append({"location_ref":str(ref),"source_stratum":str(source),"personnel":count,"force_ref":force_ref})
            row.get("candidate_reservations",{}).pop(campaign_ref,None); self._sync_local_population_row(row)
        return rows

    def _release_local_service(self, population: dict[str, Any], native_state: str, location_ref: str, count: int, *, service_key: str, to_agricultural: bool = True, service_owner_ref: str | None = None) -> int:
        _path,pop,row=self._local_population_row(native_state,location_ref,population); service_class=self._local_service_class(service_key); remaining=max(0,int(count)); released=0
        allocations=row.setdefault("service_allocations",{})
        keys=[service_owner_ref] if service_owner_ref and service_owner_ref in allocations else sorted(allocations)
        for key in keys:
            rec=allocations.get(key)
            if not isinstance(rec,dict) or str(rec.get("service_class",""))!=service_class: continue
            take=min(remaining,max(0,int(rec.get("personnel",0)))); rec["personnel"]=int(rec.get("personnel",0))-take; remaining-=take; released+=take
            source=str(rec.get("source_stratum","agricultural")) if to_agricultural else "dependents_children_elderly"
            row.setdefault("civilian_strata",{})[source]=int(row.get("civilian_strata",{}).get(source,0))+take
            if int(rec.get("personnel",0))<=0: allocations.pop(key,None)
            if remaining<=0: break
        self._sync_local_population_row(row); population.clear(); population.update(pop); return released

    def _record_local_service_deaths(self, population: dict[str, Any], native_state: str, location_ref: str, count: int, *, service_key: str, service_owner_ref: str | None = None) -> int:
        _path,pop,row=self._local_population_row(native_state,location_ref,population); service_class=self._local_service_class(service_key); remaining=max(0,int(count)); applied=0; allocations=row.setdefault("service_allocations",{})
        keys=[service_owner_ref] if service_owner_ref and service_owner_ref in allocations else sorted(allocations)
        for key in keys:
            rec=allocations.get(key)
            if not isinstance(rec,dict) or str(rec.get("service_class",""))!=service_class: continue
            take=min(remaining,max(0,int(rec.get("personnel",0)))); rec["personnel"]=int(rec.get("personnel",0))-take; remaining-=take; applied+=take; row["deaths_cumulative"]=int(row.get("deaths_cumulative",0))+take
            if int(rec.get("personnel",0))<=0: allocations.pop(key,None)
            if remaining<=0: break
        self._sync_local_population_row(row); population.clear(); population.update(pop); return applied

    def _native_recruitment_sites(self, state: str, population: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[tuple[str, int]]]:
        _path, pop = self._ensure_local_population_ledger(state, population)
        territory = self.read("state/territory/control.json")
        rows: list[tuple[str, int]] = []
        for location_ref, row in pop.get("local_population", {}).get("sites", {}).items():
            site = territory.get("sites", {}).get(location_ref, {}) if isinstance(territory, Mapping) else {}
            if str(site.get("controller", "")) != f"state_{state}":
                continue
            available = min(max(0, int(row.get("agricultural_available", 0))), max(0, int(row.get("civilian_population", 0))))
            if available > 0:
                rows.append((str(location_ref), available))
        return pop, sorted(rows, key=lambda item: (-item[1], item[0]))

    def _autonomy_state_recruitment_available(self, state: str, population: dict[str, Any]) -> int:
        pop, rows = self._native_recruitment_sites(state, population)
        population.clear(); population.update(pop)
        return sum(value for _ref, value in rows)

    def _autonomy_state_recruitment_source_location(self, state: str, population: dict[str, Any], default_location: str) -> str:
        pop, rows = self._native_recruitment_sites(state, population)
        population.clear(); population.update(pop)
        if any(ref == default_location for ref, _value in rows):
            return default_location
        return rows[0][0] if rows else default_location

    def _autonomy_state_record_local_recruitment(self, state: str, population: dict[str, Any], count: int, at: str, preferred_location: str) -> list[dict[str, Any]]:
        pop, rows = self._native_recruitment_sites(state, population)
        rows = sorted(rows, key=lambda item: (0 if item[0] == preferred_location else 1, -item[1], item[0]))
        remaining = max(0, int(count)); transfers: list[dict[str, Any]] = []
        for location_ref, _available in rows:
            if remaining <= 0:
                break
            taken = self._consume_local_recruitment(pop, state, location_ref, remaining, service_key="serving_native_military", source_stratum="agricultural", service_owner_ref=f"force_state_{state}")
            if taken:
                transfers.append({"location_ref": location_ref, "personnel": taken, "service": "native_military", "at": at})
                remaining -= taken
        if remaining:
            raise ValueError("native recruitment exceeded population physically accessible in controlled territory")
        population.clear(); population.update(pop)
        return transfers

    def _house_cash_record(self, house_ref: str) -> tuple[str, dict[str, Any], str | None, dict[str, Any] | None]:
        house_path = self.owner_path(house_ref)
        house = copy.deepcopy(self.read(house_path))
        treasury_ref = house.get("treasury_ref")
        if isinstance(treasury_ref, str) and treasury_ref:
            treasury_path = self.owner_path(treasury_ref)
            treasury = copy.deepcopy(self.read(treasury_path))
            return house_path, house, treasury_path, treasury
        return house_path, house, None, None

    def _house_cash_balance(self, house_ref: str) -> int:
        _hp, house, _tp, treasury = self._house_cash_record(house_ref)
        return max(0, int(treasury.get("silver", 0))) if isinstance(treasury, Mapping) else max(0, int(house.get("treasury_silver", 0)))

    def _credit_house_cash(self, house_ref: str, amount: int) -> int:
        amount = max(0, int(amount))
        if amount <= 0:
            return 0
        hp, house, tp, treasury = self._house_cash_record(house_ref)
        if isinstance(treasury, dict) and tp:
            treasury["silver"] = max(0, int(treasury.get("silver", 0))) + amount
            self.put(tp, treasury)
        else:
            house["treasury_silver"] = max(0, int(house.get("treasury_silver", 0))) + amount
            self.put(hp, house)
        return amount

    def _debit_house_cash(self, house_ref: str, amount: int) -> int:
        amount = max(0, int(amount))
        if amount <= 0:
            return 0
        hp, house, tp, treasury = self._house_cash_record(house_ref)
        balance = max(0, int(treasury.get("silver", 0))) if isinstance(treasury, Mapping) else max(0, int(house.get("treasury_silver", 0)))
        paid = min(amount, balance)
        if isinstance(treasury, dict) and tp:
            treasury["silver"] = balance - paid
            self.put(tp, treasury)
        else:
            house["treasury_silver"] = balance - paid
            self.put(hp, house)
        return paid

    def _private_site_owner(self, location_ref: str) -> str | None:
        land = self.read_optional(LAND_STATE_PATH)
        site = land.get("sites", {}).get(location_ref, {}) if isinstance(land, Mapping) else {}
        owner = site.get("private_owner_ref") if isinstance(site, Mapping) else None
        return str(owner) if isinstance(owner, str) and owner else None

    def _territorial_revenue_plan(self, state: str, occurrences: int) -> list[dict[str, Any]]:
        """Assess the one universal sovereign tax against real local output.

        Every sovereign state uses the same rate and formula.  Administration and
        occupation compliance can change how much of the lawful assessment is
        actually collectible, but there is no per-state tax-policy minigame.
        """
        if occurrences <= 0:
            return []
        territory = self.read("state/territory/control.json")
        occupation_rules = self._civil_rules().get("occupation", {})
        foreign_realization = max(0.0, min(1.0, _fixed(occupation_rules.get("foreign_tax_realization_factor", 0.85), 0.85)))
        fiscal_rules = self._state_fiscal_rules()
        tax_rate = max(0.0, min(1.0, _fixed(fiscal_rules.get("universal_tax_rate_fraction_of_taxable_output", 0.10), 0.10)))
        collector_administration = self._state_administration_realization(state)
        plans: list[dict[str, Any]] = []
        source_cache: dict[str, tuple[str, dict[str, Any]]] = {}
        for native, location_ref, local_row in self._controlled_demographic_population_rows(state):
            site = territory.get("sites", {}).get(location_ref, {}) if isinstance(territory, Mapping) else {}
            if native not in source_cache:
                source_cache[native] = self._private_economy(native)
            _ep, eco = source_cache[native]
            try:
                _regional_ref, local_eco = self._local_economy_region(native, eco, str(location_ref))
            except ValueError:
                continue
            production = local_eco.get("production_runtime", {}) if isinstance(local_eco, Mapping) else {}
            taxable_output = max(0, int(production.get("last_taxable_output_value_silver", 0))) if isinstance(production, Mapping) else 0
            if taxable_output <= 0:
                continue
            governance = site.get("governance") if isinstance(site, Mapping) and isinstance(site.get("governance"), Mapping) else None
            compliance = max(0.0, min(1.0, _fixed(governance.get("tax_compliance", 100), 100) / 100.0 if governance else 1.0))
            realization = 1.0 if native == state else foreign_realization
            due = max(0, int(round(taxable_output * tax_rate * collector_administration * compliance * realization)))
            if due <= 0:
                continue
            current_population = max(0, int(self._local_taxable_civilian_population(local_row)))
            private_owner_ref = self._private_site_owner(str(location_ref))
            plans.append({
                "location_ref": str(location_ref),
                "native_state": native,
                "controller_state": state,
                "source_private_economy_ref": f"private_economy_{native}",
                "payer_house_ref": private_owner_ref,
                "due_silver": due,
                "universal_tax_rate": round(tax_rate, 6),
                "taxable_output_value_silver": taxable_output,
                "tax_compliance": round(compliance, 4),
                "realization_factor": round(realization, 4),
                "local_population_living": current_population,
                "collector_administration_realization": round(collector_administration, 4),
                "occupation": native != state,
            })
        return plans

    def _occupation_garrison_strength(self, state: str, location_ref: str) -> int:
        """Count exact state-force personnel physically assigned at the occupied site."""
        force = self.read(f"state/forces/state-{state}.json")
        allocated = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
        total = 0
        for formation_ref in sorted(str(ref) for ref in allocated):
            try:
                _path, formation = self._load_formation(formation_ref)
            except ValueError:
                continue
            if str(formation.get("location_ref")) == location_ref:
                total += max(0, int(formation.get("personnel", 0)))
        return total

    def _occupation_population_estimate(self, location_ref: str) -> tuple[str | None, int]:
        native = self._native_site_state(location_ref)
        if native is None:
            return None, 0
        _path, _pop, row = self._local_population_row(native, location_ref)
        # Garrison burden follows people physically tied to the locality, including
        # active rebels and displaced locals, while soldiers serving elsewhere are
        # not counted as civilians requiring occupation control.
        local = max(0, int(row.get("civilian_population", 0))) + max(0, int(row.get("rebel_military", 0))) + max(0, int(row.get("displaced", 0)))
        return native, local

    @staticmethod
    def _occupation_revolt_refs(location_ref: str) -> dict[str, str]:
        token = hashlib.sha256(str(location_ref).encode("utf-8")).hexdigest()[:12]
        return {
            "faction_ref": f"faction_occupation_revolt_{token}",
            "force_ref": f"force_occupation_revolt_{token}",
            "formation_ref": f"formation_occupation_revolt_{token}",
            "operation_ref": f"operation_occupation_revolt_{token}",
            "leader_ref": f"char_occupation_revolt_leader_{token}",
        }

    def _ensure_occupation_rebel_force(
        self,
        *,
        location_ref: str,
        native_state: str,
        controller_state: str,
        local_population: int,
        governance: dict[str, Any],
        at: str,
    ) -> dict[str, Any]:
        """Materialize one conserved local rebel actor when scalar resistance becomes war.

        Resistance alone remains a political condition.  Crossing the registered
        revolt threshold converts some exact local civilians into a persistent rebel
        force and formation.  No bodies, silver, food or military equipment are
        created by this transition.  The force can therefore be contacted and fought
        by the normal formation/battle machinery instead of existing only as a scalar.
        """
        refs = self._occupation_revolt_refs(location_ref)
        force_existing = self.read_optional(self.owner_path(refs["force_ref"])) if refs["force_ref"] in self.read("state/index/owner-index.json").get("owners", {}) else None
        if isinstance(force_existing, Mapping):
            force = copy.deepcopy(dict(force_existing))
            formation = self.read_optional(self.owner_path(refs["formation_ref"])) if refs["formation_ref"] in self.read("state/index/owner-index.json").get("owners", {}) else None
            return {
                **refs,
                "personnel": max(0, int(force.get("headcount", 0))),
                "formation_personnel": max(0, int(formation.get("personnel", 0))) if isinstance(formation, Mapping) else 0,
                "created": False,
            }

        rules = self._civil_rules().get("occupation", {})
        population_path = f"state/population/{native_state}.json"
        population = copy.deepcopy(self.read(population_path))
        _lp, population, local_row = self._local_population_row(native_state, location_ref, population)
        agricultural = min(
            max(0, int(population.get("strata", {}).get("agricultural", 0))),
            max(0, int(local_row.get("agricultural_available", 0))),
            max(0, int(local_row.get("civilian_population", 0))),
        )
        resistance = max(0, min(100, int(governance.get("resistance", 0))))
        fraction = max(0.0001, min(0.08, _fixed(rules.get("revolt_mobilization_fraction", 0.004), 0.004)))
        elite_opposition = max(0.0, (50.0 - float(governance.get("elite_cooperation", 50))) / 100.0)
        displacement_pressure = max(0.0, min(1.0, float(governance.get("displacement_pressure", 0)) / 100.0))
        support_factor = max(0.05, (resistance / 100.0) ** 1.35 + elite_opposition * 0.35 + displacement_pressure * 0.20)
        desired = int(math.floor(max(0, local_population) * fraction * support_factor))
        # Revolt size is capacity-derived.  The local population and support base are
        # the bounds; there is no universal 6,000-person uprising ceiling.
        personnel = min(agricultural, max(1, desired) if agricultural > 0 else 0)
        if personnel <= 0:
            return {**refs, "personnel": 0, "formation_personnel": 0, "created": False, "blocked_reason": "no conserved civilian manpower is available for revolt mobilization"}

        population.setdefault("strata", {})["agricultural"] = int(population["strata"].get("agricultural", 0)) - personnel
        population["strata"]["rebel_military"] = int(population["strata"].get("rebel_military", 0)) + personnel
        moved_local = self._consume_local_recruitment(population, native_state, location_ref, personnel, service_key="rebel_military", source_stratum="agricultural", service_owner_ref=refs["force_ref"])
        if moved_local != personnel:
            raise ValueError("revolt mobilization exceeded the locality's conserved civilian manpower")

        faction_path = f"state/factions/{refs['faction_ref']}.json"
        controller_ref = controller_state if controller_state.startswith(("state_", "polity_")) else f"state_{controller_state}"
        faction = {
            "schema": "sword-faction-agenda",
            "owner_id": refs["faction_ref"],
            "name": f"Local Revolt at {location_ref}",
            "status": "active_revolt",
            "goals": [
                "end foreign occupation at the local site",
                "preserve local manpower, food access, and supporting routes",
            ],
            "knowledge": [],
            "resources": {
                "local_support": resistance,
                "agents": max(1, personnel // 250),
                "warband_capacity": personnel,
                "silver": 0,
            },
            "relationships": {
                controller_ref: {"kind": "armed_revolt", "strength": 100, "sentiment": -100},
                f"state_{native_state}": {"kind": "homeland_affinity", "strength": max(25, resistance)},
            },
            "origin": {
                "location_ref": location_ref,
                "population_ref": f"population_{native_state}",
                "source_stratum": "agricultural",
                "mobilized_stratum": "rebel_military",
                "mobilized_at": at,
                "personnel": personnel,
            },
            "force_ref": refs["force_ref"],
            "formation_refs": [refs["formation_ref"]],
            "operation_ref": refs["operation_ref"],
            "representative_refs": [refs["leader_ref"]],
        }
        force_path = f"state/forces/{refs['force_ref']}.json"
        force = {
            "schema": "sword-force",
            "owner_id": refs["force_ref"],
            "owner_type": "force",
            "kind": "local_rebel_force",
            "administrative_owner": refs["faction_ref"],
            "population_source_ref": f"population_{native_state}",
            "population_service_stratum": "rebel_military",
            "source_location_ref": location_ref,
            "headcount": personnel,
            "authorized_strength": personnel,
            "available_by_role": {"line_infantry": personnel},
            "available_by_location": {location_ref: {"line_infantry": personnel}},
            "allocated_to_formations": {},
            "materialized_people": {},
            "materialized_assignments": {},
            "cohort_ledger": {
                "schema": "force-cohort-ledger",
                "cohorts": {},
            },
        }
        profiles = self.read("game/data/mil/recruitment-cohort-profiles.json")
        record_recruitment_cohort(
            force,
            role="line_infantry",
            count=personnel,
            location_ref=location_ref,
            source_population_ref=f"population_{native_state}",
            source_stratum="agricultural",
            recruited_at=at,
            profile_registry=profiles,
            provenance_ref=refs["operation_ref"],
            intake_ref=refs["force_ref"],
        )
        self._take_force_personnel(force, "line_infantry", personnel, location_ref)
        force["allocated_to_formations"][refs["formation_ref"]] = {"role": "line_infantry", "personnel": personnel}
        cohort_slices = take_reserve_slices(
            force,
            role="line_infantry",
            count=personnel,
            location_ref=location_ref,
            formation_ref=refs["formation_ref"],
        )
        formation_path = f"state/formations/{refs['formation_ref']}.json"
        formation = {
            "schema": "sword-formation",
            "formation_ref": refs["formation_ref"],
            "name": f"Local Insurgent Bands at {location_ref}",
            "owner_force_ref": refs["force_ref"],
            "administrative_owner": refs["faction_ref"],
            "command_authority": refs["faction_ref"],
            "commander_ref": refs["leader_ref"],
            "personnel": personnel,
            "composition": {"line_infantry": personnel},
            "cohort_composition": cohort_slices,
            "location_ref": location_ref,
            "readiness": max(20, min(65, 25 + resistance // 3)),
            "morale": max(45, min(85, 45 + resistance // 2)),
            "cohesion": max(15, min(55, 15 + resistance // 3)),
            "fatigue": 0,
            "training_progress": 5,
            "equipment_completeness": "0.0000",
            "equipment_units_by_role": {"line_infantry": 0},
            "mobilized": True,
            "status": "mobilized",
            "experience": "irregular",
            "logistics": {"food_kg": 0, "fodder_kg": 0, "war_arrows": 0, "war_bolts": 0},
            "mounts": {},
            "provenance": {
                "population_ref": f"population_{native_state}",
                "mobilized_stratum": "rebel_military",
                "mobilized_at": at,
                "basis": "open occupation revolt converted conserved local civilians into an exact irregular formation",
            },
        }
        current_year = int(str(at).split("-BCE-", 1)[0]) if "-BCE-" in str(at) else 245
        leader_age = 24 + int(hashlib.sha256((refs["leader_ref"] + "|age").encode()).hexdigest()[:4], 16) % 18
        leader_path = f"state/char/{refs['leader_ref'].replace('char_', '').replace('_', '-')}.json"
        leader = {
            "schema": "sword-materialized-person",
            "owner_id": refs["leader_ref"],
            "owner_type": "character",
            "id": refs["leader_ref"],
            "name": f"Local Rebel Leader at {location_ref}",
            "birth_date": f"{current_year + leader_age}-BCE-01-01",
            "status": "active",
            "life_status": "active",
            "health_status": "healthy",
            "current_location": location_ref,
            "state": native_state,
            "attributes": {},
            "skills": {},
            "aptitude": {},
            "development_state": {"completed_reviews": 0, "maintenance_credit": 0, "training_credit": 0},
            "population_provenance": {
                "population_ref": f"population_{native_state}",
                "service_stratum": "rebel_military",
                "force_ref": refs["force_ref"],
                "formation_ref": refs["formation_ref"],
                "materialized_at": at,
                "principle": "this exact leader reclassifies one already conserved revolt cohort body",
            },
        }
        if not hasattr(self, "_ct_materialize_from_formation"):
            raise ValueError("rebel leader materialization requires cohort transaction support")
        self._ct_materialize_from_formation(
            force,
            formation,
            role="line_infantry",
            person_ref=refs["leader_ref"],
            person=leader,
        )
        force["materialized_people"][refs["leader_ref"]] = 1
        force["materialized_assignments"][refs["leader_ref"]] = {
            "formation_ref": refs["formation_ref"],
            "role": "line_infantry",
            "combat_role": "commander",
            "personnel": 1,
        }
        validate_cohort_ledger(force)
        operation_path = f"state/operations/{refs['operation_ref']}.json"
        operation = {
            "schema": "sword-operation",
            "owner_id": refs["operation_ref"],
            "operation_ref": refs["operation_ref"],
            "status": "active",
            "kind": "local_insurgency",
            "objective": f"contest foreign occupation at {location_ref}",
            "location_ref": location_ref,
            "formation_refs": [refs["formation_ref"]],
            "administrative_authorities": [refs["faction_ref"]],
            "administrative_authority": refs["faction_ref"],
            "opponent_ref": controller_ref,
            "created_at": at,
            "status_history": [{"status": "active", "at": at, "basis": "occupation revolt materialized into conserved armed resistance"}],
            "victory_criteria": ["foreign occupation ends or governing authority withdraws"],
            "termination_criteria": ["rebel force is defeated, demobilized, or reaches a political settlement"],
        }
        operation_index = copy.deepcopy(self.read("state/operations/index.json"))
        if refs["operation_ref"] in operation_index.setdefault("operations", {}):
            raise ValueError("occupation revolt operation identity already exists without its force authority")

        self.put(population_path, population)
        self.put(faction_path, faction)
        self.put(force_path, force)
        self.put(formation_path, formation)
        self.put(leader_path, leader)
        self.put(operation_path, operation)
        operation_index["operations"][refs["operation_ref"]] = operation_path
        self.put("state/operations/index.json", operation_index)
        self._register_owner(refs["faction_ref"], faction_path)
        self._register_owner(refs["force_ref"], force_path)
        self._register_owner(refs["formation_ref"], formation_path)
        self._register_owner(refs["leader_ref"], leader_path)
        self._register_owner(refs["operation_ref"], operation_path)
        self._index_formation_location(refs["formation_ref"], None, location_ref)
        self._assign_commander_index(refs["leader_ref"], refs["formation_ref"])
        self._ensure_person_life_host(refs["leader_ref"], CampaignTime.parse(at))
        return {**refs, "personnel": personnel, "formation_personnel": personnel, "created": True}

    def _support_occupation_rebel_force(self, *, refs: Mapping[str, Any], native_state: str, at: str) -> dict[str, int]:
        """Move bounded local food/cash into an already materialized revolt."""
        force_ref = str(refs.get("force_ref", ""))
        formation_ref = str(refs.get("formation_ref", ""))
        faction_ref = str(refs.get("faction_ref", ""))
        if not force_ref or not formation_ref or not faction_ref:
            return {"food_kg": 0, "silver": 0}
        try:
            force_path = self.owner_path(force_ref)
            formation_path = self.owner_path(formation_ref)
            faction_path = self.owner_path(faction_ref)
        except (KeyError, ValueError):
            return {"food_kg": 0, "silver": 0}
        force = copy.deepcopy(self.read(force_path))
        formation = copy.deepcopy(self.read(formation_path))
        faction = copy.deepcopy(self.read(faction_path))
        if int(force.get("headcount", 0)) <= 0 or int(formation.get("personnel", 0)) <= 0:
            return {"food_kg": 0, "silver": 0}
        ep, eco = self._private_economy(native_state)
        location_ref = str(formation.get("location_ref", ""))
        try:
            site_ref, local_eco = self._local_economy_region(native_state, eco, location_ref)
        except ValueError:
            site_ref, local_eco = "", eco
        rules = self._civil_rules().get("occupation", {})
        commodities = local_eco.setdefault("commodity_stock", {})
        food_need = max(0, int(formation.get("personnel", 0)) * int(rules.get("revolt_food_support_kg_per_fighter_review", 1)))
        food = min(food_need, max(0, int(commodities.get("grain_kg", 0))))
        silver_cap = max(0, int(rules.get("revolt_silver_support_per_fighter_review", 1))) * max(0, int(force.get("headcount", 0)))
        silver = min(silver_cap, max(0, int(local_eco.get("cash_silver", 0))))
        if food:
            commodities["grain_kg"] = int(commodities.get("grain_kg", 0)) - food
            formation.setdefault("logistics", {})["food_kg"] = int(formation.get("logistics", {}).get("food_kg", 0)) + food
        if silver:
            local_eco["cash_silver"] = int(local_eco.get("cash_silver", 0)) - silver
            faction.setdefault("resources", {})["silver"] = int(faction.get("resources", {}).get("silver", 0)) + silver
        if food or silver:
            history = faction.setdefault("support_history", [])
            history.append({"at": at, "source_ref": f"private_economy_{native_state}", "regional_source_ref": site_ref or None, "food_kg": food, "silver": silver, "basis": "bounded local support transferred from exact regional private economy"})
            del history[:-24]
            self._sync_local_economy_aggregate(eco)
            self._write_private_economy(ep, eco)
            self.put(formation_path, formation)
            self.put(faction_path, faction)
        return {"food_kg": food, "silver": silver}

    def _contain_occupation_rebel_force(self, *, refs: Mapping[str, Any], native_state: str, at: str) -> int:
        """Demobilize surviving insurgents only after the revolt is mechanically contained."""
        force_ref = str(refs.get("force_ref", ""))
        formation_ref = str(refs.get("formation_ref", ""))
        faction_ref = str(refs.get("faction_ref", ""))
        operation_ref = str(refs.get("operation_ref", ""))
        try:
            force_path = self.owner_path(force_ref)
            formation_path = self.owner_path(formation_ref)
            faction_path = self.owner_path(faction_ref)
            operation_path = self.owner_path(operation_ref)
        except ValueError:
            return 0
        force = copy.deepcopy(self.read(force_path))
        formation = copy.deepcopy(self.read(formation_path))
        faction = copy.deepcopy(self.read(faction_path))
        operation = copy.deepcopy(self.read(operation_path))
        survivors = max(0, int(force.get("headcount", 0)))
        if survivors:
            pop_path = f"state/population/{native_state}.json"
            pop = copy.deepcopy(self.read(pop_path))
            service = max(0, int(pop.get("strata", {}).get("rebel_military", 0)))
            returned = min(service, survivors)
            pop["strata"]["rebel_military"] = service - returned
            pop["strata"]["agricultural"] = int(pop["strata"].get("agricultural", 0)) + returned
            origin_location = str(formation.get("location_ref", ""))
            if origin_location:
                released = self._release_local_service(pop, native_state, origin_location, returned, service_key="rebel_military", to_agricultural=True, service_owner_ref=force_ref)
                if released != returned:
                    raise ValueError("rebel demobilization exceeded conserved local rebel manpower")
            self.put(pop_path, pop)
        leader_ref = str(refs.get("leader_ref") or next(iter(faction.get("representative_refs", [])), ""))
        if leader_ref:
            self._release_commander_index(leader_ref, formation_ref)
            try:
                leader_path, leader0 = self.owner(leader_ref)
                leader = copy.deepcopy(leader0)
                if self._person_health(leader) != "dead":
                    leader["service_status"] = "demobilized_after_contained_revolt"
                    leader["demobilized_at"] = at
                    leader["population_provenance"] = {
                        **dict(leader.get("population_provenance", {})),
                        "population_ref": f"population_{native_state}",
                        "service_stratum": "agricultural",
                        "reclassified_at": at,
                        "principle": "surviving exact rebel leader returned to the same conserved local population on demobilization",
                    }
                    self.put(leader_path, leader)
            except (KeyError, ValueError, FileNotFoundError):
                pass
        formation["personnel"] = 0
        formation["composition"] = {"line_infantry": 0}
        formation["cohort_composition"] = []
        formation["commander_ref"] = None
        formation["status"] = "dissolved"
        formation["mobilized"] = False
        formation["dissolved_at"] = at
        force["headcount"] = 0
        force["available_by_role"] = {"line_infantry": 0}
        force["available_by_location"] = {str(formation.get("location_ref", "")): {"line_infantry": 0}}
        force["allocated_to_formations"] = {}
        force["materialized_people"] = {}
        force["materialized_assignments"] = {}
        if isinstance(force.get("cohort_ledger"), Mapping):
            force["demobilized_cohort_snapshot"] = copy.deepcopy(force["cohort_ledger"])
            force["cohort_ledger"] = {
                "schema": "force-cohort-ledger",
                "cohorts": {},
            }
            validate_cohort_ledger(force)
        force["status"] = "demobilized"
        force["demobilized_at"] = at
        faction["status"] = "suppressed_or_demobilized"
        faction["demobilized_at"] = at
        operation["status"] = "completed"
        operation.setdefault("status_history", []).append({"status": "completed", "at": at, "basis": "occupation revolt contained and surviving irregulars demobilized"})
        self.put(force_path, force)
        self.put(formation_path, formation)
        self.put(faction_path, faction)
        self.put(operation_path, operation)
        self._index_formation_location(formation_ref, str(formation.get("location_ref", "")), None)
        return survivors

    def _occupation_initialize(self, loc: str, controller: str, old_controller: str, at: str, evidence_ref: str | None) -> None:
        terr = copy.deepcopy(self.read("state/territory/control.json"))
        site = terr.get("sites", {}).get(loc)
        if not isinstance(site, dict):
            return
        rules = self._civil_rules().get("occupation", {})
        gov = site.setdefault("governance", {})
        if str(gov.get("military_controller")) == controller and gov.get("occupation_started_at"):
            return
        gov.update({
            "military_controller": controller,
            "occupation_started_at": at,
            "administration": int(rules.get("initial_administration", 20)),
            "elite_cooperation": int(rules.get("initial_elite_cooperation", 25)),
            "civilian_loyalty": int(rules.get("initial_civilian_loyalty", 20)),
            "resistance": int(rules.get("initial_resistance", 70)),
            "tax_compliance": int(rules.get("initial_tax_compliance", 20)),
            "recruitment_access": int(rules.get("initial_recruitment_access", 10)),
            "displacement_pressure": int(rules.get("initial_displacement_pressure", 18)),
            "disease_risk": int(rules.get("initial_disease_risk", 12)),
            "food_security": int(rules.get("initial_food_security", 50)),
            "status": "military_occupation",
            "evidence_ref": evidence_ref,
        })
        claims = site.setdefault("legal_claims", {})
        claims.setdefault(old_controller, {"strength": 100, "basis": "pre-conquest administration"})
        claims[controller] = {"strength": max(25, int(claims.get(controller, {}).get("strength", 0))), "basis": "military occupation; legal integration incomplete"}
        self.put("state/territory/control.json", terr)
        new_state = controller.replace("state_", "")
        old_state = old_controller.replace("state_", "")
        for state, add in ((new_state, True), (old_state, False)):
            path = f"state/states/{state}.json"
            doc = self.read_optional(path)
            if not isinstance(doc, Mapping):
                continue
            sd = copy.deepcopy(dict(doc))
            controlled = sd.setdefault("territorial_control", [])
            if add and loc not in controlled:
                controlled.append(loc)
            if not add and loc in controlled:
                controlled.remove(loc)
            sd["territorial_control"] = sorted(set(str(x) for x in controlled))
            self.put(path, sd)
        # A dynamic polity's territorial list is an exact sovereignty index, not a
        # replacement for the territorial-control owner. Keep it synchronized when
        # conquest changes either side of a polity-held site.
        for polity_ref, add in ((controller, True), (old_controller, False)):
            if not polity_ref.startswith("polity_"):
                continue
            try:
                polity_path = self.owner_path(polity_ref); polity = copy.deepcopy(self.read(polity_path))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            controlled = [str(x) for x in polity.setdefault("occupied_site_refs", []) if isinstance(x, str)]
            if add and loc not in controlled:
                controlled.append(loc)
            if not add:
                controlled = [ref for ref in controlled if ref != loc]
            polity["occupied_site_refs"] = sorted(set(controlled))
            self.put(polity_path, polity)

    def _occupation_policy_effects(self, governance: Mapping[str, Any]) -> dict[str, float]:
        """Translate persisted occupation policy into bounded causal modifiers."""
        policy = governance.get("occupation_policy", {}) if isinstance(governance.get("occupation_policy"), Mapping) else {}
        values = {str(k): str(v.get("value", v) if isinstance(v, Mapping) else v).strip().lower() for k, v in policy.items()}
        out = {
            "budget_multiplier": 1.0, "administration_multiplier": 1.0,
            "suppression_bonus": 0.0, "resistance_delta": 0.0, "elite_delta": 0.0,
            "loyalty_delta": 0.0, "tax_compliance_delta": 0.0,
            "recruitment_access_delta": 0.0, "food_security_delta": 0.0,
            "displacement_delta": 0.0,
        }
        security = values.get("security_posture", "")
        if any(x in security for x in ("martial", "severe", "strict", "hard")):
            out.update({"budget_multiplier": out["budget_multiplier"] * 1.18, "suppression_bonus": 4.0, "resistance_delta": 2.0, "elite_delta": -1.0, "loyalty_delta": -2.0, "displacement_delta": 1.0})
        elif any(x in security for x in ("concili", "light", "community", "restrained")):
            out.update({"budget_multiplier": out["budget_multiplier"] * 0.92, "suppression_bonus": -1.0, "resistance_delta": -2.0, "elite_delta": 1.0, "loyalty_delta": 1.0})
        elite = values.get("elite_policy", "")
        if any(x in elite for x in ("retain", "cooper", "concili", "respect")):
            out["elite_delta"] += 3.0; out["administration_multiplier"] *= 1.08; out["resistance_delta"] -= 1.0
        elif any(x in elite for x in ("purge", "replace", "confisc", "hostile")):
            out["elite_delta"] -= 4.0; out["administration_multiplier"] *= 0.90; out["resistance_delta"] += 3.0
        recruit = values.get("recruitment_policy", "")
        if any(x in recruit for x in ("suspend", "none", "prohibit")):
            out["recruitment_access_delta"] -= 100.0; out["resistance_delta"] -= 1.0
        elif any(x in recruit for x in ("voluntary", "light")):
            out["recruitment_access_delta"] -= 10.0; out["loyalty_delta"] += 1.0
        elif any(x in recruit for x in ("levy", "heavy", "forced", "conscription")):
            out["recruitment_access_delta"] += 12.0; out["resistance_delta"] += 4.0; out["loyalty_delta"] -= 3.0
        relief = values.get("relief_policy", "")
        if any(x in relief for x in ("generous", "relief", "aid", "rebuild")):
            out["budget_multiplier"] *= 1.22; out["food_security_delta"] += 5.0; out["resistance_delta"] -= 2.0; out["loyalty_delta"] += 3.0; out["displacement_delta"] -= 2.0
        elif any(x in relief for x in ("austere", "none", "minimal")):
            out["budget_multiplier"] *= 0.88; out["food_security_delta"] -= 3.0; out["resistance_delta"] += 2.0; out["loyalty_delta"] -= 2.0; out["displacement_delta"] += 1.0
        out["values"] = values
        return out

    def _governor_effects(self, polity: Mapping[str, Any], location_ref: str) -> dict[str, Any]:
        appointment = polity.get("governors", {}).get(location_ref) if isinstance(polity.get("governors"), Mapping) else None
        if not isinstance(appointment, Mapping):
            return {"governor_ref": None, "administration_multiplier": 1.0, "elite_delta": 0, "resistance_delta": 0, "loyalty_delta": 0}
        person_ref = str(appointment.get("person_ref", ""))
        if not person_ref:
            return {"governor_ref": None, "administration_multiplier": 1.0, "elite_delta": 0, "resistance_delta": 0, "loyalty_delta": 0}
        try:
            person = self.read(self.owner_path(person_ref))
        except (KeyError, ValueError, FileNotFoundError):
            return {"governor_ref": person_ref, "administration_multiplier": 0.9, "elite_delta": -1, "resistance_delta": 1, "loyalty_delta": -1}
        skills = merged_skill_map(person) if isinstance(person, Mapping) else {}
        attrs = person.get("attributes", {}) if isinstance(person, Mapping) and isinstance(person.get("attributes"), Mapping) else {}
        values = [max(0.0, _fixed(skills.get(k, 0), 0)) for k in ("Governance", "Law", "Diplomacy", "Leadership")]
        presence = max(0.0, _fixed(attrs.get("Presence", 0), 0))
        score = (sum(values) + presence) / max(1, len(values) + 1)
        familiarity = 0.05 if location_ref and location_ref in str(person.get("location_scope", "")) else 0.0
        # Preserve the historical 0..200 response exactly, then continue with
        # bounded organizational diminishing returns instead of making stat 201
        # mechanically identical to stat 200. Institutions still constrain how
        # much one exceptional governor can multiply a whole administration.
        if score <= 200.0:
            capability = score / 200.0
        else:
            capability = 1.0 + 0.35 * (1.0 - math.exp(-(score - 200.0) / 150.0))
        normalized = max(0.0, min(1.40, capability + familiarity))
        return {
            "governor_ref": person_ref,
            "score": round(score, 2),
            "administration_multiplier": round(0.72 + normalized * 0.62, 4),
            "elite_delta": int(round((normalized - 0.5) * 4)),
            "resistance_delta": int(round((0.5 - normalized) * 4)),
            "loyalty_delta": int(round((normalized - 0.5) * 3)),
        }

    def _settle_occupation_administration(self, state: str, occurrences: int, at: str) -> None:
        """Settle contested occupation using exact garrison, budget and local economy.

        Time alone never integrates conquered territory. Administrative progress is
        conditioned by physical state troops, the regional administration office,
        paid occupation costs, local elite cooperation, food security and whether
        the former controller still has an adjacent support route. Severe neglect can
        push a site into open revolt, suspending taxation and recruitment access.
        """
        if occurrences <= 0:
            return
        terr = copy.deepcopy(self.read("state/territory/control.json"))
        rules = self._civil_rules().get("occupation", {})
        changed = False
        state_path = f"state/states/{state}.json"
        state_doc = copy.deepcopy(self.read(state_path))
        admin_inst = self.read(self.owner_path(f"inst_{state}_regional_administration"))
        office_capacity = max(1, int(admin_inst.get("capacity", 1)))
        routes = self.read("game/data/world/routes.json").get("routes", [])
        for loc, site in terr.get("sites", {}).items():
            if not isinstance(site, dict) or str(site.get("controller")) != f"state_{state}":
                continue
            gov = site.get("governance")
            if not isinstance(gov, dict) or gov.get("status") not in {"military_occupation", "integrating", "open_revolt"}:
                continue
            native_state, local_population = self._occupation_population_estimate(str(loc))
            if native_state is None or native_state == state or local_population <= 0:
                continue

            garrison = self._occupation_garrison_strength(state, str(loc))
            required_per_thousand = max(0.1, _fixed(rules.get("garrison_personnel_per_thousand_residents", 2.0), 2.0))
            required_garrison = max(100, int(math.ceil(local_population / 1000.0 * required_per_thousand)))
            garrison_factor = max(0.0, min(1.5, garrison / required_garrison))

            budget_rate = max(0.0, _fixed(rules.get("administration_silver_per_thousand_residents_per_review", 20.0), 20.0))
            budget_due = max(0, int(math.ceil(local_population / 1000.0 * budget_rate * occurrences)))
            budget_paid = min(budget_due, max(0, int(state_doc.get("treasury_silver", 0))))
            state_doc["treasury_silver"] = max(0, int(state_doc.get("treasury_silver", 0)) - budget_paid)
            budget_factor = 1.0 if budget_due <= 0 else budget_paid / budget_due
            local_ep, local_eco = self._private_economy(native_state)
            _local_site, local_region = self._local_economy_region(native_state, local_eco, str(loc))
            local_region["cash_silver"] = int(local_region.get("cash_silver", 0)) + budget_paid
            self._sync_local_economy_aggregate(local_eco)
            self._write_private_economy(local_ep, local_eco)

            old_controller = f"state_{native_state}"
            adjacent_support = 0
            for route in routes if isinstance(routes, list) else []:
                if not isinstance(route, Mapping):
                    continue
                a = str(route.get("a", route.get("from", "")))
                b = str(route.get("b", route.get("to", "")))
                if str(loc) not in {a, b}:
                    continue
                other = b if a == str(loc) else a
                other_site = terr.get("sites", {}).get(other)
                if isinstance(other_site, Mapping) and str(other_site.get("controller")) == old_controller:
                    adjacent_support += 1

            elite = int(gov.get("elite_cooperation", 0))
            resistance = int(gov.get("resistance", 0))
            food_security = int(gov.get("food_security", 50))
            displacement = int(gov.get("displacement_pressure", 0))
            disease = int(gov.get("disease_risk", 0))
            office_factor = max(0.25, min(1.5, office_capacity / 75.0))
            elite_factor = max(0.25, min(1.25, (elite + 25) / 100.0))
            support_pressure = min(12, adjacent_support * int(rules.get("adjacent_enemy_support_pressure", 3)))
            shortage_pressure = max(0, (55 - food_security) // 8)
            security_pressure = max(0, int(round((1.0 - min(1.0, garrison_factor)) * 12)))
            budget_pressure = max(0, int(round((1.0 - budget_factor) * 10)))

            base_gain = max(1, int(rules.get("regional_administration_gain_per_review", 4))) * occurrences
            progress_factor = office_factor * min(1.0, garrison_factor) * budget_factor * elite_factor
            admin_delta = int(round(base_gain * progress_factor))
            destabilization = support_pressure + shortage_pressure + security_pressure + budget_pressure
            if admin_delta <= 0 or destabilization >= 12:
                gov["administration"] = _clamp(int(gov.get("administration", 0)) - max(1, destabilization // 8))
            else:
                gov["administration"] = _clamp(int(gov.get("administration", 0)) + admin_delta)

            cooperation_delta = max(-3, min(3, int(round((budget_factor + min(1.0, garrison_factor) - 1.0) * 2))))
            if resistance >= 70:
                cooperation_delta -= 1
            gov["elite_cooperation"] = _clamp(elite + cooperation_delta * occurrences)

            suppression = int(round(max(0.0, min(1.5, garrison_factor)) * 3 + budget_factor * 2 + max(0, gov["elite_cooperation"] - 40) / 25.0))
            resistance_delta = destabilization - suppression
            gov["resistance"] = _clamp(resistance + resistance_delta)

            loyalty_delta = int(round((gov["administration"] - 50) / 25.0 + (gov["elite_cooperation"] - 50) / 30.0 - gov["resistance"] / 45.0))
            gov["civilian_loyalty"] = _clamp(int(gov.get("civilian_loyalty", 0)) + loyalty_delta)

            if gov["resistance"] >= 60:
                displacement = _clamp(displacement + max(1, 1 + support_pressure // 4))
                disease = _clamp(disease + max(1, shortage_pressure // 2))
                food_security = _clamp(food_security - max(1, shortage_pressure + security_pressure // 3))
            else:
                displacement = _clamp(displacement - max(1, admin_delta // 3))
                disease = _clamp(disease - max(1, admin_delta // 4))
                food_security = _clamp(food_security + max(1, admin_delta // 3))
            gov["displacement_pressure"] = displacement
            gov["disease_risk"] = disease
            gov["food_security"] = food_security

            revolt_threshold = int(rules.get("open_revolt_resistance_threshold", 88))
            revolt_garrison_ceiling = _fixed(rules.get("open_revolt_max_garrison_factor", 0.65), 0.65)
            revolt_threat_ref = f"occupation_revolt:{loc}"
            known_threats = state_doc.setdefault("known_threats", {})
            if gov["resistance"] >= revolt_threshold and garrison_factor <= revolt_garrison_ceiling:
                rebel = self._ensure_occupation_rebel_force(
                    location_ref=str(loc),
                    native_state=native_state,
                    controller_state=state,
                    local_population=local_population,
                    governance=gov,
                    at=at,
                )
                support = self._support_occupation_rebel_force(refs=rebel, native_state=native_state, at=at)
                gov["status"] = "open_revolt"
                gov["tax_compliance"] = 0
                gov["recruitment_access"] = 0
                prior_revolt = gov.get("revolt") if isinstance(gov.get("revolt"), Mapping) else {}
                gov["revolt"] = {
                    "active": True,
                    "since": prior_revolt.get("since", at),
                    "initial_personnel": int(prior_revolt.get("initial_personnel", rebel.get("personnel", 0))),
                    "basis": "resistance exceeded state control capacity while the exact occupation garrison was inadequate",
                    "adjacent_former_controller_routes": adjacent_support,
                    "faction_ref": rebel.get("faction_ref"),
                    "force_ref": rebel.get("force_ref"),
                    "formation_refs": [rebel.get("formation_ref")] if rebel.get("formation_ref") else [],
                    "operation_ref": rebel.get("operation_ref"),
                    "personnel": int(rebel.get("personnel", 0)),
                    "local_support_transfer": support,
                }
                known_threats[revolt_threat_ref] = {
                    "severity": max(55, min(100, int(gov["resistance"]))),
                    "kind": "occupation_revolt",
                    "location_ref": str(loc),
                    "source_state": native_state,
                    "observed_at": at,
                    "provenance": "exact occupied-site governance crossed the registered revolt threshold",
                    "evidence_ref": gov.get("evidence_ref"),
                    "faction_ref": rebel.get("faction_ref"),
                    "force_ref": rebel.get("force_ref"),
                    "formation_refs": [rebel.get("formation_ref")] if rebel.get("formation_ref") else [],
                    "operation_ref": rebel.get("operation_ref"),
                }
            else:
                revolt_doc = gov.get("revolt") if isinstance(gov.get("revolt"), Mapping) else {}
                rebel_force_ref = str(revolt_doc.get("force_ref", ""))
                rebel_personnel = 0
                if rebel_force_ref:
                    try:
                        rebel_force = self.read(self.owner_path(rebel_force_ref))
                        rebel_personnel = max(0, int(rebel_force.get("headcount", 0)))
                    except (KeyError, ValueError, FileNotFoundError):
                        rebel_personnel = 0
                initial_rebels = max(1, int(revolt_doc.get("initial_personnel", revolt_doc.get("personnel", rebel_personnel or 1))))
                containment_ceiling = max(int(rules.get("revolt_containment_survivor_floor", 50)), int(math.floor(initial_rebels * _fixed(rules.get("revolt_containment_survivor_fraction", 0.10), 0.10))))
                can_contain_revolt = (
                    gov.get("status") == "open_revolt"
                    and gov["resistance"] <= int(rules.get("revolt_contained_resistance_threshold", 55))
                    and garrison_factor >= 1.0
                    and rebel_personnel <= containment_ceiling
                )
                if can_contain_revolt:
                    refs = {
                        "faction_ref": revolt_doc.get("faction_ref"),
                        "force_ref": revolt_doc.get("force_ref"),
                        "formation_ref": next(iter(revolt_doc.get("formation_refs", [])), None) if isinstance(revolt_doc.get("formation_refs"), list) else None,
                        "operation_ref": revolt_doc.get("operation_ref"),
                    }
                    demobilized = self._contain_occupation_rebel_force(refs=refs, native_state=native_state, at=at) if rebel_force_ref else 0
                    gov["status"] = "military_occupation"
                    gov["revolt"] = {**dict(revolt_doc), "active": False, "contained_at": at, "demobilized_survivors": demobilized}
                elif gov.get("status") == "open_revolt":
                    # A real rebel force cannot disappear merely because the scalar
                    # resistance score later drifts downward.  Until the force is
                    # militarily reduced or politically demobilized, revolt remains
                    # a live exact military problem and taxation/recruiting stay off.
                    gov["tax_compliance"] = 0
                    gov["recruitment_access"] = 0
                    if revolt_threat_ref in known_threats:
                        known_threats[revolt_threat_ref]["severity"] = max(45, min(100, int(gov.get("resistance", 0)) + min(25, rebel_personnel // 200)))
                if gov.get("status") != "open_revolt":
                    known_threats.pop(revolt_threat_ref, None)
                    gov["tax_compliance"] = _clamp(min(int(gov.get("administration", 0)), int(gov.get("elite_cooperation", 0)), max(0, 100 - int(gov.get("resistance", 0)) // 2)))
                    recruitment_ceiling = min(int(gov.get("civilian_loyalty", 0)), int(gov.get("administration", 0)), max(0, 100 - int(gov.get("resistance", 0))))
                    gov["recruitment_access"] = _clamp(min(80, recruitment_ceiling))

            gov["occupation_capacity"] = {
                "local_population_estimate": local_population,
                "garrison_personnel": garrison,
                "required_garrison_personnel": required_garrison,
                "garrison_factor": round(garrison_factor, 4),
                "administration_office_capacity": office_capacity,
                "budget_due_silver": budget_due,
                "budget_paid_silver": budget_paid,
                "budget_factor": round(budget_factor, 4),
                "adjacent_former_controller_routes": adjacent_support,
            }
            gov["last_administration_review"] = at
            if gov.get("status") != "open_revolt":
                if int(gov["administration"]) >= 70 and int(gov["resistance"]) <= 25:
                    gov["status"] = "integrating"
                if int(gov["administration"]) >= 90 and int(gov["civilian_loyalty"]) >= 65 and int(gov["resistance"]) <= 10:
                    gov["status"] = "civil_administration_established"
                    claim = site.setdefault("legal_claims", {}).setdefault(f"state_{state}", {})
                    claim["strength"] = max(70, int(claim.get("strength", 0)))
                    claim["basis"] = "sustained civil administration after occupation"
            changed = True
        if changed:
            self.put(state_path, state_doc)
            self.put("state/territory/control.json", terr)

    def _territorial_revenue_factor(self, state: str) -> float:
        base = max(1, int(self.read(f"state/states/{state}.json").get("normal_monthly_revenue_silver", 0)))
        due = sum(int(row.get("due_silver", 0)) for row in self._territorial_revenue_plan(state, 1))
        return max(0.0, due / base)

    def _reconcile_local_state_service_casualties(
        self, force_ref: str, cohort_losses: Mapping[str, Any], *, at: str, evidence_ref: str
    ) -> dict[str, dict[str, int]]:
        """Update the local-origin partition for state-force deaths without double-charging bodies."""
        if not force_ref.startswith("force_state_") or not isinstance(cohort_losses, Mapping):
            return {}
        force = self.read(self.owner_path(force_ref))
        owner_state = str(force.get("state", "")) if isinstance(force, Mapping) and str(force.get("service_class", "")) == "state_levy" else force_ref.removeprefix("force_state_")
        owner_state = owner_state.removeprefix("state_")
        cohorts = force.get("cohort_ledger", {}).get("cohorts", {}) if isinstance(force, Mapping) else {}
        grouped: dict[tuple[str, str, str], int] = {}
        for cohort_id, raw_loss in cohort_losses.items():
            loss = max(0, int(raw_loss)); cohort = cohorts.get(str(cohort_id)) if isinstance(cohorts, Mapping) else None
            origin = cohort.get("origin", {}) if isinstance(cohort, Mapping) else {}
            population_ref = str(origin.get("population_ref", "")) if isinstance(origin, Mapping) else ""
            location_ref = str(origin.get("source_location_ref", "")) if isinstance(origin, Mapping) else ""
            if loss <= 0 or not population_ref.startswith("population_") or not location_ref:
                continue
            native_state = population_ref.removeprefix("population_")
            service_key = "serving_native_military" if native_state == owner_state else "serving_foreign_military"
            grouped[(native_state, location_ref, service_key)] = grouped.get((native_state, location_ref, service_key), 0) + loss
        out: dict[str, dict[str, int]] = {}
        for (native_state, location_ref, service_key), count in sorted(grouped.items()):
            pop_path = f"state/population/{native_state}.json"; pop = copy.deepcopy(self.read(pop_path))
            applied = self._record_local_service_deaths(pop, native_state, location_ref, count, service_key=service_key, service_owner_ref=force_ref)
            if applied != count:
                # Older cohorts may predate the local ledger.  Fail closed only when
                # the ledger explicitly claims fewer bodies than the exact cohort loss.
                raise ValueError("state-force casualty exceeds conserved local service allocation")
            pop.setdefault("local_service_casualties", []).append({"at": at, "evidence_ref": evidence_ref, "serving_force_ref": force_ref, "location_ref": location_ref, "service_key": service_key, "deaths": count})
            pop["local_service_casualties"] = pop["local_service_casualties"][-32:]
            self.put(pop_path, pop)
            out.setdefault(native_state, {})[location_ref] = out.setdefault(native_state, {}).get(location_ref, 0) + count
        return out

    def _reconcile_private_service_casualties(self, force_ref: str, casualties: int, *, at: str, evidence_ref: str) -> dict[str, int]:
        """Reconcile House/personal force deaths against exact local service allocations."""
        casualties=max(0,int(casualties))
        if casualties<=0 or force_ref.startswith("force_state_") or force_ref.startswith("force_occupation_revolt_"):
            return {}
        try: force=self.read(self.owner_path(force_ref))
        except (KeyError,ValueError,FileNotFoundError): return {}
        admin=str(force.get("administrative_owner","")); state=str(force.get("state",""))
        if not state:
            if admin.startswith("house_"):
                try: state=self._state_key(self.read(self.owner_path(admin)).get("state"))
                except Exception: state=""
            elif admin==self.PLAYER_ACTOR or force_ref=="force_tang_wei_personal": state="qin"
        if state not in {"qin","zhao","chu","wei","han","yan","qi"}: return {}
        pop_path=f"state/population/{state}.json"; pop=copy.deepcopy(self.read(pop_path)); _pp,pop=self._ensure_local_population_ledger(state,pop); sites=pop.get("local_population",{}).get("sites",{})
        remaining=casualties; out={}
        for location_ref,row in sorted(sites.items()):
            alloc=row.get("service_allocations",{}).get(force_ref) if isinstance(row,Mapping) and isinstance(row.get("service_allocations"),Mapping) else None
            if not isinstance(alloc,Mapping): continue
            available=max(0,int(alloc.get("personnel",0))); take=min(remaining,available)
            if take:
                applied=self._record_local_service_deaths(pop,state,str(location_ref),take,service_key="private_household_military",service_owner_ref=force_ref)
                if applied!=take: raise ValueError("private-force casualty exceeded local service allocation")
                out[str(location_ref)]=take; remaining-=take
            if remaining<=0: break
        if remaining:
            raise ValueError("private-force casualties exceed exact local service allocations")
        pop.setdefault("local_private_service_casualties",[]).append({"at":at,"evidence_ref":evidence_ref,"force_ref":force_ref,"deaths":casualties,"local_sources":out}); pop["local_private_service_casualties"]=pop["local_private_service_casualties"][-32:]; self.put(pop_path,pop); return out

    def _reconcile_foreign_service_casualties(
        self,
        force_ref: str,
        cohort_losses: Mapping[str, Any],
        *,
        at: str,
        evidence_ref: str,
    ) -> dict[str, int]:
        """Charge mixed state-force deaths to each cohort's real population owner.

        The base state-force casualty reducer charges the force owner's native active
        military pool. Occupation recruiting can create a mixed-provenance state
        force, so exact foreign cohort losses are redirected to each origin
        population's foreign_military_service stratum and the corresponding native
        deduction is reversed exactly once.
        """
        if not force_ref.startswith("force_state_") or not isinstance(cohort_losses, Mapping):
            return {}
        force = self.read(self.owner_path(force_ref))
        owner_state = str(force.get("state", "")) if isinstance(force, Mapping) and str(force.get("service_class", "")) == "state_levy" else force_ref.removeprefix("force_state_")
        owner_state = owner_state.removeprefix("state_")
        ledger = force.get("cohort_ledger", {}) if isinstance(force, Mapping) else {}
        cohorts = ledger.get("cohorts", {}) if isinstance(ledger, Mapping) else {}
        foreign: dict[str, int] = {}
        for cohort_id, raw_loss in cohort_losses.items():
            loss = max(0, int(raw_loss))
            cohort = cohorts.get(str(cohort_id)) if isinstance(cohorts, Mapping) else None
            origin = cohort.get("origin", {}) if isinstance(cohort, Mapping) else {}
            population_ref = str(origin.get("population_ref", "")) if isinstance(origin, Mapping) else ""
            if loss <= 0 or not population_ref.startswith("population_") or population_ref == f"population_{owner_state}":
                continue
            foreign[population_ref] = foreign.get(population_ref, 0) + loss
        if not foreign:
            return {}

        owner_path = f"state/population/{owner_state}.json"
        owner_pop = copy.deepcopy(self.read(owner_path))
        total_foreign = sum(foreign.values())
        owner_pop["strata"]["active_military"] = int(owner_pop["strata"].get("active_military", 0)) + total_foreign
        owner_pop["population_total"] = int(owner_pop.get("population_total", 0)) + total_foreign
        owner_pop.setdefault("foreign_service_casualty_reconciliation", []).append({
            "at": at, "evidence_ref": evidence_ref, "reversed_native_charge": total_foreign,
            "origin_population_losses": copy.deepcopy(foreign),
        })
        owner_pop["foreign_service_casualty_reconciliation"] = owner_pop["foreign_service_casualty_reconciliation"][-24:]
        self.put(owner_path, owner_pop)

        for population_ref, count in sorted(foreign.items()):
            origin_state = population_ref.removeprefix("population_")
            path = f"state/population/{origin_state}.json"
            pop = copy.deepcopy(self.read(path))
            service = int(pop.get("strata", {}).get("foreign_military_service", 0))
            if service < count:
                raise ValueError("foreign-service casualty exceeds conserved origin population stratum")
            pop["strata"]["foreign_military_service"] = service - count
            pop["population_total"] = max(0, int(pop.get("population_total", 0)) - count)
            pop.setdefault("foreign_service_casualties", []).append({
                "at": at, "evidence_ref": evidence_ref, "serving_force_ref": force_ref, "deaths": count,
            })
            pop["foreign_service_casualties"] = pop["foreign_service_casualties"][-24:]
            self.put(path, pop)
        return foreign

    def _reconcile_rebel_force_casualties(
        self,
        force_ref: str,
        casualties: int,
        *,
        at: str,
        evidence_ref: str,
        formation_ref: str,
    ) -> dict[str, Any] | None:
        """Charge local-rebel military deaths to the exact origin population once."""
        if casualties <= 0:
            return None
        try:
            force = self.read(self.owner_path(force_ref))
        except (KeyError, ValueError, FileNotFoundError):
            return None
        if not isinstance(force, Mapping) or str(force.get("kind", "")) != "local_rebel_force":
            return None
        source_ref = str(force.get("population_source_ref", ""))
        stratum = str(force.get("population_service_stratum", "rebel_military"))
        if not source_ref.startswith("population_"):
            return None
        state = source_ref.removeprefix("population_")
        pop_path = f"state/population/{state}.json"
        pop = copy.deepcopy(self.read(pop_path))
        service = max(0, int(pop.get("strata", {}).get(stratum, 0)))
        applied = min(service, max(0, int(casualties)))
        if applied <= 0:
            return None
        pop["strata"][stratum] = service - applied
        pop["population_total"] = max(0, int(pop.get("population_total", 0)) - applied)
        try:
            formation = self.read(self.owner_path(formation_ref))
            origin_location = str(formation.get("location_ref", force.get("source_location_ref", ""))) if isinstance(formation, Mapping) else str(force.get("source_location_ref", ""))
        except (KeyError, ValueError, FileNotFoundError):
            origin_location = str(force.get("source_location_ref", ""))
        if origin_location:
            local_applied = self._record_local_service_deaths(pop, state, origin_location, applied, service_key="rebel_military", service_owner_ref=force_ref)
            if local_applied != applied:
                raise ValueError("rebel casualty exceeds conserved local rebel allocation")
        pop.setdefault("loss_provenance", []).append({
            "at": at,
            "kind": "rebel_battle_casualty",
            "force_ref": force_ref,
            "formation_ref": formation_ref,
            "personnel": applied,
            "battle_ref": evidence_ref,
        })
        pop["loss_provenance"] = pop["loss_provenance"][-32:]
        self.put(pop_path, pop)
        return {"population_ref": source_ref, "stratum": stratum, "personnel": applied}

    def _autonomy_apply_battle_losses(
        self,
        formation_ref: str,
        loss: int,
        at: str,
        *,
        losing_side: bool,
        opponent_state: str,
        seed_material: str,
    ) -> dict[str, Any]:
        """Expose political burden only after conserved military casualties settle."""
        try:
            _path, before = self._load_formation(formation_ref)
        except ValueError:
            before = {}
        owner = str(before.get("administrative_owner", ""))
        before_personnel = max(0, int(before.get("personnel", 0)))
        result = super()._autonomy_apply_battle_losses(
            formation_ref,
            loss,
            at,
            losing_side=losing_side,
            opponent_state=opponent_state,
            seed_material=seed_material,
        )
        force_ref = str(before.get("owner_force_ref", ""))
        cohort_losses = result.get("cohort_losses", {}) if isinstance(result, Mapping) else {}
        local_losses = self._reconcile_local_state_service_casualties(
            force_ref, cohort_losses, at=at, evidence_ref=seed_material,
        )
        foreign_losses = self._reconcile_foreign_service_casualties(
            force_ref, cohort_losses,
            at=at, evidence_ref=seed_material,
        )
        if local_losses and isinstance(result, dict):
            result["local_service_population_losses"] = local_losses
        if foreign_losses and isinstance(result, dict):
            result["foreign_service_population_losses"] = foreign_losses
        rebel_loss = self._reconcile_rebel_force_casualties(
            force_ref,
            max(0, int(result.get("loss", 0))) if isinstance(result, Mapping) else 0,
            at=at,
            evidence_ref=seed_material,
            formation_ref=formation_ref,
        )
        if rebel_loss and isinstance(result, dict):
            result["rebel_population_loss"] = rebel_loss
        if force_ref and not force_ref.startswith("force_state_") and not force_ref.startswith("force_occupation_revolt_"):
            private_loss=max(0,int(result.get("loss",0))) if isinstance(result,Mapping) else 0
            if private_loss:
                try: force_now=self.read(self.owner_path(force_ref)); admin=str(force_now.get("administrative_owner","")); state=str(force_now.get("state",""))
                except Exception: state=""; admin=""
                if not state and admin.startswith("house_"):
                    try: state=self._state_key(self.read(self.owner_path(admin)).get("state"))
                    except Exception: state=""
                if not state and (admin==self.PLAYER_ACTOR or force_ref=="force_tang_wei_personal"): state="qin"
                if state in {"qin","zhao","chu","wei","han","yan","qi"}:
                    pp=f"state/population/{state}.json"; pop=copy.deepcopy(self.read(pp)); available=max(0,int(pop.get("strata",{}).get("private_household_military",0))); applied=min(private_loss,available); pop["strata"]["private_household_military"]=available-applied; pop["population_total"]=max(0,int(pop.get("population_total",0))-applied); self.put(pp,pop)
                    private_local=self._reconcile_private_service_casualties(force_ref,applied,at=at,evidence_ref=seed_material)
                    if isinstance(result,dict) and private_local: result["private_service_population_losses"]=private_local
        if not owner.startswith("state_") or before_personnel <= 0:
            return result
        state = owner.removeprefix("state_")
        sp = f"state/states/{state}.json"
        sd = copy.deepcopy(self.read(sp))
        applied = min(max(0, int(loss)), before_personnel)
        burden = sd.setdefault("war_burden", {})
        burden["casualties_total"] = int(burden.get("casualties_total", 0)) + applied
        burden["last_loss"] = {
            "at": at,
            "formation_ref": formation_ref,
            "casualties": applied,
            "opponent_state": opponent_state,
            "losing_side": bool(losing_side),
            "basis": "conserved autonomous battle losses",
        }
        history = burden.setdefault("recent_losses", [])
        history.append(copy.deepcopy(burden["last_loss"]))
        del history[:-24]
        force = self.read_optional(f"state/forces/state-{state}.json")
        authorized = max(1, int(force.get("authorized_strength", force.get("headcount", before_personnel))) if isinstance(force, Mapping) else before_personnel)
        ratio = applied / authorized
        if applied > 0 and (ratio >= 0.005 or applied >= 250):
            shock = min(3, max(1, int(math.ceil(ratio * 100))))
            sd["internal_stability"] = _clamp(int(sd.get("internal_stability", 50)) - shock)
            if losing_side:
                sd["mobilization_readiness"] = _clamp(int(sd.get("mobilization_readiness", 50)) - min(2, shock))
            burden["last_political_shock"] = {"at": at, "points": shock, "basis": "material casualty burden relative to authorized force"}
        self.put(sp, sd)
        return result

    def _autonomy_population(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Settle explicit births/deaths, age maturation, and local conservation for any scheduled population owner."""
        owner_ref = str(host["owner_ref"])
        pop_path = self.owner_path(owner_ref)
        before0 = copy.deepcopy(self.read(pop_path))
        owner_key = owner_ref.removeprefix("population_")
        if owner_key in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
            _lp, before = self._ensure_local_population_ledger(owner_key, before0)
        else:
            before = before0
        self.put(pop_path, before)
        before_total = max(0, int(before.get("population_total", 0)))
        before_strata = copy.deepcopy(before.get("strata", {}))
        super()._autonomy_population(host, occurrences, at)
        after = copy.deepcopy(self.read(pop_path))
        dem = after.get("demography") if isinstance(after.get("demography"), Mapping) else {}
        dependent_key = str(dem.get("dependent_stratum", "dependents_children_elderly"))
        maturation_target = str(dem.get("maturation_target_stratum", "agricultural"))
        default_working = (
            "agricultural", "craft_and_industry", "merchant_and_transport",
            "household_and_service", "administration_and_education", "camp_medical_support",
        )
        configured_working = dem.get("working_strata")
        working_keys = [str(x) for x in configured_working if isinstance(x, str)] if isinstance(configured_working, list) else list(default_working)
        working_keys = [k for k in working_keys if k in after.get("strata", {}) and k != dependent_key]
        if maturation_target not in after.get("strata", {}):
            raise ValueError("demographic maturation target is absent from population owner")

        local = after.get("local_population") if isinstance(after.get("local_population"), Mapping) else None
        sites = local.get("sites", {}) if isinstance(local, Mapping) and isinstance(local.get("sites"), Mapping) else {}
        births = max(0, int(dem.get("last_births", 0)))
        deaths = max(0, int(dem.get("last_deaths", 0)))
        death_by_stratum = dem.get("last_deaths_by_stratum", {}) if isinstance(dem.get("last_deaths_by_stratum"), Mapping) else {}

        if isinstance(sites, dict) and sites:
            if births:
                weighted = [
                    (ref, max(1, int(row.get("civilian_population", 0))))
                    for ref, row in sites.items()
                    if isinstance(row, Mapping)
                ]
                additions = self._weighted_integer_partition(births, weighted)
                for ref, count in additions.items():
                    row = sites[ref]
                    cs = row.setdefault("civilian_strata", {})
                    cs[dependent_key] = int(cs.get(dependent_key, 0)) + count
                    row["births_cumulative"] = int(row.get("births_cumulative", 0)) + count
                    self._sync_local_population_row(row)
            for stratum, requested in sorted(death_by_stratum.items()):
                remaining = max(0, int(requested))
                if remaining <= 0:
                    continue
                rows = [
                    (ref, max(0, int((row.get("civilian_strata", {}) if isinstance(row, Mapping) else {}).get(stratum, 0))))
                    for ref, row in sites.items()
                    if isinstance(row, Mapping)
                ]
                rows = [(ref, count) for ref, count in rows if count > 0]
                while remaining > 0 and rows:
                    allocation = self._weighted_integer_partition(remaining, [(ref, float(count)) for ref, count in rows])
                    progressed = 0
                    next_rows: list[tuple[str, int]] = []
                    for ref, available in rows:
                        take = min(available, int(allocation.get(ref, 0)))
                        if take:
                            row = sites[ref]
                            cs = row.setdefault("civilian_strata", {})
                            cs[stratum] = max(0, int(cs.get(stratum, 0)) - take)
                            row["deaths_cumulative"] = int(row.get("deaths_cumulative", 0)) + take
                            self._sync_local_population_row(row)
                            progressed += take
                            available -= take
                        if available > 0:
                            next_rows.append((ref, available))
                    remaining -= progressed
                    rows = next_rows
                    if progressed <= 0:
                        break
                if remaining:
                    raise ValueError(f"demographic deaths exceed conserved local {stratum} population")

        age = dem.get("age_cohorts") if isinstance(dem.get("age_cohorts"), Mapping) else None
        if not isinstance(age, Mapping) or sum(max(0, int(v)) for v in age.values()) != before_total:
            depend = max(0, int(before_strata.get(dependent_key, 0)))
            child = min(depend, int(round(depend * 0.72)))
            elder = max(0, depend - child)
            adult_total = max(0, before_total - depend)
            young_adult = int(round(adult_total * 0.66))
            mature_adult = max(0, adult_total - young_adult)
            age = {"age_0_14": child, "age_15_39": young_adult, "age_40_59": mature_adult, "age_60_plus": elder}
        age = {k: max(0, int(v)) for k, v in age.items()}
        mature = min(age.get("age_0_14", 0), max(0, int(round(age.get("age_0_14", 0) / 15.0 * max(1, occurrences)))))
        to_mature = min(age.get("age_15_39", 0), max(0, int(round(age.get("age_15_39", 0) / 25.0 * max(1, occurrences)))))
        to_elder = min(age.get("age_40_59", 0), max(0, int(round(age.get("age_40_59", 0) / 20.0 * max(1, occurrences)))))
        weights = {"age_0_14": 0.35, "age_15_39": 0.25, "age_40_59": 0.7, "age_60_plus": 2.4}
        caps = {k: age.get(k, 0) for k in weights}
        death_alloc = self._weighted_integer_partition(min(deaths, sum(caps.values())), [(k, weights[k] * max(1, caps[k])) for k in weights]) if deaths else {k: 0 for k in weights}
        age["age_0_14"] = max(0, age.get("age_0_14", 0) + births - mature - int(death_alloc.get("age_0_14", 0)))
        age["age_15_39"] = max(0, age.get("age_15_39", 0) + mature - to_mature - int(death_alloc.get("age_15_39", 0)))
        age["age_40_59"] = max(0, age.get("age_40_59", 0) + to_mature - to_elder - int(death_alloc.get("age_40_59", 0)))
        age["age_60_plus"] = max(0, age.get("age_60_plus", 0) + to_elder - int(death_alloc.get("age_60_plus", 0)))
        post_total = max(0, int(after.get("population_total", 0)))
        diff = post_total - sum(age.values())
        age["age_0_14"] = max(0, age.get("age_0_14", 0) + diff)
        dem["age_cohorts"] = age

        strata = after.setdefault("strata", {})
        mature_transfer = min(mature, max(0, int(strata.get(dependent_key, 0))))
        strata[dependent_key] = max(0, int(strata.get(dependent_key, 0)) - mature_transfer)
        strata[maturation_target] = int(strata.get(maturation_target, 0)) + mature_transfer
        aging_transfer = min(to_elder, sum(max(0, int(strata.get(k, 0))) for k in working_keys))
        remaining = aging_transfer
        for key in sorted(working_keys, key=lambda k: (0 if k == maturation_target else 1, k)):
            if remaining <= 0:
                break
            take = min(remaining, max(0, int(strata.get(key, 0))))
            strata[key] = int(strata.get(key, 0)) - take
            remaining -= take
        strata[dependent_key] = int(strata.get(dependent_key, 0)) + aging_transfer

        if isinstance(sites, dict) and sites:
            rem = mature_transfer
            for ref, row in sorted(sites.items(), key=lambda kv: (-int((kv[1].get("civilian_strata", {}) if isinstance(kv[1], Mapping) else {}).get(dependent_key, 0)), str(kv[0]))):
                if rem <= 0:
                    break
                cs = row.setdefault("civilian_strata", {})
                avail = max(0, int(cs.get(dependent_key, 0)))
                take = min(rem, avail)
                cs[dependent_key] = avail - take
                cs[maturation_target] = int(cs.get(maturation_target, 0)) + take
                rem -= take
                self._sync_local_population_row(row)
            rem = aging_transfer
            for ref, row in sorted(sites.items(), key=lambda kv: (-int((kv[1].get("civilian_strata", {}) if isinstance(kv[1], Mapping) else {}).get(maturation_target, 0)), str(kv[0]))):
                if rem <= 0:
                    break
                cs = row.setdefault("civilian_strata", {})
                take_total = 0
                for key in sorted(working_keys, key=lambda k: (0 if k == maturation_target else 1, k)):
                    if rem <= 0:
                        break
                    x = min(rem, max(0, int(cs.get(key, 0))))
                    cs[key] = int(cs.get(key, 0)) - x
                    rem -= x
                    take_total += x
                cs[dependent_key] = int(cs.get(dependent_key, 0)) + take_total
                self._sync_local_population_row(row)
            if rem:
                raise ValueError("population aging exceeded local working-age strata")

        after["population_total"] = sum(max(0, int(v)) for v in strata.values())
        if isinstance(local, dict):
            local["last_demography_close"] = at
            local["last_maturation"] = {"matured_to_working": mature_transfer, "aged_to_dependents": aging_transfer, "births": births, "deaths": deaths}
        self.put(pop_path, after)

    def _review_state_force_authorization_growth(
        self,
        *,
        state: str,
        state_doc: dict[str, Any],
        at: str,
        occurrences: int,
        monthly_expense_due: int,
    ) -> dict[str, Any]:
        """Expand regular-force authorization only when real pressure supports it.

        This is an authorization review, not recruitment and never a manpower source.
        The ordinary state recruitment resolver still has to move conserved civilians
        into service and pay the registered basic-issue cost.  The review is shared by
        every represented sovereign state and is bounded by population, recruiting
        throughput, treasury reserve, and the common active-military population cap.
        """
        if occurrences <= 0:
            return {"changed": False, "reason": "no_elapsed_reviews"}
        economy = self.read("game/data/mechanics/economy.json")
        posture = economy.get("force_posture_hysteresis", {}) if isinstance(economy, Mapping) else {}
        rules = posture.get("authorization_growth", {}) if isinstance(posture, Mapping) else {}
        if not isinstance(rules, Mapping):
            return {"changed": False, "reason": "no_authorization_growth_rule"}

        # A sovereign may be under military pressure and still be unable to grow its
        # regular establishment while the civilian food economy is failing. The
        # threshold is common to every state and comes from the same production close.
        _eco_path, private_economy = self._private_economy(state)
        food_close = private_economy.get("production_runtime", {}).get("last_food_close", {}) if isinstance(private_economy.get("production_runtime"), Mapping) else {}
        grain_due = max(0, int(food_close.get("grain_due_kg", 0))) if isinstance(food_close, Mapping) else 0
        grain_shortfall = max(0, int(food_close.get("grain_shortfall_kg", 0))) if isinstance(food_close, Mapping) else 0
        food_supply_fraction = 1.0 if grain_due <= 0 else max(0.0, min(1.0, (grain_due - grain_shortfall) / grain_due))
        feedback_rules = self._civil_rules().get("economy_feedback", {})
        minimum_food_supply = max(0.0, min(1.0, _fixed(feedback_rules.get("minimum_food_supply_fraction_for_force_authorization_growth", 0.98), 0.98)))
        if food_supply_fraction < minimum_food_supply:
            return {"changed": False, "reason": "civilian_food_supply_below_force_growth_floor", "food_supply_fraction": round(food_supply_fraction, 6), "minimum_food_supply_fraction": minimum_food_supply}

        now = CampaignTime.parse(at)
        recent_window = max(1, int(_fixed(rules.get("recent_threat_window_days", 90), 90))) * 86400
        threat_severity = 0
        threats = state_doc.get("known_threats", {}) if isinstance(state_doc.get("known_threats"), Mapping) else {}
        for row in threats.values():
            if isinstance(row, Mapping):
                observed = row.get("observed_at")
                if isinstance(observed, str):
                    try:
                        observed_time = CampaignTime.parse(observed)
                    except ValueError:
                        continue
                    if observed_time > now or observed_time.seconds_until(now) > recent_window:
                        continue
                severity = max(0, min(100, int(_fixed(row.get("severity", 0), 0))))
            else:
                severity = max(0, min(100, int(_fixed(row, 0))))
            threat_severity = max(threat_severity, severity)

        intent_pressure = 0
        active_intent_ref = ""
        for intent in state_doc.get("war_intents", []) if isinstance(state_doc.get("war_intents"), list) else []:
            if not isinstance(intent, Mapping) or str(intent.get("status", "")) not in {"authorized", "ready", "activated"}:
                continue
            expires = intent.get("expires_at")
            if isinstance(expires, str):
                try:
                    if CampaignTime.parse(expires) <= now:
                        continue
                except ValueError:
                    continue
            intent_pressure = max(intent_pressure, max(0, min(100, int(_fixed(rules.get("authorized_war_intent_pressure", 70), 70)))))
            active_intent_ref = str(intent.get("intent_ref", ""))

        active_war = False
        active_theater_ref = ""
        world = self.read_optional("state/politics/interstate-history.json")
        if isinstance(world, Mapping):
            for theater_ref, record in world.get("theaters", {}).items() if isinstance(world.get("theaters"), Mapping) else []:
                if not isinstance(record, Mapping) or str(record.get("phase", "peace")) == "peace":
                    continue
                if state not in {str(record.get("attacker_state", "")), str(record.get("defender_state", ""))}:
                    continue
                active_war = True
                active_theater_ref = str(theater_ref)
                break
        war_pressure = max(0, min(100, int(_fixed(rules.get("active_war_pressure", 90), 90)))) if active_war else 0
        pressure = max(threat_severity, intent_pressure, war_pressure)
        minimum_pressure = max(0, min(100, int(_fixed(rules.get("minimum_threat_severity", 55), 55))))
        readiness = max(0, min(100, int(_fixed(state_doc.get("mobilization_readiness", 50), 50))))
        minimum_readiness = max(0, min(100, int(_fixed(rules.get("minimum_mobilization_readiness", 40), 40))))
        if pressure < minimum_pressure or readiness < minimum_readiness:
            return {"changed": False, "reason": "insufficient_current_pressure_or_readiness", "pressure": pressure, "readiness": readiness}

        force_path = f"state/forces/state-{state}.json"
        force = copy.deepcopy(self.read(force_path))
        population_path = f"state/population/{state}.json"
        population = copy.deepcopy(self.read(population_path))
        current_authorized = max(int(force.get("headcount", 0)), int(force.get("authorized_strength", force.get("headcount", 0))))
        population_total = max(0, int(population.get("population_total", 0)))
        population_fraction = max(0.0, min(1.0, _fixed(rules.get("maximum_active_military_fraction_of_population", 0.10), 0.10)))
        population_ceiling = max(current_authorized, int(math.floor(population_total * population_fraction)))
        headroom = max(0, population_ceiling - current_authorized)
        if headroom <= 0:
            return {"changed": False, "reason": "active_military_population_ceiling", "pressure": pressure}

        threshold_fraction = max(0.0, _fixed(rules.get("monthly_growth_fraction_at_threshold", 0.0025), 0.0025))
        full_fraction = max(threshold_fraction, _fixed(rules.get("monthly_growth_fraction_at_full_pressure", 0.01), 0.01))
        pressure_span = max(1, 100 - minimum_pressure)
        pressure_factor = max(0.0, min(1.0, (pressure - minimum_pressure) / pressure_span))
        monthly_fraction = threshold_fraction + (full_fraction - threshold_fraction) * pressure_factor
        desired_growth = max(0, int(math.floor(current_authorized * monthly_fraction * max(1, occurrences))))

        granularity = max(1, int(_fixed(rules.get("personnel_granularity", 500), 500)))
        office = self.read(self.owner_path(f"inst_{state}_recruitment_office"))
        office_capacity = max(0, int(office.get("capacity", 0))) * max(1, occurrences)
        available = max(0, int(population.get("strata", {}).get("agricultural", 0)))
        if hasattr(self, "_autonomy_state_recruitment_available"):
            available = min(available, max(0, int(self._autonomy_state_recruitment_available(state, population))))
        unit_cost = max(1, int(economy.get("military_finance", {}).get("recruitment_and_basic_issue_cost_silver_per_person", 12)))
        reserve_months = max(0.0, _fixed(rules.get("treasury_reserve_months", 2.0), 2.0))
        reserve_silver = int(math.ceil(max(0, monthly_expense_due) * reserve_months))
        spendable = max(0, int(state_doc.get("treasury_silver", 0)) - reserve_silver)
        affordable = spendable // unit_cost
        raw_growth = min(desired_growth, headroom, office_capacity, available, affordable)
        growth = (raw_growth // granularity) * granularity
        if growth <= 0:
            return {
                "changed": False, "reason": "material_growth_capacity_below_granularity",
                "pressure": pressure, "desired_growth": desired_growth, "headroom": headroom,
                "office_capacity": office_capacity, "available_population": available, "affordable": affordable,
            }

        force["authorized_strength"] = current_authorized + growth
        validate_cohort_ledger(force)
        self.put(force_path, force)
        event_id = "state_force_authorization_" + hashlib.sha256(f"{state}|{at}|{current_authorized}|{growth}".encode()).hexdigest()[:16]
        history = copy.deepcopy(self.read("state/history/events/index.json"))
        history.setdefault("events", []).append({
            "event_id": event_id,
            "kind": "state_force_authorization_growth",
            "at": at,
            "state_ref": f"state_{state}",
            "force_ref": f"force_state_{state}",
            "authorized_strength_before": current_authorized,
            "authorized_strength_after": current_authorized + growth,
            "authorized_growth_personnel": growth,
            "basis": {
                "current_pressure": pressure, "recent_threat_severity": threat_severity,
                "authorized_war_intent_ref": active_intent_ref or None,
                "active_theater_ref": active_theater_ref or None,
                "mobilization_readiness": readiness, "population_ceiling": population_ceiling,
                "recruitment_office_capacity": office_capacity, "treasury_reserve_silver": reserve_silver,
                "principle": "authorization changed only; conserved recruitment remains the manpower transaction",
            },
        })
        write_history_index(self, history)
        return {"changed": True, "growth": growth, "pressure": pressure, "event_id": event_id}

    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Close state finances before military autonomy and conserve recruitment pay.

        The base state resolver consumes macro monthly revenue/expense fields.
        Production settles those values through exact transfers first, then invokes
        the military/state logic with the macro cash fields temporarily neutralized.
        This prevents recruiting against revenue that the private economy could not
        actually pay.
        """
        state = self._state_key(str(host["owner_ref"]))
        state_path = f"state/states/{state}.json"
        occurrences = max(0, int(occurrences))
        if occurrences <= 0:
            return

        self._settle_private_production(state, occurrences, at)
        original = copy.deepcopy(self.read(state_path))
        prepared = copy.deepcopy(original)

        revenue_plan = self._territorial_revenue_plan(state, occurrences)
        due_total = sum(max(0, int(row.get("due_silver", 0))) for row in revenue_plan)
        monthly_revenue_due = max(0, int(round(due_total / occurrences)))
        expense_plan = self._state_monthly_expense_plan(state, monthly_revenue_due)
        monthly_expense_due = max(0, int(expense_plan.get("total_due_silver", 0)))
        source_cache: dict[str, tuple[str, dict[str, Any]]] = {}
        revenue_rows: list[dict[str, Any]] = []
        collected_total = 0
        for row in revenue_plan:
            source_state = str(row["native_state"])
            if source_state not in source_cache:
                source_cache[source_state] = self._private_economy(source_state)
            _ep, eco = source_cache[source_state]
            _site_ref, local_eco = self._local_economy_region(source_state, eco, str(row["location_ref"]))
            due = max(0, int(row.get("due_silver", 0)))
            payer_house_ref = row.get("payer_house_ref")
            if isinstance(payer_house_ref, str) and payer_house_ref:
                paid = self._debit_house_cash(payer_house_ref, due)
                payment_source = payer_house_ref
            else:
                paid = min(due, max(0, int(local_eco.get("cash_silver", 0))))
                local_eco["cash_silver"] = max(0, int(local_eco.get("cash_silver", 0)) - paid)
                payment_source = f"private_economy_{source_state}"
            collected_total += paid
            revenue_rows.append({**row, "payment_source_ref": payment_source, "collected_silver": paid, "arrears_silver": max(0, due - paid)})
        for _source, (ep, eco) in source_cache.items():
            self._sync_local_economy_aggregate(eco)
            self._write_private_economy(ep, eco)
        prepared["treasury_silver"] = max(0, int(prepared.get("treasury_silver", 0)) + collected_total)

        expense_due = monthly_expense_due * occurrences
        expense_paid = min(expense_due, max(0, int(prepared.get("treasury_silver", 0))))
        prepared["treasury_silver"] = max(0, int(prepared.get("treasury_silver", 0)) - expense_paid)
        own_ep, own_eco = self._private_economy(state)
        own_eco["cash_silver"] = int(own_eco.get("cash_silver", 0)) + expense_paid
        self._write_private_economy(own_ep, own_eco)

        # Strategic pressure may expand the legal regular-force establishment, but
        # only before the ordinary state reducer runs so that the same conserved
        # recruitment transaction must fill the newly authorized bodies.
        self._review_state_force_authorization_growth(
            state=state, state_doc=prepared, at=at, occurrences=occurrences,
            monthly_expense_due=monthly_expense_due,
        )

        # Prevent the parent reducer from creating the same macro cash again.
        prepared["normal_monthly_revenue_silver"] = 0
        prepared["normal_monthly_expense_silver"] = 0
        self.put(state_path, prepared)

        native_pop_path = f"state/population/{state}.json"
        native_pop_before = copy.deepcopy(self.read(native_pop_path))
        active_before = int(native_pop_before.get("strata", {}).get("active_military", 0))
        super()._autonomy_state(host, occurrences, at)

        after = copy.deepcopy(self.read(state_path))
        after["normal_monthly_revenue_silver"] = monthly_revenue_due
        after["normal_monthly_expense_silver"] = monthly_expense_due

        economy_rules = self.read("game/data/mechanics/economy.json")
        unit_cost = max(1, int(economy_rules.get("military_finance", {}).get("recruitment_and_basic_issue_cost_silver_per_person", 12)))
        native_pop_after = self.read(native_pop_path)
        native_recruits = max(0, int(native_pop_after.get("strata", {}).get("active_military", 0)) - active_before)
        if native_recruits:
            own_ep, own_eco = self._private_economy(state)
            own_eco["cash_silver"] = int(own_eco.get("cash_silver", 0)) + native_recruits * unit_cost
            self._write_private_economy(own_ep, own_eco)

        # Lawful conquered-population recruiting is a separate exact transfer.
        force_path = f"state/forces/state-{state}.json"
        force = copy.deepcopy(self.read(force_path))
        shortage = max(0, int(force.get("authorized_strength", force.get("headcount", 0))) - int(force.get("headcount", 0)))
        office = self.read(self.owner_path(f"inst_{state}_recruitment_office"))
        office_capacity = max(0, int(office.get("capacity", 0))) * occurrences
        remaining_capacity = max(0, office_capacity - native_recruits)
        occupied_recruits = 0
        occupied_rows: list[dict[str, Any]] = []
        territory = copy.deepcopy(self.read("state/territory/control.json"))
        occupation_rules = self._civil_rules().get("occupation", {})
        minimum_access = int(occupation_rules.get("minimum_recruitment_access", 20))
        monthly_fraction = max(0.0, min(0.02, _fixed(occupation_rules.get("occupation_recruitment_fraction_per_review", 0.001), 0.001)))

        candidates: list[tuple[int, str, str, dict[str, Any]]] = []
        for location_ref, site in territory.get("sites", {}).items():
            if not isinstance(site, dict) or str(site.get("controller")) != f"state_{state}":
                continue
            native = self._native_site_state(str(location_ref))
            governance = site.get("governance") if isinstance(site.get("governance"), dict) else None
            if native is None or native == state or governance is None or governance.get("status") == "open_revolt":
                continue
            access = max(0, int(governance.get("recruitment_access", 0)))
            if access < minimum_access:
                continue
            candidates.append((-access, str(location_ref), native, governance))

        for neg_access, location_ref, native, governance in sorted(candidates):
            if shortage <= 0 or remaining_capacity <= 0:
                break
            access = -neg_access
            pop_path = f"state/population/{native}.json"
            population = copy.deepcopy(self.read(pop_path))
            _lp, population, local_row = self._local_population_row(native, location_ref, population)
            agricultural = min(max(0, int(population.get("strata", {}).get("agricultural", 0))), max(0, int(local_row.get("agricultural_available", 0))), max(0, int(local_row.get("civilian_population", 0))))
            _native, local_population = self._occupation_population_estimate(location_ref)
            access_quota = max(0, int(math.floor(local_population * monthly_fraction * (access / 100.0) * occurrences)))
            affordable = max(0, int(after.get("treasury_silver", 0))) // unit_cost
            recruits = min(shortage, remaining_capacity, agricultural, access_quota, affordable)
            if recruits <= 0:
                continue

            population["strata"]["agricultural"] = int(population["strata"].get("agricultural", 0)) - recruits
            population["strata"]["foreign_military_service"] = int(population["strata"].get("foreign_military_service", 0)) + recruits
            moved_local = self._consume_local_recruitment(population, native, location_ref, recruits, service_key="serving_foreign_military", source_stratum="agricultural", service_owner_ref=f"force_state_{state}")
            if moved_local != recruits:
                raise ValueError("occupation recruitment exceeded the locality's conserved civilian manpower")
            add_recruits(force, "line_infantry", recruits, location_ref=location_ref)
            record_recruitment_cohort(
                force,
                role="line_infantry",
                count=recruits,
                location_ref=location_ref,
                source_population_ref=f"population_{native}",
                source_stratum="agricultural",
                recruited_at=at,
                profile_registry=self.read("game/data/mil/recruitment-cohort-profiles.json"),
                selection_profile="state_basic_military_screen",
                provenance_ref=f"occupation_recruitment:{state}:{location_ref}:{at}",
            )
            cost = recruits * unit_cost
            after["treasury_silver"] = max(0, int(after.get("treasury_silver", 0)) - cost)
            local_ep, local_eco = self._private_economy(native)
            local_eco["cash_silver"] = int(local_eco.get("cash_silver", 0)) + cost
            self.put(local_ep, local_eco)
            self.put(pop_path, population)

            governance["recruited_under_occupation_total"] = int(governance.get("recruited_under_occupation_total", 0)) + recruits
            governance["last_occupation_recruitment"] = {
                "at": at,
                "personnel": recruits,
                "destination_force_ref": f"force_state_{state}",
                "source_population_ref": f"population_{native}",
                "source_stratum": "agricultural",
                "payment_silver": cost,
                "payment_destination_ref": f"private_economy_{native}",
            }
            occupied_rows.append({"location_ref": location_ref, "native_state": native, "personnel": recruits, "payment_silver": cost, "recruitment_access": access})
            occupied_recruits += recruits
            shortage -= recruits
            remaining_capacity -= recruits

        if occupied_recruits:
            self.put(force_path, force)
            self.put("state/territory/control.json", territory)

        finance = after.setdefault("civil_finance", {})
        due_total = sum(int(row.get("due_silver", 0)) for row in revenue_rows)
        finance.update({
            "last_close": at,
            "revenue_due_silver": due_total,
            "revenue_collected_silver": collected_total,
            "expense_due_silver": expense_due,
            "expense_paid_silver": expense_paid,
            "tax_arrears_silver": max(0, due_total - collected_total),
            "territorial_realization_factor": round(collected_total / max(1, due_total), 4),
            "modeled_monthly_revenue_due_silver": monthly_revenue_due,
            "modeled_monthly_expense_due_silver": monthly_expense_due,
            "expense_components": expense_plan,
            "revenue_sources": revenue_rows[-64:],
            "private_economy_ref": f"private_economy_{state}",
            "native_recruits": native_recruits,
            "native_recruitment_payments_silver": native_recruits * unit_cost,
            "occupied_recruits": occupied_recruits,
            "occupied_recruitment": occupied_rows[-32:],
        })
        self.put(state_path, after)
        settle_state_settlement_development(self, state=state, at=at, occurrences=occurrences)
        self._settle_frontier_pressure(f"state_{state}", occurrences, at)
        self._generate_npc_war_intent(f"state_{state}", at)
        self._settle_diplomatic_routes(f"state_{state}", copy.deepcopy(self.read(state_path)), at)
        self._settle_treaty_obligations(f"state_{state}", at, occurrences)
        self._generate_npc_diplomatic_initiative(f"state_{state}", at)

    def _project_funding_source(self, inst: Mapping[str, Any]) -> tuple[str, dict[str, Any], str]:
        if str(inst.get("schema", "")) == "sword-independent-organization":
            treasury_ref = str(inst.get("treasury_ref", ""))
            location_ref = str(inst.get("location_ref", ""))
            if not treasury_ref or not location_ref:
                raise ValueError("independent organization lacks exact treasury or headquarters")
            native_state = self._native_site_state(location_ref)
            if native_state is None:
                raise ValueError("independent organization headquarters lacks a physical regional economy/labor source")
            funding_path = self.owner_path(treasury_ref)
            return funding_path, copy.deepcopy(self.read(funding_path)), native_state
        state_raw = inst.get("state")
        if isinstance(state_raw, str) and state_raw:
            if state_raw.startswith("polity_"):
                polity = self.read(self.owner_path(state_raw))
                treasury_ref = str(polity.get("treasury_ref", ""))
                if not treasury_ref:
                    raise ValueError("sovereign polity institution lacks an exact treasury authority")
                seat = str(inst.get("location_ref", polity.get("seat_claim_ref", "")))
                native_state = self._native_site_state(seat) if seat else None
                if native_state is None:
                    raise ValueError("sovereign polity institution lacks a physical regional economy/labor source")
                funding_path = self.owner_path(treasury_ref)
                return funding_path, copy.deepcopy(self.read(funding_path)), native_state
            state = self._state_key(state_raw)
            path = f"state/states/{state}.json"
            return path, copy.deepcopy(self.read(path)), state
        if str(inst.get("owner_id")) == "force_sword_manor":
            return "state/treasury/treasury-house-tang.json", copy.deepcopy(self.read("state/treasury/treasury-house-tang.json")), "qin"
        raise ValueError("institution project has no lawful funding authority")

    def _location_ancestor_refs(self, location_ref: str) -> set[str]:
        doc = self.read("game/data/world/locations.json")
        rows = {str(row.get("ref")): row for row in doc.get("locations", []) if isinstance(row, Mapping) and row.get("ref")}
        current = str(location_ref); out: set[str] = set(); seen: set[str] = set()
        while current in rows and current not in seen:
            seen.add(current); out.add(current)
            parent = rows[current].get("parent_ref")
            if not isinstance(parent, str):
                break
            current = parent
        return out

    @staticmethod
    def _funds_value(doc: Mapping[str, Any]) -> tuple[str, int]:
        if "treasury_silver" in doc:
            return "treasury_silver", int(doc.get("treasury_silver", 0))
        return "silver", int(doc.get("silver", 0))

    def _start_funded_institution_project(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        ref = str(payload["institution_ref"])
        p = self.owner_path(ref)
        inst = copy.deepcopy(self.read(p))
        projects = inst.setdefault("projects", [])
        project_ref = str(payload.get("project_ref", "project_" + command.digest[:8]))
        if any(str(x.get("project_ref")) == project_ref and str(x.get("status")) not in {"completed", "cancelled"} for x in projects):
            raise ValueError("active project_ref already exists")
        magnitude = max(1, int(payload.get("magnitude", 1)))
        kind = str(payload.get("kind", "capacity"))
        effect = dict(payload.get("effect", {})) if isinstance(payload.get("effect"), Mapping) else {}
        rules = self._civil_rules().get("institution_projects", {})
        physical_work: dict[str, Any] | None = None
        land_registry_pending: dict[str, Any] | None = None
        land_reservation: dict[str, Any] | None = None
        if kind in {"infrastructure", "settlement_foundation"}:
            if kind == "settlement_foundation":
                blueprint_ref = "settlement_foundation_package"
                target_site_ref = str(effect.get("source_site_ref", ""))
                if not target_site_ref or not str(effect.get("new_settlement_name", "")).strip():
                    raise ValueError("settlement foundation requires effect.source_site_ref and effect.new_settlement_name")
                initial_settlers = max(1, int(effect.get("initial_settlers", 0)))
                if initial_settlers > 1000:
                    raise ValueError("initial settlement foundation package physically supports at most 1,000 initial settlers")
            else:
                blueprint_ref = str(effect.get("infrastructure_blueprint_ref", ""))
                target_site_ref = str(effect.get("target_site_ref", ""))
                if not blueprint_ref or not target_site_ref:
                    raise ValueError("infrastructure project requires effect.infrastructure_blueprint_ref and effect.target_site_ref")
            infrastructure = self.read(INFRASTRUCTURE_PATH)
            if not isinstance((infrastructure.get("sites") if isinstance(infrastructure, Mapping) else None), Mapping) or target_site_ref not in infrastructure.get("sites", {}):
                raise ValueError("project target/source lacks an exact physical settlement-capacity owner")
            territory = self.read("state/territory/control.json")
            target_control = (territory.get("sites", {}).get(target_site_ref, {}) if isinstance(territory, Mapping) else {})
            controller = str(target_control.get("controller", "")) if isinstance(target_control, Mapping) else ""
            administrative_owner = str(inst.get("administrative_owner", ""))
            institution_state = str(inst.get("state", ""))
            authorized = False
            if administrative_owner == "house_tang":
                locations = self.read("game/data/world/locations.json")
                target_row = next((row for row in locations.get("locations", []) if isinstance(row, Mapping) and str(row.get("ref")) == target_site_ref), {})
                authorized = target_site_ref == "loc_tang_manor" or str(target_row.get("private_owner_ref", "")) == "house_tang" or "loc_tang_manor" in self._location_ancestor_refs(target_site_ref)
            elif administrative_owner.startswith("state_"):
                authorized = controller == administrative_owner
            elif institution_state.startswith("polity_"):
                authorized = controller == institution_state
            elif institution_state:
                authorized = controller == f"state_{self._state_key(institution_state)}"
            if not authorized:
                raise PermissionError("institution lacks saved territorial/private authority for the infrastructure target")
            physical_work = infrastructure_work_spec(self.read, blueprint_ref=blueprint_ref, target_site_ref=target_site_ref, quantity=(1 if kind == "settlement_foundation" else magnitude))
            if kind == "infrastructure":
                land_registry_pending = copy.deepcopy(self.read(LAND_STATE_PATH))
                land_reservation = reserve_site_land(
                    land_registry_pending,
                    site_ref=target_site_ref,
                    project_ref=project_ref,
                    work=physical_work,
                    rules=self.read(LAND_RULES_PATH),
                    placement_zone=(str(effect.get("placement_zone")) if effect.get("placement_zone") else None),
                    source_land_category=str(effect.get("source_land_category", "open_developable")),
                )
        funding_path, funding, state = self._project_funding_source(inst)
        funds_key, funds = self._funds_value(funding)
        ep, eco = self._private_economy(state)
        location_ref = str(inst.get("location_ref", ""))
        try:
            site_ref, local_eco = self._local_economy_region(state, eco, location_ref)
        except ValueError:
            site_ref, local_eco = "", eco
        commodities = local_eco.setdefault("commodity_stock", {})
        if physical_work is not None:
            silver_cost = int(physical_work["silver_cost"])
            material_cost = int(physical_work["construction_material_units"])
        else:
            silver_cost = int(rules.get("silver_per_magnitude", 200)) * magnitude
            material_cost = int(rules.get("construction_material_units_per_magnitude", 20)) * magnitude if kind in {"capacity", "construction", "expansion"} else 0
        reserved_resource: dict[str, Any] | None = None
        if kind in {"stock", "resource", "logistics"}:
            resource = str(effect.get("resource", ""))
            if resource not in commodities:
                raise ValueError("resource project requires an exact private-economy commodity source")
            if int(commodities.get(resource, 0)) < magnitude:
                raise ValueError("insufficient physical commodity stock for institution project")
            commodities[resource] -= magnitude
            reserved_resource = {"resource": resource, "quantity": magnitude, "source_ref": f"private_economy_{state}", "regional_source_ref": site_ref or None}
        if funds < silver_cost:
            raise ValueError("institution funding authority lacks required project silver")
        if int(commodities.get("construction_material_units", 0)) < material_cost:
            raise ValueError("insufficient produced construction materials for institution project")
        funding[funds_key] = funds - silver_cost
        local_eco["cash_silver"] = int(local_eco.get("cash_silver", 0)) + silver_cost
        self._record_private_realized_sale(local_eco, amount_silver=silver_cost, at=str(self._world_time()), kind="institution_project_contract", resource=("construction_material_units" if material_cost else None), quantity=material_cost)
        if material_cost:
            commodities["construction_material_units"] = int(commodities.get("construction_material_units", 0)) - material_cost
        if physical_work is not None:
            labor_hours = int(physical_work["labor_hours"])
            labor_floor = max(int(rules.get("minimum_project_hours", 24)), int(physical_work["minimum_calendar_hours"]))
        else:
            capacity = max(1, int(inst.get("capacity", 1)))
            labor_hours = int(rules.get("labor_hours_per_magnitude", 12)) * magnitude
            labor_floor = max(int(rules.get("minimum_project_hours", 24)), int(math.ceil(labor_hours / capacity)))
        current = self._world_time()
        labor_rules = self._civil_rules().get("labor", {})
        population = self.read(f"state/population/{state}.json")
        _pp, population = self._ensure_local_population_ledger(state, copy.deepcopy(population))
        construction_fraction = max(0.0, min(1.0, _fixed(labor_rules.get("construction_labor_fraction_of_craft_workers", 0.12), 0.12)))
        if site_ref:
            local_row = population.get("local_population", {}).get("sites", {}).get(site_ref, {})
            local_civilians = local_row.get("civilian_strata", {}) if isinstance(local_row, Mapping) else {}
            craft_workers = max(0, int(local_civilians.get("craft_and_industry", 0)))
        else:
            craft_workers = max(0, int(population.get("strata", {}).get("craft_and_industry", 0)))
        construction_pool = max(1, int(math.floor(craft_workers * construction_fraction)))
        labor_alloc = eco.setdefault("labor_allocation", {})
        active_projects = labor_alloc.setdefault("projects", {})
        if not isinstance(active_projects, dict):
            raise ValueError("private economy project labor allocation is invalid")
        active_workers = 0
        for raw in active_projects.values():
            if not isinstance(raw, Mapping):
                continue
            release = raw.get("releases_at")
            if isinstance(release, str) and CampaignTime.parse(release) <= current:
                continue
            active_workers += max(0, int(raw.get("workers", 0)))
        available_workers = max(0, construction_pool - active_workers)
        if available_workers <= 0:
            raise ValueError("insufficient unallocated construction workforce for institution project")
        if physical_work is not None:
            schedule = calculate_project_schedule(
                self.read,
                work=physical_work,
                available_workers=available_workers,
                requested_minimum_hours=max(0, int(payload.get("duration_hours", 0))),
            )
            required_workers = int(schedule["construction_workers"])
            duration = int(schedule["duration_hours"])
        else:
            # Non-construction institutional work uses institution capacity rather than
            # physical building-work formulas. Physical construction never assumes
            # 24 hours of productive labor per worker-day.
            duration = max(int(payload.get("duration_hours", 168)), labor_floor)
            required_workers = max(1, int(math.ceil(labor_hours / max(1, duration))))
            schedule = {"construction_workers": required_workers, "duration_hours": duration, "institution_capacity_schedule": True}
        if active_workers + required_workers > construction_pool:
            raise ValueError("insufficient unallocated construction workforce for institution project")
        completes = str(current.add_seconds(duration * 3600))
        active_projects[project_ref] = {
            "workers": required_workers,
            "labor_hours": labor_hours,
            "allocated_at": str(current),
            "releases_at": completes,
            "institution_ref": ref,
            "location_ref": site_ref or location_ref,
            "schedule": copy.deepcopy(schedule),
        }
        labor_alloc["construction_worker_pool"] = construction_pool
        labor_alloc["allocated_construction_workers"] = active_workers + required_workers
        project = {
            "project_ref": project_ref,
            "kind": kind,
            "magnitude": magnitude,
            "status": "active",
            "started_at": str(current),
            "completes_at": completes,
            "effect": effect,
            "physical_work_spec": copy.deepcopy(physical_work),
            "inputs_reserved": {
                "silver": silver_cost,
                "construction_material_units": material_cost,
                "labor_hours": labor_hours,
                "construction_workers": required_workers,
                "funding_ref": funding_path,
                "funding_source_ref": str(funding.get("owner_id", funding_path)),
                "material_source_ref": f"private_economy_{state}",
                "regional_source_ref": site_ref or None,
                "labor_source_ref": f"private_economy_{state}",
                "resource_transfer": reserved_resource,
                "cash_cost_breakdown": copy.deepcopy(physical_work.get("cash_cost_breakdown", {})) if isinstance(physical_work, Mapping) else None,
                "material_equivalent_tonnes": physical_work.get("material_equivalent_tonnes") if isinstance(physical_work, Mapping) else None,
                "labor_hours_by_class": copy.deepcopy(physical_work.get("labor_hours_by_class", {})) if isinstance(physical_work, Mapping) else None,
            },
            "construction_schedule": copy.deepcopy(schedule),
            "land_reservation": copy.deepcopy(land_reservation),
        }
        projects.append(project)
        if land_registry_pending is not None:
            self.put(LAND_STATE_PATH, land_registry_pending)
        self.put(funding_path, funding)
        self._sync_local_economy_aggregate(eco)
        self._write_private_economy(ep, eco)
        self.put(p, inst)
        world_time, metrics = self._advance_seconds(3600)
        self._write_meta(command, world_time)
        return self._result(institution_ref=ref, project_ref=project_ref, completes_at=completes, reserved_inputs=project["inputs_reserved"], world_time=world_time, **metrics)

    def _resolve_funded_project(self, inst: dict[str, Any], project: dict[str, Any], at: str) -> None:
        if not isinstance(project.get("inputs_reserved"), Mapping):
            raise ValueError("active institution project is missing reserved material inputs")
        kind = str(project.get("kind", "capacity"))
        magnitude = max(1, int(project.get("magnitude", 1)))
        effect = project.get("effect", {}) if isinstance(project.get("effect"), Mapping) else {}
        if kind == "infrastructure":
            work = project.get("physical_work_spec")
            if not isinstance(work, Mapping):
                raise ValueError("infrastructure project lost its persisted physical work specification")
            registry = copy.deepcopy(self.read(INFRASTRUCTURE_PATH))
            land = copy.deepcopy(self.read(LAND_STATE_PATH))
            project_ref = str(project.get("project_ref", ""))
            land_result = apply_site_land_reservation(land, site_ref=str(work.get("target_site_ref", "")), project_ref=project_ref)
            record = apply_infrastructure_work(registry, work=work, project_ref=project_ref, completed_at=at)
            self.put(LAND_STATE_PATH, land)
            self.put(INFRASTRUCTURE_PATH, registry)
            project["completed_physical_work"] = record
            project["completed_land_allocation"] = land_result
        elif kind == "settlement_foundation":
            project["completed_settlement_foundation"] = complete_settlement_foundation(self, institution=inst, project=project, at=at)
        elif kind in {"capacity", "construction", "expansion"}:
            inst["capacity"] = max(0, int(inst.get("capacity", 0)) + magnitude)
            fortify_ref = str(effect.get("fortify_location_ref", ""))
            if fortify_ref:
                territory = copy.deepcopy(self.read("state/territory/control.json"))
                site = territory.get("sites", {}).get(fortify_ref) if isinstance(territory, Mapping) else None
                if isinstance(site, dict):
                    site["fortified"] = True
                    site["fortification_completed_at"] = at
                    site["fortification_project_ref"] = str(project.get("project_ref", ""))
                    self.put("state/territory/control.json", territory)
        elif kind in {"backlog", "process"}:
            inst["backlog"] = max(0, int(inst.get("backlog", 0)) - magnitude)
        elif kind in {"stock", "resource", "logistics"}:
            transfer = project.get("inputs_reserved", {}).get("resource_transfer")
            if not isinstance(transfer, Mapping) or int(transfer.get("quantity", 0)) != magnitude:
                raise ValueError("funded resource project is missing exact reserved stock")
            key = str(transfer.get("resource"))
            inst.setdefault("resources", {})[key] = int(inst.get("resources", {}).get(key, 0)) + magnitude
        else:
            inst.setdefault("resolved_effects", {})[kind] = int(inst.get("resolved_effects", {}).get(kind, 0)) + magnitude
        inputs = project.get("inputs_reserved", {})
        source_ref = str(inputs.get("labor_source_ref", "")) if isinstance(inputs, Mapping) else ""
        if source_ref.startswith("private_economy_"):
            state = source_ref.removeprefix("private_economy_")
            ep, eco = self._private_economy(state)
            labor = eco.setdefault("labor_allocation", {})
            projects = labor.setdefault("projects", {})
            if isinstance(projects, dict):
                projects.pop(str(project.get("project_ref", "")), None)
                labor["allocated_construction_workers"] = sum(
                    max(0, int(row.get("workers", 0)))
                    for row in projects.values()
                    if isinstance(row, Mapping)
                )
            self._write_private_economy(ep, eco)
        project["status"] = "completed"
        project["resolved_at"] = at
        project["resolution_basis"] = "reserved silver, materials, conserved aggregate construction workforce and elapsed time"

    def _cancel_funded_project(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        ref = str(payload["institution_ref"])
        project_ref = str(payload["project_ref"])
        path = self.owner_path(ref)
        inst = copy.deepcopy(self.read(path))
        project = next((row for row in inst.setdefault("projects", []) if isinstance(row, dict) and str(row.get("project_ref")) == project_ref), None)
        if not isinstance(project, dict):
            raise ValueError("unknown institution project")
        if str(project.get("status")) != "active":
            raise ValueError("only an active institution project may be cancelled")
        inputs = project.get("inputs_reserved")
        if not isinstance(inputs, Mapping):
            raise ValueError("active institution project is missing reserved material inputs")

        now = self._world_time()
        started = CampaignTime.parse(str(project.get("started_at")))
        completes = CampaignTime.parse(str(project.get("completes_at")))
        total_seconds = max(1, started.seconds_until(completes))
        elapsed_seconds = max(0, min(total_seconds, started.seconds_until(now)))
        progress = max(0.0, min(1.0, elapsed_seconds / total_seconds))
        unused = max(0.0, 1.0 - progress)

        funding_path = str(inputs.get("funding_ref", ""))
        source_ref = str(inputs.get("material_source_ref", inputs.get("labor_source_ref", "")))
        if not funding_path or not source_ref.startswith("private_economy_"):
            raise ValueError("funded project cancellation is missing exact refund authorities")
        state = source_ref.removeprefix("private_economy_")
        funding = copy.deepcopy(self.read(funding_path))
        funds_key, _funds = self._funds_value(funding)
        ep, eco = self._private_economy(state)
        regional_source_ref = str(inputs.get("regional_source_ref", ""))
        local_eco = eco
        if regional_source_ref:
            regions = eco.get("local_regions", {}).get("regions", {}) if isinstance(eco.get("local_regions"), Mapping) else {}
            row = regions.get(regional_source_ref) if isinstance(regions, Mapping) else None
            if isinstance(row, dict):
                local_eco = row
        commodities = local_eco.setdefault("commodity_stock", {})

        reserved_silver = max(0, int(inputs.get("silver", 0)))
        silver_refund_due = max(0, int(math.floor(reserved_silver * unused)))
        silver_refund = min(silver_refund_due, max(0, int(local_eco.get("cash_silver", 0))))
        if silver_refund:
            local_eco["cash_silver"] = int(local_eco.get("cash_silver", 0)) - silver_refund
            funding[funds_key] = int(funding.get(funds_key, 0)) + silver_refund

        reserved_material = max(0, int(inputs.get("construction_material_units", 0)))
        material_refund = max(0, int(math.floor(reserved_material * unused)))
        if material_refund:
            commodities["construction_material_units"] = int(commodities.get("construction_material_units", 0)) + material_refund

        resource_refund: dict[str, Any] | None = None
        transfer = inputs.get("resource_transfer")
        if isinstance(transfer, Mapping):
            key = str(transfer.get("resource", ""))
            qty = max(0, int(transfer.get("quantity", 0)))
            refund_qty = max(0, int(math.floor(qty * unused)))
            if key and refund_qty:
                commodities[key] = int(commodities.get(key, 0)) + refund_qty
                resource_refund = {"resource": key, "quantity": refund_qty}

        labor = eco.setdefault("labor_allocation", {})
        projects = labor.setdefault("projects", {})
        released_workers = 0
        if isinstance(projects, dict):
            row = projects.pop(project_ref, None)
            if isinstance(row, Mapping):
                released_workers = max(0, int(row.get("workers", 0)))
            labor["allocated_construction_workers"] = sum(max(0, int(row.get("workers", 0))) for row in projects.values() if isinstance(row, Mapping))

        land_release = None
        work = project.get("physical_work_spec")
        if str(project.get("kind")) == "infrastructure" and isinstance(work, Mapping):
            land = copy.deepcopy(self.read(LAND_STATE_PATH))
            land_release = release_site_land_reservation(
                land, site_ref=str(work.get("target_site_ref", "")), project_ref=project_ref
            )
            self.put(LAND_STATE_PATH, land)

        refunds = {
            "silver_due": silver_refund_due,
            "silver_refunded": silver_refund,
            "silver_unrecoverable_or_already_spent": max(0, silver_refund_due - silver_refund),
            "construction_material_units": material_refund,
            "resource_transfer": resource_refund,
            "construction_workers_released": released_workers,
            "land_reservation_released": land_release,
        }
        project["status"] = "cancelled"
        project["cancelled_at"] = str(now)
        project["progress_at_cancellation"] = round(progress, 6)
        project["refunds"] = refunds
        project["consumed_inputs"] = {
            "silver": reserved_silver - silver_refund,
            "construction_material_units": reserved_material - material_refund,
            "labor_hours_fraction": round(progress, 6),
        }
        project["cancellation_basis"] = "unused reserved materials and recoverable cash were returned; elapsed work remains consumed; aggregate construction workers were released"
        self.put(funding_path, funding)
        self._sync_local_economy_aggregate(eco)
        self._write_private_economy(ep, eco)
        self.put(path, inst)
        world_time, metrics = self._advance_seconds(1800)
        self._write_meta(command, world_time)
        return self._result(institution_ref=ref, project_ref=project_ref, status="cancelled", progress=round(progress, 6), refunds=refunds, world_time=world_time, **metrics)

    @staticmethod
    def _house_polity_ref(house_ref: str) -> str:
        return "polity_" + str(house_ref).removeprefix("house_")

    def _ensure_polity_institutions(self, polity_ref: str, polity: dict[str, Any], at: str) -> dict[str, str]:
        """Materialize the standard sovereign bureaucracy for a recognized polity.

        These offices are exact institutions, not free effects.  Their capacities
        constrain administration/recruitment and their projects still consume the
        polity treasury plus physical regional labor/materials. A dynamic polity
        therefore joins the same institutional layer as the seven core state owners.
        """
        if str(polity.get("status", "")) != "recognized_state":
            refs = polity.get("institution_refs", {})
            return {str(k): str(v) for k, v in refs.items()} if isinstance(refs, Mapping) else {}
        seat = str(polity.get("seat_claim_ref", "")) or next((str(x) for x in polity.get("occupied_site_refs", []) if isinstance(x, str)), "")
        if not seat:
            raise ValueError("recognized polity lacks an exact territorial seat for institutions")
        admin = max(10, int(polity.get("administrative_capacity", 25)))
        slug = polity_ref.removeprefix("polity_")
        specs = {
            "regional_administration": (max(10, admin), "administer controlled territory, tax compliance, loyalty and resistance"),
            "military_bureau": (max(10, admin), "review exact sovereign formations, commands, readiness and operations"),
            "recruitment_office": (max(100, admin * 50), "administer conserved recruitment from populations lawfully accessible to the polity"),
            "granary_depot_office": (max(10, admin), "procure physical grain from controlled regional economies using sovereign treasury funds"),
            "fortification_bureau": (max(10, admin), "manage material-funded fortification projects at controlled sites"),
            "horse_administration": (max(10, admin), "account for mounts already held by sovereign formations; never create horses"),
        }
        refs: dict[str, str] = {}
        for kind, (capacity, policy) in specs.items():
            ref = f"inst_{slug}_{kind}"
            refs[kind] = ref
            try:
                path = self.owner_path(ref)
                inst = copy.deepcopy(self.read(path))
            except (KeyError, ValueError, FileNotFoundError):
                path = f"state/institutions/{ref}.json"
                inst = {
                    "schema": "sword-institution",
                    "owner_id": ref,
                    "name": f"{polity.get('name', polity_ref)} {kind.replace('_', ' ').title()}",
                    "state": polity_ref,
                    "sovereign_polity_ref": polity_ref,
                    "location_ref": seat,
                    "kind": kind,
                    "capacity": capacity,
                    "backlog": 0,
                    "projects": [],
                    "resources": {},
                    "staffing": "aggregate",
                    "policy": policy,
                    "created_at": at,
                    "last_review": at,
                }
                self.put(path, inst)
                self._register_owner(ref, path)
            else:
                inst["state"] = polity_ref
                inst["sovereign_polity_ref"] = polity_ref
                inst.setdefault("location_ref", seat)
                inst.setdefault("capacity", capacity)
                inst.setdefault("projects", [])
                inst.setdefault("resources", {})
                self.put(path, inst)
        polity["institution_refs"] = refs
        return refs

    def _polity_institution_capacity(self, polity: Mapping[str, Any], kind: str, default: int = 0) -> int:
        refs = polity.get("institution_refs", {}) if isinstance(polity.get("institution_refs"), Mapping) else {}
        ref = refs.get(kind)
        if not isinstance(ref, str):
            return max(0, int(default))
        try:
            inst = self.read(self.owner_path(ref))
        except (KeyError, ValueError, FileNotFoundError):
            return max(0, int(default))
        return max(0, int(inst.get("capacity", default)))

    def _proclaim_house_territorial_authority(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Create a sovereign polity only from an exact House-backed occupation.

        Proclamation is a political status transition, not a territorial transfer.
        The House must first possess a surviving formation in an exact occupation
        operation at the claimed seat.  A subsequent territorial_consequence may
        transfer the site to the polity if the same military evidence still supports
        it.  This prevents a House identity from becoming a state merely by prose.
        """
        house_ref = str(payload.get("house_ref", "house_tang"))
        house_path = self.owner_path(house_ref)
        house = copy.deepcopy(self.read(house_path))
        location_ref = str(payload["location_ref"])
        operation_ref = str(payload["operation_ref"])
        index = self.read("state/operations/index.json")
        operation_path = index.get("operations", {}).get(operation_ref) if isinstance(index, Mapping) else None
        if not isinstance(operation_path, str):
            raise ValueError("sovereignty proclamation requires an exact saved occupation operation")
        operation = self.read(operation_path)
        if str(operation.get("location_ref", operation.get("target_location_ref", ""))) != location_ref:
            raise ValueError("sovereignty proclamation operation does not concern the claimed seat")
        if str(operation.get("status", "")) not in {"occupied", "completed", "active"}:
            raise ValueError("sovereignty proclamation requires a live or completed territorial occupation")
        formation_refs = [str(x) for x in operation.get("formation_refs", [])]
        if not formation_refs:
            raise ValueError("sovereignty proclamation requires a surviving occupation formation")
        military_force_refs: set[str] = set()
        military_authority_refs: set[str] = {house_ref}
        lawful_occupier = False
        house_force = str(house.get("military_force_ref", ""))
        operation_authorities = {str(x) for x in operation.get("administrative_authorities", []) if isinstance(x, str)} if isinstance(operation.get("administrative_authorities"), list) else set()
        operation_authority = str(operation.get("administrative_authority", ""))
        if operation_authority:
            operation_authorities.add(operation_authority)
        explicit_grants = {str(x) for x in operation.get("territorial_grants", []) if isinstance(x, str)} if isinstance(operation.get("territorial_grants"), list) else set()
        if str(operation.get("sovereign_entitlement_ref", "")):
            explicit_grants.add(str(operation.get("sovereign_entitlement_ref")))
        anticipated_polity_ref = self._house_polity_ref(house_ref)
        operation_house_entitlement = (
            house_ref in operation_authorities
            or house_ref in explicit_grants
            or anticipated_polity_ref in explicit_grants
        )
        for formation_ref in formation_refs:
            _fp, formation = self._load_formation(formation_ref)
            if int(formation.get("personnel", 0)) <= 0 or str(formation.get("location_ref", "")) != location_ref:
                continue
            administrative_owner = str(formation.get("administrative_owner", ""))
            force_ref = str(formation.get("owner_force_ref", ""))
            force_house_owned = False
            if force_ref:
                try:
                    force = self.read(self.owner_path(force_ref))
                    force_house_owned = str(force.get("administrative_owner", "")) == house_ref
                except (KeyError, ValueError, FileNotFoundError):
                    force_house_owned = False
            formation_house_owned = administrative_owner == house_ref or force_house_owned
            if formation_house_owned or operation_house_entitlement:
                lawful_occupier = True
                # A sovereign entitlement/grant may lawfully allow the House to
                # claim the occupied seat, but it does *not* transfer custody of
                # the granting state's army.  Only exact House-owned military
                # force records become polity military backing.
                if force_ref and formation_house_owned:
                    military_force_refs.add(force_ref)
                if administrative_owner and administrative_owner == house_ref:
                    military_authority_refs.add(administrative_owner)
        if house_force:
            try:
                saved_house_force = self.read(self.owner_path(house_force))
            except (KeyError, ValueError, FileNotFoundError):
                saved_house_force = None
            if isinstance(saved_house_force, Mapping) and str(saved_house_force.get("administrative_owner", "")) == house_ref:
                military_force_refs.add(house_force)
        if not lawful_occupier:
            raise PermissionError("House sovereignty requires House-owned military custody, House administrative occupation authority, or an explicit saved territorial grant; battlefield command authority alone is insufficient")

        polity_ref = anticipated_polity_ref
        owners = self.read("state/index/owner-index.json").get("owners", {})
        existing_path = owners.get(polity_ref) if isinstance(owners, Mapping) else None
        if isinstance(existing_path, str):
            polity = copy.deepcopy(self.read(existing_path))
            if str(polity.get("sovereign_house_ref")) != house_ref:
                raise ValueError("polity identity is already owned by another sovereign House")
        else:
            treasury_ref = str(house.get("treasury_ref", ""))
            if not treasury_ref:
                raise ValueError("sovereign House lacks an exact treasury authority")
            polity_path = f"state/politics/polities/{polity_ref}.json"
            polity = {
                "schema": "sword-polity",
                "owner_id": polity_ref,
                "polity_ref": polity_ref,
                "name": str(payload.get("polity_name", "Territorial Authority")),
                "sovereign_house_ref": house_ref,
                "founding_actor_ref": command.actor_id,
                "status": "territorial_authority",
                "recognition_status": "unrecognized",
                "recognized_by": [],
                "treasury_ref": treasury_ref,
                "military_force_refs": sorted(x for x in military_force_refs if x),
                "military_authority_refs": sorted(x for x in military_authority_refs if x),
                "seat_claim_ref": location_ref,
                "communication_origin_state": self._native_site_state(location_ref),
                "occupied_site_refs": [],
                "administrative_capacity": max(10, int(self._civil_rules().get("occupation", {}).get("initial_polity_administrative_capacity", 25))),
                "created_at": str(self._world_time()),
                "provenance": {
                    "operation_ref": operation_ref,
                    "location_ref": location_ref,
                    "formation_refs": formation_refs,
                    "basis": "House-backed exact occupation preceded sovereign proclamation",
                },
                "known_threats": {},
            }
            self.put(polity_path, polity)
            self._register_owner(polity_ref, polity_path)
            existing_path = polity_path
        polity["military_force_refs"] = sorted(set(str(x) for x in polity.get("military_force_refs", [])) | {x for x in military_force_refs if x})
        polity["military_authority_refs"] = sorted(set(str(x) for x in polity.get("military_authority_refs", [])) | {x for x in military_authority_refs if x})
        polity.setdefault("proclamations", []).append({
            "at": str(self._world_time()), "actor_ref": command.actor_id, "location_ref": location_ref,
            "operation_ref": operation_ref, "status": "territorial_authority",
        })
        polity["proclamations"] = polity["proclamations"][-16:]
        house["sovereignty_ref"] = polity_ref
        self.put(str(existing_path), polity)
        self.put(house_path, house)
        world_time, metrics = self._advance_seconds(2 * 3600)
        self._write_meta(command, world_time)
        return self._result(house_ref=house_ref, action="proclaim_territorial_authority", polity_ref=polity_ref, status=polity["status"], recognition_status=polity["recognition_status"], seat_claim_ref=location_ref, world_time=world_time, **metrics)

    def _apply_polity_recognition(self, recognizer_ref: str, polity_ref: str, at: str) -> dict[str, Any]:
        polity_path = self.owner_path(polity_ref)
        polity = copy.deepcopy(self.read(polity_path))
        if str(polity.get("schema")) != "sword-polity" or str(polity.get("status")) == "dissolved":
            raise ValueError("recognition target is not an active sovereign polity")
        recognized = [str(x) for x in polity.setdefault("recognized_by", [])]
        if recognizer_ref not in recognized:
            recognized.append(recognizer_ref)
        polity["recognized_by"] = sorted(set(recognized))
        threshold = max(1, int(self._civil_rules().get("occupation", {}).get("recognized_state_threshold", 2)))
        if len(polity["recognized_by"]) >= threshold:
            polity["recognition_status"] = "recognized"
            polity["status"] = "recognized_state"
            self._ensure_polity_institutions(polity_ref, polity, at)
        else:
            polity["recognition_status"] = "partially_recognized"
            if polity.get("occupied_site_refs"):
                polity["status"] = "proto_state"
        polity.setdefault("recognition_history", []).append({"at": at, "recognizer_ref": recognizer_ref, "action": "recognize"})
        polity["recognition_history"] = polity["recognition_history"][-24:]
        self.put(polity_path, polity)
        return polity

    def _recognize_polity(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        state = self._state_key(payload.get("state", "qin"))
        polity_ref = str(payload["polity_ref"])
        at = str(self._world_time())
        polity = self._apply_polity_recognition(f"state_{state}", polity_ref, at)
        world_time, metrics = self._advance_seconds(2 * 3600)
        self._write_meta(command, world_time)
        return self._result(state=state, action="recognize_polity", polity_ref=polity_ref, status=polity["status"], recognition_status=polity["recognition_status"], recognized_by=polity["recognized_by"], world_time=world_time, **metrics)

    def _polity_garrison_strength(self, polity: Mapping[str, Any], location_ref: str) -> int:
        authority_refs = {str(x) for x in polity.get("military_authority_refs", []) if isinstance(x, str)}
        authority_refs.add(str(polity.get("sovereign_house_ref", "")))
        force_refs = {str(x) for x in polity.get("military_force_refs", []) if isinstance(x, str)}
        total = 0
        for formation_ref in self._formations_at(location_ref):
            try:
                _path, formation = self._load_formation(formation_ref)
            except ValueError:
                continue
            # Battlefield command is deliberately not sovereign custody.  A state
            # can lend Wei command of its formation without lending House Tang the
            # right to use those soldiers as its occupation garrison.
            if str(formation.get("owner_force_ref", "")) in force_refs or str(formation.get("administrative_owner", "")) in authority_refs:
                total += max(0, int(formation.get("personnel", 0)))
        return total

    def _settle_house_polity(self, house_ref: str, occurrences: int, at: str, *, months: int | None = None) -> None:
        """Settle taxes, occupation capacity and local recruiting for a House polity."""
        house_path = self.owner_path(house_ref)
        house = copy.deepcopy(self.read(house_path))
        polity_ref = str(house.get("sovereignty_ref", ""))
        if not polity_ref:
            return
        try:
            polity_path = self.owner_path(polity_ref)
        except (KeyError, ValueError):
            return
        polity = copy.deepcopy(self.read(polity_path))
        if str(polity.get("status", "")) == "dissolved":
            return
        treasury_ref = str(polity.get("treasury_ref", house.get("treasury_ref", "")))
        treasury_path = self.owner_path(treasury_ref)
        treasury = copy.deepcopy(self.read(treasury_path))
        funds_key, _funds = self._funds_value(treasury)
        # Materialize local allocation views before taking the mutable territory
        # snapshot.  `_ensure_local_site_baselines` persists those views, so doing
        # it later from inside the settlement loop would let this function's stale
        # snapshot overwrite them at the final put.
        territory_seed = self.read("state/territory/control.json")
        native_states = {
            native
            for location_ref, site in territory_seed.get("sites", {}).items()
            if isinstance(site, Mapping)
            for native in [self._native_site_state(str(location_ref))]
            if native is not None
        }
        for native in sorted(native_states):
            self._ensure_local_site_baselines(native)
        territory = copy.deepcopy(self.read("state/territory/control.json"))
        rules = self._civil_rules().get("occupation", {})
        occurrences = max(1, int(occurrences))
        months = max(1, int(months if months is not None else occurrences))
        if str(polity.get("status", "")) == "recognized_state" and not isinstance(polity.get("institution_refs"), Mapping):
            self._ensure_polity_institutions(polity_ref, polity, at)
        routes = self.read("game/data/world/routes.json").get("routes", [])
        controlled: list[str] = []
        revenue_rows: list[dict[str, Any]] = []
        recruitment_rows: list[dict[str, Any]] = []
        force_ref = next((str(x) for x in polity.get("military_force_refs", []) if str(x).startswith("force_house_")), str(house.get("military_force_ref", "")))
        force_path = self.owner_path(force_ref) if force_ref else None
        force = copy.deepcopy(self.read(force_path)) if force_path else None
        recruitment_unit_cost = max(1, int(self.read("game/data/mechanics/economy.json").get("military_finance", {}).get("recruitment_and_basic_issue_cost_silver_per_person", 12)))
        polity_admin = max(0, int(polity.get("administrative_capacity", 0)))
        regional_admin_capacity = self._polity_institution_capacity(polity, "regional_administration", polity_admin)
        effective_admin_capacity = max(1, min(max(1, polity_admin), max(1, regional_admin_capacity)))
        recruitment_per_admin = max(0, int(rules.get("polity_recruitment_personnel_per_admin_capacity_per_month", 10)))
        default_recruitment_capacity = polity_admin * recruitment_per_admin
        recruitment_office_capacity = self._polity_institution_capacity(polity, "recruitment_office", default_recruitment_capacity)
        mobilization = self._polity_mobilization_effects(polity)
        effective_recruitment_capacity = max(0, int(math.floor(recruitment_office_capacity * float(mobilization["recruitment_factor"]))))
        remaining_recruitment_capacity = effective_recruitment_capacity * months
        polity.setdefault("administrative_services", {}).update({
            "regional_administration_capacity": effective_admin_capacity,
            "military_staff_capacity": self._polity_institution_capacity(polity, "military_bureau", polity_admin),
            "diplomatic_capacity": max(1, polity_admin // 4),
            "recruitment_capacity_per_month": effective_recruitment_capacity,
            "mobilization_policy": mobilization["value"],
            "basis": "exact sovereign institution capacities where present; proto-state fallback remains bounded by saved administrative capacity",
        })

        for location_ref, site in sorted(territory.get("sites", {}).items()):
            if not isinstance(site, dict) or str(site.get("controller")) != polity_ref:
                continue
            controlled.append(str(location_ref))
            native_state, local_population = self._occupation_population_estimate(str(location_ref))
            if native_state is None or local_population <= 0:
                continue
            gov = site.setdefault("governance", {})
            if not gov:
                gov.update({
                    "military_controller": polity_ref,
                    "occupation_started_at": at,
                    "administration": int(rules.get("initial_administration", 20)),
                    "elite_cooperation": int(rules.get("initial_elite_cooperation", 25)),
                    "civilian_loyalty": int(rules.get("initial_civilian_loyalty", 20)),
                    "resistance": int(rules.get("initial_resistance", 70)),
                    "tax_compliance": int(rules.get("initial_tax_compliance", 20)),
                    "recruitment_access": int(rules.get("initial_recruitment_access", 10)),
                    "food_security": int(rules.get("initial_food_security", 50)),
                    "status": "military_occupation",
                })
            garrison = self._polity_garrison_strength(polity, str(location_ref))
            required = max(100, int(math.ceil(local_population / 1000.0 * max(0.1, _fixed(rules.get("garrison_personnel_per_thousand_residents", 2.0), 2.0)))))
            garrison_factor = max(0.0, min(1.5, garrison / required))
            policy_effects = self._occupation_policy_effects(gov)
            governor_effects = self._governor_effects(polity, str(location_ref))
            budget_due = max(0, int(math.ceil(local_population / 1000.0 * _fixed(rules.get("administration_silver_per_thousand_residents_per_review", 20.0), 20.0) * occurrences * float(policy_effects.get("budget_multiplier", 1.0)))))
            budget_paid = min(budget_due, max(0, int(treasury.get(funds_key, 0))))
            treasury[funds_key] = max(0, int(treasury.get(funds_key, 0)) - budget_paid)
            local_ep, local_eco = self._private_economy(native_state)
            _budget_site_ref, budget_region = self._local_economy_region(native_state, local_eco, str(location_ref))
            budget_region["cash_silver"] = int(budget_region.get("cash_silver", 0)) + budget_paid
            self._sync_local_economy_aggregate(local_eco)
            self._write_private_economy(local_ep, local_eco)
            budget_factor = 1.0 if budget_due <= 0 else budget_paid / budget_due
            adjacent_support = 0
            for route in routes if isinstance(routes, list) else []:
                if not isinstance(route, Mapping):
                    continue
                a = str(route.get("a", route.get("from", ""))); b = str(route.get("b", route.get("to", "")))
                if str(location_ref) not in {a, b}:
                    continue
                other = b if a == str(location_ref) else a
                other_site = territory.get("sites", {}).get(other)
                if isinstance(other_site, Mapping) and str(other_site.get("controller")) == f"state_{native_state}":
                    adjacent_support += 1
            admin_capacity = effective_admin_capacity
            office_factor = max(0.25, min(1.5, admin_capacity / 50.0))
            destabilization = adjacent_support * int(rules.get("adjacent_enemy_support_pressure", 3)) + max(0, int(round((1.0 - min(1.0, garrison_factor)) * 12))) + max(0, int(round((1.0 - budget_factor) * 10)))
            destabilization += int(round(float(policy_effects.get("resistance_delta", 0)))) + int(governor_effects.get("resistance_delta", 0))
            progress = int(round(max(1, int(rules.get("regional_administration_gain_per_review", 4))) * occurrences * office_factor * min(1.0, garrison_factor) * budget_factor * float(policy_effects.get("administration_multiplier", 1.0)) * float(governor_effects.get("administration_multiplier", 1.0))))
            gov["administration"] = _clamp(int(gov.get("administration", 0)) + progress - max(0, destabilization // 8))
            suppression = max(1, int(round(garrison_factor * 3 + budget_factor * 2 + float(policy_effects.get("suppression_bonus", 0)))))
            gov["resistance"] = _clamp(int(gov.get("resistance", 0)) + destabilization - suppression)
            elite_step = (1 if budget_factor >= 1.0 and garrison_factor >= 0.75 else -1) * occurrences + int(round(float(policy_effects.get("elite_delta", 0)))) + int(governor_effects.get("elite_delta", 0))
            gov["elite_cooperation"] = _clamp(int(gov.get("elite_cooperation", 0)) + elite_step)
            loyalty_step = int(round((gov["administration"] - 50) / 30.0 - gov["resistance"] / 50.0 + float(policy_effects.get("loyalty_delta", 0)) + int(governor_effects.get("loyalty_delta", 0))))
            gov["civilian_loyalty"] = _clamp(int(gov.get("civilian_loyalty", 0)) + loyalty_step)
            gov["food_security"] = _clamp(int(gov.get("food_security", 50)) + int(round(float(policy_effects.get("food_security_delta", 0)))))
            gov["displacement_pressure"] = _clamp(int(gov.get("displacement_pressure", 0)) + int(round(float(policy_effects.get("displacement_delta", 0)))))

            if gov["resistance"] >= int(rules.get("open_revolt_resistance_threshold", 88)) and garrison_factor <= _fixed(rules.get("open_revolt_max_garrison_factor", 0.65), 0.65):
                rebel = self._ensure_occupation_rebel_force(location_ref=str(location_ref), native_state=native_state, controller_state=polity_ref, local_population=local_population, governance=gov, at=at)
                support = self._support_occupation_rebel_force(refs=rebel, native_state=native_state, at=at)
                gov["status"] = "open_revolt"; gov["tax_compliance"] = 0; gov["recruitment_access"] = 0
                prior_revolt = gov.get("revolt") if isinstance(gov.get("revolt"), Mapping) else {}
                gov["revolt"] = {"active": True, "since": prior_revolt.get("since", at), "initial_personnel": int(prior_revolt.get("initial_personnel", rebel.get("personnel", 0))), **{k: rebel.get(k) for k in ("faction_ref", "force_ref", "operation_ref")}, "formation_refs": [rebel.get("formation_ref")] if rebel.get("formation_ref") else [], "personnel": int(rebel.get("personnel", 0)), "local_support_transfer": support}
                polity.setdefault("known_threats", {})[f"occupation_revolt:{location_ref}"] = {"kind": "occupation_revolt", "severity": int(gov["resistance"]), "location_ref": str(location_ref), "force_ref": rebel.get("force_ref"), "formation_refs": [rebel.get("formation_ref")] if rebel.get("formation_ref") else [], "observed_at": at}
            else:
                revolt_doc = gov.get("revolt") if isinstance(gov.get("revolt"), Mapping) else {}
                rebel_force_ref = str(revolt_doc.get("force_ref", ""))
                rebel_personnel = 0
                if rebel_force_ref:
                    try:
                        rebel_force = self.read(self.owner_path(rebel_force_ref))
                        rebel_personnel = max(0, int(rebel_force.get("headcount", 0)))
                    except (KeyError, ValueError, FileNotFoundError):
                        rebel_personnel = 0
                initial_rebels = max(1, int(revolt_doc.get("initial_personnel", revolt_doc.get("personnel", rebel_personnel or 1))))
                containment_ceiling = max(int(rules.get("revolt_containment_survivor_floor", 50)), int(math.floor(initial_rebels * _fixed(rules.get("revolt_containment_survivor_fraction", 0.10), 0.10))))
                can_contain = gov.get("status") == "open_revolt" and gov["resistance"] <= int(rules.get("revolt_contained_resistance_threshold", 55)) and garrison_factor >= 1.0 and rebel_personnel <= containment_ceiling
                if can_contain:
                    refs = {
                        "faction_ref": revolt_doc.get("faction_ref"),
                        "force_ref": revolt_doc.get("force_ref"),
                        "formation_ref": next(iter(revolt_doc.get("formation_refs", [])), None) if isinstance(revolt_doc.get("formation_refs"), list) else None,
                        "operation_ref": revolt_doc.get("operation_ref"),
                    }
                    demobilized = self._contain_occupation_rebel_force(refs=refs, native_state=native_state, at=at) if rebel_force_ref else 0
                    gov["status"] = "military_occupation"
                    gov["revolt"] = {**dict(revolt_doc), "active": False, "contained_at": at, "demobilized_survivors": demobilized}
                    polity.setdefault("known_threats", {}).pop(f"occupation_revolt:{location_ref}", None)
                else:
                    gov["tax_compliance"] = 0
                    gov["recruitment_access"] = 0
            if gov.get("status") != "open_revolt":
                base_tax = min(int(gov.get("administration", 0)), int(gov.get("elite_cooperation", 0)), max(0, 100 - int(gov.get("resistance", 0)) // 2))
                gov["tax_compliance"] = _clamp(base_tax + int(round(float(policy_effects.get("tax_compliance_delta", 0)))))
                base_recruit = min(80, int(gov.get("civilian_loyalty", 0)), int(gov.get("administration", 0)), max(0, 100 - int(gov.get("resistance", 0))))
                gov["recruitment_access"] = _clamp(base_recruit + int(round(float(policy_effects.get("recruitment_access_delta", 0)))))
            gov["occupation_capacity"] = {"local_population_estimate": local_population, "garrison_personnel": garrison, "required_garrison_personnel": required, "garrison_factor": round(garrison_factor, 4), "administrative_capacity": admin_capacity, "budget_due_silver": budget_due, "budget_paid_silver": budget_paid, "adjacent_former_controller_routes": adjacent_support, "policy_effects": {k:v for k,v in policy_effects.items() if k != "values"}, "policy_values": policy_effects.get("values", {}), "governor_effects": governor_effects}
            gov["last_administration_review"] = at

            if gov.get("status") != "open_revolt":
                baseline = site.get("local_baseline") if isinstance(site.get("local_baseline"), Mapping) else {}
                per_site = max(0.0, _fixed(baseline.get("monthly_tax_base_silver", 0), 0.0))
                due = max(0, int(round(per_site * (int(gov.get("tax_compliance", 0)) / 100.0) * _fixed(rules.get("foreign_tax_realization_factor", 0.85), 0.85) * months)))
                local_ep, local_eco = self._private_economy(native_state)
                _tax_site, tax_region = self._local_economy_region(native_state, local_eco, str(location_ref))
                paid = min(due, max(0, int(tax_region.get("cash_silver", 0))))
                tax_region["cash_silver"] = max(0, int(tax_region.get("cash_silver", 0)) - paid)
                treasury[funds_key] = int(treasury.get(funds_key, 0)) + paid
                self._sync_local_economy_aggregate(local_eco)
                self._write_private_economy(local_ep, local_eco)
                revenue_rows.append({"location_ref": str(location_ref), "native_state": native_state, "due_silver": due, "collected_silver": paid, "tax_compliance": int(gov.get("tax_compliance", 0))})

                if force is not None and int(gov.get("recruitment_access", 0)) >= int(rules.get("minimum_recruitment_access", 20)):
                    pop_path = f"state/population/{native_state}.json"; pop = copy.deepcopy(self.read(pop_path)); _lp, pop, local_row = self._local_population_row(native_state, str(location_ref), pop)
                    agricultural = min(max(0, int(pop.get("strata", {}).get("agricultural", 0))), max(0, int(local_row.get("agricultural_available", 0))), max(0, int(local_row.get("civilian_population", 0))))
                    quota = max(0, int(math.floor(local_population * _fixed(rules.get("occupation_recruitment_fraction_per_review", 0.001), 0.001) * int(gov.get("recruitment_access", 0)) / 100.0 * occurrences)))
                    affordable = max(0, int(treasury.get(funds_key, 0))) // recruitment_unit_cost
                    recruits = min(agricultural, quota, affordable, remaining_recruitment_capacity)
                    if recruits > 0:
                        pop["strata"]["agricultural"] = int(pop["strata"].get("agricultural", 0)) - recruits
                        pop["strata"]["foreign_military_service"] = int(pop["strata"].get("foreign_military_service", 0)) + recruits
                        moved_local = self._consume_local_recruitment(pop, native_state, str(location_ref), recruits, service_key="serving_foreign_military", source_stratum="agricultural", service_owner_ref=force_ref)
                        if moved_local != recruits:
                            raise ValueError("polity recruitment exceeded the locality's conserved civilian manpower")
                        ensure_cohort_ledger(force, at=at)
                        add_recruits(force, "house_guard", recruits, location_ref=str(location_ref))
                        record_recruitment_cohort(force, role="house_guard", count=recruits, location_ref=str(location_ref), source_population_ref=f"population_{native_state}", source_stratum="agricultural", recruited_at=at, profile_registry=self.read("game/data/mil/recruitment-cohort-profiles.json"), selection_profile="household_retainer_screen", provenance_ref=f"polity_recruitment:{polity_ref}:{location_ref}:{at}")
                        force["authorized_strength"] = max(int(force.get("authorized_strength", 0)), int(force.get("headcount", 0)))
                        cost = recruits * recruitment_unit_cost
                        treasury[funds_key] = max(0, int(treasury.get(funds_key, 0)) - cost)
                        local_ep, local_eco = self._private_economy(native_state); _pay_site, pay_region = self._local_economy_region(native_state, local_eco, str(location_ref)); pay_region["cash_silver"] = int(pay_region.get("cash_silver", 0)) + cost; self._sync_local_economy_aggregate(local_eco); self._write_private_economy(local_ep, local_eco)
                        self.put(pop_path, pop)
                        remaining_recruitment_capacity = max(0, remaining_recruitment_capacity - recruits)
                        recruitment_rows.append({"location_ref": str(location_ref), "native_state": native_state, "personnel": recruits, "payment_silver": cost})

        polity["occupied_site_refs"] = sorted(set(controlled))
        if controlled and polity.get("status") == "territorial_authority":
            polity["status"] = "proto_state"
        if len(polity.get("recognized_by", [])) >= max(1, int(rules.get("recognized_state_threshold", 2))):
            polity["status"] = "recognized_state"; polity["recognition_status"] = "recognized"
        polity.setdefault("civil_finance", {})["last_close"] = at
        polity["civil_finance"]["revenue_sources"] = revenue_rows[-32:]
        polity["civil_finance"]["recruitment"] = recruitment_rows[-32:]
        polity["civil_finance"]["treasury_ref"] = treasury_ref
        polity["civil_finance"]["recruitment_capacity_remaining"] = remaining_recruitment_capacity
        polity["civil_finance"]["institutional_capacity"] = {
            "regional_administration": effective_admin_capacity,
            "recruitment_office_monthly": recruitment_office_capacity,
        }
        self.put(treasury_path, treasury)
        if force_path and force is not None:
            self.put(force_path, force)
        self.put("state/territory/control.json", territory)
        self.put(polity_path, polity)

    def _autonomy_polity_institution(self, path: str, inst: dict[str, Any], polity_ref: str, occurrences: int, at: str) -> None:
        """Review one exact institution belonging to a dynamic sovereign polity."""
        polity_path = self.owner_path(polity_ref)
        polity = copy.deepcopy(self.read(polity_path))
        if str(polity.get("status", "")) == "dissolved":
            return
        kind = str(inst.get("kind", ""))
        capacity = max(0, int(inst.get("capacity", 0)))
        seat = str(inst.get("location_ref", polity.get("seat_claim_ref", "")))
        controlled = {str(x) for x in polity.get("occupied_site_refs", []) if isinstance(x, str)}
        territory = self.read("state/territory/control.json")

        if kind == "granary_depot_office" and seat:
            native_state = self._native_site_state(seat)
            treasury_ref = str(polity.get("treasury_ref", ""))
            if native_state and treasury_ref:
                ep, eco = self._private_economy(native_state)
                try: site_ref, regional = self._local_economy_region(native_state, eco, seat)
                except ValueError: site_ref, regional = "", eco
                treasury_path = self.owner_path(treasury_ref)
                treasury = copy.deepcopy(self.read(treasury_path))
                funds_key, funds = self._funds_value(treasury)
                target = capacity * int(self._civil_rules().get("granary", {}).get("procurement_kg_per_capacity_per_review", 500)) * max(1, int(occurrences))
                prices = self.read("game/data/mechanics/economy.json").get("prices_silver", {})
                purchases: dict[str, int] = {}; total_cost = 0
                for resource, share in (("grain_kg", 1.0), ("fodder_kg", 0.35)):
                    available = max(0, int(regional.setdefault("commodity_stock", {}).get(resource, 0))); resource_target = max(0, int(round(target * share))); base_price = max(0.0, _fixed(prices.get(resource, 0.08 if resource == "grain_kg" else 0.10), 0.10)); price, price_basis = self._regional_commodity_unit_price(regional, resource, base_price); affordable = int((funds - total_cost) // price) if price > 0 else available; qty = min(available, resource_target, max(0, affordable))
                    if qty <= 0: continue
                    cost = int(math.ceil(qty * price)); regional["commodity_stock"][resource] = available - qty; regional["cash_silver"] = int(regional.get("cash_silver", 0)) + cost; self._record_private_realized_sale(regional, amount_silver=cost, at=at, kind="polity_granary_procurement", resource=resource, quantity=qty); inst.setdefault("resources", {})[resource] = int(inst.get("resources", {}).get(resource, 0)) + qty; purchases[resource] = qty; total_cost += cost
                if purchases:
                    treasury[funds_key] = funds - total_cost
                    inst["last_procurement"] = {"at": at, **purchases, "silver": total_cost, "source_ref": f"private_economy_{native_state}", "regional_source_ref": site_ref or None, "destination_ref": str(inst.get("owner_id"))}
                    inst["procurement_count"] = int(inst.get("procurement_count", 0) or 0) + 1
                    self._sync_local_economy_aggregate(eco)
                    self._write_private_economy(ep, eco)
                    self.put(treasury_path, treasury)
        elif kind == "regional_administration":
            governed = []
            for loc in sorted(controlled):
                site = territory.get("sites", {}).get(loc) if isinstance(territory, Mapping) else None
                gov = site.get("governance") if isinstance(site, Mapping) and isinstance(site.get("governance"), Mapping) else None
                if gov:
                    governed.append({"location_ref": loc, "status": gov.get("status"), "tax_compliance": gov.get("tax_compliance"), "resistance": gov.get("resistance")})
            inst["administration_review"] = {"at": at, "governed_sites": governed[-32:], "governed_site_count": len(governed)}
        elif kind == "military_bureau":
            formation_refs: list[str] = []
            vacancies: list[str] = []
            low_readiness: list[str] = []
            for force_ref in sorted(str(x) for x in polity.get("military_force_refs", []) if isinstance(x, str)):
                try:
                    force = self.read(self.owner_path(force_ref))
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                allocated = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
                for formation_ref in sorted(str(x) for x in allocated):
                    if formation_ref in formation_refs:
                        continue
                    formation_refs.append(formation_ref)
                    try:
                        _fp, formation = self._load_formation(formation_ref)
                    except ValueError:
                        continue
                    if int(formation.get("personnel", 0)) > 0 and not formation.get("commander_ref"):
                        vacancies.append(formation_ref)
                    if int(formation.get("readiness", 0)) < 55:
                        low_readiness.append(formation_ref)
            trained: list[dict[str, Any]] = []
            ministry_rules = self._civil_rules().get("polity_ministries", {})
            treasury_ref = str(polity.get("treasury_ref", ""))
            native_state = self._native_site_state(seat) if seat else None
            if treasury_ref and native_state and low_readiness:
                treasury_path = self.owner_path(treasury_ref); treasury = copy.deepcopy(self.read(treasury_path)); funds_key, funds = self._funds_value(treasury)
                ep, eco = self._private_economy(native_state)
                try: _site_ref, regional = self._local_economy_region(native_state, eco, seat)
                except ValueError: regional = eco
                per_cost = max(1, int(ministry_rules.get("military_bureau_training_silver_per_formation", 50)))
                max_actions = max(1, min(len(low_readiness), max(1, capacity // 50) * max(1, occurrences)))
                for formation_ref in sorted(low_readiness)[:max_actions]:
                    if funds < per_cost: break
                    fp, formation = self._load_formation(formation_ref); formation = copy.deepcopy(formation)
                    if str(formation.get("commander_ref", "")) == self.PLAYER_ACTOR or str(formation.get("command_authority", "")) == self.PLAYER_ACTOR: continue
                    before = int(formation.get("readiness", 0)); training_before = int(formation.get("training_progress", 0))
                    formation["readiness"] = _clamp(before + max(1, int(ministry_rules.get("military_bureau_readiness_gain", 3))))
                    formation["training_progress"] = _clamp(training_before + max(1, int(ministry_rules.get("military_bureau_training_gain", 2))))
                    formation["last_institutional_training"] = {"at": at, "institution_ref": str(inst.get("owner_id")), "silver": per_cost, "readiness_gain": formation["readiness"] - before, "training_gain": formation["training_progress"] - training_before}
                    funds -= per_cost; regional["cash_silver"] = int(regional.get("cash_silver", 0)) + per_cost; self._record_private_realized_sale(regional, amount_silver=per_cost, at=at, kind="military_training_service"); self.put(fp, formation); trained.append({"formation_ref": formation_ref, "silver": per_cost})
                treasury[funds_key] = funds; self.put(treasury_path, treasury); self._sync_local_economy_aggregate(eco); self._write_private_economy(ep, eco)
            inst["military_review"] = {"at": at, "formation_count": len(formation_refs), "commander_vacancies": vacancies, "low_readiness": low_readiness, "training_actions": trained}
        elif kind == "recruitment_office":
            access_rows = []
            for loc in sorted(controlled):
                site = territory.get("sites", {}).get(loc) if isinstance(territory, Mapping) else None
                gov = site.get("governance") if isinstance(site, Mapping) and isinstance(site.get("governance"), Mapping) else None
                if gov:
                    access_rows.append({"location_ref": loc, "recruitment_access": int(gov.get("recruitment_access", 0)), "status": gov.get("status")})
            inst["recruitment_review"] = {"at": at, "office_capacity": capacity, "controlled_site_access": access_rows[-32:]}
        elif kind == "fortification_bureau":
            priorities = []
            for loc in sorted(controlled):
                site = territory.get("sites", {}).get(loc) if isinstance(territory, Mapping) else None
                if not isinstance(site, Mapping):
                    continue
                gov = site.get("governance") if isinstance(site.get("governance"), Mapping) else {}
                score = (40 if site.get("fortified") else 0) + int(gov.get("resistance", 0))
                priorities.append({"location_ref": loc, "priority_score": score, "already_fortified": bool(site.get("fortified"))})
            ranked_priorities = sorted(priorities, key=lambda row: (-int(row["priority_score"]), str(row["location_ref"])))
            started_project = None
            target = next((row for row in ranked_priorities if not bool(row.get("already_fortified"))), None)
            if target and not any(str(pj.get("status")) == "active" for pj in inst.get("projects", []) if isinstance(pj, Mapping)):
                ministry_rules = self._civil_rules().get("polity_ministries", {}); target_ref = str(target["location_ref"]); native_state = self._native_site_state(target_ref); treasury_ref = str(polity.get("treasury_ref", ""))
                if native_state and treasury_ref:
                    treasury_path = self.owner_path(treasury_ref); treasury = copy.deepcopy(self.read(treasury_path)); funds_key, funds = self._funds_value(treasury); ep, eco = self._private_economy(native_state)
                    try: site_ref, regional = self._local_economy_region(native_state, eco, target_ref)
                    except ValueError: site_ref, regional = "", eco
                    silver = max(1, int(ministry_rules.get("fortification_project_silver", 500))); material = max(1, int(ministry_rules.get("fortification_project_material_units", 50))); workers = max(1, int(ministry_rules.get("fortification_project_workers", 20))); days = max(1, int(ministry_rules.get("fortification_project_days", 90)))
                    commodities = regional.setdefault("commodity_stock", {}); labor = eco.setdefault("labor_allocation", {}); allocations = labor.setdefault("projects", {})
                    local_pop = self._local_population_row(native_state, target_ref)[2]; craft_workers = max(0, int((local_pop.get("civilian_strata", {}) or {}).get("craft_and_industry", 0))); active_local_workers = sum(max(0, int(row.get("workers", 0))) for row in allocations.values() if isinstance(row, Mapping) and str(row.get("location_ref", "")) in {site_ref, target_ref})
                    if funds >= silver and int(commodities.get("construction_material_units", 0)) >= material and craft_workers - active_local_workers >= workers:
                        project_ref = "project_fort_" + hashlib.sha256(f"{polity_ref}|{target_ref}|{at}".encode()).hexdigest()[:16]; completes = str(CampaignTime.parse(at).add_seconds(days * 86400)); treasury[funds_key] = funds - silver; regional["cash_silver"] = int(regional.get("cash_silver", 0)) + silver; self._record_private_realized_sale(regional, amount_silver=silver, at=at, kind="fortification_contract", resource="construction_material_units", quantity=material); commodities["construction_material_units"] -= material; allocations[project_ref] = {"workers": workers, "labor_hours": workers * days * 8, "allocated_at": at, "releases_at": completes, "institution_ref": str(inst.get("owner_id")), "location_ref": site_ref or target_ref}; labor["allocated_construction_workers"] = sum(max(0, int(row.get("workers", 0))) for row in allocations.values() if isinstance(row, Mapping)); project = {"project_ref": project_ref, "kind": "construction", "magnitude": 1, "status": "active", "started_at": at, "completes_at": completes, "effect": {"fortify_location_ref": target_ref}, "inputs_reserved": {"silver": silver, "construction_material_units": material, "labor_hours": workers * days * 8, "construction_workers": workers, "funding_ref": treasury_path, "material_source_ref": f"private_economy_{native_state}", "regional_source_ref": site_ref or None, "labor_source_ref": f"private_economy_{native_state}"}}; inst.setdefault("projects", []).append(project); started_project = project_ref; self.put(treasury_path, treasury); self._sync_local_economy_aggregate(eco); self._write_private_economy(ep, eco)
            inst["fortification_review"] = {"at": at, "priorities": ranked_priorities[:16], "project_started_ref": started_project}
        elif kind == "horse_administration":
            mounted = 0; cavalry_need: list[tuple[str, int]] = []
            for force_ref in sorted(str(x) for x in polity.get("military_force_refs", []) if isinstance(x, str)):
                try:
                    force = self.read(self.owner_path(force_ref))
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                for formation_ref in sorted(str(x) for x in (force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {})):
                    try:
                        _fp, formation = self._load_formation(formation_ref)
                    except ValueError:
                        continue
                    mounts = formation.get("mounts", {}) if isinstance(formation.get("mounts"), Mapping) else {}
                    current_mounts = sum(max(0, int(v)) for v in mounts.values() if isinstance(v, (int, float))); mounted += current_mounts
                    cavalry = sum(max(0, int(v)) for role, v in (formation.get("composition", {}) or {}).items() if "cavalry" in str(role).lower() or "mounted" in str(role).lower())
                    if cavalry > current_mounts and str(formation.get("commander_ref", "")) != self.PLAYER_ACTOR and str(formation.get("command_authority", "")) != self.PLAYER_ACTOR: cavalry_need.append((formation_ref, cavalry - current_mounts))
            purchased = 0
            ministry_rules = self._civil_rules().get("polity_ministries", {}); native_state = self._native_site_state(seat) if seat else None; treasury_ref = str(polity.get("treasury_ref", ""))
            if cavalry_need and native_state and treasury_ref:
                ep, eco = self._private_economy(native_state)
                try: _site_ref, regional = self._local_economy_region(native_state, eco, seat)
                except ValueError: regional = eco
                treasury_path = self.owner_path(treasury_ref); treasury = copy.deepcopy(self.read(treasury_path)); funds_key, funds = self._funds_value(treasury); unit = max(1, int(ministry_rules.get("horse_purchase_price_silver", 500))); available = max(0, int(regional.setdefault("commodity_stock", {}).get("horse_stock", 0))); cap = max(1, capacity * max(1, int(ministry_rules.get("horse_purchase_per_capacity", 2))) * max(1, occurrences)); buy = min(sum(need for _ref, need in cavalry_need), available, cap, funds // unit)
                remaining = buy
                for formation_ref, need in cavalry_need:
                    take = min(need, remaining)
                    if take <= 0: break
                    fp, formation = self._load_formation(formation_ref); formation = copy.deepcopy(formation); formation.setdefault("mounts", {})["horse"] = int(formation.get("mounts", {}).get("horse", 0)) + take; self.put(fp, formation); remaining -= take; purchased += take
                if purchased:
                    regional["commodity_stock"]["horse_stock"] = available - purchased; cost = purchased * unit; regional["cash_silver"] = int(regional.get("cash_silver", 0)) + cost; self._record_private_realized_sale(regional, amount_silver=cost, at=at, kind="horse_procurement", resource="horse_stock", quantity=purchased); treasury[funds_key] = funds - cost; self._sync_local_economy_aggregate(eco); self._write_private_economy(ep, eco); self.put(treasury_path, treasury); mounted += purchased
            inst["mount_review"] = {"at": at, "mounts_in_exact_formation_custody": mounted, "purchased_and_assigned": purchased, "unfilled_cavalry_need": max(0, sum(need for _ref, need in cavalry_need) - purchased), "rule": "horse administration buys locally produced horse stock with exact treasury silver and assigns custody to exact non-player formations"}

        inst["last_review"] = at
        inst["backlog"] = max(0, int(inst.get("backlog", 0)) - capacity * max(1, int(occurrences)))
        settled = 0
        for project in inst.get("projects", []):
            if str(project.get("status")) != "active" or not project.get("completes_at"):
                continue
            if CampaignTime.parse(str(project["completes_at"])) > CampaignTime.parse(at):
                continue
            self._resolve_funded_project(inst, project, str(project["completes_at"]))
            settled += int(project.get("status") == "completed")
        if settled:
            inst.setdefault("runtime", {})["projects_settled"] = int(inst.get("runtime", {}).get("projects_settled", 0)) + settled
        polity.setdefault("institutional_runtime", {})[kind] = {"last_review": at, "institution_ref": str(inst.get("owner_id")), "capacity": capacity}
        self.put(path, inst)
        self.put(polity_path, polity)

    def _autonomy_institution_bundle(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Settle the six baseline ministries for one Warring State in one causal host.

        Generic ministries remain independently addressable logical records, but
        they share one state-level review frontier. This avoids six scheduler
        hosts per state while preserving each ministry's current capacity,
        projects, resources, and exact command surface.
        """
        state = self._state_key(str(host.get("owner_ref", "")))
        suffixes = (
            "fortification_bureau", "granary_depot_office", "horse_administration",
            "military_bureau", "recruitment_office", "regional_administration",
        )
        for suffix in suffixes:
            self._autonomy_institution({"owner_ref": f"inst_{state}_{suffix}"}, occurrences, at)

    def _autonomy_institution(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        if str(host.get("owner_ref")) == "force_sword_manor":
            super()._autonomy_institution(host, occurrences, at)
            return
        p = self.owner_path(str(host["owner_ref"]))
        inst = copy.deepcopy(self.read(p))
        inst["last_review"] = at
        kind = str(inst.get("kind", ""))
        state_raw = str(inst.get("state", ""))
        if state_raw.startswith("polity_"):
            self._autonomy_polity_institution(p, inst, state_raw, occurrences, at)
            return
        state = self._state_key(state_raw)
        if kind == "horse_administration":
            mp = f"state/mounts/{state}.json"
            mounts = copy.deepcopy(self.read(mp))
            recovering = int(mounts.get("health", {}).get("recovering", 0))
            recover = min(recovering, int(inst.get("capacity", 500)) * occurrences)
            mounts["health"]["recovering"] -= recover
            mounts["health"]["fit"] += recover
            self.put(mp, mounts)
        elif kind == "granary_depot_office":
            ep, eco = self._private_economy(state)
            depot = self.read(f"state/depots/{state}.json")
            depot_location = str(depot.get("location_ref", inst.get("location_ref", "")))
            regional_source_ref, regional = self._local_economy_region(state, eco, depot_location)
            available = int(regional.setdefault("commodity_stock", {}).get("grain_kg", 0))
            target = max(0, int(inst.get("capacity", 0))) * int(self._civil_rules().get("granary", {}).get("procurement_kg_per_capacity_per_review", 500)) * occurrences
            econ = self.read("game/data/mechanics/economy.json")
            base_price = max(0.0, _fixed(econ.get("prices_silver", {}).get("grain_kg", 0.08), 0.08))
            price, price_basis = self._regional_commodity_unit_price(regional, "grain_kg", base_price)
            sp = f"state/states/{state}.json"
            sd = copy.deepcopy(self.read(sp))
            affordable = int(sd.get("treasury_silver", 0) // price) if price > 0 else available
            qty = min(available, target, affordable)
            if qty:
                cost = int(math.ceil(qty * price))
                dp = f"state/depots/{state}.json"
                depot = copy.deepcopy(self.read(dp))
                regional["commodity_stock"]["grain_kg"] -= qty
                regional["cash_silver"] = int(regional.get("cash_silver", 0)) + cost
                self._record_private_realized_sale(regional, amount_silver=cost, at=at, kind="state_grain_procurement", resource="grain_kg", quantity=qty)
                sd["treasury_silver"] -= cost
                depot.setdefault("stocks", {})["grain_kg"] = int(depot.get("stocks", {}).get("grain_kg", 0)) + qty
                inst["last_procurement"] = {"at": at, "grain_kg": qty, "silver": cost, "unit_price_silver": round(price, 6), "price_basis": price_basis, "source_ref": f"private_economy_{state}", "regional_source_ref": regional_source_ref, "destination_ref": f"state_depot_{state}"}
                inst["procurement_count"] = int(inst.get("procurement_count", 0) or 0) + 1
                # Regional stock is authoritative in v6; update the aggregate
                # current aggregate mirror before writing so the cash reconcile
                # step cannot re-inject grain that was physically procured.
                self._sync_local_economy_aggregate(eco)
                self._write_private_economy(ep, eco); self.put(sp, sd); self.put(dp, depot)
        elif kind == "regional_administration":
            self._settle_occupation_administration(state, occurrences, at)
            terr = self.read("state/territory/control.json")
            governed = []
            for loc, site in terr.get("sites", {}).items():
                if not isinstance(site, Mapping) or str(site.get("controller")) != f"state_{state}":
                    continue
                gov = site.get("governance") if isinstance(site.get("governance"), Mapping) else None
                if gov:
                    governed.append({"location_ref": loc, "status": gov.get("status"), "tax_compliance": gov.get("tax_compliance"), "resistance": gov.get("resistance")})
            inst["administration_review"] = {"at": at, "governed_sites": governed[-32:], "governed_site_count": len(governed)}
        elif kind == "military_bureau":
            force = self.read(f"state/forces/state-{state}.json")
            allocated = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
            vacancies = []; low_readiness = []; undersupplied = []
            for formation_ref in sorted(str(x) for x in allocated):
                try:
                    _, formation = self._load_formation(formation_ref)
                except ValueError:
                    continue
                if not formation.get("commander_ref") and int(formation.get("personnel", 0)) > 0:
                    vacancies.append(formation_ref)
                if int(formation.get("readiness", 0)) < 55:
                    low_readiness.append(formation_ref)
                logistics = formation.get("logistics", {}) if isinstance(formation.get("logistics"), Mapping) else {}
                if int(formation.get("personnel", 0)) > 0 and int(logistics.get("food_kg", 0)) < int(formation.get("personnel", 0)) * 2:
                    undersupplied.append(formation_ref)
            sp = f"state/states/{state}.json"; sd = copy.deepcopy(self.read(sp))
            ministry_rules = self._civil_rules().get("polity_ministries", {})
            unit_cost = max(1, int(ministry_rules.get("military_bureau_training_silver_per_formation", 50)))
            readiness_gain = max(0, int(ministry_rules.get("military_bureau_readiness_gain", 3)))
            training_gain = max(0, int(ministry_rules.get("military_bureau_training_gain", 2)))
            training_capacity = max(1, int(inst.get("capacity", 1))) * max(1, int(occurrences))
            trained: list[str] = []
            for formation_ref in low_readiness:
                if len(trained) >= training_capacity or int(sd.get("treasury_silver", 0)) < unit_cost:
                    break
                fp, formation = self._load_formation(formation_ref); formation = copy.deepcopy(formation)
                if str(formation.get("commander_ref", "")) == self.PLAYER_ACTOR or str(formation.get("command_authority", "")) == self.PLAYER_ACTOR:
                    continue
                loc = str(formation.get("location_ref", "")); ep, eco = self._private_economy(state)
                try: _region_ref, regional = self._local_economy_region(state, eco, loc)
                except ValueError: regional = eco
                sd["treasury_silver"] = int(sd.get("treasury_silver", 0)) - unit_cost
                regional["cash_silver"] = int(regional.get("cash_silver", 0)) + unit_cost
                self._record_private_realized_sale(regional, amount_silver=unit_cost, at=at, kind="military_training_service")
                formation["readiness"] = min(100, int(formation.get("readiness", 0)) + readiness_gain)
                formation["training_progress"] = min(100, int(formation.get("training_progress", 0)) + training_gain)
                formation["last_institutional_training"] = {"at": at, "institution_ref": str(inst.get("owner_id")), "silver": unit_cost, "readiness_gain": readiness_gain, "training_gain": training_gain}
                self.put(fp, formation); self._sync_local_economy_aggregate(eco); self._write_private_economy(ep, eco); trained.append(formation_ref)
            inst["military_review"] = {"at": at, "formation_count": len(allocated), "commander_vacancies": vacancies, "low_readiness": low_readiness, "undersupplied": undersupplied, "trained_formations": trained, "rule": "bureau spends exact treasury silver into the formation locality to improve non-player formation readiness; command appointments and stock transfers remain separately owned"}
            sd["military_administration"] = {"last_review": at, "commander_vacancy_count": len(vacancies), "low_readiness_count": len(low_readiness), "undersupplied_count": len(undersupplied), "trained_formation_count": len(trained)}
            self.put(sp, sd)
        elif kind == "fortification_bureau":
            terr = self.read("state/territory/control.json")
            priorities = []
            for loc, site in terr.get("sites", {}).items():
                if not isinstance(site, Mapping) or str(site.get("controller")) != f"state_{state}":
                    continue
                gov = site.get("governance") if isinstance(site.get("governance"), Mapping) else {}
                score = (40 if site.get("fortified") else 0) + int(gov.get("resistance", 0))
                if score > 0:
                    priorities.append((score, str(loc), bool(site.get("fortified"))))
            priorities.sort(key=lambda row: (-row[0], row[1]))
            started_project = None
            active_fortification = any(isinstance(row, Mapping) and str(row.get("status", "")) == "active" and str(row.get("effect", {}).get("fortify_location_ref", "")) for row in inst.get("projects", []))
            target_row = next((row for row in priorities if not row[2]), None)
            if target_row and not active_fortification:
                _score, target_ref, _fortified = target_row
                rules = self._civil_rules().get("polity_ministries", {}); silver = max(1, int(rules.get("fortification_project_silver", 500))); material = max(1, int(rules.get("fortification_project_material_units", 50))); desired_workers = max(1, int(rules.get("fortification_project_workers", 20))); days = max(1, int(rules.get("fortification_project_days", 90)))
                sp = f"state/states/{state}.json"; sd = copy.deepcopy(self.read(sp)); native_state = self._native_site_state(target_ref) or state; ep, eco = self._private_economy(native_state)
                try: site_ref, regional = self._local_economy_region(native_state, eco, target_ref)
                except ValueError: site_ref, regional = "", eco
                pp, pop = self._ensure_local_population_ledger(native_state, copy.deepcopy(self.read(f"state/population/{native_state}.json"))); local_row = pop.get("local_population", {}).get("sites", {}).get(site_ref or target_ref, {}); craft = max(0, int((local_row.get("civilian_strata", {}) if isinstance(local_row, Mapping) else {}).get("craft_and_industry", 0))); fraction = max(0.0, min(1.0, _fixed(self._civil_rules().get("labor", {}).get("construction_labor_fraction_of_craft_workers", 0.12), 0.12))); local_pool = max(0, int(math.floor(craft * fraction)))
                labor = eco.setdefault("labor_allocation", {}); allocations = labor.setdefault("projects", {}); active_workers = sum(max(0, int(row.get("workers", 0))) for row in allocations.values() if isinstance(row, Mapping) and (not row.get("releases_at") or CampaignTime.parse(str(row.get("releases_at"))) > CampaignTime.parse(at))); workers = min(desired_workers, max(0, local_pool - active_workers)); commodities = regional.setdefault("commodity_stock", {})
                if int(sd.get("treasury_silver", 0)) >= silver and int(commodities.get("construction_material_units", 0)) >= material and workers > 0:
                    project_ref = "project_state_fort_" + hashlib.sha256(f"{state}|{target_ref}|{at}".encode()).hexdigest()[:16]; completes = str(CampaignTime.parse(at).add_seconds(days * 86400)); sd["treasury_silver"] -= silver; regional["cash_silver"] = int(regional.get("cash_silver", 0)) + silver; self._record_private_realized_sale(regional, amount_silver=silver, at=at, kind="fortification_contract", resource="construction_material_units", quantity=material); commodities["construction_material_units"] -= material; allocations[project_ref] = {"workers": workers, "labor_hours": workers * days * 8, "allocated_at": at, "releases_at": completes, "institution_ref": str(inst.get("owner_id")), "location_ref": site_ref or target_ref}; labor["allocated_construction_workers"] = active_workers + workers; project = {"project_ref": project_ref, "kind": "construction", "magnitude": 1, "status": "active", "started_at": at, "completes_at": completes, "effect": {"fortify_location_ref": target_ref}, "inputs_reserved": {"silver": silver, "construction_material_units": material, "labor_hours": workers * days * 8, "construction_workers": workers, "funding_ref": sp, "material_source_ref": f"private_economy_{native_state}", "regional_source_ref": site_ref or None, "labor_source_ref": f"private_economy_{native_state}"}}; inst.setdefault("projects", []).append(project); started_project = project_ref; self.put(sp, sd); self._sync_local_economy_aggregate(eco); self._write_private_economy(ep, eco)
            inst["fortification_review"] = {"at": at, "priorities": [{"location_ref": loc, "priority_score": score, "already_fortified": fortified} for score, loc, fortified in priorities[:16]], "project_started_ref": started_project}
        elif kind == "recruitment_office":
            pop = self.read(f"state/population/{state}.json")
            force = self.read(f"state/forces/state-{state}.json")
            authorized = int(force.get("authorized_strength", force.get("headcount", 0)))
            shortage = max(0, authorized - int(force.get("headcount", 0)))
            inst["recruitment_review"] = {"at": at, "office_capacity": int(inst.get("capacity", 0)), "force_shortage": shortage, "civil_population_total": int(pop.get("population_total", 0)), "active_military": int(pop.get("strata", {}).get("active_military", 0))}
        inst["backlog"] = max(0, int(inst.get("backlog", 0)) - int(inst.get("capacity", 0)) * occurrences)
        settled = 0
        for project in inst.get("projects", []):
            if str(project.get("status")) != "active" or not project.get("completes_at"):
                continue
            if CampaignTime.parse(str(project["completes_at"])) > CampaignTime.parse(at):
                continue
            self._resolve_funded_project(inst, project, str(project["completes_at"]))
            settled += int(project.get("status") == "completed")
        if settled:
            inst.setdefault("runtime", {})["projects_settled"] = int(inst.get("runtime", {}).get("projects_settled", 0)) + settled
        self.put(p, inst)

    def _autonomy_house(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        house_ref = str(host["owner_ref"])
        house_path = self.owner_path(house_ref)
        before_house = copy.deepcopy(self.read(house_path))
        force_ref = before_house.get("military_force_ref")
        before_force_n = int(self.read(self.owner_path(force_ref)).get("headcount", 0)) if isinstance(force_ref, str) else None
        super()._autonomy_house(host, occurrences, at)
        reviewed = copy.deepcopy(self.read(house_path))
        before_cohort = before_house.get("lineage_cohort", {}) if isinstance(before_house.get("lineage_cohort"), Mapping) else {}
        after_cohort = reviewed.get("lineage_cohort", {}) if isinstance(reviewed.get("lineage_cohort"), Mapping) else {}
        if not after_cohort.get("exact_member_refs"):
            lineage = reviewed.setdefault("lineage_runtime", {})
            lineage["representation"] = "aggregate household branches; exact people materialize only when individually relevant"
            branch = lineage.setdefault("branches", {}).setdefault("household_core", {})
            for key in ("children", "adults", "elders", "marriages"):
                branch[key] = int(after_cohort.get(key, 0))
            lineage.setdefault("reviews", []).append({"at": at, "occurrences": occurrences, "deltas": {key: int(after_cohort.get(key, 0)) - int(before_cohort.get(key, 0)) for key in ("children", "adults", "elders", "marriages")}})
            lineage["reviews"] = lineage["reviews"][-24:]

        recruited = 0
        state = self._state_key(reviewed.get("state"))
        if isinstance(force_ref, str) and before_force_n is not None:
            recruited = max(0, int(self.read(self.owner_path(force_ref)).get("headcount", 0)) - before_force_n)
        if recruited and isinstance(force_ref, str):
            population_path = f"state/population/{state}.json"
            population = copy.deepcopy(self.read(population_path))
            force_now = self.read(self.owner_path(force_ref))
            source_location = str(force_now.get("source_location_ref") or reviewed.get("location_ref") or f"loc_{state}")
            rows = self._consume_local_private_recruitment(population, state, source_location, recruited, source_stratum="household_and_service", force_ref=force_ref, controller_ref=f"state_{state}")
            self.put(population_path, population)
            reviewed.setdefault("local_recruitment_history", []).append({"at": at, "personnel": recruited, "force_ref": force_ref, "local_sources": rows})
            reviewed["local_recruitment_history"] = reviewed["local_recruitment_history"][-24:]
            unit_cost = max(0, int(self.read("game/data/mechanics/economy.json").get("military_finance", {}).get("recruitment_and_basic_issue_cost_silver_per_person", 12)))
            due = recruited * unit_cost
            paid = self._debit_house_cash(house_ref, due)
            ep, eco = self._private_economy(state)
            eco["cash_silver"] = int(eco.get("cash_silver", 0)) + paid
            self._write_private_economy(ep, eco)
            reviewed.setdefault("civil_finance", {}).update({"last_recruitment_close": at, "recruits": recruited, "recruitment_cost_due_silver": due, "recruitment_cost_paid_silver": paid, "recruitment_arrears_silver": max(0, due - paid)})

        # A full-strength House must still participate in the political economy.
        # Use one compact universal patronage/standing action rather than bespoke
        # House scripts. Real silver leaves the House and enters the same private
        # economy as other civil spending; the political result is deliberately
        # slow and bounded so wealth creates leverage rather than free offices.
        politics = reviewed.setdefault("politics", {})
        fields = ("court_access", "information_access", "patronage", "influence")
        if all(isinstance(politics.get(key), (int, float)) for key in fields):
            target_field = min(fields, key=lambda key: (int(politics.get(key, 0)), fields.index(key)))
            per_review_cost = max(25, min(500, sum(max(0, int(politics.get(key, 0))) for key in fields) // 4))
            desired_reviews = max(1, int(occurrences))
            treasury_ref = reviewed.get("treasury_ref")
            treasury_path = None
            treasury = None
            if isinstance(treasury_ref, str) and treasury_ref:
                treasury_path = self.owner_path(treasury_ref)
                treasury = copy.deepcopy(self.read(treasury_path))
                balance = max(0, int(treasury.get("silver", 0)))
            else:
                balance = max(0, int(reviewed.get("treasury_silver", 0)))
            funded_reviews = min(desired_reviews, balance // per_review_cost)
            if funded_reviews > 0:
                spent = funded_reviews * per_review_cost
                if isinstance(treasury, dict) and treasury_path:
                    treasury["silver"] = balance - spent
                    self.put(treasury_path, treasury)
                else:
                    reviewed["treasury_silver"] = balance - spent
                ep, eco = self._private_economy(state)
                eco["cash_silver"] = int(eco.get("cash_silver", 0)) + spent
                self._write_private_economy(ep, eco)
                before_value = max(0, int(politics.get(target_field, 0)))
                after_value = _clamp(before_value + funded_reviews)
                politics[target_field] = after_value
                reviewed["last_political_action"] = {
                    "at": at,
                    "kind": "house_patronage_and_standing",
                    "focus": target_field,
                    "value_before": before_value,
                    "value_after": after_value,
                    "silver_spent": spent,
                    "destination_ref": f"private_economy_{state}",
                }
                reviewed["political_action_count"] = int(reviewed.get("political_action_count", 0)) + funded_reviews
            else:
                reviewed["last_political_action"] = {"at": at, "kind": "house_patronage_and_standing", "status": "unfunded", "focus": target_field, "required_silver": per_review_cost}
        self.put(house_path, reviewed)

    @staticmethod
    def _mercenary_route_ids(owner_ref: str) -> tuple[str, str]:
        slug = str(owner_ref).replace(".", "_").replace("-", "_")
        return f"host_merc_{slug}", f"event_merc_{slug}"

    def _regional_mercenary_entry(self, owner_ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
        index = copy.deepcopy(self.read(_REGIONAL_MERCENARY_INDEX))
        entries = index.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError("regional mercenary index entries are invalid")
        for entry in entries:
            if isinstance(entry, dict) and str(entry.get("id")) == str(owner_ref):
                return index, entry
        raise ValueError(f"unknown regional mercenary: {owner_ref}")

    def _materialize_regional_mercenary(self, owner_ref: str, at: str) -> str:
        """Materialize one background regional company only when causally relevant."""

        index, entry = self._regional_mercenary_entry(owner_ref)
        existing_path = entry.get("path")
        owner_index = self.read("state/index/owner-index.json").get("owners", {})
        if isinstance(existing_path, str) and isinstance(owner_index, Mapping) and owner_index.get(owner_ref) == existing_path:
            return existing_path

        profiles_doc = self.read(_REGIONAL_MERCENARY_PROFILES)
        profiles = profiles_doc.get("profiles", {}) if isinstance(profiles_doc, Mapping) else {}
        profile = profiles.get(owner_ref) if isinstance(profiles, Mapping) else None
        if not isinstance(profile, Mapping):
            raise ValueError(f"regional mercenary profile missing: {owner_ref}")
        template = profile.get("template")
        if not isinstance(template, Mapping):
            raise ValueError(f"regional mercenary template missing: {owner_ref}")
        company = copy.deepcopy(dict(template))
        count = max(1, int(entry.get("count", company.get("count", 1))))
        company.update({
            "id": owner_ref,
            "owner_id": owner_ref,
            "count": count,
            "establishment_strength": max(count, int(entry.get("establishment_strength", company.get("establishment_strength", count)))),
            "status": str(entry.get("status", "available")),
            "current_location_ref": str(entry.get("current_location_ref") or company.get("home_location_ref")),
            "contracts": copy.deepcopy(entry.get("contracts", [])) if isinstance(entry.get("contracts"), list) else [],
            "profile_ref": f"{_REGIONAL_MERCENARY_PROFILES}#profiles.{owner_ref}",
        })
        engagement = entry.get("market_engagement")
        if isinstance(engagement, Mapping):
            company["market_engagement"] = copy.deepcopy(dict(engagement))
        runtime_summary = entry.get("runtime")
        if isinstance(runtime_summary, Mapping):
            company["runtime"] = copy.deepcopy(dict(runtime_summary))
        else:
            company["runtime"] = {"completed_quarterly_reviews": 0, "last_settled_at": at}

        path = str(profile.get("state_path") or f"state/merc/regional/{owner_ref.replace('.', '-')}.json")
        self.put(path, company)
        self._register_owner(owner_ref, path)

        entry["path"] = path
        entry["materialized"] = True
        entry["status"] = company["status"]
        entry["count"] = count
        self.put(_REGIONAL_MERCENARY_INDEX, index)

        runtime = copy.deepcopy(self.read("state/runtime.json"))
        hosts = runtime.setdefault("hosts", {})
        events = runtime.setdefault("events", [])
        host_id, event_id = self._mercenary_route_ids(owner_ref)
        if host_id not in hosts:
            now = CampaignTime.parse(at)
            due = now.add_seconds(_MERCENARY_REVIEW_SECONDS)
            hosts[host_id] = {
                "kind": "mercenary",
                "owner_ref": owner_ref,
                "quiet_run_count": 0,
                "recurrence_seconds": _MERCENARY_REVIEW_SECONDS,
                "resolved_through": at,
                "next_due": str(due),
                "safe_through": str(due.add_seconds(-1)),
            }
            events.append({"event_id": event_id, "priority": 75, "target_host": host_id, "due_at": str(due)})
            self.put("state/runtime.json", runtime)
        return path

    def _aggregate_idle_regional_mercenary(self, owner_ref: str, at: str) -> bool:
        """Collapse an idle regional company back into the aggregate market.

        Contracted/deployed companies remain exact.  The current scheduler host
        is marked for retirement and the causal scheduler removes its own route
        after this occurrence has settled, avoiding a second permanent clock.
        """

        try:
            path = self.owner_path(owner_ref)
            company = copy.deepcopy(self.read(path))
        except (FileNotFoundError, KeyError, ValueError):
            return False
        if str(company.get("schema")) != "regional-mercenary-company":
            return False
        contracts = company.get("contracts", [])
        if not isinstance(contracts, list):
            return False
        live_statuses = {"offered", "accepted_unpaid", "active", "renewal_offered", "renewal_accepted"}
        if str(company.get("status")) != "available" or any(str(c.get("status")) in live_statuses for c in contracts if isinstance(c, Mapping)):
            return False

        index, entry = self._regional_mercenary_entry(owner_ref)
        entry.update({
            "count": max(1, int(company.get("count", company.get("headcount", 1)))),
            "establishment_strength": max(1, int(company.get("establishment_strength", company.get("count", 1)))),
            "state_market": str(company.get("state_market", entry.get("state_market", ""))),
            "status": "available",
            "current_location_ref": str(company.get("current_location_ref") or company.get("home_location_ref") or entry.get("current_location_ref", "")),
            "market_engagement": copy.deepcopy(company.get("market_engagement", {"kind": "available", "short_notice_available": True})),
            "runtime": copy.deepcopy(company.get("runtime", {"last_settled_at": at})),
            "materialized": False,
        })
        entry.pop("path", None)
        entry.pop("contracts", None)
        self.put(_REGIONAL_MERCENARY_INDEX, index)
        self.delete(path)
        self._unregister_owner(owner_ref)

        runtime = copy.deepcopy(self.read("state/runtime.json"))
        host_id, _event_id = self._mercenary_route_ids(owner_ref)
        host = runtime.get("hosts", {}).get(host_id) if isinstance(runtime.get("hosts"), Mapping) else None
        if isinstance(host, dict):
            host["retire_after_settlement"] = True
            self.put("state/runtime.json", runtime)
        return True

    def _broker_one_mercenary_offer(self, at: str) -> dict[str, Any]:
        runtime = self.read("state/runtime.json")
        hosts = runtime.get("hosts", {}) if isinstance(runtime, Mapping) else {}
        exact_refs = {
            str(host.get("owner_ref"))
            for host in hosts.values()
            if isinstance(host, Mapping) and host.get("kind") == "mercenary" and isinstance(host.get("owner_ref"), str)
        }
        regional = self.read(_REGIONAL_MERCENARY_INDEX)
        aggregate_refs = {
            str(entry.get("id"))
            for entry in regional.get("entries", [])
            if isinstance(entry, Mapping)
            and entry.get("materialized") is not True
            and str(entry.get("status", "available")) == "available"
            and isinstance(entry.get("id"), str)
        } if isinstance(regional, Mapping) else set()
        merc_refs = sorted(exact_refs | aggregate_refs)
        employers: list[tuple[int, int, str]] = []
        for state in ("qin", "zhao", "chu", "wei", "han", "yan", "qi"):
            sd = self.read(f"state/states/{state}.json")
            threats = sd.get("known_threats", {}) if isinstance(sd, Mapping) else {}
            severity = max((self._threat_severity(v) if hasattr(self, "_threat_severity") else int(_fixed(v.get("severity", 0) if isinstance(v, Mapping) else v, 0)) for v in threats.values()), default=0)
            if severity >= 35:
                employers.append((severity, int(sd.get("treasury_silver", 0)), state))
        if not employers:
            return {"status": "no_solvent_threat_employer"}
        _severity, cash, state = sorted(employers, key=lambda row: (-row[0], -row[1], row[2]))[0]
        econ = self.read("game/data/mechanics/economy.json")
        monthly = _fixed(econ.get("wages", {}).get("professional_soldier_monthly_silver", 7), 7)
        factor = _fixed(self.read("game/data/mechanics/career.json").get("service_models", {}).get("army_model_mercenary", {}).get("cash_pay_factor_vs_common_role_baseline", 1.35), 1.35)
        for ref in merc_refs:
            try:
                path = self.owner_path(ref)
            except ValueError:
                path = self._materialize_regional_mercenary(ref, at)
            company = copy.deepcopy(self.read(path))
            contracts = company.setdefault("contracts", [])
            if company.get("status") != "available" or any(str(c.get("status")) in {"offered", "accepted_unpaid", "active", "renewal_offered", "renewal_accepted"} for c in contracts):
                continue
            headcount = max(1, int(company.get("headcount", company.get("count", company.get("personnel", company.get("strength", 1))))))
            fair = int(math.ceil(headcount * monthly * factor * 3))
            amount = int(math.ceil(fair * 1.05))
            if cash < amount:
                continue
            contract_ref = "merc_broker_" + hashlib.sha256(f"{ref}|{state}|{at}".encode()).hexdigest()[:14]
            contracts.append({
                "contract_ref": contract_ref,
                "employer_ref": f"state_{state}",
                "status": "offered",
                "amount_silver": amount,
                "term_days": 90,
                "offered_at": at,
                "broker_ref": "mercenary_market_index",
                "basis": "saved state threat, employer solvency, exact available company and fair-pay floor",
            })
            company["status"] = "considering_offer"
            company["contracts"] = contracts[-32:]
            self.put(path, company)
            return {"status": "offer_created", "contract_ref": contract_ref, "company_ref": ref, "employer_ref": f"state_{state}", "amount_silver": amount}
        return {"status": "no_available_affordable_company"}

    def _transport_network_action(self, profile: Mapping[str, Any], occurrences: int, at: str) -> dict[str, Any]:
        states = [str(x) for x in profile.get("states", []) if str(x) in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}]
        candidates: list[tuple[float, str, str, dict[str, Any]]] = []
        for state in states:
            spec = self._civil_rules().get("capital_markets", {}).get(state, {})
            if not isinstance(spec, Mapping):
                continue
            path = str(spec.get("path", ""))
            market = self.read_optional(path) if path else None
            if isinstance(market, Mapping):
                candidates.append((_fixed(market.get("insecurity_hoarding_factor", 1.0), 1.0), state, path, copy.deepcopy(dict(market))))
        if not candidates:
            return {"status": "no_exact_market_route"}
        insecurity, state, path, market = sorted(candidates, key=lambda row: (-row[0], row[1]))[0]
        improved = max(0.75, insecurity - min(0.10, 0.01 * max(1, occurrences)))
        market["insecurity_hoarding_factor"] = round(improved, 4)
        market.setdefault("transport_reviews", []).append({"at": at, "faction_ref": "faction_river_transport_leagues", "before": insecurity, "after": improved})
        market["transport_reviews"] = market["transport_reviews"][-24:]
        self.put(path, market)
        return {"status": "route_reliability_improved", "market_ref": market.get("owner_id"), "state": state, "insecurity_before": insecurity, "insecurity_after": improved}

    def _faction_profile(self, ref: str) -> Mapping[str, Any]:
        profiles = self.read(_FACTION_PROFILES).get("profiles", {})
        profile = profiles.get(ref, {}) if isinstance(profiles, Mapping) else {}
        return profile if isinstance(profile, Mapping) else {}

    def _faction_for_actor(self, actor_ref: str) -> str | None:
        profiles = self.read(_FACTION_PROFILES).get("profiles", {})
        if not isinstance(profiles, Mapping):
            return None
        if actor_ref in profiles:
            return actor_ref
        for ref, profile in profiles.items():
            reps = profile.get("representative_refs", []) if isinstance(profile, Mapping) else []
            if isinstance(reps, list) and actor_ref in {str(x) for x in reps}:
                return str(ref)
        return None

    def _faction_organizational_observation(self, ref: str, doc: dict[str, Any], profile: Mapping[str, Any], at: str | None) -> list[str]:
        """Create bounded organization-owned observations without inventing secrets.

        Some independent polities have aggregate scout/messenger institutions but no
        materialized representative character.  Their own patrol network may know
        directly observable conditions at relationships/routes it actually touches.
        These receipts never expose hidden enemy dispositions and never become player
        knowledge merely by existing.
        """
        channels = profile.get("organizational_information_channels", [])
        if not isinstance(channels, list) or not channels or not at:
            return []
        resources = doc.get("resources", {}) if isinstance(doc.get("resources"), Mapping) else {}
        observation_capacity = max(0, int(_fixed(resources.get("agents", 0)))) + max(0, int(_fixed(resources.get("information_access", 0))))
        if observation_capacity <= 0:
            return []
        relationships = doc.get("relationships", {}) if isinstance(doc.get("relationships"), Mapping) else {}
        observed_refs = sorted(str(target) for target in relationships if isinstance(target, str))
        if not observed_refs:
            return []
        channel_kinds = sorted({str(row.get("kind", "")) for row in channels if isinstance(row, Mapping) and str(row.get("kind", ""))})
        if not channel_kinds:
            return []
        bucket = str(at).split("T", 1)[0]
        digest = hashlib.sha256((ref + "|" + bucket + "|" + "|".join(observed_refs) + "|" + "|".join(channel_kinds)).encode("utf-8")).hexdigest()[:18]
        receipt_ref = f"orginfo_{digest}"
        # This is a current anti-repeat/knowledge-routing token, not an append-only
        # observation diary. Channel semantics live in the canonical faction
        # profile; hot state keeps only the newest directly observed frontier.
        doc["organizational_observation"] = {
            "information_ref": receipt_ref,
            "at": at,
            "observed_refs": observed_refs[:16],
        }
        doc.pop("organizational_knowledge_receipts", None)
        return [receipt_ref]

    def _faction_knowledge_basis(self, ref: str, doc: Mapping[str, Any], profile: Mapping[str, Any], at: str | None = None) -> list[str]:
        reps = {str(x) for x in profile.get("representative_refs", []) if isinstance(x, str)}
        candidates = [str(x) for x in doc.get("knowledge", []) if isinstance(x, str)] if isinstance(doc.get("knowledge"), list) else []
        state = str(profile.get("state", ""))
        if state in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
            sd = self.read(f"state/states/{state}.json")
            threats = sd.get("known_threats", {}) if isinstance(sd, Mapping) else {}
            if isinstance(threats, Mapping):
                for threat in threats.values():
                    if isinstance(threat, Mapping) and isinstance(threat.get("information_ref"), str):
                        candidates.append(str(threat["information_ref"]))
        index = self.read("state/information/index.json")
        claims = index.get("claims", {}) if isinstance(index, Mapping) else {}
        valid: list[str] = []
        for info_ref in reversed(list(dict.fromkeys(candidates))):
            path = claims.get(info_ref) if isinstance(claims, Mapping) else None
            if not isinstance(path, str):
                continue
            claim = self.read(path)
            knowers = {str(x) for x in claim.get("knowers", [])} if isinstance(claim, Mapping) and isinstance(claim.get("knowers"), list) else set()
            # State threat registration itself is a lawful organizational knowledge
            # bridge; otherwise a faction must have an exact representative knower.
            state_knows = False
            if state:
                sd = self.read(f"state/states/{state}.json")
                threats = sd.get("known_threats", {}) if isinstance(sd, Mapping) else {}
                state_knows = any(isinstance(v, Mapping) and v.get("information_ref") == info_ref for v in threats.values()) if isinstance(threats, Mapping) else False
            if (reps and reps & knowers) or state_knows:
                valid.append(info_ref)
            if len(valid) >= 8:
                break
        if isinstance(doc, dict):
            for receipt_ref in self._faction_organizational_observation(ref, doc, profile, at):
                if receipt_ref not in valid:
                    valid.append(receipt_ref)
        return list(dict.fromkeys(reversed(valid)))

    def _update_faction_relationship(self, source_ref: str, target_ref: str, *, at: str, delta: int, kind: str) -> dict[str, Any]:
        path = self.owner_path(source_ref)
        doc = copy.deepcopy(self.read(path))
        rels = doc.setdefault("relationships", {})
        rel = rels.setdefault(target_ref, {"kind": kind, "strength": 50})
        before = int(rel.get("sentiment", 0))
        rel["sentiment"] = max(-100, min(100, before + delta))
        rel["interaction_count"] = int(rel.get("interaction_count", 0)) + 1
        rel["last_interaction_at"] = at
        rel["last_interaction_kind"] = kind
        self.put(path, doc)
        return {"source_ref": source_ref, "target_ref": target_ref, "sentiment_before": before, "sentiment_after": rel["sentiment"], "kind": kind}

    def _record_faction_information(self, information_ref: str, knowers: list[str], at: str) -> list[str]:
        profiles = self.read(_FACTION_PROFILES).get("profiles", {})
        if not isinstance(profiles, Mapping):
            return []
        knower_set = {str(x) for x in knowers}
        touched: list[str] = []
        for ref, profile in profiles.items():
            reps = {str(x) for x in profile.get("representative_refs", [])} if isinstance(profile, Mapping) and isinstance(profile.get("representative_refs"), list) else set()
            if not reps or not (reps & knower_set):
                continue
            path = self.owner_path(str(ref))
            doc = copy.deepcopy(self.read(path))
            knowledge = doc.setdefault("knowledge", [])
            if information_ref not in knowledge:
                knowledge.append(information_ref)
                del knowledge[:-64]
            pending = doc.setdefault("pending_information_refs", [])
            if information_ref not in pending:
                pending.append(information_ref)
                del pending[:-16]
            doc["knowledge_updated_at"] = at
            self.put(path, doc)
            touched.append(str(ref))
        if touched:
            runtime = copy.deepcopy(self.read("state/runtime.json"))
            hosts = runtime.get("hosts", {})
            events = runtime.get("events", [])
            by_host = {str(row.get("target_host")): row for row in events if isinstance(row, dict)} if isinstance(events, list) else {}
            current = CampaignTime.parse(at)
            for ref in touched:
                host_id = f"host_{ref}"
                host = hosts.get(host_id) if isinstance(hosts, dict) else None
                profile = profiles.get(ref, {})
                if not isinstance(host, dict) or not isinstance(profile, Mapping):
                    continue
                urgent = max(3600, int(profile.get("urgent_review_seconds", 24 * 3600)))
                due = current.add_seconds(urgent)
                old_due = CampaignTime.parse(str(host["next_due"])) if isinstance(host.get("next_due"), str) else None
                if old_due is None or due < old_due:
                    host["next_due"] = str(due)
                    host["safe_through"] = str(due.add_seconds(-1))
                    event = by_host.get(host_id)
                    if isinstance(event, dict):
                        event["due_at"] = str(due)
            self.put("state/runtime.json", runtime)
        return touched

    @staticmethod
    def _world_arc_priority_signature(arc_ref: str, target_ref: str | None, goal: str) -> tuple[str, str, str]:
        return (str(arc_ref), str(target_ref or ""), str(goal)[:500])

    def _schedule_world_arc_priority_work(self, *, actor_ref: str, action_ref: str, domain: str, at: str) -> None:
        """Create one bounded one-shot causal route for actor-owned queued work.

        The world arc only creates the queue.  This independent host wakes later and
        lets the exact actor domain settle (or fail) the work.  A scheduler route is
        not itself evidence and is garbage-collected after the one-shot callback.
        """
        runtime = copy.deepcopy(self.read("state/runtime.json"))
        hosts = runtime.get("hosts"); events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        token = hashlib.sha256(action_ref.encode("utf-8")).hexdigest()[:18]
        host_id = f"host_world_arc_priority_{token}"
        event_id = f"event_world_arc_priority_{token}"
        existing = hosts.get(host_id)
        if isinstance(existing, Mapping) and existing.get("next_due") is not None:
            return
        delay_by_domain = {"person": 2 * 86400, "house": 2 * 86400, "institution": 2 * 86400, "state": 3 * 86400, "polity": 3 * 86400}
        due = CampaignTime.parse(at).add_seconds(delay_by_domain.get(domain, 3 * 86400))
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "world_arc_priority",
            "owner_ref": actor_ref,
            "domain": domain,
            "action_ref": action_ref,
            "event_id": event_id,
            "recurrence_seconds": 0,
            "next_due": str(due),
            "resolved_through": at,
            "safe_through": str(due.add_seconds(-1)),
        }
        found = next((row for row in events if isinstance(row, dict) and row.get("event_id") == event_id), None)
        payload = {"event_id": event_id, "kind": "world_arc_priority", "priority": 79, "target_host": host_id, "due_at": str(due)}
        if found is None:
            events.append(payload)
        else:
            found.update(payload); found.pop("suspended", None)
        self.put("state/runtime.json", runtime)

    def _record_world_arc_material_history(
        self, *, action_ref: str, actor_ref: str, arc_ref: str, at: str, kind: str, goal: str, target_ref: str | None, evidence: Mapping[str, Any]
    ) -> str:
        event_id = "autonomous_domain_" + hashlib.sha256(f"{action_ref}|{at}|{kind}".encode("utf-8")).hexdigest()[:18]
        history = copy.deepcopy(self.read("state/history/events/index.json"))
        rows = history.setdefault("events", [])
        if not any(isinstance(row, Mapping) and str(row.get("event_id", "")) == event_id for row in rows):
            rows.append({
                "event_id": event_id,
                "kind": kind,
                "at": at,
                "actor_ref": actor_ref,
                "arc_ref": arc_ref,
                "target_ref": target_ref,
                "goal": goal[:500],
                "action_ref": action_ref,
                "material_evidence": copy.deepcopy(dict(evidence)),
                "basis": "actor-owned causal host settled this action independently of the world-arc review",
            })
            write_history_index(self, history)
        return event_id

    def _priority_row(self, actor_ref: str, domain: str, action_ref: str) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        path = self.owner_path(actor_ref)
        doc = copy.deepcopy(self.read(path))
        if domain == "person":
            priorities = doc.setdefault("runtime", {}).setdefault("autonomous_priorities", {})
            if not isinstance(priorities, dict):
                raise ValueError("person autonomous priorities are invalid")
            queue = list(priorities.values())
        elif domain in {"state", "house", "polity"}:
            queue = doc.setdefault("world_arc_priorities", [])
        elif domain == "institution":
            queue = doc.setdefault("operational_priorities", [])
        else:
            raise ValueError("unsupported world-arc priority domain")
        if not isinstance(queue, list):
            raise ValueError("world-arc priority queue is invalid")
        matches = [item for item in queue if isinstance(item, dict) and str(item.get("action_ref", "")) == action_ref]
        if len(matches) > 1:
            raise ValueError("duplicate world-arc priority action_ref")
        row = matches[0] if matches else None
        return path, doc, row

    def _retask_player_controlled_institutional_operation(
        self, *, actor_ref: str, action_ref: str, arc_ref: str, goal: str, target_ref: str | None, at: str
    ) -> dict[str, Any] | None:
        """Issue a lawful institutional order to a player-commanded state detachment.

        Player protection forbids autonomous movement/tactical choices for Tang Wei,
        but it must not make state-owned formations under his accepted field command
        invisible to the state that still owns them.  This bridge may retask the
        *operation objective* and issue an exact order; it never moves Wei, chooses a
        route, resolves a battle, or commandeers House Tang-owned formations.
        """
        try:
            meta = self.read("state/meta.json")
            player_ref = str(meta.get("player_id", self.PLAYER_ACTOR)) if isinstance(meta, Mapping) else self.PLAYER_ACTOR
            index = self.read("state/operations/index.json")
        except (KeyError, FileNotFoundError, ValueError):
            return None
        operations = index.get("operations", {}) if isinstance(index, Mapping) else {}
        if not isinstance(operations, Mapping):
            return None
        actor_state = str(actor_ref).removeprefix("state_")
        expected_force_ref = f"force_state_{actor_state}"
        for operation_ref, op_path in sorted(operations.items()):
            if not isinstance(operation_ref, str) or not isinstance(op_path, str):
                continue
            operation0 = self.read_optional(op_path)
            if not isinstance(operation0, Mapping) or str(operation0.get("status", "")) not in {"planned", "mobilizing", "active", "advancing", "engaged"}:
                continue
            objective_refs = operation0.get("objective_refs", [])
            if not isinstance(objective_refs, list) or arc_ref not in objective_refs:
                continue
            institutional_owner = str(operation0.get("institutional_owner_ref") or operation0.get("administrative_authority") or "")
            source_force = str(operation0.get("source_force_ref") or (operation0.get("authority_basis", {}) or {}).get("source_force_ref") or "")
            if institutional_owner != actor_ref and source_force != expected_force_ref:
                continue
            assignment_authority = str(operation0.get("assignment_authority_ref") or operation0.get("administrative_authority") or "")
            group_ref = str(operation0.get("command_group_ref") or "")
            player_controlled = assignment_authority == player_ref
            if not player_controlled and group_ref.startswith("cmdgrp."):
                group = self.read_optional(f"state/cmd/command-groups/{group_ref}.json")
                player_controlled = isinstance(group, Mapping) and (str(group.get("commander_ref")) == player_ref or str(group.get("authority_ref")) == player_ref)
            if not player_controlled:
                continue

            state_owned_refs: list[str] = []
            excluded_house_refs: list[str] = []
            for formation_ref in operation0.get("formation_refs", []) if isinstance(operation0.get("formation_refs"), list) else []:
                if not isinstance(formation_ref, str):
                    continue
                try:
                    _fp, formation = self._load_formation(formation_ref)
                except ValueError:
                    continue
                owner_force_ref = str(formation.get("owner_force_ref", ""))
                if owner_force_ref == expected_force_ref:
                    state_owned_refs.append(formation_ref)
                else:
                    excluded_house_refs.append(formation_ref)
            if not state_owned_refs:
                continue

            operation = copy.deepcopy(dict(operation0))
            order_goal = goal[:500]
            try:
                arc_doc = self.read("state/arc/kingdom-arcs.json")
                records = arc_doc.get("records", []) if isinstance(arc_doc, Mapping) else []
                arc_row = next((row for row in records if isinstance(row, Mapping) and str(row.get("record_id", "")) == arc_ref), None)
                facts = arc_row.get("facts", {}) if isinstance(arc_row, Mapping) and isinstance(arc_row.get("facts"), Mapping) else {}
                stage = str(facts.get("stage", ""))
                basis = str(facts.get("current_basis", "")).strip()
                if stage in {"active_operation", "campaign", "battle", "siege"} and basis:
                    order_goal = f"participate in {basis}; execute the institutional order with the assigned Qin formations under Tang Wei's current field-command authority"[:500]
            except (KeyError, FileNotFoundError, ValueError):
                pass
            order_ref = "operational_order_" + hashlib.sha256(f"{actor_ref}|{operation_ref}|{arc_ref}|{action_ref}|{order_goal}|{target_ref}".encode("utf-8")).hexdigest()[:18]
            orders = operation.setdefault("operational_orders", [])
            if not isinstance(orders, list):
                orders = []
                operation["operational_orders"] = orders
            existing = next((row for row in orders if isinstance(row, Mapping) and str(row.get("order_ref", "")) == order_ref), None)
            if existing is None:
                prior_objective = str(operation.get("objective", ""))
                order = {
                    "order_ref": order_ref,
                    "issued_at": at,
                    "issuer_ref": actor_ref,
                    "arc_ref": arc_ref,
                    "target_ref": target_ref,
                    "objective": order_goal,
                    "prior_objective": prior_objective[:500],
                    "status": "issued_awaiting_commander_execution",
                    "applies_to_formation_refs": sorted(state_owned_refs),
                    "excluded_non_state_formation_refs": sorted(excluded_house_refs),
                    "agency_rule": "state may order/retask its own formations under Tang Wei's accepted command; the order does not move Tang Wei, select his route/tactics, or commandeer House Tang-owned troops",
                }
                orders.append(order)
                operation["operational_orders"] = orders[-16:]
                operation["objective"] = order_goal
                refs = [str(x) for x in operation.get("objective_refs", []) if isinstance(x, str)]
                for ref in (arc_ref, target_ref):
                    if isinstance(ref, str) and ref and ref not in refs:
                        refs.append(ref)
                operation["objective_refs"] = refs
                operation["last_operational_order_ref"] = order_ref
                operation["last_operational_order_at"] = at
                operation["order_status"] = "awaiting_commander_execution"
                operation["autonomous"] = False
                operation["institutional_owner_ref"] = actor_ref
                operation["source_force_ref"] = expected_force_ref
                self.put(op_path, operation)
            return {
                "kind": "player_command_operational_order_issued",
                "operation_ref": operation_ref,
                "order_ref": order_ref,
                "issuer_ref": actor_ref,
                "formation_refs": sorted(state_owned_refs),
                "excluded_non_state_formation_refs": sorted(excluded_house_refs),
                "objective": order_goal,
                "target_ref": target_ref,
                "movement_committed": False,
                "tactical_decision_committed": False,
                "evidence_stage": "external_consequence",
            }
        return None

    def _priority_operation_evidence(
        self, *, actor_ref: str, action_ref: str, arc_ref: str, goal: str, target_ref: str | None, at: str, force_refs: list[str], kind: str
    ) -> dict[str, Any] | None:
        """Materialize a bounded mobilization operation from actor-owned forces.

        Player-commanded formations and formations already committed to an active
        operation are excluded.  Creation changes the exact operation registry and
        the exact formation's mobilization state, so it is real domain evidence.
        """
        player_order = self._retask_player_controlled_institutional_operation(
            actor_ref=actor_ref, action_ref=action_ref, arc_ref=arc_ref, goal=goal, target_ref=target_ref, at=at
        )
        if isinstance(player_order, Mapping):
            return dict(player_order)

        index = copy.deepcopy(self.read("state/operations/index.json"))
        active_formations: set[str] = set()
        for _op_ref, op_path in index.get("operations", {}).items():
            if not isinstance(op_path, str):
                continue
            op = self.read_optional(op_path)
            if not isinstance(op, Mapping) or str(op.get("status", "")) not in {"active", "mobilizing", "advancing", "engaged", "occupied"}:
                continue
            active_formations.update(str(x) for x in op.get("formation_refs", []) if isinstance(x, str))
        candidates: list[tuple[int, str, str, dict[str, Any]]] = []
        for force_ref in force_refs:
            try:
                force = self.read(self.owner_path(force_ref))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            allocated = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
            for formation_ref in sorted(str(x) for x in allocated):
                if formation_ref in active_formations:
                    continue
                try:
                    formation_path, formation0 = self._load_formation(formation_ref)
                except ValueError:
                    continue
                formation = copy.deepcopy(formation0)
                if int(formation.get("personnel", 0)) <= 0:
                    continue
                if str(formation.get("command_authority", "")) == self.PLAYER_ACTOR or str(formation.get("commander_ref", "")) == self.PLAYER_ACTOR:
                    continue
                score = int(formation.get("readiness", 0)) + int(formation.get("cohesion", 0)) + min(100, int(formation.get("personnel", 0)) // 10)
                candidates.append((score, formation_ref, formation_path, formation))
        if not candidates:
            return None
        _score, formation_ref, formation_path, formation = sorted(candidates, key=lambda row: (-row[0], row[1]))[0]
        old_status = str(formation.get("status", ""))
        formation["mobilized"] = True
        if old_status in {"forming", "ready", "garrisoned", "reserve"}:
            formation["status"] = "mobilized"
        formation.setdefault("autonomous_orders", []).append({"at": at, "kind": kind, "arc_ref": arc_ref, "action_ref": action_ref, "goal": goal[:500], "target_ref": target_ref})
        formation["autonomous_orders"] = formation["autonomous_orders"][-16:]
        self.put(formation_path, formation)
        op_ref = "operation_arc_" + hashlib.sha256(f"{action_ref}|{at}".encode("utf-8")).hexdigest()[:18]
        op_path = f"state/operations/{op_ref}.json"
        if self.read_optional(op_path) is None:
            operation = {
                "schema": "sword-operation",
                "owner_id": op_ref,
                "operation_ref": op_ref,
                "status": "active",
                "kind": kind,
                "objective": goal[:500],
                "objective_refs": [x for x in [arc_ref, target_ref] if isinstance(x, str) and x],
                "location_ref": str(formation.get("location_ref", "")),
                "formation_refs": [formation_ref],
                "administrative_authorities": [actor_ref],
                "administrative_authority": actor_ref,
                "created_at": at,
                "authority_basis": {"actor_ref": actor_ref, "force_ref": str(formation.get("owner_force_ref", "")), "rule": "actor-owned priority consumer may mobilize only a non-player-controlled formation from the actor's exact force authority"},
                "victory_criteria": ["the saved objective reaches an exact material consequence owned by its target subsystem"],
                "termination_criteria": ["the objective is withdrawn, superseded, blocked, or settled"],
            }
            self.put(op_path, operation)
            index.setdefault("operations", {})[op_ref] = op_path
            self.put("state/operations/index.json", index)
            self._register_owner(op_ref, op_path)
        return {"kind": "exact_operation_created", "operation_ref": op_ref, "formation_ref": formation_ref, "formation_status_before": old_status, "formation_status_after": str(formation.get("status", old_status)), "evidence_stage": "domain_action"}

    def _settle_world_arc_priority_host(self, host: Mapping[str, Any], at: str) -> None:
        actor_ref = str(host.get("owner_ref", "")); domain = str(host.get("domain", "")); action_ref = str(host.get("action_ref", ""))
        if not actor_ref or not action_ref or domain not in {"person", "state", "house", "polity", "institution"}:
            return
        try:
            path, doc, row = self._priority_row(actor_ref, domain, action_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return
        if not isinstance(row, dict) or str(row.get("status", "")) not in {"queued", "queued_for_institutional_review", "attempted", "commitment_settled"}:
            return
        prior_status = str(row.get("status", ""))
        prior_evidence = copy.deepcopy(row.get("material_evidence")) if isinstance(row.get("material_evidence"), Mapping) else None
        arc_ref = str(row.get("arc_ref", "")); goal = str(row.get("goal", "")); target_ref = str(row.get("target_ref")) if row.get("target_ref") is not None else None
        evidence: dict[str, Any] | None = None
        action_kind = f"{domain}_autonomous_directive"

        if domain == "person":
            # The live priority row is current causal state. Durable proof belongs
            # only in semantic history; do not grow a second per-person action log.
            evidence = {"kind": "exact_person_commitment", "person_ref": actor_ref, "action_ref": action_ref, "evidence_stage": "commitment"}
            action_kind = "autonomous_person_commitment"
        elif domain == "state":
            state = self._state_key(actor_ref)
            evidence = self._priority_operation_evidence(actor_ref=actor_ref, action_ref=action_ref, arc_ref=arc_ref, goal=goal, target_ref=target_ref, at=at, force_refs=[f"force_state_{state}"], kind="state_world_arc_operation")
            if evidence is None:
                directives = doc.setdefault("strategic_directives", [])
                if not any(isinstance(x, Mapping) and str(x.get("action_ref", "")) == action_ref for x in directives):
                    directives.append({"at": at, "action_ref": action_ref, "arc_ref": arc_ref, "goal": goal[:500], "target_ref": target_ref, "status": "issued"}); del directives[:-32]
                evidence = {"kind": "exact_state_directive", "state_ref": actor_ref, "action_ref": action_ref, "evidence_stage": "commitment"}
            action_kind = "autonomous_state_directive"
        elif domain == "polity":
            force_refs = [str(x) for x in doc.get("military_force_refs", []) if isinstance(x, str)]
            evidence = self._priority_operation_evidence(actor_ref=actor_ref, action_ref=action_ref, arc_ref=arc_ref, goal=goal, target_ref=target_ref, at=at, force_refs=force_refs, kind="polity_world_arc_operation")
            if evidence is None:
                directives = doc.setdefault("strategic_directives", [])
                if not any(isinstance(x, Mapping) and str(x.get("action_ref", "")) == action_ref for x in directives):
                    directives.append({"at": at, "action_ref": action_ref, "arc_ref": arc_ref, "goal": goal[:500], "target_ref": target_ref, "status": "issued"}); del directives[:-32]
                evidence = {"kind": "exact_polity_directive", "polity_ref": actor_ref, "action_ref": action_ref, "evidence_stage": "commitment"}
            action_kind = "autonomous_polity_directive"
        elif domain == "house":
            force_ref = str(doc.get("military_force_ref", ""))
            evidence = self._priority_operation_evidence(actor_ref=actor_ref, action_ref=action_ref, arc_ref=arc_ref, goal=goal, target_ref=target_ref, at=at, force_refs=[force_ref] if force_ref else [], kind="house_world_arc_operation")
            if evidence is None:
                actions = doc.setdefault("material_directives", [])
                if not any(isinstance(x, Mapping) and str(x.get("action_ref", "")) == action_ref for x in actions):
                    actions.append({"at": at, "action_ref": action_ref, "arc_ref": arc_ref, "goal": goal[:500], "target_ref": target_ref, "status": "issued"}); del actions[:-24]
                evidence = {"kind": "exact_house_directive", "house_ref": actor_ref, "action_ref": action_ref, "evidence_stage": "commitment"}
            action_kind = "autonomous_house_directive"
        else:
            orders = doc.setdefault("operational_orders", [])
            order = {"at": at, "action_ref": action_ref, "arc_ref": arc_ref, "goal": goal[:500], "target_ref": target_ref, "status": "issued", "capacity_basis": int(doc.get("capacity", 0))}
            if not any(isinstance(x, Mapping) and str(x.get("action_ref", "")) == action_ref for x in orders):
                orders.append(order); del orders[:-24]
            evidence = {"kind": "exact_institution_order", "institution_ref": actor_ref, "action_ref": action_ref, "capacity": int(doc.get("capacity", 0)), "evidence_stage": "commitment"}
            action_kind = "autonomous_institution_order"

        stage = str(evidence.get("evidence_stage", "commitment"))
        # Rechecking an already-settled commitment is deliberately quiet.  If the
        # actor still cannot materialize the priority, keep one durable row, one
        # original commitment/history record, and only record the bounded recheck.
        # A later transition to domain_action/external_consequence is new semantic
        # history and is recorded normally.
        if prior_status == "commitment_settled" and stage == "commitment":
            row["last_checked_at"] = at
            row["recheck_count"] = min(255, int(row.get("recheck_count", 0)) + 1)
            if prior_evidence is not None:
                row["material_evidence"] = prior_evidence
                row["evidence_stage"] = str(prior_evidence.get("evidence_stage", "commitment"))
            self.put(path, doc)
            return

        history_ref = self._record_world_arc_material_history(action_ref=action_ref, actor_ref=actor_ref, arc_ref=arc_ref, at=at, kind=action_kind, goal=goal, target_ref=target_ref, evidence=evidence)
        evidence = {**evidence, "history_event_ref": history_ref}
        row["status"] = "material_settled" if stage in {"domain_action", "external_consequence"} else "commitment_settled"
        row["settled_at"] = at
        row["evidence_stage"] = stage
        row["material_evidence"] = copy.deepcopy(evidence)
        row["arc_observed"] = False
        self.put(path, doc)

    def _world_arc_completed_priority(self, actor_ref: str, arc_ref: str, target_ref: str | None = None, goal: str | None = None) -> dict[str, Any] | None:
        domain = "person" if actor_ref.startswith("char_") else "state" if actor_ref.startswith("state_") else "polity" if actor_ref.startswith("polity_") else "house" if actor_ref.startswith("house_") else "institution" if actor_ref.startswith("inst_") else None
        if domain is None:
            return None
        try:
            path, doc, _row = self._priority_row(actor_ref, domain, "")
        except (KeyError, ValueError, FileNotFoundError):
            return None
        if domain == "person":
            priorities = doc.get("runtime", {}).get("autonomous_priorities", {})
            queue = list(priorities.values()) if isinstance(priorities, Mapping) else []
        else:
            queue = doc.get("operational_priorities", []) if domain == "institution" else doc.get("world_arc_priorities", [])
        if not isinstance(queue, list):
            return None
        row = next((x for x in queue if isinstance(x, dict) and str(x.get("arc_ref", "")) == arc_ref and str(x.get("status", "")) in {"material_settled", "commitment_settled"} and x.get("arc_observed") is not True and (target_ref is None or (str(x.get("target_ref")) if x.get("target_ref") is not None else "") == str(target_ref)) and (goal is None or str(x.get("goal", "")) == goal[:500])), None)
        if not isinstance(row, dict):
            return None
        evidence = row.get("material_evidence") if isinstance(row.get("material_evidence"), Mapping) else None
        if not evidence:
            return None
        stage = str(row.get("evidence_stage", evidence.get("evidence_stage", "commitment")))
        # Commitments/orders are durable actor state, but they are not material arc
        # progress.  Leave them visible as queued evidence without upgrading them.
        if stage == "commitment":
            row["arc_observed"] = True; row["arc_observed_at"] = str(self.read("state/runtime.json").get("world_time", row.get("settled_at", "")))
            self.put(path, doc)
            return {"status": "work_queued", "actor_ref": actor_ref, "action": "actor_commitment_settled", "action_ref": str(row.get("action_ref", "")), "effect": copy.deepcopy(row), "evidence_stage": stage, "material_evidence": copy.deepcopy(dict(evidence))}
        row["arc_observed"] = True; row["arc_observed_at"] = str(self.read("state/runtime.json").get("world_time", row.get("settled_at", "")))
        self.put(path, doc)
        return {"status": "material_action_settled", "actor_ref": actor_ref, "action": "settled_actor_priority", "action_ref": str(row.get("action_ref", "")), "effect": copy.deepcopy(row), "evidence_stage": stage, "material_evidence": copy.deepcopy(dict(evidence))}

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == "settlement_development_project":
            settle_development_project(self, host, due_text)
            self._pending_wake_created = None
            return
        if host.get("kind") == "world_arc_priority":
            self._settle_world_arc_priority_host(host, due_text)
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)

    def _world_arc_person_action(self, actor_ref: str, target_ref: str | None, goal: str, at: str, arc_ref: str) -> dict[str, Any]:
        path, person0 = self._exact_person(actor_ref, active=False)
        person = copy.deepcopy(person0)
        if str(person.get("life_status", person.get("status", "active"))).lower() in {"dead", "deceased"}:
            return {"status": "work_blocked", "reason": "selected exact character is not alive", "actor_ref": actor_ref}
        # Prefer an exact household authority when this person is its saved leader.
        derived_house = "house_" + actor_ref.removeprefix("char_") + "_household"
        house_ref = str(person.get("house_ref", "")) or derived_house
        try:
            hp = self.owner_path(house_ref)
            house = self.read(hp)
        except (KeyError, ValueError, FileNotFoundError):
            house = None
        if isinstance(house, Mapping) and str(house.get("leader_ref", "")) == actor_ref:
            result = self._world_arc_house_action(house_ref, target_ref, goal, at, arc_ref)
            result["delegated_by_person_ref"] = actor_ref
            return result

        text = goal.lower()
        skill_names = ("Diplomacy", "Intelligence Operations", "Governance", "Leadership") if any(x in text for x in ("court", "polit", "royal", "advoc", "network", "service")) else ("Strategy", "Leadership", "Awareness", "Diplomacy")
        skills = merged_skill_map(person)
        capability = sorted(((int(_fixed(skills.get(name, 0))), name) for name in skill_names), reverse=True)
        runtime = person.setdefault("runtime", {})
        priorities = runtime.setdefault("autonomous_priorities", {})
        if not isinstance(priorities, dict):
            raise ValueError("person autonomous priorities are invalid")
        def same_pending_person_arc(row: object) -> bool:
            return (
                isinstance(row, Mapping)
                and str(row.get("arc_ref", "")) == arc_ref
                and (str(row.get("target_ref")) if row.get("target_ref") is not None else "") == (str(target_ref) if target_ref is not None else "")
                and str(row.get("goal", "")) == goal[:500]
                and str(row.get("status", "")) in {"queued", "attempted", "commitment_settled"}
            )
        existing = next((row for row in priorities.values() if same_pending_person_arc(row)), None)
        if isinstance(existing, dict):
            existing["last_reaffirmed_at"] = at
            action_ref = str(existing.get("action_ref", ""))
            record = copy.deepcopy(existing)
        else:
            action_ref = "person_arc_" + hashlib.sha256(f"{actor_ref}|{arc_ref}|{goal}|{target_ref or ''}|{at}".encode("utf-8")).hexdigest()[:18]
            record = {
                "action_ref": action_ref,
                "at": at,
                "kind": "world_arc_personal_initiative",
                "arc_ref": arc_ref,
                "target_ref": target_ref,
                "goal": goal[:500],
                "status": "queued",
            }
            # Bounded current causal queue. Observed terminal rows are discarded
            # before admitting additional work; semantic history keeps the past.
            for ref in [ref for ref,row in priorities.items() if isinstance(row, Mapping) and row.get("arc_observed") is True]:
                priorities.pop(ref, None)
            if len(priorities) >= 4:
                oldest = min(priorities, key=lambda ref: str(priorities[ref].get("at", "")))
                priorities.pop(oldest, None)
            priorities[action_ref] = record
        self.put(path, person)
        self._schedule_world_arc_priority_work(actor_ref=actor_ref, action_ref=action_ref, domain="person", at=at)
        return {"status": "work_queued", "actor_ref": actor_ref, "action": "personal_initiative_attempt", "action_ref": action_ref, "effect": record}

    def _world_arc_state_action(self, actor_ref: str, target_ref: str | None, goal: str, at: str, arc_ref: str) -> dict[str, Any]:
        """Queue state-owned arc work without confusing preparation for progress.

        A state may spend conserved silver to staff/courier a priority, but that is
        only *preparation*.  It does not prove that an army moved, an office changed,
        a treaty was made, a target yielded, or any other strategic consequence
        settled.  Therefore this bridge always returns ``work_queued``.  A later
        owning subsystem must establish an independent material consequence before
        the world arc may gain momentum.
        """
        state = self._state_key(actor_ref)
        path = f"state/states/{state}.json"
        doc = copy.deepcopy(self.read(path))
        admin = max(0, int(doc.get("administrative_capacity", 0)))
        if admin <= 0:
            return {"status": "work_blocked", "reason": "state lacks saved administrative capacity", "actor_ref": actor_ref}
        priorities = doc.setdefault("world_arc_priorities", [])
        if not isinstance(priorities, list):
            raise ValueError("state world-arc priorities are invalid")
        existing = next((
            row for row in reversed(priorities)
            if isinstance(row, dict)
            and str(row.get("arc_ref", "")) == arc_ref
            and (str(row.get("target_ref")) if row.get("target_ref") is not None else "") == (str(target_ref) if target_ref is not None else "")
            and str(row.get("goal", "")) == goal[:500]
            and str(row.get("status", "")) in {"queued", "commitment_settled"}
        ), None)
        if existing is not None:
            existing["last_reaffirmed_at"] = at
            self.put(path, doc)
            self._schedule_world_arc_priority_work(actor_ref=actor_ref, action_ref=str(existing.get("action_ref", "")), domain="state", at=at)
            return {
                "status": "work_queued",
                "actor_ref": actor_ref,
                "action": "state_strategic_priority",
                "action_ref": str(existing.get("action_ref", "")),
                "effect": copy.deepcopy(existing),
                "reason": "state priority remains queued; no independent material consequence has settled",
            }

        treasury = max(0, int(doc.get("treasury_silver", 0)))
        spend = min(treasury, max(100, admin * 10))
        if spend <= 0:
            return {"status": "work_blocked", "reason": "state lacks treasury funds for coordination preparation", "actor_ref": actor_ref}
        action_ref = "state_arc_" + hashlib.sha256(f"{actor_ref}|{arc_ref}|{goal}|{target_ref or ''}|{at}".encode("utf-8")).hexdigest()[:18]
        ep, eco = self._private_economy(state)
        doc["treasury_silver"] = treasury - spend
        eco["cash_silver"] = int(eco.get("cash_silver", 0)) + spend
        priority = {
            "action_ref": action_ref,
            "at": at,
            "arc_ref": arc_ref,
            "target_ref": target_ref,
            "goal": goal[:500],
            "status": "queued",
            "coordination_spent_silver": spend,
            "payer_ref": actor_ref,
            "payee_ref": f"private_economy_{state}",
            "basis": "exact state treasury funded preparation only; a separate domain consequence is required before arc momentum can increase",
        }
        priorities.append(priority)
        del priorities[:-32]
        doc.setdefault("autonomous_actions", []).append({"at": at, "kind": "strategic_priority_queued", "action_ref": action_ref, "arc_ref": arc_ref, "target_ref": target_ref, "coordination_spent_silver": spend})
        doc["autonomous_actions"] = doc["autonomous_actions"][-24:]
        self._write_private_economy(ep, eco)
        self.put(path, doc)
        self._schedule_world_arc_priority_work(actor_ref=actor_ref, action_ref=action_ref, domain="state", at=at)
        return {
            "status": "work_queued",
            "actor_ref": actor_ref,
            "action": "state_strategic_priority",
            "action_ref": action_ref,
            "effect": priority,
            "spent": {"silver": spend},
            "preparation_evidence": {
                "kind": "conserved_silver_transfer",
                "payer_ref": actor_ref,
                "payee_ref": f"private_economy_{state}",
                "silver_transferred": spend,
            },
        }

    def _world_arc_polity_action(self, actor_ref: str, target_ref: str | None, goal: str, at: str, arc_ref: str) -> dict[str, Any]:
        """Queue sovereign preparation; preparation alone never advances an arc."""
        path = self.owner_path(actor_ref)
        polity = copy.deepcopy(self.read(path))
        if str(polity.get("status", "")) not in {"proto_state", "recognized_state"}:
            return {"status": "work_blocked", "reason": "polity lacks active territorial sovereignty", "actor_ref": actor_ref}
        treasury_ref = str(polity.get("treasury_ref", ""))
        if not treasury_ref:
            return {"status": "work_blocked", "reason": "polity lacks exact treasury authority", "actor_ref": actor_ref}
        queue = polity.setdefault("world_arc_priorities", [])
        if not isinstance(queue, list):
            raise ValueError("polity world-arc priorities are invalid")
        existing = next((
            row for row in reversed(queue)
            if isinstance(row, dict)
            and str(row.get("arc_ref", "")) == arc_ref
            and (str(row.get("target_ref")) if row.get("target_ref") is not None else "") == (str(target_ref) if target_ref is not None else "")
            and str(row.get("goal", "")) == goal[:500]
            and str(row.get("status", "")) in {"queued", "commitment_settled"}
        ), None)
        if existing is not None:
            existing["last_reaffirmed_at"] = at
            self.put(path, polity)
            self._schedule_world_arc_priority_work(actor_ref=actor_ref, action_ref=str(existing.get("action_ref", "")), domain="polity", at=at)
            return {
                "status": "work_queued", "actor_ref": actor_ref,
                "action": "polity_strategic_priority", "action_ref": str(existing.get("action_ref", "")),
                "effect": copy.deepcopy(existing),
                "reason": "sovereign priority remains queued; no independent material consequence has settled",
            }
        treasury_path = self.owner_path(treasury_ref); treasury = copy.deepcopy(self.read(treasury_path)); funds_key, funds = self._funds_value(treasury)
        admin = max(0, int(polity.get("administrative_capacity", 0))); spend = min(max(0, funds), max(100, admin * 10))
        if spend <= 0:
            return {"status": "work_blocked", "reason": "polity lacks treasury funds for coordination preparation", "actor_ref": actor_ref}
        seat = str(polity.get("seat_claim_ref", "")) or next((str(x) for x in polity.get("occupied_site_refs", []) if isinstance(x, str)), "")
        economy_state = str(polity.get("economy_state_key", ""))
        if not economy_state:
            economy_state = str(self._native_site_state(seat) or "") if seat else ""
        if not economy_state:
            return {"status": "work_blocked", "reason": "polity has no exact local economy at its seat", "actor_ref": actor_ref}
        action_ref = "polity_arc_" + hashlib.sha256(f"{actor_ref}|{arc_ref}|{goal}|{target_ref or ''}|{at}".encode("utf-8")).hexdigest()[:18]
        ep, eco = self._private_economy(economy_state); treasury[funds_key] = funds - spend
        regions = eco.get("local_regions", {}).get("regions", {}) if isinstance(eco.get("local_regions"), Mapping) else {}
        self._adjust_local_pool(regions, "cash_silver", None, spend)
        priority = {"action_ref": action_ref, "at": at, "arc_ref": arc_ref, "target_ref": target_ref, "goal": goal[:500], "status": "queued", "coordination_spent_silver": spend, "payer_ref": treasury_ref, "payee_ref": f"private_economy_{economy_state}", "basis": "exact sovereign treasury funded preparation only; a separate domain consequence is required before arc momentum can increase"}
        queue.append(priority); polity["world_arc_priorities"] = queue[-32:]
        polity.setdefault("autonomous_actions", []).append({"at": at, "kind": "strategic_priority_queued", "action_ref": action_ref, "arc_ref": arc_ref, "target_ref": target_ref, "coordination_spent_silver": spend}); polity["autonomous_actions"] = polity["autonomous_actions"][-24:]
        self.put(treasury_path, treasury); self._sync_local_economy_aggregate(eco); self._write_private_economy(ep, eco); self.put(path, polity)
        return {
            "status": "work_queued",
            "actor_ref": actor_ref,
            "action": "polity_strategic_priority",
            "action_ref": action_ref,
            "effect": priority,
            "spent": {"silver": spend},
            "preparation_evidence": {
                "kind": "conserved_silver_transfer",
                "payer_ref": treasury_ref,
                "payee_ref": f"private_economy_{economy_state}",
                "silver_transferred": spend,
            },
        }

    def _world_arc_house_action(self, actor_ref: str, target_ref: str | None, goal: str, at: str, arc_ref: str) -> dict[str, Any]:
        """Queue House-owned preparation without treating it as strategic progress."""
        path = self.owner_path(actor_ref)
        house = copy.deepcopy(self.read(path))
        if str(house.get("status", "active")).lower() in {"destroyed", "dissolved"}:
            return {"status": "work_blocked", "reason": "selected House is inactive", "actor_ref": actor_ref}
        state = str(house.get("state", "")).lower().replace("state_", "")
        queue = house.setdefault("world_arc_priorities", [])
        if not isinstance(queue, list):
            raise ValueError("House world-arc priorities are invalid")
        existing = next((
            row for row in reversed(queue)
            if isinstance(row, dict)
            and str(row.get("arc_ref", "")) == arc_ref
            and (str(row.get("target_ref")) if row.get("target_ref") is not None else "") == (str(target_ref) if target_ref is not None else "")
            and str(row.get("goal", "")) == goal[:500]
            and str(row.get("status", "")) in {"queued", "commitment_settled"}
        ), None)
        if existing is not None:
            existing["last_reaffirmed_at"] = at
            self.put(path, house)
            self._schedule_world_arc_priority_work(actor_ref=actor_ref, action_ref=str(existing.get("action_ref", "")), domain="house", at=at)
            return {
                "status": "work_queued", "actor_ref": actor_ref,
                "action": "household_initiative", "action_ref": str(existing.get("action_ref", "")),
                "effect": copy.deepcopy(existing),
                "reason": "House priority remains queued; no independent material consequence has settled",
            }
        action_ref = "house_arc_" + hashlib.sha256(f"{actor_ref}|{arc_ref}|{goal}|{target_ref or ''}|{at}".encode("utf-8")).hexdigest()[:18]
        spend = 0
        payer_ref = actor_ref
        treasury_ref = str(house.get("treasury_ref", ""))
        treasury_path = None
        treasury_doc = None
        if treasury_ref:
            try:
                treasury_path = self.owner_path(treasury_ref)
                treasury_doc = copy.deepcopy(self.read(treasury_path))
                available = max(0, int(treasury_doc.get("silver", 0)))
                spend = min(available, 100)
                if spend:
                    treasury_doc["silver"] = available - spend
                    payer_ref = treasury_ref
            except (KeyError, ValueError, FileNotFoundError):
                treasury_path = None
                treasury_doc = None
        else:
            available = max(0, int(house.get("treasury_silver", 0)))
            spend = min(available, 100)
            if spend:
                house["treasury_silver"] = available - spend
        if spend <= 0 or state not in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
            record = {
                "kind": "world_arc_house_initiative", "action_ref": action_ref, "at": at,
                "arc_ref": arc_ref, "target_ref": target_ref, "goal": goal[:500],
                "status": "queued", "basis": "House objective saved, but no conserved coordination payment could settle",
            }
            queue.append(copy.deepcopy(record))
            del queue[:-24]
            self.put(path, house)
            self._schedule_world_arc_priority_work(actor_ref=actor_ref, action_ref=action_ref, domain="house", at=at)
            return {"status": "work_queued", "actor_ref": actor_ref, "action": "household_initiative", "action_ref": action_ref, "effect": record}
        ep, eco = self._private_economy(state)
        eco["cash_silver"] = int(eco.get("cash_silver", 0)) + spend
        record = {
            "kind": "world_arc_house_initiative", "action_ref": action_ref, "at": at,
            "arc_ref": arc_ref, "target_ref": target_ref, "goal": goal[:500],
            "status": "queued", "coordination_spent_silver": spend,
            "payer_ref": payer_ref, "payee_ref": f"private_economy_{state}",
            "basis": "exact House treasury funded preparation only; a separate domain consequence is required before arc momentum can increase",
        }
        queue.append(copy.deepcopy(record))
        house["world_arc_priorities"] = queue[-24:]
        if treasury_path and treasury_doc is not None:
            self.put(treasury_path, treasury_doc)
        self._write_private_economy(ep, eco)
        self.put(path, house)
        self._schedule_world_arc_priority_work(actor_ref=actor_ref, action_ref=action_ref, domain="house", at=at)
        return {
            "status": "work_queued",
            "actor_ref": actor_ref,
            "action": "household_initiative",
            "action_ref": action_ref,
            "effect": record,
            "spent": {"silver": spend},
            "preparation_evidence": {
                "kind": "conserved_silver_transfer",
                "payer_ref": payer_ref,
                "payee_ref": f"private_economy_{state}",
                "silver_transferred": spend,
            },
        }

    def _world_arc_institution_action(self, actor_ref: str, target_ref: str | None, goal: str, at: str, arc_ref: str) -> dict[str, Any]:
        path = self.owner_path(actor_ref)
        inst = copy.deepcopy(self.read(path))
        if int(inst.get("capacity", 0)) <= 0:
            return {"status": "work_blocked", "reason": "institution has no saved operating capacity", "actor_ref": actor_ref}
        action_ref = "inst_arc_" + hashlib.sha256(f"{actor_ref}|{arc_ref}|{at}|{goal}".encode("utf-8")).hexdigest()[:18]
        priority = {
            "action_ref": action_ref,
            "at": at,
            "arc_ref": arc_ref,
            "target_ref": target_ref,
            "goal": goal[:500],
            "status": "queued_for_institutional_review",
            "basis": "existing institution capacity only; no material output is created without its normal funded workflow",
        }
        queue = inst.setdefault("operational_priorities", [])
        if not isinstance(queue, list):
            raise ValueError("institution operational priorities are invalid")
        existing = next((
            row for row in reversed(queue)
            if isinstance(row, dict)
            and str(row.get("arc_ref", "")) == arc_ref
            and (str(row.get("target_ref")) if row.get("target_ref") is not None else "") == (str(target_ref) if target_ref is not None else "")
            and str(row.get("goal", "")) == goal[:500]
            and (str(row.get("status", "")).startswith("queued") or str(row.get("status", "")) == "commitment_settled")
        ), None)
        if existing is not None:
            existing["last_reaffirmed_at"] = at
            action_ref = str(existing.get("action_ref", action_ref))
            priority = copy.deepcopy(existing)
        else:
            queue.append(priority)
            del queue[:-32]
        self.put(path, inst)
        self._schedule_world_arc_priority_work(actor_ref=actor_ref, action_ref=action_ref, domain="institution", at=at)
        return {"status": "work_queued", "actor_ref": actor_ref, "action": "institutional_priority", "action_ref": action_ref, "effect": priority}

    def _world_arc_domain_action(self, actor_ref: str, target_ref: str | None, goal: str, at: str, arc_ref: str) -> dict[str, Any]:
        """Dispatch an arc-selected actor to its exact owning domain.

        The bridge may register/attempt actor-owned work, but it never supplies the
        external outcome that the target subsystem must establish.
        """
        completed = self._world_arc_completed_priority(actor_ref, arc_ref, target_ref, goal)
        if completed is not None:
            return completed
        faction_ref = self._faction_for_actor(actor_ref)
        if faction_ref is None:
            if actor_ref.startswith("char_"):
                return self._world_arc_person_action(actor_ref, target_ref, goal, at, arc_ref)
            if actor_ref.startswith("state_"):
                return self._world_arc_state_action(actor_ref, target_ref, goal, at, arc_ref)
            if actor_ref.startswith("polity_"):
                return self._world_arc_polity_action(actor_ref, target_ref, goal, at, arc_ref)
            if actor_ref.startswith("house_"):
                return self._world_arc_house_action(actor_ref, target_ref, goal, at, arc_ref)
            if actor_ref.startswith("inst_"):
                return self._world_arc_institution_action(actor_ref, target_ref, goal, at, arc_ref)
            return {"status": "intent_recorded", "reason": "no exact domain action route for this actor", "actor_ref": actor_ref}
        path = self.owner_path(faction_ref)
        before = copy.deepcopy(self.read(path))
        profile = self._faction_profile(faction_ref)
        knowledge_basis = self._faction_knowledge_basis(faction_ref, before, profile, at)
        if bool(profile.get("knowledge_required")) and not knowledge_basis:
            return {"status": "work_blocked", "reason": "faction lacks exact actionable knowledge", "faction_ref": faction_ref}
        before_count = int(before.get("action_count", 0) or 0)
        before["pressure"] = max(30, int(before.get("pressure", 0)))
        before["last_arc_pressure"] = {"at": at, "arc_ref": arc_ref, "goal": goal[:500], "target_ref": target_ref}
        self.put(path, before)
        self._autonomy_faction({"owner_ref": faction_ref}, 1, at)
        after = copy.deepcopy(self.read(path))
        if int(after.get("action_count", 0) or 0) <= before_count:
            return {"status": "work_blocked", "reason": str(after.get("last_blocked_reason", "faction action did not settle")), "faction_ref": faction_ref}
        commitment = copy.deepcopy(after.get("last_action", {})) if isinstance(after.get("last_action"), Mapping) else {}
        if not commitment:
            return {"status": "work_blocked", "reason": "faction action produced no current action result", "faction_ref": faction_ref}
        relation_updates: list[dict[str, Any]] = []
        if isinstance(target_ref, str) and target_ref.startswith("faction_") and target_ref != faction_ref:
            relation_updates.append(self._update_faction_relationship(faction_ref, target_ref, at=at, delta=-3, kind="contested_world_arc"))
            try:
                relation_updates.append(self._update_faction_relationship(target_ref, faction_ref, at=at, delta=-2, kind="contested_world_arc"))
            except (FileNotFoundError, KeyError, ValueError):
                pass
        spent = commitment.get("spent", {}) if isinstance(commitment.get("spent"), Mapping) else {}
        effect = commitment.get("effect", {}) if isinstance(commitment.get("effect"), Mapping) else {}
        material_evidence: dict[str, Any] = {}
        positive_spend = {str(key): value for key, value in spent.items() if _fixed(value, 0) > 0}
        if positive_spend:
            material_evidence["spent"] = positive_spend
        if effect:
            material_evidence["effect"] = copy.deepcopy(effect)
        if not material_evidence:
            return {
                "status": "work_queued",
                "faction_ref": faction_ref,
                "action": commitment.get("action"),
                "reason": "faction review created no verifiable material/resource effect",
                "effect": effect,
                "spent": spent,
                "knowledge_refs_used": commitment.get("knowledge_refs_used", []),
                "relationship_updates": relation_updates,
            }
        evidence_stage = "external_consequence" if (positive_spend or effect) else "domain_action"
        material_evidence["evidence_stage"] = evidence_stage
        return {
            "status": "material_action_settled",
            "evidence_stage": evidence_stage,
            "faction_ref": faction_ref,
            "action": commitment.get("action"),
            "effect": effect,
            "spent": spent,
            "knowledge_refs_used": commitment.get("knowledge_refs_used", []),
            "relationship_updates": relation_updates,
            "material_evidence": material_evidence,
        }

    def _polity_mobilization_effects(self, polity: Mapping[str, Any]) -> dict[str, Any]:
        value = str((polity.get("mobilization_policy") or {}).get("value", "balanced")) if isinstance(polity.get("mobilization_policy"), Mapping) else "balanced"
        table = self._civil_rules().get("mobilization_policy", {})
        if not isinstance(table, Mapping):
            table = {}
        raw = table.get(value, table.get("balanced", {}))
        if not isinstance(raw, Mapping):
            raw = {}
        out = {
            "readiness_target": int(raw.get("readiness_target", 60)),
            "threat_threshold": int(raw.get("threat_threshold", 35)),
            "operation_capacity": max(1, int(raw.get("operation_capacity", 3))),
            "recruitment_factor": max(0.0, _fixed(raw.get("recruitment_factor", 1.0), 1.0)),
            "expeditionary": value in {"balanced", "expeditionary", "total_war"},
            "value": value,
        }
        return out

    def _autonomy_polity_court(self, polity_ref: str, polity: dict[str, Any], at: str) -> None:
        """Advance exact sovereign court cases without inventing a player's verdict."""
        now = CampaignTime.parse(at); pending: list[str] = []
        for case_ref in [str(x) for x in polity.get("court_case_refs", []) if isinstance(x, str)]:
            try: case_path = self.owner_path(case_ref); case = copy.deepcopy(self.read(case_path))
            except (KeyError, ValueError, FileNotFoundError): continue
            status = str(case.get("status", "")); due_text = case.get("next_review_at")
            if status in {"decided", "dismissed"}: continue
            pending.append(case_ref)
            if not isinstance(due_text, str) or CampaignTime.parse(due_text) > now: continue
            if status in {"open", "remanded"}:
                case["status"] = "investigating"; case["stage"] = "evidence_review"; case["next_review_at"] = str(now.add_seconds(30 * 86400)); event = "investigation_opened"
            elif status == "investigating":
                case["status"] = "hearing"; case["stage"] = "hearing"; case["next_review_at"] = str(now.add_seconds(30 * 86400)); event = "hearing_opened"
            elif status == "hearing":
                case["status"] = "decision_required"; case["stage"] = "decision_required"; case.pop("next_review_at", None); event = "decision_required"
            else:
                continue
            case.setdefault("history", []).append({"at": at, "event": event, "basis": "exact sovereign court monthly procedure"}); case["history"] = case["history"][-64:]; self.put(case_path, case)
        polity["court_runtime"] = {"last_review": at, "active_case_refs": pending[-64:], "player_verdicts_are_never_auto_selected": True}

    def _settle_minor_polity(self, polity_ref: str, occurrences: int, at: str) -> None:
        """Monthly close for a living exact minor polity using universal civil rules.

        Productive land plus conserved labor creates stock through the same private
        economy resolver used by major states.  Sovereign revenue is the universal
        tax on realized local output and is paid only from cash that actually exists.
        No static minor-polity revenue envelope, free food, or readiness manpower is
        created here.
        """
        polity_path = self.owner_path(polity_ref)
        polity = copy.deepcopy(self.read(polity_path))
        population_ref = str(polity.get("population_ref", ""))
        force_refs = [str(x) for x in polity.get("military_force_refs", []) if isinstance(x, str)]
        treasury_ref = str(polity.get("treasury_ref", ""))
        economy_ref = str(polity.get("economy_ref", ""))
        economy_state = str(polity.get("economy_state_key", ""))
        if not population_ref or not treasury_ref or not economy_ref or not economy_state:
            raise ValueError("minor polity lacks exact population/treasury/economy authority")
        months = max(1, int(occurrences))
        population = self.read(self.owner_path(population_ref))
        if int(population.get("population_total", 0)) != sum(max(0, int(v)) for v in population.get("strata", {}).values()):
            raise ValueError("minor polity population strata do not conserve population_total")

        # Civil production consumes civilian food and records taxable realized activity.
        self._settle_private_production(economy_state, months, at)
        economy_path, economy = self._private_economy(economy_state)
        treasury_path = self.owner_path(treasury_ref)
        treasury = copy.deepcopy(self.read(treasury_path))
        fiscal = self._state_fiscal_rules()
        tax_rate = max(0.0, min(1.0, _fixed(fiscal.get("universal_tax_rate_fraction_of_taxable_output", 0.10), 0.10)))
        admin = max(0, int(polity.get("administrative_capacity", 0)))
        admin_rules = fiscal.get("administration_realization", {}) if isinstance(fiscal, Mapping) else {}
        floor = max(0.0, _fixed(admin_rules.get("floor_factor", 0.45), 0.45))
        marginal = max(0.0, _fixed(admin_rules.get("marginal_factor", 0.75), 0.75))
        scale = max(1.0, _fixed(admin_rules.get("diminishing_scale", 80.0), 80.0))
        admin_realization = max(0.0, min(1.0, floor + marginal * (1.0 - math.exp(-admin / scale))))
        regions = economy.get("local_regions", {}).get("regions", {}) if isinstance(economy.get("local_regions"), Mapping) else {}
        assessed = 0
        paid = 0
        detail = []
        for ref, region in sorted(regions.items()):
            if not isinstance(region, dict):
                continue
            production = region.get("production_runtime", {}) if isinstance(region.get("production_runtime"), Mapping) else {}
            taxable = max(0, int(production.get("last_taxable_output_value_silver", 0)))
            due = max(0, int(round(taxable * tax_rate * admin_realization)))
            cash = max(0, int(region.get("cash_silver", 0)))
            transfer = min(due, cash)
            region["cash_silver"] = cash - transfer
            assessed += due; paid += transfer
            detail.append({"location_ref": str(ref), "taxable_output_value_silver": taxable, "due_silver": due, "paid_silver": transfer})
        funds_key, funds = self._funds_value(treasury)
        treasury[funds_key] = max(0, funds) + paid
        treasury.setdefault("runtime", {})["last_monthly_close_at"] = at
        self._sync_local_economy_aggregate(economy)
        self._write_private_economy(economy_path, economy)
        polity.setdefault("civil_finance", {})["last_close"] = at
        polity["civil_finance"].update({
            "universal_tax_rate": round(tax_rate, 6),
            "administration_realization": round(admin_realization, 6),
            "last_tax_assessed_silver": assessed,
            "last_tax_paid_silver": paid,
            "last_tax_arrears_silver": max(0, assessed - paid),
            "regional_tax_close": detail,
            "food_settled_by_private_production": True,
        })
        for force_ref in force_refs:
            try:
                force_path = self.owner_path(force_ref)
                force = copy.deepcopy(self.read(force_path))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if int(force.get("headcount", 0)) > int(population.get("strata", {}).get("active_military", 0)):
                raise ValueError("minor polity force exceeds conserved active-military population")
            self._fc_train(force, "regular_army", float(months), f"minor_polity:{polity_ref}:{at}")
            validate_cohort_ledger(force)
            self.put(force_path, force)
        self.put(treasury_path, treasury)
        self.put(polity_path, polity)

    def _autonomy_polity(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Monthly state-like close for a House-founded sovereign polity.

        The polity remains its own exact authority rather than masquerading as one of
        the seven core state files.  It settles territorial finance/recruitment on
        a monthly clock and can create exact defensive operations from saved threats.
        """
        polity_ref = str(host.get("owner_ref", ""))
        polity_path = self.owner_path(polity_ref)
        polity = copy.deepcopy(self.read(polity_path))
        if str(polity.get("status", "")) == "dissolved": return
        house_ref = str(polity.get("sovereign_house_ref", ""))
        administration_mode = str(polity.get("administration_mode", "house_founded" if house_ref else "minor_polity"))
        occurrences = max(1, int(occurrences))
        if administration_mode == "house_founded":
            if not house_ref:
                raise ValueError("House-founded sovereign polity lost its House authority")
            self._settle_house_polity(house_ref, occurrences, at, months=occurrences)
        elif administration_mode == "minor_polity":
            self._settle_minor_polity(polity_ref, occurrences, at)
        else:
            raise ValueError("unsupported sovereign polity administration mode")
        polity = copy.deepcopy(self.read(polity_path))
        polity.setdefault("strategic_goals", ["secure controlled territory", "maintain treasury and armed force", "pursue lawful recognition and diplomacy"])
        polity.setdefault("mobilization_readiness", 45)
        polity.setdefault("internal_stability", 50)
        polity.setdefault("diplomacy", {})
        polity["last_review"] = at
        mobilization = self._polity_mobilization_effects(polity)
        readiness = int(polity.get("mobilization_readiness", 45)); target_readiness = int(mobilization["readiness_target"])
        step = min(12, max(1, int(occurrences) * 4)); polity["mobilization_readiness"] = readiness + max(-step, min(step, target_readiness - readiness))
        polity["mobilization_runtime"] = {"last_review": at, **mobilization, "effective_readiness": int(polity["mobilization_readiness"])}
        controlled_sites = {str(x) for x in polity.get("occupied_site_refs", []) if isinstance(x, str)}
        capital_markets = self._civil_rules().get("capital_markets", {})
        market_refs = sorted(
            str(row.get("market_ref"))
            for row in capital_markets.values()
            if isinstance(row, Mapping) and str(row.get("location_ref", "")) in controlled_sites and isinstance(row.get("market_ref"), str)
        ) if isinstance(capital_markets, Mapping) else []
        # Preserve founded exact markets that physically remain under this polity.
        owners = self.read("state/index/owner-index.json").get("owners", {})
        for ref in sorted(str(x) for x in owners if str(x).startswith("market_")):
            path = owners.get(ref); market = self.read_optional(path) if isinstance(path, str) else None
            if isinstance(market, Mapping) and str(market.get("location_ref", "")) in controlled_sites and ref not in market_refs:
                market_refs.append(ref)
        polity["market_access_refs"] = sorted(set(market_refs))
        for market_ref in polity["market_access_refs"]:
            if market_ref not in {str(row.get("market_ref")) for row in capital_markets.values() if isinstance(row, Mapping)}:
                self._restock_dynamic_market(market_ref, at)
        polity.setdefault("state_integration", {}).update({
            "mode": "dynamic_sovereign_polity",
            "monthly_autonomy": True,
            "territorial_taxation": True,
            "territorial_recruitment": True,
            "administrative_services": True,
            "state_institutions": bool(polity.get("institution_refs")),
            "threat_response_operations": True,
            "shared_interstate_theaters": True,
            "shared_treaty_registry": True,
            "world_arc_actor": True,
            "physical_market_access": True,
            "recognition_diplomacy": True,
        })

        threats = polity.get("known_threats", {}) if isinstance(polity.get("known_threats"), Mapping) else {}
        ranked = sorted(((int(v.get("severity", 0)), str(k), v) for k, v in threats.items() if isinstance(v, Mapping)), key=lambda row: (-row[0], row[1]))
        if ranked:
            severity, threat_ref, threat = ranked[0]
            location_ref = str(threat.get("location_ref", ""))
            formation_refs: list[tuple[int, int, str]] = []
            for force_ref in sorted(str(x) for x in polity.get("military_force_refs", []) if isinstance(x, str)):
                try: force = self.read(self.owner_path(force_ref))
                except (KeyError, ValueError, FileNotFoundError): continue
                allocated = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
                for formation_ref in sorted(str(x) for x in allocated):
                    try: _fp, formation = self._load_formation(formation_ref)
                    except ValueError: continue
                    if int(formation.get("personnel", 0)) <= 0: continue
                    if str(formation.get("commander_ref", "")) == self.PLAYER_ACTOR or str(formation.get("command_authority", "")) == self.PLAYER_ACTOR: continue
                    origin = str(formation.get("location_ref", "")); travel = 0
                    if location_ref and origin and origin != location_ref:
                        try: travel = self._route_travel_hours(origin, location_ref)
                        except ValueError: continue
                    score = int(formation.get("readiness", 0)) + int(formation.get("cohesion", 0)) + int(formation.get("morale", 0))
                    formation_refs.append((travel, -score, formation_ref))
            if formation_refs and severity >= int(mobilization["threat_threshold"]):
                index = copy.deepcopy(self.read("state/operations/index.json"))
                already = None
                for op_ref, op_path in index.get("operations", {}).items():
                    if not isinstance(op_path, str): continue
                    op = self.read_optional(op_path)
                    if isinstance(op, Mapping) and str(op.get("administrative_authority", "")) == polity_ref and threat_ref in [str(x) for x in op.get("objective_refs", [])]:
                        already = str(op_ref); break
                if already is None:
                    active_ops = 0
                    for _op_ref, op_path in index.get("operations", {}).items():
                        if not isinstance(op_path, str): continue
                        op = self.read_optional(op_path)
                        if isinstance(op, Mapping) and str(op.get("administrative_authority", "")) == polity_ref and str(op.get("status", "")) in {"planned", "mobilizing", "active", "engaged"}: active_ops += 1
                    if active_ops >= int(mobilization["operation_capacity"]):
                        polity.setdefault("autonomous_actions", []).append({"at": at, "kind": "threat_response_deferred", "threat_ref": threat_ref, "reason": "mobilization policy operation capacity committed"}); polity["autonomous_actions"] = polity["autonomous_actions"][-24:]
                    else:
                        formation_ref = sorted(formation_refs)[0][2]; formation_path, formation = self._load_formation(formation_ref); formation = copy.deepcopy(formation)
                        formation["mobilized"] = True
                        if str(formation.get("status", "")) in {"forming", "ready", "garrisoned"}: formation["status"] = "mobilized"
                        self.put(formation_path, formation)
                        op_ref = "operation_" + polity_ref.removeprefix("polity_") + "_response_" + hashlib.sha256(f"{threat_ref}|{location_ref}".encode()).hexdigest()[:14]
                        op_path = f"state/operations/{op_ref}.json"
                        op = {"schema": "sword-operation", "owner_id": op_ref, "operation_ref": op_ref, "status": "active", "kind": "polity_threat_response", "objective": f"respond to {threat_ref}", "objective_refs": [threat_ref], "location_ref": location_ref or str(formation.get("location_ref", "")), "formation_refs": [formation_ref], "administrative_authorities": [polity_ref], "administrative_authority": polity_ref, "created_at": at, "authority_basis": {"polity_ref": polity_ref, "force_ref": str(formation.get("owner_force_ref", "")), "mobilization_policy": mobilization["value"], "rule": "recognized/proto polity may direct only formations from its saved military_force_refs; travel to a remote threat is lawful when an exact route exists"}, "victory_criteria": ["saved threat is contained or removed"], "termination_criteria": ["force withdraws, is defeated, or threat ends"]}
                        self.put(op_path, op); index.setdefault("operations", {})[op_ref] = op_path; self.put("state/operations/index.json", index); self._register_owner(op_ref, op_path)
                        polity.setdefault("autonomous_actions", []).append({"at": at, "kind": "threat_response_operation_created", "operation_ref": op_ref, "threat_ref": threat_ref})
                        polity["autonomous_actions"] = polity["autonomous_actions"][-24:]
        self._autonomy_polity_court(polity_ref, polity, at)
        self.put(polity_path, polity)
        self._generate_npc_war_intent(polity_ref, at)
        self._settle_diplomatic_routes(polity_ref, copy.deepcopy(self.read(polity_path)), at)
        self._settle_treaty_obligations(polity_ref, at, occurrences)
        self._generate_npc_diplomatic_initiative(polity_ref, at)

    def _counterinsurgency_response_operation(self, controller_ref: str, location_ref: str) -> tuple[str, str, dict[str, Any]] | None:
        threat_ref = f"occupation_revolt:{location_ref}"
        index = self.read("state/operations/index.json")
        candidates: list[tuple[str, str, dict[str, Any]]] = []
        for op_ref, op_path in index.get("operations", {}).items():
            if not isinstance(op_path, str):
                continue
            op = self.read_optional(op_path)
            if not isinstance(op, Mapping) or str(op.get("status", "")) not in {"planned", "mobilizing", "active", "engaged"}:
                continue
            authorities = {str(op.get("administrative_authority", "")), str(op.get("assignment_authority_ref", "")), *[str(x) for x in op.get("administrative_authorities", [])]}
            authority_terms = op.get("authority_terms", {}) if isinstance(op.get("authority_terms"), Mapping) else {}
            authorities.add(str(authority_terms.get("assignment_authority_ref", "")))
            if controller_ref not in authorities or threat_ref not in {str(x) for x in op.get("objective_refs", [])}:
                continue
            candidates.append((str(op_ref), op_path, copy.deepcopy(op)))
        return sorted(candidates, key=lambda x: x[0])[0] if candidates else None

    def _autonomy_counterinsurgency(self, rebel_ref: str, rebel_formation_ref: str, rebel_operation_ref: str, location_ref: str, at: str) -> dict[str, Any]:
        territory = copy.deepcopy(self.read("state/territory/control.json"))
        site = territory.get("sites", {}).get(location_ref, {}) if isinstance(territory, Mapping) else {}
        controller_ref = str(site.get("controller", "")) if isinstance(site, Mapping) else ""
        if not (controller_ref.startswith("state_") or controller_ref.startswith("polity_")):
            return {"status": "no_sovereign_controller"}
        response = self._counterinsurgency_response_operation(controller_ref, location_ref)
        if response is None:
            return {"status": "awaiting_government_response", "controller_ref": controller_ref}
        response_ref, response_path, response_op = response
        government_refs = [str(x) for x in response_op.get("formation_refs", []) if isinstance(x, str)]
        government_ref = None
        for candidate in government_refs:
            try:
                _gp, government = self._load_formation(candidate)
            except ValueError:
                continue
            if int(government.get("personnel", 0)) <= 0:
                continue
            if str(government.get("commander_ref", "")) == self.PLAYER_ACTOR or str(government.get("command_authority", "")) == self.PLAYER_ACTOR:
                response_op["player_decision_required"] = {"at": at, "formation_ref": candidate, "location_ref": location_ref, "reason": "player-commanded force reached an autonomous insurgency decision boundary"}
                self.put(response_path, response_op)
                return {"status": "player_decision_required", "operation_ref": response_ref, "formation_ref": candidate}
            government_ref = candidate
            break
        if government_ref is None:
            return {"status": "no_autonomous_government_formation", "operation_ref": response_ref}
        _gp, government = self._load_formation(government_ref)
        if str(government.get("location_ref", "")) != location_ref:
            march = self._autonomy_move_formation_step(government_ref, location_ref, at)
            response_op["last_march"] = march; response_op["last_autonomous_action"] = {"at": at, "kind": "counterinsurgency_march", **march}
            self.put(response_path, response_op)
            return {"status": "government_marching", "operation_ref": response_ref, "formation_ref": government_ref, "march": march}
        try:
            _rp, rebel = self._load_formation(rebel_formation_ref)
        except ValueError:
            return {"status": "rebel_force_missing"}
        if str(rebel.get("location_ref", "")) != location_ref or int(rebel.get("personnel", 0)) <= 0:
            return {"status": "no_rebel_contact"}
        government_power = float(self._autonomy_formation_power(government_ref, defender=False, opposing_ref=rebel_formation_ref))
        rebel_power = float(self._autonomy_formation_power(rebel_formation_ref, defender=True, opposing_ref=government_ref))
        seed = int(hashlib.sha256(f"counterinsurgency|{location_ref}|{at}|{government_ref}|{rebel_formation_ref}".encode()).hexdigest()[:8], 16)
        variance = 0.95 + (seed % 1001) / 10000.0
        government_wins = government_power * variance >= rebel_power if government_power > 0 and rebel_power > 0 else government_power > rebel_power
        winner_ref = government_ref if government_wins else rebel_formation_ref; loser_ref = rebel_formation_ref if government_wins else government_ref
        winner_power = government_power if government_wins else rebel_power; loser_power = rebel_power if government_wins else government_power
        ratio = max(0.25, min(4.0, winner_power / max(1.0, loser_power)))
        loser_rate = min(0.45, 0.14 + 0.05 * max(0.0, ratio - 1.0)); winner_rate = min(0.22, 0.05 + 0.025 * max(0.0, 1.0 / ratio))
        _wp, winner = self._load_formation(winner_ref); _lp, loser = self._load_formation(loser_ref)
        winner_loss = min(int(winner.get("personnel", 0)), max(1, int(round(int(winner.get("personnel", 0)) * winner_rate)))) if int(winner.get("personnel", 0)) else 0
        loser_loss = min(int(loser.get("personnel", 0)), max(1, int(round(int(loser.get("personnel", 0)) * loser_rate)))) if int(loser.get("personnel", 0)) else 0
        gov_side = controller_ref
        rebel_side = rebel_ref
        seed_material = f"counterinsurgency|{location_ref}|{at}"
        wloss = self._autonomy_apply_battle_losses(winner_ref, winner_loss, at, losing_side=False, opponent_state=(rebel_side if government_wins else gov_side), seed_material=seed_material + "|winner")
        lloss = self._autonomy_apply_battle_losses(loser_ref, loser_loss, at, losing_side=True, opponent_state=(gov_side if government_wins else rebel_side), seed_material=seed_material + "|loser")
        hist = copy.deepcopy(self.read("state/history/events/index.json")); event_id = "counterinsurgency_" + hashlib.sha256(seed_material.encode()).hexdigest()[:16]
        hist.setdefault("events", []).append({"event_id": event_id, "kind": "counterinsurgency_battle", "at": at, "location_ref": location_ref, "controller_ref": controller_ref, "government_operation_ref": response_ref, "rebel_operation_ref": rebel_operation_ref, "government_formation_ref": government_ref, "rebel_formation_ref": rebel_formation_ref, "winner_ref": winner_ref, "losses": {winner_ref: wloss, loser_ref: lloss}}); write_history_index(self, hist)
        response_op["status"] = "engaged"; response_op["last_battle_event"] = event_id; response_op["last_autonomous_action"] = {"at": at, "kind": "counterinsurgency_battle", "event_ref": event_id, "winner_ref": winner_ref}
        self.put(response_path, response_op)
        _rp2, rebel_after = self._load_formation(rebel_formation_ref)
        revolt = site.get("governance", {}).get("revolt", {}) if isinstance(site.get("governance"), Mapping) else {}
        initial = max(1, int(revolt.get("initial_personnel", int(rebel_after.get("personnel", 0)) or 1))) if isinstance(revolt, Mapping) else max(1, int(rebel_after.get("personnel", 0)))
        floor = max(50, int(math.floor(initial * 0.10)))
        if government_wins and int(rebel_after.get("personnel", 0)) <= floor:
            refs = self._occupation_revolt_refs(location_ref)
            native_state = str((self.read(self.owner_path(rebel_ref)).get("origin", {}) if rebel_ref else {}).get("population_ref", "")).removeprefix("population_")
            survivors = self._contain_occupation_rebel_force(refs=refs, native_state=native_state, at=at) if native_state else 0
            governance = site.get("governance") if isinstance(site.get("governance"), dict) else None
            if governance is not None:
                governance["status"] = "military_occupation"; governance["resistance"] = min(int(governance.get("resistance", 0)), 55); governance.setdefault("revolt", {})["active"] = False; governance["revolt"]["contained_at"] = at; governance["revolt"]["survivors_returned"] = survivors
                if controller_ref.startswith("state_"):
                    sp = f"state/states/{controller_ref.removeprefix('state_')}.json"; sd = copy.deepcopy(self.read(sp)); sd.setdefault("known_threats", {}).pop(f"occupation_revolt:{location_ref}", None); self.put(sp, sd)
                else:
                    pp = self.owner_path(controller_ref); pd = copy.deepcopy(self.read(pp)); pd.setdefault("known_threats", {}).pop(f"occupation_revolt:{location_ref}", None); self.put(pp, pd)
            response_op = copy.deepcopy(self.read(response_path)); response_op["status"] = "completed"; response_op["completed_at"] = at; response_op["completion_evidence_ref"] = event_id; self.put(response_path, response_op); self.put("state/territory/control.json", territory)
            return {"status": "revolt_contained", "battle_event": event_id, "government_formation_ref": government_ref, "rebel_formation_ref": rebel_formation_ref, "survivors_returned": survivors}
        return {"status": "battle_settled", "battle_event": event_id, "winner_ref": winner_ref, "government_formation_ref": government_ref, "rebel_formation_ref": rebel_formation_ref}

    def _autonomy_rebel_faction(self, ref: str, path: str, doc: dict[str, Any], occurrences: int, at: str) -> None:
        """Run a materialized revolt as an irregular actor with conserved bodies/supply."""
        if str(doc.get("status", "")) != "active_revolt": return
        force_ref = str(doc.get("force_ref", "")); operation_ref = str(doc.get("operation_ref", "")); formation_refs = [str(x) for x in doc.get("formation_refs", []) if isinstance(x, str)]
        if not force_ref or not operation_ref or not formation_refs: return
        formation_ref = formation_refs[0]
        try:
            force_path = self.owner_path(force_ref); formation_path = self.owner_path(formation_ref); operation_path = self.owner_path(operation_ref)
            force = copy.deepcopy(self.read(force_path)); formation = copy.deepcopy(self.read(formation_path)); operation = copy.deepcopy(self.read(operation_path))
        except (KeyError, ValueError, FileNotFoundError): return
        if int(force.get("headcount", 0)) <= 0 or int(formation.get("personnel", 0)) <= 0: return
        origin = doc.get("origin", {}) if isinstance(doc.get("origin"), Mapping) else {}; population_ref = str(origin.get("population_ref", "")); native_state = population_ref.removeprefix("population_")
        location_ref = str(origin.get("location_ref", formation.get("location_ref", "")))
        support = self._support_occupation_rebel_force(refs={"force_ref": force_ref, "formation_ref": formation_ref, "faction_ref": ref}, native_state=native_state, at=at) if native_state else {"food_kg": 0, "silver": 0}
        # Recruit a bounded local increment from the same conserved population.
        recruited = 0
        if native_state in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
            pop_path = f"state/population/{native_state}.json"; pop = copy.deepcopy(self.read(pop_path)); _lp, pop, local_row = self._local_population_row(native_state, location_ref, pop)
            agricultural = min(max(0, int(pop.get("strata", {}).get("agricultural", 0))), max(0, int(local_row.get("agricultural_available", 0))), max(0, int(local_row.get("civilian_population", 0))))
            local_support = max(0, min(100, int(doc.get("resources", {}).get("local_support", 0))))
            territory = self.read("state/territory/control.json")
            site = territory.get("sites", {}).get(location_ref, {}) if isinstance(territory, Mapping) else {}
            governance = site.get("governance", {}) if isinstance(site, Mapping) and isinstance(site.get("governance"), Mapping) else {}
            resistance = max(0, min(100, int(governance.get("resistance", local_support))))
            agents = max(1, int(doc.get("resources", {}).get("agents", 1)))
            weekly_rate = 0.0005 + 0.006 * (local_support / 100.0) * (resistance / 100.0)
            population_capacity = max(0, int(math.floor(agricultural * weekly_rate * max(1, occurrences))))
            organizational_capacity = max(1, int(round(agents * (4.0 + local_support / 8.0) * max(1, occurrences))))
            supply_food = max(0, int(force.get("logistics", {}).get("food_kg", 0))) if isinstance(force.get("logistics"), Mapping) else 0
            faction_silver = max(0, int(doc.get("resources", {}).get("silver", 0)))
            supply_capacity = max(1, supply_food // 30 + faction_silver // 5)
            recruited = min(agricultural, population_capacity, organizational_capacity + supply_capacity)
            if recruited > 0:
                pop["strata"]["agricultural"] = int(pop["strata"].get("agricultural", 0)) - recruited; pop["strata"]["rebel_military"] = int(pop["strata"].get("rebel_military", 0)) + recruited
                moved_local = self._consume_local_recruitment(pop, native_state, location_ref, recruited, service_key="rebel_military", source_stratum="agricultural", service_owner_ref=force_ref)
                if moved_local != recruited:
                    raise ValueError("rebel autonomous recruitment exceeded the locality's conserved civilian manpower")
                ensure_cohort_ledger(force, at=at)
                add_recruits(force, "line_infantry", recruited, location_ref=location_ref)
                record_recruitment_cohort(force, role="line_infantry", count=recruited, location_ref=location_ref, source_population_ref=population_ref, source_stratum="agricultural", recruited_at=at, profile_registry=self.read("game/data/mil/recruitment-cohort-profiles.json"), provenance_ref=f"{operation_ref}:autonomous_recruit:{at}")
                self._take_force_personnel(force, "line_infantry", recruited, location_ref)
                allocation = force.setdefault("allocated_to_formations", {}).setdefault(formation_ref, {"role": "line_infantry", "personnel": 0})
                allocation["personnel"] = int(allocation.get("personnel", 0)) + recruited
                slices = take_reserve_slices(force, role="line_infantry", count=recruited, location_ref=location_ref, formation_ref=formation_ref)
                formation["personnel"] = int(formation.get("personnel", 0)) + recruited; formation.setdefault("composition", {})["line_infantry"] = int(formation.get("composition", {}).get("line_infantry", 0)) + recruited; formation.setdefault("cohort_composition", []).extend(slices)
                validate_cohort_ledger(force); self.put(pop_path, pop)
        # Choose one adjacent exact route to interdict; the market transport subsystem consumes this.
        routes = self.read("game/data/world/routes.json").get("routes", []); adjacent = []
        for row in routes if isinstance(routes, list) else []:
            if not isinstance(row, Mapping): continue
            a = str(row.get("a", row.get("from", ""))); b = str(row.get("b", row.get("to", "")))
            if location_ref in {a, b} and str(row.get("ref", "")): adjacent.append(str(row.get("ref")))
        route_ref = sorted(adjacent)[int(hashlib.sha256(f"{ref}|{at}".encode()).hexdigest()[:8], 16) % len(adjacent)] if adjacent else None
        if route_ref:
            operation["route_refs"] = [route_ref]; operation["objective"] = f"raid and interdict {route_ref} while contesting occupation at {location_ref}"; operation["kind"] = "local_insurgency_raid"
        operation["last_autonomous_action"] = {"at": at, "kind": "raid_and_recruit" if recruited else "raid", "route_ref": route_ref, "recruited": recruited, "support": support}
        doc["last_action"] = {"at": at, "action": "irregular_campaign", "operation_ref": operation_ref, "route_ref": route_ref, "recruited": recruited, "support": support}
        doc["action_count"] = int(doc.get("action_count", 0) or 0) + 1
        doc.pop("commitments", None)
        self.put(force_path, force); self.put(formation_path, formation); self.put(operation_path, operation); self.put(path, doc)
        counter = self._autonomy_counterinsurgency(ref, formation_ref, operation_ref, location_ref, at)
        if counter.get("status") not in {"awaiting_government_response", "no_sovereign_controller"}:
            doc = copy.deepcopy(self.read(path)); doc.setdefault("counterinsurgency_history", []).append({"at": at, **counter}); doc["counterinsurgency_history"] = doc["counterinsurgency_history"][-24:]; self.put(path, doc)

    def _autonomy_faction(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        ref = str(host["owner_ref"])
        path = self.owner_path(ref)
        doc = copy.deepcopy(self.read(path))
        if ref.startswith("faction_occupation_revolt_"):
            self._autonomy_rebel_faction(ref, path, doc, occurrences, at)
            return
        profiles = self.read(_FACTION_PROFILES).get("profiles", {})
        profile = profiles.get(ref, {}) if isinstance(profiles, Mapping) else {}
        if isinstance(profile, Mapping):
            if not doc.get("goals"):
                doc["goals"] = list(profile.get("goals", []))
            resources = doc.setdefault("resources", {})
            for key, value in profile.get("resource_seed", {}).items():
                resources.setdefault(str(key), value)
            relationships = doc.setdefault("relationships", {})
            for key, value in profile.get("relationship_seed", {}).items():
                relationships.setdefault(str(key), copy.deepcopy(value))
        doc["last_review"] = at
        resources = doc.setdefault("resources", {})
        if isinstance(profile, Mapping):
            regen = profile.get("resource_regeneration", {}) if isinstance(profile.get("resource_regeneration"), Mapping) else {}
            caps = profile.get("resource_caps", {}) if isinstance(profile.get("resource_caps"), Mapping) else {}
            for key, amount in regen.items():
                before = _fixed(resources.get(str(key), 0))
                cap = _fixed(caps.get(str(key), before + _fixed(amount) * max(1, occurrences)), before + _fixed(amount) * max(1, occurrences))
                value = min(cap, before + max(0.0, _fixed(amount)) * max(1, occurrences))
                resources[str(key)] = int(value) if float(value).is_integer() else value
        pressure_step = max(1, int(profile.get("pressure_per_review", 5))) if isinstance(profile, Mapping) else 5
        pressure = _clamp(int(doc.get("pressure", 0)) + min(40, occurrences * pressure_step))
        doc["pressure"] = pressure
        action = str(profile.get("action", "network_review")) if isinstance(profile, Mapping) else "network_review"
        # Factions keep one current action result plus a monotonic count. Exact
        # semantic history belongs in the central event/history owners, not here.
        resources = doc.setdefault("resources", {})
        cost = profile.get("cost", {}) if isinstance(profile, Mapping) and isinstance(profile.get("cost"), Mapping) else {}
        knowledge_basis = self._faction_knowledge_basis(ref, doc, profile, at) if isinstance(profile, Mapping) else []
        has_resources = all(_fixed(resources.get(k, 0)) >= _fixed(v) for k, v in cost.items())
        knowledge_ok = (not bool(profile.get("knowledge_required"))) or bool(knowledge_basis)
        can_act = pressure >= 30 and has_resources and knowledge_ok
        if pressure >= 30 and not knowledge_ok:
            doc["last_blocked_reason"] = "exact actionable knowledge has not reached this faction"
        elif pressure >= 30 and not has_resources:
            doc["last_blocked_reason"] = "saved faction resources are insufficient for the registered action"
        if can_act:
            doc.pop("last_blocked_reason", None)
            spent: dict[str, Any] = {}
            for key, amount in cost.items():
                before = _fixed(resources.get(key, 0))
                after = max(0, before - _fixed(amount))
                resources[str(key)] = int(after) if float(after).is_integer() else after
                spent[str(key)] = amount
            state = str(profile.get("state", "")) if isinstance(profile, Mapping) else ""
            effect: dict[str, Any] = {}
            if state in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
                sp = f"state/states/{state}.json"
                sd = copy.deepcopy(self.read(sp))
                if action == "administrative_reform":
                    sd["administrative_capacity"] = _clamp(int(sd.get("administrative_capacity", 0)) + 1)
                    effect = {"administrative_capacity": sd["administrative_capacity"]}
                elif action == "court_resistance":
                    sd["internal_stability"] = _clamp(int(sd.get("internal_stability", 0)) - 1)
                    effect = {"internal_stability": sd["internal_stability"]}
                elif action in {"frontier_readiness", "engineering_priority"}:
                    sd["mobilization_readiness"] = _clamp(int(sd.get("mobilization_readiness", 0)) + 1)
                    sd.setdefault("institutional_priorities", {})[ref] = {"at": at, "kind": action}
                    effect = {"mobilization_readiness": sd["mobilization_readiness"], "priority_recorded": True}
                elif action == "patronage_lobbying":
                    sd.setdefault("political_pressure", {})[ref] = {"at": at, "influence": int(_fixed(resources.get("influence", 0))), "kind": action}
                    patronage = max(0, int(_fixed(spent.get("funds_silver", 0))))
                    if patronage:
                        ep, eco = self._private_economy(state)
                        eco["cash_silver"] = int(eco.get("cash_silver", 0)) + patronage
                        self._write_private_economy(ep, eco)
                    effect = {"political_pressure_recorded": True, "patronage_disbursed_silver": patronage}
                self.put(sp, sd)
            if action == "merchant_liquidity":
                states = [state] if state else [str(x) for x in profile.get("states", [])]
                valid = [x for x in states if x in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}]
                if valid:
                    target = min(valid, key=lambda key: int(self.read(f"state/economy/private/{key}.json").get("cash_silver", 0)))
                    ep, eco = self._private_economy(target)
                    transfer = max(0, int(_fixed(spent.get("funds_silver", 0))))
                    eco["cash_silver"] = int(eco.get("cash_silver", 0)) + transfer
                    self._write_private_economy(ep, eco)
                    effect = {"private_market_liquidity_silver": transfer, "state": target}
            elif action == "broker_contracts":
                effect = self._broker_one_mercenary_offer(at)
            elif action == "transport_capacity":
                resources["throughput_reviews"] = int(resources.get("throughput_reviews", 0)) + max(1, occurrences)
                effect = self._transport_network_action(profile, occurrences, at)
            elif action == "training_network":
                cap = max(0, int(_fixed(resources.get("instruction_capacity", 0))))
                resources["available_instruction_slots"] = min(cap, int(resources.get("available_instruction_slots", 0)) + 2 * max(1, occurrences))
                effect = {"available_instruction_slots": resources["available_instruction_slots"]}
            elif action == "confederation_muster":
                cap = max(0, int(_fixed(resources.get("warband_capacity", 0))))
                resources["muster_readiness"] = min(cap, int(resources.get("muster_readiness", 0)) + 3 * max(1, occurrences))
                effect = {"muster_readiness": resources["muster_readiness"]}
            elif action == "household_coordination":
                house_path = self.owner_path("house_tang")
                house = copy.deepcopy(self.read(house_path))
                runtime = house.setdefault("coordination_runtime", {})
                runtime["reviews"] = int(runtime.get("reviews", 0)) + max(1, occurrences)
                runtime["last_review"] = at
                self.put(house_path, house)
                effect = {"household_coordination_reviews": runtime["reviews"]}
            if knowledge_basis:
                used = [str(x) for x in knowledge_basis[-3:]]
                effect["knowledge_refs_used"] = used
                pending = doc.get("pending_information_refs", [])
                if isinstance(pending, list):
                    doc["pending_information_refs"] = [x for x in pending if x not in set(used)]
            relation_changes = []
            local_relationships = doc.setdefault("relationships", {})
            for target, delta, relation_kind in [
                *[(x, 2, "cooperative_faction_action") for x in (profile.get("partners", []) if isinstance(profile, Mapping) else [])],
                *[(x, -1, "competitive_faction_action") for x in (profile.get("rivals", []) if isinstance(profile, Mapping) else [])],
            ]:
                if not isinstance(target, str) or not target.startswith("faction_"):
                    continue
                rel = local_relationships.setdefault(target, {"kind": relation_kind, "strength": 50})
                before_sentiment = int(rel.get("sentiment", 0))
                rel["sentiment"] = max(-100, min(100, before_sentiment + delta))
                rel["interaction_count"] = int(rel.get("interaction_count", 0)) + 1
                rel["last_interaction_at"] = at
                rel["last_interaction_kind"] = relation_kind
                relation_changes.append({"source_ref": ref, "target_ref": target, "sentiment_before": before_sentiment, "sentiment_after": rel["sentiment"], "kind": relation_kind})
            if relation_changes:
                effect["relationship_changes"] = relation_changes
            doc["last_action"] = {
                "at": at,
                "action": action,
                "goal": (doc.get("goals") or ["preserve organization"])[0],
                "spent": dict(spent),
                "effect": effect,
                "knowledge_refs_used": [str(x) for x in knowledge_basis[-3:]],
            }
            doc["action_count"] = int(doc.get("action_count", 0) or 0) + 1
            doc.pop("commitments", None)
            doc["pressure"] = max(0, pressure - 25)
        self.put(path, doc)

    def _autonomy_mercenary(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_mercenary(host, occurrences, at)
        ref = str(host["owner_ref"]); path = self.owner_path(ref); doc = copy.deepcopy(self.read(path))
        contracts = doc.setdefault("contracts", [])
        # Fund accepted contracts from the exact employer treasury.
        for contract in contracts:
            if str(contract.get("status")) not in {"accepted_unpaid", "renewal_accepted"}:
                continue
            employer = str(contract.get("employer_ref", ""))
            amount = max(0, int(contract.get("amount_silver", 0)))
            if employer.startswith("state_"):
                state = employer.replace("state_", "")
                sp = f"state/states/{state}.json"; sd = copy.deepcopy(self.read(sp))
                if amount and int(sd.get("treasury_silver", 0)) >= amount:
                    sd["treasury_silver"] -= amount
                    doc["treasury_silver"] = int(doc.get("treasury_silver", 0)) + amount
                    contract["status"] = "active"; contract["paid_at"] = at; contract["active_at"] = at
                    contract["payment_source_ref"] = employer
                    doc["status"] = "contracted"
                    self.put(sp, sd)
                continue
            if employer in {"house_tang", "institution_house_tang"}:
                tp = "state/treasury/treasury-house-tang.json"
                treasury = copy.deepcopy(self.read(tp))
                protected = int(treasury.get("stable_monthly_flows", {}).get("expense_silver", 0)) * 12 if isinstance(treasury.get("stable_monthly_flows"), Mapping) else 0
                if amount and int(treasury.get("silver", 0)) - amount >= protected:
                    treasury["silver"] = int(treasury.get("silver", 0)) - amount
                    doc["treasury_silver"] = int(doc.get("treasury_silver", 0)) + amount
                    contract["status"] = "active"; contract["paid_at"] = at; contract["active_at"] = at
                    contract["payment_source_ref"] = "treasury_house_tang"
                    doc["status"] = "contracted"
                    self.put(tp, treasury)
                continue
        if doc.get("status") == "available" and not any(str(c.get("status")) in {"offered", "accepted_unpaid", "active", "renewal_offered", "renewal_accepted"} for c in contracts):
            candidates = []
            for state in ("qin", "zhao", "chu", "wei", "han", "yan", "qi"):
                sd = self.read(f"state/states/{state}.json")
                threats = sd.get("known_threats", {}) if isinstance(sd, Mapping) else {}
                severity = max((int(v.get("severity", 0)) if isinstance(v, Mapping) else int(_fixed(v, 0)) for v in threats.values()), default=0)
                if severity >= 35:
                    candidates.append((severity, int(sd.get("treasury_silver", 0)), state))
            if candidates:
                _, cash, state = sorted(candidates, reverse=True)[0]
                headcount = max(1, int(doc.get("headcount", doc.get("count", doc.get("personnel", doc.get("strength", 1))))))
                econ = self.read("game/data/mechanics/economy.json"); monthly = _fixed(econ.get("wages", {}).get("professional_soldier_monthly_silver", 7), 7)
                factor = _fixed(self.read("game/data/mechanics/career.json").get("service_models", {}).get("army_model_mercenary", {}).get("cash_pay_factor_vs_common_role_baseline", 1.35), 1.35)
                fair = int(math.ceil(headcount * monthly * factor * 3))
                amount = int(math.ceil(fair * 1.05))
                if cash >= amount:
                    contract_ref = "merc_auto_" + hashlib.sha256(f"{ref}|{state}|{at}".encode()).hexdigest()[:14]
                    contracts.append({"contract_ref": contract_ref, "employer_ref": f"state_{state}", "status": "offered", "amount_silver": amount, "term_days": 90, "offered_at": at, "basis": "saved state threat, employer solvency and mercenary fair-pay floor"})
                    doc["status"] = "considering_offer"
        doc["contracts"] = contracts[-32:]
        self.put(path, doc)

    def _interstate_war_decision(
        self, attacker: str, defender: str, target_location_ref: str, record: Mapping[str, Any], cfg: Mapping[str, Any], at: str
    ) -> dict[str, Any]:
        """Authorize war from exact interests, never from elapsed frontier pressure.

        A connected theater is only infrastructure.  Hostilities require a saved war
        intent, or a severe exact threat plus a strong saved claim/hostile relation.
        Active ceasefires/non-aggression terms fail closed.  This prevents every
        neighboring sovereign pair from drifting into inevitable war simply because
        enough quarters passed.
        """
        attacker_ref = attacker if attacker.startswith("polity_") else f"state_{attacker}"
        defender_ref = defender if defender.startswith("polity_") else f"state_{defender}"
        try:
            attacker_path = self.owner_path(attacker_ref) if attacker.startswith("polity_") else f"state/states/{attacker}.json"
            attacker_doc = copy.deepcopy(self.read(attacker_path))
        except (KeyError, ValueError, FileNotFoundError):
            return {"authorized": False, "reason": "attacker authority unavailable", "tension_score": 0, "basis": {"attacker_ref": attacker_ref}}

        now = CampaignTime.parse(at)
        treaties = self.read("state/politics/treaties.json")
        active_barrier_refs: list[str] = []
        for treaty_ref, treaty in treaties.get("records", {}).items() if isinstance(treaties, Mapping) else []:
            if not isinstance(treaty, Mapping) or str(treaty.get("status", "")) != "active":
                continue
            parties = {str(x) for x in treaty.get("parties", []) if isinstance(x, str)}
            if {attacker_ref, defender_ref} - parties:
                continue
            terms = treaty.get("terms", {}) if isinstance(treaty.get("terms"), Mapping) else {}
            until = terms.get("nonaggression_until", treaty.get("truce_until"))
            if isinstance(until, str):
                try:
                    if CampaignTime.parse(until) > now:
                        active_barrier_refs.append(str(treaty_ref))
                except ValueError:
                    pass
            if bool(terms.get("ceasefire")) and isinstance(treaty.get("truce_until"), str):
                try:
                    if CampaignTime.parse(str(treaty.get("truce_until"))) > now:
                        active_barrier_refs.append(str(treaty_ref))
                except ValueError:
                    pass
            if str(treaty.get("kind", "")) in {"alliance", "client_state"} and {attacker_ref, defender_ref} <= parties:
                active_barrier_refs.append(str(treaty_ref))
        if active_barrier_refs:
            return {"authorized": False, "reason": "binding ceasefire or non-aggression term remains active", "tension_score": 10, "basis": {"treaty_refs": sorted(set(active_barrier_refs))}}

        relation = attacker_doc.get("diplomacy", {}).get(defender_ref, {}) if isinstance(attacker_doc.get("diplomacy"), Mapping) else {}
        relation_tension = max(0, min(100, int(_fixed(relation.get("tension", 0), 0)))) if isinstance(relation, Mapping) else 0
        relation_status = str(relation.get("status", "")) if isinstance(relation, Mapping) else ""
        known_threats = attacker_doc.get("known_threats", {}) if isinstance(attacker_doc.get("known_threats"), Mapping) else {}
        threat_score = 0
        threat_refs: list[str] = []
        for threat_ref, threat in known_threats.items():
            if not isinstance(threat, Mapping):
                continue
            source = str(threat.get("source_ref", threat.get("actor_ref", threat.get("state_ref", ""))))
            location = str(threat.get("location_ref", ""))
            if source in {defender_ref, defender} or location == target_location_ref:
                severity = max(0, min(100, int(_fixed(threat.get("severity", 0), 0))))
                if severity > threat_score:
                    threat_score = severity
                threat_refs.append(str(threat_ref))

        territory = self.read("state/territory/control.json")
        site = territory.get("sites", {}).get(target_location_ref, {}) if isinstance(territory, Mapping) else {}
        claims = site.get("legal_claims", {}) if isinstance(site, Mapping) and isinstance(site.get("legal_claims"), Mapping) else {}
        claim = claims.get(attacker_ref, {}) if isinstance(claims, Mapping) else {}
        claim_strength = max(0, min(100, int(_fixed(claim.get("strength", 0), 0)))) if isinstance(claim, Mapping) else 0

        intents = attacker_doc.setdefault("war_intents", [])
        if not isinstance(intents, list):
            raise ValueError("sovereign war intent registry is invalid")
        exact_intent = None
        for row in intents:
            if not isinstance(row, dict) or str(row.get("status", "")) not in {"authorized", "ready"}:
                continue
            target_ref = str(row.get("target_ref", "")); location_ref = str(row.get("location_ref", ""))
            if target_ref not in {defender_ref, defender, ""}:
                continue
            if location_ref not in {target_location_ref, ""}:
                continue
            exact_intent = row
            break

        readiness = max(0, min(100, int(_fixed(attacker_doc.get("mobilization_readiness", 50), 50))))
        treasury = max(0, int(attacker_doc.get("treasury_silver", 0))) if not attacker.startswith("polity_") else 0
        if attacker.startswith("polity_"):
            treasury_ref = str(attacker_doc.get("treasury_ref", ""))
            try:
                treasury_doc = self.read(self.owner_path(treasury_ref)) if treasury_ref else {}
            except (KeyError, ValueError, FileNotFoundError):
                treasury_doc = {}
            treasury = max(0, int(treasury_doc.get("silver", treasury_doc.get("treasury_silver", 0)))) if isinstance(treasury_doc, Mapping) else 0

        structural_score = min(100, int(round(0.35 * relation_tension + 0.35 * threat_score + 0.30 * claim_strength)))
        explicit = isinstance(exact_intent, dict)
        emergent = relation_status in {"hostile", "war_preparation"} and threat_score >= 70 and claim_strength >= 60
        authorized = (explicit or emergent) and readiness >= 25 and treasury > 0
        if not authorized:
            return {
                "authorized": False,
                "reason": "no lawful willing war decision is ready",
                "tension_score": structural_score,
                "basis": {"explicit_war_intent": bool(explicit), "relation_status": relation_status, "relation_tension": relation_tension, "threat_score": threat_score, "claim_strength": claim_strength, "mobilization_readiness": readiness, "treasury_positive": treasury > 0, "threat_refs": sorted(set(threat_refs))[-8:]},
            }

        decision_ref = str(exact_intent.get("intent_ref", "")) if isinstance(exact_intent, dict) else "emergent_claim_and_threat"
        objective = str(exact_intent.get("objective", "")) if isinstance(exact_intent, dict) else "compel settlement of the saved territorial claim"
        if not objective:
            objective = "occupy and compel settlement"
        war_goal = {"kind": str(exact_intent.get("kind", "territorial_control")) if isinstance(exact_intent, dict) else "territorial_control", "location_ref": target_location_ref, "objective": objective}
        casus = {
            "kind": "authorized_war_intent" if explicit else "claim_and_verified_threat",
            "target_location_ref": target_location_ref,
            "attacker_ref": attacker_ref,
            "defender_ref": defender_ref,
            "intent_ref": decision_ref if explicit else None,
            "threat_refs": sorted(set(threat_refs))[-8:],
            "claim_strength": claim_strength,
        }
        if isinstance(exact_intent, dict):
            exact_intent["status"] = "activated"
            exact_intent["activated_at"] = at
            exact_intent["theater_ref"] = str(cfg.get("theater_ref", ""))
            self.put(attacker_path, attacker_doc)
        return {"authorized": True, "decision_ref": decision_ref, "tension_score": max(structural_score, 75), "war_goal": war_goal, "casus_belli": casus, "basis": {"explicit_war_intent": bool(explicit), "emergent_claim_and_threat": bool(emergent), "mobilization_readiness": readiness, "treasury_positive": treasury > 0}}

    def _settle_frontier_pressure(self, sovereign_ref: str, occurrences: int, at: str) -> list[dict[str, Any]]:
        """Settle bounded physical-border friction into saved diplomatic evidence.

        A frontier theater is not a war timer.  It can, however, produce real border
        incidents while both sides maintain forces and access across the same strategic
        connection.  Incidents are deterministic from campaign time/theater identity,
        are settled once per theater per review, and update both sovereigns symmetrically.
        Quiet reviews decay tension toward the theater's background friction floor.
        War still requires the normal sovereign intent and war-decision gates.
        """
        if occurrences <= 0:
            return []
        side = sovereign_ref.removeprefix("state_") if sovereign_ref.startswith("state_") else sovereign_ref
        config = self._interstate_theater_config(self.read("game/data/world/autonomous-theaters.json"), at=at, include_expeditionary=False)
        settled: list[dict[str, Any]] = []
        for cfg in config.get("theaters", []):
            if not isinstance(cfg, Mapping):
                continue
            sides = [str(x) for x in cfg.get("sides", []) if isinstance(x, str)]
            if len(sides) != 2 or side not in sides or side != sorted(sides)[0]:
                continue
            left, right = sides
            left_ref = left if left.startswith("polity_") else f"state_{left}"
            right_ref = right if right.startswith("polity_") else f"state_{right}"
            try:
                left_path, left_doc = self._sovereign_owner(left_ref)
                right_path, right_doc = self._sovereign_owner(right_ref)
            except (KeyError, ValueError, FileNotFoundError):
                continue
            # A treaty or explicitly friendly saved relation suppresses border friction.
            left_rel = left_doc.setdefault("diplomacy", {}).setdefault(right_ref, {})
            right_rel = right_doc.setdefault("diplomacy", {}).setdefault(left_ref, {})
            base = max(0, min(100, int(_fixed(cfg.get("base_pressure", 0), 0))))
            initial = min(60, base + 20)
            if "tension" not in left_rel:
                left_rel["tension"] = initial
            if "tension" not in right_rel:
                right_rel["tension"] = initial
            friendly = {str(left_rel.get("status", "")), str(right_rel.get("status", ""))} & {"allied", "client_relation", "nonaggression"}
            treaty_barrier = False
            treaties = self.read("state/politics/treaties.json")
            now = CampaignTime.parse(at)
            for treaty in treaties.get("records", {}).values() if isinstance(treaties, Mapping) else []:
                if not isinstance(treaty, Mapping) or str(treaty.get("status", "")) != "active":
                    continue
                parties = {str(x) for x in treaty.get("parties", []) if isinstance(x, str)}
                if {left_ref, right_ref} - parties:
                    continue
                terms = treaty.get("terms", {}) if isinstance(treaty.get("terms"), Mapping) else {}
                until = terms.get("nonaggression_until", treaty.get("truce_until"))
                if str(treaty.get("kind", "")) in {"alliance", "client_state"}:
                    treaty_barrier = True; break
                if isinstance(until, str):
                    try:
                        if CampaignTime.parse(until) > now:
                            treaty_barrier = True; break
                    except ValueError:
                        pass
            if friendly or treaty_barrier:
                for rel in (left_rel, right_rel):
                    rel["tension"] = max(0, int(rel.get("tension", 0)) - 4 * occurrences)
                    rel["last_changed_at"] = at
                self.put(left_path, left_doc); self.put(right_path, right_doc)
                continue

            theater_ref = str(cfg.get("theater_ref", ""))
            target = str(cfg.get("target_location_ref", ""))
            # The same theater-time hash is used for both sides, so review order cannot
            # create two different incidents.  Higher background friction raises chance.
            roll = int(hashlib.sha256(f"{theater_ref}|{at}|frontier-incident".encode()).hexdigest()[:8], 16) % 100
            incident = roll < min(60, base)
            floor = min(55, base + 10)
            if incident:
                severity_roll = int(hashlib.sha256(f"{theater_ref}|{at}|severity".encode()).hexdigest()[:8], 16) % 21
                severity = min(100, 45 + base // 2 + severity_roll)
                delta = 6 + severity // 15
                for rel in (left_rel, right_rel):
                    rel["tension"] = min(100, int(rel.get("tension", initial)) + delta)
                    rel["status"] = "hostile" if int(rel["tension"]) >= 70 else "tense"
                    rel["last_changed_at"] = at
                token = hashlib.sha256(f"{theater_ref}|{at}".encode()).hexdigest()[:12]
                for source_doc, source_ref, other_ref in ((left_doc, left_ref, right_ref), (right_doc, right_ref, left_ref)):
                    threats = source_doc.setdefault("known_threats", {})
                    threat_ref = f"frontier_incident_{token}_{source_ref.removeprefix('state_')}"
                    threats[threat_ref] = {
                        "kind": "frontier_incident", "severity": severity,
                        "source_ref": other_ref, "location_ref": target,
                        "observed_at": at, "theater_ref": theater_ref,
                        "basis": "deterministic contested-frontier contact between existing sovereign military systems",
                    }
                    # Keep only a bounded recent incident window plus all non-incident threats.
                    incident_keys = sorted((k for k,v in threats.items() if isinstance(v, Mapping) and v.get("kind") == "frontier_incident"), key=lambda k: str(threats[k].get("observed_at", "")))
                    for old in incident_keys[:-12]:
                        threats.pop(old, None)
                settled.append({"theater_ref": theater_ref, "at": at, "severity": severity, "tension_delta": delta, "sides": [left_ref, right_ref], "location_ref": target})
                for doc in (left_doc, right_doc):
                    runtime = doc.setdefault("frontier_runtime", {})
                    runtime["incident_count"] = int(runtime.get("incident_count", 0)) + 1
                    runtime["last_incident"] = settled[-1]
            else:
                for rel in (left_rel, right_rel):
                    rel["tension"] = max(floor, int(rel.get("tension", initial)) - occurrences)
                    rel["status"] = "tense" if int(rel["tension"]) >= 45 else "neutral"
                    rel["last_changed_at"] = at
            self.put(left_path, left_doc); self.put(right_path, right_doc)
        return settled

    def _generate_npc_war_intent(self, sovereign_ref: str, at: str) -> dict[str, Any] | None:
        """Generate a lawful NPC war goal from saved interests and capability.

        Border theaters are infrastructure only. This planner may create willingness,
        but actual hostilities still pass through `_interstate_war_decision`.
        """
        path, doc = self._sovereign_owner(sovereign_ref)
        if sovereign_ref.startswith("polity_") and str(doc.get("sovereign_house_ref", "")) == "house_tang":
            return None
        side = sovereign_ref.removeprefix("state_") if sovereign_ref.startswith("state_") else sovereign_ref
        existing = doc.setdefault("war_intents", [])
        if not isinstance(existing, list):
            raise ValueError("sovereign war intent registry is invalid")
        now = CampaignTime.parse(at)
        active: list[dict[str, Any]] = []
        for row in existing:
            if not isinstance(row, dict):
                continue
            expires = row.get("expires_at")
            if isinstance(expires, str) and CampaignTime.parse(expires) <= now and str(row.get("status", "")) in {"authorized", "ready"}:
                row["status"] = "expired"; row["expired_at"] = at
            if str(row.get("status", "")) in {"authorized", "ready"}:
                active.append(row)
        if active:
            self.put(path, doc)
            return None
        config = self._interstate_theater_config(self.read("game/data/world/autonomous-theaters.json"), at=at, include_expeditionary=False)
        territory = self.read("state/territory/control.json")
        own_strength = max(1, self._sovereign_military_strength(sovereign_ref, doc))
        treasury_path, treasury_doc, treasury_key = self._sovereign_treasury(sovereign_ref, doc)
        treasury = max(0, int(treasury_doc.get(treasury_key, 0)))
        readiness = max(0, min(100, int(_fixed(doc.get("mobilization_readiness", 50), 50))))
        goals_text = " ".join(str(x).lower() for x in doc.get("strategic_goals", []) if isinstance(x, str))
        candidates: list[tuple[float, str, str, dict[str, Any]]] = []
        for cfg in config.get("theaters", []):
            if not isinstance(cfg, Mapping) or side not in [str(x) for x in cfg.get("sides", [])]:
                continue
            other_side = next((str(x) for x in cfg.get("sides", []) if str(x) != side), "")
            if not other_side:
                continue
            target_ref = other_side if other_side.startswith("polity_") else f"state_{other_side}"
            target_location = str(cfg.get("target_location_ref", ""))
            relation = doc.get("diplomacy", {}).get(target_ref, {}) if isinstance(doc.get("diplomacy"), Mapping) else {}
            status = str(relation.get("status", "")) if isinstance(relation, Mapping) else ""
            if status in {"allied", "client_relation", "nonaggression"}:
                continue
            tension = max(0, min(100, int(_fixed(relation.get("tension", 0), 0)))) if isinstance(relation, Mapping) else 0
            site = territory.get("sites", {}).get(target_location, {}) if isinstance(territory, Mapping) else {}
            claims = site.get("legal_claims", {}) if isinstance(site, Mapping) and isinstance(site.get("legal_claims"), Mapping) else {}
            claim = claims.get(sovereign_ref, {}) if isinstance(claims, Mapping) else {}
            claim_strength = max(0, min(100, int(_fixed(claim.get("strength", 0), 0)))) if isinstance(claim, Mapping) else 0
            threat = 0
            for raw in doc.get("known_threats", {}).values() if isinstance(doc.get("known_threats"), Mapping) else []:
                if not isinstance(raw, Mapping):
                    continue
                source = str(raw.get("source_ref", raw.get("actor_ref", raw.get("state_ref", ""))))
                if source in {target_ref, other_side} or str(raw.get("location_ref", "")) == target_location:
                    threat = max(threat, max(0, min(100, int(_fixed(raw.get("severity", 0), 0)))))
            target_strength = max(1, self._sovereign_military_strength(target_ref))
            power_ratio = own_strength / target_strength
            opportunity = max(0.0, min(25.0, (power_ratio - 0.8) * 20.0))
            authored_friction = max(0, min(40, int(_fixed(cfg.get("base_pressure", 0), 0))))
            goal_interest = 10 if target_location.lower() in goals_text or other_side.lower() in goals_text or "expand" in goals_text or "contest" in goals_text else 0
            # Stable sovereign disposition changes the threshold, not the outcome.
            disposition = int(hashlib.sha256(f"{sovereign_ref}|strategic-risk".encode()).hexdigest()[:8], 16) % 21 - 10
            score = 0.28 * claim_strength + 0.26 * threat + 0.16 * tension + 0.45 * authored_friction + opportunity + goal_interest + disposition
            if readiness < 35 or treasury <= 0:
                score -= 30
            candidates.append((score, target_ref, target_location, {"claim_strength": claim_strength, "threat_score": threat, "tension": tension, "power_ratio": round(power_ratio, 4), "frontier_friction": authored_friction, "goal_interest": goal_interest, "readiness": readiness, "treasury_silver": treasury, "disposition_adjustment": disposition}))
        if not candidates:
            self.put(path, doc)
            return None
        score, target_ref, location_ref, basis = sorted(candidates, key=lambda row: (-row[0], row[1], row[2]))[0]
        # A state must have a material interest or serious threat; military superiority
        # alone never creates a casus belli.
        material_interest = int(basis["claim_strength"]) >= 35 or int(basis["threat_score"]) >= 45 or int(basis["tension"]) >= 65 or int(basis["goal_interest"]) > 0
        if score < 58 or not material_interest:
            doc["last_war_intent_review"] = {"at": at, "status": "no_intent", "best_score": round(score, 3), "target_ref": target_ref, "location_ref": location_ref, "basis": basis}
            self.put(path, doc)
            return None
        intent_ref = "war_intent_" + hashlib.sha256(f"{sovereign_ref}|{target_ref}|{location_ref}|{at}".encode()).hexdigest()[:16]
        intent = {"intent_ref": intent_ref, "target_ref": target_ref, "location_ref": location_ref, "kind": "npc_sovereign_strategic_intent", "objective": f"pursue the saved strategic interest at {location_ref}", "status": "authorized", "authorized_at": at, "expires_at": str(now.add_seconds(365 * 86400)), "authorization_basis": basis, "decision_score": round(score, 3)}
        existing.append(intent); doc["war_intents"] = existing[-32:]; doc["last_war_intent_review"] = {"at": at, "status": "authorized", "intent_ref": intent_ref, "basis": basis}
        self.put(path, doc)
        return intent

    def _interstate_theater_config(self, base: Mapping[str, Any], *, at: str | None = None, include_expeditionary: bool = True) -> dict[str, Any]:
        """Discover one exact front for every currently connected sovereign pair.

        Configured core-state theaters remain authoritative where their current
        controllers still match. Dynamic discovery uses *current territorial
        controllers*, so a House-founded polity that actually controls a border can
        enter the same interstate scheduler without being rewritten as one of the
        seven core state identities.
        """
        rows = [copy.deepcopy(x) for x in base.get("theaters", []) if isinstance(x, Mapping)]
        existing_pairs = {
            tuple(sorted(str(side) for side in row.get("sides", [])))
            for row in rows
            if isinstance(row.get("sides"), list) and len(row.get("sides", [])) == 2
        }
        locations = {
            str(x.get("ref")): x
            for x in self.read("game/data/world/locations.json").get("locations", [])
            if isinstance(x, Mapping)
        }
        territory = self.read("state/territory/control.json")
        sites = territory.get("sites", {}) if isinstance(territory, Mapping) else {}
        routes = self.read("game/data/world/routes.json").get("routes", [])
        core_states = {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}

        def controller_side(location_ref: str) -> str:
            site = sites.get(location_ref) if isinstance(sites, Mapping) else None
            controller = str(site.get("controller", "")) if isinstance(site, Mapping) else ""
            if controller.startswith("state_"):
                state = controller.removeprefix("state_")
                if state in core_states:
                    return state
            if controller.startswith("polity_"):
                try:
                    polity = self.read(self.owner_path(controller))
                except (KeyError, ValueError, FileNotFoundError):
                    return ""
                if str(polity.get("status", "")) in {"proto_state", "recognized_state"}:
                    return controller
                return ""
            static = str(locations.get(location_ref, {}).get("state", ""))
            return static if static in core_states else ""

        def ranked_formations(side: str) -> list[str]:
            force_refs: list[str] = []
            if side in core_states:
                force_refs = [f"force_state_{side}"]
            elif side.startswith("polity_"):
                try:
                    polity = self.read(self.owner_path(side))
                except (KeyError, ValueError, FileNotFoundError):
                    return []
                if str(polity.get("status", "")) not in {"proto_state", "recognized_state"}:
                    return []
                force_refs = sorted(str(x) for x in polity.get("military_force_refs", []) if isinstance(x, str))
            candidates: list[tuple[int, str]] = []
            seen: set[str] = set()
            for force_ref in force_refs:
                try:
                    force = self.read(self.owner_path(force_ref))
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                allocated = force.get("allocated_to_formations", {}) if isinstance(force, Mapping) else {}
                for ref in sorted(str(x) for x in allocated):
                    if ref in seen:
                        continue
                    seen.add(ref)
                    try:
                        _, formation = self._load_formation(ref)
                    except ValueError:
                        continue
                    if int(formation.get("personnel", 0)) <= 0:
                        continue
                    if str(formation.get("commander_ref", "")) == self.PLAYER_ACTOR or str(formation.get("command_authority", "")) == self.PLAYER_ACTOR:
                        continue
                    readiness = int(formation.get("readiness", 0))
                    cohesion = int(formation.get("cohesion", 0))
                    morale = int(formation.get("morale", 0))
                    candidates.append((readiness + cohesion + morale, ref))
            return [ref for _, ref in sorted(candidates, key=lambda row: (-row[0], row[1]))]

        # Authored theaters define strategic geography, not a fictional two-unit cap.
        # Refresh each side's executable campaign group from its current exact force
        # owners while preserving an authored preferred principal formation when it
        # is still eligible.
        for row in rows:
            sides = [str(x) for x in row.get("sides", [])]
            if len(sides) != 2:
                continue
            lists: dict[str, list[str]] = {}
            groups: dict[str, Any] = {}
            for side in sides:
                refs = ranked_formations(side)
                preferred = str((row.get("formation_refs", {}) or {}).get(side, "")) if isinstance(row.get("formation_refs"), Mapping) else ""
                if preferred in refs:
                    refs = [preferred] + [ref for ref in refs if ref != preferred]
                if refs:
                    lists[side] = refs
                    groups[side] = {"primary_ref": refs[0], "formation_refs": refs, "reserve_refs": refs[1:]}
                    row.setdefault("formation_refs", {})[side] = refs[0]
            if lists:
                row["formation_ref_lists"] = lists
                row["army_groups"] = groups

        pair_routes: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
        for route in routes if isinstance(routes, list) else []:
            if not isinstance(route, Mapping):
                continue
            a = str(route.get("a", route.get("from", "")))
            b = str(route.get("b", route.get("to", "")))
            sa = controller_side(a)
            sb = controller_side(b)
            if not sa or not sb or sa == sb:
                continue
            pair = tuple(sorted((sa, sb)))
            pair_routes.setdefault(pair, []).append((str(route.get("ref", "")), a, b))

        for pair, connections in sorted(pair_routes.items()):
            if pair in existing_pairs:
                continue
            left, right = pair
            left_forms = ranked_formations(left)
            right_forms = ranked_formations(right)
            if not left_forms or not right_forms:
                continue
            route_ref, a, b = sorted(connections)[0]
            target = b if controller_side(b) == right else a
            slug = lambda value: value.replace("polity_", "polity-").replace("_", "-")
            rows.append({
                "theater_ref": f"dynamic_{slug(left)}_{slug(right)}_front",
                "sides": [left, right],
                "target_location_ref": target,
                "base_pressure": 12,
                "formation_refs": {left: left_forms[0], right: right_forms[0]},
                "formation_ref_lists": {left: left_forms, right: right_forms},
                "army_groups": {
                    left: {"primary_ref": left_forms[0], "formation_refs": left_forms, "reserve_refs": left_forms[1:]},
                    right: {"primary_ref": right_forms[0], "formation_refs": right_forms, "reserve_refs": right_forms[1:]},
                },
                "dynamic": True,
                "route_ref": route_ref,
                "route_candidates": [ref for ref, _, _ in sorted(connections)],
                "discovery_basis": "current cross-sovereign route topology plus exact staffed force availability",
            })
            existing_pairs.add(pair)

        if not include_expeditionary:
            return {"theaters": rows}

        # Defensive treaty obligations can create an expeditionary front even when
        # the obligated sovereign does not directly border the aggressor.  Exact
        # military-access/alliance/client/coalition transit is enforced later by the
        # formation route planner; this discovery step merely exposes a lawful target
        # that the saved treaty-defense war intent can activate.
        sovereign_refs = [f"state_{s}" for s in sorted(core_states)]
        sovereign_refs.extend(sorted(str(ref) for ref in self.read("state/index/owner-index.json").get("owners", {}) if str(ref).startswith("polity_")))
        now_text = str(at or self._world_time())
        for sovereign_ref in sovereign_refs:
            try: _sp, sovereign = self._sovereign_owner(sovereign_ref)
            except (KeyError, ValueError, FileNotFoundError): continue
            own_side = sovereign_ref if sovereign_ref.startswith("polity_") else sovereign_ref.removeprefix("state_")
            own_forms = ranked_formations(own_side)
            if not own_forms: continue
            for intent in sovereign.get("war_intents", []) if isinstance(sovereign, Mapping) else []:
                if not isinstance(intent, Mapping) or str(intent.get("kind", "")) != "treaty_defense" or str(intent.get("status", "")) not in {"authorized", "ready", "activated"}: continue
                target_ref = str(intent.get("target_ref", "")); target_side = target_ref if target_ref.startswith("polity_") else target_ref.removeprefix("state_")
                if not target_side or target_side == own_side: continue
                pair = tuple(sorted((own_side, target_side)))
                if pair in existing_pairs: continue
                enemy_forms = ranked_formations(target_side)
                if not enemy_forms: continue
                candidate_sites = sorted(str(loc) for loc, site in sites.items() if isinstance(site, Mapping) and str(site.get("controller", "")) == target_ref)
                if not candidate_sites:
                    continue
                # Discovery needs one physically reachable expeditionary objective, not
                # a full movement preview for every formation x enemy site pair.  Exact
                # military-access/treaty admission is still enforced when the selected
                # formation actually marches.  Group by current origin and run one
                # multi-target route search per origin to keep long-horizon strategic
                # review bounded without changing movement mechanics.
                formation_by_origin: dict[str, str] = {}
                for formation_ref in own_forms:
                    try:
                        _fp, formation = self._load_formation(formation_ref)
                    except ValueError:
                        continue
                    origin = str(formation.get("location_ref", ""))
                    if origin and origin not in formation_by_origin:
                        formation_by_origin[origin] = formation_ref
                best: tuple[int, str, str] | None = None
                for origin, formation_ref in sorted(formation_by_origin.items()):
                    try:
                        route_pick = geography_nearest_destination(
                            self.read, origin, candidate_sites, modes=("formation",)
                        )
                    except ValueError:
                        continue
                    row = (int(route_pick.get("duration_hours", 0)), str(route_pick.get("destination", "")), formation_ref)
                    if row[1] and (best is None or row < best):
                        best = row
                if best is None:
                    continue
                _travel, target_loc, preferred = best
                own_forms = [preferred] + [ref for ref in own_forms if ref != preferred]
                slug = lambda value: value.replace("polity_", "polity-").replace("_", "-")
                rows.append({"theater_ref": f"expeditionary_{slug(own_side)}_vs_{slug(target_side)}", "sides": [own_side, target_side], "target_location_ref": target_loc, "base_pressure": 0, "formation_refs": {own_side: own_forms[0], target_side: enemy_forms[0]}, "formation_ref_lists": {own_side: own_forms, target_side: enemy_forms}, "army_groups": {own_side: {"primary_ref": own_forms[0], "formation_refs": own_forms, "reserve_refs": own_forms[1:]}, target_side: {"primary_ref": enemy_forms[0], "formation_refs": enemy_forms, "reserve_refs": enemy_forms[1:]}}, "dynamic": True, "expeditionary": True, "defended_sovereign_ref": str(intent.get("defended_sovereign_ref", "")), "source_treaty_ref": str(intent.get("treaty_ref", "")), "discovery_basis": "saved treaty-defense war intent plus exact access-aware formation route to aggressor-controlled territory"})
                existing_pairs.add(pair); break
        return {"theaters": rows}

    def _sovereign_owner(self, sovereign_ref: str) -> tuple[str, dict[str, Any]]:
        if sovereign_ref.startswith("state_"):
            self._state_key(sovereign_ref)
        elif sovereign_ref.startswith("polity_"):
            _path, doc = self.owner(sovereign_ref)
            if str(doc.get("schema", "")) != "sword-polity" or str(doc.get("status", "")) == "dissolved":
                raise ValueError("sovereign polity is not active")
        else:
            raise ValueError("sovereign reference must be state_ or polity_")
        path = self.owner_path(sovereign_ref)
        return path, copy.deepcopy(self.read(path))

    def _sovereign_seat(self, sovereign_ref: str, doc: Mapping[str, Any]) -> str:
        if sovereign_ref.startswith("state_"):
            state = sovereign_ref.removeprefix("state_")
            return str(self.read(f"state/depots/{state}.json").get("location_ref", ""))
        seat = str(doc.get("seat_claim_ref", ""))
        if seat:
            return seat
        occupied = [str(x) for x in doc.get("occupied_site_refs", []) if isinstance(x, str)]
        return occupied[0] if occupied else ""

    def _sovereign_treasury(self, sovereign_ref: str, sovereign_doc: Mapping[str, Any] | None = None) -> tuple[str, dict[str, Any], str]:
        path, doc = self._sovereign_owner(sovereign_ref) if sovereign_doc is None else (self.owner_path(sovereign_ref), copy.deepcopy(dict(sovereign_doc)))
        if sovereign_ref.startswith("state_"):
            return path, doc, "treasury_silver"
        treasury_ref = str(doc.get("treasury_ref", ""))
        if not treasury_ref:
            raise ValueError("sovereign polity has no exact treasury")
        tp = self.owner_path(treasury_ref); td = copy.deepcopy(self.read(tp)); key, _ = self._funds_value(td)
        return tp, td, key

    def _sovereign_military_strength(self, sovereign_ref: str, doc: Mapping[str, Any] | None = None) -> int:
        _path, sd = self._sovereign_owner(sovereign_ref) if doc is None else (self.owner_path(sovereign_ref), copy.deepcopy(dict(doc)))
        force_refs = [f"force_state_{sovereign_ref.removeprefix('state_')}"] if sovereign_ref.startswith("state_") else [str(x) for x in sd.get("military_force_refs", []) if isinstance(x, str)]
        total = 0
        for force_ref in force_refs:
            try:
                force = self.read(self.owner_path(force_ref))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            total += max(0, int(force.get("headcount", 0)))
        return total

    def _update_sovereign_diplomacy(self, a_ref: str, b_ref: str, *, status: str | None = None, tension_delta: int = 0, at: str, treaty_ref: str | None = None) -> None:
        for source_ref, target_ref in ((a_ref, b_ref), (b_ref, a_ref)):
            sp, sd = self._sovereign_owner(source_ref)
            diplomacy = sd.setdefault("diplomacy", {})
            row = diplomacy.setdefault(target_ref, {})
            row["tension"] = max(0, min(100, int(row.get("tension", 0)) + int(tension_delta)))
            if status is not None:
                row["status"] = status
            row["last_changed_at"] = at
            if treaty_ref:
                refs = row.setdefault("treaty_refs", [])
                if treaty_ref not in refs: refs.append(treaty_ref)
                del refs[:-16]
            self.put(sp, sd)

    def _active_treaties(self, at: str) -> list[dict[str, Any]]:
        """Return active unexpired treaties without mutating their registry."""
        registry = self.read("state/politics/treaties.json")
        now = CampaignTime.parse(at)
        out: list[dict[str, Any]] = []
        for raw in registry.get("records", {}).values() if isinstance(registry, Mapping) else []:
            if not isinstance(raw, Mapping) or str(raw.get("status", "")) != "active":
                continue
            terms = raw.get("terms", {}) if isinstance(raw.get("terms"), Mapping) else {}
            expiry = terms.get("expires_at") or raw.get("truce_until")
            if isinstance(expiry, str):
                try:
                    if CampaignTime.parse(expiry) <= now:
                        continue
                except ValueError:
                    continue
            out.append(copy.deepcopy(dict(raw)))
        return out

    def _active_treaties_between(self, a_ref: str, b_ref: str, at: str) -> list[dict[str, Any]]:
        """Return exact active treaty records binding both sovereigns.

        Bilateral ``diplomacy.status`` is only a compact relationship summary.  A
        later access, guarantee, or other agreement may legitimately change that
        summary without cancelling an earlier alliance.  Treaty existence and
        obligations therefore come from the treaty registry itself.
        """
        pair = {str(a_ref), str(b_ref)}
        return [
            treaty
            for treaty in self._active_treaties(at)
            if pair.issubset({str(x) for x in treaty.get("parties", []) if isinstance(x, str)})
        ]

    def _equivalent_active_treaty(
        self,
        *,
        kind: str,
        direction: str,
        proposer_ref: str,
        target_ref: str,
        terms: Mapping[str, Any],
        at: str,
    ) -> dict[str, Any] | None:
        """Find an already-active treaty with the same durable obligation.

        This deliberately covers only standing diplomatic relationships that would
        otherwise stack accidentally.  One-shot settlements such as reparations,
        hostage exchanges, marriages, and territorial exchanges remain distinct
        transactions because their exact terms can create separate consequences.
        """
        kind = str(kind)
        if kind not in {"alliance", "nonaggression", "military_access", "guarantee", "client_state", "coalition"}:
            return None
        for treaty in self._active_treaties_between(proposer_ref, target_ref, at):
            if str(treaty.get("kind", "")) != kind:
                continue
            active_terms = treaty.get("terms", {}) if isinstance(treaty.get("terms"), Mapping) else {}
            if kind in {"alliance", "nonaggression"}:
                return treaty
            if kind == "military_access":
                grantor, beneficiary = self._asymmetric_treaty_roles(kind, direction, proposer_ref, target_ref)
                if str(active_terms.get("military_access_grantor_ref", "")) == grantor and str(active_terms.get("military_access_beneficiary_ref", "")) == beneficiary:
                    return treaty
            elif kind == "guarantee":
                guarantor, protected = self._asymmetric_treaty_roles(kind, direction, proposer_ref, target_ref)
                if str(active_terms.get("guarantor_ref", "")) == guarantor and str(active_terms.get("protected_ref", "")) == protected:
                    return treaty
            elif kind == "client_state":
                client, patron = self._asymmetric_treaty_roles(kind, direction, proposer_ref, target_ref)
                if str(active_terms.get("client_ref", "")) == client and str(active_terms.get("patron_ref", "")) == patron:
                    return treaty
            elif kind == "coalition":
                if str(active_terms.get("coalition_target_ref", "")) == str(terms.get("coalition_target_ref", "")):
                    return treaty
        return None

    def _autonomous_diplomatic_initiative_cooldown_seconds(self, sovereign_doc: Mapping[str, Any], at: str, *, threat_severity: int) -> int:
        """Return remaining autonomous formal-diplomacy cooldown in seconds.

        The cooldown is derived from already-existing proposal records instead of a
        mutable ``last_action`` field, keeping hot state compact and auditable.
        Player-authored or externally initiated proposals do not consume this NPC
        sovereign initiative capacity.
        """
        politics = self.read("game/data/mechanics/politics.json")
        rules = politics.get("diplomacy_autonomy", {}) if isinstance(politics, Mapping) else {}
        urgent_threshold = max(0, min(100, int(_fixed(rules.get("urgent_threat_severity", 65), 65))))
        cooldown_days = int(_fixed(
            rules.get("urgent_initiative_cooldown_days" if int(threat_severity) >= urgent_threshold else "ordinary_initiative_cooldown_days", 30 if int(threat_severity) >= urgent_threshold else 90),
            30 if int(threat_severity) >= urgent_threshold else 90,
        ))
        cooldown_seconds = max(1, cooldown_days) * 86400
        now = CampaignTime.parse(at)
        latest_at: CampaignTime | None = None
        for proposal_ref in [str(x) for x in sovereign_doc.get("outgoing_diplomatic_proposal_refs", []) if isinstance(x, str)]:
            try:
                proposal = self.read(self.owner_path(proposal_ref))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            provenance = proposal.get("provenance", {}) if isinstance(proposal.get("provenance"), Mapping) else {}
            if str(provenance.get("kind", "")) != "npc_sovereign_initiative":
                continue
            proposed_at = proposal.get("proposed_at")
            if not isinstance(proposed_at, str):
                continue
            try:
                parsed = CampaignTime.parse(proposed_at)
            except ValueError:
                continue
            if latest_at is None or parsed > latest_at:
                latest_at = parsed
        if latest_at is None:
            return 0
        elapsed = max(0, latest_at.seconds_until(now))
        return max(0, cooldown_seconds - elapsed)

    def _propagate_defensive_treaty_obligations(
        self,
        *,
        attacker_ref: str,
        defender_ref: str,
        location_ref: str,
        theater_ref: str,
        at: str,
    ) -> list[dict[str, Any]]:
        """Turn accepted defensive treaties into exact sovereign response work.

        An alliance/guarantee/client relation is not decorative diplomacy. When the
        protected party is attacked, the obligated sovereign receives an exact
        defensive war intent and threat basis. The normal interstate planner still
        decides whether/where that sovereign can materially enter the war; this hook
        does not fabricate a battle or teleport a force.
        """
        obligations: list[dict[str, Any]] = []
        registry = copy.deepcopy(self.read("state/politics/treaties.json"))
        changed_registry = False
        for treaty_ref, treaty in registry.get("records", {}).items():
            if not isinstance(treaty, dict) or str(treaty.get("status", "")) != "active":
                continue
            terms = treaty.get("terms", {}) if isinstance(treaty.get("terms"), Mapping) else {}
            kind = str(treaty.get("kind", ""))
            obligated: list[str] = []
            if kind == "alliance" and bool(terms.get("mutual_defense")):
                parties = [str(x) for x in treaty.get("parties", []) if isinstance(x, str)]
                if defender_ref in parties:
                    obligated.extend(x for x in parties if x != defender_ref)
            elif kind == "guarantee" and str(terms.get("protected_ref", "")) == defender_ref:
                guarantor = str(terms.get("guarantor_ref", ""))
                if guarantor:
                    obligated.append(guarantor)
            elif kind == "client_state" and bool(terms.get("patron_defense_obligation")) and str(terms.get("client_ref", "")) == defender_ref:
                patron = str(terms.get("patron_ref", ""))
                if patron:
                    obligated.append(patron)
            elif kind == "coalition" and bool(terms.get("mutual_defense_against_target")) and str(terms.get("coalition_target_ref", "")) == attacker_ref:
                members = [str(x) for x in treaty.get("parties", []) if isinstance(x, str)]
                if defender_ref in members:
                    obligated.extend(x for x in members if x != defender_ref)
            for obligated_ref in sorted(set(obligated)):
                if obligated_ref in {attacker_ref, defender_ref}:
                    continue
                try:
                    opath, odoc = self._sovereign_owner(obligated_ref)
                except (KeyError, ValueError, FileNotFoundError):
                    continue
                intents = odoc.setdefault("war_intents", [])
                existing = next((
                    row for row in intents
                    if isinstance(row, Mapping)
                    and str(row.get("status", "")) in {"authorized", "ready", "activated"}
                    and str(row.get("target_ref", "")) == attacker_ref
                    and str(row.get("treaty_ref", "")) == str(treaty_ref)
                ), None)
                if existing is None:
                    intent_ref = "war_intent_treaty_" + hashlib.sha256(
                        f"{treaty_ref}|{obligated_ref}|{attacker_ref}|{defender_ref}|{theater_ref}".encode("utf-8")
                    ).hexdigest()[:18]
                    intent = {
                        "intent_ref": intent_ref,
                        "target_ref": attacker_ref,
                        "location_ref": "",
                        "kind": "treaty_defense",
                        "objective": f"honor {treaty_ref} and defend {defender_ref} against {attacker_ref}",
                        "status": "authorized",
                        "authorized_at": at,
                        "authorized_by": str(treaty_ref),
                        "treaty_ref": str(treaty_ref),
                        "defended_sovereign_ref": defender_ref,
                        "source_theater_ref": theater_ref,
                    }
                    intents.append(intent)
                    del intents[:-32]
                else:
                    intent_ref = str(existing.get("intent_ref", ""))
                threat_ref = f"treaty_defense:{theater_ref}:{attacker_ref}"
                odoc.setdefault("known_threats", {})[threat_ref] = {
                    "severity": 90,
                    "kind": "treaty_defense_obligation",
                    "source_ref": attacker_ref,
                    "location_ref": location_ref,
                    "observed_at": at,
                    "treaty_ref": str(treaty_ref),
                    "defended_sovereign_ref": defender_ref,
                    "provenance": "active accepted defensive treaty invoked by exact interstate war initiation",
                }
                self.put(opath, odoc)
                invocation = {
                    "at": at,
                    "obligated_ref": obligated_ref,
                    "protected_ref": defender_ref,
                    "against_ref": attacker_ref,
                    "source_theater_ref": theater_ref,
                    "war_intent_ref": intent_ref,
                }
                history = treaty.setdefault("defense_invocations", [])
                if not any(
                    isinstance(row, Mapping)
                    and str(row.get("source_theater_ref", "")) == theater_ref
                    and str(row.get("obligated_ref", "")) == obligated_ref
                    for row in history
                ):
                    history.append(copy.deepcopy(invocation))
                    del history[:-24]
                    treaty["last_invoked_at"] = at
                    changed_registry = True
                obligations.append({"treaty_ref": str(treaty_ref), **invocation})
        if changed_registry:
            self.put("state/politics/treaties.json", registry)
        return obligations

    def _formation_sovereign_ref(self, formation: Mapping[str, Any]) -> str | None:
        """Resolve the sovereign whose movement law governs one exact formation."""
        owner = str(formation.get("administrative_owner", ""))
        if owner.startswith("state_") or owner.startswith("polity_"):
            return owner
        if owner.startswith("house_"):
            try:
                house = self.read(self.owner_path(owner))
            except (KeyError, ValueError, FileNotFoundError):
                return None
            polity_ref = str(house.get("sovereignty_ref", ""))
            if polity_ref.startswith("polity_"):
                return polity_ref
            state = str(house.get("state", ""))
            if state in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
                return f"state_{state}"
        return None

    def _autonomy_polity_sustain_march(self, formation_ref: str, destination: str, at: str, theater_record: dict[str, Any], key: str, polity_ref: str) -> dict[str, Any]:
        """Dispatch one exact polity supply convoy from its granary authority."""
        path, formation0 = self._load_formation(formation_ref); formation = copy.deepcopy(formation0); origin = str(formation.get("location_ref", "")); n = max(0, int(formation.get("personnel", 0)))
        if n <= 0 or origin == destination: return {"status": "not_needed", "location_ref": origin}
        try: next_hop, hours = self._formation_route_next(origin, destination, formation=formation, at=at)
        except ValueError: return {"status": "no_route", "location_ref": origin}
        mounts = sum(max(0, int(v)) for v in (formation.get("mounts", {}) or {}).values()); food_need = max(1, int(math.ceil(n * 1.5 * hours / 24.0))); fodder_need = max(0, int(math.ceil(mounts * 4.0 * hours / 24.0))); logistics = formation.setdefault("logistics", {})
        if int(logistics.get("food_kg", 0)) >= food_need and int(logistics.get("fodder_kg", 0)) >= fodder_need: return {"status": "sufficient", "location_ref": origin}
        convoy_key = f"{key}_supply_convoy_{formation_ref}"; convoy = theater_record.get(convoy_key); now = CampaignTime.parse(at)
        if isinstance(convoy, Mapping):
            if CampaignTime.parse(str(convoy.get("arrives_at"))) <= now and str(formation.get("location_ref", "")) == str(convoy.get("destination_location_ref", "")):
                food = max(0, int(convoy.get("food_kg", 0))); fodder = max(0, int(convoy.get("fodder_kg", 0))); logistics["food_kg"] = int(logistics.get("food_kg", 0)) + food; logistics["fodder_kg"] = int(logistics.get("fodder_kg", 0)) + fodder; self.put(path, formation); theater_record.pop(convoy_key, None); return {"status": "convoy_received", "location_ref": origin, "food_kg": food, "fodder_kg": fodder}
            return {"status": "convoy_in_transit", "location_ref": origin, "arrives_at": str(convoy.get("arrives_at"))}
        polity = self.read(self.owner_path(polity_ref)); granary = None; granary_path = None
        for ref in [str(x) for x in polity.get("institution_refs", []) if isinstance(x, str)]:
            try: ip = self.owner_path(ref); inst = self.read(ip)
            except (KeyError, ValueError, FileNotFoundError): continue
            if str(inst.get("kind", "")) == "granary_depot_office": granary = copy.deepcopy(inst); granary_path = ip; break
        if granary is None or granary_path is None: return {"status": "no_polity_granary", "location_ref": origin}
        resources = granary.setdefault("resources", {}); dispatch_food = min(max(food_need * 4, n * 3), max(0, int(resources.get("grain_kg", 0)))); dispatch_fodder = min(max(fodder_need * 4, mounts * 8), max(0, int(resources.get("fodder_kg", 0))))
        if dispatch_food < food_need or dispatch_fodder < fodder_need: return {"status": "granary_shortfall", "location_ref": origin, "food_available": dispatch_food, "fodder_available": dispatch_fodder}
        resources["grain_kg"] = int(resources.get("grain_kg", 0)) - dispatch_food; resources["fodder_kg"] = int(resources.get("fodder_kg", 0)) - dispatch_fodder; travel_hours = max(1, self._route_travel_hours(str(granary.get("location_ref", polity.get("seat_claim_ref", origin))), origin, modes=("horse", "foot"))); arrives = str(now.add_seconds(travel_hours * 3600)); theater_record[convoy_key] = {"source_ref": str(granary.get("owner_id")), "formation_ref": formation_ref, "destination_location_ref": origin, "food_kg": dispatch_food, "fodder_kg": dispatch_fodder, "dispatched_at": at, "arrives_at": arrives}; granary.setdefault("convoy_history", []).append({"at": at, "formation_ref": formation_ref, "food_kg": dispatch_food, "fodder_kg": dispatch_fodder, "arrives_at": arrives}); granary["convoy_history"] = granary["convoy_history"][-24:]; self.put(granary_path, granary); return {"status": "convoy_dispatched", "location_ref": origin, "arrives_at": arrives}

    def _validate_formation_transit(self, formation: Mapping[str, Any], destination_ref: str, at: str) -> None:
        """Enforce sovereign access at a foreign-controlled destination.

        Hostile wartime entry remains legal. Peaceful foreign entry requires an
        accepted military-access treaty. Locations outside the exact territorial
        registry retain their existing local/reference movement behavior.
        """
        territory = self.read("state/territory/control.json")
        site = territory.get("sites", {}).get(destination_ref, {}) if isinstance(territory, Mapping) else {}
        controller_ref = str(site.get("controller", "")) if isinstance(site, Mapping) else ""
        sovereign_ref = self._formation_sovereign_ref(formation)
        # Hostile strategic approach and hostile entry behind an intact enclosing
        # fortification are different authorities.  A wartime formation may reach
        # the fort/gate to contest it, but cannot use a local interior edge as a
        # teleport past the defensive perimeter.  Once the parent site's physical
        # controller changes, ordinary transit rules apply again.
        enclosure = enclosing_fortification_site(self.read, destination_ref)
        if enclosure and enclosure != destination_ref:
            try:
                locations = self.read("game/data/world/locations.json")
                loc = next((row for row in locations.get("locations", []) if str(row.get("ref")) == destination_ref), {})
            except (KeyError, FileNotFoundError, ValueError):
                loc = {}
            is_access_node = bool(loc.get("strategic_node")) and str(loc.get("spatial_scale", "")) == "access"
            enclosure_site = territory.get("sites", {}).get(enclosure, {}) if isinstance(territory, Mapping) else {}
            enclosure_controller = str(enclosure_site.get("controller", "")) if isinstance(enclosure_site, Mapping) else ""
            if not is_access_node and sovereign_ref and enclosure_controller and enclosure_controller != sovereign_ref:
                raise PermissionError(f"formation cannot enter {destination_ref} behind hostile enclosing fortification {enclosure}")
        if not controller_ref or not sovereign_ref or controller_ref == sovereign_ref:
            return
        # An active war relation is sufficient authority for hostile strategic entry.
        try:
            _sp, sovereign = self._sovereign_owner(sovereign_ref)
        except (KeyError, ValueError, FileNotFoundError):
            sovereign = {}
        diplomacy = sovereign.get("diplomacy", {}) if isinstance(sovereign, Mapping) else {}
        relation = diplomacy.get(controller_ref, {}) if isinstance(diplomacy, Mapping) else {}
        if isinstance(relation, Mapping) and str(relation.get("status", "")) == "war":
            return
        for intent in sovereign.get("war_intents", []) if isinstance(sovereign, Mapping) else []:
            if not isinstance(intent, Mapping) or str(intent.get("status", "")) not in {"authorized", "ready", "activated"}: continue
            if str(intent.get("target_ref", "")) == controller_ref:
                return
        for treaty in self._active_treaties(at):
            kind = str(treaty.get("kind", "")); parties = {str(x) for x in treaty.get("parties", []) if isinstance(x, str)}
            terms = treaty.get("terms", {}) if isinstance(treaty.get("terms"), Mapping) else {}
            if kind == "military_access" and str(terms.get("military_access_grantor_ref", "")) == controller_ref and str(terms.get("military_access_beneficiary_ref", "")) == sovereign_ref:
                return
            if kind == "alliance" and bool(terms.get("mutual_defense")) and {controller_ref, sovereign_ref}.issubset(parties):
                return
            if kind == "coalition" and {controller_ref, sovereign_ref}.issubset(parties):
                return
            if kind == "client_state" and {controller_ref, sovereign_ref}.issubset(parties):
                return
        raise PermissionError(f"formation lacks sovereign military access to {destination_ref} under {controller_ref}")

    @staticmethod
    def _asymmetric_treaty_roles(kind: str, direction: str, proposer: str, target: str) -> tuple[str, str]:
        if direction not in {"proposer_to_target", "target_to_proposer"}:
            raise ValueError(f"{kind} requires an explicit asymmetric treaty direction")
        return (proposer, target) if direction == "proposer_to_target" else (target, proposer)

    def _person_under_sovereign_authority(self, person_ref: str, sovereign_ref: str) -> bool:
        """Return whether a sovereign can lawfully nominate this exact person diplomatically.

        State affiliation, House sovereignty, and exact polity appointments are the
        admissible authority routes. Mere physical presence or model inference is
        never enough.
        """
        try:
            _pp, person = self._exact_person(person_ref)
            _sp, sovereign = self._sovereign_owner(sovereign_ref)
        except (KeyError, ValueError, FileNotFoundError):
            return False
        if sovereign_ref.startswith("state_"):
            try:
                return self._state_key(str(person.get("state", ""))) == sovereign_ref.removeprefix("state_")
            except ValueError:
                return False
        if not sovereign_ref.startswith("polity_"):
            return False
        house_ref = str(sovereign.get("sovereign_house_ref", ""))
        if person_ref == self.PLAYER_ACTOR and house_ref == "house_tang":
            return True
        if house_ref and str(person.get("house_ref", "")) == house_ref:
            return True
        career = person.get("career_state", {}) if isinstance(person.get("career_state"), Mapping) else {}
        for row in career.get("appointments", []) if isinstance(career.get("appointments"), list) else []:
            if isinstance(row, Mapping) and str(row.get("polity_ref", "")) == sovereign_ref:
                return True
        return False

    def _create_diplomatic_family_proposal(self, person_ref: str, partner_ref: str, treaty_ref: str, at: str) -> str:
        self._exact_person(person_ref); self._exact_person(partner_ref)
        idx = copy.deepcopy(self.read("state/family/index.json"))
        proposal_id = "family_diplomatic_" + hashlib.sha256(f"{treaty_ref}|{person_ref}|{partner_ref}".encode()).hexdigest()[:18]
        path = f"state/family/proposals/{proposal_id}.json"
        if self.read_optional(path) is None:
            proposal = {"schema": "family-proposal", "proposal_id": proposal_id, "kind": "marriage_proposal", "proposer_id": person_ref, "target_id": partner_ref, "status": "pending", "authority": True, "proposed_at": at, "player_choice_required": partner_ref == self.PLAYER_ACTOR or person_ref == self.PLAYER_ACTOR, "diplomatic_treaty_ref": treaty_ref, "basis": "accepted sovereign marriage diplomacy creates a real personal/family proposal but never substitutes for individual consent"}
            self.put(path, proposal)
            self._register_owner(proposal_id, path)
            idx.setdefault("proposals", {})[proposal_id] = path
            idx.setdefault("counts", {})["proposals"] = len(idx["proposals"])
            for ref in (person_ref, partner_ref):
                refs = idx.setdefault("person_index", {}).setdefault(ref, {}).setdefault("proposals", [])
                if proposal_id not in refs: refs.append(proposal_id)
            self.put("state/family/index.json", idx)
        return proposal_id

    def _apply_diplomatic_hostage(self, person_ref: str, giver_ref: str, receiver_ref: str, treaty_ref: str, at: str) -> dict[str, Any]:
        if not self._person_under_sovereign_authority(person_ref, giver_ref):
            raise PermissionError("hostage giver lacks exact sovereign authority over nominated person")
        person_path, person0 = self._exact_person(person_ref); person = copy.deepcopy(person0)
        _rp, receiver = self._sovereign_owner(receiver_ref); destination = self._sovereign_seat(receiver_ref, receiver)
        if not destination: raise ValueError("hostage receiver has no exact sovereign seat")
        old_location = self._person_location(person)
        self._set_person_location(person, destination)
        person.setdefault("career_state", {})["hostage_status"] = {"active": True, "treaty_ref": treaty_ref, "giver_ref": giver_ref, "receiver_ref": receiver_ref, "held_at": destination, "since": at}
        self.put(person_path, person)
        return {"person_ref": person_ref, "from_location_ref": old_location, "to_location_ref": destination, "giver_ref": giver_ref, "receiver_ref": receiver_ref}

    def _apply_treaty_territorial_exchange(self, proposer: str, target: str, terms: Mapping[str, Any], treaty_ref: str, at: str) -> list[dict[str, Any]]:
        territory = copy.deepcopy(self.read("state/territory/control.json")); changes: list[dict[str, Any]] = []
        transfers = [(proposer, target, [str(x) for x in terms.get("offer_location_refs", []) if isinstance(x, str)]), (target, proposer, [str(x) for x in terms.get("request_location_refs", []) if isinstance(x, str)])]
        for giver, receiver, locations in transfers:
            for location_ref in locations:
                site = territory.get("sites", {}).get(location_ref) if isinstance(territory, Mapping) else None
                if not isinstance(site, dict) or str(site.get("controller", "")) != giver:
                    raise ValueError("territorial exchange requires the giver to currently control every transferred site")
                prior = str(site.get("controller", "")); site["previous_controller"] = prior; site["controller"] = receiver; site["changed_at"] = at; site["change_basis"] = "negotiated_territorial_exchange"; site["change_evidence_ref"] = treaty_ref
                claims = site.setdefault("legal_claims", {}); claims.setdefault(receiver, {}).update({"strength": max(90, int(claims.get(receiver, {}).get("strength", 0))), "basis": "accepted negotiated territorial exchange", "treaty_ref": treaty_ref})
                gov = site.setdefault("governance", {}); gov.update({"military_controller": receiver, "status": "transferred_civil_administration", "administration": max(60, int(gov.get("administration", 60))), "resistance": min(40, int(gov.get("resistance", 40))), "tax_compliance": max(45, int(gov.get("tax_compliance", 45))), "last_transfer_at": at})
                changes.append({"location_ref": location_ref, "from": giver, "to": receiver})
                for ref, add in ((giver, False), (receiver, True)):
                    pp, pd = self._sovereign_owner(ref)
                    if ref.startswith("polity_"):
                        held = [str(x) for x in pd.get("occupied_site_refs", []) if isinstance(x, str)]
                        if add and location_ref not in held: held.append(location_ref)
                        if not add: held = [x for x in held if x != location_ref]
                        pd["occupied_site_refs"] = sorted(set(held))
                    else:
                        held = [str(x) for x in pd.get("territorial_control", []) if isinstance(x, str)]
                        if add and location_ref not in held: held.append(location_ref)
                        if not add: held = [x for x in held if x != location_ref]
                        pd["territorial_control"] = sorted(set(held))
                    self.put(pp, pd)
        self.put("state/territory/control.json", territory)
        return changes

    def _activate_diplomatic_treaty(self, proposal: dict[str, Any], at: str) -> str:
        treaty_registry = copy.deepcopy(self.read("state/politics/treaties.json"))
        proposal_ref = str(proposal["proposal_ref"]); kind = str(proposal["kind"]); proposer = str(proposal["proposer_ref"]); target = str(proposal["target_ref"]); direction = str(proposal.get("direction", "mutual")); terms = copy.deepcopy(proposal.get("terms", {}))
        treaty_ref = "treaty_" + hashlib.sha256(f"{proposal_ref}|{at}|accepted".encode()).hexdigest()[:18]
        duration_days = max(1, int(terms.get("duration_days", 365))); expires_at = str(CampaignTime.parse(at).add_seconds(duration_days * 86400))
        if kind in {"alliance", "nonaggression", "coalition"} and direction != "mutual":
            raise ValueError(f"{kind} must be mutual")
        equivalent = self._equivalent_active_treaty(
            kind=kind,
            direction=direction,
            proposer_ref=proposer,
            target_ref=target,
            terms=terms,
            at=at,
        )
        if isinstance(equivalent, Mapping):
            existing_ref = str(equivalent.get("treaty_ref", ""))
            existing = treaty_registry.get("records", {}).get(existing_ref)
            if not isinstance(existing, dict):
                raise ValueError("active treaty registry changed during activation")
            existing_terms = existing.setdefault("terms", {})
            current_expiry = existing_terms.get("expires_at") or existing.get("truce_until")
            should_extend = True
            if isinstance(current_expiry, str):
                try:
                    should_extend = CampaignTime.parse(expires_at) > CampaignTime.parse(current_expiry)
                except ValueError:
                    should_extend = True
            if should_extend:
                existing_terms["expires_at"] = expires_at
                existing_terms["duration_days"] = max(int(existing_terms.get("duration_days", 0) or 0), duration_days)
                if kind == "nonaggression":
                    existing_terms["nonaggression_until"] = expires_at
            existing["renewal_count"] = max(0, int(existing.get("renewal_count", 0) or 0)) + 1
            existing["last_renewed_at"] = at
            existing["last_renewal_proposal_ref"] = proposal_ref
            self.put("state/politics/treaties.json", treaty_registry)
            status_by_kind = {
                "alliance": "allied",
                "nonaggression": "nonaggression",
                "military_access": "access_agreement",
                "guarantee": "guaranteed",
                "client_state": "client_relation",
                "coalition": "coalition",
            }
            self._update_sovereign_diplomacy(proposer, target, status=status_by_kind.get(kind), tension_delta=0, at=at, treaty_ref=existing_ref)
            return existing_ref
        active_terms: dict[str, Any] = {"duration_days": duration_days, "expires_at": expires_at}; status = "neutral"
        if kind == "alliance":
            active_terms.update({"alliance": True, "mutual_defense": True}); status = "allied"
        elif kind == "nonaggression":
            active_terms.update({"nonaggression_until": expires_at, "ceasefire": True}); status = "nonaggression"
        elif kind == "military_access":
            grantor, beneficiary = self._asymmetric_treaty_roles(kind, direction, proposer, target); active_terms.update({"military_access_grantor_ref": grantor, "military_access_beneficiary_ref": beneficiary}); status = "access_agreement"
        elif kind == "guarantee":
            guarantor, protected = self._asymmetric_treaty_roles(kind, direction, proposer, target); active_terms.update({"guarantor_ref": guarantor, "protected_ref": protected}); status = "guaranteed"
        elif kind == "tribute":
            payer, payee = self._asymmetric_treaty_roles(kind, direction, proposer, target); active_terms.update({"payer_ref": payer, "payee_ref": payee, "amount_silver_per_month": max(1, int(terms.get("amount_silver", 1))), "arrears_silver": 0}); status = "tribute"
        elif kind == "client_state":
            client, patron = self._asymmetric_treaty_roles(kind, direction, proposer, target); active_terms.update({"client_ref": client, "patron_ref": patron, "mutual_nonaggression": True, "patron_defense_obligation": True}); status = "client_relation"
        elif kind == "reparations":
            payer, payee = self._asymmetric_treaty_roles(kind, direction, proposer, target); total = max(1, int(terms.get("amount_silver", 1))); active_terms.update({"payer_ref": payer, "payee_ref": payee, "reparations_total_silver": total, "reparations_remaining_silver": total, "installment_silver_per_month": max(1, int(math.ceil(total / max(1, min(24, duration_days // 30))))), "arrears_silver": 0}); status = "reparations"
        elif kind == "hostage_exchange":
            giver, receiver = self._asymmetric_treaty_roles(kind, direction, proposer, target); hostage = str(terms.get("hostage_person_ref", "")); counter = str(terms.get("counter_hostage_person_ref", "")); transfers=[]
            if hostage: transfers.append(self._apply_diplomatic_hostage(hostage, giver, receiver, treaty_ref, at))
            if counter: transfers.append(self._apply_diplomatic_hostage(counter, receiver, giver, treaty_ref, at))
            active_terms.update({"hostage_giver_ref": giver, "hostage_receiver_ref": receiver, "hostage_transfers": transfers}); status = "hostage_compact"
        elif kind == "marriage_alliance":
            if direction != "mutual": raise ValueError("marriage_alliance must be mutual")
            person_ref = str(terms.get("marriage_person_ref", "")); partner_ref = str(terms.get("marriage_partner_ref", ""))
            direct = self._person_under_sovereign_authority(person_ref, proposer) and self._person_under_sovereign_authority(partner_ref, target)
            reverse = self._person_under_sovereign_authority(person_ref, target) and self._person_under_sovereign_authority(partner_ref, proposer)
            if not (direct or reverse): raise PermissionError("marriage diplomacy requires one exact person under each sovereign's lawful authority")
            proposal_id = self._create_diplomatic_family_proposal(person_ref, partner_ref, treaty_ref, at); active_terms.update({"marriage_person_ref": person_ref, "marriage_partner_ref": partner_ref, "family_proposal_ref": proposal_id, "marriage_status": "pending_personal_consent"}); status = "marriage_negotiation"
        elif kind == "territorial_exchange":
            if direction != "mutual": raise ValueError("territorial_exchange must be mutual")
            active_terms.update({"offer_location_refs": [str(x) for x in terms.get("offer_location_refs", [])], "request_location_refs": [str(x) for x in terms.get("request_location_refs", [])]}); active_terms["territorial_changes"] = self._apply_treaty_territorial_exchange(proposer, target, active_terms, treaty_ref, at); status = "territorial_settlement"
        elif kind == "coalition":
            coalition_target = str(terms.get("coalition_target_ref", "")); existing = next((row for row in treaty_registry.get("records", {}).values() if isinstance(row, dict) and str(row.get("kind", "")) == "coalition" and str(row.get("status", "")) == "active" and str(row.get("terms", {}).get("coalition_target_ref", "")) == coalition_target and proposer in {str(x) for x in row.get("parties", [])}), None)
            if isinstance(existing, dict):
                if target not in existing.setdefault("parties", []): existing["parties"].append(target)
                existing["parties"] = sorted(set(str(x) for x in existing["parties"]))
                existing.setdefault("terms", {})["member_refs"] = list(existing["parties"]); existing["terms"]["mutual_defense_against_target"] = True
                existing.setdefault("accession_history", []).append({"at": at, "proposal_ref": proposal_ref, "new_member_ref": target})
                self.put("state/politics/treaties.json", treaty_registry)
                self._update_sovereign_diplomacy(proposer, target, status="coalition", tension_delta=-10, at=at, treaty_ref=str(existing.get("treaty_ref")))
                return str(existing.get("treaty_ref"))
            active_terms.update({"coalition_target_ref": coalition_target, "member_refs": sorted({proposer, target}), "mutual_defense_against_target": True}); status = "coalition"
        else:
            raise ValueError("unsupported diplomatic treaty kind")
        treaty = {"treaty_ref": treaty_ref, "kind": kind, "parties": sorted({proposer, target}), "status": "active", "signed_at": at, "terms": active_terms, "provenance": {"kind": "accepted_diplomatic_proposal", "proposal_ref": proposal_ref, "direction": direction}}
        treaty_registry.setdefault("records", {})[treaty_ref] = treaty; self.put("state/politics/treaties.json", treaty_registry)
        self._update_sovereign_diplomacy(proposer, target, status=status, tension_delta=-15 if kind in {"alliance", "nonaggression", "client_state", "marriage_alliance", "coalition"} else -5, at=at, treaty_ref=treaty_ref)
        return treaty_ref

    def _evaluate_diplomatic_proposal(self, proposal: Mapping[str, Any], target_ref: str, target_doc: Mapping[str, Any], at: str) -> tuple[bool, dict[str, Any]]:
        proposer_ref = str(proposal.get("proposer_ref", "")); kind = str(proposal.get("kind", "")); direction = str(proposal.get("direction", "mutual"))
        diplomacy = target_doc.get("diplomacy", {}) if isinstance(target_doc.get("diplomacy"), Mapping) else {}
        relation = diplomacy.get(proposer_ref, {}) if isinstance(diplomacy, Mapping) else {}
        tension = max(0, min(100, int(_fixed(relation.get("tension", 0), 0)))) if isinstance(relation, Mapping) else 0
        rel_status = str(relation.get("status", "")) if isinstance(relation, Mapping) else ""
        threat = max((int(v.get("severity", 0)) for v in target_doc.get("known_threats", {}).values() if isinstance(v, Mapping)), default=0) if isinstance(target_doc.get("known_threats"), Mapping) else 0
        proposer_power = self._sovereign_military_strength(proposer_ref); target_power = self._sovereign_military_strength(target_ref, target_doc)
        accept = False
        if kind == "nonaggression": accept = tension <= 65 and rel_status != "war"
        elif kind == "alliance": accept = tension <= 25 and (rel_status in {"friendly", "allied", "cooperative"} or threat >= 40)
        elif kind == "military_access": accept = tension <= 30
        elif kind == "guarantee": accept = tension <= 50
        elif kind == "tribute":
            accept = tension < 80 if direction == "proposer_to_target" else (proposer_power >= max(1, int(target_power * 1.5)) and threat >= 35)
        elif kind == "client_state":
            if direction == "proposer_to_target": accept = target_power >= max(1, int(proposer_power * 1.2)) and tension <= 60
            else: accept = proposer_power >= max(1, int(target_power * 1.6)) and threat >= 55 and tension <= 70
        elif kind == "reparations":
            payer, _payee = self._asymmetric_treaty_roles(kind, direction, proposer_ref, target_ref)
            accept = tension <= 75 if payer == proposer_ref else proposer_power >= max(1, int(target_power * 1.35)) and threat >= 35
        elif kind == "hostage_exchange":
            accept = tension <= 65 and (rel_status in {"armed_peace", "nonaggression", "friendly", "cooperative"} or threat >= 35)
        elif kind == "marriage_alliance":
            accept = tension <= 30 and rel_status != "war"
        elif kind == "territorial_exchange":
            offer = proposal.get("terms", {}).get("offer_location_refs", []) if isinstance(proposal.get("terms"), Mapping) else []
            request = proposal.get("terms", {}).get("request_location_refs", []) if isinstance(proposal.get("terms"), Mapping) else []
            accept = bool(offer and request) and tension <= 55 and rel_status != "war"
        elif kind == "coalition":
            coalition_target = str(proposal.get("terms", {}).get("coalition_target_ref", "")) if isinstance(proposal.get("terms"), Mapping) else ""
            target_threat_match = any(isinstance(v, Mapping) and str(v.get("source_ref", v.get("actor_ref", ""))) == coalition_target and int(v.get("severity", 0)) >= 45 for v in target_doc.get("known_threats", {}).values()) if isinstance(target_doc.get("known_threats"), Mapping) else False
            accept = tension <= 35 and target_threat_match
        return accept, {"tension": tension, "relationship_status": rel_status, "target_threat_severity": threat, "proposer_military_strength": proposer_power, "target_military_strength": target_power, "rule": "target sovereign evaluates delivered proposal from saved diplomacy, threats and relative material strength"}

    def _create_diplomatic_proposal(self, proposer_ref: str, target_ref: str, kind: str, direction: str, at: str, *, terms: Mapping[str, Any] | None = None, provenance: Mapping[str, Any] | None = None) -> dict[str, Any]:
        proposer_path, proposer = self._sovereign_owner(proposer_ref); target_path, target = self._sovereign_owner(target_ref)
        origin = self._sovereign_seat(proposer_ref, proposer); destination = self._sovereign_seat(target_ref, target)
        if not origin or not destination:
            raise ValueError("formal diplomacy requires exact sovereign communication origins")
        hours = self._route_travel_hours(origin, destination)
        arrives = str(CampaignTime.parse(at).add_seconds(max(1, hours) * 3600)); expires = str(CampaignTime.parse(arrives).add_seconds(90 * 86400))
        proposal_ref = "diplomatic_proposal_" + hashlib.sha256(f"{proposer_ref}|{target_ref}|{kind}|{direction}|{at}".encode()).hexdigest()[:18]
        proposal_path = f"state/politics/diplomatic-proposals/{proposal_ref}.json"
        proposal = {"schema": "sword-diplomatic-proposal", "owner_id": proposal_ref, "proposal_ref": proposal_ref, "proposer_ref": proposer_ref, "target_ref": target_ref, "kind": kind, "direction": direction, "status": "in_transit", "proposed_at": at, "arrives_at": arrives, "expires_at": expires, "terms": copy.deepcopy(dict(terms or {})), "provenance": {"kind": "sovereign_diplomatic_proposal", "origin_ref": origin, "destination_ref": destination, "travel_hours": hours, **copy.deepcopy(dict(provenance or {}))}}
        self.put(proposal_path, proposal); self._register_owner(proposal_ref, proposal_path)
        target.setdefault("diplomatic_route_refs", []).append(proposal_ref); target["diplomatic_route_refs"] = target["diplomatic_route_refs"][-64:]; self.put(target_path, target)
        proposer.setdefault("outgoing_diplomatic_proposal_refs", []).append(proposal_ref); proposer["outgoing_diplomatic_proposal_refs"] = proposer["outgoing_diplomatic_proposal_refs"][-64:]; self.put(proposer_path, proposer)
        return proposal

    def _generate_npc_diplomatic_initiative(self, sovereign_ref: str, at: str) -> dict[str, Any] | None:
        """Let NPC sovereigns originate treaty offers from exact strategic conditions."""
        path, doc = self._sovereign_owner(sovereign_ref)
        if sovereign_ref.startswith("polity_") and str(doc.get("sovereign_house_ref", "")) == "house_tang":
            return None
        # One unresolved outbound offer at a time keeps diplomacy bounded without
        # imposing a fictional lifetime quota.
        for proposal_ref in [str(x) for x in doc.get("outgoing_diplomatic_proposal_refs", []) if isinstance(x, str)]:
            try: proposal = self.read(self.owner_path(proposal_ref))
            except (KeyError, ValueError, FileNotFoundError): continue
            if str(proposal.get("status", "")) in {"in_transit", "pending_response"}:
                return None
        own_threats = doc.get("known_threats", {}) if isinstance(doc.get("known_threats"), Mapping) else {}
        own_threat = max((max(0, int(_fixed(x.get("severity", 0), 0))) for x in own_threats.values() if isinstance(x, Mapping)), default=0)
        if self._autonomous_diplomatic_initiative_cooldown_seconds(doc, at, threat_severity=own_threat) > 0:
            return None
        side = sovereign_ref.removeprefix("state_") if sovereign_ref.startswith("state_") else sovereign_ref
        candidate_refs: set[str] = set()
        for cfg in self._interstate_theater_config(self.read("game/data/world/autonomous-theaters.json"), at=at).get("theaters", []):
            sides = [str(x) for x in cfg.get("sides", [])] if isinstance(cfg, Mapping) else []
            if side not in sides: continue
            other = next((x for x in sides if x != side), "")
            if other: candidate_refs.add(other if other.startswith("polity_") else f"state_{other}")
        for ref in doc.get("diplomacy", {}) if isinstance(doc.get("diplomacy"), Mapping) else {}:
            text = str(ref); candidate_refs.add(text if text.startswith(("state_", "polity_")) else f"state_{text}")
        if not candidate_refs: return None
        own_power = max(1, self._sovereign_military_strength(sovereign_ref, doc))
        # Protected or emergent shared threats may establish lawful diplomatic
        # contact candidates even when no bilateral treaty row existed beforehand.
        # The contact is not a treaty and grants no acceptance; it merely allows the
        # existing proposal/response machinery to do its job.
        for threat in own_threats.values():
            if not isinstance(threat, Mapping):
                continue
            contacts = threat.get("coordination_candidate_refs", [])
            if isinstance(contacts, Sequence) and not isinstance(contacts, (str, bytes, bytearray)):
                for ref in contacts:
                    if isinstance(ref, str) and ref.startswith(("state_", "polity_")) and ref != sovereign_ref:
                        candidate_refs.add(ref)
        choices: list[tuple[float, str, str, str, dict[str, Any]]] = []
        for target_ref in sorted(candidate_refs):
            if target_ref == sovereign_ref: continue
            try: _tp, target = self._sovereign_owner(target_ref)
            except (KeyError, ValueError, FileNotFoundError): continue
            relation = doc.get("diplomacy", {}).get(target_ref, {}) if isinstance(doc.get("diplomacy"), Mapping) else {}
            tension = max(0, min(100, int(_fixed(relation.get("tension", 0), 0)))) if isinstance(relation, Mapping) else 0
            status = str(relation.get("status", "")) if isinstance(relation, Mapping) else ""
            if status == "war": continue
            active_pair_treaties = self._active_treaties_between(sovereign_ref, target_ref, at)
            active_pair_kinds = {str(row.get("kind", "")) for row in active_pair_treaties}
            target_power = max(1, self._sovereign_military_strength(target_ref, target))
            ratio = own_power / target_power
            target_threats = target.get("known_threats", {}) if isinstance(target.get("known_threats"), Mapping) else {}
            target_threat = max((max(0, int(_fixed(x.get("severity", 0), 0))) for x in target_threats.values() if isinstance(x, Mapping)), default=0)
            if tension <= 25 and own_threat >= 45 and "alliance" not in active_pair_kinds and "client_state" not in active_pair_kinds:
                choices.append((70 + own_threat * 0.2, target_ref, "alliance", "mutual", {"duration_days": 720}))
            if 25 <= tension <= 65 and not active_pair_kinds.intersection({"nonaggression", "alliance", "client_state"}):
                choices.append((55 + (65 - tension) * 0.2, target_ref, "nonaggression", "mutual", {"duration_days": 365}))
            client_terms = {"duration_days": 1080}
            if ratio >= 1.8 and target_threat >= 45 and tension <= 60 and self._equivalent_active_treaty(kind="client_state", direction="target_to_proposer", proposer_ref=sovereign_ref, target_ref=target_ref, terms=client_terms, at=at) is None:
                choices.append((62 + min(25, (ratio - 1.8) * 10) + target_threat * 0.1, target_ref, "client_state", "target_to_proposer", client_terms))
            if ratio >= 1.5 and tension <= 50 and target_threat >= 35:
                guarantee_terms = {"duration_days": 720}
                redundant_defense = "alliance" in active_pair_kinds or any(
                    str(row.get("kind", "")) == "client_state" and str((row.get("terms", {}) if isinstance(row.get("terms"), Mapping) else {}).get("patron_ref", "")) == sovereign_ref and str((row.get("terms", {}) if isinstance(row.get("terms"), Mapping) else {}).get("client_ref", "")) == target_ref
                    for row in active_pair_treaties
                )
                if not redundant_defense and self._equivalent_active_treaty(kind="guarantee", direction="proposer_to_target", proposer_ref=sovereign_ref, target_ref=target_ref, terms=guarantee_terms, at=at) is None:
                    choices.append((58 + target_threat * 0.12, target_ref, "guarantee", "proposer_to_target", guarantee_terms))
            if tension <= 30 and own_threat >= 55:
                access_terms = {"duration_days": 365}
                if self._equivalent_active_treaty(kind="military_access", direction="target_to_proposer", proposer_ref=sovereign_ref, target_ref=target_ref, terms=access_terms, at=at) is None:
                    choices.append((57 + own_threat * 0.1, target_ref, "military_access", "target_to_proposer", access_terms))
            own_sources = {str(v.get("source_ref", v.get("actor_ref", ""))) for v in own_threats.values() if isinstance(v, Mapping) and int(_fixed(v.get("severity", 0), 0)) >= 55}
            target_sources = {str(v.get("source_ref", v.get("actor_ref", ""))) for v in target_threats.values() if isinstance(v, Mapping) and int(_fixed(v.get("severity", 0), 0)) >= 55}
            shared = sorted(x for x in own_sources.intersection(target_sources) if x and x not in {sovereign_ref, target_ref})
            if shared and tension <= 40:
                coalition_terms = {"duration_days": 720, "coalition_target_ref": shared[0]}
                if self._equivalent_active_treaty(kind="coalition", direction="mutual", proposer_ref=sovereign_ref, target_ref=target_ref, terms=coalition_terms, at=at) is None:
                    choices.append((72 + min(18, min(own_threat, target_threat) * 0.12), target_ref, "coalition", "mutual", coalition_terms))
        if not choices: return None
        # A verified shared high-severity external threat is stronger evidence
        # for multilateral coordination than a generic bilateral friendship
        # offer.  Prefer the coalition route when one is lawfully available;
        # otherwise use the ordinary scored sovereign initiative ordering.
        coalition_choices = [row for row in choices if row[2] == "coalition"]
        pool = coalition_choices or choices
        score, target_ref, kind, direction, terms = sorted(pool, key=lambda row: (-row[0], row[1], row[2]))[0]
        # Stable initiative threshold prevents diplomatic spam while allowing urgent
        # threat-driven offers to wake immediately on the monthly sovereign close.
        if score < 60: return None
        proposal = self._create_diplomatic_proposal(sovereign_ref, target_ref, kind, direction, at, terms=terms, provenance={"kind": "npc_sovereign_initiative", "decision_score": round(score, 3), "basis": "saved diplomacy, exact threats, relative military strength and sovereign autonomy"})
        return proposal

    def _settle_diplomatic_routes(self, sovereign_ref: str, sovereign_doc: dict[str, Any], at: str) -> None:
        routes = sovereign_doc.setdefault("diplomatic_route_refs", [])
        if not isinstance(routes, list):
            raise ValueError("sovereign diplomatic routes are invalid")
        now = CampaignTime.parse(at); retained: list[str] = []
        for proposal_ref in [str(x) for x in routes if isinstance(x, str)]:
            try:
                pp = self.owner_path(proposal_ref); proposal = copy.deepcopy(self.read(pp))
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if str(proposal.get("target_ref", "")) != sovereign_ref:
                continue
            if str(proposal.get("status", "")) in {"accepted", "rejected", "withdrawn", "expired"}:
                continue
            if CampaignTime.parse(str(proposal.get("expires_at", proposal.get("arrives_at")))) <= now:
                proposal["status"] = "expired"; proposal["responded_at"] = at; self.put(pp, proposal); continue
            if CampaignTime.parse(str(proposal.get("arrives_at"))) > now:
                retained.append(proposal_ref); continue
            proposal["status"] = "pending_response"
            # Tang Wei's sovereign commitments remain player-owned decisions.  An
            # incoming proposal may arrive and become visible, but autonomy may not
            # accept/reject it on behalf of the player polity.
            if sovereign_ref.startswith("polity_") and str(sovereign_doc.get("sovereign_house_ref", "")) == "house_tang":
                proposal["response_basis"] = {
                    "kind": "pending_player_sovereign_decision",
                    "target_ref": sovereign_ref,
                    "arrived_at": at,
                }
                self.put(pp, proposal)
                retained.append(proposal_ref)
                continue
            accepted, basis = self._evaluate_diplomatic_proposal(proposal, sovereign_ref, sovereign_doc, at)
            proposal["response_basis"] = basis; proposal["responded_at"] = at
            if accepted:
                proposal["status"] = "accepted"; proposal["treaty_ref"] = self._activate_diplomatic_treaty(proposal, at)
            else:
                proposal["status"] = "rejected"
                self._update_sovereign_diplomacy(str(proposal.get("proposer_ref")), sovereign_ref, tension_delta=3, at=at)
            self.put(pp, proposal)
        target_path, current_target = self._sovereign_owner(sovereign_ref)
        current_target["diplomatic_route_refs"] = retained[-64:]
        self.put(target_path, current_target)

    def _settle_treaty_obligations(self, sovereign_ref: str, at: str, occurrences: int) -> None:
        treaties = copy.deepcopy(self.read("state/politics/treaties.json")); changed = False; now = CampaignTime.parse(at)
        for treaty in treaties.get("records", {}).values():
            if not isinstance(treaty, dict) or str(treaty.get("status", "")) != "active": continue
            terms = treaty.get("terms", {}) if isinstance(treaty.get("terms"), Mapping) else {}
            expires = terms.get("expires_at") or treaty.get("truce_until")
            if isinstance(expires, str):
                try:
                    if CampaignTime.parse(expires) <= now:
                        treaty["status"] = "expired"; treaty["expired_at"] = at; changed = True; continue
                except ValueError: pass
            payer = str(terms.get("payer_ref", ""))
            if payer != sovereign_ref: continue
            payee = str(terms.get("payee_ref", ""))
            if str(treaty.get("kind", "")) == "reparations":
                remaining = max(0, int(terms.get("reparations_remaining_silver", 0)))
                if remaining <= 0: continue
                amount = min(remaining, max(1, int(terms.get("installment_silver_per_month", remaining))) * max(1, int(occurrences)))
            else:
                monthly = int(terms.get("amount_silver_per_month", 0))
                if monthly <= 0: continue
                amount = max(1, monthly) * max(1, int(occurrences))
            payer_path, payer_doc, payer_key = self._sovereign_treasury(payer); payee_path, payee_doc, payee_key = self._sovereign_treasury(payee)
            paid = min(amount, max(0, int(payer_doc.get(payer_key, 0)))); payer_doc[payer_key] = int(payer_doc.get(payer_key, 0)) - paid; payee_doc[payee_key] = int(payee_doc.get(payee_key, 0)) + paid; self.put(payer_path, payer_doc); self.put(payee_path, payee_doc)
            terms["arrears_silver"] = int(terms.get("arrears_silver", 0)) + max(0, amount - paid); terms["last_payment_at"] = at; terms["last_payment_silver"] = paid
            if str(treaty.get("kind", "")) == "reparations": terms["reparations_remaining_silver"] = max(0, int(terms.get("reparations_remaining_silver", 0)) - paid)
            treaty["terms"] = dict(terms); changed = True
            if paid < amount: self._update_sovereign_diplomacy(payer, payee, tension_delta=5, at=at, treaty_ref=str(treaty.get("treaty_ref", "")))
        if changed: self.put("state/politics/treaties.json", treaties)

    def _appointment_bloc_evidence(self, person_ref: str) -> dict[str, Any]:
        """Return only exact saved relationship evidence relevant to an appointment.

        This is deliberately not a popularity inference. No edge means no bloc.
        """
        rel = self.read("state/relationships.json")
        evidence: list[dict[str, Any]] = []
        for edge in rel.get("edges", []) if isinstance(rel, Mapping) else []:
            if not isinstance(edge, Mapping):
                continue
            src = str(edge.get("source_ref", "")); dst = str(edge.get("target_ref", ""))
            if person_ref not in {src, dst}:
                continue
            dims = edge.get("dimensions", {}) if isinstance(edge.get("dimensions"), Mapping) else {}
            value = int(edge.get("value", 0) or 0)
            respect = int(dims.get("respect", 0) or 0); trust = int(dims.get("trust", 0) or 0)
            if max(value, respect, trust) < 50:
                continue
            supporter = src if dst == person_ref else dst
            evidence.append({
                "evidence_ref": str(edge.get("edge_ref", "")),
                "supporter_ref": supporter,
                "kind": str(edge.get("kind", "relationship")),
                "value": value,
                "respect": respect,
                "trust": trust,
                "institutional_union_ref": edge.get("institutional_union_ref"),
            })
        evidence.sort(key=lambda row: (-max(row["value"], row["respect"], row["trust"]), row["evidence_ref"]))
        return {
            "person_ref": person_ref,
            "evidence_refs": [row["evidence_ref"] for row in evidence if row["evidence_ref"]],
            "supporters": evidence,
            "rule": "appointment support is derived only from exact saved relationship edges; absence of saved evidence creates no bloc",
        }

    def _defect_client_state(self, polity_ref: str, treaty_ref: str, at: str) -> dict[str, Any]:
        treaties = copy.deepcopy(self.read("state/politics/treaties.json"))
        treaty = treaties.get("records", {}).get(treaty_ref)
        if not isinstance(treaty, dict) or str(treaty.get("status", "")) != "active" or str(treaty.get("kind", "")) != "client_state":
            raise ValueError("client defection requires one exact active client-state treaty")
        terms = treaty.get("terms", {}) if isinstance(treaty.get("terms"), Mapping) else {}
        if str(terms.get("client_ref", "")) != polity_ref:
            raise PermissionError("only the exact client polity may defect from its client-state treaty")
        patron_ref = str(terms.get("patron_ref", ""))
        treaty["status"] = "broken"
        treaty["broken_at"] = at
        treaty["broken_by_ref"] = polity_ref
        treaty["break_kind"] = "client_defection"
        treaty.setdefault("history", []).append({"at": at, "event": "client_defection", "client_ref": polity_ref, "patron_ref": patron_ref})
        treaty["history"] = treaty["history"][-32:]
        self.put("state/politics/treaties.json", treaties)
        if patron_ref:
            self._update_sovereign_diplomacy(polity_ref, patron_ref, status="hostile", tension_delta=45, at=at, treaty_ref=treaty_ref)
        return {"treaty_ref": treaty_ref, "client_ref": polity_ref, "patron_ref": patron_ref, "status": "broken", "break_kind": "client_defection"}

    def _dispatch_polity_action(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        polity_ref = str(payload["polity_ref"]); polity_path = self.owner_path(polity_ref); polity = copy.deepcopy(self.read(polity_path)); action = str(payload["action"]); now = str(self._world_time()); result: dict[str, Any] = {"polity_ref": polity_ref, "action": action}
        if action == "set_strategic_goal":
            goal = str(payload["goal"]); polity.setdefault("strategic_goals", []).append(goal); polity["strategic_goals"] = polity["strategic_goals"][-16:]; result["goal"] = goal
        elif action == "set_mobilization_policy":
            value = str(payload["policy_value"]); polity["mobilization_policy"] = {"value": value, "set_at": now, "set_by": command.actor_id}; result["policy_value"] = value
        elif action == "set_occupation_policy":
            location_ref = str(payload["location_ref"]); territory = copy.deepcopy(self.read("state/territory/control.json")); site = territory.get("sites", {}).get(location_ref)
            if not isinstance(site, dict) or str(site.get("controller", "")) != polity_ref: raise PermissionError("polity may set occupation policy only in territory it currently controls")
            gov = site.get("governance") if isinstance(site.get("governance"), dict) else None
            if gov is None: raise ValueError("location has no active occupation/governance authority")
            key = str(payload["policy_key"]); value = str(payload["policy_value"]); gov.setdefault("occupation_policy", {})[key] = {"value": value, "set_at": now, "set_by": command.actor_id}; self.put("state/territory/control.json", territory); result.update({"location_ref": location_ref, "policy_key": key, "policy_value": value})
        elif action == "appoint_governor":
            location_ref = str(payload["location_ref"]); person_ref = str(payload["person_ref"]); territory = self.read("state/territory/control.json"); site = territory.get("sites", {}).get(location_ref) if isinstance(territory, Mapping) else None
            if not isinstance(site, Mapping) or str(site.get("controller", "")) != polity_ref: raise PermissionError("polity may appoint governors only for territory it controls")
            person_path, person = self._exact_person(person_ref); person = copy.deepcopy(person); appointment = {"office": "governor", "person_ref": person_ref, "polity_ref": polity_ref, "location_ref": location_ref, "appointed_at": now, "grantor_ref": command.actor_id}; person.setdefault("career_state", {}).setdefault("appointments", []).append(appointment); person["career_state"]["appointments"] = person["career_state"]["appointments"][-32:]; self.put(person_path, person); polity.setdefault("governors", {})[location_ref] = appointment; result.update({"location_ref": location_ref, "person_ref": person_ref})
        elif action == "authorize_war":
            target_ref = str(payload["target_ref"]); location_ref = str(payload["location_ref"]); goal = str(payload["war_goal"]); intents = polity.setdefault("war_intents", []); intent_ref = "war_intent_" + hashlib.sha256(f"{polity_ref}|{target_ref}|{location_ref}|{now}|{goal}".encode()).hexdigest()[:16]; intents.append({"intent_ref": intent_ref, "target_ref": target_ref, "location_ref": location_ref, "kind": "territorial_control", "objective": goal, "status": "authorized", "authorized_at": now, "authorized_by": command.actor_id}); polity["war_intents"] = intents[-24:]; result.update({"war_intent_ref": intent_ref, "target_ref": target_ref, "location_ref": location_ref})
        elif action == "recognize_polity":
            target_ref = str(payload["target_ref"]); recognized = self._apply_polity_recognition(polity_ref, target_ref, now); result.update({"target_ref": target_ref, "target_status": recognized.get("status"), "target_recognition_status": recognized.get("recognition_status"), "target_recognized_by": recognized.get("recognized_by", [])})
        elif action == "propose_treaty":
            target_ref = str(payload["target_ref"]); kind = str(payload["treaty_kind"]); direction = str(payload.get("direction", "mutual")); duration = int(payload.get("duration_days", 365))
            terms: dict[str, Any] = {"duration_days": duration}
            if kind in {"tribute", "reparations"}: terms["amount_silver"] = int(payload.get("amount_silver", 0))
            if kind == "hostage_exchange":
                if payload.get("hostage_person_ref"): terms["hostage_person_ref"] = str(payload["hostage_person_ref"])
                if payload.get("counter_hostage_person_ref"): terms["counter_hostage_person_ref"] = str(payload["counter_hostage_person_ref"])
            if kind == "marriage_alliance": terms.update({"marriage_person_ref": str(payload["marriage_person_ref"]), "marriage_partner_ref": str(payload["marriage_partner_ref"])})
            if kind == "territorial_exchange": terms.update({"offer_location_refs": [str(x) for x in payload.get("offer_location_refs", [])], "request_location_refs": [str(x) for x in payload.get("request_location_refs", [])]})
            if kind == "coalition": terms["coalition_target_ref"] = str(payload["coalition_target_ref"])
            proposal = self._create_diplomatic_proposal(polity_ref, target_ref, kind, direction, now, terms=terms, provenance={"kind": "player_sovereign_proposal", "actor_ref": command.actor_id})
            polity = copy.deepcopy(self.read(polity_path)); result.update({"proposal_ref": proposal["proposal_ref"], "target_ref": target_ref, "arrives_at": proposal["arrives_at"], "treaty_kind": kind})
        elif action in {"accept_treaty", "reject_treaty"}:
            proposal_ref = str(payload["proposal_ref"]); proposal_path = self.owner_path(proposal_ref); proposal = copy.deepcopy(self.read(proposal_path))
            # Persist any local polity changes accumulated above before helper
            # functions update bilateral diplomacy through fresh exact reads.
            self.put(polity_path, polity)
            proposal["responded_at"] = now
            proposal["response_basis"] = {"kind": "player_sovereign_decision", "actor_ref": command.actor_id, "target_ref": polity_ref}
            if action == "accept_treaty":
                proposal["status"] = "accepted"; proposal["treaty_ref"] = self._activate_diplomatic_treaty(proposal, now); result["treaty_ref"] = proposal["treaty_ref"]
            else:
                proposal["status"] = "rejected"; self._update_sovereign_diplomacy(str(proposal.get("proposer_ref")), polity_ref, tension_delta=3, at=now); result["proposal_ref"] = proposal_ref
            self.put(proposal_path, proposal)
            polity = copy.deepcopy(self.read(polity_path)); routes = [str(x) for x in polity.get("diplomatic_route_refs", []) if isinstance(x, str) and str(x) != proposal_ref]; polity["diplomatic_route_refs"] = routes[-64:]
            result.update({"proposal_ref": proposal_ref, "proposal_status": proposal["status"], "proposer_ref": str(proposal.get("proposer_ref", "")), "treaty_kind": str(proposal.get("kind", ""))})
        elif action == "defect_client_state":
            treaty_ref = str(payload["treaty_ref"])
            self.put(polity_path, polity)
            result.update(self._defect_client_state(polity_ref, treaty_ref, now))
            polity = copy.deepcopy(self.read(polity_path))
            polity.setdefault("client_defection_history", []).append({"at": now, "treaty_ref": treaty_ref, "patron_ref": result.get("patron_ref")})
            polity["client_defection_history"] = polity["client_defection_history"][-32:]
        elif action == "break_treaty":
            treaty_ref = str(payload["treaty_ref"]); treaties = copy.deepcopy(self.read("state/politics/treaties.json")); treaty = treaties.get("records", {}).get(treaty_ref)
            if not isinstance(treaty, dict) or str(treaty.get("status", "")) != "active": raise ValueError("treaty is not active")
            if polity_ref not in {str(x) for x in treaty.get("parties", [])}: raise PermissionError("polity is not a party to this treaty")
            treaty["status"] = "broken"; treaty["broken_at"] = now; treaty["broken_by_ref"] = polity_ref; self.put("state/politics/treaties.json", treaties); self.put(polity_path, polity); other = next((str(x) for x in treaty.get("parties", []) if str(x) != polity_ref), None)
            if other: self._update_sovereign_diplomacy(polity_ref, other, status="hostile", tension_delta=35, at=now, treaty_ref=treaty_ref); polity = copy.deepcopy(self.read(polity_path))
            result["treaty_ref"] = treaty_ref
        elif action == "found_market":
            location_ref = str(payload["location_ref"]); investment = int(payload["investment_silver"]); market_name = str(payload.get("market_name", "Sovereign Market"))
            territory = self.read("state/territory/control.json"); site = territory.get("sites", {}).get(location_ref) if isinstance(territory, Mapping) else None
            if not isinstance(site, Mapping) or str(site.get("controller", "")) != polity_ref:
                raise PermissionError("polity may found a market only in territory it currently controls")
            owners = self.read("state/index/owner-index.json").get("owners", {})
            for ref, path in owners.items():
                if not str(ref).startswith("market_") or not isinstance(path, str): continue
                existing = self.read_optional(path)
                if isinstance(existing, Mapping) and str(existing.get("location_ref", "")) == location_ref:
                    raise ValueError("location already has an exact active market")
            treasury_ref = str(polity.get("treasury_ref", "")); treasury_path = self.owner_path(treasury_ref); treasury = copy.deepcopy(self.read(treasury_path)); funds_key, funds = self._funds_value(treasury)
            if funds < investment: raise ValueError("polity treasury cannot fund the market investment")
            treasury[funds_key] = funds - investment
            token = hashlib.sha256(f"{polity_ref}|{location_ref}|{now}|{market_name}".encode()).hexdigest()[:16]
            market_ref = f"market_{token}"; market_path = f"state/markets/{token}.json"
            normal = {str(k): max(0, int(v)) for k, v in self._civil_rules().get("market_normal_stock", {}).items()}
            market = {"schema": "sword-market", "owner_id": market_ref, "location_ref": location_ref, "name": market_name, "sovereign_ref": polity_ref, "state": self._native_site_state(location_ref), "prices_ref": "game/data/mechanics/economy.json", "normal_stock": normal, "stock": {k: 0 for k in normal}, "capital_silver": investment, "founded_at": now, "founded_by_ref": command.actor_id, "demand_factor": 1.0, "insecurity_hoarding_factor": 1.0}
            native_state = self._native_site_state(location_ref)
            if native_state:
                ep, eco = self._private_economy(native_state); site_ref, region = self._local_economy_region(native_state, eco, location_ref)
                market["private_economy_ref"] = f"private_economy_{native_state}"; market["regional_source_ref"] = site_ref
                prices = self.read("game/data/mechanics/economy.json").get("prices_silver", {})
                for key, target in normal.items():
                    available = max(0, int(region.setdefault("finished_goods", {}).get(key, 0))); unit = max(0.0, _fixed(prices.get(key, 0), 0))
                    affordable = int(market["capital_silver"] // unit) if unit > 0 else available
                    take = min(target, available, affordable)
                    if take <= 0: continue
                    cost = int(math.ceil(take * unit)); region["finished_goods"][key] = available - take; region["cash_silver"] = int(region.get("cash_silver", 0)) + cost; market["capital_silver"] -= cost; market["stock"][key] = take
                self._sync_local_economy_aggregate(eco)
                self._write_private_economy(ep, eco)
            self.put(treasury_path, treasury); self.put(market_path, market); self._register_owner(market_ref, market_path)
            refs = polity.setdefault("market_access_refs", []);
            if market_ref not in refs: refs.append(market_ref)
            polity["market_access_refs"] = refs[-64:]
            result.update({"market_ref": market_ref, "location_ref": location_ref, "investment_silver": investment, "market_name": market_name})
        elif action == "open_court_case":
            kind = str(payload["case_kind"]); subject_ref = str(payload["subject_ref"]); token = hashlib.sha256(f"{polity_ref}|{kind}|{subject_ref}|{now}".encode()).hexdigest()[:18]; case_ref = f"court_case_{token}"; case_path = f"state/politics/court-cases/{token}.json"
            case = {"schema": "sword-court-case", "owner_id": case_ref, "case_ref": case_ref, "polity_ref": polity_ref, "kind": kind, "subject_ref": subject_ref, "status": "open", "stage": "filing", "opened_at": now, "next_review_at": str(CampaignTime.parse(now).add_seconds(30 * 86400)), "evidence_refs": [], "history": [{"at": now, "event": "case_opened", "opened_by_ref": command.actor_id}]}
            self.put(case_path, case); self._register_owner(case_ref, case_path); refs = polity.setdefault("court_case_refs", []); refs.append(case_ref); polity["court_case_refs"] = refs[-128:]; result.update({"case_ref": case_ref, "case_kind": kind, "subject_ref": subject_ref})
        elif action == "decide_court_case":
            case_ref = str(payload["case_ref"]); case_path = self.owner_path(case_ref); case = copy.deepcopy(self.read(case_path))
            if str(case.get("polity_ref", "")) != polity_ref: raise PermissionError("polity may decide only its own court cases")
            if str(case.get("status", "")) not in {"decision_required", "hearing", "remanded"}: raise ValueError("court case is not at a lawful decision stage")
            decision = str(payload["policy_value"]); case["decision"] = {"value": decision, "at": now, "decided_by_ref": command.actor_id}; case.setdefault("history", []).append({"at": now, "event": "sovereign_decision", "decision": decision, "decided_by_ref": command.actor_id})
            if decision == "remand": case["status"] = "remanded"; case["stage"] = "additional_investigation"; case["next_review_at"] = str(CampaignTime.parse(now).add_seconds(30 * 86400))
            else: case["status"] = "dismissed" if decision == "dismiss" else "decided"; case["stage"] = "closed"; case.pop("next_review_at", None)
            case["history"] = case["history"][-64:]; self.put(case_path, case); result.update({"case_ref": case_ref, "decision": decision, "case_status": case["status"]})
        elif action == "issue_decree":
            decree_text = str(payload["decree_text"]); decree_ref = "decree_" + hashlib.sha256(f"{polity_ref}|{now}|{decree_text}".encode()).hexdigest()[:18]; decrees = polity.setdefault("decrees", []); decrees.append({"decree_ref": decree_ref, "issued_at": now, "issued_by_ref": command.actor_id, "text": decree_text, "status": "in_force"}); polity["decrees"] = decrees[-128:]; result["decree_ref"] = decree_ref
        elif action == "appoint_office":
            person_ref = str(payload["person_ref"]); office_key = str(payload["office_key"]); person_path, person = self._exact_person(person_ref); person = copy.deepcopy(person)
            bloc = self._appointment_bloc_evidence(person_ref)
            appointment = {"office": office_key, "polity_ref": polity_ref, "appointed_at": now, "grantor_ref": command.actor_id, "appointment_bloc_evidence": bloc}
            polity.setdefault("officeholders", {})[office_key] = {"person_ref": person_ref, **appointment}
            polity.setdefault("appointment_history", []).append({"person_ref": person_ref, **appointment}); polity["appointment_history"] = polity["appointment_history"][-128:]
            person.setdefault("career_state", {}).setdefault("appointments", []).append({"person_ref": person_ref, **appointment}); person["career_state"]["appointments"] = person["career_state"]["appointments"][-32:]
            self.put(person_path, person); result.update({"person_ref": person_ref, "office_key": office_key, "appointment_bloc_evidence": bloc})
        self.put(polity_path, polity); world_time, metrics = self._advance_seconds(2 * 3600); self._write_meta(command, world_time); return self._result(world_time=world_time, **result, **metrics)

    def _dispatch_market(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        t = command.command_type
        state, marketp, market, location_ref = self._market_at_player_location()
        key = str(payload["item_key"]); qty = int(payload.get("quantity", 1))
        if key not in market.get("stock", {}):
            raise ValueError("unknown market item")
        unit, factors = self._market_unit_price(market, key)
        total = max(1, int(round(unit * qty)))
        item_id = self._market_item_id(key); self._item_record(item_id)
        pack_size = 20 if key in {"arrows_20", "bolts_20"} else 1; exact_qty = qty * pack_size
        walletp = "state/economy/player-wallet.json"; wallet = copy.deepcopy(self.read(walletp)); invp, inv = self._player_inventory(); ep, eco = self._private_economy(state)
        regional_source_ref, regional = self._local_economy_region(state, eco, location_ref)
        if t == "market_purchase":
            if int(market["stock"].get(key, 0)) < qty: raise ValueError("insufficient market stock")
            if int(wallet.get("silver", 0)) < total: raise ValueError("insufficient player funds")
            wallet["silver"] -= total; market["stock"][key] -= qty; regional["cash_silver"] = int(regional.get("cash_silver", 0)) + total; self._record_private_realized_sale(regional, amount_silver=total, at=str(self._world_time()), kind="retail_sale", resource=key, quantity=qty); inv["items"][item_id] = int(inv["items"].get(item_id, 0)) + exact_qty
            result = {"item_key": key, "item_id": item_id, "quantity": qty, "exact_quantity": exact_qty, "spent_silver": total}
        else:
            if int(inv["items"].get(item_id, 0)) < exact_qty: raise ValueError("insufficient unequipped player inventory to sell")
            sellback = _fixed(self._civil_rules().get("market", {}).get("retail_sellback_factor", 0.70), 0.70)
            proceeds = max(1, int(math.floor(total * sellback)))
            if int(regional.get("cash_silver", 0)) < proceeds: raise ValueError("local private economy cannot fund this purchase")
            inv["items"][item_id] -= exact_qty; wallet["silver"] += proceeds; market["stock"][key] = int(market["stock"].get(key, 0)) + qty; regional["cash_silver"] -= proceeds
            result = {"item_key": key, "item_id": item_id, "quantity": qty, "exact_quantity": exact_qty, "received_silver": proceeds}
        market.setdefault("last_price", {})[key] = {"unit_silver": round(unit, 4), **{k: round(v, 4) for k, v in factors.items()}, "at": str(self._world_time()), "regional_economy_ref": regional_source_ref}
        self.put(invp, inv); self._register_owner("inventory_char_tang_wei", invp); self._write_private_economy(ep, eco); self.put(marketp, market); self.put(walletp, wallet)
        world_time, metrics = self._advance_seconds(max(300, qty * 60)); self._write_meta(command, world_time)
        return self._result(world_time=world_time, market_ref=str(market.get("owner_id")), unit_price_silver=round(unit, 4), pricing=factors, **result, **metrics)

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "house_action" and str(payload.get("action", "")) == "proclaim_territorial_authority":
            return self._proclaim_house_territorial_authority(command, payload)
        if command.command_type == "state_action" and str(payload.get("action", "")) == "recognize_polity":
            return self._recognize_polity(command, payload)
        if command.command_type == "polity_action":
            return self._dispatch_polity_action(command, payload)
        if command.command_type in {"market_purchase", "market_sell"}:
            return self._dispatch_market(command, payload)
        if command.command_type == "institution_project":
            return self._start_funded_institution_project(command, payload)
        if command.command_type == "project_resolve":
            ref = str(payload["institution_ref"]); p = self.owner_path(ref); inst = copy.deepcopy(self.read(p)); project_ref = str(payload["project_ref"])
            project = next((x for x in inst.setdefault("projects", []) if str(x.get("project_ref")) == project_ref), None)
            if not isinstance(project, dict): raise ValueError("unknown institution project")
            if project.get("status") != "active": raise ValueError("institution project is not active")
            if self._world_time() < CampaignTime.parse(str(project.get("completes_at"))): raise ValueError("institution project is not complete yet")
            self._resolve_funded_project(inst, project, str(self._world_time())); self.put(p, inst); world_time, metrics = self._advance_seconds(3600); self._write_meta(command, world_time); return self._result(institution_ref=ref, project_ref=project_ref, status=project.get("status"), world_time=world_time, **metrics)
        if command.command_type == "project_cancel":
            return self._cancel_funded_project(command, payload)
        result = super()._dispatch(command, payload)
        # dict.get(default) evaluates default eagerly.  After a causal command has
        # advanced runtime time but before the outer dispatcher commits meta time,
        # calling _world_time() here would falsely report chronology disagreement.
        result_world_time = str(result.get("world_time")) if isinstance(result, Mapping) and result.get("world_time") else None
        if result_world_time is None:
            result_world_time = str(self._world_time())
        if command.command_type == "recruitment" and isinstance(result, dict):
            state=str(payload.get("state","")); force_ref=f"force_state_{state}"; source=str(payload.get("source_stratum","agricultural")); n=max(0,int(payload.get("personnel",0)))
            if state in {"qin","zhao","chu","wei","han","yan","qi"} and n:
                pop_path=f"state/population/{state}.json"; pop=copy.deepcopy(self.read(pop_path)); force=self.read(self.owner_path(force_ref)); requested=str(force.get("source_location_ref") or self.read(f"state/depots/{state}.json").get("location_ref","")); _pp,pop,site_ref=self._local_population_site_for_location(state,requested,pop,controller_ref=f"state_{state}")
                moved=self._consume_local_recruitment(pop,state,site_ref,n,service_key="serving_native_military",source_stratum=source,service_owner_ref=force_ref)
                if moved!=n: raise ValueError("direct state recruitment exceeded locally accessible population")
                self.put(pop_path,pop); result["local_recruitment"]={"location_ref":site_ref,"source_stratum":source,"personnel":moved}
        if command.command_type == "battle_resolve" and isinstance(result, Mapping):
            material_losses = result.get("material_losses", {})
            if isinstance(material_losses, Mapping):
                foreign_population_losses: dict[str, dict[str, int]] = {}
                local_service_population_losses: dict[str, dict[str, dict[str, int]]] = {}
                rebel_population_losses: dict[str, dict[str, int]] = {}
                for formation_ref, raw in material_losses.items():
                    if not isinstance(raw, Mapping):
                        continue
                    try:
                        _fp, formation = self._load_formation(str(formation_ref))
                    except ValueError:
                        continue
                    force_ref = str(formation.get("owner_force_ref", ""))
                    cohort_losses = raw.get("cohort_losses", {}) if isinstance(raw.get("cohort_losses"), Mapping) else {}
                    local_losses = self._reconcile_local_state_service_casualties(
                        force_ref, cohort_losses,
                        at=result_world_time,
                        evidence_ref=str(result.get("battle_event", command.digest)),
                    )
                    losses = self._reconcile_foreign_service_casualties(
                        force_ref, cohort_losses,
                        at=result_world_time,
                        evidence_ref=str(result.get("battle_event", command.digest)),
                    )
                    if local_losses:
                        local_service_population_losses[str(formation_ref)] = local_losses
                    if losses:
                        foreign_population_losses[str(formation_ref)] = losses
                    force_ref = str(formation.get("owner_force_ref", ""))
                    casualties = max(0, int(result.get("casualties", {}).get(str(formation_ref), 0))) if isinstance(result.get("casualties"), Mapping) else 0
                    rebel_loss = self._reconcile_rebel_force_casualties(
                        force_ref,
                        casualties,
                        at=result_world_time,
                        evidence_ref=str(result.get("battle_event", command.digest)),
                        formation_ref=str(formation_ref),
                    )
                    if rebel_loss:
                        rebel_population_losses[str(formation_ref)] = rebel_loss
                    private_local = self._reconcile_private_service_casualties(
                        force_ref,
                        casualties,
                        at=result_world_time,
                        evidence_ref=str(result.get("battle_event", command.digest)),
                    )
                    if private_local:
                        result.setdefault("private_service_population_losses", {})[str(formation_ref)] = private_local
                if local_service_population_losses and isinstance(result, dict):
                    result["local_service_population_losses"] = local_service_population_losses
                if foreign_population_losses and isinstance(result, dict):
                    result["foreign_service_population_losses"] = foreign_population_losses
                if rebel_population_losses and isinstance(result, dict):
                    result["rebel_population_losses"] = rebel_population_losses
        if command.command_type in {"information_create", "information_deliver"}:
            info_ref = str(payload.get("information_ref", ""))
            if info_ref:
                index = self.read("state/information/index.json")
                info_path = index.get("claims", {}).get(info_ref) if isinstance(index, Mapping) and isinstance(index.get("claims"), Mapping) else None
                if isinstance(info_path, str):
                    claim = self.read(info_path)
                    knowers = [str(x) for x in claim.get("knowers", [])] if isinstance(claim, Mapping) and isinstance(claim.get("knowers"), list) else []
                    touched = self._record_faction_information(info_ref, knowers, result_world_time)
                    if touched:
                        result["factions_informed"] = touched
        if command.command_type == "territorial_consequence":
            loc = str(payload["location_ref"]); controller = str(payload["controller"]); terr = self.read("state/territory/control.json"); site = terr.get("sites", {}).get(loc, {}) if isinstance(terr, Mapping) else {}; old = str(site.get("previous_controller", "")); self._occupation_initialize(loc, controller, old, result_world_time, str(result.get("evidence_ref", "")) or None)
        return result

    def _autonomy_interstate(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        before = copy.deepcopy(self.read("state/territory/control.json"))
        super()._autonomy_interstate(host, occurrences, at)
        # The parent reducer owns the treaty registry snapshot for war/peace
        # settlement. Defensive-obligation hooks can run during that reducer, so
        # persist their treaty invocation audit *after* the parent writes its
        # snapshot to avoid losing the newer evidence row.
        try:
            world = self.read(self.owner_path(str(host.get("owner_ref", "interstate_warring_states"))))
        except (KeyError, ValueError, FileNotFoundError):
            world = {}
        treaties = copy.deepcopy(self.read("state/politics/treaties.json"))
        treaties_changed = False
        for theater_ref, record in world.get("theaters", {}).items() if isinstance(world, Mapping) else []:
            obligations = record.get("defensive_treaty_obligations", []) if isinstance(record, Mapping) else []
            if not isinstance(obligations, list):
                continue
            for obligation in obligations:
                if not isinstance(obligation, Mapping):
                    continue
                treaty_ref = str(obligation.get("treaty_ref", ""))
                treaty = treaties.get("records", {}).get(treaty_ref) if isinstance(treaties, Mapping) else None
                if not isinstance(treaty, dict):
                    continue
                history = treaty.setdefault("defense_invocations", [])
                key = (
                    str(obligation.get("source_theater_ref", theater_ref)),
                    str(obligation.get("obligated_ref", "")),
                    str(obligation.get("against_ref", "")),
                )
                if any(
                    isinstance(row, Mapping)
                    and (
                        str(row.get("source_theater_ref", "")),
                        str(row.get("obligated_ref", "")),
                        str(row.get("against_ref", "")),
                    ) == key
                    for row in history
                ):
                    continue
                history.append(copy.deepcopy(dict(obligation)))
                del history[:-24]
                treaty["last_invoked_at"] = str(obligation.get("at", at))
                treaties_changed = True
        if treaties_changed:
            self.put("state/politics/treaties.json", treaties)
        after = self.read("state/territory/control.json")
        for loc, site in after.get("sites", {}).items():
            old_site = before.get("sites", {}).get(loc, {})
            if isinstance(site, Mapping) and str(site.get("controller")) != str(old_site.get("controller")):
                self._occupation_initialize(str(loc), str(site.get("controller")), str(old_site.get("controller")), str(site.get("changed_at", at)), str(site.get("change_evidence_ref", "")) or None)
