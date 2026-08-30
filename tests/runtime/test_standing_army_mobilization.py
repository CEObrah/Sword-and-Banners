from __future__ import annotations

import copy

from sword_runtime.support_tasks import FORBIDDEN_PERMANENT_SUPPORT_ROLES


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    return ProductionCampaignPlanner(campaign)


def _reserve_total(force):
    return sum(max(0, int(v)) for v in force.get("available_by_role", {}).values())




def _raise_mobilization_targets(campaign, *, general=60000, great_general=90000):
    path = campaign / "game/data/mechanics/military-career.json"
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    row = data.setdefault("standing_army_mobilization", {})
    targets = row.setdefault("target_recursive_strength_by_rank", {})
    targets["general"] = max(int(targets.get("general", 0) or 0), int(general))
    targets["great_general"] = max(int(targets.get("great_general", 0) or 0), int(great_general))
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

def _cohort_snapshot(force, formation_ref):
    out = {}
    for cohort_id, cohort in force.get("cohort_ledger", {}).get("cohorts", {}).items():
        if not isinstance(cohort, dict):
            continue
        held = int(cohort.get("allocated_by_formation", {}).get(formation_ref, 0) or 0)
        if held > 0:
            out[str(cohort_id)] = {
                "held": held,
                "capability": copy.deepcopy(cohort.get("capability")),
                "service": copy.deepcopy(cohort.get("service")),
            }
    return out


def test_rank_guided_mobilization_permanently_expands_existing_state_army_without_minting_people(campaign):
    _raise_mobilization_targets(campaign)
    planner = planner_for(campaign)
    at = planner.read("state/meta.json")["time"]
    force_path = "state/forces/state-qin.json"
    formation_ref = "formation_qin_mou_bu_shock_army"
    formation_path = planner.owner_path(formation_ref)
    before_force = copy.deepcopy(planner.read(force_path))
    before_form = copy.deepcopy(planner.read(formation_path))
    before_reserve = _reserve_total(before_force)
    before_allocated = sum(int(v.get("personnel", 0)) for v in before_force["allocated_to_formations"].values())
    before_cohorts = _cohort_snapshot(before_force, formation_ref)

    result = planner._reinforce_state_field_army_for_mobilization(
        "cmdgrp.mou_bu.field_army", state_ref="state_qin", force_ref="force_state_qin", at=at,
    )

    after_force = planner.read(force_path)
    after_form = planner.read(formation_path)
    after_group = planner.read("state/cmd/command-groups/cmdgrp.mou_bu.field_army.json")
    after_person = planner.read(planner.owner_path("char_mou_bu"))
    moved = int(result["assigned"])
    assert moved > 0
    assert after_form["personnel"] == before_form["personnel"] + moved
    assert after_form["authorized_strength"] >= after_form["personnel"]
    assert _reserve_total(after_force) == before_reserve - moved
    after_allocated = sum(int(v.get("personnel", 0)) for v in after_force["allocated_to_formations"].values())
    assert after_allocated == before_allocated + moved
    assert int(after_force["headcount"]) == int(before_force["headcount"])
    assert not (set(after_form.get("composition", {})) & set(FORBIDDEN_PERMANENT_SUPPORT_ROLES))
    assert "levy" not in after_form.get("composition", {})
    assert int(after_group["organizational_state"]["current_recursive_strength"]) >= 40000
    assert int(after_group["organizational_state"]["authorized_strength"]) == int(after_group["organizational_state"]["current_recursive_strength"])
    assert int(after_person["command_assignment"]["current_command_span"]) == int(after_group["organizational_state"]["current_recursive_strength"])

    after_cohorts = _cohort_snapshot(after_force, formation_ref)
    for cohort_id, before in before_cohorts.items():
        assert cohort_id in after_cohorts
        assert after_cohorts[cohort_id]["held"] >= before["held"]
        assert after_cohorts[cohort_id]["capability"] == before["capability"]
        assert after_cohorts[cohort_id]["service"] == before["service"]


