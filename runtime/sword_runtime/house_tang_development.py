"""Causal House Tang and Sword Manor aggregate development.

Sword Manor, House Guards, Guardian Cavalry, and Tang Champions remain aggregate
cohorts at Sword & Banners scale. Monthly settlement advances verified cohort
training, moves only eligible conserved headcount through the progression ladder,
and performs capacity-bounded recruitment without creating people from nothing.

This module also owns the House-specific Sword Manor expansion lifecycle. Exact candidate bodies remain conserved through the ordinary population and cohort authorities.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import (
    conserved_establishment_role_count,
    add_recruits,
    consume_population_recruits,
    ensure_cohort_ledger,
    qualification_capacity,
    record_recruitment_cohort,
    role_count,
    transfer_between_forces,
    transfer_role,
    validate_cohort_ledger,
)
from sword_runtime.history_store import recent_history_events
from sword_runtime.household_request_flow import (
    _emit_watch_report,
    _perform_house_requested_sword_intake,
    _response_event,
    _sword_manor_status,
    _treasury_safe_ceiling,
)
from sword_runtime.recruitment_campaigns import (
    PROFILE_PATH as CANDIDATE_PROFILE_PATH,
    REGISTRY_PATH as CANDIDATE_REGISTRY_PATH,
    _apportion,
    _credit_recruitment_payment,
    _registry as _candidate_registry,
    _slice_id,
)
from sword_runtime.sim.calendar import CampaignTime

SWORD_FORCE = "state/forces/sword-manor.json"
HOUSE_FORCE = "state/forces/house-tang.json"
QIN_POPULATION = "state/population/qin.json"
MANOR_POPULATION = "state/population/tang-manor.json"
SETTLEMENT_INFRASTRUCTURE = "state/infrastructure/settlements.json"
SWORD_PROGRESSION = "state/prog/sword-manor-progression.json"
CHAMPION_PROGRESSION = "state/prog/house-tang-champion-progression.json"
HOUSE_PATH = "state/houses/house_tang.json"
TREASURY_PATH = "state/treasury/treasury-house-tang.json"
RUNTIME_PATH = "state/runtime.json"
HOUSE_RULES_PATH = "game/data/mechanics/house-tang-programs.json"
DEVELOPMENT_RULES_PATH = "game/data/mechanics/house-tang-development.json"
TRAINING_GROUND = "loc_tang_manor_training_ground"
GARRISON = "loc_tang_manor_garrison_yard"
MONTH_SECONDS = 30 * 86400
_HISTORY_WINDOW = 256
_EXPANSION_REQUEST_KIND = "sword_manor_infrastructure_expansion"
_EXPANSION_PRIORITY = 53


def _records(doc: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row["record_id"]): row
        for row in doc.get("records", [])
        if isinstance(row, Mapping) and row.get("record_id")
    }


def _allocation_count(value: Any) -> int:
    return int(value.get("personnel", 0)) if isinstance(value, Mapping) else int(value)


def _months(value: Any, default: int = 0) -> int:
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else default


def _request_ids(request_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(("house-development-request|" + request_id).encode("utf-8")).hexdigest()[:20]
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
    if "sword manor" not in text:
        return False
    expansion = any(term in text for term in ("expand", "expanding", "infrastructure", "capacity", "build", "construction"))
    intake = any(term in text for term in ("recruit", "recruiting", "intake", "initiate", "initiates"))
    development = any(term in text for term in ("train", "training", "promote", "promoting", "promotion"))
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
    "sword_manor_civilian_medical": "camp_medical_support",
    "administrative_clerks": "administration_and_education",
    "water_sanitation_and_firefighting": "household_and_service",
}


class HouseTangDevelopmentMixin:
    def _qualified_reserve(
        self,
        force: Mapping[str, Any],
        role: str,
        row: Mapping[str, Any],
        location_ref: str,
        minimum_service_months: int = 0,
    ) -> int:
        facts = row.get("facts", {}) if isinstance(row, Mapping) else {}
        total = 0
        for cohort in force.get("cohort_ledger", {}).get("cohorts", {}).values():
            if not isinstance(cohort, Mapping) or str(cohort.get("role")) != role:
                continue
            available = int(cohort.get("reserve_by_location", {}).get(location_ref, 0))
            if available <= 0:
                continue
            total += qualification_capacity(
                cohort,
                minimum_attribute_values=facts.get("minimum_attribute_values"),
                minimum_skill_values=facts.get("minimum_skill_values"),
                minimum_service_months=minimum_service_months,
                available_count=available,
            )
        return total

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
            history = manor.setdefault("civil_recruitment_history", [])
            history.append({"at": at, "ref": cycle_ref, "count": moved, "source_population_ref": "population_qin", "mix": mix})
            manor["civil_recruitment_history"] = history[-24:]
        return moved

    def _normalize_sword_manor_host(self, runtime: dict[str, Any]) -> None:
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        now = CampaignTime.parse(str(runtime["world_time"]))
        for host_id, host in hosts.items():
            if not isinstance(host_id, str) or not isinstance(host, dict):
                continue
            if host.get("owner_ref") != "force_sword_manor" and host_id != "host_sword_manor":
                continue
            host["kind"] = "sword_manor"
            host["recurrence_seconds"] = MONTH_SECONDS
            desired = now.add_seconds(MONTH_SECONDS)
            current_due = CampaignTime.parse(str(host["next_due"])) if isinstance(host.get("next_due"), str) else desired
            if current_due > desired:
                host["next_due"] = str(desired)
                host["safe_through"] = str(desired.add_seconds(-1))
                for event in events:
                    if isinstance(event, dict) and event.get("target_host") == host_id:
                        event["due_at"] = str(desired)
                        break
            break

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
        for event in recent_history_events(self, _HISTORY_WINDOW):
            if not isinstance(event, Mapping):
                continue
            attempt = parse_interaction_attempt_summary(event.get("summary"))
            if not isinstance(attempt, Mapping) or not _is_expansion_request(attempt):
                continue
            request_id = attempt.get("request_id")
            requested_at = event.get("at")
            if not isinstance(request_id, str) or not request_id or not isinstance(requested_at, str):
                continue
            if request_id not in requests:
                requests[request_id] = {
                    "request_id": request_id,
                    "kind": _EXPANSION_REQUEST_KIND,
                    "status": "queued",
                    "requested_at": requested_at,
                    "source_event_id": event.get("event_id"),
                    "target_ref": attempt.get("target_ref"),
                    "player_statement": str(attempt.get("player_statement", ""))[:2000],
                }
                changed = True
            if requests[request_id].get("status") == "settled":
                continue
            host_id, event_id = _request_ids(request_id)
            if host_id in hosts:
                continue
            due = CampaignTime.parse(requested_at).add_seconds(3600)
            if due < now:
                due = now
            hosts[host_id] = {
                "host_id": host_id,
                "kind": "house_development_request",
                "owner_ref": "house_tang",
                "request_id": request_id,
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
        request_id = str(host.get("request_id", ""))
        house = copy.deepcopy(self.read(HOUSE_PATH))
        requests = house.get("development_requests", {})
        request = requests.get(request_id) if isinstance(requests, Mapping) else None
        if not isinstance(request, Mapping) or request.get("status") == "settled":
            return
        rules = self.read(DEVELOPMENT_RULES_PATH)
        cfg = rules.get("sword_manor_expansion", {}) if isinstance(rules, Mapping) else {}
        project_ref = str(cfg.get("project_ref", "project_house_tang_sword_manor_expansion_i"))
        programs = house.setdefault("administrative_programs", {})
        existing = programs.get("sword_manor_expansion")
        if isinstance(existing, Mapping) and existing.get("status") == "active":
            summary = f"Tang Ling confirms that Sword Manor expansion is already underway as {existing.get('project_ref', project_ref)}."
            result = dict(existing)
        else:
            treasury = copy.deepcopy(self.read(TREASURY_PATH))
            house_rules = self.read(HOUSE_RULES_PATH)
            safe = _treasury_safe_ceiling(treasury, house_rules)
            cost = max(0, int(cfg.get("start_cost_silver", 1800000)))
            if cost > safe["treasury_safe_ceiling_silver"] or cost > int(treasury.get("silver", 0)):
                summary = f"Tang Ling declines to start the registered Sword Manor expansion tranche because its {cost} silver start cost exceeds the current treasury-safe discretionary ceiling of {safe['treasury_safe_ceiling_silver']} silver."
                result = {"status": "blocked_by_treasury_safety", "start_cost_silver": cost, "treasury": safe}
            else:
                treasury["silver"] = int(treasury.get("silver", 0)) - cost
                duration = max(3600, int(cfg.get("construction_seconds", 60 * 86400)))
                due = CampaignTime.parse(at).add_seconds(duration)
                capacity_add = cfg.get("completion_capacity_add", {}) if isinstance(cfg, Mapping) else {}
                if not isinstance(capacity_add, Mapping):
                    raise ValueError("Sword Manor expansion physical-capacity additions are invalid")
                project = {
                    "project_ref": project_ref,
                    "status": "active",
                    "started_at": at,
                    "completion_due_at": str(due),
                    "start_cost_silver": cost,
                    "physical_capacity_ref": "state/infrastructure/settlements.json#/sites/loc_tang_manor/sword_manor",
                    "completion_capacity_add": {
                        str(key): max(0, int(value))
                        for key, value in capacity_add.items()
                        if isinstance(key, str)
                    },
                    "standards_rule": "expansion changes only constructed Sword Manor support systems; no fixed personnel cap exists and recruitment/promotion standards remain unchanged",
                }
                programs["sword_manor_expansion"] = project
                self.put(TREASURY_PATH, treasury)
                self.put(HOUSE_PATH, house)
                self._schedule_expansion_completion(project_ref, due)
                intake = _perform_house_requested_sword_intake(self, at=at, request_id=request_id)
                status = _sword_manor_status(self)
                house = copy.deepcopy(self.read(HOUSE_PATH))
                programs = house.setdefault("administrative_programs", {})
                project = dict(programs.get("sword_manor_expansion", project))
                project["initial_intake_count"] = int(intake.get("intake_count", 0))
                project["initial_status"] = status
                programs["sword_manor_expansion"] = project
                self.put(HOUSE_PATH, house)
                result = {**project, "treasury_safe_ceiling_before_start_silver": safe["treasury_safe_ceiling_silver"], "treasury_silver_after_start": int(treasury.get("silver", 0)), "sword_manor": status}
                summary = (f"Tang Ling and Tang Zhu start the Sword Manor expansion tranche for {cost} silver. {int(intake.get('intake_count', 0))} new Initiates can be admitted now only where conserved applicants and the already-built physical support systems permit it. Construction is due to complete at {due}; completion expands registered dormitory, instruction, training, water, dining, medical, assessment, and induction capacity. No fixed Sword Manor personnel cap is created, and the ordinary training and promotion standards remain unchanged.")
        event_ref = _response_event(self, request_id=request_id, at=at, summary=summary)
        house = copy.deepcopy(self.read(HOUSE_PATH))
        requests = house.setdefault("development_requests", {})
        mutable = dict(requests[request_id])
        mutable.update({"status": "settled", "settled_at": at, "response_event_ref": event_ref, "response_summary": summary[:4000], "result": copy.deepcopy(dict(result))})
        requests[request_id] = mutable
        house["last_review"] = at
        self.put(HOUSE_PATH, house)

    def _settle_expansion_completion(self, host: Mapping[str, Any], at: str) -> None:
        house = copy.deepcopy(self.read(HOUSE_PATH))
        programs = house.get("administrative_programs", {}) if isinstance(house.get("administrative_programs"), Mapping) else {}
        project = programs.get("sword_manor_expansion") if isinstance(programs, Mapping) else None
        if not isinstance(project, dict) or project.get("status") != "active":
            return
        if host.get("project_ref") != project.get("project_ref"):
            raise ValueError("Sword Manor expansion completion lost its project owner")
        infrastructure = copy.deepcopy(self.read(SETTLEMENT_INFRASTRUCTURE))
        sites = infrastructure.get("sites")
        if not isinstance(sites, dict):
            raise ValueError("settlement infrastructure registry is invalid")
        tang_site = sites.get("loc_tang_manor")
        if not isinstance(tang_site, dict):
            raise ValueError("Tang Manor infrastructure owner is missing")
        sm = tang_site.get("sword_manor")
        if not isinstance(sm, dict):
            raise ValueError("Sword Manor physical-capacity owner is missing")
        additions = project.get("completion_capacity_add", {})
        if not isinstance(additions, Mapping):
            raise ValueError("Sword Manor expansion lost its physical work specification")
        for key, value in additions.items():
            if key not in {
                "trainee_dormitory_beds",
                "total_residential_beds",
                "instruction_capacity_people",
                "dining_capacity_people_per_day",
                "water_capacity_people_per_day",
                "medical_support_capacity_people",
                "training_space_capacity_people",
                "intake_assessment_candidates_per_day",
                "induction_equipment_issue_capacity_per_30d",
            }:
                raise ValueError(f"unsupported Sword Manor physical-capacity work: {key}")
            sm[key] = max(0, int(sm.get(key, 0))) + max(0, int(value))
        project["status"] = "completed"
        project["completed_at"] = at
        project["final_physical_capacity"] = {
            str(key): int(sm.get(key, 0)) for key in additions
        }
        programs["sword_manor_expansion"] = project
        self.put(SETTLEMENT_INFRASTRUCTURE, infrastructure)
        self.put(HOUSE_PATH, house)
        status = _sword_manor_status(self)
        _emit_watch_report(self, player_ref="char_tang_wei", at=at, key=f"sword_manor_expansion_complete:{project['project_ref']}", summary=(f"House Tang reports that Sword Manor expansion {project['project_ref']} is complete. Physical trainee capacity is now {status['physical_trainee_capacity']}, with a 30-day assessment throughput of {status['physical_intake_throughput_30d']}. Recruitment, training, and promotion remain conserved and standards-driven; there is no fixed personnel cap."))

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

    def _autonomy_manor(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        occurrences = max(0, int(occurrences))
        if not occurrences:
            return
        sword = deepcopy(self.read(SWORD_FORCE))
        house = deepcopy(self.read(HOUSE_FORCE))
        qin = deepcopy(self.read(QIN_POPULATION))
        manor = deepcopy(self.read(MANOR_POPULATION))
        progression = deepcopy(self.read(SWORD_PROGRESSION))
        champion_progression = deepcopy(self.read(CHAMPION_PROGRESSION))
        ensure_cohort_ledger(sword, at=at)
        ensure_cohort_ledger(house, at=at)
        sword_rules = _records(progression)
        champion_rules = _records(champion_progression)
        profiles = self._fc_profiles()
        for cycle in range(occurrences):
            event_ref = f"sword_manor:{at}:{cycle}"
            self._fc_train(sword, "house_tang_max_sustainable", 1, event_ref)
            self._fc_train(house, "house_tang_max_sustainable", 1, event_ref + ":house")
            # _fc_train owns both aggregate cohorts and materialized person-lite
            # officers, so no second individual training settlement is needed here.
            ladder = (("trainee", "junior_disciple", "trainee_to_junior_disciple", "required_verified_training_months"), ("junior_disciple", "general_disciple", "junior_to_general_disciple", "required_verified_service_months_at_junior"), ("general_disciple", "senior_disciple", "general_to_senior_disciple", "required_verified_service_months_at_general"))
            for source, destination, record_id, service_key in ladder:
                row = sword_rules.get(record_id, {})
                facts = row.get("facts", {}) if isinstance(row, Mapping) else {}
                eligible = self._qualified_reserve(sword, source, row, TRAINING_GROUND, _months(facts.get(service_key), 0))
                transfer_role(sword, source, destination, eligible, location_ref=TRAINING_GROUND, evidence_ref=f"{event_ref}:{record_id}")
            caps = house.setdefault("authorized_by_role", {"house_guard": 700, "guardian_cavalry": 300, "tang_champion": 100})
            guard_vacancy = max(0, int(caps.get("house_guard", 700)) - conserved_establishment_role_count(house, "house_guard"))
            guard_rule = sword_rules.get("house_guard_candidate", {})
            transfer_between_forces(sword, house, source_role="senior_disciple", destination_role="house_guard", count=min(guard_vacancy, self._qualified_reserve(sword, "senior_disciple", guard_rule, TRAINING_GROUND)), source_location_ref=TRAINING_GROUND, destination_location_ref=GARRISON, evidence_ref=f"{event_ref}:guard")
            cavalry_vacancy = max(0, int(caps.get("guardian_cavalry", 300)) - conserved_establishment_role_count(house, "guardian_cavalry"))
            cavalry_rule = sword_rules.get("house_guard_to_house_guardian_cavalry", {})
            transfer_role(house, "house_guard", "guardian_cavalry", min(cavalry_vacancy, self._qualified_reserve(house, "house_guard", cavalry_rule, GARRISON)), location_ref=GARRISON, evidence_ref=f"{event_ref}:cavalry")
            champion_vacancy = max(0, int(caps.get("tang_champion", 100)) - conserved_establishment_role_count(house, "tang_champion"))
            champion_rule = champion_rules.get("guardian_cavalry_to_tang_champion", {})
            champion_facts = champion_rule.get("facts", {}) if isinstance(champion_rule, Mapping) else {}
            eligible_champions = self._qualified_reserve(house, "guardian_cavalry", champion_rule, GARRISON, int(champion_facts.get("minimum_verified_service_months_at_guardian_cavalry", 24)))
            transfer_role(house, "guardian_cavalry", "tang_champion", min(champion_vacancy, eligible_champions), location_ref=GARRISON, evidence_ref=f"{event_ref}:champion")
            status = _sword_manor_status(self)
            wanted = max(0, int(status.get("practical_intake_now", 0)))
            moved, source_mix = consume_population_recruits(qin, wanted, source_roles=("agricultural", "craft_and_industry", "household_and_service", "merchant_and_transport"), destination_role="private_household_military")
            for source, count in source_mix.items():
                add_recruits(sword, "trainee", count, location_ref=TRAINING_GROUND)
                record_recruitment_cohort(sword, role="trainee", count=count, location_ref=TRAINING_GROUND, source_population_ref="population_qin", source_stratum=source, recruited_at=at, profile_registry=profiles, selection_profile="sword_manor_screened_initiate", provenance_ref=f"{event_ref}:intake:{source}")
            manor.setdefault("sword_manor", {})["provisional_trainees"] = conserved_establishment_role_count(sword, "trainee")
            runtime = manor.setdefault("recruitment_runtime", {})
            runtime["last_sword_manor_intake"] = moved
            runtime["last_civil_intake"] = self._civil_intake(qin, manor, at=at, cycle_ref=event_ref)
        sword["cohort_training_closes"] = int(sword.get("cohort_training_closes", 0)) + occurrences
        sword["last_review"] = at
        manor.setdefault("recruitment_runtime", {})["last_review"] = at
        progression.setdefault("runtime", {})["last_settled_at"] = at
        progression["runtime"]["completed_monthly_reviews"] = int(progression["runtime"].get("completed_monthly_reviews", 0)) + occurrences
        validate_cohort_ledger(sword)
        validate_cohort_ledger(house)
        self.put(SWORD_FORCE, sword)
        self.put(HOUSE_FORCE, house)
        self.put(QIN_POPULATION, qin)
        self.put(MANOR_POPULATION, manor)
        self.put(SWORD_PROGRESSION, progression)
        self.put(CHAMPION_PROGRESSION, champion_progression)

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read(RUNTIME_PATH))
        self._normalize_sword_manor_host(runtime)
        self._sync_house_development_requests(runtime)
        self.put(RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)


    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        kind = host.get("kind")
        if kind == "house_development_request":
            self._settle_expansion_request(host, due_text)
            self._pending_wake_created = None
            return
        if kind == "house_development_completion":
            self._settle_expansion_completion(host, due_text)
            self._pending_wake_created = None
            return
        if kind == "world_arc_report" and isinstance(host.get("source_event_ref"), str):
            source_event_ref = str(host["source_event_ref"])
            super()._run_due_host(host, due_text)
            self._enrich_world_arc_report(source_event_ref)
            return
        super()._run_due_host(host, due_text)



__all__ = ["HouseTangDevelopmentMixin"]
