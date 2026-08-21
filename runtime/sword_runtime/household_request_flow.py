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

from sword_runtime.api.interaction_surface import parse_interaction_attempt_summary
from sword_runtime.causal_event_store import get_causal_event_from_reader, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import (
    conserved_establishment_role_count,
    add_recruits,
    consume_population_recruits,
    ensure_cohort_ledger,
    record_recruitment_cohort,
    validate_cohort_ledger,
)
from sword_runtime.history_store import recent_history_events
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_SWORD_FORCE_PATH = "state/forces/sword-manor.json"
_BASTION_FORCE_PATHS = (
    "state/forces/bastion-iron-wall.json",
    "state/forces/bastion-red-thunder.json",
    "state/forces/bastion-white-blade.json",
    "state/forces/bastion-stone-spear.json",
)
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


def _request_ids(request_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(("house-request|" + request_id).encode("utf-8")).hexdigest()[:20]
    return f"host_house_request_{digest}", f"event_house_request_{digest}"


def _watch_ids(player_ref: str) -> tuple[str, str]:
    digest = hashlib.sha256(("house-recruitment-watch|" + player_ref).encode("utf-8")).hexdigest()[:20]
    return f"host_house_recruitment_watch_{digest}", f"event_house_recruitment_watch_{digest}"


def _response_ref(request_id: str) -> str:
    digest = hashlib.sha256(("house-response|" + request_id).encode("utf-8")).hexdigest()[:20]
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
    has_sword = "sword manor" in text
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


def _next_sword_manor_review(runtime: Mapping[str, Any]) -> str | None:
    hosts = runtime.get("hosts")
    if not isinstance(hosts, Mapping):
        return None
    due: list[CampaignTime] = []
    for host in hosts.values():
        if not isinstance(host, Mapping) or host.get("kind") != "sword_manor":
            continue
        next_due = host.get("next_due")
        if isinstance(next_due, str):
            due.append(CampaignTime.parse(next_due))
    return str(min(due)) if due else None


def _sword_manor_status(planner: Any) -> dict[str, Any]:
    """Return the current physical intake envelope for Sword Manor.

    ``authorized_by_role`` is an establishment/accounting snapshot, not a legal
    personnel ceiling.  Admissions are bounded by conserved applicants and by
    the smallest relevant constructed support system.
    """
    sword = planner.read(_SWORD_FORCE_PATH)
    runtime = planner.read(_RUNTIME_PATH)
    rules = planner.read(_RULES_PATH)
    infrastructure = planner.read(_INFRASTRUCTURE_PATH)
    template = rules.get("sword_manor_initiates", {}) if isinstance(rules, Mapping) else {}
    role = str(template.get("role", "trainee"))
    current = _role_total(sword, role)
    higher_rank_count = sum(
        _role_total(sword, r)
        for r in ("junior_disciple", "general_disciple", "senior_disciple")
    )
    sites = infrastructure.get("sites", {}) if isinstance(infrastructure, Mapping) else {}
    physical = sites.get("loc_sword_manor", {}) if isinstance(sites, Mapping) else {}
    if not isinstance(physical, Mapping):
        raise ValueError("Sword Manor physical-capacity authority is missing")
    military = physical.get("military_support", {}) if isinstance(physical.get("military_support"), Mapping) else {}
    training = physical.get("training_support", {}) if isinstance(physical.get("training_support"), Mapping) else {}
    resident_support = physical.get("physical_support", {}) if isinstance(physical.get("physical_support"), Mapping) else {}
    institution = physical.get("institutional_support", {}) if isinstance(physical.get("institutional_support"), Mapping) else {}
    intake = physical.get("intake_support", {}) if isinstance(physical.get("intake_support"), Mapping) else {}

    # Sword Manor is now a real nested physical site rather than a pseudo-capacity
    # dictionary hanging off Tang Manor. Empty beds/training space remain capacity
    # only and never create personnel.
    total_beds = max(0, int(military.get("permanent_bed_capacity_people", 0)))
    bastion_residents = sum(max(0, int(planner.read(path).get("headcount", 0))) for path in _BASTION_FORCE_PATHS)
    sword_residents = max(0, int(sword.get("headcount", 0)))
    assigned_resident_military = bastion_residents + sword_residents
    # The 350k Sword Manor bed pool belongs to every formation permanently based
    # there, not only Initiates. Empty beds are capacity only.  A new Initiate can
    # occupy only a bed/support slot not already assigned to a Bastion or a higher
    # Sword Manor rank.
    other_residents = max(0, assigned_resident_military - current)
    support_capacity = min(
        max(0, int(institution.get("instruction_capacity_people", 0))),
        max(0, int(institution.get("dining_capacity_people_per_day", 0))),
        max(0, int(resident_support.get("water_capacity_people", 0))),
        max(0, int(institution.get("medical_support_capacity_people", 0))),
        max(0, int(training.get("simultaneous_trainee_capacity", 0))),
        total_beds,
    )
    trainee_capacity = max(0, support_capacity - other_residents)
    trainee_beds = max(0, total_beds - other_residents)
    assessment_per_day = max(0, int(intake.get("intake_assessment_candidates_per_day", 0)))
    physical_intake_throughput_30d = assessment_per_day * 30
    equipment_issue_capacity = max(0, int(intake.get("induction_equipment_issue_capacity_per_30d", 0)))
    vacancy = max(0, trainee_capacity - current)
    practical_intake = min(vacancy, physical_intake_throughput_30d, equipment_issue_capacity)
    return {
        "role": role,
        "current": current,
        "higher_rank_count": higher_rank_count,
        "bastion_resident_count": bastion_residents,
        "assigned_resident_military": assigned_resident_military,
        "physical_trainee_capacity": trainee_capacity,
        "trainee_dormitory_beds": trainee_beds,
        "institution_support_capacity": support_capacity,
        "intake_assessment_candidates_per_day": assessment_per_day,
        "physical_intake_throughput_30d": physical_intake_throughput_30d,
        "induction_equipment_issue_capacity_per_30d": equipment_issue_capacity,
        "current_vacancy": vacancy,
        "practical_intake_now": practical_intake,
        "capacity_ref": "state/infrastructure/settlements.json#/sites/loc_sword_manor",
        "next_review_at": _next_sword_manor_review(runtime),
        "selection_profile": str(template.get("selection_profile", "sword_manor_screened_initiate")),
    }


def _perform_house_requested_sword_intake(planner: Any, at: str, request_id: str) -> dict[str, Any]:
    status = _sword_manor_status(planner)
    wanted = int(status["practical_intake_now"])
    if wanted <= 0:
        return {**status, "intake_count": 0, "status": "waiting_for_capacity"}

    sword = copy.deepcopy(planner.read(_SWORD_FORCE_PATH))
    qin = copy.deepcopy(planner.read(_QIN_POPULATION_PATH))
    manor = copy.deepcopy(planner.read(_MANOR_POPULATION_PATH))
    profiles = planner.read(_PROFILES_PATH)
    ensure_cohort_ledger(sword, at=at)
    moved, source_mix = consume_population_recruits(
        qin,
        wanted,
        source_roles=("agricultural", "craft_and_industry", "household_and_service", "merchant_and_transport"),
        destination_role="private_household_military",
    )
    for source, count in source_mix.items():
        add_recruits(sword, status["role"], count, location_ref=_TRAINING_GROUND)
        record_recruitment_cohort(
            sword,
            role=status["role"],
            count=count,
            location_ref=_TRAINING_GROUND,
            source_population_ref="population_qin",
            source_stratum=source,
            recruited_at=at,
            profile_registry=profiles,
            selection_profile=status["selection_profile"],
            provenance_ref=f"house_request:{request_id}:sword_manor_intake:{source}",
            intake_ref=f"house_request:{request_id}",
        )
    validate_cohort_ledger(sword)
    recruitment_runtime = manor.setdefault("recruitment_runtime", {})
    recruitment_runtime["last_house_requested_intake"] = moved
    recruitment_runtime["last_house_requested_intake_at"] = at
    recruitment_runtime["last_house_requested_intake_ref"] = request_id
    manor.setdefault("sword_manor", {})["provisional_trainees"] = _role_total(sword, status["role"])
    planner.put(_SWORD_FORCE_PATH, sword)
    planner.put(_QIN_POPULATION_PATH, qin)
    planner.put(_MANOR_POPULATION_PATH, manor)
    after = _sword_manor_status(planner)
    return {**after, "intake_count": moved, "status": "intake_opened" if moved else "population_blocked", "source_mix": source_mix}


def _response_event(planner: Any, *, request_id: str, at: str, summary: str) -> str:
    """Publish one schema-valid player-visible House response event.

    Detailed administrative result data stays in the exact House request owner.
    The causal event is the delivery surface only and therefore uses only fields
    already authorized by event-registry.schema.json.
    """
    event_ref = _response_ref(request_id)
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
            "basis_goal": f"House Tang response to player request {request_id}"[:500],
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




def _settle_start(planner: Any, *, at: str, request_id: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    sword = _perform_house_requested_sword_intake(planner, at, request_id)
    house.setdefault("administrative_programs", {})["sword_manor_initiate_intake"] = {
        "status": "active", "last_review_at": at, "last_intake": int(sword.get("intake_count", 0)),
        "rule": "Sword Manor intake uses conserved eligible population and the ordinary monthly development cycle."
    }
    if int(sword.get("intake_count", 0)) > 0:
        summary = f"Sword Manor admits {int(sword['intake_count'])} screened Initiates into existing vacancies. Their training remains on the normal Sword Manor cycle."
    else:
        summary = "Sword Manor opens its intake review, but no conserved eligible candidates can be admitted into current vacancies at this close."
    return summary, {"sword_manor": sword}



def _settle_numbers(planner: Any, *, at: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    safety = _treasury_safe_ceiling(planner.read(_TREASURY_PATH), planner.read(_RULES_PATH))
    sword = _sword_manor_status(planner)
    summary = (f"House Tang's current treasury-safe discretionary ceiling is {safety['treasury_safe_ceiling_silver']} silver. "
               f"Sword Manor has {sword['current_vacancy']} trainee vacancies, physical 30-day intake throughput {sword['physical_intake_throughput_30d']}, "
               f"and next scheduled review {sword.get('next_review_at') or 'not currently scheduled'}.")
    return summary, {"treasury": safety, "sword_manor": sword, "reviewed_at": at}



def _settle_constraints(planner: Any, *, at: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    sword = _sword_manor_status(planner)
    constraints=[]
    if sword['current_vacancy'] <= 0: constraints.append("Sword Manor has no trainee vacancy")
    if sword['physical_intake_throughput_30d'] <= 0: constraints.append("Sword Manor has no functioning assessment/induction throughput")
    if not constraints: constraints.append("current conserved population and physical housing, instruction, assessment, equipment, medical, water, and training-space capacity permit an ordinary intake review")
    summary="Tang Zhu identifies the current practical Sword Manor intake constraints: " + "; ".join(constraints) + "."
    return summary, {"reviewed_at": at, "sword_manor": sword, "constraints": constraints}



def _settle_northern_wei_review(planner: Any, *, at: str, house: dict[str, Any], request: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    safety=_treasury_safe_ceiling(planner.read(_TREASURY_PATH), planner.read(_RULES_PATH))
    sword=_sword_manor_status(planner)
    source_ref=str(request.get("process_ref", ""))
    source=get_causal_event_from_reader(planner, source_ref) if source_ref else None
    source_summary=str(source.get("summary", "")) if isinstance(source,Mapping) else ""
    summary=("Tang Ling reviews the delivered northern-operation report against House recruitment and logistics capacity. "
             f"Sword Manor currently has {sword['current_vacancy']} trainee vacancies and House discretionary capacity of {safety['treasury_safe_ceiling_silver']} silver. "
             "The review creates no recruits or intelligence beyond the delivered report; any hiring or intake remains a separate conserved process.")
    return summary,{"reviewed_at":at,"source_report_summary":source_summary[:4000],"treasury":safety,"sword_manor":sword}



def _ensure_report_watch(planner: Any, *, at: str, house: dict[str, Any], player_ref: str) -> None:
    reporting=house.setdefault("recruitment_reporting",{})
    subscription=reporting.setdefault(player_ref,{})
    subscription.update({"active":True,"subscribed_at":at,"watch":"sword_manor_intake"})
    runtime=copy.deepcopy(planner.read(_RUNTIME_PATH)); hosts=runtime.setdefault("hosts",{}); events=runtime.setdefault("events",[])
    host_id,event_id=_watch_ids(player_ref)
    if host_id not in hosts:
        due=CampaignTime.parse(at).add_seconds(_REPORT_WATCH_SECONDS)
        hosts[host_id]={"host_id":host_id,"kind":"household_recruitment_watch","owner_ref":"house_tang","player_ref":player_ref,"recurrence_seconds":_REPORT_WATCH_SECONDS,"next_due":str(due),"resolved_through":at,"safe_through":str(due.add_seconds(-1))}
        events.append({"event_id":event_id,"kind":"household_recruitment_watch","priority":52,"target_host":host_id,"due_at":str(due)})
    planner.put(_RUNTIME_PATH,runtime)



def _settle_reporting(planner: Any, *, at: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    _ensure_report_watch(planner, at=at, house=house, player_ref="char_tang_wei")
    sword=_sword_manor_status(planner)
    return ("House Tang records Tang Wei's instruction to send a concrete report when Sword Manor admits a new intake. "
            f"Current trainee vacancy is {sword['current_vacancy']} and physical 30-day intake throughput is {sword['physical_intake_throughput_30d']}.",
            {"reporting_active":True,"sword_manor":sword})



def _settle_household_request(planner: Any, host: Mapping[str, Any], at: str) -> None:
    request_id = str(host.get("request_id", ""))
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    requests = house.get("administrative_requests")
    request = requests.get(request_id) if isinstance(requests, Mapping) else None
    if not isinstance(request, Mapping):
        raise ValueError("House Tang request host lost its exact administrative request")
    if request.get("status") == "settled":
        return
    kind = str(request.get("kind", ""))
    if kind == _KIND_START:
        summary, result = _settle_start(planner, at=at, request_id=request_id, house=house)
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
    event_ref = _response_event(planner, request_id=request_id, at=at, summary=summary)
    mutable_requests = house.setdefault("administrative_requests", {})
    mutable = dict(mutable_requests[request_id])
    mutable.update({
        "status": "settled",
        "settled_at": at,
        "response_event_ref": event_ref,
        "response_summary": summary[:4000],
        "result": copy.deepcopy(dict(result)),
    })
    mutable_requests[request_id] = mutable
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
    intake_at=rr.get("last_house_requested_intake_at") or rr.get("last_review"); count=max(int(rr.get("last_house_requested_intake",0) or 0),int(rr.get("last_sword_manor_intake",0) or 0))
    if isinstance(intake_at,str) and count>0 and not subscription.get("reported_sword_manor_intake_at"):
        _emit_watch_report(planner,player_ref=player_ref,at=at,key="sword_manor_intake",summary=f"House Tang reports that Sword Manor admitted {count} Initiates at {intake_at}.")
        subscription["reported_sword_manor_intake_at"]=at; subscription["active"]=False; planner.put(_HOUSE_PATH,house)



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
        for event in recent_history_events(self, _HISTORY_WINDOW):
            if not isinstance(event, Mapping):
                continue
            attempt = parse_interaction_attempt_summary(event.get("summary"))
            if not isinstance(attempt, Mapping):
                continue
            kind = _classify_request(self, attempt)
            request_id = attempt.get("request_id")
            at = event.get("at")
            if kind is None or not isinstance(request_id, str) or not request_id or not isinstance(at, str):
                continue
            if request_id not in requests:
                requests[request_id] = {
                    "request_id": request_id,
                    "kind": kind,
                    "status": "queued",
                    "requested_at": at,
                    "source_event_id": event.get("event_id"),
                    "target_ref": attempt.get("target_ref"),
                    "process_ref": attempt.get("process_ref"),
                    "action": attempt.get("action"),
                    "player_statement": str(attempt.get("player_statement", ""))[:2000],
                }
                changed = True
            if requests[request_id].get("status") == "settled":
                continue
            host_id, event_id = _request_ids(request_id)
            if host_id in hosts:
                continue
            due = CampaignTime.parse(at).add_seconds(_REQUEST_REVIEW_SECONDS)
            if due < current:
                due = current
            hosts[host_id] = {
                "host_id": host_id,
                "kind": "household_request",
                "owner_ref": "house_tang",
                "request_id": request_id,
                "event_id": event_id,
                "recurrence_seconds": 0,
                "next_due": str(due),
                "resolved_through": str(current if current < due else due.add_seconds(-1)),
                "safe_through": str(due.add_seconds(-1)),
            }
            events.append({"event_id": event_id, "kind": "household_request", "priority": _PRIORITY[kind], "target_host": host_id, "due_at": str(due)})
        if changed:
            self.put(_HOUSE_PATH, house)

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        if getattr(self, "_central_scheduler_reconciliation_active", False):
            return super()._advance_runtime(target_text)
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        self._sync_household_request_routes(runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        kind = host.get("kind")
        if kind == "household_request":
            _settle_household_request(self, host, due_text)
            self._pending_wake_created = None
            return
        if kind == "household_recruitment_watch":
            _settle_recruitment_watch(self, host, due_text)
            self._pending_wake_created = None
            return
        super()._run_due_host(host, due_text)


__all__ = ["HouseholdRequestFlowMixin"]
