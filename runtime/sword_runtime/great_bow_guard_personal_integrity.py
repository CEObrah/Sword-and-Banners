"""Close Great Bow Guard ownership and training-provenance invariants.

The Great Bow Guard is Tang Wei's personal elite formation project. House Tang is
its sponsor and administrative supporter, not the troop owner. Earlier lifecycle
code finalized accepted candidates into the House institutional force and dropped
candidate training metadata when cohort records were materialized. This adapter
repairs the already-accepted campaign and closes the same invariants for future
acceptance without minting bodies, equipment, training time, or field formations.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import ensure_cohort_ledger, role_count, transfer_between_forces, validate_cohort_ledger
from sword_runtime.recruitment_campaigns import REGISTRY_PATH

_HOUSE_PATH = "state/houses/house_tang.json"
_HOUSE_FORCE_PATH = "state/forces/house-tang.json"
_PERSONAL_FORCE_PATH = "state/forces/tang-wei-personal.json"
_QIN_POPULATION_PATH = "state/population/qin.json"
_ROLE = "great_bow_guard"
_LOCATION = "loc_tang_manor_training_ground"
_PERSONAL_FORCE_REF = "force_tang_wei_personal"
_HOUSE_FORCE_REF = "force_house_tang"


def _cohort_total(row: Mapping[str, Any]) -> int:
    return sum(max(0, int(value)) for value in row.get("reserve_by_location", {}).values()) + sum(
        max(0, int(value)) for value in row.get("allocated_by_formation", {}).values()
    )


def _campaign_and_program(planner: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], MutableMapping[str, Any] | None]:
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    programs = house.setdefault("administrative_programs", {})
    great = programs.get("great_bow_guard")
    if not isinstance(great, dict):
        return house, {}, {}, None
    campaign_ref = str(great.get("candidate_campaign_ref", ""))
    registry = copy.deepcopy(planner.read(REGISTRY_PATH))
    campaign = registry.get("campaigns", {}).get(campaign_ref) if campaign_ref else None
    return house, great, registry, campaign if isinstance(campaign, MutableMapping) else None


def _restore_candidate_training(personal_force: MutableMapping[str, Any], campaign: Mapping[str, Any], campaign_ref: str) -> list[str]:
    slices: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in campaign.get("slices", []):
        if not isinstance(row, Mapping) or int(row.get("count", 0)) <= 0:
            continue
        key = (str(row.get("source_stratum", "")), str(row.get("background_profile", "")))
        if key in slices:
            raise ValueError("Great Bow Guard candidate training repair has ambiguous source/background slice")
        slices[key] = row

    ledger = ensure_cohort_ledger(personal_force)
    repaired_refs: list[str] = []
    repaired_count = 0
    for cohort_id, cohort in ledger.get("cohorts", {}).items():
        if not isinstance(cohort, MutableMapping) or str(cohort.get("role", "")) != _ROLE:
            continue
        origin = cohort.get("origin", {}) if isinstance(cohort.get("origin"), Mapping) else {}
        if str(origin.get("intake_ref", "")) != campaign_ref:
            continue
        key = (str(origin.get("source_stratum", "")), str(origin.get("background_profile", "")))
        source_slice = slices.get(key)
        if not isinstance(source_slice, Mapping):
            raise ValueError("Great Bow Guard accepted cohort lost its exact candidate training slice")
        expected = max(0, int(source_slice.get("count", 0)))
        actual = _cohort_total(cohort)
        if actual != expected:
            raise ValueError("Great Bow Guard accepted cohort count does not match candidate training slice")
        profile = source_slice.get("profile")
        if not isinstance(profile, Mapping):
            raise ValueError("Great Bow Guard candidate training profile is unavailable")
        for key_name in (
            "age_distribution", "aptitude_means", "aptitude_sd", "aptitude_min", "aptitude_max",
            "attribute_means", "attribute_sd", "attribute_min", "attribute_max",
            "skill_means", "skill_sd", "skill_min", "skill_max",
            "skill_edu_banks", "attribute_edu_banks", "correlation_groups",
            "verified_training_hours_per_person", "verified_role_exposure_hours_per_person", "training_history",
        ):
            if key_name in profile:
                cohort[key_name] = copy.deepcopy(profile[key_name])
        repaired_refs.append(str(cohort_id))
        repaired_count += actual
    accepted = max(0, int(campaign.get("accepted_count", 0)))
    if repaired_count != accepted:
        raise ValueError("Great Bow Guard personal-force cohort repair does not cover accepted manpower")
    validate_cohort_ledger(personal_force)
    return repaired_refs


def _repair_population_service_owner(planner: Any, accepted: int) -> None:
    population = copy.deepcopy(planner.read(_QIN_POPULATION_PATH))
    sites = population.get("local_population", {}).get("sites", {}) if isinstance(population.get("local_population"), Mapping) else {}
    site = sites.get(_LOCATION) if isinstance(sites, Mapping) else None
    if not isinstance(site, MutableMapping):
        return
    allocations = site.setdefault("service_allocations", {})
    personal = allocations.get(_PERSONAL_FORCE_REF)
    personal_count = int(personal.get("personnel", 0)) if isinstance(personal, Mapping) else 0
    house = allocations.get(_HOUSE_FORCE_REF)
    house_count = int(house.get("personnel", 0)) if isinstance(house, Mapping) else 0
    if personal_count >= accepted and house_count == 0:
        return
    if personal_count not in {0, accepted}:
        raise ValueError("Great Bow Guard population service owner conflicts with existing personal-force allocation")
    if house_count < accepted:
        raise ValueError("Great Bow Guard population service owner lacks accepted House allocation")
    source = dict(house) if isinstance(house, Mapping) else {}
    remaining = house_count - accepted
    if remaining:
        source["personnel"] = remaining
        allocations[_HOUSE_FORCE_REF] = source
    else:
        allocations.pop(_HOUSE_FORCE_REF, None)
    allocations[_PERSONAL_FORCE_REF] = {
        "personnel": accepted,
        "service_class": "private_house_military",
        "source_stratum": str(source.get("source_stratum", "private_household_military")),
    }
    planner.put(_QIN_POPULATION_PATH, population)


def repair_great_bow_guard_personal_ownership(planner: Any, *, at: str) -> dict[str, Any] | None:
    house, great, registry, campaign = _campaign_and_program(planner)
    if campaign is None or str(campaign.get("status", "")) != "accepted_equipment_pending":
        return None
    campaign_ref = str(campaign.get("campaign_ref", ""))
    accepted = max(0, int(campaign.get("accepted_count", 0)))
    if not campaign_ref or accepted <= 0:
        return None

    house_force = copy.deepcopy(planner.read(_HOUSE_FORCE_PATH))
    personal_force = copy.deepcopy(planner.read(_PERSONAL_FORCE_PATH))
    destination = str(campaign.get("destination_force_ref", ""))
    personal_count = role_count(personal_force, _ROLE)
    house_count = role_count(house_force, _ROLE)

    changed = False
    if destination != _PERSONAL_FORCE_REF:
        if personal_count not in {0, accepted}:
            raise ValueError("Great Bow Guard ownership repair found conflicting personal-force manpower")
        if personal_count == 0:
            if house_count < accepted:
                raise ValueError("Great Bow Guard ownership repair cannot find conserved accepted House manpower")
            moved = transfer_between_forces(
                house_force,
                personal_force,
                source_role=_ROLE,
                destination_role=_ROLE,
                count=accepted,
                source_location_ref=_LOCATION,
                destination_location_ref=_LOCATION,
                evidence_ref=f"gbg_personal_ownership:{campaign_ref}:{at}",
            )
            if moved != accepted:
                raise ValueError("Great Bow Guard ownership repair did not transfer all accepted manpower")
        campaign["destination_force_ref"] = _PERSONAL_FORCE_REF
        for row in campaign.get("local_service_allocations", []):
            if isinstance(row, MutableMapping) and str(row.get("force_ref", "")) == _HOUSE_FORCE_REF:
                row["force_ref"] = _PERSONAL_FORCE_REF
        changed = True

    cohort_refs = _restore_candidate_training(personal_force, campaign, campaign_ref)
    if sorted(str(value) for value in campaign.get("cohort_refs", [])) != sorted(cohort_refs):
        campaign["cohort_refs"] = cohort_refs
        changed = True

    great["force_ref"] = _PERSONAL_FORCE_REF
    great["command_authority_ref"] = "char_tang_wei"
    great["administrative_sponsor_ref"] = "house_tang"
    great["accepted_cohort_refs"] = cohort_refs
    great["ownership_rule"] = "Tang Wei owns and commands Great Bow Guard manpower; House Tang may sponsor, supply and administer without acquiring troop ownership."
    house["administrative_programs"]["great_bow_guard"] = great

    authorized = house_force.get("authorized_by_role")
    if isinstance(authorized, MutableMapping) and _ROLE in authorized:
        authorized.pop(_ROLE, None)
        house_force["authorized_strength"] = sum(max(0, int(value)) for value in authorized.values())
        changed = True
    personal_force["authorized_strength"] = max(int(personal_force.get("authorized_strength", 0)), int(personal_force.get("headcount", 0)))

    history = campaign.setdefault("ownership_repair_history", [])
    if not any(isinstance(row, Mapping) and row.get("kind") == "tang_wei_personal_force_closure" for row in history):
        history.append({
            "kind": "tang_wei_personal_force_closure",
            "at": at,
            "from_force_ref": _HOUSE_FORCE_REF,
            "to_force_ref": _PERSONAL_FORCE_REF,
            "personnel": accepted,
            "training_hours_per_person": float(campaign.get("verified_training_hours_per_person", 0.0) or 0.0),
            "evidence_rule": "conserved cohort transfer plus exact candidate-slice training provenance",
        })
        campaign["ownership_repair_history"] = history[-16:]
        changed = True

    if changed:
        _repair_population_service_owner(planner, accepted)
    planner.put(_HOUSE_FORCE_PATH, house_force)
    planner.put(_PERSONAL_FORCE_PATH, personal_force)
    planner.put(REGISTRY_PATH, registry)
    planner.put(_HOUSE_PATH, house)
    return {"campaign_ref": campaign_ref, "personnel": accepted, "cohort_refs": cohort_refs, "changed": changed}


def _rewrite_acceptance_wake(planner: Any, wake: MutableMapping[str, Any] | None) -> None:
    if not isinstance(wake, MutableMapping):
        return
    event_ref = wake.get("campaign_event_ref")
    if not isinstance(event_ref, str):
        return
    event = get_causal_event(planner, event_ref)
    if not isinstance(event, Mapping):
        return
    summary = str(event.get("summary", ""))
    marker = "accepted into House Tang's conserved military force as Great Bow Guard fighters"
    if marker not in summary:
        return
    corrected = summary.replace(
        marker,
        "accepted into Tang Wei's conserved personal force as Great Bow Guard fighters, with House Tang remaining their sponsor and supplier",
    )
    _path, owner = read_causal_event_owner(planner)
    mutable = owner.get("causal_events", {}).get(event_ref)
    if isinstance(mutable, MutableMapping):
        mutable["summary"] = corrected[:4000]
        write_causal_event_owner(planner, owner)
    wake["reason"] = corrected[:4000]


class GreatBowGuardPersonalIntegrityMixin:
    """Repair current GBG ownership and close future acceptance in the same transaction."""

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = self.read("state/runtime.json")
        repair_great_bow_guard_personal_ownership(self, at=str(runtime["world_time"]))
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") != "house_gbg_lifecycle":
            return super()._run_due_host(host, due_text)
        super()._run_due_host(host, due_text)
        repair_great_bow_guard_personal_ownership(self, at=due_text)
        _rewrite_acceptance_wake(self, self._pending_wake_created)


__all__ = ["GreatBowGuardPersonalIntegrityMixin", "repair_great_bow_guard_personal_ownership"]
