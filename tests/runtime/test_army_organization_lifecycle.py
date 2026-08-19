import json


def _read(root, path):
    return json.loads((root / path).read_text())


def _write(root, path, doc):
    (root / path).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")


def test_npc_review_can_attach_one_intact_parent_direct_nested_army_without_flattening(campaign):
    from types import SimpleNamespace
    from sword_runtime.production_planner import ProductionCampaignPlanner

    parent_ref = "cmdgrp.sword_manor.field"
    child_ref = "cmdgrp.sword_manor.senior"
    candidate_ref = "cmdgrp.sword_manor.general"
    child_path = "state/cmd/command-groups/cmdgrp.sword_manor.senior.json"
    parent_path = "state/cmd/command-groups/cmdgrp.sword_manor.field.json"
    candidate_path = "state/cmd/command-groups/cmdgrp.sword_manor.general.json"

    child = _read(campaign, child_path)
    child["organizational_state"]["authorized_direct_unit_slots"] = 2
    child["organizational_state"]["authorized_strength"] = 6000
    _write(campaign, child_path, child)

    candidate_before = _read(campaign, candidate_path)
    candidate_units_before = [dict(row) for row in candidate_before["units"]]

    planner = ProductionCampaignPlanner(campaign); planner._reset()
    command = SimpleNamespace(actor_id=planner.INTERNAL_ACTOR, expected_revision=int(planner.read("state/meta.json")["revision"]), command_type="command_group_action", digest="armyorgnpc")
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
    assert child_after["organizational_state"]["last_auto_attached_unit_refs"] == [candidate_ref]


def test_player_commander_is_never_auto_staffed_even_when_requested(campaign):
    from types import SimpleNamespace
    from sword_runtime.production_planner import ProductionCampaignPlanner

    # Make the player personal-force child eligible for a real parent direct Unit
    # using an exact same-force sibling in this disposable campaign copy.
    child_ref = "cmdgrp.tang_wei.personal_force"
    parent_ref = "cmdgrp.tang_wei.field_army"
    child_path = "state/cmd/command-groups/cmdgrp.tang_wei.personal_force.json"
    parent_path = "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json"
    owner_index = _read(campaign, "state/index/owner-index.json")["owners"]

    child = _read(campaign, child_path)
    child["organizational_state"]["authorized_direct_unit_slots"] = max(2, int(child["organizational_state"].get("direct_unit_count", 1)) + 1)
    child["organizational_state"]["authorized_strength"] = max(10000, int(child["organizational_state"].get("current_recursive_strength", 0)) + 5000)
    _write(campaign, child_path, child)

    parent = _read(campaign, parent_path)
    sibling_ref = next(row["ref"] for row in parent["units"] if row["kind"] == "formation")
    sibling_path = owner_index[sibling_ref]
    sibling = _read(campaign, sibling_path)

    # Align only the test copy's force/location with the player's child anchor so a
    # candidate definitely exists; this is testing agency, not baseline OOB truth.
    first_child_unit = child["units"][0]
    if first_child_unit["kind"] == "nested_army":
        nested = _read(campaign, f"state/cmd/command-groups/{first_child_unit['ref']}.json")
        anchor_ref = next(row["ref"] for row in nested["units"] if row["kind"] == "formation")
    else:
        anchor_ref = first_child_unit["ref"]
    anchor = _read(campaign, owner_index[anchor_ref])
    sibling["owner_force_ref"] = anchor["owner_force_ref"]
    sibling["location_ref"] = child["location"]
    _write(campaign, sibling_path, sibling)

    before = list(_read(campaign, child_path)["units"])
    planner = ProductionCampaignPlanner(campaign); planner._reset()
    command = SimpleNamespace(actor_id=planner.INTERNAL_ACTOR, expected_revision=int(planner.read("state/meta.json")["revision"]), command_type="command_group_action", digest="armyorgplayer")
    receipt = planner._dispatch_command_group_action(command, {
        "action": "review_organization",
        "command_group_ref": child_ref,
        "allow_auto_staff": True,
    })
    after = planner.read(child_path)
    assert after["units"] == before
    assert receipt["auto_attached_unit_refs"] == ()
    assert any(row["ref"] == sibling_ref for row in receipt["available_attachment_candidates"])


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
    assert group["organizational_state"]["last_staffing_review_at"] == at
    routes = planner.read("state/cmd/army-staff-routes.json")
    assert routes["runtime"]["last_immediate_battle_review"]["battle_ref"] == "battle.test.major.damage"


def test_post_battle_staff_trigger_ignores_subthreshold_and_player_hierarchy(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner

    owner_index = _read(campaign, "state/index/owner-index.json")["owners"]
    npc_ref = "formation_house_ou_family_01"
    player_ref = "formation_qin_wei_unit_01"
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
