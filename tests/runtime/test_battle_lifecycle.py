from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from conftest import activate_operation, execute, execute_internal, meta
from sword_runtime.engine import RepositoryCommandPlanner, SwordRuntime
from sword_runtime.commands import CommandEnvelope
from sword_runtime.environment import daylight_window
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.store.json_fragments import assign_json_fragment, select_json_fragment, split_json_fragment


def _hosted_execute_internal(root: Path, command_type: str, payload: dict, *, request_id: str | None = None):
    from sword_runtime.production_runtime_planner import ProductionCampaignPlanner

    m = meta(root)
    request_id = request_id or f"hosted-{m['revision']}-{command_type}"
    runtime = SwordRuntime(root)
    runtime.planner = ProductionCampaignPlanner(root)
    command = CommandEnvelope(
        m["campaign_id"],
        request_id,
        RepositoryCommandPlanner.INTERNAL_ACTOR,
        command_type,
        m["revision"],
        m["time"],
        payload,
        mode="autonomous",
    )
    return runtime.execute(command)


def _co_locate(campaign: Path, refs: list[str], location_ref: str) -> None:
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    touched: list[str] = []
    for ref in refs:
        path = campaign / owners[ref]
        formation = json.loads(path.read_text())
        formation["location_ref"] = location_ref
        formation["mobilized"] = True
        formation["status"] = "ready"
        path.write_text(json.dumps(formation, ensure_ascii=False, indent=2) + "\n")
        touched.append(str(path.relative_to(campaign)))
        # Operational battle fixtures must preserve the real co-location rule for
        # the exact top commander instead of relying on state-only auto repair.
        for person_ref in (formation.get("commander_ref"),):
            if not isinstance(person_ref, str) or person_ref not in owners:
                continue
            person_route = owners[person_ref]
            person_rel, fragment = split_json_fragment(person_route)
            person_path = campaign / person_rel
            person_owner = json.loads(person_path.read_text())
            person = select_json_fragment(person_owner, fragment) if fragment else person_owner
            person = copy.deepcopy(person)
            # Mirror runtime location authority: exact people use the top-level
            # location/current_location string, not an auxiliary projection key.
            if "location" in person:
                person["location"] = location_ref
            else:
                person["current_location"] = location_ref
            person.pop("location_scope", None)
            if fragment:
                assign_json_fragment(person_owner, fragment, person)
            else:
                person_owner = person
            person_path.write_text(json.dumps(person_owner, ensure_ascii=False, indent=2) + "\n")
            touched.append(str(person_path.relative_to(campaign)))
    subprocess.run(["git", "-C", str(campaign), "add", *sorted(set(touched))], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test: battle lifecycle fixture"], check=True)


def test_daylight_contact_is_bounded_and_scales_casualty_exposure(campaign):
    planner = RepositoryCommandPlanner(campaign)
    start = CampaignTime.parse("244-BCE-09-10T08:00:00+08:00")
    battlefield = {
        "assignments": {
            "formation_test_attacker": {"order": "attack"},
        }
    }
    plan = planner._battle_lifecycle_contact_plan(
        battlefield,
        attacker_refs=["formation_test_attacker"],
        start=start,
        base_battle_hours=8.0,
    )
    assert plan["light_mode"] == "daylight"
    assert plan["duration_hours"] == pytest.approx(2.0)
    assert plan["casualty_reference_hours"] == pytest.approx(6.0)
    assert plan["casualty_duration_factor"] == pytest.approx(1.0 / 3.0)
    assert CampaignTime.parse(plan["planned_end_at"]) == start.add_seconds(2 * 3600)


def test_contact_stops_at_operational_boundary_so_reinforcements_can_intervene(campaign):
    planner = RepositoryCommandPlanner(campaign)
    start = CampaignTime.parse("244-BCE-09-10T08:00:00+08:00")
    boundary = start.add_seconds(45 * 60)
    planner._battlefield_next_boundary_time = lambda current, target: (
        boundary,
        {"kind": "redeployment_leg", "formation_ref": "formation_reinforcement"},
    )
    plan = planner._battle_lifecycle_contact_plan(
        {"assignments": {"formation_test_attacker": {"order": "attack"}}},
        attacker_refs=["formation_test_attacker"],
        start=start,
        base_battle_hours=8.0,
    )
    assert plan["duration_seconds"] == 45 * 60
    assert plan["truncated_by_boundary"] == "redeployment_leg"
    assert CampaignTime.parse(plan["planned_end_at"]) == boundary


def test_registered_military_scheduler_event_truncates_contact_before_external_intervention(campaign):
    from sword_runtime.production_runtime_planner import ProductionCampaignPlanner

    planner = ProductionCampaignPlanner(campaign)
    start = CampaignTime.parse("244-BCE-09-10T08:00:00+08:00")
    due = start.add_seconds(45 * 60)
    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    host_id = "host_test_battle_intervention"
    event_id = "evt_test_battle_intervention"
    runtime.setdefault("hosts", {})[host_id] = {
        "kind": "world_arc",
        "owner_ref": "world_arc_test_intervention",
        "resolved_through": str(start),
        "safe_through": str(due.add_seconds(-1)),
        "next_due": str(due),
        "recurrence_seconds": 0,
    }
    runtime.setdefault("events", []).append({
        "event_id": event_id,
        "kind": "world_arc_review",
        "priority": 50,
        "target_host": host_id,
        "due_at": str(due),
    })
    planner.put("state/runtime.json", runtime)

    plan = planner._battle_lifecycle_contact_plan(
        {"assignments": {"formation_test_attacker": {"order": "attack"}}},
        attacker_refs=["formation_test_attacker"],
        start=start,
        base_battle_hours=8.0,
    )
    assert plan["duration_seconds"] == 45 * 60
    assert plan["truncated_by_boundary"] == "scheduler:world_arc"
    assert plan["truncated_boundary_detail"]["event_id"] == event_id
    assert plan["truncated_boundary_detail"]["host_id"] == host_id


def test_new_night_contact_requires_saved_aggressive_orders(campaign):
    planner = RepositoryCommandPlanner(campaign)
    start = CampaignTime.parse("244-BCE-09-10T21:00:00+08:00")
    battlefield = {"assignments": {"formation_test_attacker": {"order": "hold"}}}
    with pytest.raises(ValueError, match="saved aggressive battlefield order"):
        planner._battle_lifecycle_contact_plan(
            battlefield,
            attacker_refs=["formation_test_attacker"],
            start=start,
            base_battle_hours=6.0,
        )
    battlefield["assignments"]["formation_test_attacker"]["order"] = "attack"
    plan = planner._battle_lifecycle_contact_plan(
        battlefield,
        attacker_refs=["formation_test_attacker"],
        start=start,
        base_battle_hours=6.0,
    )
    assert plan["light_mode"] == "night"
    assert plan["duration_hours"] == pytest.approx(1.0)


def test_too_little_daylight_rejects_a_new_organized_contact(campaign):
    planner = RepositoryCommandPlanner(campaign)
    day = CampaignTime.parse("244-BCE-09-10T12:00:00+08:00")
    _sunrise, sunset = daylight_window(day)
    start = sunset.add_seconds(-20 * 60)
    with pytest.raises(ValueError, match="too little daylight"):
        planner._battle_lifecycle_contact_plan(
            {"assignments": {"formation_test_attacker": {"order": "attack"}}},
            attacker_refs=["formation_test_attacker"],
            start=start,
            base_battle_hours=6.0,
        )


def test_dusk_enters_field_camp_and_dawn_refits_only_from_real_stock(campaign):
    planner = RepositoryCommandPlanner(campaign)
    ref = "formation_red_lance_a"
    path = planner.owner_path(ref)
    formation = copy.deepcopy(planner.read(path))
    formation["mounts"] = {"horse": 495}
    formation.setdefault("logistics", {})["remount_horses"] = 3
    formation["fatigue"] = 60
    planner.put(path, formation)

    day = CampaignTime.parse("244-BCE-09-10T12:00:00+08:00")
    sunrise, sunset = daylight_window(day)
    battlefield = {
        "side_refs": ["state_qin", "state_zhao"],
        "assignments": {
            ref: {
                "formation_ref": ref,
                "side_ref": "state_qin",
                "sector_ref": "battlefield_test.sector.left",
                "status": "holding",
                "order": "hold",
            }
        },
        "day_cycle": planner._battle_lifecycle_initial_cycle(sunset.add_seconds(-3600)),
    }
    dusk = planner._battle_lifecycle_transition(battlefield, at=sunset)
    assert dusk["kind"] == "dusk_camp"
    assert battlefield["day_cycle"]["posture"] == "night_camp"
    assert battlefield["day_cycle"]["camped_formation_refs"] == [ref]

    # A camp posture is not invisible night fighting. With a live body on each
    # represented side, pressure rates are recovery-only until explicit night contact.
    pressure_battlefield = copy.deepcopy(battlefield)
    pressure_battlefield["assignments"][ref]["sector_ref"] = "battlefield_test.sector.left"
    pressure_battlefield["sectors"] = {
        "battlefield_test.sector.left": {
            "id": "battlefield_test.sector.left",
            "formation_refs": [ref],
        }
    }
    rates = planner._battlefield_sector_rates(pressure_battlefield, pressure_battlefield["sectors"]["battlefield_test.sector.left"])
    assert rates["state_qin"] < 0
    assert rates["state_zhao"] == 0

    # A reinforcement that arrives after dusk did not spend the night in this camp
    # and must not receive a full dawn rest/refit retroactively.
    late_ref = "formation_red_lance_b"
    battlefield["assignments"][late_ref] = {
        "formation_ref": late_ref,
        "side_ref": "state_qin",
        "sector_ref": "battlefield_test.sector.left",
        "status": "holding",
        "order": "hold",
    }

    next_dawn = sunrise.add_seconds(24 * 3600)
    dawn = planner._battle_lifecycle_transition(battlefield, at=next_dawn)
    assert dawn["kind"] == "dawn_muster"
    assert dawn["camped_overnight_formation_refs"] == [ref]
    assert [row["formation_ref"] for row in dawn["formation_refits"]] == [ref]
    after = planner.read(path)
    assert after["mounts"]["horse"] == 498
    assert after["logistics"]["remount_horses"] == 0
    assert dawn["formation_refits"][0]["remount_horses_issued"] == 3
    assert battlefield["day_cycle"]["posture"] == "day_operations"


def test_explicit_night_contact_keeps_pressure_active_only_in_its_sector(campaign):
    planner = RepositoryCommandPlanner(campaign)
    qin = "formation_red_lance_a"
    zhao = "formation_zhao_border_line"
    sector_ref = "battlefield_night.sector.left"
    battlefield = {
        "side_refs": ["state_qin", "state_zhao"],
        "assignments": {
            qin: {"formation_ref": qin, "side_ref": "state_qin", "sector_ref": sector_ref, "status": "holding", "order": "attack"},
            zhao: {"formation_ref": zhao, "side_ref": "state_zhao", "sector_ref": sector_ref, "status": "holding", "order": "hold"},
        },
        "sectors": {sector_ref: {"id": sector_ref, "formation_refs": [qin, zhao]}},
        "day_cycle": {"posture": "night_camp"},
    }
    sector = battlefield["sectors"][sector_ref]
    resting = planner._battlefield_sector_rates(battlefield, sector)
    assert resting["state_qin"] < 0
    assert resting["state_zhao"] < 0

    battlefield["active_contact"] = {
        "contact_ref": "battle_test_night",
        "sector_ref": sector_ref,
        "started_at": "244-BCE-09-10T21:00:00+08:00",
        "ends_at": "244-BCE-09-10T22:00:00+08:00",
        "light_mode": "night",
    }
    fighting = planner._battlefield_sector_rates(battlefield, sector)
    assert fighting["state_qin"] > 0
    assert fighting["state_zhao"] > 0

    other_sector = {"id": "battlefield_night.sector.reserve", "formation_refs": []}
    other_rates = planner._battlefield_sector_rates(battlefield, other_sector)
    assert other_rates == {"state_qin": 0, "state_zhao": 0}


def test_live_operational_contact_ends_at_reinforcement_arrival_and_next_contact_can_use_it(campaign):
    attacker = "formation_red_lance_a"
    reinforcement = "formation_red_lance_b"
    defender = "formation_zhao_border_line"
    location = "loc_qin_eastern_depot"
    _co_locate(campaign, [attacker, reinforcement, defender], location)

    operation_ref = activate_operation(
        campaign,
        "operation_contact_period_reinforcement",
        [attacker, reinforcement, defender],
        location=location,
    )
    battlefield_ref = "battlefield_contact_period_reinforcement"
    execute(campaign, "battlefield_control", {
        "action": "open",
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "name": "Contact Period Reinforcement Test",
        "side_refs": ["state_qin", "state_zhao"],
        "layout_ref": "battlefield.layout.line_three",
    })
    left = battlefield_ref + ".sector.left"
    reserve = battlefield_ref + ".sector.reserve"
    execute(campaign, "battlefield_control", {
        "action": "assign",
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "formation_ref": attacker,
        "side_ref": "state_qin",
        "sector_ref": left,
        "order": "attack",
    })
    execute_internal(campaign, "battlefield_control", {
        "action": "assign",
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "formation_ref": defender,
        "side_ref": "state_zhao",
        "sector_ref": left,
        "order": "hold",
    })
    execute(campaign, "battlefield_control", {
        "action": "assign",
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "formation_ref": reinforcement,
        "side_ref": "state_qin",
        "sector_ref": reserve,
        "order": "reserve",
    })
    execute(campaign, "battlefield_control", {
        "action": "redeploy",
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "formation_ref": reinforcement,
        "target_sector_ref": left,
        "pace": "forced",
        "order": "attack",
    })

    operations = json.loads((campaign / "state/operations/index.json").read_text())["operations"]
    op_path = campaign / operations[operation_ref]
    before = json.loads(op_path.read_text())
    eta = before["battlefields"][battlefield_ref]["assignments"][reinforcement]["leg_eta_at"]

    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    attacker_before = json.loads((campaign / owners[attacker]).read_text())
    logistics_before = dict(attacker_before.get("logistics", {}))

    result = _hosted_execute_internal(campaign, "battle_resolve", {
        "attacker_formation_refs": [attacker],
        "defender_formation_refs": [defender],
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "sector_ref": left,
        "objective": "hold contact until reinforcement arrival",
    }).receipt.result

    assert result["winner_scope"] == "contact_period"
    assert result["operational_contact"] is True
    assert result["contact_plan"]["truncated_by_boundary"] == "redeployment_leg"
    assert result["world_time"] == eta
    assert result["contact_status"]["battle_continues"] is True

    attacker_after = json.loads((campaign / owners[attacker]).read_text())
    losses = result["material_losses"][attacker]
    # Battle contact uses one derived strategic-supply authority.  It does not
    # consume abstract food/fodder or write a second ration/subsistence result.
    assert losses["strategic_supply_condition"] in {"secure", "adequate", "strained", "poor", "critical", "isolated"}
    assert 0 <= int(losses["strategic_supply_score_milli"]) <= 1000
    assert "food_kg_consumed" not in losses
    assert "fodder_kg_consumed" not in losses
    assert attacker_after.get("logistics", {}).get("food_kg") == logistics_before.get("food_kg")
    assert attacker_after.get("logistics", {}).get("fodder_kg") == logistics_before.get("fodder_kg")

    after = json.loads(op_path.read_text())
    battlefield_after = after["battlefields"][battlefield_ref]
    assert "active_contact" not in battlefield_after
    assert battlefield_after["last_contact"]["contact_ref"] == result["battle_event"]
    assert battlefield_after["last_contact"]["sector_ref"] == left
    assignment = battlefield_after["assignments"][reinforcement]
    assert assignment["status"] == "holding"
    assert assignment["sector_ref"] == left
    assert reinforcement in after["battlefields"][battlefield_ref]["sectors"][left]["formation_refs"]

    # The new arrival is now physically eligible for a later contact period. We do
    # not resolve it here because this assertion is about causal admission/geometry.
    planner = RepositoryCommandPlanner(campaign)
    planner._battlefield_validate_contact(
        operation_ref=operation_ref,
        battlefield_ref=battlefield_ref,
        sector_ref=left,
        attacker_refs=[attacker, reinforcement],
        defender_refs=[defender],
    )


def test_mounted_battle_contact_uses_derived_supply_without_fodder_inventory(campaign):
    attacker = "formation_red_lance_a"
    defender = "formation_zhao_border_line"
    location = "loc_qin_eastern_depot"
    _co_locate(campaign, [attacker, defender], location)
    owners = json.loads((campaign / 'state/index/owner-index.json').read_text())['owners']
    attacker_path = campaign / owners[attacker]
    before = json.loads(attacker_path.read_text())
    assert sum(int(v or 0) for v in (before.get("mounts") or {}).values()) > 0
    before_food = before.get("logistics", {}).get("food_kg")
    before_fodder = before.get("logistics", {}).get("fodder_kg")

    operation_ref = activate_operation(campaign, "operation_derived_mounted_supply", [attacker, defender], location=location)
    result = _hosted_execute_internal(campaign, "battle_resolve", {
        "attacker_formation_refs": [attacker],
        "defender_formation_refs": [defender],
        "operation_ref": operation_ref,
        "objective": "derived strategic supply contact test",
    }).receipt.result

    supply = result["material_losses"][attacker]
    assert supply["strategic_supply_condition"] in {"secure", "adequate", "strained", "poor", "critical", "isolated"}
    assert 0 <= int(supply["strategic_supply_score_milli"]) <= 1000
    assert not any(key.startswith("food_kg_") or key.startswith("fodder_kg_") for key in supply)
    after = json.loads(attacker_path.read_text())
    assert after.get("logistics", {}).get("food_kg") == before_food
    assert after.get("logistics", {}).get("fodder_kg") == before_fodder

def test_side_wide_received_withdrawal_concludes_battle_not_campaign(campaign):
    qin = "formation_red_lance_b"
    wei = "formation_wei_disciplined_line"
    location = "loc_kankoku_pass"
    _co_locate(campaign, [qin, wei], location)
    operation_ref = activate_operation(campaign, "operation_battle_conclusion_withdrawal", [qin, wei], location=location)
    battlefield_ref = "battlefield_battle_conclusion_withdrawal"
    execute_internal(campaign, "battlefield_control", {
        "action": "open", "operation_ref": operation_ref, "battlefield_ref": battlefield_ref,
        "name": "Withdrawal Conclusion", "side_refs": ["state_qin", "state_wei"],
        "layout_ref": "battlefield.layout.line_three",
    })
    left = battlefield_ref + ".sector.left"
    execute_internal(campaign, "battlefield_control", {
        "action": "assign", "operation_ref": operation_ref, "battlefield_ref": battlefield_ref,
        "formation_ref": qin, "side_ref": "state_qin", "sector_ref": left, "order": "hold",
    })
    execute_internal(campaign, "battlefield_control", {
        "action": "assign", "operation_ref": operation_ref, "battlefield_ref": battlefield_ref,
        "formation_ref": wei, "side_ref": "state_wei", "sector_ref": left, "order": "hold",
    })
    execute_internal(campaign, "battlefield_control", {
        "action": "set_order", "operation_ref": operation_ref, "battlefield_ref": battlefield_ref,
        "formation_ref": wei, "order": "withdraw",
    })
    op_path = json.loads((campaign / "state/operations/index.json").read_text())["operations"][operation_ref]
    state = json.loads((campaign / op_path).read_text())
    eta = state["battlefields"][battlefield_ref]["assignments"][wei].get("order_eta_at")
    if eta:
        execute_internal(campaign, "advance_time", {"target_time": eta})
    else:
        now = json.loads((campaign / "state/runtime.json").read_text())["world_time"]
        execute_internal(campaign, "advance_time", {"target_time": str(CampaignTime.parse(now).add_seconds(1))})

    after = json.loads((campaign / op_path).read_text())
    bf = after["battlefields"][battlefield_ref]
    assert bf["status"] == "ended"
    assert bf["outcome"]["winner_side_ref"] == "state_qin"
    assert bf["outcome"]["loser_side_ref"] == "state_wei"
    assert bf["outcome"]["reason"] == "side_wide_withdrawal_order_received"
    assert after["status"] in {"active", "engaged"}
    assert after["campaign_phase"] == "post_battle_reorganization_under_superior_order"
    staff = after["last_battlefield_after_action"]
    assert staff["battlefield_ref"] == battlefield_ref
    assert staff["outcome"]["winner_side_ref"] == "state_qin"
    assert staff["side_summary"]["state_qin"]["personnel_remaining"] > 0
    follow_on = next(row for row in after["operational_orders"] if row.get("order_ref") == after["last_operational_order_ref"])
    assert follow_on["post_battle_directive"] == "secure_field_reorganize_and_maintain_contact"
    assert qin in follow_on["accompanying_non_state_formation_refs"]
    assert qin not in follow_on["applies_to_formation_refs"]
    assert bf["outcome"]["follow_on_order_ref"] == follow_on["order_ref"]
    conclusion_report = next(row for row in bf["reports"] if row.get("level") == "battle_concluded")
    delivery_at = conclusion_report["deliver_at"]
    execute_internal(campaign, "advance_time", {"target_time": delivery_at})
    delivered = json.loads((campaign / op_path).read_text())["battlefields"][battlefield_ref]["reports"]
    assert any(row.get("level") == "battle_concluded" and row.get("status") == "delivered" for row in delivered)
    history = json.loads((campaign / "state/history/events/index.json").read_text())["events"]
    assert any(row.get("kind") == "battlefield_conclusion" and row.get("operation_ref") == operation_ref for row in history)