def test_nested_state_armies_reinforce_children_before_parent_without_touching_private_children(campaign):
    _raise_mobilization_targets(campaign)
    planner = planner_for(campaign)
    at = planner.read("state/meta.json")["time"]
    private_force_path = "state/forces/house_tou_household.json"
    private_before = copy.deepcopy(planner.read(private_force_path))

    result = planner._reinforce_state_field_army_for_mobilization(
        "cmdgrp.ouki.field_army", state_ref="state_qin", force_ref="force_state_qin", at=at,
    )

    tou = planner.read("state/cmd/command-groups/cmdgrp.tou.field_army.json")
    ouki = planner.read("state/cmd/command-groups/cmdgrp.ouki.field_army.json")
    assert int(result["assigned"]) > 0
    assert int(tou["organizational_state"]["current_recursive_strength"]) >= 40000
    assert int(ouki["organizational_state"]["current_recursive_strength"]) >= 60000
    assert planner.read(private_force_path) == private_before
    assert "cmdgrp.tou.field_army" in result["changed_command_group_refs"]
    assert "cmdgrp.ouki.field_army" in result["changed_command_group_refs"]


def test_state_world_arc_operation_mobilization_keeps_reinforced_strength_persistent(campaign):
    _raise_mobilization_targets(campaign)
    planner = planner_for(campaign)
    planner._reset()
    at = planner.read("state/meta.json")["time"]
    before_force = planner.read("state/forces/state-qin.json")
    before_reserve = _reserve_total(before_force)
    # Isolate fresh state mobilization from the checkpoint's already-active war
    # operations; active formations are correctly unavailable to a second order.
    op_index = planner.read("state/operations/index.json")
    for op_path in op_index.get("operations", {}).values():
        op = copy.deepcopy(planner.read(op_path))
        op["status"] = "completed"
        planner.put(op_path, op)

    evidence = planner._priority_operation_evidence(
        actor_ref="state_qin",
        action_ref="action_test_persistent_army_growth",
        arc_ref="arc_test_persistent_army_growth",
        goal="mobilize a major Qin field command against a hostile frontier",
        target_ref="loc_sanyou",
        at=at,
        force_refs=["force_state_qin"],
        kind="state_world_arc_operation",
    )
    assert evidence is not None
    assert evidence["kind"] == "exact_operation_created"
    reinforcement = evidence.get("standing_army_reinforcement")
    assert isinstance(reinforcement, dict) and int(reinforcement.get("assigned", 0)) > 0
    operation = planner.read(planner.owner_path(evidence["operation_ref"]))
    group_ref = operation.get("command_group_ref")
    assert isinstance(group_ref, str) and group_ref
    group = planner.read(f"state/cmd/command-groups/{group_ref}.json")
    current = int(group["organizational_state"]["current_recursive_strength"])
    assert current >= int(group["organizational_state"]["authorized_strength"])
    assert _reserve_total(planner.read("state/forces/state-qin.json")) < before_reserve


def test_ungrouped_general_command_can_reinforce_without_becoming_a_fake_support_or_levy_unit(campaign):
    _raise_mobilization_targets(campaign)
    planner = planner_for(campaign)
    at = planner.read("state/meta.json")["time"]
    formation_ref = "formation_wei_mobile_reserve"
    before = copy.deepcopy(planner.read(planner.owner_path(formation_ref)))
    assert before.get("commander_ref") == "char_gai_mou"
    result = planner._reinforce_state_independent_formation_for_mobilization(
        formation_ref, state_ref="state_wei", force_ref="force_state_wei", at=at,
    )
    after = planner.read(planner.owner_path(formation_ref))
    assert int(result["assigned"]) > 0
    assert int(after["personnel"]) >= 40000
    assert int(after["composition"].get("cavalry", 0)) >= int(before["composition"].get("cavalry", 0))
    assert int(after["composition"].get("line_infantry", 0)) > 0
    assert int(after["composition"].get("missile_crossbow", 0)) > 0
    assert set(after.get("composition", {})).isdisjoint(FORBIDDEN_PERMANENT_SUPPORT_ROLES)
    assert "levy" not in after.get("composition", {})
    assert "command_personnel" not in after.get("composition", {})
    assert after.get("commander_ref") == "char_gai_mou"
