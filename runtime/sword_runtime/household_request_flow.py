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
_QIN_POPULATION_PATH = "state/population/qin.json"
_MANOR_POPULATION_PATH = "state/population/tang-manor.json"
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

    # A request to Tang Ling to investigate a delivered northern-operation report
    # is owned by House administration, not by the report itself. Bind the route
    # to the exact player-visible source so this cannot turn arbitrary family talk
    # into hidden intelligence or a second world-arc outcome authority.
    process_ref = attempt.get("process_ref")
    if attempt.get("target_ref") == "char_tang_ling" and isinstance(process_ref, str):
        source = get_causal_event_from_reader(planner, process_ref)
        investigation_terms = ("investigate", "verify", "look into", "find out", "learn more", "inquire")
        planning_terms = ("recruit", "recruitment", "cost", "costs", "expense", "expenses", "hiring")
        if (
            isinstance(source, Mapping)
            and source.get("kind") == "world_arc_report"
            and source.get("status") == "triggered"
            and source.get("arc_ref") == "arc_ryo_fui_northern_wei_campaign"
            and any(term in text for term in investigation_terms)
            and any(term in text for term in planning_terms)
        ):
            return _KIND_NORTHERN_WEI_REVIEW

    has_gbg = "great bow guard" in text
    has_sword = "sword manor" in text
    has_recruit = "recruit" in text or "intake" in text

    # Classify the most specific typed intent before generic start language.
    # A numbers question may legitimately contain the word "open", while the
    # start order may legitimately mention the treasury-safe ceiling. The typed
    # interaction action disambiguates those cases without parsing hidden intent.
    if action == "ask" and has_gbg and has_sword and any(
        phrase in text for phrase in ("treasury-safe ceiling", "treasury safe ceiling", "how soon", "earliest")
    ):
        return _KIND_NUMBERS
    if action == "ask" and has_gbg and has_sword and (
        "parallel" in text or "constraint" in text or "prevent" in text
    ):
        return _KIND_CONSTRAINTS
    if action == "request" and has_recruit and any(
        phrase in text for phrase in ("send me word", "report to me", "tell me when", "word immediately")
    ) and any(word in text for word in ("open", "opens", "begins", "starts")):
        return _KIND_REPORTING
    if has_gbg and has_sword and has_recruit and any(word in text for word in ("start", "begin", "open")):
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
    reserve = int(force.get("available_by_role", {}).get(role, 0)) if isinstance(force.get("available_by_role"), Mapping) else 0
    allocated = 0
    allocations = force.get("allocated_to_formations", {})
    if isinstance(allocations, Mapping):
        for value in allocations.values():
            if isinstance(value, Mapping) and str(value.get("role", "")) == role:
                allocated += max(0, int(value.get("personnel", 0)))
    return reserve + allocated


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
    sword = planner.read(_SWORD_FORCE_PATH)
    manor = planner.read(_MANOR_POPULATION_PATH)
    runtime = planner.read(_RUNTIME_PATH)
    rules = planner.read(_RULES_PATH)
    template = rules.get("sword_manor_initiates", {}) if isinstance(rules, Mapping) else {}
    role = str(template.get("role", "trainee"))
    authorized = int(sword.get("authorized_by_role", {}).get(role, 0)) if isinstance(sword.get("authorized_by_role"), Mapping) else 0
    current = _role_total(sword, role)
    sword_manor = manor.get("sword_manor", {}) if isinstance(manor.get("sword_manor"), Mapping) else {}
    housing = max(0, int(sword_manor.get("trainee_housing_capacity", authorized)))
    monthly = max(0, int(sword_manor.get("monthly_intake_capacity", 0)))
    vacancy = max(0, min(authorized, housing) - current)
    return {
        "role": role,
        "authorized": authorized,
        "current": current,
        "housing_capacity": housing,
        "monthly_intake_capacity": monthly,
        "current_vacancy": vacancy,
        "next_review_at": _next_sword_manor_review(runtime),
        "selection_profile": str(template.get("selection_profile", "sword_manor_screened_initiate")),
    }


