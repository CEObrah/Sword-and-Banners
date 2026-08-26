import json


def _read(root, path):
    return json.loads((root / path).read_text())


def _write(root, path, doc):
    (root / path).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def test_npc_review_can_attach_one_intact_parent_direct_nested_army_without_flattening(campaign):
    from types import SimpleNamespace
    from sword_runtime.production_planner import ProductionCampaignPlanner

    parent_ref = "cmdgrp.tang_wei.black_banner"
    child_ref = "cmdgrp.tang_wei.black_banner.wing_1"
    candidate_ref = "cmdgrp.tang_wei.black_banner.wing_2"
    child_path = f"state/cmd/command-groups/{child_ref}.json"
    parent_path = f"state/cmd/command-groups/{parent_ref}.json"
    candidate_path = f"state/cmd/command-groups/{candidate_ref}.json"

    child = _read(campaign, child_path)
    child["organizational_state"]["authorized_direct_unit_slots"] = 3
    child["organizational_state"]["authorized_strength"] = 4000
    _write(campaign, child_path, child)

    candidate_before = _read(campaign, candidate_path)
    candidate_units_before = [dict(row) for row in candidate_before["units"]]

    planner = ProductionCampaignPlanner(campaign); planner._reset()
    command = SimpleNamespace(actor_id=planner.INTERNAL_ACTOR, expected_revision=int(planner.read("state/meta.json")["revision"]), command_type="command_group_action", digest="armyorgnpc", semantic_digest="armyorgnpc")
    receipt = planner._dispatch_command_group_action(command, {
        "action": "review_organization",
        "command_group_ref": child_ref,
        "allow_auto_staff": True,
    })
    assert candidate_ref in receipt["auto_attached_unit_refs"]

    child_after = planner.read(child_path)
    parent_after = planner.read(parent_path)
    candidate_after = planner.read(candidate_path)
    assert {"kind": "nested_army", "ref": candidate_ref} in child_after["units"]
    assert candidate_ref not in [row["ref"] for row in parent_after["units"]]
    assert candidate_after["parent_command_group_ref"] == child_ref
    assert candidate_after["units"] == candidate_units_before
    assert "last_auto_attached_unit_refs" not in child_after["organizational_state"]


def test_player_commander_is_never_auto_staffed_even_when_requested(campaign):
    from types import SimpleNamespace
    from sword_runtime.production_planner import ProductionCampaignPlanner

    child_ref = "cmdgrp.tang_wei.high_guard"
    candidate_ref = "cmdgrp.tang_wei.red_lance"
    child_path = f"state/cmd/command-groups/{child_ref}.json"

    child = _read(campaign, child_path)
    child["commander_ref"] = "char_tang_wei"
    child["organizational_state"]["authorized_direct_unit_slots"] = len(child["units"]) + 1
    child["organizational_state"]["authorized_strength"] = int(child["organizational_state"]["current_recursive_strength"]) + 1000
    _write(campaign, child_path, child)

    before = list(_read(campaign, child_path)["units"])
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    command = SimpleNamespace(actor_id=planner.INTERNAL_ACTOR, expected_revision=int(planner.read("state/meta.json")["revision"]), command_type="command_group_action", digest="armyorgplayer", semantic_digest="armyorgplayer")
    receipt = planner._dispatch_command_group_action(command, {
        "action": "review_organization",
        "command_group_ref": child_ref,
        "allow_auto_staff": True,
    })
    after = planner.read(child_path)
    assert after["units"] == before
    assert receipt["auto_attached_unit_refs"] == ()
    assert any(row["ref"] == candidate_ref for row in receipt["available_attachment_candidates"])


