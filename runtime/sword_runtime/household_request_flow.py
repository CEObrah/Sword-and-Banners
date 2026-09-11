"""Causal House Tang administrative responses to player-authored family requests.

Interaction attempts remain player-owned intent only. This layer discovers a small
registered set of House-administration requests from typed interaction history,
queues a real House review, and lets exact House/treasury/force owners settle the
response later in campaign time. It never treats dialogue itself as acceptance.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.api.interaction_surface import interaction_attempt_ref, recent_interaction_attempts
from sword_runtime.causal_event_store import get_causal_event_from_reader, read_causal_event_owner, write_causal_event_owner
from sword_runtime.campaign_communications import (
    command_message_route, command_person_location,
    ensure_player_message_delivery, player_command_location,
)
from sword_runtime.cohort_personnel import (
    conserved_establishment_role_count,
    add_recruits,
    consume_population_recruits,
    ensure_cohort_ledger,
    record_recruitment_cohort,
    validate_cohort_ledger,
)
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.mount_custody import regional_horses, reserve_regional_horses_for_role
from sword_runtime.tang_population import sync_tang_private_population

_RUNTIME_PATH = "state/runtime.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_HOUSE_FORCE_PATH = "state/forces/house-tang.json"
_INVENTORY_PATH = "state/inv/inventories.json"
_MOUNT_POOL_PATH = "state/mounts/house-tang.json"
_QIN_POPULATION_PATH = "state/population/qin.json"
_MANOR_POPULATION_PATH = "state/population/tang-manor.json"
_INFRASTRUCTURE_PATH = "state/infrastructure/settlements.json"
_PLAYER_PATH = "state/player.json"
_RULES_PATH = "game/data/mechanics/house-tang-programs.json"
_PROFILES_PATH = "game/data/mil/recruitment-cohort-profiles.json"
_TRAINING_GROUND = "loc_tang_manor_training_ground"
_PARENT_REFS = frozenset({"char_tang_ling", "char_tang_zhu"})
_REQUEST_REVIEW_SECONDS = 3600
_REPORT_WATCH_SECONDS = 12 * 3600
_HISTORY_WINDOW = 256

_KIND_START = "recruitment_start"
_KIND_NUMBERS = "recruitment_numbers"
_KIND_CONSTRAINTS = "recruitment_parallel_constraints"
_KIND_REPORTING = "recruitment_opening_report"
_KIND_NORTHERN_WEI_REVIEW = "northern_wei_recruitment_review"
_PRIORITY = {
    _KIND_START: 45,
    _KIND_NUMBERS: 50,
    _KIND_CONSTRAINTS: 51,
    _KIND_REPORTING: 52,
    _KIND_NORTHERN_WEI_REVIEW: 53,
}


def _request_ids(request_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(("house-request|" + request_ref).encode("utf-8")).hexdigest()[:20]
    return f"host_house_request_{digest}", f"event_house_request_{digest}"


def _watch_ids(player_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(("house-recruitment-watch|" + player_ref).encode("utf-8")).hexdigest()[:20]
    return f"host_house_recruitment_watch_{digest}", f"event_house_recruitment_watch_{digest}"


def _response_ref(request_ref: str) -> str:
    digest = hashlib.sha256(("house-response|" + request_ref).encode("utf-8")).hexdigest()[:20]
    return f"event_household_response_{digest}"


def _classify_request(planner: Any, attempt: Mapping[str, Any]) -> str | None:
    if attempt.get("actor_id") != "char_tang_wei" or attempt.get("target_ref") not in _PARENT_REFS:
        return None
    action = str(attempt.get("action", ""))
    if action not in {"ask", "request", "present", "comply"}:
        return None
    text = str(attempt.get("player_statement", "")).lower()
    if not text:
        return None
    process_ref = attempt.get("process_ref")
    if attempt.get("target_ref") == "char_tang_ling" and isinstance(process_ref, str):
        source = get_causal_event_from_reader(planner, process_ref)
        if (isinstance(source, Mapping) and source.get("kind") == "world_arc_report" and source.get("status") == "triggered"
            and source.get("arc_ref") == "arc_ryo_fui_northern_wei_campaign"
            and any(term in text for term in ("investigate", "verify", "look into", "find out", "learn more", "inquire"))
            and any(term in text for term in ("recruit", "recruitment", "cost", "costs", "expense", "expenses", "hiring"))):
            return _KIND_NORTHERN_WEI_REVIEW
    has_sword = "inner walls" in text
    has_recruit = "recruit" in text or "intake" in text
    if action == "ask" and has_sword and any(phrase in text for phrase in ("treasury-safe ceiling", "treasury safe ceiling", "how soon", "earliest", "how many", "numbers")):
        return _KIND_NUMBERS
    if action == "ask" and has_sword and ("parallel" in text or "constraint" in text or "prevent" in text):
        return _KIND_CONSTRAINTS
    if action == "request" and has_sword and has_recruit and any(phrase in text for phrase in ("send me word", "report to me", "tell me when", "word immediately")):
        return _KIND_REPORTING
    if has_sword and has_recruit and any(word in text for word in ("start", "begin", "open")):
        return _KIND_START
    return None



def _monthly_expense(treasury: Mapping[str, Any]) -> int:
    stable = treasury.get("stable_monthly_flows")
    if isinstance(stable, Mapping):
        value = stable.get("expense_silver")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    cash = treasury.get("monthly_flow_components", {}).get("cash", {}) if isinstance(treasury.get("monthly_flow_components"), Mapping) else {}
    if isinstance(cash, Mapping):
        return sum(max(0, int(value)) for value in cash.values() if isinstance(value, int) and not isinstance(value, bool))
    return 0


def _treasury_safe_ceiling(treasury: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, int]:
    policy = rules.get("treasury_safety", {}) if isinstance(rules.get("treasury_safety"), Mapping) else {}
    reserve_months = max(1, int(policy.get("reserve_months_of_stable_expense", 12)))
    fraction_bps = max(0, min(10000, int(policy.get("discretionary_program_fraction_basis_points", 1000))))
    silver = max(0, int(treasury.get("silver", 0)))
    expense = _monthly_expense(treasury)
    protected_reserve = reserve_months * expense
    post_reserve = max(0, silver - protected_reserve)
    ceiling = post_reserve * fraction_bps // 10000
    return {
        "cash_silver": silver,
        "stable_monthly_expense_silver": expense,
        "protected_reserve_silver": protected_reserve,
        "post_reserve_cash_silver": post_reserve,
        "treasury_safe_ceiling_silver": ceiling,
    }


def _role_total(force: Mapping[str, Any], role: str) -> int:
    return conserved_establishment_role_count(force, role)


def _next_house_tang_training_review(runtime: Mapping[str, Any]) -> str | None:
    hosts = runtime.get("hosts")
    if not isinstance(hosts, Mapping):
        return None
    due: list[CampaignTime] = []
    for host in hosts.values():
        if not isinstance(host, Mapping) or host.get("kind") != "house_tang_training":
            continue
        next_due = host.get("next_due")
        if isinstance(next_due, str):
            due.append(CampaignTime.parse(next_due))
    return str(min(due)) if due else None


def _house_outfitting_facts(inventory: dict[str, Any]) -> dict[str, Any]:
    for row in inventory.get("records", []):
        if isinstance(row, dict) and row.get("record_id") == "house_tang_outfitting_sets":
            facts = row.setdefault("facts", {})
            if not isinstance(facts, dict):
                raise ValueError("House Tang outfitting reserve is invalid")
            return facts
    raise ValueError("House Tang outfitting reserve is missing")


def _add_house_force_equipment(force: dict[str, Any], role: str, count: int, location_ref: str) -> None:
    n = max(0, int(count))
    if n <= 0:
        return
    aggregate = force.setdefault("available_equipment_units_by_role", {})
    local = force.setdefault("available_equipment_by_location", {}).setdefault(location_ref, {})
    aggregate[role] = max(0, int(aggregate.get(role, 0) or 0)) + n
    local[role] = max(0, int(local.get(role, 0) or 0)) + n


def _house_tang_force_status(planner: Any) -> dict[str, Any]:
    """Return the lawful replacement-intake envelope for unified House Tang troops.

    House Infantry and House Cavalry are the only active House Tang troop species.
    Exact commanders still occupy their conserved source-role establishment, so
    materialization never creates a recruitment vacancy. Fresh intake is bounded
    by real role vacancies, Inner Walls assessment/issue throughput, equipment,
    cavalry harnesses, and conserved remounts.
    """
    force = planner.read(_HOUSE_FORCE_PATH)
    runtime = planner.read(_RUNTIME_PATH)
    infrastructure = planner.read(_INFRASTRUCTURE_PATH)
    inventory = planner.read(_INVENTORY_PATH)
    mounts = planner.read(_MOUNT_POOL_PATH)
    authorized = force.get("authorized_by_role", {}) if isinstance(force.get("authorized_by_role"), Mapping) else {}
    counts = {
        "house_infantry": _role_total(force, "house_infantry"),
        "house_cavalry": _role_total(force, "house_cavalry"),
    }
    vacancies = {
        role: max(0, int(authorized.get(role, 0) or 0) - counts[role])
        for role in counts
    }
    sites = infrastructure.get("sites", {}) if isinstance(infrastructure, Mapping) else {}
    physical = sites.get("loc_tang_inner_walls", {}) if isinstance(sites, Mapping) else {}
    if not isinstance(physical, Mapping):
        raise ValueError("Inner Walls physical-capacity authority is missing")
    intake = physical.get("intake_support", {}) if isinstance(physical.get("intake_support"), Mapping) else {}
    assessment_per_day = max(0, int(intake.get("intake_assessment_candidates_per_day", 0) or 0))
    assessment_capacity = assessment_per_day * 30
    issue_capacity = max(0, int(intake.get("induction_equipment_issue_capacity_per_30d", 0) or 0))
    throughput = min(assessment_capacity, issue_capacity)
    mutable_inventory = copy.deepcopy(inventory)
    outfitting = _house_outfitting_facts(mutable_inventory)
    standard_sets = max(0, int(outfitting.get("standard_role_sets_reserve", 0) or 0))
    harness_sets = max(0, int(outfitting.get("mounted_harness_sets_reserve", 0) or 0))
    remounts = max(0, int(regional_horses(mounts, "loc_tang_manor_garrison_yard")))

    # Cavalry has the tighter physical chain, so reserve its bounded share first;
    # infantry then uses remaining common issue/assessment throughput.
    cavalry_capacity = min(vacancies["house_cavalry"], throughput, standard_sets, harness_sets, remounts)
    remaining_throughput = max(0, throughput - cavalry_capacity)
    remaining_standard = max(0, standard_sets - cavalry_capacity)
    infantry_capacity = min(vacancies["house_infantry"], remaining_throughput, remaining_standard)
    role_capacity = {"house_cavalry": cavalry_capacity, "house_infantry": infantry_capacity}
    return {
        "authorized_by_role": {k: int(authorized.get(k, 0) or 0) for k in counts},
        "current_by_role": counts,
        "vacancy_by_role": vacancies,
        "role_intake_capacity": role_capacity,
        "practical_intake_now": sum(role_capacity.values()),
        "intake_assessment_candidates_per_day": assessment_per_day,
        "physical_intake_throughput_30d": assessment_capacity,
        "induction_equipment_issue_capacity_per_30d": issue_capacity,
        "standard_role_sets_reserve": standard_sets,
        "mounted_harness_sets_reserve": harness_sets,
        "regional_remounts": remounts,
        "capacity_ref": "state/infrastructure/settlements.json#/sites/loc_tang_inner_walls",
        "next_review_at": _next_house_tang_training_review(runtime),
        "selection_profile": "household_retainer_screen",
    }


def _perform_house_requested_military_intake(planner: Any, at: str, request_ref: str) -> dict[str, Any]:
    status = _house_tang_force_status(planner)
    role_targets = {role: max(0, int(n)) for role, n in status["role_intake_capacity"].items() if int(n) > 0}
    wanted = sum(role_targets.values())
    if wanted <= 0:
        return {**status, "intake_count": 0, "status": "waiting_for_real_vacancy_or_capacity"}

    force = copy.deepcopy(planner.read(_HOUSE_FORCE_PATH))
    qin = copy.deepcopy(planner.read(_QIN_POPULATION_PATH))
    manor = copy.deepcopy(planner.read(_MANOR_POPULATION_PATH))
    profiles = planner.read(_PROFILES_PATH)
    inventory = copy.deepcopy(planner.read(_INVENTORY_PATH))
    mount_pool = copy.deepcopy(planner.read(_MOUNT_POOL_PATH))
    outfitting = _house_outfitting_facts(inventory)
    ensure_cohort_ledger(force, at=at)
    moved, source_mix = consume_population_recruits(
        qin,
        wanted,
        source_roles=("agricultural", "craft_and_industry", "household_and_service", "merchant_and_transport"),
        destination_role="private_household_military",
    )
    if moved != wanted:
        raise ValueError("House Tang replacement intake exceeded available Qin population")

    # Assign the exact accepted source mix to the pre-bounded role targets. Each
    # source/role pair becomes its own fresh cohort, preserving weaker intake
    # capability rather than averaging recruits into veteran standing cohorts.
    remaining_by_source = {str(k): int(v) for k, v in source_mix.items()}
    assigned_by_role = {role: 0 for role in role_targets}
    for role in ("house_cavalry", "house_infantry"):
        need = role_targets.get(role, 0)
        for source in list(remaining_by_source):
            if need <= 0:
                break
            available = remaining_by_source[source]
            take = min(need, available)
            if take <= 0:
                continue
            planner._consume_local_private_recruitment(
                qin,
                "qin",
                _TRAINING_GROUND,
                take,
                source_stratum=source,
                force_ref="force_house_tang",
                controller_ref="state_qin",
            )
            add_recruits(force, role, take, location_ref=_TRAINING_GROUND)
            record_recruitment_cohort(
                force,
                role=role,
                count=take,
                location_ref=_TRAINING_GROUND,
                source_population_ref="population_qin",
                source_stratum=source,
                recruited_at=at,
                profile_registry=profiles,
                selection_profile=status["selection_profile"],
                provenance_ref=f"house_request:{request_ref}:house_tang_intake:{role}:{source}",
                intake_ref=f"house_request:{request_ref}",
                validate=False,
            )
            remaining_by_source[source] -= take
            need -= take
            assigned_by_role[role] += take
        if need:
            raise ValueError(f"House Tang intake source mix could not fill bounded {role} target")

    standard_used = sum(assigned_by_role.values())
    cavalry_used = assigned_by_role.get("house_cavalry", 0)
    if standard_used > int(outfitting.get("standard_role_sets_reserve", 0) or 0):
        raise ValueError("House Tang replacement intake exceeded standard equipment reserve")
    if cavalry_used > int(outfitting.get("mounted_harness_sets_reserve", 0) or 0):
        raise ValueError("House Tang cavalry replacement intake exceeded harness reserve")
    outfitting["standard_role_sets_reserve"] = int(outfitting.get("standard_role_sets_reserve", 0) or 0) - standard_used
    outfitting["mounted_harness_sets_reserve"] = int(outfitting.get("mounted_harness_sets_reserve", 0) or 0) - cavalry_used
    for role, count in assigned_by_role.items():
        _add_house_force_equipment(force, role, count, _TRAINING_GROUND)
    if cavalry_used and reserve_regional_horses_for_role(
        mount_pool, location_ref="loc_tang_manor_garrison_yard", role="house_cavalry", count=cavalry_used
    ) != cavalry_used:
        raise ValueError("House Tang cavalry replacement intake lost exact remount custody")

    validate_cohort_ledger(force)
    recruitment_runtime = manor.setdefault("recruitment_runtime", {})
    recruitment_runtime["last_house_tang_military_intake"] = moved
    recruitment_runtime["last_house_tang_military_intake_at"] = at
    recruitment_runtime["last_house_tang_military_intake_ref"] = request_ref
    recruitment_runtime["last_house_tang_military_intake_by_role"] = assigned_by_role
    planner.put(_HOUSE_FORCE_PATH, force)
    planner.put(_INVENTORY_PATH, inventory)
    planner.put(_MOUNT_POOL_PATH, mount_pool)
    planner.put(_MANOR_POPULATION_PATH, manor)
    planner.put(_QIN_POPULATION_PATH, qin)
    sync_tang_private_population(planner, at=at, reason="house_tang_replacement_intake", evidence_ref=request_ref)
    after = _house_tang_force_status(planner)
    return {**after, "intake_count": moved, "status": "intake_opened", "source_mix": source_mix, "intake_by_role": assigned_by_role}


def _response_event(planner: Any, *, request_ref: str, at: str, summary: str) -> str:
    """Publish one schema-valid player-visible House response event.

    Detailed administrative result data stays in the exact House request owner.
    The causal event is the delivery surface only and therefore uses only fields
    already authorized by event-registry.schema.json.
    """
    event_ref = _response_ref(request_ref)
    _path, owner = read_causal_event_owner(planner)
    causal = owner["causal_events"]
    if event_ref not in causal:
        causal[event_ref] = {
            "event_ref": event_ref,
            "kind": "institutional_response",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": "house_tang",
            "target_ref": "char_tang_wei",
            "basis_goal": f"House Tang response to player request {request_ref}"[:500],
            "process_kind": "house_tang_household_administration",
            "process_stage": "completed",
            "summary": summary[:4000],
            "provenance": {
                "kind": "causal_runtime_settlement",
                "source_owner_ref": "house_tang",
                "work_ref": event_ref,
                "late_catch_up": False,
            },
        }
        owner.setdefault("runtime", {})["last_settled_at"] = at
        write_causal_event_owner(planner, owner)
    return event_ref




def _settle_start(planner: Any, *, at: str, request_ref: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    sword = _perform_house_requested_military_intake(planner, at, request_ref)
    house.setdefault("administrative_programs", {})["house_tang_military_replacement_intake"] = {
        "status": "active", "last_review_at": at, "last_intake": int(sword.get("intake_count", 0)),
        "rule": "House Tang replacement intake uses conserved Qin population, exact role vacancies, standard equipment, and the ordinary monthly training cycle."
    }
    if int(sword.get("intake_count", 0)) > 0:
        summary = f"House Tang admits {int(sword['intake_count'])} screened replacement soldiers into real Infantry/Cavalry vacancies. Their training remains on the normal House Tang professional cycle."
    else:
        summary = "House Tang opens its replacement-intake review, but no conserved eligible candidates can be admitted into current Infantry/Cavalry vacancies at this close."
    return summary, {"house_force": sword}



def _settle_numbers(planner: Any, *, at: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    safety = _treasury_safe_ceiling(planner.read(_TREASURY_PATH), planner.read(_RULES_PATH))
    sword = _house_tang_force_status(planner)
    summary = (f"House Tang's current treasury-safe discretionary ceiling is {safety['treasury_safe_ceiling_silver']} silver. "
               f"House Tang has {sum(int(v) for v in sword['vacancy_by_role'].values())} military replacement vacancies, physical 30-day intake throughput {sword['physical_intake_throughput_30d']}, "
               f"and next scheduled review {sword.get('next_review_at') or 'not currently scheduled'}.")
    return summary, {"treasury": safety, "house_force": sword, "reviewed_at": at}



def _settle_constraints(planner: Any, *, at: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    sword = _house_tang_force_status(planner)
    constraints=[]
    if sum(int(v) for v in sword['vacancy_by_role'].values()) <= 0: constraints.append("House Tang has no Infantry/Cavalry replacement vacancy")
    if sword['physical_intake_throughput_30d'] <= 0: constraints.append("Inner Walls has no functioning assessment/induction throughput")
    if not constraints: constraints.append("current conserved population and physical housing, instruction, assessment, equipment, medical, water, and training-space capacity permit an ordinary intake review")
    summary="Tang Zhu identifies the current practical House Tang replacement-intake constraints: " + "; ".join(constraints) + "."
    return summary, {"reviewed_at": at, "house_force": sword, "constraints": constraints}



def _settle_northern_wei_review(planner: Any, *, at: str, house: dict[str, Any], request: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    safety=_treasury_safe_ceiling(planner.read(_TREASURY_PATH), planner.read(_RULES_PATH))
    sword=_house_tang_force_status(planner)
    source_ref=str(request.get("process_ref", ""))
    source=get_causal_event_from_reader(planner, source_ref) if source_ref else None
    source_summary=str(source.get("summary", "")) if isinstance(source,Mapping) else ""
    summary=("Tang Ling reviews the delivered northern-operation report against House recruitment and logistics capacity. "
             f"House Tang currently has {sum(int(v) for v in sword['vacancy_by_role'].values())} military replacement vacancies and House discretionary capacity of {safety['treasury_safe_ceiling_silver']} silver. "
             "The review creates no recruits or intelligence beyond the delivered report; any hiring or intake remains a separate conserved process.")
    return summary,{"reviewed_at":at,"source_report_summary":source_summary[:4000],"treasury":safety,"house_force":sword}



def _ensure_report_watch(planner: Any, *, at: str, house: dict[str, Any], player_ref: str) -> None:
    reporting=house.setdefault("recruitment_reporting",{})
    subscription=reporting.setdefault(player_ref,{})
    subscription.update({"active":True,"subscribed_at":at,"watch":"house_tang_military_intake"})
    runtime=copy.deepcopy(planner.read(_RUNTIME_PATH)); hosts=runtime.setdefault("hosts",{}); events=runtime.setdefault("events",[])
    host_id,event_id=_watch_ids(player_ref)
    if host_id not in hosts:
        due=CampaignTime.parse(at).add_seconds(_REPORT_WATCH_SECONDS)
        hosts[host_id]={"host_id":host_id,"kind":"household_recruitment_watch","owner_ref":"house_tang","player_ref":player_ref,"recurrence_seconds":_REPORT_WATCH_SECONDS,"next_due":str(due),"resolved_through":at,"safe_through":str(due.add_seconds(-1))}
        events.append({"event_id":event_id,"kind":"household_recruitment_watch","priority":52,"target_host":host_id,"due_at":str(due)})
    planner.put(_RUNTIME_PATH,runtime)



def _settle_reporting(planner: Any, *, at: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    _ensure_report_watch(planner, at=at, house=house, player_ref="char_tang_wei")
    sword=_house_tang_force_status(planner)
    return ("House Tang records Tang Wei's instruction to send a concrete report when a replacement intake is admitted. "
            f"Current military replacement vacancy is {sum(int(v) for v in sword['vacancy_by_role'].values())} and physical 30-day intake throughput is {sword['physical_intake_throughput_30d']}.",
            {"reporting_active":True,"house_force":sword})



def _settle_household_request(planner: Any, host: Mapping[str, Any], at: str) -> None:
    if not ensure_player_message_delivery(planner, host, at):
        return
    request_ref = str(host.get("request_ref", ""))
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    requests = house.get("administrative_requests")
    request = requests.get(request_ref) if isinstance(requests, Mapping) else None
    if not isinstance(request, Mapping):
        raise ValueError("House Tang request host lost its exact administrative request")
    if request.get("status") == "settled":
        return
    kind = str(request.get("kind", ""))
    if kind == _KIND_START:
        summary, result = _settle_start(planner, at=at, request_ref=request_ref, house=house)
    elif kind == _KIND_NUMBERS:
        summary, result = _settle_numbers(planner, at=at, house=house)
    elif kind == _KIND_CONSTRAINTS:
        summary, result = _settle_constraints(planner, at=at, house=house)
    elif kind == _KIND_REPORTING:
        summary, result = _settle_reporting(planner, at=at, house=house)
    elif kind == _KIND_NORTHERN_WEI_REVIEW:
        summary, result = _settle_northern_wei_review(planner, at=at, house=house, request=request)
    else:
        raise ValueError("unsupported House Tang administrative request kind")
    event_ref = _response_event(planner, request_ref=request_ref, at=at, summary=summary)
    mutable_requests = house.setdefault("administrative_requests", {})
    mutable = dict(mutable_requests[request_ref])
    mutable.update({
        "status": "settled",
        "settled_at": at,
        "response_event_ref": event_ref,
        "response_summary": summary[:4000],
        "result": copy.deepcopy(dict(result)),
    })
    mutable_requests[request_ref] = mutable
    house["last_review"] = at
    planner.put(_HOUSE_PATH, house)


def _emit_watch_report(planner: Any, *, player_ref: str, at: str, summary: str, key: str) -> str:
    digest = hashlib.sha256(f"house-recruitment-report|{player_ref}|{key}|{at}".encode("utf-8")).hexdigest()[:20]
    event_ref = f"event_house_recruitment_report_{digest}"
    player = planner.read(_PLAYER_PATH)
    location_ref = player.get("location") if isinstance(player, Mapping) else None
    if not isinstance(location_ref, str) or not location_ref:
        raise ValueError("House recruitment report cannot resolve the player's delivery location")
    _path, owner = read_causal_event_owner(planner)
    if event_ref not in owner["causal_events"]:
        owner["causal_events"][event_ref] = {
            "event_ref": event_ref,
            "kind": "institutional_response",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": "house_tang",
            "target_ref": player_ref,
            "process_kind": "house_tang_recruitment_reporting",
            "process_stage": "delivered",
            "summary": summary[:4000],
            "delivery": {"target_ref": player_ref, "location_ref": location_ref, "route": "House Tang direct report"},
            "provenance": {
                "kind": "causal_runtime_settlement",
                "source_owner_ref": "house_tang",
                "work_ref": event_ref,
                "late_catch_up": False,
            },
        }
        owner.setdefault("runtime", {})["last_settled_at"] = at
        write_causal_event_owner(planner, owner)
    return event_ref


def _settle_recruitment_watch(planner: Any, host: Mapping[str, Any], at: str) -> None:
    player_ref=str(host.get("player_ref","char_tang_wei")); house=copy.deepcopy(planner.read(_HOUSE_PATH))
    reporting=house.get("recruitment_reporting",{}); subscription=reporting.get(player_ref) if isinstance(reporting,Mapping) else None
    if not isinstance(subscription,dict) or subscription.get("active") is not True: return
    manor=planner.read(_MANOR_POPULATION_PATH); rr=manor.get("recruitment_runtime",{}) if isinstance(manor,Mapping) else {}
    intake_at=rr.get("last_house_requested_intake_at") or rr.get("last_review"); count=max(int(rr.get("last_house_requested_intake",0) or 0),int(rr.get("last_house_tang_military_intake",0) or 0))
    if isinstance(intake_at,str) and count>0 and not subscription.get("reported_house_tang_military_intake_at"):
        _emit_watch_report(planner,player_ref=player_ref,at=at,key="house_tang_military_intake",summary=f"House Tang reports that House Tang admitted {count} replacement soldiers at {intake_at}.")
        subscription["reported_house_tang_military_intake_at"]=at; subscription["active"]=False; planner.put(_HOUSE_PATH,house)



class HouseholdRequestFlowMixin:
    """Production-only causal router for exact House Tang family administration."""

    def _sync_household_request_routes(self, runtime: dict[str, Any]) -> None:
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        house = copy.deepcopy(self.read(_HOUSE_PATH))
        requests = house.setdefault("administrative_requests", {})
        if not isinstance(requests, dict):
            raise ValueError("House Tang administrative request registry is invalid")
        current = CampaignTime.parse(str(runtime["world_time"]))
        changed = False
        attempts, _ = recent_interaction_attempts(self, "char_tang_wei", limit=_HISTORY_WINDOW)
        for attempt in attempts:
            kind = _classify_request(self, attempt)
            at = attempt.get("at")
            if kind is None or not isinstance(at, str):
                continue
            request_ref = interaction_attempt_ref(attempt)
            if request_ref not in requests:
                requests[request_ref] = {
                    "request_ref": request_ref,
                    "kind": kind,
                    "status": "queued",
                    "requested_at": at,
                    "source_event_id": attempt.get("event_id"),
                    "target_ref": attempt.get("target_ref"),
                    "process_ref": attempt.get("process_ref"),
                    "action": attempt.get("action"),
                    "player_statement": str(attempt.get("player_statement", ""))[:2000],
                }
                changed = True
            if requests[request_ref].get("status") == "settled":
                continue
            host_id, event_id = _request_ids(request_ref)
            if host_id in hosts:
                continue
            origin_location = attempt.get("origin_location_ref")
            if not isinstance(origin_location, str) or not origin_location:
                origin_location = player_command_location(self)
            recipient_location = command_person_location(self, attempt.get("target_ref"))
            if not origin_location or not recipient_location:
                raise ValueError("House Tang administrative request lacks physical family communication endpoints")
            route = command_message_route(self.read, origin_location, recipient_location, round_trip=True)
            travel_seconds = max(0, int(route.get("travel_seconds", 0) or 0))
            due = CampaignTime.parse(at).add_seconds(_REQUEST_REVIEW_SECONDS + travel_seconds)
            if due < current:
                due = current
            hosts[host_id] = {
                "host_id": host_id,
                "kind": "household_request",
                "owner_ref": "house_tang",
                "request_ref": request_ref,
                "event_id": event_id,
                "request_origin_location_ref": origin_location,
                "recipient_location_ref": recipient_location,
                "response_target_location_ref": origin_location,
                "communication_travel_seconds": travel_seconds,
                "house_processing_seconds": _REQUEST_REVIEW_SECONDS,
                "courier_route": copy.deepcopy(dict(route)),
                "communication_rule": "House administrative request and response require physical family-channel travel",
                "recurrence_seconds": 0,
                "next_due": str(due),
                "resolved_through": str(current if current < due else due.add_seconds(-1)),
                "safe_through": str(due.add_seconds(-1)),
            }
            events.append({"event_id": event_id, "kind": "household_request", "priority": _PRIORITY[kind], "target_host": host_id, "due_at": str(due)})
        if changed:
            self.put(_HOUSE_PATH, house)

    # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = ["HouseholdRequestFlowMixin"]
