from __future__ import annotations

import copy

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import conserved_establishment_role_count, role_count
from sword_runtime.house_tang_development import (
    MONTH_SECONDS,
    _is_expansion_request,
)
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def test_exact_expansion_intent_is_classified() -> None:
    attempt = {
        "actor_id": "char_tang_wei",
        "action": "request",
        "target_ref": "char_tang_ling",
        "player_statement": (
            "Mother, Father: begin expanding Sword Manor's infrastructure and authorized intake "
            "so we can recruit more Initiates. Keep Sword Manor and our House troops on their "
            "sustainable training and promotion cycle as capacity opens. Do not lower standards."
        ),
    }
    assert _is_expansion_request(attempt)
    assert not _is_expansion_request({**attempt, "player_statement": "Recruit more Initiates."})


def test_sword_manor_scheduler_is_migrated_to_monthly_development(campaign) -> None:
    planner = _planner(campaign)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    now = CampaignTime.parse(str(runtime["world_time"]))
    progression = planner.read("state/prog/sword-manor-progression.json")
    last = CampaignTime.parse(str(progression["runtime"]["last_settled_at"]))
    lawful_next = last.add_seconds(MONTH_SECONDS)
    expected_due = now if lawful_next <= now else lawful_next
    planner._normalize_sword_manor_host(runtime)
    matches = [
        (host_id, host)
        for host_id, host in runtime["hosts"].items()
        if isinstance(host, dict) and host.get("owner_ref") == "force_sword_manor"
    ]
    assert len(matches) == 1
    host_id, host = matches[0]
    assert host["kind"] == "sword_manor"
    assert host["recurrence_seconds"] == MONTH_SECONDS
    assert host["next_due"] == str(expected_due)
    event = next(row for row in runtime["events"] if row.get("target_host") == host_id)
    assert event["due_at"] == host["next_due"]


def test_sword_manor_intake_is_blocked_by_physical_capacity_not_authorized_snapshot(campaign) -> None:
    planner = _planner(campaign)
    sword = copy.deepcopy(planner.read("state/forces/sword-manor.json"))
    infrastructure = copy.deepcopy(planner.read("state/infrastructure/settlements.json"))
    current = role_count(sword, "trainee")
    # Deliberately make the accounting snapshot enormous.  It must not create a
    # vacancy if the actual dormitory/support system is already full.
    sword.setdefault("authorized_by_role", {})["trainee"] = current + 100_000
    physical = infrastructure["sites"]["loc_tang_manor"]["sword_manor"]
    higher = sum(role_count(sword, role) for role in ("junior_disciple", "general_disciple", "senior_disciple"))
    physical["trainee_dormitory_beds"] = current
    physical["total_residential_beds"] = current + higher
    physical["instruction_capacity_people"] = current + higher
    physical["dining_capacity_people_per_day"] = current + higher
    physical["water_capacity_people_per_day"] = current + higher
    physical["medical_support_capacity_people"] = current + higher
    physical["training_space_capacity_people"] = current + higher
    planner.put("state/forces/sword-manor.json", sword)
    planner.put("state/infrastructure/settlements.json", infrastructure)
    planner._fc_train = lambda *args, **kwargs: None
    planner._qualified_reserve = lambda *args, **kwargs: 0
    before = role_count(planner.read("state/forces/sword-manor.json"), "trainee")
    planner._autonomy_manor({"owner_ref": "force_sword_manor"}, 1, str(planner._world_time().add_seconds(MONTH_SECONDS)))
    after_force = planner.read("state/forces/sword-manor.json")
    after = role_count(after_force, "trainee")
    assert before == after
    # The legacy field is resynchronized to the conserved current establishment;
    # it is not retained as a ceiling.
    assert after_force["authorized_by_role"]["trainee"] == conserved_establishment_role_count(after_force, "trainee")

