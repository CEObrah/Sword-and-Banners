from __future__ import annotations

import copy
import math
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from sword_runtime.cohort_personnel import (
    add_recruits,
    apply_selection_profile,
    record_recruitment_cohort,
    take_reserve_slices,
    validate_cohort_ledger,
)
from sword_runtime.officer_cadre import reorganize_officer_cadre
from sword_runtime.officer_personnel import sync_materialized_officer_billets
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_programs import REGISTRY_PATH as TRAINING_PROGRAM_REGISTRY_PATH, resolve_program_ref, settle_cohort_program
from sword_runtime.training_instructors import instructor_contexts_for_program
from sword_runtime.training_facilities import program_facility_access

_POLICY_PATH = "game/data/mechanics/bastion-corps.json"
_PROFILE_PATH = "game/data/mil/recruitment-cohort-profiles.json"
_TRAINING_PATH = "game/data/mechanics/training.json"
_INFRA_PATH = "state/infrastructure/settlements.json"
_POP_PATH = "state/population/qin.json"
TANG_POPULATION_PATH = "state/population/tang-manor.json"
_LOCATION = "loc_tang_manor_defense_camp"
_SITE = "loc_tang_manor"
_FORCE_PATHS = {
    "iron_rampart": "state/forces/bastion-iron-rampart.json",
    "red_crane": "state/forces/bastion-red-crane.json",
    "white_lantern": "state/forces/bastion-white-lantern.json",
    "deep_earth": "state/forces/bastion-deep-earth.json",
}


def _apportion(total: int, weights: Mapping[str, Any], capacities: Mapping[str, Any] | None = None) -> dict[str, int]:
    target = max(0, int(total))
    if target <= 0:
        return {}
    clean = {str(k): max(0.0, float(v)) for k, v in weights.items() if float(v) > 0}
    if not clean:
        return {}
    caps = {k: max(0, int((capacities or {}).get(k, target))) for k in clean}
    if sum(caps.values()) < target:
        target = sum(caps.values())
    if target <= 0:
        return {}
    remaining = target
    result = {k: 0 for k in clean}
    active = {k for k in clean if caps[k] > 0}
    while remaining > 0 and active:
        weight_sum = sum(clean[k] for k in active)
        exact = {k: remaining * clean[k] / weight_sum for k in active}
        bases = {k: min(caps[k] - result[k], int(math.floor(exact[k]))) for k in active}
        moved = sum(max(0, v) for v in bases.values())
        for k, n in bases.items():
            result[k] += max(0, n)
        remaining -= moved
        if remaining <= 0:
            break
        ranked = sorted(active, key=lambda k: (-(exact[k] - math.floor(exact[k])), k))
        progressed = False
        for k in ranked:
            if remaining <= 0:
                break
            if result[k] < caps[k]:
                result[k] += 1
                remaining -= 1
                progressed = True
        active = {k for k in active if result[k] < caps[k]}
        if not progressed and moved == 0:
            break
    return {k: n for k, n in result.items() if n > 0}


def _role_totals(force: Mapping[str, Any]) -> dict[str, int]:
    totals = {str(k): max(0, int(v)) for k, v in force.get("available_by_role", {}).items()}
    for alloc in force.get("allocated_to_formations", {}).values():
        if not isinstance(alloc, Mapping):
            continue
        for role, raw in alloc.get("composition", {}).items():
            totals[str(role)] = totals.get(str(role), 0) + max(0, int(raw))
    return totals


def _profile_copy(registry: Mapping[str, Any], background: str) -> dict[str, Any]:
    profiles = registry.get("background_profiles", {})
    profile = profiles.get(background) if isinstance(profiles, Mapping) else None
    if not isinstance(profile, Mapping):
        raise ValueError(f"unknown Bastion candidate background: {background}")
    return copy.deepcopy(dict(profile))


