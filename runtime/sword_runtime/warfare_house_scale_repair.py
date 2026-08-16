"""Registered one-time repair for the warfare/House/Great Bow Guard scale defect.

This recipe corrects an under-scaled abstraction already committed to the live
campaign.  It advances no time and does not replay outcomes.  It repartitions the
existing aggregate recruitment representation into 25 conserved 100-fighter
cohorts, moves the additional 2,200 bodies from exact Qin civilian strata into
private military service, reconciles the additional historical screening/training
cost, deepens House reserve stock by the explicitly requested scale correction,
raises (but does not fill) Sword Manor officer authorization, and registers zero-
body internal command structure for the 8,000-man Qin line formation.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.history_store import HISTORY_INDEX_PATH, write_history_index
from sword_runtime.warfare_depth import build_formation_command_structure

_REPAIR_ID = "warfare_house_gbg_depth_v1"
_GBG_FORCE = "state/forces/tang-wei-personal.json"
_GBG_FORMATION = "state/formations/tang-wei-great-bow-guard-first.json"
_CANDIDATES = "state/recruitment/candidate-pools.json"
_POPULATION = "state/population/qin.json"
_INVENTORY = "state/inv/inventories.json"
_TREASURY = "state/treasury/treasury-house-tang.json"
_PRIVATE_ECONOMY = "state/economy/private/qin.json"
_HOUSE = "state/houses/house_tang.json"
_SWORD_MANOR_FORCE = "state/forces/sword-manor.json"
_QIN_BORDER = "state/formations/qin-border-line.json"
_PLAYER = "state/player.json"
_RETINUE_GROUP = "state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json"
_RULES = "game/data/mechanics/warfare-organization.json"
_PRODUCTION = "game/data/mechanics/house-tang-production.json"
_GBG_PROGRAM = "game/data/mechanics/house-tang-programs.json"
_GBG_FORMATION_REF = "formation_tang_wei_great_bow_guard_first"
_LOCATION = "loc_tang_manor_training_ground"


def _scale_integer_rows(rows: list[Mapping[str, Any]], total: int, *, key: str) -> list[dict[str, Any]]:
    weights = [max(0, int(row.get(key, 0))) for row in rows]
    denominator = sum(weights)
    if denominator <= 0 or total < 0:
        raise ValueError("scale repair cannot proportion zero-weight rows")
    raw = [total * weight / denominator for weight in weights]
    values = [int(math.floor(value)) for value in raw]
    remainder = total - sum(values)
    order = sorted(range(len(rows)), key=lambda idx: (-(raw[idx] - values[idx]), idx))
    for idx in order[:remainder]:
        values[idx] += 1
    result: list[dict[str, Any]] = []
    for row, value in zip(rows, values):
        item = copy.deepcopy(dict(row))
        item[key] = value
        result.append(item)
    return result


def _inventory_facts(inventory: MutableMapping[str, Any], record_id: str) -> MutableMapping[str, Any]:
    for row in inventory.get("records", []):
        if isinstance(row, MutableMapping) and row.get("record_id") == record_id:
            facts = row.setdefault("facts", {})
            if isinstance(facts, MutableMapping):
                return facts
    raise ValueError(f"scale repair missing inventory record {record_id}")


def _target_record_map(production: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for field in ("items", "remounts"):
        rows = production.get(field, [])
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            reserve = str(row.get("reserve_key", ""))
            record = str(row.get("record_id", ""))
            total = str(row.get("total_key", ""))
            if reserve and record:
                result[reserve] = (record, total)
    return result


def _cohort_plan(force: MutableMapping[str, Any], at: str) -> tuple[list[str], list[dict[str, Any]]]:
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
    if len(parents) != 15 or sum(item[2] for item in parents) != 300:
        raise ValueError("GBG scale repair precondition changed: expected 15 current cohorts totaling 300")

    copies = {cid: 1 for cid, _row, _count in parents}
    for cid, _row, _count in sorted(parents, key=lambda item: (-item[2], item[0]))[:10]:
        copies[cid] += 1

    new_refs: list[str] = []
    composition: list[dict[str, Any]] = []
    original_ids = {cid for cid, _row, _count in parents}
    for cid in original_ids:
        cohorts.pop(cid, None)
    for cid, parent, old_count in parents:
        for index in range(copies[cid]):
            new_id = cid if index == 0 else f"{cid}_scale_{index + 1:02d}"
            if new_id in cohorts:
                raise ValueError("GBG scale repair cohort id collision")
            clone = copy.deepcopy(parent)
            clone["cohort_id"] = new_id
            clone["reserve_by_location"] = {}
            clone["allocated_by_formation"] = {_GBG_FORMATION_REF: 100}
            clone["command_candidate_slots"] = 1
            clone["command_candidate_status"] = "aggregate_unmaterialized"
            tags = clone.setdefault("tags", [])
            if "field_command_candidate_pool" not in tags:
                tags.append("field_command_candidate_pool")
            history = clone.setdefault("scale_repair_history", [])
            history.append({
                "at": at,
                "repair_id": _REPAIR_ID,
                "parent_cohort_ref": cid,
                "parent_personnel_before": old_count,
                "personnel_after": 100,
                "reason": "repartition under-scaled accepted Great Bow Guard into 100-fighter conserved command/recruitment cohorts",
            })
            clone["scale_repair_history"] = history[-8:]
            cohorts[new_id] = clone
            new_refs.append(new_id)
            composition.append({"cohort_id": new_id, "count": 100})
    if len(new_refs) != 25 or sum(item["count"] for item in composition) != 2500:
        raise ValueError("GBG scale repair failed to construct 25 x 100 cohorts")
    return new_refs, composition


def _apply_population_scale(population: MutableMapping[str, Any], service_rows: list[dict[str, Any]]) -> None:
    site = population.get("local_population", {}).get("sites", {}).get(_LOCATION)
    if not isinstance(site, MutableMapping):
        raise ValueError("GBG scale repair missing Tang Manor local population site")
    current_alloc = site.get("service_allocations", {}).get("force_tang_wei_personal")
    if not isinstance(current_alloc, MutableMapping) or int(current_alloc.get("personnel", 0)) != 300:
        raise ValueError("GBG scale repair local service allocation is not the expected 300")
    current_by_source = {
        str(row.get("source_stratum")): max(0, int(row.get("personnel", 0)))
        for row in service_rows
    }
    # service_rows are already final 2,500 rows. Historical campaign rows are
    # scaled from the current 300-person distribution, so derive old counts by
    # proportional reverse lookup from the exact site change target.
    old_total = 300
    final_total = sum(current_by_source.values())
    if final_total != 2500:
        raise ValueError("GBG scale repair service rows do not total 2500")
    strata = population.get("strata")
    local_civ = site.get("civilian_strata")
    if not isinstance(strata, MutableMapping) or not isinstance(local_civ, MutableMapping):
        raise ValueError("GBG scale repair population strata are invalid")

    # The current campaign's exact source distribution is reconstructed by
    # scaling final rows back to 300 with the same largest-remainder rule.
    reverse_rows = _scale_integer_rows(service_rows, old_total, key="personnel")
    old_by_source = {str(row.get("source_stratum")): int(row["personnel"]) for row in reverse_rows}
    moved = 0
    for row in service_rows:
        source = str(row.get("source_stratum", ""))
        final_count = int(row.get("personnel", 0))
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
    if moved != 2200:
        raise ValueError("GBG scale repair must transfer exactly 2200 additional civilians")
    strata["private_household_military"] = int(strata.get("private_household_military", 0)) + moved
    site["civilian_population"] = int(site.get("civilian_population", 0)) - moved
    site["private_household_military"] = int(site.get("private_household_military", 0)) + moved
    site["service_population"] = int(site.get("service_population", 0)) + moved
    if "agricultural_available" in site:
        site["agricultural_available"] = int(local_civ.get("agricultural", site.get("agricultural_available", 0)))
    current_alloc["personnel"] = 2500


def _adjust_recruitment_economics(campaign: MutableMapping[str, Any]) -> tuple[int, int]:
    additional_silver = 0
    additional_food = 0
    for row in campaign.get("economic_history", []):
        if not isinstance(row, MutableMapping):
            continue
        kind = str(row.get("kind", ""))
        old_silver = max(0, int(row.get("silver", 0)))
        old_food = max(0, int(row.get("food_kg", 0)))
        if kind == "candidate_contact":
            row["candidate_count"] = 10000
            row["silver"] = 1000
        elif kind == "regional_application_contact":
            row["candidate_count"] = 110000
            row["silver"] = 11000
        elif kind == "regional_candidate_screening":
            row["candidate_count"] = 120000
            row["silver"] = 12000
        elif kind == "screening":
            row["candidate_count"] = 10000
            row["silver"] = 1000
        elif kind == "candidate_training_support":
            row["candidate_count"] = 2500
            row["food_kg"] = int(math.ceil(2500 * 1.6 * 56 / 24.0 - 1e-9))
        additional_silver += max(0, int(row.get("silver", 0)) - old_silver)
        additional_food += max(0, int(row.get("food_kg", 0)) - old_food)
        # Regional application contact is intentionally cheaper after the
        # residential shortlist expands from 1,200 to 10,000. Offset that
        # historical overcharge against other newly represented screening work.
        additional_silver -= max(0, old_silver - int(row.get("silver", 0)))
        additional_food -= max(0, old_food - int(row.get("food_kg", 0)))
    if additional_silver != 880 or additional_food != 32856:
        raise ValueError("GBG scale repair historical cost delta changed")
    return additional_silver, additional_food


def apply_warfare_house_scale_repair(planner: Any, command: Any, reason: str) -> dict[str, Any]:
    at = str(command.submitted_at)
    force = copy.deepcopy(planner.read(_GBG_FORCE))
    formation = copy.deepcopy(planner.read(_GBG_FORMATION))
    registry = copy.deepcopy(planner.read(_CANDIDATES))
    population = copy.deepcopy(planner.read(_POPULATION))
    inventory = copy.deepcopy(planner.read(_INVENTORY))
    treasury = copy.deepcopy(planner.read(_TREASURY))
    economy = copy.deepcopy(planner.read(_PRIVATE_ECONOMY))
    house = copy.deepcopy(planner.read(_HOUSE))
    sword_force = copy.deepcopy(planner.read(_SWORD_MANOR_FORCE))
    qin_border = copy.deepcopy(planner.read(_QIN_BORDER))
    player = copy.deepcopy(planner.read(_PLAYER))
    retinue = copy.deepcopy(planner.read(_RETINUE_GROUP))
    warfare_rules = planner.read(_RULES)
    production_rules = planner.read(_PRODUCTION)
    gbg_rules = planner.read(_GBG_PROGRAM)

    if int(formation.get("personnel", 0)) != 300 or formation.get("composition") != {"great_bow_guard": 300}:
        raise ValueError("GBG scale repair precondition changed: formation is no longer the under-scaled 300")
    if float(formation.get("equipment_completeness", "0") or 0) != 0.0:
        raise ValueError("GBG scale repair requires the pre-issue formation")
    if int(force.get("allocated_to_formations", {}).get(_GBG_FORMATION_REF, {}).get("personnel", 0)) != 300:
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

    new_refs, composition = _cohort_plan(force, at)
    force["headcount"] = int(force.get("headcount", 300)) + 2200
    force["authorized_strength"] = max(2500, int(force.get("authorized_strength", 0)) + 2200)
    force.setdefault("allocated_to_formations", {})[_GBG_FORMATION_REF] = {"personnel": 2500, "role": "great_bow_guard"}
    force.setdefault("available_by_role", {})["great_bow_guard"] = 0
    force.setdefault("available_by_location", {}).setdefault(_LOCATION, {})["great_bow_guard"] = 0
    force.setdefault("scale_repair_history", []).append({"at": at, "repair_id": _REPAIR_ID, "from_personnel": 300, "to_personnel": 2500, "reason": reason})
    force["scale_repair_history"] = force["scale_repair_history"][-8:]
    validate_cohort_ledger(force)

    formation["personnel"] = 2500
    formation["composition"] = {"great_bow_guard": 2500}
    formation["cohort_composition"] = composition
    formation["command_structure"] = build_formation_command_structure(formation, warfare_rules)
    formation.setdefault("scale_repair_history", []).append({"at": at, "repair_id": _REPAIR_ID, "from_personnel": 300, "to_personnel": 2500, "cohorts": 25})
    formation["scale_repair_history"] = formation["scale_repair_history"][-8:]

    service_rows = _scale_integer_rows(
        [row for row in campaign.get("local_service_allocations", []) if isinstance(row, Mapping)],
        2500,
        key="personnel",
    )
    if len(service_rows) != 5:
        raise ValueError("GBG scale repair expected five conserved civilian source strata")
    _apply_population_scale(population, service_rows)

    slices = [row for row in campaign.get("slices", []) if isinstance(row, Mapping)]
    campaign["slices"] = _scale_integer_rows(slices, 2500, key="count")
    reservations = [row for row in campaign.get("local_reservations", []) if isinstance(row, Mapping)]
    scaled_reservations = _scale_integer_rows(reservations, 10000, key="personnel")
    campaign["local_reservations"] = scaled_reservations
    campaign["local_service_allocations"] = service_rows
    service_by_source = {str(row.get("source_stratum")): int(row["personnel"]) for row in service_rows}
    return_rows = []
    for row in scaled_reservations:
        source = str(row.get("source_stratum", ""))
        returned = int(row.get("personnel", 0)) - int(service_by_source.get(source, 0))
        if returned < 0:
            raise ValueError("GBG scale repair source service exceeds residential reservation")
        return_rows.append({"location_ref": _LOCATION, "personnel": returned, "source_stratum": source})
    returns = campaign.get("local_return_history", [])
    if isinstance(returns, list) and returns and isinstance(returns[-1], MutableMapping):
        returns[-1]["rows"] = return_rows
    campaign["initial_applicants"] = 10000
    campaign["regional_application_count"] = 120000
    campaign["regional_application_records_nonresident"] = 110000
    campaign["regional_shortlist_count"] = 10000
    campaign["remaining_candidates"] = 2500
    campaign["accepted_count"] = 2500
    campaign["cohort_refs"] = new_refs
    campaign.setdefault("scale_repair_history", []).append({
        "at": at,
        "repair_id": _REPAIR_ID,
        "from_residential_candidates": 1200,
        "to_residential_candidates": 10000,
        "from_accepted": 300,
        "to_accepted": 2500,
        "cohort_count": 25,
        "cohort_personnel": 100,
        "reason": reason,
    })
    campaign["scale_repair_history"] = campaign["scale_repair_history"][-8:]
    additional_silver, additional_food = _adjust_recruitment_economics(campaign)

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

    targets = production_rules.get("reserve_targets", {}) if isinstance(production_rules, Mapping) else {}
    target_map = _target_record_map(production_rules)
    scaled_stock: dict[str, int] = {}
    for reserve_key, raw_target in targets.items():
        target = max(0, int(raw_target))
        owner = target_map.get(str(reserve_key))
        if owner is None:
            raise ValueError(f"scale repair target has no inventory owner: {reserve_key}")
        record_id, total_key = owner
        facts = _inventory_facts(inventory, record_id)
        current_reserve = max(0, int(facts.get(reserve_key, 0)))
        assigned = max(0, int(facts.get(total_key, current_reserve)) - current_reserve) if total_key else 0
        facts[str(reserve_key)] = target
        if total_key:
            facts[total_key] = assigned + target
        scaled_stock[str(reserve_key)] = target

    gbg["accepted_cohort_refs"] = new_refs
    gbg["accepted_fighters"] = 2500
    gbg["fighting_establishment_max"] = 2500
    gbg["recruitment_spending_silver"] = 25000
    gbg["regional_applicants_screened"] = 120000
    gbg["regional_screening_rejected"] = 110000
    gbg["residential_trial_candidates"] = 10000
    gbg["screened_candidates"] = 10000
    gbg["shortlisted_candidates"] = 2500
    gbg["rejected_candidates"] = 117500
    gbg["command_candidate_slots"] = 25
    gbg["command_candidate_status"] = "aggregate_unmaterialized"
    gbg["field_officer_cadre_requested"] = 25
    gbg["field_officer_source_ref"] = "institution_sword_manor"
    gbg.setdefault("scale_repair_history", []).append({"at": at, "repair_id": _REPAIR_ID, "from_fighters": 300, "to_fighters": 2500, "reason": reason})
    gbg["scale_repair_history"] = gbg["scale_repair_history"][-8:]

    if isinstance(prep, MutableMapping):
        prep["great_bow_guard_personnel"] = 2500
        prep["production_rules_ref"] = _PRODUCTION
        prep["manufacturing_truth"] = (
            "House Tang has a registered resource-bounded armory and remount production owner backed by exact Tang Manor forge/armory and stable/remount workers; future output consumes private materials or horse stock plus House silver and refills only registered reserve shortages."
        )
        snapshot = prep.get("house_stock_snapshot")
        if isinstance(snapshot, MutableMapping):
            snapshot["tang_armor_reserve"] = int(targets.get("Tang Armor unissued reserve", 0))
            snapshot["tang_helmet_reserve"] = int(targets.get("Tang Helmet unissued reserve", 0))
            snapshot["tang_shield_reserve"] = int(targets.get("Tang Shield unissued reserve", 0))
            snapshot["great_war_bow_reserve"] = int(targets.get("Great War Bow armory reserve", 0))
            snapshot["tang_horse_armor_reserve"] = int(targets.get("Tang Horse Armor reserve", 0))
            snapshot["tang_tack_reserve"] = int(targets.get("Tang Tack reserve", 0))
            snapshot["tang_heavy_warhorse_reserve"] = int(targets.get("Tang Heavy Warhorse reserve", 0))
            snapshot["war_arrows_strategic_reserve"] = int(targets.get("War Arrows strategic reserve", 0))
            snapshot["food_kg"] = int(treasury.get("food_kg", 0))
            snapshot["silver"] = int(treasury.get("silver", 0))

    production_program = programs.setdefault("house_equipment_production", {})
    production_program["schema"] = "house-equipment-production-runtime.v1"
    production_program["status"] = "registered_resource_bounded_replenishment"
    production_program["forge_and_armory_workers"] = int(planner.read("state/population/tang-manor.json").get("strata", {}).get("forge_and_armory_workers", 0))
    production_program["stable_remount_and_carriage_workers"] = int(planner.read("state/population/tang-manor.json").get("strata", {}).get("stable_remount_and_carriage_workers", 0))
    production_program["reserve_targets"] = copy.deepcopy(dict(targets))
    production_program["registered_at"] = at
    production_program["last_close"] = None
    production_program["one_time_storage_scale_repair_at"] = at

    officer_auth = sword_force.setdefault("authorized_by_role", {})
    current_officer_auth = max(0, int(officer_auth.get("officer", 0)))
    if current_officer_auth not in {50, 250}:
        raise ValueError("Sword Manor officer authorization changed unexpectedly")
    if current_officer_auth == 50:
        officer_auth["officer"] = 250
        sword_force["authorized_strength"] = int(sword_force.get("authorized_strength", 0)) + 200
    officer_count = max(0, int(sword_force.get("available_by_role", {}).get("officer", 0)))
    if officer_count != 50:
        raise ValueError("Sword Manor officer pool changed unexpectedly")
    ledger = sword_force.get("cohort_ledger", {}).get("cohorts", {})
    officer_cohorts = [row for row in ledger.values() if isinstance(row, MutableMapping) and str(row.get("role", "")) == "officer"] if isinstance(ledger, MutableMapping) else []
    if sum(sum(int(v) for v in row.get("reserve_by_location", {}).values()) for row in officer_cohorts) != 50:
        raise ValueError("Sword Manor officer cohort pool is not the expected conserved 50")
    for row in officer_cohorts:
        count = sum(max(0, int(v)) for v in row.get("reserve_by_location", {}).values())
        row["command_candidate_slots"] = count
        row["command_candidate_status"] = "institutional_officer_pool_available_for_lawful_secondment"
    sword_force["officer_pipeline"] = {
        "authorized": 250,
        "current": 50,
        "current_unassigned_pool": 50,
        "great_bow_guard_requested_cadre": 25,
        "assignment_status": "not_yet_seconded",
        "materialization_rule": "named officers consume one conserved officer body only when individually relevant or formally appointed",
        "registered_at": at,
    }
    programs["sword_manor_officer_cadre"] = {
        "authorized_officer_target": 250,
        "current_officers": 50,
        "available_unassigned_officers": 50,
        "great_bow_guard_field_cadre_requested": 25,
        "status": "candidate_pool_available_not_seconded",
        "rule": "authorization creates vacancies only; promotions and secondments must conserve real Sword Manor personnel",
        "registered_at": at,
    }

    qin_border["command_structure"] = build_formation_command_structure(qin_border, warfare_rules)
    qin_border["command_structure"]["player_appointment_status"] = "awaiting_physical_assumption"
    qin_border["command_structure"]["named_subordinate_status"] = "materialize_only_when_individually_relevant_or_formally_appointed"

    career = player.get("career_state")
    if isinstance(career, MutableMapping):
        appointments = career.get("appointments", [])
        for appointment in appointments if isinstance(appointments, list) else []:
            if isinstance(appointment, MutableMapping) and appointment.get("formation_ref") == "formation_qin_border_line":
                appointment["command_structure_status"] = "aggregate_internal_echelons_registered"
                appointment["staffing_request_status"] = "aggregate_staff_registered_named_officers_unmaterialized"
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
        "summary": "Corrected the under-scaled warfare/House representation: Great Bow Guard 300->2500 as 25x100 conserved cohorts, reconciled 2200 additional civilian-to-private-service bodies and historical support costs, deepened registered House/Sword Manor reserve stock, raised Sword Manor officer authorization without minting officers, and registered internal command depth for Qin Border Line.",
        "affected_owners": [_GBG_FORCE, _GBG_FORMATION, _CANDIDATES, _POPULATION, _INVENTORY, _TREASURY, _PRIVATE_ECONOMY, _HOUSE, _SWORD_MANOR_FORCE, _QIN_BORDER, _PLAYER, _RETINUE_GROUP],
    })
    write_history_index(planner, history)

    planner.put(_GBG_FORCE, force)
    planner.put(_GBG_FORMATION, formation)
    planner.put(_CANDIDATES, registry)
    planner.put(_POPULATION, population)
    planner.put(_INVENTORY, inventory)
    planner.put(_TREASURY, treasury)
    planner.put(_PRIVATE_ECONOMY, economy)
    planner.put(_HOUSE, house)
    planner.put(_SWORD_MANOR_FORCE, sword_force)
    planner.put(_QIN_BORDER, qin_border)
    planner.put(_PLAYER, player)
    planner.put(_RETINUE_GROUP, retinue)

    return {
        "repair_event": event_id,
        "great_bow_guard_personnel": 2500,
        "great_bow_guard_cohorts": 25,
        "great_bow_guard_cohort_personnel": 100,
        "additional_conserved_personnel": 2200,
        "sword_manor_officers_current": 50,
        "sword_manor_officer_authorization": 250,
        "qin_border_line_personnel": 8000,
        "qin_border_line_internal_companies": int(qin_border["command_structure"].get("company_elements", 0)),
        "reserve_targets_scaled": scaled_stock,
        "historical_additional_silver": additional_silver,
        "historical_additional_food_kg": additional_food,
    }


__all__ = ["apply_warfare_house_scale_repair"]
