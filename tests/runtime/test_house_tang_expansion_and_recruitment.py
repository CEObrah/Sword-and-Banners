from __future__ import annotations

import copy

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import role_count
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
        if isinstance(host, dict) and host.get("owner_ref") == "institution_sword_manor"
    ]
    assert len(matches) == 1
    host_id, host = matches[0]
    assert host["kind"] == "sword_manor"
    assert host["recurrence_seconds"] == MONTH_SECONDS
    assert host["next_due"] == str(expected_due)
    event = next(row for row in runtime["events"] if row.get("target_host") == host_id)
    assert event["due_at"] == host["next_due"]


def test_monthly_intake_never_exceeds_authorized_trainee_capacity(campaign) -> None:
    planner = _planner(campaign)
    sword = copy.deepcopy(planner.read("state/forces/sword-manor.json"))
    manor = copy.deepcopy(planner.read("state/population/tang-manor.json"))
    sword.setdefault("authorized_by_role", {})["trainee"] = role_count(sword, "trainee")
    manor.setdefault("sword_manor", {})["trainee_housing_capacity"] = role_count(sword, "trainee") + 5000
    manor["sword_manor"]["monthly_intake_capacity"] = 5000
    planner.put("state/forces/sword-manor.json", sword)
    planner.put("state/population/tang-manor.json", manor)
    planner._fc_train = lambda *args, **kwargs: None
    planner._qualified_reserve = lambda *args, **kwargs: 0
    before = role_count(planner.read("state/forces/sword-manor.json"), "trainee")
    planner._autonomy_manor({"owner_ref": "institution_sword_manor"}, 1, str(planner._world_time().add_seconds(MONTH_SECONDS)))
    after = role_count(planner.read("state/forces/sword-manor.json"), "trainee")
    assert before == after
    assert after <= planner.read("state/forces/sword-manor.json")["authorized_by_role"]["trainee"]


def test_expansion_start_spends_once_raises_authorization_and_uses_spare_housing(campaign) -> None:
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
    assert sword["authorized_by_role"]["trainee"] == before_sword["authorized_by_role"]["trainee"] + 1000
    assert sword["authorized_strength"] == sum(int(v) for v in sword["authorized_by_role"].values())
    assert manor["sword_manor"]["trainee_housing_capacity"] == before_manor["sword_manor"]["trainee_housing_capacity"]
    assert 0 <= project["initial_intake_count"] <= before_manor["sword_manor"]["monthly_intake_capacity"]
    assert role_count(sword, "trainee") <= min(
        sword["authorized_by_role"]["trainee"],
        manor["sword_manor"]["trainee_housing_capacity"],
    )
    assert "sword_manor_trainee_program_expense_silver" not in treasury["monthly_flow_components"]["cash"]
    assert "trainee_population_requirement_kg" not in treasury["monthly_flow_components"]["food"]
    assert treasury["monthly_flow_components"]["cash"]["sword_manor_core_expense_silver"] == sword["headcount"] * 40
    assert treasury["monthly_flow_components"]["food"]["sword_manor_requirement_kg"] == sword["headcount"] * 48
    assert treasury["stable_monthly_flows"]["expense_silver"] == sum(
        int(v) for v in treasury["monthly_flow_components"]["cash"].values()
    )
    assert settled_house["development_requests"][request_id]["status"] == "settled"


def test_expansion_completion_adds_only_registered_physical_capacity(campaign) -> None:
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
    before_manor = copy.deepcopy(planner.read("state/population/tang-manor.json"))
    planner._settle_expansion_completion({"project_ref": project["project_ref"]}, project["completion_due_at"])
    sword = planner.read("state/forces/sword-manor.json")
    manor = planner.read("state/population/tang-manor.json")
    assert sword["authorized_by_role"]["trainee"] == before_sword["authorized_by_role"]["trainee"] + 1000
    assert sword["authorized_strength"] == sum(int(v) for v in sword["authorized_by_role"].values())
    assert manor["sword_manor"]["trainee_housing_capacity"] == before_manor["sword_manor"]["trainee_housing_capacity"] + 2000
    assert manor["sword_manor"]["monthly_intake_capacity"] == before_manor["sword_manor"]["monthly_intake_capacity"] + 250




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