class BastionPersonnelLifecycleMixin:
    """Permanent Four Bastion Corps recruiting, qualification and replacement.

    Candidates are conserved Qin/Tang Manor civilians while training.  A body
    enters an exact Bastion force only when a real active-service vacancy exists.
    Physical training facilities limit concurrent trainees, not the size of the
    world or the long-run size of a Corps.
    """

    def _bastion_policy(self) -> Mapping[str, Any]:
        return self.read(_POLICY_PATH)

    def _bastion_facilities(self) -> Mapping[str, Any]:
        infra = self.read(_INFRA_PATH)
        return infra.get("sites", {}).get(_SITE, {}).get("bastion_training", {})

    def _bastion_pipeline_count(self, force: Mapping[str, Any]) -> int:
        pipeline = force.get("personnel_pipeline", {})
        cohorts = pipeline.get("cohorts", []) if isinstance(pipeline, Mapping) else []
        return sum(max(0, int(row.get("remaining_candidates", 0))) for row in cohorts if isinstance(row, Mapping) and row.get("status") in {"training", "qualified_reserve"})


    def _bastion_outside_application_pool(self, corps_key: str) -> tuple[dict[str, Any], int]:
        tang = copy.deepcopy(self.read(TANG_POPULATION_PATH))
        pools = tang.setdefault("bastion_outside_applications", {})
        row = pools.setdefault(corps_key, {
            "available_applicants": 0,
            "arrival_history": [],
            "selection_history": [],
            "rule": "subset/provenance over already-conserved Tang Manor civilians; this record owns zero additional bodies",
        })
        return tang, max(0, int(row.get("available_applicants", 0)))

    def _bastion_relocate_outside_applicants(
        self,
        corps_key: str,
        *,
        source_state: str,
        source_site_ref: str,
        applicant_count: int,
        at: str,
    ) -> dict[str, Any]:
        policy = self._bastion_policy()
        corps_cfg = policy.get("corps", {}).get(corps_key) if isinstance(policy.get("corps"), Mapping) else None
        if not isinstance(corps_cfg, Mapping):
            raise ValueError("unknown Bastion Corps for outside applicants")
        count = max(0, int(applicant_count))
        if count <= 0:
            raise ValueError("outside applicant count must be positive")
        state_key = str(source_state).strip().lower()
        source_path = f"state/population/{state_key}.json"
        source = self.read_optional(source_path)
        if not isinstance(source, Mapping):
            raise ValueError("outside applicant source population is not represented")
        local = source.get("local_population", {}).get("sites", {}) if isinstance(source.get("local_population"), Mapping) else {}
        origin = local.get(str(source_site_ref)) if isinstance(local, Mapping) else None
        if not isinstance(origin, Mapping):
            raise ValueError("outside applicant source site is not an exact demographic locality")
        if str(source_site_ref) == _SITE:
            raise ValueError("outside applicant relocation requires an origin outside Tang Manor")

        qin = self.read(_POP_PATH)
        tang_row = qin.get("local_population", {}).get("sites", {}).get(_SITE, {}) if isinstance(qin.get("local_population"), Mapping) else {}
        current_residents = max(0, int(tang_row.get("civilian_population", 0))) + max(0, int(tang_row.get("service_population", 0)))
        support = self.read(_INFRA_PATH).get("sites", {}).get(_SITE, {})
        resident_capacity = max(0, int(support.get("effective_resident_support_capacity_people", 0))) if isinstance(support, Mapping) else 0
        mobility = self.read("state/mobility/population-transit.json")
        inbound = sum(
            max(0, int(row.get("count", 0)))
            for row in (mobility.get("cohorts", {}) if isinstance(mobility, Mapping) else {}).values()
            if isinstance(row, Mapping) and row.get("status") == "in_transit" and row.get("destination_site_ref") == _SITE
        )
        headroom = max(0, resident_capacity - current_residents - inbound)
        if headroom <= 0:
            raise ValueError("Tang Manor has no physical resident-support headroom for outside applicants")
        requested = min(count, headroom)

        move = self._queue_population_move(
            source_population_path=source_path,
            destination_population_path=_POP_PATH,
            origin_site_ref=str(source_site_ref),
            destination_site_ref=_SITE,
            count=requested,
            departed_at=at,
            basis=f"lawful outside applicants accepted for possible {corps_key} Bastion service; relocation precedes selection and guarantees no appointment",
        )
        if not isinstance(move, Mapping) or int(move.get("count", 0)) <= 0:
            raise ValueError("no conserved willing applicant bodies were available to relocate")
        mobility2 = copy.deepcopy(self.read("state/mobility/population-transit.json"))
        cohort = mobility2.get("cohorts", {}).get(str(move.get("migration_ref")))
        if not isinstance(cohort, dict):
            raise ValueError("outside applicant migration cohort failed to materialize")
        cohort["bastion_application"] = {
            "corps": corps_key,
            "status": "relocating_applicant",
            "source_state": state_key,
            "source_site_ref": str(source_site_ref),
            "accepted_at": at,
            "rule": "arrival creates only eligibility as a Tang Manor resident applicant; selection, training, qualification, vacancy, and appointment remain separate",
        }
        self.put("state/mobility/population-transit.json", mobility2)
        return {
            "corps": corps_key,
            "source_state": state_key,
            "source_site_ref": str(source_site_ref),
            "migration_ref": move.get("migration_ref"),
            "relocated_applicants": int(move.get("count", 0)),
            "arrives_at": move.get("arrives_at"),
            "resident_headroom_before_departure": headroom,
        }

    def _bastion_source_counts(self, pop: Mapping[str, Any], cfg: Mapping[str, Any], applicant_count: int) -> dict[str, int]:
        local = pop.get("local_population", {}).get("sites", {}).get(_SITE, {})
        civilian = local.get("civilian_strata", {}) if isinstance(local, Mapping) else {}
        global_strata = pop.get("strata", {})
        weights = cfg.get("candidate_source_mix", {})
        capacities = {
            str(k): min(max(0, int(civilian.get(str(k), 0))), max(0, int(global_strata.get(str(k), 0))))
            for k in weights
        }
        result = _apportion(applicant_count, weights, capacities)
        if sum(result.values()) != applicant_count:
            raise ValueError("Bastion candidate pool lacks enough conserved Tang Manor civilians")
        return result

    def _bastion_candidate_slices(
        self,
        profile_registry: Mapping[str, Any],
        source_counts: Mapping[str, int],
        selected_by_source: Mapping[str, int],
        selection_ref: str,
    ) -> list[dict[str, Any]]:
        mixes = profile_registry.get("population_background_mixes", {})
        selection = profile_registry.get("selection_profiles", {}).get(selection_ref)
        if not isinstance(selection, Mapping):
            raise ValueError(f"unknown Bastion selection profile: {selection_ref}")
        rows: list[dict[str, Any]] = []
        for source, selected in sorted(selected_by_source.items()):
            applicants = max(1, int(source_counts.get(source, selected)))
            mix = mixes.get(source, {}) if isinstance(mixes, Mapping) else {}
            if not isinstance(mix, Mapping) or not mix:
                raise ValueError(f"Bastion source stratum lacks background mix: {source}")
            bg_counts = _apportion(int(selected), mix)
            retain = max(0.001, min(1.0, int(selected) / applicants))
            for background, count in sorted(bg_counts.items()):
                profile = _profile_copy(profile_registry, background)
                apply_selection_profile(profile, selection, retain_fraction=retain)
                rows.append({
                    "source_stratum": str(source),
                    "background_profile": str(background),
                    "count": int(count),
                    "profile": profile,
                    "selection_retain_fraction": round(retain, 6),
                })
        return rows

    def _bastion_start_pipeline(self, corps_key: str, force: MutableMapping[str, Any], at: str) -> int:
        policy = self._bastion_policy()
        cfg = policy.get("corps", {}).get(corps_key, {})
        if not isinstance(cfg, Mapping):
            return 0
        facilities = self._bastion_facilities()
        corps_fac = facilities.get(corps_key, {}) if isinstance(facilities, Mapping) else {}
        concurrent_capacity = max(0, int(corps_fac.get("concurrent_trainee_capacity", 0)))
        common_capacity = max(0, int(facilities.get("common_induction_concurrent_capacity", 0)))
        all_force_rows = []
        for path in _FORCE_PATHS.values():
            other = force if path == _FORCE_PATHS[corps_key] else self.read(path)
            all_force_rows.append(self._bastion_pipeline_count(other))
        common_used = sum(all_force_rows)
        current_pipeline = self._bastion_pipeline_count(force)
        qualification_days = max(1, int(cfg.get("qualification_days", policy.get("common_induction_days", 180))))
        establishment = max(0, int(force.get("authorized_strength", cfg.get("establishment", 0))))
        shortage = max(0, establishment - int(force.get("headcount", 0)))
        forecast_bp = max(0, int(policy.get("recruitment", {}).get("forecast_annual_normal_separation_basis_points", 180)))
        forecast = int(math.ceil(establishment * forecast_bp / 10000.0 * qualification_days / 365.0))
        desired_pipeline = shortage + forecast
        needed = max(0, desired_pipeline - current_pipeline)
        physical_open = min(max(0, concurrent_capacity - current_pipeline), max(0, common_capacity - common_used))
        start_count = min(needed, physical_open)
        if start_count <= 0:
            return 0

        profile_registry = self.read(_PROFILE_PATH)
        selection_ref = str(cfg.get("selection_profile_ref", "state_basic_military_screen"))
        selection = profile_registry.get("selection_profiles", {}).get(selection_ref, {})
        retain_fraction = max(0.05, min(1.0, float(selection.get("default_retain_fraction", 0.65)))) if isinstance(selection, Mapping) else 0.65
        applicants = max(start_count, int(math.ceil(start_count / retain_fraction)))
        pop = copy.deepcopy(self.read(_POP_PATH))
        source_counts = self._bastion_source_counts(pop, cfg, applicants)
        tang_applications, available_outside = self._bastion_outside_application_pool(corps_key)
        outside_considered = min(applicants, available_outside)
        outside_arrival_refs: list[str] = []
        if outside_considered:
            app_row = tang_applications.setdefault("bastion_outside_applications", {}).setdefault(corps_key, {})
            app_row["available_applicants"] = available_outside - outside_considered
            need_refs = outside_considered
            for arrival in app_row.get("arrival_history", []) if isinstance(app_row.get("arrival_history"), list) else []:
                if need_refs <= 0 or not isinstance(arrival, dict):
                    break
                remaining = max(0, int(arrival.get("unconsidered_applicants", arrival.get("count", 0))))
                if remaining <= 0:
                    continue
                take = min(remaining, need_refs)
                arrival["unconsidered_applicants"] = remaining - take
                ref = arrival.get("migration_ref")
                if isinstance(ref, str) and ref:
                    outside_arrival_refs.append(ref)
                need_refs -= take
            app_row.setdefault("selection_history", []).append({
                "at": at,
                "corps": corps_key,
                "applicants_considered": outside_considered,
                "selection_campaign_ref": f"pending:{corps_key}:{at}",
                "rule": "consideration guarantees no selection or active-service appointment",
            })
            app_row["selection_history"] = app_row["selection_history"][-24:]
        pipeline = force.setdefault("personnel_pipeline", {})
        serial = int(pipeline.get("next_serial", 1))
        campaign_ref = f"bastion:{corps_key}:{serial}:{at}"
        local_rows = self._reserve_local_candidates(pop, "qin", _SITE, campaign_ref, source_counts, controller_ref="state_qin")
        strata = pop.setdefault("strata", {})
        for source, count in source_counts.items():
            strata[source] = int(strata.get(source, 0)) - int(count)
        strata["recruitment_candidates_reserved"] = int(strata.get("recruitment_candidates_reserved", 0)) + applicants

        selected_by_source = _apportion(start_count, source_counts, source_counts)
        rejected_by_source = {source: int(source_counts[source]) - int(selected_by_source.get(source, 0)) for source in source_counts}
        rejected = applicants - start_count
        if rejected:
            for source, count in rejected_by_source.items():
                strata[source] = int(strata.get(source, 0)) + int(count)
            strata["recruitment_candidates_reserved"] = int(strata.get("recruitment_candidates_reserved", 0)) - rejected
            self._release_local_candidate_rejections(pop, campaign_ref, rejected_by_source)

        slices = self._bastion_candidate_slices(profile_registry, source_counts, selected_by_source, selection_ref)
        qualifies_at = str(CampaignTime.parse(at).add_days(qualification_days))
        row = {
            "pipeline_ref": campaign_ref,
            "corps": corps_key,
            "status": "training",
            "started_at": at,
            "qualifies_at": qualifies_at,
            "qualification_days": qualification_days,
            "initial_applicants": applicants,
            "selected_candidates": start_count,
            "remaining_candidates": start_count,
            "selection_profile_ref": selection_ref,
            "source_counts_selected": dict(selected_by_source),
            "candidate_slices": slices,
            "local_reservations": local_rows,
            "outside_applicants_considered": outside_considered,
            "outside_applicant_arrival_refs": outside_arrival_refs,
            "rule": "training candidates remain conserved population reservations until a real Bastion active-service vacancy exists; outside applicants are ordinary Tang Manor residents before selection and receive no guaranteed appointment",
        }
        pipeline.setdefault("cohorts", []).append(row)
        pipeline["next_serial"] = serial + 1
        pipeline["cohorts"] = [r for r in pipeline["cohorts"] if isinstance(r, Mapping) and r.get("status") not in {"closed", "released"}][-64:]
        pipeline["last_forecast"] = {
            "at": at,
            "authorized_strength": establishment,
            "active_shortage": shortage,
            "normal_separation_forecast": forecast,
            "desired_pipeline": desired_pipeline,
            "concurrent_capacity": concurrent_capacity,
            "common_induction_capacity": common_capacity,
        }
        self.put(_POP_PATH, pop)
        if outside_considered:
            app_row = tang_applications["bastion_outside_applications"][corps_key]
            if app_row.get("selection_history"):
                app_row["selection_history"][-1]["selection_campaign_ref"] = campaign_ref
                app_row["selection_history"][-1]["selected_candidates_total"] = start_count
            self.put(TANG_POPULATION_PATH, tang_applications)
        return start_count

    def _dispatch(self, command: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
        if command.command_type == "house_action" and str(payload.get("action", "")) == "accept_bastion_applicants":
            at = str(self._world_time())
            result = self._bastion_relocate_outside_applicants(
                str(payload["corps_key"]),
                source_state=str(payload["source_state"]),
                source_site_ref=str(payload["source_site_ref"]),
                applicant_count=int(payload["applicant_count"]),
                at=at,
            )
            world_time, metrics = self._advance_seconds(2 * 3600)
            self._write_meta(command, world_time)
            return self._result(house_ref=str(payload.get("house_ref", "house_tang")), action="accept_bastion_applicants", world_time=world_time, **result, **metrics)
        return super()._dispatch(command, payload)

    def _bastion_finalize_local_partial(self, pop: MutableMapping[str, Any], campaign_ref: str, force_ref: str, source_counts: Mapping[str, int]) -> None:
        remaining = {str(k): max(0, int(v)) for k, v in source_counts.items()}
        sites = pop.get("local_population", {}).get("sites", {})
        for _ref, row in sorted(sites.items()):
            reservation = row.get("candidate_reservations", {}).get(campaign_ref) if isinstance(row, Mapping) else None
            if not isinstance(reservation, MutableMapping):
                continue
            sources = reservation.get("source_strata", {}) if isinstance(reservation.get("source_strata"), MutableMapping) else {}
            for source in sorted(list(sources)):
                need = remaining.get(source, 0)
                if need <= 0:
                    continue
                take = min(need, max(0, int(sources.get(source, 0))))
                if not take:
                    continue
                sources[source] = int(sources.get(source, 0)) - take
                self._add_local_service_allocation(row, force_ref, take, service_class="private_house_military", source_stratum=source)
                remaining[source] -= take
            reservation["source_strata"] = {k: v for k, v in sources.items() if int(v) > 0}
            if not reservation["source_strata"]:
                row.get("candidate_reservations", {}).pop(campaign_ref, None)
            self._sync_local_population_row(row)
        if any(remaining.values()):
            raise ValueError("Bastion qualification could not reconcile candidate locality reservation")

    def _bastion_role_deficits(self, force: Mapping[str, Any]) -> dict[str, int]:
        current = _role_totals(force)
        authorized = force.get("authorized_by_role", {})
        return {str(role): max(0, int(target) - int(current.get(str(role), 0))) for role, target in authorized.items()}

    def _bastion_training_focus(self, role: str, policy: Mapping[str, Any]) -> tuple[list[str], list[str]]:
        focus = policy.get("role_training_focuses", {}).get(role, {})
        if not isinstance(focus, Mapping):
            return ["Formation Fighting", "Defense", "Mass Combat"], ["Endurance", "Coordination", "Composure"]
        return [str(x) for x in focus.get("skills", [])], [str(x) for x in focus.get("attributes", [])]

    def _bastion_admit_from_row(self, corps_key: str, force: MutableMapping[str, Any], row: MutableMapping[str, Any], count: int, at: str) -> int:
        n = min(max(0, int(count)), max(0, int(row.get("remaining_candidates", 0))))
        if n <= 0:
            return 0
        deficits = self._bastion_role_deficits(force)
        if sum(deficits.values()) <= 0:
            return 0
        role_counts = _apportion(n, deficits, deficits)
        admitted = sum(role_counts.values())
        if admitted <= 0:
            return 0
        profile_registry = self.read(_PROFILE_PATH)
        training_rules = self.read(_TRAINING_PATH)
        policy = self._bastion_policy()
        cfg = policy.get("corps", {}).get(corps_key, {})
        regimen = policy.get("qualification_regimen", {})
        months = max(0.0, float(row.get("qualification_days", cfg.get("qualification_days", 360))) / 30.0)
        deliberate_hours = months * float(regimen.get("deliberate_hours_per_30d", 205.714286))
        exposure_hours = months * float(regimen.get("role_exposure_hours_per_30d", 120.0))
        slices = [r for r in row.get("candidate_slices", []) if isinstance(r, MutableMapping) and int(r.get("count", 0)) > 0]
        source_admitted: dict[str, int] = {}
        role_history: dict[str, int] = {}
        for role, target in sorted(role_counts.items()):
            need = int(target)
            for candidate in slices:
                if need <= 0:
                    break
                available = max(0, int(candidate.get("count", 0)))
                take = min(need, available)
                if take <= 0:
                    continue
                add_recruits(force, role, take, location_ref=_LOCATION)
                cid = record_recruitment_cohort(
                    force,
                    role=role,
                    count=take,
                    location_ref=_LOCATION,
                    source_population_ref="population_qin",
                    source_stratum=str(candidate.get("source_stratum", "household_and_service")),
                    recruited_at=at,
                    profile_registry=profile_registry,
                    background_profile=str(candidate.get("background_profile", "civilian_common")),
                    selection_profile=str(row.get("selection_profile_ref")),
                    selection_retain_fraction=float(candidate.get("selection_retain_fraction", 1.0)),
                    provenance_ref=str(row.get("pipeline_ref")),
                    conditioned_profile=candidate.get("profile") if isinstance(candidate.get("profile"), Mapping) else None,
                    intake_ref=str(row.get("pipeline_ref")),
                    validate=False,
                )
                cohort = force.get("cohort_ledger", {}).get("cohorts", {}).get(cid)
                if isinstance(cohort, MutableMapping):
                    registry = self.read(TRAINING_PROGRAM_REGISTRY_PATH)
                    program_ref = resolve_program_ref(registry, role=role)
                    evidence = f"{row.get('pipeline_ref')}:qualification:{role}"
                    training_start = str(row.get("started_at", at))
                    training_end = str(at)
                    instructor_contexts = instructor_contexts_for_program(
                        self, registry=registry, training_rules=training_rules, program_ref=program_ref,
                        trainee_skills=(cohort.get("skill_means", {}) if isinstance(cohort.get("skill_means"), Mapping) else {}),
                        student_count=max(1, take), location_ref=_LOCATION,
                        scheduled_hours=deliberate_hours, window_start=training_start, window_end=training_end,
                        evidence_ref=evidence, reserve_duty=True,
                    )
                    drill_access = program_facility_access(
                        self, registry=registry, program_ref=program_ref, location_ref=_LOCATION
                    )
                    settle_cohort_program(
                        cohort, registry=registry, program_ref=program_ref,
                        deliberate_hours=deliberate_hours, role_exposure_hours=exposure_hours,
                        training_rules=training_rules,
                        facility_grade=str(regimen.get("facility_grade", "excellent")),
                        equipment_grade=str(regimen.get("equipment_grade", "correct")),
                        recovery_grade=str(regimen.get("recovery_grade", "good")),
                        evidence_ref=evidence,
                        instructor_context_by_drill=instructor_contexts,
                        drill_access=drill_access,
                    )
                    cohort.setdefault("tags", []).extend(["permanent_bastion_corps", "professionally_qualified", f"corps:{corps_key}"])
                candidate["count"] = available - take
                source = str(candidate.get("source_stratum", "household_and_service"))
                source_admitted[source] = source_admitted.get(source, 0) + take
                role_history[role] = role_history.get(role, 0) + take
                need -= take
            if need:
                raise ValueError("Bastion candidate slices do not conserve selected trainees")
        row["candidate_slices"] = [r for r in slices if int(r.get("count", 0)) > 0]
        row["remaining_candidates"] = int(row.get("remaining_candidates", 0)) - admitted
        row.setdefault("admission_history", []).append({"at": at, "personnel": admitted, "by_role": role_history, "source_strata": source_admitted})
        row["admission_history"] = row["admission_history"][-24:]
        if row["remaining_candidates"] <= 0:
            row["remaining_candidates"] = 0
            row["status"] = "closed"
            row["closed_at"] = at

        pop = copy.deepcopy(self.read(_POP_PATH))
        strata = pop.setdefault("strata", {})
        if int(strata.get("recruitment_candidates_reserved", 0)) < admitted:
            raise ValueError("Bastion candidate reserved population underflow")
        strata["recruitment_candidates_reserved"] = int(strata.get("recruitment_candidates_reserved", 0)) - admitted
        strata["private_household_military"] = int(strata.get("private_household_military", 0)) + admitted
        self._bastion_finalize_local_partial(pop, str(row.get("pipeline_ref")), str(force.get("owner_id")), source_admitted)
        self.put(_POP_PATH, pop)
        validate_cohort_ledger(force)
        return admitted

    def _bastion_fill_formation_vacancies(self, force: MutableMapping[str, Any], at: str) -> int:
        owner = str(force.get("owner_id", ""))
        formation_index = self.read("state/index/owner-index.json").get("owners", {})
        filled = 0
        for formation_ref, alloc in sorted(force.get("allocated_to_formations", {}).items()):
            route = formation_index.get(formation_ref)
            if not isinstance(route, str) or "#" in route:
                continue
            formation = copy.deepcopy(self.read(route))
            establishment = formation.get("establishment_composition")
            if not isinstance(establishment, Mapping) or not establishment:
                establishment = copy.deepcopy(alloc.get("composition", {})) if isinstance(alloc, Mapping) else {}
                formation["establishment_composition"] = copy.deepcopy(establishment)
            current = {str(k): max(0, int(v)) for k, v in formation.get("composition", {}).items()}
            role_need = {str(role): max(0, int(target) - current.get(str(role), 0)) for role, target in establishment.items()}
            actual_add: dict[str, int] = {}
            location = str(formation.get("location_ref", _LOCATION))
            local = force.get("available_by_location", {}).get(location, {})
            for role, need in role_need.items():
                available = min(max(0, int(force.get("available_by_role", {}).get(role, 0))), max(0, int(local.get(role, 0))))
                take = min(need, available)
                if take > 0:
                    actual_add[role] = take
            if not actual_add:
                continue
            equipment = self._equipment_units(formation)
            shield_units = self._shield_units(formation)
            armor_units = self._armor_units(formation)
            incoming_slices: list[dict[str, Any]] = []
            for role, count in actual_add.items():
                self._take_force_personnel(force, role, count, location)
                incoming_slices.extend(take_reserve_slices(force, role=role, count=count, location_ref=location, formation_ref=formation_ref, validate=False))
                gear_take = self._take_force_equipment(force, role, count, location)
                equipment[role] = int(equipment.get(role, 0)) + gear_take
                if gear_take > 0 and self._combat_role_uses_shield(role):
                    shield_units[role] = int(shield_units.get(role, 0)) + gear_take
                if gear_take > 0 and self._combat_role_uses_armor(role):
                    armor_units[role] = int(armor_units.get(role, 0)) + gear_take
                formation.setdefault("composition", {})[role] = int(formation.get("composition", {}).get(role, 0)) + count
            added = sum(actual_add.values())
            formation["personnel"] = int(formation.get("personnel", 0)) + added
            self._set_equipment_units(formation, equipment)
            self._set_shield_units(formation, shield_units)
            self._set_armor_units(formation, armor_units)
            from sword_runtime.cohort_personnel import append_formation_slices
            append_formation_slices(formation, incoming_slices)
            force.setdefault("allocated_to_formations", {})[formation_ref] = self._formation_allocation_record(formation)
            formation["last_reconstituted_at"] = at
            formation["last_reconstitution_by_role"] = dict(actual_add)
            formation["last_reconstitution_basis"] = "qualified Bastion reserve physically present at the formation location"
            reorganize_officer_cadre(formation, at=at, reason="bastion_reconstitution")
            sync_materialized_officer_billets(self, formation)
            self.put(route, formation)
            filled += added
        validate_cohort_ledger(force)
        return filled


    def _bastion_retirements(self, corps_key: str, force: MutableMapping[str, Any], at: str) -> int:
        """Return due long-service rank-and-file to Tang Manor civilian life.

        Retirement is cohort-service completion, not disappearance. The same body
        leaves military custody, re-enters the Tang Manor/Qin civilian partition,
        and creates an active-service vacancy. Named/materialized officers are not
        bulk-retired by this aggregate path; their career exit remains explicit.
        """
        policy = self._bastion_policy()
        retirement = policy.get("retirement", {}) if isinstance(policy, Mapping) else {}
        minimum = max(1.0, float(retirement.get("minimum_service_months", 240)))
        window = max(1.0, float(retirement.get("completion_window_months", 60)))
        ledger = force.get("cohort_ledger", {}) if isinstance(force.get("cohort_ledger"), Mapping) else {}
        cohorts = ledger.get("cohorts", {}) if isinstance(ledger, Mapping) else {}
        if not isinstance(cohorts, MutableMapping):
            return 0
        retired_total = 0
        retired_by_role: dict[str, int] = {}
        for cohort_id, cohort in sorted(cohorts.items()):
            if not isinstance(cohort, MutableMapping):
                continue
            service = float(cohort.get("service_months_mean", 0.0))
            if service <= minimum:
                continue
            current_total = sum(max(0, int(v)) for v in cohort.get("reserve_by_location", {}).values()) + sum(max(0, int(v)) for v in cohort.get("allocated_by_formation", {}).values()) + sum(max(0, int(v)) for v in cohort.get("allocated_external_by_formation", {}).values())
            if current_total <= 0:
                continue
            state = cohort.setdefault("retirement_state", {})
            baseline = max(current_total + int(state.get("retired_to_date", 0)), int(state.get("baseline_personnel", 0)))
            state["baseline_personnel"] = baseline
            target_fraction = min(1.0, max(0.0, (service - minimum) / window))
            target_retired = min(baseline, int(math.floor(baseline * target_fraction + 1e-9)))
            due = max(0, target_retired - int(state.get("retired_to_date", 0)))
            if due <= 0:
                continue
            role = str(cohort.get("role", ""))
            retired = 0
            # Reserve personnel retire first; no formation bookkeeping is needed.
            reserves = cohort.get("reserve_by_location", {}) if isinstance(cohort.get("reserve_by_location"), MutableMapping) else {}
            for location in sorted(list(reserves)):
                if retired >= due:
                    break
                available = max(0, int(reserves.get(location, 0)))
                take = min(due - retired, available)
                if take <= 0:
                    continue
                reserves[location] = available - take
                local = force.setdefault("available_by_location", {}).setdefault(location, {})
                local[role] = max(0, int(local.get(role, 0)) - take)
                force.setdefault("available_by_role", {})[role] = max(0, int(force.get("available_by_role", {}).get(role, 0)) - take)
                retired += take
            # Then retire ordinary bodies from active formations. Rank inventory is
            # left intact; explicit officer retirement is a separate career event.
            allocations = cohort.get("allocated_by_formation", {}) if isinstance(cohort.get("allocated_by_formation"), MutableMapping) else {}
            for formation_ref in sorted(list(allocations)):
                if retired >= due:
                    break
                available = max(0, int(allocations.get(formation_ref, 0)))
                take = min(due - retired, available)
                if take <= 0:
                    continue
                owner_index = self.read("state/index/owner-index.json").get("owners", {})
                fpath = owner_index.get(formation_ref) if isinstance(owner_index, Mapping) else None
                if not isinstance(fpath, str) or "#" in fpath:
                    continue
                formation = copy.deepcopy(self.read(fpath))
                if str(formation.get("owner_force_ref")) != str(force.get("owner_id")):
                    continue
                allocations[formation_ref] = available - take
                formation["personnel"] = max(0, int(formation.get("personnel", 0)) - take)
                composition = formation.setdefault("composition", {})
                composition[role] = max(0, int(composition.get(role, 0)) - take)
                if composition[role] == 0:
                    composition.pop(role, None)
                remaining = take
                for row in formation.get("cohort_composition", []):
                    if remaining <= 0 or not isinstance(row, MutableMapping) or str(row.get("cohort_id")) != str(cohort_id):
                        continue
                    cut = min(remaining, max(0, int(row.get("count", 0))))
                    row["count"] = max(0, int(row.get("count", 0)) - cut); remaining -= cut
                formation["cohort_composition"] = [row for row in formation.get("cohort_composition", []) if isinstance(row, Mapping) and int(row.get("count", 0)) > 0]
                equipment = self._equipment_units(formation)
                shield_units = self._shield_units(formation)
                armor_units = self._armor_units(formation)
                returned_gear = min(take, max(0, int(equipment.get(role, 0))))
                equipment[role] = max(0, int(equipment.get(role, 0)) - returned_gear)
                if role in shield_units:
                    returned_shields = min(take, max(0, int(shield_units.get(role, 0))))
                    shield_units[role] = max(0, int(shield_units.get(role, 0)) - returned_shields)
                if role in armor_units:
                    returned_armor = min(take, max(0, int(armor_units.get(role, 0))))
                    armor_units[role] = max(0, int(armor_units.get(role, 0)) - returned_armor)
                self._set_equipment_units(formation, equipment)
                self._set_shield_units(formation, shield_units)
                self._set_armor_units(formation, armor_units)
                if returned_gear:
                    self._return_force_equipment(force, role, returned_gear, str(formation.get("location_ref", _LOCATION)))
                force.setdefault("allocated_to_formations", {})[formation_ref] = self._formation_allocation_record(formation)
                formation["last_service_retirement_at"] = at
                reorganize_officer_cadre(formation, at=at, reason="ordinary_service_retirement")
                sync_materialized_officer_billets(self, formation)
                self.put(fpath, formation)
                retired += take
            if retired:
                force["headcount"] = max(0, int(force.get("headcount", 0)) - retired)
                state["retired_to_date"] = int(state.get("retired_to_date", 0)) + retired
                state["last_retired_at"] = at
                retired_total += retired
                retired_by_role[role] = retired_by_role.get(role, 0) + retired

        if retired_total:
            pop = copy.deepcopy(self.read(_POP_PATH))
            strata = pop.setdefault("strata", {})
            if int(strata.get("private_household_military", 0)) < retired_total:
                raise ValueError("Bastion retirement exceeds conserved Qin private military stratum")
            strata["private_household_military"] = int(strata.get("private_household_military", 0)) - retired_total
            strata["retired_military_veterans"] = int(strata.get("retired_military_veterans", 0)) + retired_total
            local = pop.setdefault("local_population", {}).setdefault("sites", {}).get(_SITE)
            if not isinstance(local, MutableMapping):
                raise ValueError("Tang Manor local population row is missing for Bastion retirement")
            local["private_household_military"] = max(0, int(local.get("private_household_military", 0)) - retired_total)
            local["service_population"] = max(0, int(local.get("service_population", 0)) - retired_total)
            local["civilian_population"] = int(local.get("civilian_population", 0)) + retired_total
            local.setdefault("civilian_strata", {})["retired_military_veterans"] = int(local.get("civilian_strata", {}).get("retired_military_veterans", 0)) + retired_total
            service = local.setdefault("service_allocations", {}).get(str(force.get("owner_id")))
            if isinstance(service, MutableMapping):
                service["personnel"] = max(0, int(service.get("personnel", 0)) - retired_total)
            self.put(_POP_PATH, pop)
            tang = copy.deepcopy(self.read(TANG_POPULATION_PATH))
            tang.setdefault("strata", {})["veterans_and_retired_service"] = int(tang.get("strata", {}).get("veterans_and_retired_service", 0)) + retired_total
            tang["population_total"] = int(tang.get("population_total", 0)) + retired_total
            tang["last_service_retirement"] = {"at": at, "corps": corps_key, "count": retired_total, "by_role": retired_by_role}
            self.put(TANG_POPULATION_PATH, tang)
        return retired_total

    def _settle_bastion_personnel(self, at: str) -> dict[str, Any]:
        now = CampaignTime.parse(at)
        result: dict[str, Any] = {"at": at, "corps": {}}
        for corps_key, path in _FORCE_PATHS.items():
            force = copy.deepcopy(self.read(path))
            pipeline = force.setdefault("personnel_pipeline", {"next_serial": 1, "cohorts": []})
            retired = self._bastion_retirements(corps_key, force, at)
            admitted = 0
            for row in pipeline.get("cohorts", []):
                if not isinstance(row, MutableMapping):
                    continue
                if row.get("status") == "training" and CampaignTime.parse(str(row.get("qualifies_at"))) <= now:
                    row["status"] = "qualified_reserve"
                    row["qualified_at"] = at
                if row.get("status") == "qualified_reserve":
                    shortage = max(0, int(force.get("authorized_strength", 0)) - int(force.get("headcount", 0)))
                    if shortage > 0:
                        admitted += self._bastion_admit_from_row(corps_key, force, row, shortage, at)
            filled = self._bastion_fill_formation_vacancies(force, at)
            started = self._bastion_start_pipeline(corps_key, force, at)
            pipeline["cohorts"] = [r for r in pipeline.get("cohorts", []) if isinstance(r, Mapping) and r.get("status") != "closed"][-64:]
            pipeline.setdefault("history", []).append({"at": at, "retired_service": retired, "started_training": started, "admitted_active": admitted, "assigned_to_formations": filled, "active_pipeline": self._bastion_pipeline_count(force)})
            pipeline["history"] = pipeline["history"][-36:]
            force["personnel_pipeline"] = pipeline
            validate_cohort_ledger(force)
            self.put(path, force)
            result["corps"][corps_key] = pipeline["history"][-1]
        return result

    def _autonomy_house(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_house(host, occurrences, at)
        if str(host.get("owner_ref", "")) == "house_tang":
            self._settle_bastion_personnel(at)