def _perform_house_requested_sword_intake(planner: Any, at: str, request_id: str) -> dict[str, Any]:
    status = _sword_manor_status(planner)
    wanted = min(status["current_vacancy"], status["monthly_intake_capacity"])
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


def _open_great_bow_guard(planner: Any, *, at: str, request_id: str, house: dict[str, Any], treasury: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    template = rules.get("great_bow_guard", {}) if isinstance(rules.get("great_bow_guard"), Mapping) else {}
    safety = _treasury_safe_ceiling(treasury, rules)
    programs = house.setdefault("administrative_programs", {})
    existing = programs.get("great_bow_guard")
    if isinstance(existing, Mapping) and str(existing.get("status")) in {"recruiting", "screening", "training", "forming", "active"}:
        return {"status": str(existing.get("status")), "opened_at": existing.get("opened_at"), **safety}
    if safety["treasury_safe_ceiling_silver"] <= 0:
        return {"status": "blocked_by_treasury_reserve", **safety}
    programs["great_bow_guard"] = {
        "program_ref": str(template.get("program_ref", "program_house_tang_great_bow_guard")),
        "status": "recruiting",
        "recruitment_phase": str(template.get("recruitment_phase_on_open", "applicant_intake")),
        "opened_at": at,
        "opened_from_request_id": request_id,
        "fighting_establishment_max": int(template.get("fighting_establishment_max", 300)),
        "selection_profile": str(template.get("selection_profile", "wei_archery_trial")),
        "standards_rule": str(template.get("standards_rule", "standards are not lowered to fill places")),
        "separate_from_formation_ref": str(template.get("separate_from_formation_ref", "formation_tang_champions_first")),
        "treasury_safe_ceiling_silver": safety["treasury_safe_ceiling_silver"],
        "accepted_fighters": 0,
        "headcount_created_by_opening": 0,
        "spending_committed_by_opening_silver": 0,
        "template_ref": _RULES_PATH + "#great_bow_guard",
        "opening_rule": str(template.get("opening_rule", "opening intake creates no fighter headcount")),
    }
    return {"status": "recruiting", "opened_at": at, **safety}


def _settle_start(planner: Any, *, at: str, request_id: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rules = planner.read(_RULES_PATH)
    treasury = planner.read(_TREASURY_PATH)
    great = _open_great_bow_guard(planner, at=at, request_id=request_id, house=house, treasury=treasury, rules=rules)
    sword = _perform_house_requested_sword_intake(planner, at, request_id)
    house.setdefault("administrative_programs", {})["sword_manor_initiate_intake"] = {
        "status": sword["status"],
        "last_reviewed_at": at,
        "last_request_id": request_id,
        "current_trainees": sword["current"],
        "authorized_trainees": sword["authorized"],
        "current_vacancy": sword["current_vacancy"],
        "next_normal_review_at": sword.get("next_review_at"),
        "training_rule": "Existing Initiates continue through the normal Sword Manor training cycle; this request grants no free training time.",
    }
    if great["status"] == "recruiting":
        great_text = f"House Tang opens Great Bow Guard applicant intake under a treasury-safe ceiling of {great['treasury_safe_ceiling_silver']} silver. Opening the intake creates no fighter headcount and commits no spending; standards remain unchanged."
    else:
        great_text = "House Tang cannot open the Great Bow Guard intake without breaching its protected treasury reserve."
    if sword["intake_count"] > 0:
        sword_text = f"Sword Manor opens an immediate intake of {sword['intake_count']} Initiates into existing trainee vacancies; their training remains on the normal Sword Manor cycle."
    elif sword["status"] == "waiting_for_capacity":
        next_text = f" The next normal Sword Manor review is {sword['next_review_at']}." if sword.get("next_review_at") else ""
        sword_text = f"Sword Manor has no trainee vacancy at this review ({sword['current']} of {min(sword['authorized'], sword['housing_capacity'])} trainee places occupied), so no new Initiates can be added now.{next_text} Existing Initiates continue training."
    else:
        sword_text = "Sword Manor had an intake vacancy but no conserved eligible Qin population could be moved into it at this review; existing Initiates continue training."
    return great_text + " " + sword_text, {"great_bow_guard": great, "sword_manor": sword}


def _settle_numbers(planner: Any, *, at: str, house: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    rules = planner.read(_RULES_PATH)
    safety = _treasury_safe_ceiling(planner.read(_TREASURY_PATH), rules)
    sword = _sword_manor_status(planner)
    great = house.get("administrative_programs", {}).get("great_bow_guard", {}) if isinstance(house.get("administrative_programs"), Mapping) else {}
    great_status = str(great.get("status", "not_open")) if isinstance(great, Mapping) else "not_open"
    if great_status == "recruiting":
        great_timing = f"Great Bow Guard applicant intake is already open as of {great.get('opened_at')}"
    else:
        great_timing = "Great Bow Guard applicant intake is not open"
    if sword["current_vacancy"] > 0:
        sword_timing = f"Sword Manor currently has {sword['current_vacancy']} trainee vacancies and can admit up to {min(sword['current_vacancy'], sword['monthly_intake_capacity'])} on a House-requested review"
    else:
        sword_timing = f"Sword Manor currently has no trainee vacancy; its next normal review is {sword.get('next_review_at') or 'not presently scheduled'}"
    summary = (
        f"Tang Ling's House accounts put the current discretionary treasury-safe ceiling at {safety['treasury_safe_ceiling_silver']} silver after protecting {safety['protected_reserve_silver']} silver of stable expense reserve. "
        f"{great_timing}. {sword_timing}."
    )
    return summary, {"treasury": safety, "great_bow_guard_status": great_status, "sword_manor": sword, "reviewed_at": at}


def _settle_constraints(planner: Any, *, at: str, house: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    sword = _sword_manor_status(planner)
    programs = house.get("administrative_programs", {}) if isinstance(house.get("administrative_programs"), Mapping) else {}
    great = programs.get("great_bow_guard", {}) if isinstance(programs, Mapping) else {}
    great_status = str(great.get("status", "not_open")) if isinstance(great, Mapping) else "not_open"
    constraints: list[str] = []
    if great_status != "recruiting":
        constraints.append("Great Bow Guard applicant intake is not yet open")
    else:
        constraints.append("Great Bow Guard remains an applicant intake only; screening, accepted headcount, equipment and formation creation have not yet settled")
    if sword["current_vacancy"] <= 0:
        constraints.append("Sword Manor has no trainee vacancy")
    if sword["monthly_intake_capacity"] <= 0:
        constraints.append("Sword Manor has no registered intake throughput")
    summary = "Tang Zhu identifies the current practical constraints on parallel recruiting: " + "; ".join(constraints) + ". The two programs remain institutionally separate, so one does not consume the other's authorized fighting establishment."
    return summary, {"reviewed_at": at, "great_bow_guard_status": great_status, "sword_manor": sword, "constraints": constraints}


def _settle_northern_wei_review(planner: Any, *, at: str, house: Mapping[str, Any], request: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    process_ref = request.get("process_ref")
    if not isinstance(process_ref, str) or not process_ref:
        raise ValueError("House Tang northern Wei review lost its source report")
    source = get_causal_event_from_reader(planner, process_ref)
    if (
        not isinstance(source, Mapping)
        or source.get("kind") != "world_arc_report"
        or source.get("status") != "triggered"
        or source.get("arc_ref") != "arc_ryo_fui_northern_wei_campaign"
    ):
        raise ValueError("House Tang northern Wei review source is not the committed player-visible report")
    source_summary = source.get("summary")
    if not isinstance(source_summary, str) or not source_summary:
        raise ValueError("House Tang northern Wei review source report has no usable summary")

    rules = planner.read(_RULES_PATH)
    safety = _treasury_safe_ceiling(planner.read(_TREASURY_PATH), rules)
    sword = _sword_manor_status(planner)
    programs = house.get("administrative_programs", {}) if isinstance(house.get("administrative_programs"), Mapping) else {}
    great = programs.get("great_bow_guard", {}) if isinstance(programs, Mapping) else {}
    great_status = str(great.get("status", "not_open")) if isinstance(great, Mapping) else "not_open"
    accepted_fighters = int(great.get("accepted_fighters", 0)) if isinstance(great, Mapping) and isinstance(great.get("accepted_fighters", 0), int) else 0
    committed_spend = int(great.get("spending_committed_by_opening_silver", 0)) if isinstance(great, Mapping) and isinstance(great.get("spending_committed_by_opening_silver", 0), int) else 0
    if great_status == "recruiting":
        great_text = (
            "Great Bow Guard applicant intake is open. The current House program record establishes "
            f"{accepted_fighters} accepted fighters and {committed_spend} silver committed by the opening itself; "
            "it does not yet register separate applicant, screened, or rejected totals, so those figures cannot be claimed from the records."
        )
    else:
        great_text = f"Great Bow Guard applicant intake is currently {great_status.replace('_', ' ')}."
    if sword["current_vacancy"] > 0:
        sword_text = f"Sword Manor has {sword['current_vacancy']} trainee vacancies and can admit at most {min(sword['current_vacancy'], sword['monthly_intake_capacity'])} through a House-requested intake review."
    else:
        sword_text = f"Sword Manor has no current trainee vacancy; its next normal review is {sword.get('next_review_at') or 'not presently scheduled'}."
    summary = (
        "Tang Ling completes the House review requested from the delivered northern-operation report. "
        f"The military information available to this House review remains the report already received: {source_summary} "
        f"House accounts place the current discretionary treasury-safe ceiling at {safety['treasury_safe_ceiling_silver']} silver after protecting {safety['protected_reserve_silver']} silver of stable expense reserve. "
        f"{great_text} {sword_text} "
        "This review establishes planning information only; it creates no Qin appointment or deployment order and does not claim enemy dispositions beyond the delivered report."
    )
    return summary, {
        "reviewed_at": at,
        "source_process_ref": process_ref,
        "source_report_summary": source_summary[:4000],
        "treasury": safety,
        "great_bow_guard_status": great_status,
        "great_bow_guard_accounting": {
            "accepted_fighters": accepted_fighters,
            "spending_committed_by_opening_silver": committed_spend,
            "applicant_total": None,
            "screened_total": None,
            "rejected_total": None,
            "missing_totals_status": "not_registered_by_current_program_owner",
        },
        "sword_manor": sword,
        "knowledge_boundary": "No enemy disposition is established beyond the committed player-visible source report.",
    }


def _ensure_report_watch(planner: Any, *, at: str, house: dict[str, Any], player_ref: str) -> None:
    reporting = house.setdefault("recruitment_reporting", {})
    subscription = reporting.setdefault(player_ref, {})
    subscription.update({"active": True, "subscribed_at": at})

    # Baseline conditions that are disclosed in the same response that creates
    # the subscription. A watch reports transitions after subscription; it must
    # not later re-emit a condition the player was already explicitly told.
    programs = house.get("administrative_programs", {}) if isinstance(house.get("administrative_programs"), Mapping) else {}
    great = programs.get("great_bow_guard", {}) if isinstance(programs, Mapping) else {}
    if isinstance(great, Mapping) and great.get("status") == "recruiting":
        subscription.setdefault("reported_great_bow_guard_opened_at", str(great.get("opened_at", at)))

    runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = _watch_ids(player_ref)
    if host_id not in hosts:
        due = CampaignTime.parse(at).add_seconds(_REPORT_WATCH_SECONDS)
        hosts[host_id] = {
            "host_id": host_id,
            "kind": "household_recruitment_watch",
            "owner_ref": "house_tang",
            "player_ref": player_ref,
            "event_id": event_id,
            "recurrence_seconds": _REPORT_WATCH_SECONDS,
            "next_due": str(due),
            "resolved_through": at,
            "safe_through": str(due.add_seconds(-1)),
        }
        events.append({"event_id": event_id, "kind": "household_recruitment_watch", "priority": 78, "target_host": host_id, "due_at": str(due)})
        planner.put(_RUNTIME_PATH, runtime)


def _settle_reporting(planner: Any, *, at: str, house: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    _ensure_report_watch(planner, at=at, house=house, player_ref="char_tang_wei")
    programs = house.get("administrative_programs", {}) if isinstance(house.get("administrative_programs"), Mapping) else {}
    great = programs.get("great_bow_guard", {}) if isinstance(programs, Mapping) else {}
    sword = _sword_manor_status(planner)
    great_text = "Great Bow Guard applicant intake is already open." if isinstance(great, Mapping) and great.get("status") == "recruiting" else "Great Bow Guard applicant intake is not yet open."
    sword_text = "Sword Manor has current trainee capacity." if sword["current_vacancy"] > 0 else "Sword Manor has no current trainee vacancy."
    return f"House Tang records Tang Wei's instruction to send a concrete report when either recruitment intake opens. {great_text} {sword_text}", {"reporting_active": True, "great_bow_guard_status": great.get("status") if isinstance(great, Mapping) else None, "sword_manor": sword}


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
    player_ref = str(host.get("player_ref", "char_tang_wei"))
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    reporting = house.get("recruitment_reporting", {})
    subscription = reporting.get(player_ref) if isinstance(reporting, Mapping) else None
    if not isinstance(subscription, dict) or subscription.get("active") is not True:
        runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
        current = runtime.get("hosts", {}).get(host.get("host_id")) if isinstance(runtime.get("hosts"), dict) else None
        if isinstance(current, dict):
            current["recurrence_seconds"] = 0
            planner.put(_RUNTIME_PATH, runtime)
        return

    programs = house.get("administrative_programs", {}) if isinstance(house.get("administrative_programs"), Mapping) else {}
    great = programs.get("great_bow_guard", {}) if isinstance(programs, Mapping) else {}
    if isinstance(great, Mapping) and great.get("status") == "recruiting" and not subscription.get("reported_great_bow_guard_opened_at"):
        opened = str(great.get("opened_at", at))
        _emit_watch_report(planner, player_ref=player_ref, at=at, key="great_bow_guard_open", summary=f"House Tang reports that Great Bow Guard applicant intake is open under the recorded treasury-safe ceiling. The intake opened at {opened}; no fighter headcount is implied by the opening itself.")
        subscription["reported_great_bow_guard_opened_at"] = at

    manor = planner.read(_MANOR_POPULATION_PATH)
    recruitment_runtime = manor.get("recruitment_runtime", {}) if isinstance(manor.get("recruitment_runtime"), Mapping) else {}
    intake_at = recruitment_runtime.get("last_house_requested_intake_at")
    intake_count = int(recruitment_runtime.get("last_house_requested_intake", 0)) if isinstance(recruitment_runtime, Mapping) else 0
    normal_at = recruitment_runtime.get("last_review")
    normal_count = int(recruitment_runtime.get("last_sword_manor_intake", 0)) if isinstance(recruitment_runtime, Mapping) else 0
    candidate_at = intake_at if intake_count > 0 else normal_at if normal_count > 0 else None
    candidate_count = intake_count if intake_count > 0 else normal_count
    if isinstance(candidate_at, str) and candidate_count > 0 and CampaignTime.parse(candidate_at) >= CampaignTime.parse(str(subscription.get("subscribed_at", candidate_at))) and not subscription.get("reported_sword_manor_intake_at"):
        _emit_watch_report(planner, player_ref=player_ref, at=at, key="sword_manor_intake", summary=f"House Tang reports that Sword Manor admitted {candidate_count} Initiates at {candidate_at}. Their later development remains governed by the ordinary Sword Manor training cycle.")
        subscription["reported_sword_manor_intake_at"] = at

    if subscription.get("reported_great_bow_guard_opened_at") and subscription.get("reported_sword_manor_intake_at"):
        subscription["active"] = False
        runtime = copy.deepcopy(planner.read(_RUNTIME_PATH))
        current = runtime.get("hosts", {}).get(host.get("host_id")) if isinstance(runtime.get("hosts"), dict) else None
        if isinstance(current, dict):
            current["recurrence_seconds"] = 0
            planner.put(_RUNTIME_PATH, runtime)
    planner.put(_HOUSE_PATH, house)


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
