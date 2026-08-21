from __future__ import annotations

import copy

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import conserved_establishment_role_count, role_count
from sword_runtime.house_tang_development import (
    MONTH_SECONDS,
    _is_expansion_request,
)
from sword_runtime.infrastructure_projects import infrastructure_work_spec
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.sim.calendar import CampaignTime


def _planner(campaign):
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()
    return planner


def _fund_registered_expansion_materials(planner):
    rules = planner.read("game/data/mechanics/house-tang-development.json")["sword_manor_expansion"]
    required = 0
    for row in rules["capacity_projects"]:
        work = infrastructure_work_spec(
            planner.read,
            blueprint_ref=row["blueprint_ref"],
            target_site_ref=rules["target_site_ref"],
            quantity=row["quantity"],
        )
        required += int(work["construction_material_units"])
    ep, eco = planner._private_economy("qin")
    _ref, local = planner._local_economy_region("qin", eco, rules["economic_source_site_ref"])
    local.setdefault("commodity_stock", {})["construction_material_units"] = max(
        required, int(local.get("commodity_stock", {}).get("construction_material_units", 0))
    )
    planner._sync_local_economy_aggregate(eco)
    planner._write_private_economy(ep, eco)
    return required


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
    sword = planner.read("state/forces/sword-manor.json")
    last = CampaignTime.parse(str(sword["last_review"]))
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
    sword.setdefault("authorized_by_role", {})["trainee"] = current + 100_000
    physical = infrastructure["sites"]["loc_sword_manor"]
    bastions = sum(
        int(planner.read(path)["headcount"])
        for path in (
            "state/forces/bastion-iron-wall.json",
            "state/forces/bastion-red-thunder.json",
            "state/forces/bastion-white-blade.json",
            "state/forces/bastion-stone-spear.json",
        )
    )
    assigned = int(sword["headcount"]) + bastions
    physical["military_support"]["permanent_bed_capacity_people"] = assigned
    for key in ("instruction_capacity_people", "dining_capacity_people_per_day", "medical_support_capacity_people"):
        physical["institutional_support"][key] = max(assigned, int(physical["institutional_support"].get(key, 0)))
    physical["physical_support"]["water_capacity_people"] = max(assigned, int(physical["physical_support"].get("water_capacity_people", 0)))
    physical["training_support"]["simultaneous_trainee_capacity"] = max(assigned, int(physical["training_support"].get("simultaneous_trainee_capacity", 0)))
    planner.put("state/forces/sword-manor.json", sword)
    planner.put("state/infrastructure/settlements.json", infrastructure)
    planner._fc_train = lambda *args, **kwargs: None
    planner._qualified_reserve = lambda *args, **kwargs: 0
    before = role_count(planner.read("state/forces/sword-manor.json"), "trainee")
    planner._autonomy_manor({"owner_ref": "force_sword_manor"}, 1, str(planner._world_time().add_seconds(MONTH_SECONDS)))
    after_force = planner.read("state/forces/sword-manor.json")
    after = role_count(after_force, "trainee")
    assert before == after
    assert after_force["authorized_by_role"]["trainee"] == conserved_establishment_role_count(after_force, "trainee")

def test_expansion_start_spends_once_and_reserves_current_physical_work(campaign) -> None:
    planner = _planner(campaign)
    _fund_registered_expansion_materials(planner)
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
    _ep, before_eco = planner._private_economy("qin")
    _ref, before_local = planner._local_economy_region("qin", before_eco, "loc_tang_manor")
    before_material = int(before_local["commodity_stock"]["construction_material_units"])
    before_cash = int(before_local["cash_silver"])

    planner._settle_expansion_request({"request_id": request_id}, at)

    treasury = planner.read("state/treasury/treasury-house-tang.json")
    sword = planner.read("state/forces/sword-manor.json")
    settled_house = planner.read("state/houses/house_tang.json")
    project = settled_house["administrative_programs"]["sword_manor_expansion"]
    reserved = project["inputs_reserved"]
    assert project["status"] == "active"
    assert len(project["physical_work_specs"]) == 3
    assert len(project["land_reservations"]) == 3
    assert treasury["silver"] == before_treasury["silver"] - int(reserved["silver"])
    _ep, after_eco = planner._private_economy("qin")
    _ref, after_local = planner._local_economy_region("qin", after_eco, "loc_tang_manor")
    assert int(after_local["commodity_stock"]["construction_material_units"]) == before_material - int(reserved["construction_material_units"])
    assert int(after_local["cash_silver"]) == before_cash + int(reserved["silver"])
    assert project["project_ref"] in after_eco["labor_allocation"]["projects"]
    assert sword["authorized_strength"] == sum(int(v) for v in sword["authorized_by_role"].values()) == sword["headcount"]
    status = project["sword_manor"] if "sword_manor" in project else settled_house["development_requests"][request_id]["result"]["sword_manor"]
    assert 0 <= project["initial_intake_count"] <= status["physical_intake_throughput_30d"]
    assert sword["authorized_by_role"]["trainee"] == conserved_establishment_role_count(sword, "trainee")
    assert settled_house["development_requests"][request_id]["status"] == "settled"


def test_expansion_completion_adds_registered_physical_works_only(campaign) -> None:
    planner = _planner(campaign)
    _fund_registered_expansion_materials(planner)
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
    before_land = copy.deepcopy(planner.read("state/development/land.json"))
    planner._settle_expansion_completion({"project_ref": project["project_ref"]}, project["completion_due_at"])
    sword = planner.read("state/forces/sword-manor.json")
    infrastructure = planner.read("state/infrastructure/settlements.json")
    physical_before = before_infrastructure["sites"]["loc_sword_manor"]
    physical = infrastructure["sites"]["loc_sword_manor"]
    assert physical["military_support"]["permanent_bed_capacity_people"] == physical_before["military_support"]["permanent_bed_capacity_people"] + 2000
    assert physical["training_support"]["simultaneous_trainee_capacity"] == physical_before["training_support"]["simultaneous_trainee_capacity"] + 2000
    assert physical["training_support"]["prepared_training_ground_area_km2"] == physical_before["training_support"]["prepared_training_ground_area_km2"] + 0.24
    assert physical["institutional_support"]["medical_support_capacity_people"] == physical_before["institutional_support"]["medical_support_capacity_people"] + 2000
    completed = planner.read("state/houses/house_tang.json")["administrative_programs"]["sword_manor_expansion"]
    assert completed["status"] == "completed"
    assert len(completed["completed_work_refs"]) == 3
    assert "physical_work_specs" not in completed
    assert not planner._private_economy("qin")[1]["labor_allocation"]["projects"].get(project["project_ref"])
    land_after = planner.read("state/development/land.json")
    assert land_after["sites"]["loc_sword_manor"]["enclosed_land_use_km2"]["open_developable"] < before_land["sites"]["loc_sword_manor"]["enclosed_land_use_km2"]["open_developable"]
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
