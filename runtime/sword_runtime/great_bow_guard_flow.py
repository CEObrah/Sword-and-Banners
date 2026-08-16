"""Autonomous Great Bow Guard candidate screening and training lifecycle.

The House program already owns an applicant pool.  This layer advances that pool
through registered selection and verified cohort training without creating bodies,
equipment, or a field formation by narration.  Accepted fighters enter the exact
House Tang force only after screening and training; equipment issue and formation
materialization remain separate conserved consequences.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_event_store import get_causal_event
from sword_runtime.cohort_personnel import (
    add_recruits,
    advance_cohort_training,
    ensure_cohort_ledger,
    record_recruitment_cohort,
    validate_cohort_ledger,
)
from sword_runtime.household_request_flow import _emit_watch_report, _treasury_safe_ceiling
from sword_runtime.recruitment_campaigns import (
    PROFILE_PATH,
    REGISTRY_PATH,
    _registry as _candidate_registry,
    stage_campaign,
)
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_HOUSE_FORCE = "state/forces/house-tang.json"
_QIN_POPULATION = "state/population/qin.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_HOUSE_RULES_PATH = "game/data/mechanics/house-tang-programs.json"
_TRAINING_RULES_PATH = "game/data/mechanics/training.json"
_ECONOMY_RULES_PATH = "game/data/mechanics/economy.json"
_TRAINING_GROUND = "loc_tang_manor_training_ground"

_HOST_ID = "host_house_great_bow_guard_lifecycle"
_EVENT_ID = "event_house_great_bow_guard_lifecycle_review"
_PRIORITY = 50
_ROLE = "great_bow_guard"


def _program(planner: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    programs = house.setdefault("administrative_programs", {})
    great = programs.get("great_bow_guard")
    if not isinstance(great, dict):
        raise ValueError("Great Bow Guard program is not an exact House Tang program")
    return house, great


def _rules(planner: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    rules = planner.read(_HOUSE_RULES_PATH)
    great = rules.get("great_bow_guard", {}) if isinstance(rules, Mapping) else {}
    training = great.get("candidate_training", {}) if isinstance(great, Mapping) else {}
    if not isinstance(great, Mapping) or not isinstance(training, Mapping):
        raise ValueError("Great Bow Guard lifecycle rules are invalid")
    return great, training


def _campaign(planner: Any, campaign_ref: str) -> tuple[dict[str, Any], MutableMapping[str, Any] | None]:
    registry = _candidate_registry(planner)
    row = registry.get("campaigns", {}).get(campaign_ref)
    return registry, row if isinstance(row, MutableMapping) else None


def _report(planner: Any, *, at: str, key: str, summary: str) -> str:
    return _emit_watch_report(
        planner,
        player_ref="char_tang_wei",
        at=at,
        key=key,
        summary=summary[:4000],
    )


def _wake_for_report(planner: Any, report_ref: str, at: str) -> dict[str, Any] | None:
    report = get_causal_event(planner, report_ref)
    if not isinstance(report, Mapping):
        return None
    summary = str(report.get("summary", "House Tang has sent a Great Bow Guard report."))
    digest = hashlib.sha256(f"{report_ref}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.house.great_bow_guard.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": report_ref,
        "reason": summary,
    }


def _prepare_house_force(planner: Any, establishment: int) -> dict[str, Any]:
    force = copy.deepcopy(planner.read(_HOUSE_FORCE))
    force["support_treasury_ref"] = "treasury_house_tang"
    authorized = force.setdefault("authorized_by_role", {})
    authorized[_ROLE] = max(int(authorized.get(_ROLE, 0)), establishment)
    force["authorized_strength"] = sum(max(0, int(value)) for value in authorized.values())
    force.setdefault("available_by_role", {}).setdefault(_ROLE, 0)
    force.setdefault("available_by_location", {}).setdefault(_TRAINING_GROUND, {}).setdefault(_ROLE, 0)
    force.setdefault("available_equipment_units_by_role", {}).setdefault(_ROLE, 0)
    force.setdefault("available_equipment_by_location", {}).setdefault(_TRAINING_GROUND, {}).setdefault(_ROLE, 0)
    planner.put(_HOUSE_FORCE, force)
    return force


def _screening_cost(planner: Any, candidate_count: int) -> int:
    economy = planner.read(_ECONOMY_RULES_PATH)
    constants = economy.get("recruitment_cost_constants", {}) if isinstance(economy, Mapping) else {}
    campaign_rules = economy.get("recruitment_campaign", {}) if isinstance(economy, Mapping) else {}
    key = str(campaign_rules.get("screening_cost_key", "screened_candidate_ordinary"))
    rate = float(constants.get(key, 0.1))
    return max(0, int(math.ceil(candidate_count * rate - 1e-9)))


def _settle_screening(planner: Any, great_rules: Mapping[str, Any], house: dict[str, Any], great: dict[str, Any], campaign_ref: str, at: str) -> dict[str, Any] | None:
    registry, campaign = _campaign(planner, campaign_ref)
    if campaign is None:
        return None
    current = max(0, int(campaign.get("remaining_candidates", 0)))
    establishment = max(1, int(great_rules.get("fighting_establishment_max", 300)))
    if current <= establishment:
        campaign["status"] = "training_candidate"
        campaign["destination_force_ref"] = "force_house_tang"
        campaign["role"] = _ROLE
        planner.put(REGISTRY_PATH, registry)
        return None

    treasury = planner.read(_TREASURY_PATH)
    safety = _treasury_safe_ceiling(treasury, planner.read(_HOUSE_RULES_PATH))
    cost = _screening_cost(planner, current)
    if cost > int(treasury.get("silver", 0)) or cost > int(safety.get("treasury_safe_ceiling_silver", 0)):
        report_ref = _report(
            planner,
            at=at,
            key=f"gbg_screening_blocked:{campaign_ref}:{current}:{cost}",
            summary=(
                f"House Tang reports that Great Bow Guard screening is ready to examine {current} registered applicants, but the registered screening cost of {cost} silver is outside the current treasury-safe discretionary ceiling. "
                "The applicants remain conserved in the candidate pool; no one is accepted or rejected until lawful screening can be funded."
            ),
        )
        return _wake_for_report(planner, report_ref, at)

    _prepare_house_force(planner, establishment)
    campaign["destination_force_ref"] = "force_house_tang"
    campaign["role"] = _ROLE
    planner.put(REGISTRY_PATH, registry)
    selection_ref = str(great.get("selection_profile", great_rules.get("selection_profile", "wei_archery_trial")))
    result = stage_campaign(
        planner,
        {"campaign_ref": campaign_ref, "selection_profile": selection_ref, "retain_count": establishment},
        evidence_ref=f"house_great_bow_guard_screening:{at}",
    )
    registry = _candidate_registry(planner)
    campaign = registry.get("campaigns", {}).get(campaign_ref)
    if not isinstance(campaign, MutableMapping):
        raise ValueError("Great Bow Guard candidate campaign disappeared after screening")
    campaign["status"] = "training_candidate"
    campaign["destination_force_ref"] = "force_house_tang"
    campaign["role"] = _ROLE
    campaign["screened_at"] = at
    planner.put(REGISTRY_PATH, registry)

    great["screened_candidates"] = int(result.get("before", current))
    great["rejected_candidates"] = int(great.get("rejected_candidates", 0)) + int(result.get("rejected", 0))
    great["shortlisted_candidates"] = int(result.get("remaining_candidates", establishment))
    great["recruitment_phase"] = "candidate_training"
    great["recruitment_spending_silver"] = int(great.get("recruitment_spending_silver", 0)) + int(result.get("silver_spent", 0))
    house["administrative_programs"]["great_bow_guard"] = great
    planner.put(_HOUSE_PATH, house)
    report_ref = _report(
        planner,
        at=at,
        key=f"gbg_screened:{campaign_ref}",
        summary=(
            f"House Tang completes the registered Great Bow Guard screening. All {int(result.get('before', current))} applicants are examined under {selection_ref}; {int(result.get('remaining_candidates', establishment))} are retained for training and {int(result.get('rejected', 0))} are released back to their conserved civilian source populations. "
            f"Screening costs {int(result.get('silver_spent', 0))} silver. No fighter or equipment is created by screening; the retained candidates now enter verified House training."
        ),
    )
    return _wake_for_report(planner, report_ref, at)


def _finalize_trained_candidates(planner: Any, house: dict[str, Any], great: dict[str, Any], campaign_ref: str, at: str, establishment: int) -> str:
    registry, campaign = _campaign(planner, campaign_ref)
    if campaign is None:
        raise ValueError("Great Bow Guard finalization lost its candidate campaign")
    n = max(0, int(campaign.get("remaining_candidates", 0)))
    if n <= 0 or n > establishment:
        raise ValueError("Great Bow Guard accepted candidate count is invalid")

    pop = copy.deepcopy(planner.read(_QIN_POPULATION))
    strata = pop.setdefault("strata", {})
    reserved = str(campaign.get("reserved_stratum", "recruitment_candidates_reserved"))
    if int(strata.get(reserved, 0)) < n:
        raise ValueError("Great Bow Guard reserved candidate population is inconsistent")
    local_service: list[dict[str, Any]] = []
    if hasattr(planner, "_finalize_local_candidate_reservations"):
        local_service = planner._finalize_local_candidate_reservations(pop, campaign_ref, "force_house_tang")
        if sum(int(row.get("personnel", 0)) for row in local_service) != n:
            raise ValueError("Great Bow Guard locality finalization does not match accepted population")
    strata[reserved] = int(strata.get(reserved, 0)) - n
    strata["private_household_military"] = int(strata.get("private_household_military", 0)) + n

    force = _prepare_house_force(planner, establishment)
    ensure_cohort_ledger(force, at=at)
    add_recruits(force, _ROLE, n, location_ref=_TRAINING_GROUND)
    profiles = planner.read(PROFILE_PATH)
    cohort_refs: list[str] = []
    for candidate_slice in campaign.get("slices", []):
        if not isinstance(candidate_slice, Mapping) or int(candidate_slice.get("count", 0)) <= 0:
            continue
        cohort_ref = record_recruitment_cohort(
            force,
            role=_ROLE,
            count=int(candidate_slice["count"]),
            location_ref=_TRAINING_GROUND,
            source_population_ref="population_qin",
            source_stratum=str(candidate_slice.get("source_stratum", "")),
            recruited_at=at,
            profile_registry=profiles,
            background_profile=str(candidate_slice.get("background_profile", "")),
            provenance_ref=f"house_great_bow_guard_acceptance:{campaign_ref}:{at}",
            conditioned_profile=candidate_slice.get("profile") if isinstance(candidate_slice.get("profile"), Mapping) else None,
            selection_history=candidate_slice.get("selection_history", []),
            intake_ref=campaign_ref,
            validate=False,
        )
        if cohort_ref:
            cohort_refs.append(cohort_ref)
    validate_cohort_ledger(force)

    campaign["status"] = "accepted_equipment_pending"
    campaign["accepted_count"] = n
    campaign["accepted_at"] = at
    campaign["cohort_refs"] = cohort_refs
    campaign["local_service_allocations"] = local_service
    planner.put(REGISTRY_PATH, registry)
    planner.put(_QIN_POPULATION, pop)
    planner.put(_HOUSE_FORCE, force)

    great["accepted_fighters"] = n
    great["shortlisted_candidates"] = n
    great["status"] = "forming"
    great["recruitment_phase"] = "equipment_and_formation_pending"
    great["accepted_at"] = at
    great["accepted_cohort_refs"] = cohort_refs
    house["administrative_programs"]["great_bow_guard"] = great
    planner.put(_HOUSE_PATH, house)
    return _report(
        planner,
        at=at,
        key=f"gbg_training_complete:{campaign_ref}",
        summary=(
            f"House Tang reports that {n} Great Bow Guard candidates have completed the registered selection and verified candidate-training phase and are now accepted into House Tang's conserved military force as Great Bow Guard fighters. "
            "They are not yet a field formation: the registered full fighter loadout, arrow reserve, equipment issue, and separate formation materialization remain outstanding consequences. No equipment or extra bodies are invented by this acceptance."
        ),
    )


def _settle_training(planner: Any, great_rules: Mapping[str, Any], training_cfg: Mapping[str, Any], house: dict[str, Any], great: dict[str, Any], campaign_ref: str, at: str) -> dict[str, Any] | None:
    registry, campaign = _campaign(planner, campaign_ref)
    if campaign is None or str(campaign.get("status", "")) != "training_candidate":
        return None
    candidates = max(0, int(campaign.get("remaining_candidates", 0)))
    establishment = max(1, int(great_rules.get("fighting_establishment_max", 300)))
    if candidates <= 0 or candidates > establishment:
        raise ValueError("Great Bow Guard training pool must be screened to its registered establishment")
    hours = max(1, int(training_cfg.get("deliberate_hours_per_review", 56)))
    day_hours = max(1.0, float(training_cfg.get("training_day_hours", 24.0)))
    food_rate = max(0.0, float(training_cfg.get("food_kg_per_candidate_day", 1.6)))
    food_needed = max(0, int(math.ceil(candidates * food_rate * hours / day_hours - 1e-9)))
    treasury = copy.deepcopy(planner.read(_TREASURY_PATH))
    if int(treasury.get("food_kg", 0)) < food_needed:
        report_ref = _report(
            planner,
            at=at,
            key=f"gbg_training_food_blocked:{campaign_ref}:{food_needed}",
            summary=(
                f"House Tang reports that Great Bow Guard candidate training is temporarily constrained by food support. The next registered training block requires {food_needed} kg for {candidates} candidates, but the House treasury does not currently hold that amount. "
                "The candidates remain conserved and accepted by no fiction shortcut; training resumes when exact support is available."
            ),
        )
        return _wake_for_report(planner, report_ref, at)

    profile_registry = planner.read(PROFILE_PATH)
    regimens = profile_registry.get("training_regimens", {}) if isinstance(profile_registry, Mapping) else {}
    regimen = regimens.get("house_tang_max_sustainable", {}) if isinstance(regimens, Mapping) else {}
    training_rules = planner.read(_TRAINING_RULES_PATH)
    skill_focuses = [str(value) for value in training_cfg.get("skill_focuses", []) if isinstance(value, str)]
    attribute_focuses = [str(value) for value in training_cfg.get("attribute_focuses", []) if isinstance(value, str)]
    evidence_ref = f"house_great_bow_guard_training:{campaign_ref}:{at}"
    changed = 0
    for candidate_slice in campaign.get("slices", []):
        if not isinstance(candidate_slice, MutableMapping) or int(candidate_slice.get("count", 0)) <= 0:
            continue
        profile = candidate_slice.get("profile")
        if not isinstance(profile, MutableMapping):
            continue
        advance_cohort_training(
            profile,
            deliberate_hours=float(hours),
            role_exposure_hours=0.0,
            skill_focuses=skill_focuses,
            attribute_focuses=attribute_focuses,
            training_rules=training_rules,
            facility_grade=str(regimen.get("facility_grade", "adequate")),
            equipment_grade=str(regimen.get("equipment_grade", "adequate")),
            recovery_grade=str(regimen.get("recovery_grade", "adequate")),
            evidence_ref=evidence_ref,
        )
        changed += 1
    if changed <= 0:
        raise ValueError("Great Bow Guard candidate training has no live candidate slices")
    treasury["food_kg"] = int(treasury.get("food_kg", 0)) - food_needed
    total_hours = round(float(campaign.get("verified_training_hours_per_person", 0.0)) + hours, 3)
    campaign["verified_training_hours_per_person"] = total_hours
    campaign.setdefault("stage_history", []).append({"kind": "candidate_training", "hours": hours, "at": at, "evidence_ref": evidence_ref})
    campaign["stage_history"] = campaign["stage_history"][-32:]
    campaign.setdefault("economic_history", []).append({"kind": "candidate_training_support", "hours": hours, "food_kg": food_needed, "candidate_count": candidates, "evidence_ref": evidence_ref})
    campaign["economic_history"] = campaign["economic_history"][-32:]
    planner.put(_TREASURY_PATH, treasury)
    planner.put(REGISTRY_PATH, registry)

    great["verified_training_hours_per_candidate"] = total_hours
    great["last_candidate_training_at"] = at
    great["recruitment_phase"] = "candidate_training"
    house["administrative_programs"]["great_bow_guard"] = great
    planner.put(_HOUSE_PATH, house)

    minimum = max(hours, int(training_cfg.get("minimum_verified_training_hours", 224)))
    if total_hours < minimum:
        return None
    report_ref = _finalize_trained_candidates(planner, house, great, campaign_ref, at, establishment)
    return _wake_for_report(planner, report_ref, at)


def settle_great_bow_guard_review(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    house, great = _program(planner)
    campaign_ref = str(great.get("candidate_campaign_ref", ""))
    if not campaign_ref:
        return None
    great_rules, training_cfg = _rules(planner)
    registry, campaign = _campaign(planner, campaign_ref)
    if campaign is None:
        return None
    status = str(campaign.get("status", ""))
    if status == "screening":
        return _settle_screening(planner, great_rules, house, great, campaign_ref, at)
    if status == "training_candidate":
        return _settle_training(planner, great_rules, training_cfg, house, great, campaign_ref, at)
    return None


def sync_great_bow_guard_flow(planner: Any, runtime: dict[str, Any]) -> None:
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    try:
        _house, great = _program(planner)
    except ValueError:
        return
    campaign_ref = str(great.get("candidate_campaign_ref", ""))
    if not campaign_ref:
        return
    _registry, campaign = _campaign(planner, campaign_ref)
    active = isinstance(campaign, Mapping) and str(campaign.get("status", "")) in {"screening", "training_candidate"}
    if not active:
        hosts.pop(_HOST_ID, None)
        events[:] = [row for row in events if not (isinstance(row, Mapping) and row.get("target_host") == _HOST_ID)]
        return
    _great_rules, training_cfg = _rules(planner)
    recurrence = max(86400, int(training_cfg.get("review_seconds", 7 * 86400)))
    now = CampaignTime.parse(str(runtime["world_time"]))
    host = hosts.get(_HOST_ID)
    if not isinstance(host, dict):
        host = {
            "host_id": _HOST_ID,
            "kind": "house_gbg_lifecycle",
            "owner_ref": "house_tang",
            "campaign_ref": campaign_ref,
            "recurrence_seconds": recurrence,
            "next_due": str(now),
            "resolved_through": str(now.add_seconds(-1)),
            "safe_through": str(now.add_seconds(-1)),
        }
        hosts[_HOST_ID] = host
    else:
        host["kind"] = "house_gbg_lifecycle"
        host["owner_ref"] = "house_tang"
        host["campaign_ref"] = campaign_ref
        host["recurrence_seconds"] = recurrence
        if host.get("next_due") is None:
            host["next_due"] = str(now)
            host["safe_through"] = str(now.add_seconds(-1))
    event = next((row for row in events if isinstance(row, dict) and row.get("event_id") == _EVENT_ID), None)
    if not isinstance(event, dict):
        events.append({"event_id": _EVENT_ID, "kind": "house_gbg_lifecycle", "priority": _PRIORITY, "target_host": _HOST_ID, "due_at": str(host["next_due"])})
    else:
        event.update({"kind": "house_gbg_lifecycle", "priority": _PRIORITY, "target_host": _HOST_ID, "due_at": str(host["next_due"])})
        event.pop("suspended", None)


class GreatBowGuardFlowMixin:
    """Add the missing autonomous screening/training steps after applicant intake."""

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        sync_great_bow_guard_flow(self, runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") == "house_gbg_lifecycle":
            wake = settle_great_bow_guard_review(self, host, due_text)
            if isinstance(wake, dict):
                wake["target_host"] = self._active_host_id
                wake["event_id"] = self._active_event_id
            self._pending_wake_created = wake
            return
        super()._run_due_host(host, due_text)


__all__ = [
    "GreatBowGuardFlowMixin",
    "settle_great_bow_guard_review",
    "sync_great_bow_guard_flow",
]