def test_expansion_start_spends_once_and_uses_existing_physical_vacancy(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    request_id = "test-sword-manor-expansion"
    house = copy.deepcopy(planner.read("state/houses/house_tang.json"))
    house.setdefault("development_requests", {})[request_id] = {
        "request_id": request_id,
        "kind": "sword_manor_infrastructure_expansion",
        "status": "queued",
        "requested_at": at,
        "target_ref": "char_tang_ling",
        "player_statement": "Expand Sword Manor infrastructure, recruit Initiates, train and promote our troops.",
    }
    planner.put("state/houses/house_tang.json", house)
    before_treasury = copy.deepcopy(planner.read("state/treasury/treasury-house-tang.json"))
    before_sword = copy.deepcopy(planner.read("state/forces/sword-manor.json"))
    before_manor = copy.deepcopy(planner.read("state/population/tang-manor.json"))

    planner._settle_expansion_request({"request_id": request_id}, at)

    treasury = planner.read("state/treasury/treasury-house-tang.json")
    sword = planner.read("state/forces/sword-manor.json")
    manor = planner.read("state/population/tang-manor.json")
    settled_house = planner.read("state/houses/house_tang.json")
    project = settled_house["administrative_programs"]["sword_manor_expansion"]
    assert treasury["silver"] == before_treasury["silver"] - 1_800_000
    assert sword["authorized_strength"] == sum(int(v) for v in sword["authorized_by_role"].values()) == sword["headcount"]
    infrastructure = planner.read("state/infrastructure/settlements.json")
    physical = infrastructure["sites"]["loc_tang_manor"]["sword_manor"]
    assert 0 <= project["initial_intake_count"] <= physical["intake_assessment_candidates_per_day"] * 30
    assert sword["authorized_by_role"]["trainee"] == conserved_establishment_role_count(sword, "trainee")
    assert role_count(sword, "trainee") <= physical["trainee_dormitory_beds"]
    assert manor.get("sword_manor", {}).get("trainee_housing_capacity") == before_manor.get("sword_manor", {}).get("trainee_housing_capacity")
    assert "sword_manor_trainee_program_expense_silver" not in treasury["monthly_flow_components"]["cash"]
    assert "trainee_population_requirement_kg" not in treasury["monthly_flow_components"]["food"]
    assert treasury["monthly_flow_components"]["cash"]["sword_manor_core_expense_silver"] == sword["headcount"] * 40
    assert treasury["monthly_flow_components"]["food"]["sword_manor_requirement_kg"] == sword["headcount"] * 48
    assert treasury["stable_monthly_flows"]["expense_silver"] == sum(
        int(v) for v in treasury["monthly_flow_components"]["cash"].values()
    )
    assert settled_house["development_requests"][request_id]["status"] == "settled"


def test_expansion_completion_adds_registered_physical_works_only(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    request_id = "test-sword-manor-expansion-complete"
    house = copy.deepcopy(planner.read("state/houses/house_tang.json"))
    house.setdefault("development_requests", {})[request_id] = {
        "request_id": request_id,
        "kind": "sword_manor_infrastructure_expansion",
        "status": "queued",
        "requested_at": at,
        "target_ref": "char_tang_ling",
        "player_statement": "Expand Sword Manor infrastructure, recruit Initiates, train and promote our troops.",
    }
    planner.put("state/houses/house_tang.json", house)
    planner._settle_expansion_request({"request_id": request_id}, at)
    project = planner.read("state/houses/house_tang.json")["administrative_programs"]["sword_manor_expansion"]
    before_sword = copy.deepcopy(planner.read("state/forces/sword-manor.json"))
    before_infrastructure = copy.deepcopy(planner.read("state/infrastructure/settlements.json"))
    planner._settle_expansion_completion({"project_ref": project["project_ref"]}, project["completion_due_at"])
    sword = planner.read("state/forces/sword-manor.json")
    infrastructure = planner.read("state/infrastructure/settlements.json")
    before_physical = before_infrastructure["sites"]["loc_tang_manor"]["sword_manor"]
    physical = infrastructure["sites"]["loc_tang_manor"]["sword_manor"]
    for key, value in project["completion_capacity_add"].items():
        assert physical[key] == before_physical[key] + value
    assert sword["authorized_strength"] == sum(int(v) for v in sword["authorized_by_role"].values()) == sword["headcount"]
    assert sword["authorized_by_role"]["trainee"] == before_sword["authorized_by_role"]["trainee"]




def test_material_world_arc_report_adds_bounded_evidence_detail(campaign) -> None:
    planner = _planner(campaign)
    at = str(planner._world_time())
    source_ref = "event_test_material_world_arc"
    report_ref = source_ref + ".report"
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][source_ref] = {
        "event_ref": source_ref,
        "kind": "world_arc_activity",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "actor_ref": "state_qin",
        "target_ref": "state_wei",
        "result": "material_action_settled",
        "summary": "material work settled",
        "provenance": {
            "kind": "world_arc_orchestration",
            "material_evidence": {
                "kind": "exact_operation_created",
                "operation_ref": "operation_test",
                "formation_ref": "formation_secret_ref",
                "formation_status_before": "formed",
                "formation_status_after": "formed",
            },
        },
    }
    owner["causal_events"][report_ref] = {
        "event_ref": report_ref,
        "kind": "world_arc_report",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "source_event_ref": source_ref,
        "summary": "Reports reaching Tang Wei concern northern Wei. Material work settled.",
        "provenance": {"kind": "world_arc_information_propagation"},
    }
    write_causal_event_owner(planner, owner)
    planner._enrich_world_arc_report(source_ref)
    _path, after = read_causal_event_owner(planner)
    summary = after["causal_events"][report_ref]["summary"]
    assert "Qin has opened an actual military operation directed at Wei" in summary
    assert "assigned an existing formation" in summary
    assert "formation_secret_ref" not in summary
    assert "do not establish the formation's size, exact route, supply state, combat contact, or result" in summary
