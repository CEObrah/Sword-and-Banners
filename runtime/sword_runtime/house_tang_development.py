"""Causal House Tang and Inner Walls aggregate development.

House Tang's military population is represented only as House Infantry and House
Cavalry cohorts. Monthly settlement advances verified cohort capability without a
troop-species promotion ladder; replacement intake remains capacity-bounded and
conservation-backed.

This module also owns the House-specific Inner Walls expansion lifecycle. Exact candidate bodies remain conserved through the ordinary population and cohort authorities.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import (
    conserved_establishment_role_count,
    add_recruits,
    consume_population_recruits,
    ensure_cohort_ledger,
    record_recruitment_cohort,
    role_count,
    validate_cohort_ledger,
)
from sword_runtime.infrastructure_projects import apply_infrastructure_work, calculate_project_schedule, infrastructure_work_spec
from sword_runtime.land_development import LAND_RULES_PATH, LAND_STATE_PATH, apply_site_land_reservation, reserve_site_land
from sword_runtime.household_request_flow import (
    _emit_watch_report,
    _perform_house_requested_military_intake,
    _house_tang_force_status,
    _response_event,
    _treasury_safe_ceiling,
)
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.tang_population import sync_tang_private_population

HOUSE_FORCE = "state/forces/house-tang.json"
QIN_POPULATION = "state/population/qin.json"
MANOR_POPULATION = "state/population/tang-manor.json"
SETTLEMENT_INFRASTRUCTURE = "state/infrastructure/settlements.json"
HOUSE_PATH = "state/houses/house_tang.json"
TREASURY_PATH = "state/treasury/treasury-house-tang.json"
INVENTORY_PATH = "state/inv/inventories.json"
HOUSE_MOUNT_POOL_PATH = "state/mounts/house-tang.json"
RUNTIME_PATH = "state/runtime.json"
HOUSE_RULES_PATH = "game/data/mechanics/house-tang-programs.json"
DEVELOPMENT_RULES_PATH = "game/data/mechanics/house-tang-development.json"
TRAINING_GROUND = "loc_tang_manor_training_ground"
GARRISON = "loc_tang_manor_garrison_yard"
MONTH_SECONDS = 30 * 86400
_HISTORY_WINDOW = 256
_EXPANSION_REQUEST_KIND = "inner_walls_infrastructure_expansion"
_EXPANSION_PRIORITY = 53


def _records(doc: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row["record_id"]): row
        for row in doc.get("records", [])
        if isinstance(row, Mapping) and row.get("record_id")
    }


def _allocation_count(value: Any) -> int:
    return int(value.get("personnel", 0)) if isinstance(value, Mapping) else int(value)


def _role_vacancy(force: Mapping[str, Any], role: str) -> int:
    """Return the real unfilled authorized establishment for one force role.

    Rank/class promotion may only reclassify bodies into an establishment that
    actually exists.  This is deliberately based on conserved role ownership
    across reserve plus formations rather than on the reserve pool alone.
    """
    authorized = force.get("authorized_by_role", {}) if isinstance(force.get("authorized_by_role"), Mapping) else {}
    if role not in authorized:
        return 0
    return max(0, int(authorized.get(role, 0) or 0) - conserved_establishment_role_count(force, role))


def _months(value: Any, default: int = 0) -> int:
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else default


def _outfitting_facts_mutable(inventory: dict[str, Any]) -> dict[str, Any]:
    for row in inventory.get("records", []):
        if isinstance(row, dict) and row.get("record_id") == "house_tang_outfitting_sets":
            facts = row.setdefault("facts", {})
            if not isinstance(facts, dict):
                raise ValueError("House Tang outfitting reserve is invalid")
            return facts
    raise ValueError("House Tang outfitting reserve is missing")


def _force_equipment_available(force: Mapping[str, Any], role: str, location_ref: str) -> int:
    aggregate = force.get("available_equipment_units_by_role", {}) if isinstance(force.get("available_equipment_units_by_role"), Mapping) else {}
    local_rows = force.get("available_equipment_by_location", {}) if isinstance(force.get("available_equipment_by_location"), Mapping) else {}
    local = local_rows.get(location_ref, {}) if isinstance(local_rows, Mapping) else {}
    return min(max(0, int(aggregate.get(role, 0) or 0)), max(0, int(local.get(role, 0) or 0)) if isinstance(local, Mapping) else 0)


def _add_force_equipment(force: dict[str, Any], role: str, count: int, location_ref: str) -> None:
    count = max(0, int(count))
    if count <= 0:
        return
    aggregate = force.setdefault("available_equipment_units_by_role", {})
    local = force.setdefault("available_equipment_by_location", {}).setdefault(location_ref, {})
    aggregate[role] = max(0, int(aggregate.get(role, 0) or 0)) + count
    local[role] = max(0, int(local.get(role, 0) or 0)) + count


def _move_force_equipment(force: dict[str, Any], source_role: str, destination_role: str, count: int, location_ref: str) -> int:
    count = min(max(0, int(count)), _force_equipment_available(force, source_role, location_ref))
    if count <= 0:
        return 0
    aggregate = force.setdefault("available_equipment_units_by_role", {})
    local = force.setdefault("available_equipment_by_location", {}).setdefault(location_ref, {})
    aggregate[source_role] = max(0, int(aggregate.get(source_role, 0) or 0)) - count
    local[source_role] = max(0, int(local.get(source_role, 0) or 0)) - count
    aggregate[destination_role] = max(0, int(aggregate.get(destination_role, 0) or 0)) + count
    local[destination_role] = max(0, int(local.get(destination_role, 0) or 0)) + count
    return count


def _request_ids(request_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(("house-development-request|" + request_ref).encode("utf-8")).hexdigest()[:20]
    return f"host_house_development_{digest}", f"event_house_development_{digest}"


def _completion_ids(project_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(("house-development-completion|" + project_ref).encode("utf-8")).hexdigest()[:20]
    return f"host_house_development_completion_{digest}", f"event_house_development_completion_{digest}"




def _is_expansion_request(attempt: Mapping[str, Any]) -> bool:
    if attempt.get("actor_id") != "char_tang_wei" or attempt.get("target_ref") not in {"char_tang_ling", "char_tang_zhu"}:
        return False
    if attempt.get("action") not in {"ask", "request", "present", "comply"}:
        return False
    text = " ".join(str(attempt.get("player_statement", "")).lower().split())
    if "inner walls" not in text:
        return False
    expansion = any(term in text for term in ("expand", "expanding", "infrastructure", "capacity", "build", "construction"))
    intake = any(term in text for term in ("recruit", "recruiting", "intake", "replacement", "replacements", "soldier", "soldiers"))
    development = any(term in text for term in ("train", "training", "drill", "drilling", "develop", "development"))
    return expansion and intake and development


def _public_owner_label(value: Any) -> str:
    ref = str(value or "")
    state = {
        "state_qin": "Qin",
        "state_wei": "Wei",
        "state_zhao": "Zhao",
        "state_chu": "Chu",
        "state_han": "Han",
        "state_yan": "Yan",
        "state_qi": "Qi",
    }
    return state.get(ref, "the reported actor" if ref else "the actor")


_CIVIL_PARENT_STRATUM = {
    "agricultural_workers_and_supervisors": "agricultural",
    "forge_and_armory_workers": "craft_and_industry",
    "stable_remount_and_carriage_workers": "merchant_and_transport",
    "warehouse_and_granary_workers": "merchant_and_transport",
    "construction_and_maintenance_workers": "craft_and_industry",
    "household_service": "household_and_service",
    "inner_walls_civilian_medical": "camp_medical_support",
    "administrative_clerks": "administration_and_education",
    "water_sanitation_and_firefighting": "household_and_service",
}


class HouseTangDevelopmentMixin:
    @staticmethod
    def _civil_intake(
        qin: Mapping[str, Any], manor: dict[str, Any], *, at: str, cycle_ref: str
    ) -> int:
        """Add voluntary permanent residents from the Qin parent population."""
        policy = manor.get("civil_recruitment_policy", {})
        if not isinstance(policy, Mapping):
            return 0
        capacity = max(0, int(policy.get("monthly_capacity", 0)))
        targets = policy.get("target_staffing", {})
        strata = manor.setdefault("strata", {})
        qin_strata = qin.get("strata", {}) if isinstance(qin.get("strata"), Mapping) else {}
        remaining = capacity
        moved = 0
        mix: list[dict[str, Any]] = []
        for manor_role, target in targets.items() if isinstance(targets, Mapping) else ():
            if remaining <= 0:
                break
            parent_role = _CIVIL_PARENT_STRATUM.get(str(manor_role))
            if parent_role is None:
                continue
            current = max(0, int(strata.get(manor_role, 0)))
            vacancy = max(0, int(target) - current)
            parent_available = max(0, int(qin_strata.get(parent_role, 0)))
            take = min(remaining, vacancy, parent_available)
            if take <= 0:
                continue
            strata[manor_role] = current + take
            remaining -= take
            moved += take
            mix.append({"target_stratum": str(manor_role), "parent_stratum": parent_role, "count": take})
        if moved:
            manor["population_total"] = int(manor.get("population_total", 0)) + moved
        return moved

    def _normalize_house_tang_training_host(self, runtime: dict[str, Any]) -> None:
        """Keep one monthly House Tang training/replacement host and retire old hosts."""
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        now = CampaignTime.parse(str(runtime["world_time"]))
        old_hosts = [
            host_id for host_id, host in hosts.items()
            if isinstance(host, Mapping)
            and (host_id == "host_sword_manor" or host.get("kind") == "sword_manor" or host.get("owner_ref") == "force_sword_manor")
        ]
        inherited = None
        for host_id in old_hosts:
            row = hosts.pop(host_id, None)
            if inherited is None and isinstance(row, Mapping):
                inherited = dict(row)
        events[:] = [
            row for row in events
            if not isinstance(row, Mapping)
            or str(row.get("target_host", "")) not in set(old_hosts) | {"host_house_tang_training"}
        ]
        host_id = "host_house_tang_training"
        existing = hosts.get(host_id)
        if not isinstance(existing, dict):
            existing = {}
            hosts[host_id] = existing
        inherited_due = inherited.get("next_due") if isinstance(inherited, Mapping) else None
        due = CampaignTime.parse(str(inherited_due)) if isinstance(inherited_due, str) else None
        if due is None or due <= now:
            due = now.add_seconds(MONTH_SECONDS)
        existing.update({
            "kind": "house_tang_training",
            "owner_ref": "force_house_tang",
            "recurrence_seconds": MONTH_SECONDS,
            "next_due": str(due),
            "resolved_through": str((inherited or {}).get("resolved_through", runtime["world_time"])),
            "safe_through": str(due.add_seconds(-1)),
            "quiet_run_count": max(0, int(existing.get("quiet_run_count", (inherited or {}).get("quiet_run_count", 0)) or 0)),
        })
        events.append({
            "event_id": "event_host_house_tang_training_review",
            "kind": "institution_review",
            "priority": 100,
            "target_host": host_id,
            "due_at": str(due),
        })

    def _sync_house_development_requests(self, runtime: dict[str, Any]) -> None:
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        house = copy.deepcopy(self.read(HOUSE_PATH))
        requests = house.setdefault("development_requests", {})
        if not isinstance(requests, dict):
            raise ValueError("House Tang development request registry is invalid")
        now = CampaignTime.parse(str(runtime["world_time"]))
        changed = False
        attempts, _ = recent_interaction_attempts(self, "char_tang_wei", limit=_HISTORY_WINDOW)
        for attempt in attempts:
            if not _is_expansion_request(attempt):
                continue
            requested_at = attempt.get("at")
            if not isinstance(requested_at, str):
                continue
            request_ref = interaction_attempt_ref(attempt)
            if request_ref not in requests:
                requests[request_ref] = {
                    "request_ref": request_ref,
                    "kind": _EXPANSION_REQUEST_KIND,
                    "status": "queued",
                    "requested_at": requested_at,
                    "source_event_id": attempt.get("event_id"),
                    "target_ref": attempt.get("target_ref"),
                    "player_statement": str(attempt.get("player_statement", ""))[:2000],
                }
                changed = True
            if requests[request_ref].get("status") == "settled":
                continue
            host_id, event_id = _request_ids(request_ref)
            if host_id in hosts:
                continue
            due = CampaignTime.parse(requested_at).add_seconds(3600)
            if due < now:
                due = now
            hosts[host_id] = {
                "host_id": host_id,
                "kind": "house_development_request",
                "owner_ref": "house_tang",
                "request_ref": request_ref,
                "recurrence_seconds": 0,
                "next_due": str(due),
                "resolved_through": str(now if now < due else due.add_seconds(-1)),
                "safe_through": str(due.add_seconds(-1)),
            }
            events.append({
                "event_id": event_id,
                "kind": "house_development_request",
                "priority": _EXPANSION_PRIORITY,
                "target_host": host_id,
                "due_at": str(due),
            })
        if changed:
            self.put(HOUSE_PATH, house)



    def _schedule_expansion_completion(self, project_ref: str, due: CampaignTime) -> None:
        runtime = copy.deepcopy(self.read(RUNTIME_PATH))
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        host_id, event_id = _completion_ids(project_ref)
        if host_id not in hosts:
            hosts[host_id] = {"host_id": host_id, "kind": "house_development_completion", "owner_ref": "house_tang", "project_ref": project_ref, "recurrence_seconds": 0, "next_due": str(due), "resolved_through": str(CampaignTime.parse(str(runtime["world_time"]))), "safe_through": str(due.add_seconds(-1))}
            events.append({"event_id": event_id, "kind": "house_development_completion", "priority": _EXPANSION_PRIORITY, "target_host": host_id, "due_at": str(due)})
            self.put(RUNTIME_PATH, runtime)

    def _settle_expansion_request(self, host: Mapping[str, Any], at: str) -> None:
        request_ref = str(host.get("request_ref", ""))
        house = copy.deepcopy(self.read(HOUSE_PATH))
        requests = house.get("development_requests", {})
        request = requests.get(request_ref) if isinstance(requests, Mapping) else None
        if not isinstance(request, Mapping) or request.get("status") == "settled":
            return
        rules = self.read(DEVELOPMENT_RULES_PATH)
        cfg = rules.get("inner_walls_expansion", {}) if isinstance(rules, Mapping) else {}
        target_site_ref = str(cfg.get("target_site_ref", "loc_tang_inner_walls"))
        source_site_ref = str(cfg.get("economic_source_site_ref", "loc_tang_manor"))
        project_ref = "project_house_tang_inner_walls_" + hashlib.sha256(request_ref.encode("utf-8")).hexdigest()[:16]
        programs = house.setdefault("administrative_programs", {})
        existing = programs.get("inner_walls_expansion")
        if isinstance(existing, Mapping) and existing.get("status") == "active":
            summary = f"Tang Ling confirms that Inner Walls expansion is already underway as {existing.get('project_ref', project_ref)}."
            result = dict(existing)
        else:
            rows = cfg.get("capacity_projects", []) if isinstance(cfg, Mapping) else []
            if not isinstance(rows, list) or not rows:
                raise ValueError("Inner Walls expansion has no registered current infrastructure work")
            work_entries: list[dict[str, Any]] = []
            total_silver = 0
            total_material = 0
            total_labor = 0
            labor_by_class: dict[str, int] = {}
            workfront_capacity = 0
            critical_path = 1
            for index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    raise ValueError("Inner Walls capacity project row is invalid")
                blueprint_ref = str(row.get("blueprint_ref", ""))
                quantity = max(1, int(row.get("quantity", 1)))
                work = infrastructure_work_spec(
                    self.read, blueprint_ref=blueprint_ref, target_site_ref=target_site_ref, quantity=quantity
                )
                work_ref = f"{project_ref}.work{index + 1:02d}"
                work_entries.append({"work_ref": work_ref, "work": work})
                total_silver += int(work.get("silver_cost", 0))
                total_material += int(work.get("construction_material_units", 0))
                total_labor += int(work.get("labor_hours", 0))
                workfront_capacity += max(1, int(work.get("workfront_capacity_workers", 1)))
                critical_path = max(critical_path, int(work.get("minimum_calendar_hours", 1)))
                for labor_class, hours in (work.get("labor_hours_by_class", {}) or {}).items():
                    labor_by_class[str(labor_class)] = labor_by_class.get(str(labor_class), 0) + max(0, int(hours))

            treasury = copy.deepcopy(self.read(TREASURY_PATH))
            house_rules = self.read(HOUSE_RULES_PATH)
            safe = _treasury_safe_ceiling(treasury, house_rules)
            ep, eco = self._private_economy("qin")
            _local_ref, local_eco = self._local_economy_region("qin", eco, source_site_ref)
            commodities = local_eco.setdefault("commodity_stock", {})
            available_material = max(0, int(commodities.get("construction_material_units", 0)))

            _pop_path, population, population_site_ref = self._local_population_site_for_location("qin", source_site_ref)
            pop_row = population.get("local_population", {}).get("sites", {}).get(population_site_ref, {})
            strata = pop_row.get("civilian_strata", {}) if isinstance(pop_row, Mapping) else {}
            craft_workers = max(0, int(strata.get("craft_and_industry", 0))) if isinstance(strata, Mapping) else 0
            labor_rules = self._civil_rules().get("labor", {})
            construction_fraction = max(0.0, min(1.0, float(labor_rules.get("construction_labor_fraction_of_craft_workers", 0.12))))
            construction_pool = max(1, int(math.floor(craft_workers * construction_fraction)))
            labor = eco.setdefault("labor_allocation", {})
            active_projects = labor.setdefault("projects", {})
            if not isinstance(active_projects, dict):
                raise ValueError("private economy project labor allocation is invalid")
            now = CampaignTime.parse(at)
            active_workers = sum(
                max(0, int(row.get("workers", 0)))
                for row in active_projects.values()
                if isinstance(row, Mapping)
                and (not isinstance(row.get("releases_at"), str) or CampaignTime.parse(str(row.get("releases_at"))) > now)
            )
            available_workers = max(0, construction_pool - active_workers)
            aggregate_work = {
                "labor_hours": total_labor,
                "minimum_calendar_hours": critical_path,
                "workfront_capacity_workers": max(1, workfront_capacity),
            }
            schedule = None if available_workers <= 0 else calculate_project_schedule(
                self.read, work=aggregate_work, available_workers=available_workers
            )
            blocked = []
            if total_silver > safe["treasury_safe_ceiling_silver"] or total_silver > int(treasury.get("silver", 0)):
                blocked.append("treasury")
            if total_material > available_material:
                blocked.append("construction_materials")
            if schedule is None:
                blocked.append("construction_labor")

            land_pending = copy.deepcopy(self.read(LAND_STATE_PATH))
            land_reservations: list[dict[str, Any]] = []
            if not blocked:
                try:
                    land_rules = self.read(LAND_RULES_PATH)
                    for entry in work_entries:
                        reservation = reserve_site_land(
                            land_pending,
                            site_ref=target_site_ref,
                            project_ref=str(entry["work_ref"]),
                            work=entry["work"],
                            rules=land_rules,
                        )
                        land_reservations.append(reservation)
                except ValueError:
                    blocked.append("developable_land")

            if blocked:
                result = {
                    "status": "blocked_by_resources",
                    "blocked": sorted(set(blocked)),
                    "required_inputs": {
                        "silver": total_silver,
                        "construction_material_units": total_material,
                        "labor_hours": total_labor,
                    },
                    "available_inputs": {
                        "treasury_safe_ceiling_silver": safe["treasury_safe_ceiling_silver"],
                        "treasury_silver": int(treasury.get("silver", 0)),
                        "construction_material_units": available_material,
                        "construction_workers": available_workers,
                    },
                }
                summary = "Tang Ling declines to start the Inner Walls expansion because the registered construction package lacks current conserved resources: " + ", ".join(sorted(set(blocked))) + "."
            else:
                assert schedule is not None
                treasury["silver"] = int(treasury.get("silver", 0)) - total_silver
                local_eco["cash_silver"] = int(local_eco.get("cash_silver", 0)) + total_silver
                self._record_private_realized_sale(
                    local_eco, amount_silver=total_silver, at=at, kind="house_tang_inner_walls_construction",
                    resource="construction_material_units", quantity=total_material,
                )
                commodities["construction_material_units"] = available_material - total_material
                duration_hours = max(1, int(schedule["duration_hours"]))
                due = now.add_seconds(duration_hours * 3600)
                required_workers = max(1, int(schedule["construction_workers"]))
                active_projects[project_ref] = {
                    "workers": required_workers,
                    "labor_hours": total_labor,
                    "allocated_at": at,
                    "releases_at": str(due),
                    "institution_ref": "house_tang",
                    "location_ref": source_site_ref,
                }
                labor["construction_worker_pool"] = construction_pool
                labor["allocated_construction_workers"] = active_workers + required_workers
                project = {
                    "project_ref": project_ref,
                    "status": "active",
                    "started_at": at,
                    "completion_due_at": str(due),
                    "target_site_ref": target_site_ref,
                    "economic_source_site_ref": source_site_ref,
                    "physical_work_specs": work_entries,
                    "inputs_reserved": {
                        "silver": total_silver,
                        "construction_material_units": total_material,
                        "labor_hours": total_labor,
                        "labor_hours_by_class": labor_by_class,
                        "construction_workers": required_workers,
                    },
                    "construction_schedule": schedule,
                    "land_reservations": land_reservations,
                }
                programs["inner_walls_expansion"] = project
                self.put(TREASURY_PATH, treasury)
                self.put(LAND_STATE_PATH, land_pending)
                self._sync_local_economy_aggregate(eco)
                self._write_private_economy(ep, eco)
                self.put(HOUSE_PATH, house)
                self._schedule_expansion_completion(project_ref, due)
                intake = _perform_house_requested_military_intake(self, at=at, request_ref=request_ref)
                status = _house_tang_force_status(self)
                house = copy.deepcopy(self.read(HOUSE_PATH))
                programs = house.setdefault("administrative_programs", {})
                project = dict(programs.get("inner_walls_expansion", project))
                project["initial_intake_count"] = int(intake.get("intake_count", 0))
                programs["inner_walls_expansion"] = project
                self.put(HOUSE_PATH, house)
                result = {**project, "treasury_safe_ceiling_before_start_silver": safe["treasury_safe_ceiling_silver"], "treasury_silver_after_start": int(treasury.get("silver", 0)), "house_force": status}
                summary = f"Tang Ling and Tang Zhu start the registered Inner Walls construction package for {total_silver} silver and {total_material} construction-material units. {int(intake.get('intake_count', 0))} replacement soldiers can be admitted immediately only where a real establishment vacancy and existing conserved applicants, equipment, remounts, and built capacity permit it. Construction is due to complete at {due}."
        event_ref = _response_event(self, request_ref=request_ref, at=at, summary=summary)
        house = copy.deepcopy(self.read(HOUSE_PATH))
        requests = house.setdefault("development_requests", {})
        mutable = dict(requests[request_ref])
        mutable.update({"status": "settled", "settled_at": at, "response_event_ref": event_ref, "response_summary": summary[:4000], "result": copy.deepcopy(dict(result))})
        requests[request_ref] = mutable
        house["last_review"] = at
        self.put(HOUSE_PATH, house)

    def _settle_expansion_completion(self, host: Mapping[str, Any], at: str) -> None:
        house = copy.deepcopy(self.read(HOUSE_PATH))
        programs = house.get("administrative_programs", {}) if isinstance(house.get("administrative_programs"), Mapping) else {}
        project = programs.get("inner_walls_expansion") if isinstance(programs, Mapping) else None
        if not isinstance(project, dict) or project.get("status") != "active":
            return
        if host.get("project_ref") != project.get("project_ref"):
            raise ValueError("Inner Walls expansion completion lost its project owner")
        target_site_ref = str(project.get("target_site_ref", "loc_tang_inner_walls"))
        entries = project.get("physical_work_specs", [])
        if not isinstance(entries, list) or not entries:
            raise ValueError("Inner Walls expansion lost its registered physical work")
        infrastructure = copy.deepcopy(self.read(SETTLEMENT_INFRASTRUCTURE))
        land = copy.deepcopy(self.read(LAND_STATE_PATH))
        completed_works: list[dict[str, Any]] = []
        completed_land: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("work"), Mapping):
                raise ValueError("Inner Walls expansion work entry is invalid")
            work_ref = str(entry.get("work_ref", ""))
            if not work_ref:
                raise ValueError("Inner Walls expansion work entry has no exact reference")
            land_result = apply_site_land_reservation(land, site_ref=target_site_ref, project_ref=work_ref)
            if isinstance(land_result, Mapping):
                completed_land.append({"work_ref": work_ref, **dict(land_result)})
            record = apply_infrastructure_work(infrastructure, work=entry["work"], project_ref=work_ref, completed_at=at)
            completed_works.append(record)

        ep, eco = self._private_economy("qin")
        labor = eco.setdefault("labor_allocation", {})
        projects = labor.setdefault("projects", {})
        if isinstance(projects, dict):
            projects.pop(str(project.get("project_ref", "")), None)
            now = CampaignTime.parse(at)
            labor["allocated_construction_workers"] = sum(
                max(0, int(row.get("workers", 0)))
                for row in projects.values()
                if isinstance(row, Mapping)
                and (not isinstance(row.get("releases_at"), str) or CampaignTime.parse(str(row.get("releases_at"))) > now)
            )
        self._sync_local_economy_aggregate(eco)
        self._write_private_economy(ep, eco)
        self.put(SETTLEMENT_INFRASTRUCTURE, infrastructure)
        self.put(LAND_STATE_PATH, land)

        compact_project = {
            "project_ref": str(project.get("project_ref", "")),
            "status": "completed",
            "started_at": str(project.get("started_at", "")),
            "completed_at": at,
            "completed_work_refs": [str(row.get("project_ref", "")) for row in completed_works],
        }
        programs["inner_walls_expansion"] = compact_project
        self.put(HOUSE_PATH, house)
        status = _house_tang_force_status(self)
        _emit_watch_report(
            self, player_ref="char_tang_wei", at=at,
            key=f"inner_walls_expansion_complete:{compact_project['project_ref']}",
            summary=(f"House Tang reports that Inner Walls expansion {compact_project['project_ref']} is complete. "
                     f"Built military, training, and medical capacity has increased through registered physical works. "
                     f"Current practical replacement intake is {status['practical_intake_now']}, with a 30-day assessment throughput of {status['physical_intake_throughput_30d']}."),
        )

    def _enrich_world_arc_report(self, source_event_ref: str) -> None:
        source = get_causal_event(self, source_event_ref)
        report_ref = f"{source_event_ref}.report"
        report = get_causal_event(self, report_ref)
        if not isinstance(source, Mapping) or not isinstance(report, Mapping):
            return
        provenance = report.get("provenance") if isinstance(report.get("provenance"), Mapping) else {}
        if int(provenance.get("public_detail_version", 0)) >= 1:
            return
        result = str(source.get("result", ""))
        actor = _public_owner_label(source.get("actor_ref"))
        target = _public_owner_label(source.get("target_ref")) if source.get("target_ref") else "its reported objective"
        detail = ""
        if result == "material_action_settled":
            src_prov = source.get("provenance") if isinstance(source.get("provenance"), Mapping) else {}
            evidence = src_prov.get("material_evidence") if isinstance(src_prov.get("material_evidence"), Mapping) else {}
            kind = str(evidence.get("kind", ""))
            if kind == "exact_operation_created":
                detail = f" The material evidence is specific enough to establish that {actor} has opened an actual military operation directed at {target} and assigned an existing formation to it. The delivered channels do not establish the formation's size, exact route, supply state, combat contact, or result."
            elif kind in {"exact_operation_transition", "exact_operation_advanced"}:
                detail = f" The material evidence establishes that an existing operation owned by {actor} has advanced to a new settled operational state against {target}. The delivered channels do not establish undisclosed orders, force size, or combat outcome."
            elif kind in {"exact_formation_moved", "exact_formation_state_change"}:
                detail = f" The material evidence establishes a real formation-level movement or state change by {actor} connected to {target}. Exact strength and undisclosed destination details remain outside this report."
            else:
                detail = f" The source carries concrete actor-owned evidence that {actor} completed a real domain action connected to {target}, rather than merely recording intent. The delivered channels do not establish additional tactical particulars."
        elif result == "work_blocked":
            detail = f" The available evidence establishes that {actor}'s attempted move toward {target} failed to satisfy a concrete domain requirement; no success is inferred from the attempt."
        if not detail:
            return
        _path, owner = read_causal_event_owner(self)
        mutable = owner.get("causal_events", {}).get(report_ref)
        if not isinstance(mutable, dict):
            return
        mutable["summary"] = (str(mutable.get("summary", "")).rstrip() + detail)[:4000]
        mutable_prov = mutable.setdefault("provenance", {})
        mutable_prov["public_detail_version"] = 1
        owner.setdefault("runtime", {})["last_settled_at"] = str(report.get("triggered_at", report.get("due_at", "")))
        write_causal_event_owner(self, owner)

    def _autonomy_house_tang_training(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        """Advance the unified two-species House Tang professional force.

        This monthly owner deliberately has no rank/species promotion ladder. The
        same conserved House Infantry and House Cavalry cohorts improve their real
        attributes/skills through the normal deterministic cohort training engine.
        Replacement recruitment remains vacancy-, equipment-, remount-, and
        population-bounded through household_request_flow; this host never mints
        bodies merely because a review occurred.
        """
        occurrences = max(0, int(occurrences))
        if not occurrences:
            return
        house = deepcopy(self.read(HOUSE_FORCE))
        manor = deepcopy(self.read(MANOR_POPULATION))
        qin = deepcopy(self.read(QIN_POPULATION))
        ensure_cohort_ledger(house, at=at)
        roles = set(str(r) for r in house.get("authorized_by_role", {}))
        if roles != {"house_infantry", "house_cavalry"}:
            raise ValueError(f"House Tang active troop taxonomy must be exactly infantry/cavalry, got {sorted(roles)}")
        for cycle in range(occurrences):
            event_ref = f"house_tang_training:{at}:{cycle}"
            self._fc_train(house, "house_tang_max_sustainable", 1, event_ref)
            # Civilian household growth remains independent of military replacement
            # intake and therefore cannot fill a military vacancy by side effect.
            manor.setdefault("recruitment_runtime", {})["last_civil_intake"] = self._civil_intake(
                qin, manor, at=at, cycle_ref=event_ref
            )
        house["cohort_training_closes"] = int(house.get("cohort_training_closes", 0)) + occurrences
        house["last_review"] = at
        manor.setdefault("recruitment_runtime", {})["last_review"] = at
        validate_cohort_ledger(house)
        self.put(HOUSE_FORCE, house)
        self.put(MANOR_POPULATION, manor)
        self.put(QIN_POPULATION, qin)
        runtime = deepcopy(self.read(RUNTIME_PATH))
        runtime["last_house_tang_training_review"] = at
        self.put(RUNTIME_PATH, runtime)
        sync_tang_private_population(
            self,
            at=at,
            reason="house_tang_monthly_training_and_civil_settlement",
            evidence_ref=f"house_tang_training:{at}",
        )

    # Due-host settlement is centrally dispatched by time_integration.py.



__all__ = ["HouseTangDevelopmentMixin"]