def test_major_battle_damage_immediately_reviews_exact_npc_containing_army(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    formation_ref = "formation_house_ou_family_01"
    group_ref = "cmdgrp.house_ou_family.field_army"
    owner_index = _read(campaign, "state/index/owner-index.json")["owners"]
    formation_path = owner_index[formation_ref]
    formation = _read(campaign, formation_path)
    before = int(formation["personnel"])
    loss = max(1, (before * 20) // 100)
    formation["personnel"] = before - loss
    _write(campaign, formation_path, formation)

    planner = ProductionCampaignPlanner(campaign); planner._reset()
    at = str(planner._world_time())
    result = planner._trigger_post_battle_army_staff_reviews(
        {formation_ref: loss}, at=at, battle_ref="battle.test.major.damage"
    )

    assert result["reviewed_command_group_refs"] == [group_ref]
    assert result["evidence"][0]["casualty_basis_points"] >= 1500
    group = planner.read(f"state/cmd/command-groups/{group_ref}.json")
    assert "last_staffing_review_at" not in group["organizational_state"]
    routes = planner.read("state/cmd/army-staff-routes.json")
    assert "runtime" not in routes


def test_post_battle_staff_trigger_ignores_subthreshold_and_player_hierarchy(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    owner_index = _read(campaign, "state/index/owner-index.json")["owners"]
    npc_ref = "formation_house_ou_family_01"
    player_ref = "formation_red_lance_a"
    casualties = {}
    for ref, pct in ((npc_ref, 10), (player_ref, 25)):
        path = owner_index[ref]
        formation = _read(campaign, path)
        before = int(formation["personnel"])
        loss = max(1, (before * pct) // 100)
        formation["personnel"] = before - loss
        _write(campaign, path, formation)
        casualties[ref] = loss

    planner = ProductionCampaignPlanner(campaign); planner._reset()
    result = planner._trigger_post_battle_army_staff_reviews(
        casualties, at=str(planner._world_time()), battle_ref="battle.test.no.auto.player"
    )
    assert result["reviewed_command_group_refs"] == []


def test_generic_detach_promotes_nested_army_to_top_level_without_resetting_units_or_training(campaign):
    from types import SimpleNamespace
    from sword_runtime.production_planner import ProductionCampaignPlanner

    parent_ref = "cmdgrp.ouki.field_army"
    child_ref = "cmdgrp.tou.field_army"
    parent_path = f"state/cmd/command-groups/{parent_ref}.json"
    child_path = f"state/cmd/command-groups/{child_ref}.json"

    parent_before = _read(campaign, parent_path)
    child_before = _read(campaign, child_path)
    child_units_before = [dict(row) for row in child_before["units"]]
    owner_index = _read(campaign, "state/index/owner-index.json")["owners"]
    formation_snapshots = {
        row["ref"]: _read(campaign, owner_index[row["ref"]])
        for row in child_units_before
        if row.get("kind") == "formation"
    }
    qin_force_before = _read(campaign, "state/forces/state-qin.json")

    planner = ProductionCampaignPlanner(campaign); planner._reset()
    command = SimpleNamespace(
        actor_id=planner.INTERNAL_ACTOR,
        expected_revision=int(planner.read("state/meta.json")["revision"]),
        command_type="command_group_action",
        digest="detach_nested_army",
        semantic_digest="detach_nested_army",
    )
    planner._dispatch_command_group_action(command, {
        "action": "detach_command_group",
        "command_group_ref": parent_ref,
        "subordinate_group_ref": child_ref,
    })

    parent_after = planner.read(parent_path)
    child_after = planner.read(child_path)
    assert child_after["parent_command_group_ref"] is None
    assert child_after["units"] == child_units_before
    assert not any(
        isinstance(row, dict) and row.get("kind") == "nested_army" and row.get("ref") == child_ref
        for row in parent_after["units"]
    )
    for formation_ref, before in formation_snapshots.items():
        after = planner.read(owner_index[formation_ref])
        assert after["personnel"] == before["personnel"]
        assert after.get("training_progress") == before.get("training_progress")
        assert after.get("experience") == before.get("experience")
        assert after.get("cohort_composition") == before.get("cohort_composition")
    assert planner.read("state/forces/state-qin.json") == qin_force_before
