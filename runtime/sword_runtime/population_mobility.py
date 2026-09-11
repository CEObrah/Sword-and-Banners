"""Conserved aggregate population movement over physical world routes.

This layer moves civilian household cohorts between legitimate demographic sites
without materializing families.  Departure removes people from the origin local
partition and places the same bodies in an in-transit stratum.  Same-owner moves
never change national population.  Cross-owner moves change population ownership
only on physical arrival.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.geography import shortest_path as geography_shortest_path
from sword_runtime.settlement_development import DYNAMIC_GEOGRAPHY_PATH, refresh_dynamic_settlement_class
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.tang_population import resident_support_capacity, sync_tang_private_population

MOBILITY_PATH = "state/mobility/population-transit.json"
INFRASTRUCTURE_PATH = "state/infrastructure/settlements.json"
RUNTIME_PATH = "state/runtime.json"
LOCATIONS_PATH = "game/data/world/locations.json"
OWNER_INDEX_PATH = "state/index/owner-index.json"
TANG_POPULATION_PATH = "state/population/tang-manor.json"
TRANSIT_STRATUM = "civilian_migration_in_transit"
MONTH_SECONDS = 30 * 86400
POPULATION_ARRIVAL_HOST_ID = "host_population_arrival_queue"
POPULATION_ARRIVAL_EVENT_ID = "event_population_arrival_queue"


def _integer_partition(total: int, weights: Mapping[str, int]) -> dict[str, int]:
    total = max(0, int(total))
    positive = {str(k): max(0, int(v)) for k, v in weights.items() if int(v) > 0}
    if total <= 0 or not positive:
        return {str(k): 0 for k in weights}
    available = sum(positive.values())
    total = min(total, available)
    raw = {key: total * value / available for key, value in positive.items()}
    out = {key: int(math.floor(value)) for key, value in raw.items()}
    remaining = total - sum(out.values())
    for key in sorted(positive, key=lambda k: (-(raw[k] - out[k]), k))[:remaining]:
        out[key] += 1
    return out


def _civilian_mix(row: Mapping[str, Any], count: int) -> dict[str, int]:
    strata = row.get("civilian_strata", {}) if isinstance(row.get("civilian_strata"), Mapping) else {}
    return _integer_partition(count, {str(k): max(0, int(v)) for k, v in strata.items()})


def _sync_local_row(row: MutableMapping[str, Any]) -> None:
    civilian = sum(max(0, int(v)) for v in (row.get("civilian_strata", {}) or {}).values())
    allocations = row.get("service_allocations", {}) if isinstance(row.get("service_allocations"), Mapping) else {}
    service = sum(max(0, int(v.get("personnel", 0))) for v in allocations.values() if isinstance(v, Mapping))
    reservations = row.get("candidate_reservations", {}) if isinstance(row.get("candidate_reservations"), Mapping) else {}
    reserved = sum(
        sum(max(0, int(x)) for x in (v.get("source_strata", {}) if isinstance(v, Mapping) else {}).values())
        for v in reservations.values()
        if isinstance(v, Mapping)
    )
    row["civilian_population"] = civilian
    row["service_population"] = service
    row["candidates_reserved"] = reserved
    row["reserved_candidates"] = reserved
    row["agricultural_available"] = max(0, int((row.get("civilian_strata", {}) or {}).get("agricultural", 0)))


def _local_load(row: Mapping[str, Any]) -> int:
    return max(0, int(row.get("civilian_population", 0))) + max(0, int(row.get("service_population", 0)))


class PopulationMobilityMixin:
    """Production mixin for autonomous and explicitly routed population movement."""

    def _mobility_owner(self) -> dict[str, Any]:
        owner = copy.deepcopy(self.read(MOBILITY_PATH))
        if not isinstance(owner.get("cohorts"), dict):
            raise ValueError("population mobility cohort registry is invalid")
        return owner

    def _population_owner_paths_for_mobility(self) -> list[str]:
        """Discover exact demographic owners from the authoritative owner index.

        Mobility must not carry a static copy of the population registry in hot
        state. Dynamic polity populations become eligible automatically, while
        projection/subset owners such as Tang Manor are skipped.
        """
        idx = self.read(OWNER_INDEX_PATH)
        owners = idx.get("owners", {}) if isinstance(idx, Mapping) else {}
        if not isinstance(owners, Mapping):
            raise ValueError("owner index is invalid")
        paths: list[str] = []
        for owner_ref, path in sorted((str(k), str(v)) for k, v in owners.items() if isinstance(k, str) and isinstance(v, str)):
            if owner_ref == "population_mobility" or not owner_ref.startswith("population_"):
                continue
            if not path.startswith("state/population/") or not path.endswith(".json"):
                continue
            pop = self.read(path)
            if not isinstance(pop, Mapping) or pop.get("subset_of_parent") is True:
                continue
            local = pop.get("local_population")
            sites = local.get("sites", {}) if isinstance(local, Mapping) else {}
            if isinstance(sites, Mapping):
                paths.append(path)
        return paths

    def _location_rows_for_mobility(self) -> dict[str, Mapping[str, Any]]:
        doc = self.read(LOCATIONS_PATH)
        rows = {
            str(row.get("ref")): row
            for row in doc.get("locations", [])
            if isinstance(row, Mapping) and isinstance(row.get("ref"), str)
        }
        dynamic = self.read_optional(DYNAMIC_GEOGRAPHY_PATH)
        if isinstance(dynamic, Mapping):
            for row in dynamic.get("locations", []):
                if isinstance(row, Mapping) and isinstance(row.get("ref"), str):
                    rows[str(row.get("ref"))] = row
        return rows

    def _schedule_population_arrival(
        self, cohort_ref: str, arrives_at: str, *, runtime_queue: dict[str, Any] | None = None
    ) -> bool:
        """Route all conserved migration cohorts through one exact next-arrival clock.

        Cohort truth remains in ``state/mobility/population-transit.json``.  The
        scheduler needs only the earliest outstanding arrival instant; after that
        arrival settles, the same route retimes itself to the next exact cohort.
        This keeps chronology exact without creating one host/event pair per move.
        """
        owned_queue = runtime_queue is None
        runtime = copy.deepcopy(self.read(RUNTIME_PATH)) if owned_queue else runtime_queue
        if not isinstance(runtime, dict):
            raise ValueError("runtime causal queue is invalid")
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        due = CampaignTime.parse(arrives_at)
        now_text = str(runtime.get("world_time"))
        now = CampaignTime.parse(now_text)
        if due <= now:
            raise ValueError("population arrival must be scheduled after departure time")

        host = hosts.get(POPULATION_ARRIVAL_HOST_ID)
        event = next((row for row in events if isinstance(row, dict) and row.get("event_id") == POPULATION_ARRIVAL_EVENT_ID), None)
        changed = False
        if isinstance(host, dict):
            current_due_text = host.get("next_due")
            current_due = CampaignTime.parse(str(current_due_text)) if isinstance(current_due_text, str) else None
            if current_due is None or due < current_due:
                host["next_due"] = arrives_at
                host["safe_through"] = str(due.add_seconds(-1))
                host["recurrence_seconds"] = max(1, now.seconds_until(due))
                host.pop("retire_after_settlement", None)
                if event is None:
                    events.append({
                        "event_id": POPULATION_ARRIVAL_EVENT_ID,
                        "kind": "population_mobility_arrival",
                        "priority": 61,
                        "target_host": POPULATION_ARRIVAL_HOST_ID,
                        "due_at": arrives_at,
                    })
                else:
                    event["due_at"] = arrives_at
                    event.pop("suspended", None)
                changed = True
        else:
            hosts[POPULATION_ARRIVAL_HOST_ID] = {
                "host_id": POPULATION_ARRIVAL_HOST_ID,
                "kind": "population_mobility_arrival",
                "owner_ref": "population_mobility",
                "recurrence_seconds": max(1, now.seconds_until(due)),
                "next_due": arrives_at,
                "resolved_through": now_text,
                "safe_through": str(due.add_seconds(-1)),
            }
            if event is None:
                events.append({
                    "event_id": POPULATION_ARRIVAL_EVENT_ID,
                    "kind": "population_mobility_arrival",
                    "priority": 61,
                    "target_host": POPULATION_ARRIVAL_HOST_ID,
                    "due_at": arrives_at,
                })
            else:
                event.update({
                    "kind": "population_mobility_arrival",
                    "priority": 61,
                    "target_host": POPULATION_ARRIVAL_HOST_ID,
                    "due_at": arrives_at,
                })
                event.pop("suspended", None)
            changed = True
        if owned_queue and changed:
            self.put(RUNTIME_PATH, runtime)
        return changed

    def _queue_population_move(
        self,
        *,
        source_population_path: str,
        destination_population_path: str,
        origin_site_ref: str,
        destination_site_ref: str,
        count: int,
        departed_at: str,
        basis: str,
        runtime_queue: dict[str, Any] | None = None,
        route_plan: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        requested = max(0, int(count))
        if requested <= 0 or origin_site_ref == destination_site_ref:
            return None
        source = copy.deepcopy(self.read(source_population_path))
        destination = source if destination_population_path == source_population_path else copy.deepcopy(self.read(destination_population_path))
        source_sites = source.get("local_population", {}).get("sites", {}) if isinstance(source.get("local_population"), Mapping) else {}
        destination_sites = destination.get("local_population", {}).get("sites", {}) if isinstance(destination.get("local_population"), Mapping) else {}
        origin = source_sites.get(origin_site_ref) if isinstance(source_sites, Mapping) else None
        dest = destination_sites.get(destination_site_ref) if isinstance(destination_sites, Mapping) else None
        if not isinstance(origin, dict) or not isinstance(dest, dict):
            raise ValueError("population movement requires exact demographic origin and destination rows")

        mix = _civilian_mix(origin, requested)
        moved = sum(mix.values())
        if moved <= 0:
            return None
        plan = dict(route_plan) if isinstance(route_plan, Mapping) else geography_shortest_path(
            self.read, origin_site_ref, destination_site_ref, modes=("foot", "horse", "convoy")
        )
        duration_hours = max(1, int(plan.get("duration_hours", 0)))
        arrives_at = str(CampaignTime.parse(departed_at).add_seconds(duration_hours * 3600))

        digest = hashlib.sha256(
            f"{departed_at}|{source_population_path}|{origin_site_ref}|{destination_population_path}|{destination_site_ref}|{moved}".encode("utf-8")
        ).hexdigest()[:24]
        cohort_ref = f"migration_{digest}"
        owner = self._mobility_owner()
        if cohort_ref in owner["cohorts"]:
            return copy.deepcopy(owner["cohorts"][cohort_ref])

        # Debit physical origin locality immediately and place the same bodies in
        # an in-transit national stratum. National ownership is unchanged here.
        origin_strata = origin.setdefault("civilian_strata", {})
        source_strata = source.setdefault("strata", {})
        for key, value in mix.items():
            if int(origin_strata.get(key, 0)) < value or int(source_strata.get(key, 0)) < value:
                raise ValueError("population movement exceeds conserved source stratum")
            origin_strata[key] = int(origin_strata.get(key, 0)) - value
            source_strata[key] = int(source_strata.get(key, 0)) - value
        source_strata[TRANSIT_STRATUM] = int(source_strata.get(TRANSIT_STRATUM, 0)) + moved
        _sync_local_row(origin)

        cohort = {
            "migration_ref": cohort_ref,
            "status": "in_transit",
            "count": moved,
            "source_population_path": source_population_path,
            "destination_population_path": destination_population_path,
            "origin_site_ref": origin_site_ref,
            "destination_site_ref": destination_site_ref,
            "civilian_strata_mix": mix,
            "departed_at": departed_at,
            "arrives_at": arrives_at,
            "route_refs": list(plan.get("route_refs", [])),
            "route_path": list(plan.get("path", [])),
            "duration_hours": duration_hours,
            "ownership_transfer_at": "arrival" if destination_population_path != source_population_path else "unchanged",
        }
        owner["cohorts"][cohort_ref] = cohort
        self.put(source_population_path, source)
        if source_population_path == "state/population/qin.json" and origin_site_ref == "loc_tang_manor":
            sync_tang_private_population(self, at=departed_at, reason="population_migration_departure", evidence_ref=cohort_ref)
        self.put(MOBILITY_PATH, owner)
        self._schedule_population_arrival(cohort_ref, arrives_at, runtime_queue=runtime_queue)
        return copy.deepcopy(cohort)

    def _settle_population_mobility_arrival(self, host: Mapping[str, Any], at: str) -> None:
        # Direct cohort settlement remains available to focused tests and exact
        # subsystem callers. Production scheduling uses the single queue host.
        explicit_ref = host.get("cohort_ref")
        if isinstance(explicit_ref, str) and explicit_ref:
            cohort_ref = str(host.get("cohort_ref", ""))
            owner = self._mobility_owner()
            cohort = owner.get("cohorts", {}).get(cohort_ref)
            if not isinstance(cohort, dict) or cohort.get("status") != "in_transit":
                return
            if str(cohort.get("arrives_at")) != at:
                raise ValueError("population migration arrival time diverged from cohort route")
            source_path = str(cohort["source_population_path"])
            destination_path = str(cohort["destination_population_path"])
            source = copy.deepcopy(self.read(source_path))
            destination = source if source_path == destination_path else copy.deepcopy(self.read(destination_path))
            destination_sites = destination.get("local_population", {}).get("sites", {}) if isinstance(destination.get("local_population"), Mapping) else {}
            dest = destination_sites.get(str(cohort["destination_site_ref"])) if isinstance(destination_sites, Mapping) else None
            if not isinstance(dest, dict):
                raise ValueError("population migration destination demographic row disappeared")
            mix = {str(k): max(0, int(v)) for k, v in cohort.get("civilian_strata_mix", {}).items()}
            count = sum(mix.values())
            source_strata = source.setdefault("strata", {})
            if int(source_strata.get(TRANSIT_STRATUM, 0)) < count:
                raise ValueError("population migration lost its conserved in-transit bodies")
            source_strata[TRANSIT_STRATUM] = int(source_strata.get(TRANSIT_STRATUM, 0)) - count
            if source_strata[TRANSIT_STRATUM] == 0:
                source_strata.pop(TRANSIT_STRATUM, None)

            destination_strata = destination.setdefault("strata", {})
            dest_civilian = dest.setdefault("civilian_strata", {})
            for key, value in mix.items():
                destination_strata[key] = int(destination_strata.get(key, 0)) + value
                dest_civilian[key] = int(dest_civilian.get(key, 0)) + value
            _sync_local_row(dest)

            if source_path != destination_path:
                source["population_total"] = max(0, int(source.get("population_total", 0)) - count)
                destination["population_total"] = int(destination.get("population_total", 0)) + count
                self.put(source_path, source)
                self.put(destination_path, destination)
            else:
                # Same-owner movement only reclassifies transit bodies back into their
                # civilian source mix. Population total never changed.
                self.put(source_path, source)

            if destination_path == "state/population/qin.json" and str(cohort["destination_site_ref"]) == "loc_tang_manor":
                sync_tang_private_population(self, at=at, reason="population_migration_arrival", evidence_ref=cohort_ref)
                application = cohort.get("bastion_application") if isinstance(cohort.get("bastion_application"), Mapping) else None
                if application:
                    tang = copy.deepcopy(self.read(TANG_POPULATION_PATH))
                    corps = str(application.get("corps", ""))
                    pools = tang.setdefault("bastion_outside_applications", {})
                    row = pools.setdefault(corps, {
                        "available_applicants": 0,
                        "arrival_history": [],
                    })
                    row["available_applicants"] = max(0, int(row.get("available_applicants", 0))) + count
                    row.setdefault("arrival_history", []).append({
                        "migration_ref": cohort_ref,
                        "count": count,
                        "unconsidered_applicants": count,
                        "source_state": application.get("source_state"),
                        "source_site_ref": application.get("source_site_ref"),
                        "arrived_at": at,
                    })
                    row["arrival_history"] = row["arrival_history"][-32:]
                    self.put(TANG_POPULATION_PATH, tang)
                    application["status"] = "resident_applicant"
                    application["arrived_at"] = at

            # Arrival resolves the conserved obligation. Transaction idempotency
            # lives in the write/receipt layer; mobility state retains no duplicate
            # audit diary after the bodies reach their exact destination owner.
            owner.get("cohorts", {}).pop(cohort_ref, None)
            self.put(MOBILITY_PATH, owner)
            refresh_dynamic_settlement_class(self, str(cohort["destination_site_ref"]))
            return

        if str(host.get("host_id", POPULATION_ARRIVAL_HOST_ID)) != POPULATION_ARRIVAL_HOST_ID:
            raise ValueError("population arrival scheduler host is invalid")
        owner = self._mobility_owner()
        due_refs = sorted(
            str(ref) for ref, row in owner.get("cohorts", {}).items()
            if isinstance(row, Mapping) and str(row.get("status")) == "in_transit" and str(row.get("arrives_at")) == at
        )
        earlier = sorted(
            str(ref) for ref, row in owner.get("cohorts", {}).items()
            if isinstance(row, Mapping)
            and str(row.get("status")) == "in_transit"
            and isinstance(row.get("arrives_at"), str)
            and CampaignTime.parse(str(row.get("arrives_at"))) < CampaignTime.parse(at)
        )
        if earlier:
            raise ValueError("population arrival queue has an overdue conserved cohort")
        for cohort_ref in due_refs:
            self._settle_population_mobility_arrival({"cohort_ref": cohort_ref}, at)

        remaining = self._mobility_owner().get("cohorts", {})
        next_times = sorted(
            CampaignTime.parse(str(row.get("arrives_at")))
            for row in remaining.values()
            if isinstance(row, Mapping)
            and str(row.get("status")) == "in_transit"
            and isinstance(row.get("arrives_at"), str)
        )
        runtime = copy.deepcopy(self.read(RUNTIME_PATH))
        live = runtime.get("hosts", {}).get(POPULATION_ARRIVAL_HOST_ID) if isinstance(runtime.get("hosts"), dict) else None
        if not isinstance(live, dict):
            raise ValueError("population arrival queue lost its scheduler host")
        if next_times:
            now = CampaignTime.parse(at)
            next_due = next_times[0]
            seconds = now.seconds_until(next_due)
            if seconds <= 0:
                raise ValueError("population arrival queue failed to advance")
            live["recurrence_seconds"] = seconds
            live.pop("retire_after_settlement", None)
        else:
            # The central scheduler retires this exact host/event after the current
            # callback, leaving no empty population clock behind.
            live["retire_after_settlement"] = True
            live["recurrence_seconds"] = 1
        self.put(RUNTIME_PATH, runtime)

    def _autonomy_population_mobility(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Create lawful internal household movement from pressure and opportunity.

        ``occurrences`` is normally one under the chronological production scheduler.
        Movement amount is a behavioral propensity applied to willing civilian
        households and then bounded by actual destination headroom and route access;
        there is no standalone monthly migration ceiling.
        """
        if max(0, int(occurrences)) <= 0:
            return
        infrastructure = self.read(INFRASTRUCTURE_PATH)
        infra_sites = infrastructure.get("sites", {}) if isinstance(infrastructure, Mapping) else {}
        location_rows = self._location_rows_for_mobility()
        population_paths = self._population_owner_paths_for_mobility()

        runtime_queue = copy.deepcopy(self.read(RUNTIME_PATH))
        runtime_queue_changed = False
        for population_path in population_paths:
            if not isinstance(population_path, str):
                continue
            pop = self.read(population_path)
            local = pop.get("local_population") if isinstance(pop, Mapping) else None
            sites = local.get("sites", {}) if isinstance(local, Mapping) else {}
            if not isinstance(sites, Mapping) or len(sites) < 2:
                continue
            for source_ref, source_row in sorted(sites.items()):
                if not isinstance(source_row, Mapping):
                    continue
                civilian = max(0, int(source_row.get("civilian_population", 0)))
                if civilian < 25:
                    continue
                source_infra = infra_sites.get(source_ref, {}) if isinstance(infra_sites, Mapping) else {}
                source_policy = source_infra.get("mobility", {}) if isinstance(source_infra, Mapping) else {}
                source_kind = str(location_rows.get(source_ref, {}).get("kind", "region"))
                default_propensity_bp = 8 if source_kind in {"region", "major_region", "village"} else 3
                propensity_bp = max(0, int(source_policy.get("outmigration_propensity_per_30d_basis_points", default_propensity_bp))) if isinstance(source_policy, Mapping) else default_propensity_bp
                _source_residence_ref, resolved_source_capacity = resident_support_capacity(infra_sites, str(source_ref), _local_load(source_row))
                source_capacity = max(1, resolved_source_capacity)
                source_load = _local_load(source_row)
                overcrowding = max(0.0, (source_load - source_capacity) / source_capacity)
                displaced = max(0, int(source_row.get("displaced", 0)))

                # Destination desirability depends only on represented physical
                # headroom and pull. Route duration was never part of the score, so
                # running a full shortest-path search for every source/destination
                # pair was redundant. Rank candidates first, then route-check only
                # until the best reachable destination is found.
                candidates: list[tuple[float, str]] = []
                for destination_ref, destination_row in sites.items():
                    if destination_ref == source_ref or not isinstance(destination_row, Mapping):
                        continue
                    destination_infra = infra_sites.get(destination_ref, {}) if isinstance(infra_sites, Mapping) else {}
                    if not isinstance(destination_infra, Mapping):
                        continue
                    _dest_residence_ref, capacity = resident_support_capacity(infra_sites, str(destination_ref), 0)
                    load = _local_load(destination_row)
                    headroom = max(0, capacity - load)
                    if headroom <= 0:
                        continue
                    dest_kind = str(location_rows.get(destination_ref, {}).get("kind", "region"))
                    urban_weight = 1.45 if dest_kind in {"capital", "city"} else (1.20 if dest_kind in {"town", "estate"} else 1.0)
                    mobility = destination_infra.get("mobility", {}) if isinstance(destination_infra.get("mobility"), Mapping) else {}
                    pull = max(0.1, float(mobility.get("pull_weight", urban_weight)))
                    score = (headroom / max(1, capacity)) * pull
                    candidates.append((score, str(destination_ref)))
                best: tuple[float, str, dict[str, Any]] | None = None
                for score, destination_ref in sorted(candidates, reverse=True):
                    try:
                        route = geography_shortest_path(
                            self.read, str(source_ref), str(destination_ref), modes=("foot", "horse", "convoy")
                        )
                    except ValueError:
                        continue
                    best = (score, destination_ref, dict(route))
                    break
                if best is None:
                    continue
                pull_score, destination_ref, selected_route = best
                # Normal household willingness is a rate, not a hard cap.  Severe
                # crowding/displacement increases pressure; destination headroom
                # still provides the physical stop condition.
                willing_fraction = propensity_bp / 10000.0
                desired = int(math.floor(civilian * willing_fraction * max(0.25, pull_score)))
                desired += int(math.floor(civilian * min(0.25, overcrowding)))
                if displaced:
                    desired += min(displaced, max(1, int(math.ceil(displaced * 0.25))))
                destination_row = sites[destination_ref]
                _destination_residence_ref, destination_capacity = resident_support_capacity(infra_sites, str(destination_ref), 0)
                destination_headroom = max(0, destination_capacity - _local_load(destination_row))
                desired = min(max(0, desired), destination_headroom)
                if desired <= 0:
                    continue
                cohort = self._queue_population_move(
                    source_population_path=population_path,
                    destination_population_path=population_path,
                    origin_site_ref=str(source_ref),
                    destination_site_ref=destination_ref,
                    count=desired,
                    departed_at=at,
                    basis="autonomous household movement from physical headroom, settlement pull, household willingness, and source pressure",
                    runtime_queue=runtime_queue,
                    route_plan=selected_route,
                )
                if cohort:
                    runtime_queue_changed = True

        if runtime_queue_changed:
            self.put(RUNTIME_PATH, runtime_queue)
        # Scheduler frontier records completion of this review. Only unresolved
        # migration cohorts remain in hot mobility state.


__all__ = ["PopulationMobilityMixin"]
