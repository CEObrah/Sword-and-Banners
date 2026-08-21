from sword_runtime.warfare_depth import build_formation_command_structure
import json


def _read(root, path):
    return json.loads((root / path).read_text())


def test_formation_promotes_to_nested_army_with_commander_deputy_and_conserved_successors(campaign):
    from conftest import execute_production_internal

    parent_ref = "cmdgrp.tang_wei.field_army"
    formation_ref = "formation_qin_wei_unit_04"
    army_ref = "cmdgrp.feng_zhao.army"
    before_force = _read(campaign, "state/forces/state-qin.json")
    before_headcount = before_force["headcount"]
    before_form = _read(campaign, "state/formations/qin-wei-unit-04.json")
    old_commander = before_form["commander_ref"]
    old_deputy = before_form["deputy_ref"]
    old_personnel = before_form["personnel"]
    before_internal = list(before_form["embedded_person_refs"])

    result = execute_production_internal(campaign, "command_group_action", {
        "action": "promote_formation_to_army",
        "command_group_ref": parent_ref,
        "formation_ref": formation_ref,
        "subordinate_group_ref": army_ref,
        "display_name": "Feng Zhao Army",
    })

    result = dict(result.receipt.result)
    assert result["promoted_army_ref"] == army_ref
    parent = _read(campaign, "state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")
    assert any(row == {"kind": "nested_army", "ref": army_ref} for row in parent["units"])
    assert not any(row.get("ref") == formation_ref for row in parent["units"])

    army = _read(campaign, "state/cmd/command-groups/cmdgrp.feng_zhao.army.json")
    assert army["commander_ref"] == old_commander
    assert army["deputy_ref"] == old_deputy
    assert army["units"] == [{"kind": "formation", "ref": formation_ref}]

    after_form = _read(campaign, "state/formations/qin-wei-unit-04.json")
    assert after_form["higher_command_ref"] == army_ref
    assert after_form["personnel"] == old_personnel - 2
    assert after_form["commander_ref"] in before_internal
    assert after_form["deputy_ref"] in before_internal
    assert after_form["commander_ref"] != old_commander
    assert after_form["deputy_ref"] != old_deputy
    assert result["replacement_embedded_officer_refs"] == ()
    rules = _read(campaign, "game/data/mechanics/warfare-organization.json")
    assert "command_structure" not in after_form
    cadre = build_formation_command_structure(after_form, rules)["officer_cadre"]
    assert cadre["vacant_billets"]["1000_commander"] >= 1
    assert cadre["vacant_billets"]["500_commander"] >= 1
    # The two promoted successors are now external top command posts and keep
    # their durable embedded rank rather than being renamed to a billet.
    idx = _read(campaign, "state/index/owner-index.json")["owners"]
    for ref, billet in ((after_form["commander_ref"], "formation_commander"), (after_form["deputy_ref"], "formation_deputy")):
        route = idx[ref]
        path, frag = route.split("#/records/")
        person = _read(campaign, path)["records"][frag]
        assert person["military_rank"]["durable"] is True
        assert person["military_rank"]["grade"] in {"1000_commander", "500_commander", "100_commander"}
        assert person["command_assignment"]["billet"] == billet

    after_force = _read(campaign, "state/forces/state-qin.json")
    assert after_force["headcount"] == before_headcount
    assert after_force["allocated_to_formations"][formation_ref]["personnel"] == old_personnel - 2
