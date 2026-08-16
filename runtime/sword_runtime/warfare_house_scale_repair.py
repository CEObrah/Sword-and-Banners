"""Registered one-time repair for the Great Bow Guard scale defect.

The committed campaign currently contains a valid 300-fighter first intake that
was represented one decimal scale too small. This maintenance recipe advances no
time and replays no contested outcome. It expands the same fifteen recruitment
and provenance cohorts from a combined 300 fighters to fifteen conserved
200-fighter cohorts, transfers exactly 2,700 additional bodies from the same
saved Qin civilian source strata into Tang Wei's private military force, and
reconciles the already-recorded screening/training resource history at the same
10x representation scale.

The repair deliberately does not manufacture weapons, mounts, support staff,
Sword Manor officers or named commanders. Those remain separate lawful staffing,
issue, procurement and materialization consequences.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.history_store import HISTORY_INDEX_PATH, write_history_index
from sword_runtime.warfare_depth import build_formation_command_structure

_REPAIR_ID = "warfare_house_gbg_depth_v2"
_GBG_FORCE = "state/forces/tang-wei-personal.json"
_GBG_FORMATION = "state/formations/tang-wei-great-bow-guard-first.json"
_CANDIDATES = "state/recruitment/candidate-pools.json"
_POPULATION = "state/population/qin.json"
_TREASURY = "state/treasury/treasury-house-tang.json"
_PRIVATE_ECONOMY = "state/economy/private/qin.json"
_HOUSE = "state/houses/house_tang.json"
_QIN_BORDER = "state/formations/qin-border-line.json"
_PLAYER = "state/player.json"
_RETINUE_GROUP = "state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json"
_RULES = "game/data/mechanics/warfare-organization.json"
_GBG_PROGRAM = "game/data/mechanics/house-tang-programs.json"
_GBG_FORMATION_REF = "formation_tang_wei_great_bow_guard_first"
_LOCATION = "loc_tang_manor_training_ground"


def _scaled_rows(rows: list[Mapping[str, Any]], factor: int, *, key: str) -> list[dict[str, Any]]:
    if factor <= 0:
        raise ValueError("scale repair factor must be positive")
    result: list[dict[str, Any]] = []
    for row in rows:
        item = copy.deepcopy(dict(row))
        item[key] = max(0, int(row.get(key, 0))) * factor
        result.append(item)
    return result


def _cohort_plan(force: MutableMapping[str, Any], at: str, *, target_count: int, cohort_size: int) -> tuple[list[str], list[dict[str, Any]]]:
    ledger = force.get("cohort_ledger")
    cohorts = ledger.get("cohorts", {}) if isinstance(ledger, MutableMapping) else None
    if not isinstance(cohorts, MutableMapping):
        raise ValueError("GBG scale repair requires a cohort ledger")
    parents: list[tuple[str, MutableMapping[str, Any], int]] = []
    for cid, row in cohorts.items():
        if not isinstance(row, MutableMapping) or str(row.get("role", "")) != "great_bow_guard":
            continue
        count = max(0, int(row.get("allocated_by_formation", {}).get(_GBG_FORMATION_REF, 0)))
        if count:
            parents.append((str(cid), row, count))
    parents.sort(key=lambda item: item[0])
    if len(parents) != target_count or sum(item[2] for item in parents) != 300:
        raise ValueError("GBG scale repair precondition changed: expected fifteen current cohorts totaling 300")

    refs: list[str] = []
    composition: list[dict[str, Any]] = []
    for cid, cohort, old_count in parents:
        allocated = cohort.setdefault("allocated_by_formation", {})
        allocated[_GBG_FORMATION_REF] = cohort_size
        cohort["command_candidate_status"] = "aggregate_internal_candidate_body"
        cohort["command_candidate_rule"] = "internal command may be selected from this conserved Great Bow Guard body without adding manpower"
        tags = cohort.setdefault("tags", [])
        if "great_bow_guard_internal_command_source" not in tags:
            tags.append("great_bow_guard_internal_command_source")
        history = cohort.setdefault("scale_repair_history", [])
        history.append({
            "at": at,
            "repair_id": _REPAIR_ID,
            "personnel_before": old_count,
            "personnel_after": cohort_size,
            "cohort_id_preserved": True,
            "reason": "correct decimal-scale representation while preserving original recruitment provenance",
        })
        cohort["scale_repair_history"] = history[-8:]
        refs.append(cid)
        composition.append({"cohort_id": cid, "count": cohort_size})
    if len(refs) != target_count or sum(row["count"] for row in composition) != target_count * cohort_size:
        raise ValueError("GBG scale repair failed to preserve fifteen 200-person cohorts")
    return refs, composition


def _apply_population_scale(
    population: MutableMapping[str, Any],
    *,
    old_service_rows: list[Mapping[str, Any]],
    final_service_rows: list[Mapping[str, Any]],
    additional_personnel: int,
) -> None:
    site = population.get("local_population", {}).get("sites", {}).get(_LOCATION)
    if not isinstance(site, MutableMapping):
        raise ValueError("GBG scale repair missing Tang Manor local population site")
    current_alloc = site.get("service_allocations", {}).get("force_tang_wei_personal")
    if not isinstance(current_alloc, MutableMapping) or int(current_alloc.get("personnel", 0)) != 300:
        raise ValueError("GBG scale repair local service allocation is not the expected 300")
    old_by_source = {str(row.get("source_stratum")): max(0, int(row.get("personnel", 0))) for row in old_service_rows}
    final_by_source = {str(row.get("source_stratum")): max(0, int(row.get("personnel", 0))) for row in final_service_rows}
    if sum(old_by_source.values()) != 300 or sum(final_by_source.values()) != 3000:
        raise ValueError("GBG scale repair service-source totals changed")
    strata = population.get("strata")
    local_civ = site.get("civilian_strata")
    if not isinstance(strata, MutableMapping) or not isinstance(local_civ, MutableMapping):
        raise ValueError("GBG scale repair population strata are invalid")
    moved = 0
    for source, final_count in sorted(final_by_source.items()):
        delta = final_count - int(old_by_source.get(source, 0))
        if delta < 0:
            raise ValueError("GBG scale repair cannot return already-serving manpower")
        if delta == 0:
            continue
        if int(strata.get(source, 0)) < delta or int(local_civ.get(source, 0)) < delta:
            raise ValueError(f"GBG scale repair lacks conserved civilian source {source}")
        strata[source] = int(strata.get(source, 0)) - delta
        local_civ[source] = int(local_civ.get(source, 0)) - delta
        moved += delta
    if moved != additional_personnel:
        raise ValueError("GBG scale repair must transfer exactly 2700 additional civilians")
    strata["private_household_military"] = int(strata.get("private_household_military", 0)) + moved
    site["civilian_population"] = int(site.get("civilian_population", 0)) - moved
    site["private_household_military"] = int(site.get("private_household_military", 0)) + moved
    site["service_population"] = int(site.get("service_population", 0)) + moved
    if "agricultural_available" in site:
        site["agricultural_available"] = int(local_civ.get("agricultural", site.get("agricultural_available", 0)))
    current_alloc["personnel"] = 3000


def _scale_recruitment_economics(campaign: MutableMapping[str, Any], factor: int) -> tuple[int, int]:
    additional_silver = 0
    additional_food = 0
    for row in campaign.get("economic_history", []):
        if not isinstance(row, MutableMapping):
            continue
        old_silver = max(0, int(row.get("silver", 0)))
        old_food = max(0, int(row.get("food_kg", 0)))
        if "candidate_count" in row:
            row["candidate_count"] = max(0, int(row.get("candidate_count", 0))) * factor
        if "silver" in row:
            row["silver"] = old_silver * factor
        if "food_kg" in row:
            row["food_kg"] = old_food * factor
        additional_silver += max(0, int(row.get("silver", 0)) - old_silver)
        additional_food += max(0, int(row.get("food_kg", 0)) - old_food)
    return additional_silver, additional_food


def apply_warfare_house_scale_repair(planner: Any, command: Any, reason: str) -> dict[str, Any]:
    at = str(command.submitted_at)
    force = copy.deepcopy(planner.read(_GBG_FORCE))
    formation = copy.deepcopy(planner.read(_GBG_FORMATION))
    registry = copy.deepcopy(planner.read(_CANDIDATES))
    population = copy.deepcopy(planner.read(_POPULATION))
    treasury = copy.deepcopy(planner.read(_TREASURY))
    economy = copy.deepcopy(planner.read(_PRIVATE_ECONOMY))
    house = copy.deepcopy(planner.read(_HOUSE))
    qin_border = copy.deepcopy(planner.read(_QIN_BORDER))
    player = copy.deepcopy(planner.read(_PLAYER))
    retinue = copy.deepcopy(planner.read(_RETINUE_GROUP))
    warfare_rules = planner.read(_RULES)
    program_rules = planner.read(_GBG_PROGRAM)

    static_gbg = program_rules.get("great_bow_guard", {}) if isinstance(program_rules, Mapping) else {}
    org_gbg = warfare_rules.get("great_bow_guard", {}) if isinstance(warfare_rules, Mapping) else {}
    target = int(static_gbg.get("fighting_establishment_max", 0))
    org_target = int(org_gbg.get("fighting_establishment", 0))
    cohort_count = int(static_gbg.get("conserved_recruitment_cohorts", org_gbg.get("conserved_recruitment_cohorts", 0)))
    cohort_size = int(static_gbg.get("preferred_recruitment_cohort_size", org_gbg.get("preferred_cohort_size", 0)))
    if target != 3000 or org_target != 3000 or cohort_count != 15 or cohort_size != 200:
        raise ValueError("GBG scale repair rules no longer describe 3000 fighters as fifteen 200-person cohorts")
    if target % 300 != 0:
        raise ValueError("GBG scale repair target is not an exact decimal expansion")
    factor = target // 300
    additional_personnel = target - 300

    if int(formation.get("personnel", 0)) != 300 or formation.get("composition") != {"great_bow_guard": 300}:
        raise ValueError("GBG scale repair precondition changed: formation is no longer the under-scaled 300")
    if float(formation.get("equipment_completeness", "0") or 0) != 0.0:
        raise ValueError("GBG scale repair requires the pre-issue formation")
    allocation = force.get("allocated_to_formations", {}).get(_GBG_FORMATION_REF, {})
    if not isinstance(allocation, Mapping) or int(allocation.get("personnel", 0)) != 300:
        raise ValueError("GBG scale repair precondition changed: personal-force allocation is not 300")

    programs = house.get("administrative_programs")
    gbg = programs.get("great_bow_guard") if isinstance(programs, MutableMapping) else None
    prep = programs.get("wei_field_preparation") if isinstance(programs, MutableMapping) else None
    if not isinstance(gbg, MutableMapping) or int(gbg.get("accepted_fighters", 0)) != 300:
        raise ValueError("GBG scale repair House program precondition changed")
    campaign_ref = str(gbg.get("candidate_campaign_ref", ""))
    campaign = registry.get("campaigns", {}).get(campaign_ref) if isinstance(registry, MutableMapping) else None
    if not isinstance(campaign, MutableMapping) or int(campaign.get("accepted_count", 0)) != 300:
        raise ValueError("GBG scale repair candidate campaign precondition changed")

    cohort_refs, composition = _cohort_plan(force, at, target_count=cohort_count, cohort_size=cohort_size)
    force["headcount"] = int(force.get("headcount", 0)) + additional_personnel
    force["authorized_strength"] = max(target, int(force.get("authorized_strength", 0)) + additional_personnel)
    force.setdefault("allocated_to_formations", {})[_GBG_FORMATION_REF] = {"personnel": target, "role": "great_bow_guard"}
    force.setdefault("available_by_role", {})["great_bow_guard"] = 0
    force.setdefault("available_by_location", {}).setdefault(_LOCATION, {})["great_bow_guard"] = 0
    force.setdefault("scale_repair_history", []).append({
        "at": at,
        "repair_id": _REPAIR_ID,
        "from_personnel": 300,
        "to_personnel": target,
        "additional_conserved_personnel": additional_personnel,
        "cohort_count": cohort_count,
        "cohort_personnel": cohort_size,
        "reason": reason,
    })
    force["scale_repair_history"] = force["scale_repair_history"][-8:]
    validate_cohort_ledger(force)

    formation["personnel"] = target
    formation["composition"] = {"great_bow_guard": target}
    formation["cohort_composition"] = composition
    formation["command_structure"] = build_formation_command_structure(formation, warfare_rules)
    formation.setdefault("scale_repair_history", []).append({
        "at": at,
        "repair_id": _REPAIR_ID,
        "from_personnel": 300,
        "to_personnel": target,
        "cohort_refs_preserved": True,
        "cohort_count": cohort_count,
    })
    formation["scale_repair_history"] = formation["scale_repair_history"][-8:]

    old_service_rows = [copy.deepcopy(dict(row)) for row in campaign.get("local_service_allocations", []) if isinstance(row, Mapping)]
    final_service_rows = _scaled_rows(old_service_rows, factor, key="personnel")
    _apply_population_scale(population, old_service_rows=old_service_rows, final_service_rows=final_service_rows, additional_personnel=additional_personnel)
    campaign["local_service_allocations"] = final_service_rows
    campaign["local_reservations"] = _scaled_rows([row for row in campaign.get("local_reservations", []) if isinstance(row, Mapping)], factor, key="personnel")
    campaign["slices"] = _scaled_rows([row for row in campaign.get("slices", []) if isinstance(row, Mapping)], factor, key="count")
    service_by_source = {str(row.get("source_stratum")): int(row.get("personnel", 0)) for row in final_service_rows}
    return_rows: list[dict[str, Any]] = []
    for row in campaign["local_reservations"]:
        source = str(row.get("source_stratum", ""))
        returned = int(row.get("personnel", 0)) - int(service_by_source.get(source, 0))
        if returned < 0:
            raise ValueError("GBG scale repair source service exceeds residential reservation")
        return_rows.append({"location_ref": _LOCATION, "personnel": returned, "source_stratum": source})
    returns = campaign.get("local_return_history", [])
    if isinstance(returns, list) and returns and isinstance(returns[-1], MutableMapping):
        returns[-1]["rows"] = return_rows

    for key in ("initial_applicants", "regional_application_count", "regional_application_records_nonresident", "regional_shortlist_count", "remaining_candidates", "accepted_count"):
        campaign[key] = max(0, int(campaign.get(key, 0))) * factor
    campaign["cohort_refs"] = cohort_refs
    campaign.setdefault("scale_repair_history", []).append({
        "at": at,
        "repair_id": _REPAIR_ID,
        "representation_factor": factor,
        "from_accepted": 300,
        "to_accepted": target,
        "cohort_count": cohort_count,
        "cohort_personnel": cohort_size,
        "cohort_refs_preserved": True,
        "reason": reason,
    })
    campaign["scale_repair_history"] = campaign["scale_repair_history"][-8:]
    additional_silver, additional_food = _scale_recruitment_economics(campaign, factor)

    if int(treasury.get("silver", 0)) < additional_silver or int(treasury.get("food_kg", 0)) < additional_food:
        raise ValueError("GBG scale repair lacks exact House resources for reconciled historical support")
    treasury["silver"] = int(treasury.get("silver", 0)) - additional_silver
    treasury["food_kg"] = int(treasury.get("food_kg", 0)) - additional_food
    local_regions = economy.get("local_regions", {}).get("regions", {}) if isinstance(economy, MutableMapping) else {}
    local_market = local_regions.get(_LOCATION) if isinstance(local_regions, MutableMapping) else None
    if not isinstance(local_market, MutableMapping):
        raise ValueError("GBG scale repair missing private-economy training-ground owner")
    local_market["cash_silver"] = int(local_market.get("cash_silver", 0)) + additional_silver
    economy["cash_silver"] = int(economy.get("cash_silver", 0)) + additional_silver

    gbg["accepted_cohort_refs"] = cohort_refs
    gbg["accepted_fighters"] = target
    gbg["fighting_establishment_max"] = target
    gbg["applicants_registered"] = int(gbg.get("applicants_registered", 0)) * factor
    gbg["recruitment_spending_silver"] = int(gbg.get("recruitment_spending_silver", 0)) * factor
    gbg["regional_applicants_screened"] = int(gbg.get("regional_applicants_screened", 0)) * factor
    gbg["regional_screening_rejected"] = int(gbg.get("regional_screening_rejected", 0)) * factor
    gbg["residential_trial_candidates"] = int(gbg.get("residential_trial_candidates", 0)) * factor
    gbg["screened_candidates"] = int(gbg.get("screened_candidates", 0)) * factor
    gbg["shortlisted_candidates"] = target
    gbg["rejected_candidates"] = int(gbg.get("rejected_candidates", 0)) * factor
    gbg["internal_command_candidate_source"] = "accepted_great_bow_guard_recruits"
    gbg["internal_command_node_target"] = 18
    gbg["internal_command_candidate_status"] = "aggregate_unmaterialized"
    gbg.pop("field_officer_cadre_requested", None)
    gbg.pop("field_officer_source_ref", None)
    gbg.setdefault("scale_repair_history", []).append({"at": at, "repair_id": _REPAIR_ID, "from_fighters": 300, "to_fighters": target, "reason": reason})
    gbg["scale_repair_history"] = gbg["scale_repair_history"][-8:]

    if isinstance(prep, MutableMapping):
        prep["great_bow_guard_personnel"] = target
        prep["manufacturing_truth"] = "Current exact House reserves remain current stock. The scale repair does not manufacture missing Great Bow Guard equipment, spares, mounts or ammunition."
        snapshot = prep.get("house_stock_snapshot")
        if isinstance(snapshot, MutableMapping):
            snapshot["food_kg"] = int(treasury.get("food_kg", 0))
            snapshot["silver"] = int(treasury.get("silver", 0))

    qin_border["command_structure"] = build_formation_command_structure(qin_border, warfare_rules)
    qin_border["command_structure"]["player_appointment_status"] = "awaiting_physical_assumption"
    qin_border["command_structure"]["named_subordinate_status"] = "aggregate_by_default_materialize_only_when_saved_relevance_or_evidence_requires"

    career = player.get("career_state")
    if isinstance(career, MutableMapping):
        appointments = career.get("appointments", [])
        for appointment in appointments if isinstance(appointments, list) else []:
            if isinstance(appointment, MutableMapping) and appointment.get("formation_ref") == "formation_qin_border_line":
                appointment["command_structure_status"] = "scale_aware_internal_echelons_registered"
                appointment["staffing_request_status"] = "conserved_external_staff_required_named_officers_sparse"
                appointment["briefed_command_structure"] = copy.deepcopy(qin_border["command_structure"])

    direct_units = retinue.setdefault("direct_unit_refs", [])
    if _GBG_FORMATION_REF not in direct_units:
        direct_units.append(_GBG_FORMATION_REF)

    history = copy.deepcopy(planner.read(HISTORY_INDEX_PATH))
    events = history.setdefault("events", [])
    if not isinstance(events, list):
        raise ValueError("scale repair history owner is invalid")
    event_id = "repair_bundle_" + command.digest[:16]
    events.append({
        "event_id": event_id,
        "kind": "explicit_repair_bundle",
        "at": at,
        "repair_id": _REPAIR_ID,
        "reason": reason,
        "summary": "Corrected the Great Bow Guard decimal-scale defect from 300 to 3000 fighters while preserving the same fifteen recruitment cohorts as fifteen 200-person cohorts; transferred 2700 additional conserved Qin civilians from the same saved source mix; reconciled recorded recruitment support at the same 10x representation scale; did not create equipment, Sword Manor officers, support personnel or named commanders.",
        "affected_owners": [_GBG_FORCE, _GBG_FORMATION, _CANDIDATES, _POPULATION, _TREASURY, _PRIVATE_ECONOMY, _HOUSE, _QIN_BORDER, _PLAYER, _RETINUE_GROUP],
    })
    write_history_index(planner, history)

    planner.put(_GBG_FORCE, force)
    planner.put(_GBG_FORMATION, formation)
    planner.put(_CANDIDATES, registry)
    planner.put(_POPULATION, population)
    planner.put(_TREASURY, treasury)
    planner.put(_PRIVATE_ECONOMY, economy)
    planner.put(_HOUSE, house)
    planner.put(_QIN_BORDER, qin_border)
    planner.put(_PLAYER, player)
    planner.put(_RETINUE_GROUP, retinue)

    return {
        "repair_event": event_id,
        "great_bow_guard_personnel": target,
        "great_bow_guard_cohorts": cohort_count,
        "great_bow_guard_cohort_personnel": cohort_size,
        "great_bow_guard_cohort_refs_preserved": True,
        "additional_conserved_personnel": additional_personnel,
        "internal_command_node_target": 18,
        "sword_manor_officers_created_or_seconded": 0,
        "qin_border_line_personnel": int(qin_border.get("personnel", 0)),
        "qin_border_line_internal_command_assignments": int(qin_border["command_structure"].get("internal_commander_assignments", 0)),
        "historical_additional_silver": additional_silver,
        "historical_additional_food_kg": additional_food,
        "equipment_created": 0,
    }


__all__ = ["apply_warfare_house_scale_repair"]
